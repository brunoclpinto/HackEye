"""Media discovery, GoPro chapter grouping and the browser-proxy builder.

GoPro splits a long take into ~4 GB chapters (GOPR4927, GP014927, GP024927).
The Lab treats them as one continuous timeline: recording time `t` is the
sum of the preceding chapters' durations plus the time inside the chapter,
and the proxy is a concat of all chapters so proxy time equals recording
time. Chapter duration is `frames / fps` (not the container duration) so the
analysis reader can address a frame by index and land on the same `t` the
proxy plays at.

Metadata comes from cv2.VideoCapture properties (header only, no decoding)
and is cached per (path, mtime, size) because listing runs on every page load.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2

MEDIA_DIR = Path(os.environ.get("HACKEYE_MEDIA_DIR", "/media"))
LAB_DIR = Path(os.environ.get("HACKEYE_LAB_DIR", "/debug/lab"))
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}

_GOPR = re.compile(r"^GOPR(\d{4})$", re.IGNORECASE)
_GP = re.compile(r"^GP(\d{2})(\d{4})$", re.IGNORECASE)

PROXY_WIDTH = 960


def _log(msg: str) -> None:
    print(f"[recordings] {msg}", file=sys.stderr, flush=True)


def proxies_dir() -> Path:
    return LAB_DIR / "proxies"


def proxy_path(rec_id: str) -> Path:
    return proxies_dir() / f"{rec_id}.mp4"


def _atomic_write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc))
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

@dataclass
class _VideoInfo:
    width: int
    height: int
    fps: float
    frames: int


_info_cache: dict[tuple[str, float, int], _VideoInfo] = {}


def _probe(path: Path) -> _VideoInfo | None:
    st = path.stat()
    key = (str(path), st.st_mtime, st.st_size)
    if key in _info_cache:
        return _info_cache[key]
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return None
        info = _VideoInfo(
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=float(cap.get(cv2.CAP_PROP_FPS)),
            frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        )
    finally:
        cap.release()
    if info.fps <= 0 or info.frames <= 0:
        return None
    _info_cache[key] = info
    return info


def _group_key(path: Path) -> tuple[str, int]:
    """(recording id, chapter number starting at 1) for a media file."""
    m = _GOPR.match(path.stem)
    if m:
        return m.group(1), 1
    m = _GP.match(path.stem)
    if m:
        return m.group(2), int(m.group(1)) + 1
    return path.stem, 1


def scan_recordings() -> list[dict]:
    """Recordings (without proxy state) found in MEDIA_DIR, sorted by id."""
    groups: dict[str, list[tuple[int, Path]]] = {}
    if MEDIA_DIR.is_dir():
        for p in MEDIA_DIR.iterdir():
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                rec_id, chapter = _group_key(p)
                groups.setdefault(rec_id, []).append((chapter, p))

    recs: list[dict] = []
    for rec_id, items in sorted(groups.items()):
        items.sort()
        chapters: list[dict] = []
        infos: list[_VideoInfo] = []
        t = 0.0
        for _, p in items:
            info = _probe(p)
            if info is None:
                _log(f"skipping unreadable file {p}")
                continue
            dur = info.frames / info.fps
            chapters.append({"file": str(p), "start": round(t, 6), "duration": round(dur, 6), "frames": info.frames})
            infos.append(info)
            t += dur
        if not chapters:
            continue
        first = infos[0]
        is_gopro = bool(_GOPR.match(Path(chapters[0]["file"]).stem))
        recs.append({
            "id": rec_id,
            "name": f"GoPro {rec_id}" if is_gopro else rec_id,
            "chapters": chapters,
            "duration": round(t, 3),
            "width": first.width, "height": first.height, "fps": round(first.fps, 3),
        })
    return recs


def list_recordings() -> list[dict]:
    recs = scan_recordings()
    for rec in recs:
        rec["proxy"] = proxy_status(rec["id"])
    return recs


def get_recording(rec_id: str) -> dict | None:
    for rec in scan_recordings():
        if rec["id"] == rec_id:
            rec["proxy"] = proxy_status(rec_id)
            return rec
    return None


def recording_frame_at(rec: dict, t: float) -> tuple[str, float]:
    """Map recording time `t` to (chapter file, time inside that chapter).
    Times past the end clamp to the last chapter's end."""
    chapters = rec["chapters"]
    for ch in chapters:
        if t < ch["start"] + ch["duration"]:
            return ch["file"], max(0.0, t - ch["start"])
    last = chapters[-1]
    return last["file"], last["duration"]


