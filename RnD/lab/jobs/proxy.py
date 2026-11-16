"""The browser-proxy builder (v26.3.0 p5-03): an ffmpeg thread per recording, its live status dict and its status files.

`proxy_status(rec_id)` reads the live `_building` dict, else the finished mp4, else a leftover error file.
`start_proxy(rec)` starts the builder thread unless one is running or the proxy exists. The proxy of a recording is
a concat of all its chapters, so proxy time equals recording time. Files live under `LAB_DIR/proxies/` (the
recordings `LAB_DIR`, read at call time)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, Any

from lab.store import recordings as store_recordings
from lab.store import util

if TYPE_CHECKING:
    from pathlib import Path

PROXY_WIDTH = 960


def _log(msg: str) -> None:
    print(f"[recordings] {msg}", file=sys.stderr, flush=True)


def proxies_dir() -> Path:
    path: Path = store_recordings.LAB_DIR / "proxies"
    return path


def proxy_path(rec_id: str) -> Path:
    return proxies_dir() / f"{rec_id}.mp4"


# --------------------------------------------------------------------------
# Proxy
# --------------------------------------------------------------------------

_proxy_lock = threading.Lock()
_building: dict[str, dict[str, Any]] = {}  # rec_id -> live {"status","progress","error"}


def proxy_status(rec_id: str) -> dict[str, Any]:
    with _proxy_lock:
        live = _building.get(rec_id)
        if live is not None:
            return dict(live)
    if proxy_path(rec_id).exists():
        return {"status": "ready", "progress": 1.0, "error": None}
    # A leftover status file with no live thread: report a failed build's
    # error, but treat an interrupted one (service restart) as missing.
    f = proxies_dir() / f"{rec_id}.json"
    if f.exists():
        try:
            doc = json.loads(f.read_text())
            if doc.get("status") == "error":
                return {"status": "error", "progress": 0.0, "error": doc.get("error")}
        except (OSError, ValueError):
            pass
    return {"status": "missing", "progress": 0.0, "error": None}


def _set_proxy(rec_id: str, **fields: Any) -> None:
    with _proxy_lock:
        st = _building.setdefault(rec_id, {"status": "building", "progress": 0.0, "error": None})
        st.update(fields)
        snapshot = dict(st)
    util._atomic_write_json(proxies_dir() / f"{rec_id}.json", snapshot)


def start_proxy(rec: dict[str, Any]) -> dict[str, Any]:
    """Start a proxy build unless one is running or already finished."""
    rec_id = rec["id"]
    with _proxy_lock:
        if rec_id in _building and _building[rec_id]["status"] == "building":
            return dict(_building[rec_id])
    if proxy_path(rec_id).exists():
        return proxy_status(rec_id)
    _set_proxy(rec_id, status="building", progress=0.0, error=None)
    threading.Thread(target=_build_proxy, args=(rec,), name=f"proxy-{rec_id}", daemon=True).start()
    return proxy_status(rec_id)


def _build_proxy(rec: dict[str, Any]) -> None:
    rec_id = rec["id"]
    out = proxy_path(rec_id)
    part = out.with_name(out.name + ".part")
    concat = proxies_dir() / f"{rec_id}.concat.txt"
    try:
        # concat demuxer quoting: single quotes, with ' written as '\''.
        concat.write_text("".join("file '{}'\n".format(ch["file"].replace("'", "'\\''")) for ch in rec["chapters"]))
        gop = max(1, round(rec["fps"]))
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            # Video + first audio only: GoPro files carry telemetry/timecode
            # data streams that the mp4 muxer can't (and needn't) copy.
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            f"scale={PROXY_WIDTH}:-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-g",
            str(gop),
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            "-progress",
            "pipe:1",
            str(part),
        ]
        _log(f"proxy {rec_id}: building ({rec['duration']:.0f}s of video)")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stderr_tail: list[str] = []
        # Drain stderr on a thread so a chatty ffmpeg can't block on a full pipe.
        threading.Thread(target=lambda: stderr_tail.extend(proc.stderr.readlines()[-20:]), daemon=True).start()  # type: ignore[union-attr]
        total_us = rec["duration"] * 1_000_000
        for line in proc.stdout:  # type: ignore[union-attr]
            key, _, val = line.strip().partition("=")
            # (despite its name, ffmpeg's out_time_ms is in microseconds)
            if key == "out_time_ms" and val.lstrip("-").isdigit():
                _set_proxy(rec_id, progress=min(0.999, max(0.0, int(val) / total_us)))
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed: " + "".join(stderr_tail).strip()[-500:])
        os.replace(part, out)
        _set_proxy(rec_id, status="ready", progress=1.0, error=None)
        _log(f"proxy {rec_id}: ready")
    except Exception as exc:  # surfaced to the UI via status
        _log(f"proxy {rec_id}: FAILED: {exc}")
        part.unlink(missing_ok=True)
        _set_proxy(rec_id, status="error", progress=0.0, error=str(exc))
    finally:
        concat.unlink(missing_ok=True)
        with _proxy_lock:
            final = _building.pop(rec_id, None)
        if final is not None:
            util._atomic_write_json(proxies_dir() / f"{rec_id}.json", final)
