"""Recordings of the Lab: discovery in MEDIA_DIR, GoPro chapter grouping, per-recording settings, sensor cache path.

Moved from lab/recordings.py (the proxy builder stays there until p5-03). `LAB_DIR` here is the recordings module's
own global (`recordings.LAB_DIR` forwards to it); it is independent of `lab.store.runs.LAB_DIR` and
`lab.features.reviews.LAB_DIR`.

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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import profiles
from lab.store.util import _atomic_write_json

MEDIA_DIR = Path(os.environ.get("HACKEYE_MEDIA_DIR", "/media"))
LAB_DIR = Path(os.environ.get("HACKEYE_LAB_DIR", "/debug/lab"))
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}

_GOPR = re.compile(r"^GOPR(\d{4})$", re.IGNORECASE)
_GP = re.compile(r"^GP(\d{2})(\d{4})$", re.IGNORECASE)


def _log(msg: str) -> None:
    print(f"[recordings] {msg}", file=sys.stderr, flush=True)


def sensors_path(rec_id: str) -> Path:
    return LAB_DIR / "sensors" / f"{rec_id}.npz"


def sensors_for(rec_id: str) -> dict[str, Any] | None:
    """v26.2.11: the device telemetry of a recording (GoPro GPMF: gyro, accelerometer, GPS, exposure;
    ``src/sensors.py``) on the recording's time line, cached in ``LAB_DIR/sensors/<recId>.npz`` (kept across version
    wipes like the proxies; the cache records the chapter files' size / mtime and is rebuilt when they change). None for
    a recording without telemetry (an empty marker is cached too) or an unknown id."""
    rec = get_recording(rec_id)
    if rec is None:
        return None
    try:
        import sensors
    except ImportError:
        return None
    key = ";".join(
        f"{c['file']}|{Path(c['file']).stat().st_size}|{int(Path(c['file']).stat().st_mtime)}" for c in rec["chapters"]
    )
    path = sensors_path(rec_id)
    cached = sensors.load(path)
    if cached is not None and str(cached.get("_src", "")) == key:
        return None if "gyro" not in cached else {k: v for k, v in cached.items() if k != "_src"}
    parts = [(float(c["start"]), sensors.extract(c["file"])) for c in rec["chapters"]]
    got: dict[str, Any] | None = sensors.concat(parts)
    sensors.save(path, {**(got or {}), "_src": np.array(key)})
    return got


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


def scan_recordings() -> list[dict[str, Any]]:
    """Recordings (without proxy state) found in MEDIA_DIR, sorted by id."""
    groups: dict[str, list[tuple[int, Path]]] = {}
    if MEDIA_DIR.is_dir():
        for p in MEDIA_DIR.iterdir():
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                rec_id, chapter = _group_key(p)
                groups.setdefault(rec_id, []).append((chapter, p))

    recs: list[dict[str, Any]] = []
    for rec_id, items in sorted(groups.items()):
        items.sort()
        chapters: list[dict[str, Any]] = []
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
        recs.append(
            {
                "id": rec_id,
                "name": f"GoPro {rec_id}" if is_gopro else rec_id,
                "chapters": chapters,
                "duration": round(t, 3),
                "width": first.width,
                "height": first.height,
                "fps": round(first.fps, 3),
                "inputSizes": _input_sizes(first.width, first.height),
                "inputSizesPortrait": _input_sizes(first.width, first.height, "portrait"),
                "nameHints": name_hints(rec_id),
            }
        )
    return recs


_NAME = re.compile(r"^([A-Za-z]+)-(left|center|right)-\d+$", re.IGNORECASE)


def name_hints(rec_id: str) -> dict[str, str]:
    """Body location and camera side encoded in a recording name ``<Location>-<side>-<nnnn>`` ({} when it has none)."""
    m = _NAME.match(rec_id)
    return {"cameraLocation": m.group(1).lower(), "cameraSide": m.group(2).lower()} if m else {}


def _input_sizes(width: int, height: int, orientation: str = "landscape") -> dict[str, list[int]]:
    """Model input (w, h) per offered resolution of the full frame (landscape) or the portrait window; options that
    would upscale are omitted."""
    sizes: dict[str, list[int]] = {}
    for n in profiles.SHORT_SIDE_OPTIONS:
        try:
            spec = profiles.window_spec(width, height, n, orientation)
        except ValueError:
            continue
        sizes[f"{n}p"] = [spec.dst_w, spec.dst_h]
    return sizes


def _proxy_status(rec_id: str) -> dict[str, Any]:
    """The proxy state of a recording; the proxy builder lives in the flat `lab.recordings` (lab.jobs from p5-03)."""
    from lab import recordings as flat

    status: dict[str, Any] = flat.proxy_status(rec_id)
    return status


def list_recordings() -> list[dict[str, Any]]:
    recs = scan_recordings()
    for rec in recs:
        rec["proxy"] = _proxy_status(rec["id"])
    return recs


def get_recording(rec_id: str) -> dict[str, Any] | None:
    for rec in scan_recordings():
        if rec["id"] == rec_id:
            rec["proxy"] = _proxy_status(rec_id)
            return rec
    return None


def recording_frame_at(rec: dict[str, Any], t: float) -> tuple[str, float]:
    """Map recording time `t` to (chapter file, time inside that chapter).
    Times past the end clamp to the last chapter's end."""
    chapters = rec["chapters"]
    for ch in chapters:
        if t < ch["start"] + ch["duration"]:
            return ch["file"], max(0.0, t - ch["start"])
    last = chapters[-1]
    return last["file"], last["duration"]


# --------------------------------------------------------------------------
# Per-recording settings (§4)
# --------------------------------------------------------------------------


def _settings_path(rec_id: str) -> Path:
    return LAB_DIR / "recordings" / f"{rec_id}.json"


def _body_locations() -> list[str]:
    try:
        import collision

        return list((collision.load_config().get("body") or {}).get("cameraLocations", {}))
    except Exception:  # no config: no location default
        return []


def _distance_defaults() -> tuple[str, bool]:
    """The object distance and horizon switch of collision.json (distance.objectDistance / useHorizon)."""
    try:
        import collision

        d = collision.load_config().get("distance", {})
        return d.get("objectDistance", "depth"), bool(d.get("useHorizon", True))
    except Exception:  # no config: the v26.2.2 behaviour
        return "depth", True


def get_settings(rec_id: str, default_mount: str) -> dict[str, Any]:
    """Stored settings, or the defaults when nothing was saved. Camera location and side default from the recording
    name (``Chest-center-0004``: chest, center) where the body calibration has that location."""
    hints = name_hints(rec_id)
    location: str | None = hints.get("cameraLocation")
    if location not in _body_locations():
        location = None
    obj_dist, use_h = _distance_defaults()
    defaults = {
        "mount": default_mount,
        "hfovDeg": None,
        "cameraHeightM": None,
        "stepLengthM": None,
        "projection": "auto",
        "distanceSource": "depth",
        "userHeightM": None,
        "cameraLocation": location,
        "cameraSide": hints.get("cameraSide", "center"),
        "orientation": "landscape",
        "objectDistance": obj_dist,
        "useHorizon": use_h,
    }
    try:
        stored = json.loads(_settings_path(rec_id).read_text())
    except (OSError, ValueError):
        return defaults
    return {**defaults, **{k: stored[k] for k in defaults if k in stored}}


def save_settings(rec_id: str, settings: dict[str, Any]) -> None:
    _atomic_write_json(_settings_path(rec_id), settings)