# --------------------------------------------------------------------------
# Proxy
# --------------------------------------------------------------------------

_proxy_lock = threading.Lock()
_building: dict[str, dict] = {}  # rec_id -> live {"status","progress","error"}


def proxy_status(rec_id: str) -> dict:
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


def _set_proxy(rec_id: str, **fields) -> None:
    with _proxy_lock:
        st = _building.setdefault(rec_id, {"status": "building", "progress": 0.0, "error": None})
        st.update(fields)
        snapshot = dict(st)
    _atomic_write_json(proxies_dir() / f"{rec_id}.json", snapshot)


def start_proxy(rec: dict) -> dict:
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


def _build_proxy(rec: dict) -> None:
    rec_id = rec["id"]
    out = proxy_path(rec_id)
    part = out.with_name(out.name + ".part")
    concat = proxies_dir() / f"{rec_id}.concat.txt"
    try:
        # concat demuxer quoting: single quotes, with ' written as '\''.
        concat.write_text("".join(
            "file '{}'\n".format(ch["file"].replace("'", "'\\''")) for ch in rec["chapters"]
        ))
        gop = max(1, round(rec["fps"]))
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "concat", "-safe", "0", "-i", str(concat),
            # Video + first audio only: GoPro files carry telemetry/timecode
            # data streams that the mp4 muxer can't (and needn't) copy.
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", f"scale={PROXY_WIDTH}:-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-g", str(gop),
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart", "-f", "mp4",
            "-progress", "pipe:1", str(part),
        ]
        _log(f"proxy {rec_id}: building ({rec['duration']:.0f}s of video)")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stderr_tail: list[str] = []
        # Drain stderr on a thread so a chatty ffmpeg can't block on a full pipe.
        threading.Thread(target=lambda: stderr_tail.extend(proc.stderr.readlines()[-20:]), daemon=True).start()
        total_us = rec["duration"] * 1_000_000
        for line in proc.stdout:
            key, _, val = line.strip().partition("=")
            # (despite its name, ffmpeg's out_time_ms is in microseconds)
            if key == "out_time_ms" and val.lstrip("-").isdigit():
                _set_proxy(rec_id, progress=min(0.999, max(0.0, int(val) / total_us)))
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed: " + "".join(stderr_tail).strip()[-500:])
        os.replace(part, out)
        _set_proxy(rec_id, status="ready", progress=1.0, error=None)
        _log(f"proxy {rec_id}: ready")
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI via status
        _log(f"proxy {rec_id}: FAILED: {exc}")
        part.unlink(missing_ok=True)
        _set_proxy(rec_id, status="error", progress=0.0, error=str(exc))
    finally:
        concat.unlink(missing_ok=True)
        with _proxy_lock:
            final = _building.pop(rec_id, None)
        if final is not None:
            _atomic_write_json(proxies_dir() / f"{rec_id}.json", final)


# --------------------------------------------------------------------------
# Per-recording settings (§4)
# --------------------------------------------------------------------------

def _settings_path(rec_id: str) -> Path:
    return LAB_DIR / "recordings" / f"{rec_id}.json"


def get_settings(rec_id: str, default_mount: str) -> dict:
    """Stored settings, or the defaults when nothing was saved."""
    defaults = {"mount": default_mount, "hfovDeg": None, "corridor": None}
    try:
        stored = json.loads(_settings_path(rec_id).read_text())
    except (OSError, ValueError):
        return defaults
    return {**defaults, **{k: stored[k] for k in defaults if k in stored}}


def save_settings(rec_id: str, settings: dict) -> None:
    _atomic_write_json(_settings_path(rec_id), settings)
