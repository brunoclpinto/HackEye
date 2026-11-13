"""GPMF telemetry of a GoPro recording: ffmpeg extraction, KLV parsing, time stamping, concat and the npz cache."""

from __future__ import annotations

import json
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from collections.abc import Iterator

_FMT = {"b": "b", "B": "B", "s": "h", "S": "H", "l": "i", "L": "I", "j": "q", "J": "Q", "f": "f", "d": "d"}
_STREAMS = ("GYRO", "ACCL", "GPS5", "SHUT", "ISOG")


# ----------------------------------------------------------------------------------------------------
# GPMF parsing
# ----------------------------------------------------------------------------------------------------


def _klv(buf: bytes) -> Iterator[tuple[str, str | None, int, int, bytes]]:
    """Yield (key, type char or None for nested, struct size, repeat, body) of one level of KLV entries."""
    i, n = 0, len(buf)
    while i + 8 <= n:
        key = buf[i : i + 4].decode("latin1")
        typ, size, rep = buf[i + 4], buf[i + 5], struct.unpack(">H", buf[i + 6 : i + 8])[0]
        ln = size * rep
        yield key, (chr(typ) if typ else None), size, rep, buf[i + 8 : i + 8 + ln]
        i += 8 + ((ln + 3) & ~3)


def _numbers(typ: str, size: int, rep: int, body: bytes) -> npt.NDArray[np.float64] | None:
    fmt = _FMT.get(typ)
    if fmt is None or size == 0 or rep == 0:
        return None
    w = struct.calcsize(fmt)
    cnt = size // w
    if cnt == 0 or len(body) < rep * size:
        return None
    return np.frombuffer(body[: rep * size], dtype=">" + fmt).astype(float).reshape(rep, cnt)


def parse_payload(buf: bytes) -> dict[str, dict[str, Any]]:
    """One DEVC payload -> {stream key: {"data": (rep, ch) scaled, "fix": int, "dop": float, "utc": str}} (the first device)."""  # noqa: E501
    out: dict[str, dict[str, Any]] = {}

    def strm(b: bytes) -> None:
        scal = fix = dop = utc = None
        data: dict[str, npt.NDArray[np.float64]] = {}
        for key, typ, size, rep, body in _klv(b):
            if typ is None:
                continue
            if key == "SCAL":
                a = _numbers(typ, size, rep, body)
                scal = None if a is None else a.reshape(-1)
            elif key == "GPSF":
                fix = int(_numbers(typ, size, rep, body)[0, 0])  # type: ignore[index]
            elif key == "GPSP":
                dop = float(_numbers(typ, size, rep, body)[0, 0]) / 100.0  # type: ignore[index]
            elif key == "GPSU":
                utc = body.rstrip(b"\0").decode("latin1")
            elif key in _STREAMS:
                a = _numbers(typ, size, rep, body)
                if a is not None:
                    data[key] = a
        for key, a in data.items():
            if scal is not None and len(scal) in (1, a.shape[1]):
                a = a / scal
            out[key] = {"data": a, "fix": fix, "dop": dop, "utc": utc}

    def walk(b: bytes) -> None:
        for key, typ, _size, _rep, body in _klv(b):
            if typ is None:
                if key == "STRM":
                    strm(body)
                else:
                    walk(body)

    walk(buf)
    return out


def split_payloads(raw: bytes) -> list[bytes]:
    """The top-level DEVC entries of the raw stream copy (one per packet)."""
    out, i = [], 0
    while i + 8 <= len(raw):
        ln = raw[i + 5] * struct.unpack(">H", raw[i + 6 : i + 8])[0]
        if raw[i : i + 4] != b"DEVC":
            break
        out.append(raw[i : i + 8 + ln])
        i += 8 + ((ln + 3) & ~3)
    return out


def _gpmd_stream(media_path: str) -> tuple[int, list[tuple[float, float]]] | None:
    """(stream index, [(pts, duration)] of its packets) or None."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_tag_string",
                "-of",
                "json",
                str(media_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        idx = next(
            (
                s["index"]
                for s in json.loads(r.stdout or "{}").get("streams", [])
                if s.get("codec_tag_string") == "gpmd"
            ),
            None,
        )
        if idx is None:
            return None
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                str(idx),
                "-show_entries",
                "packet=pts_time,duration_time",
                "-of",
                "csv=p=0",
                str(media_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        pk = []
        for line in r.stdout.splitlines():
            a = line.split(",")
            if len(a) >= 2 and a[0] and a[1]:
                pk.append((float(a[0]), float(a[1])))
        return idx, pk
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _utc_epoch(s: str | None) -> float:
    """GPSU 'yymmddhhmmss.sss' -> epoch seconds (nan when absent)."""
    if not s or len(s) < 12:
        return float("nan")
    try:
        import calendar

        yy, mo, dd, hh, mi = int(s[0:2]), int(s[2:4]), int(s[4:6]), int(s[6:8]), int(s[8:10])
        return calendar.timegm((2000 + yy, mo, dd, hh, mi, 0)) + float(s[10:])
    except ValueError:
        return float("nan")


def build(payloads: list[bytes], packets: list[tuple[float, float]]) -> dict[str, npt.NDArray[np.float64]]:
    """Time-stamped arrays from the payloads (payload i spans packets[i])."""
    acc: dict[str, list[Any]] = {k: [] for k in ("gyro", "accl", "gps", "shut", "isog")}
    tt: dict[str, list[Any]] = {k: [] for k in acc}
    gps_fix: list[Any]
    gps_dop: list[Any]
    gps_utc: list[Any]
    gps_fix, gps_dop, gps_utc = [], [], []
    for p, (pts, dur) in zip(payloads, packets):  # noqa: B905
        for key, v in parse_payload(p).items():
            name = {"GYRO": "gyro", "ACCL": "accl", "GPS5": "gps", "SHUT": "shut", "ISOG": "isog"}[key]
            a = v["data"]
            n = len(a)
            tt[name].append(pts + dur * (np.arange(n) + 0.5) / n)
            acc[name].append(a)
            if name == "gps":
                gps_fix.append(np.full(n, -1 if v["fix"] is None else v["fix"]))
                gps_dop.append(np.full(n, 9999.0 if v["dop"] is None else v["dop"]))
                gps_utc.append(np.full(n, _utc_epoch(v["utc"])))
    out: dict[str, npt.NDArray[np.float64]] = {}
    for name in acc:  # noqa: PLC0206
        if acc[name]:
            out[name] = np.concatenate(acc[name])
            out[name + "_t"] = np.concatenate(tt[name])
    if gps_fix:
        out["gps_fix"], out["gps_dop"], out["gps_utc"] = (
            np.concatenate(gps_fix),
            np.concatenate(gps_dop),
            np.concatenate(gps_utc),
        )
    for k in ("shut", "isog"):  # per-frame scalars: keep one column
        if k in out and out[k].ndim == 2:
            out[k] = out[k][:, 0]
    return out


def extract(media_path: str) -> dict[str, npt.NDArray[np.float64]] | None:
    """The telemetry of one media file, or None when it has no GPMF stream (or ffmpeg is missing)."""
    found = _gpmd_stream(str(media_path))
    if found is None or not found[1]:
        return None
    idx, packets = found
    with tempfile.TemporaryDirectory() as td:
        raw_path = Path(td) / "gpmd.bin"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(media_path),
                    "-map",
                    f"0:{idx}",
                    "-codec",
                    "copy",
                    "-f",
                    "rawvideo",
                    str(raw_path),
                ],
                check=True,
                capture_output=True,
                timeout=300,
            )
            raw = raw_path.read_bytes()
        except (OSError, subprocess.SubprocessError):
            return None
    payloads = split_payloads(raw)
    if not payloads:
        return None
    n = min(len(payloads), len(packets))
    out = build(payloads[:n], packets[:n])
    return out if "gyro" in out and "accl" in out else None


def hilights(media_path: str) -> list[float]:
    """HiLight tags (udta ``HMMT``: u32 count, then count x u32 milliseconds), seconds. Empty when none."""
    try:
        with open(media_path, "rb") as f:
            size = Path(media_path).stat().st_size

            def atoms(off: int, end: int, path: str) -> list[float] | None:
                while off + 8 <= end:
                    f.seek(off)
                    size_, typ = struct.unpack(">I4s", f.read(8))
                    hdr = 8
                    if size_ == 1:
                        size_, hdr = struct.unpack(">Q", f.read(8))[0], 16
                    elif size_ == 0:
                        size_ = end - off
                    typ = typ.decode("latin1")
                    if size_ < hdr:
                        return None
                    if typ in ("moov", "udta") and path in ("", "moov"):
                        r = atoms(off + hdr, off + size_, "moov" if typ == "moov" else "udta")
                        if r is not None:
                            return r
                    elif typ == "HMMT" and path == "udta":
                        f.seek(off + hdr)
                        body = f.read(size_ - hdr)
                        cnt = struct.unpack(">I", body[:4])[0] if len(body) >= 4 else 0
                        cnt = min(cnt, (len(body) - 4) // 4)
                        return [struct.unpack(">I", body[4 + 4 * k : 8 + 4 * k])[0] / 1000.0 for k in range(cnt)]
                    off += size_
                return None

            return atoms(0, size, "") or []
    except (OSError, struct.error):
        return []


def concat(parts: list[tuple[float, dict[str, npt.NDArray[np.float64]]]]) -> dict[str, npt.NDArray[np.float64]] | None:
    """Join chapters: (start offset s, extract() result) -> one dict on the recording's timeline."""
    parts = [(o, d) for o, d in parts if d]
    if not parts:
        return None
    out: dict[str, npt.NDArray[np.float64]] = {}
    for k in parts[0][1]:
        if k.endswith("_t"):
            out[k] = np.concatenate([d[k] + o for o, d in parts if k in d])
        else:
            out[k] = np.concatenate([d[k] for o, d in parts if k in d])
    return out


def save(path: str | Path, s: dict[str, npt.NDArray[np.float64]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez_compressed(tmp, **s)  # type: ignore[arg-type]
    tmp.replace(p)


def load(path: str | Path) -> dict[str, npt.NDArray[np.float64]] | None:
    try:
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    except (OSError, ValueError):
        return None
