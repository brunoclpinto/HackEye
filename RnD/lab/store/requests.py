"""Run request validation, the run id and the request-derived helpers (moved verbatim from lab/analysis.py).

Reads `recordings.get_recording`, `models.list_models` and the constants as attributes of their store modules at call
time, so the patches tests make on the flat modules (which forward here) are seen.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import profiles
from lab.store import constants, models, recordings
from lab.store.errors import RunError


def _normalise_request(req: dict[str, Any]) -> dict[str, Any]:
    rec = recordings.get_recording(str(req.get("recording", "")))
    if rec is None:
        raise RunError(f"Unknown recording: {req.get('recording')!r}")
    try:
        start, end, fps = float(req["start"]), float(req["end"]), float(req.get("fps", 6.0))
    except (KeyError, TypeError, ValueError):
        raise RunError("start, end and fps must be numbers") from None
    # An end past the footage is clamped (the UI's default range may overshoot
    # a short clip); the clamped value is what gets stored and hashed.
    end = min(end, rec["duration"])
    if not (0 <= start < end):
        raise RunError(f"Range must satisfy 0 <= start < end <= {rec['duration']:.1f}")
    if not (0 < fps <= 60):
        raise RunError("fps must be in (0, 60]")
    profile = req.get("profile") or "default"
    if profile not in constants.RESOLUTIONS + constants.PROFILES:
        raise RunError(f"profile must be one of {constants.RESOLUTIONS + constants.PROFILES}")
    orientation = req.get("orientation") or "landscape"
    if orientation not in profiles.ORIENTATIONS:
        raise RunError(f"orientation must be one of {list(profiles.ORIENTATIONS)}")
    side = request_side(req, rec)
    if profile in constants.RESOLUTIONS:
        try:
            profiles.window_spec(rec["width"], rec["height"], int(profile[:-1]), orientation, side)
        except ValueError as e:
            raise RunError(str(e)) from None
    model = req.get("model")
    if model not in {m["path"] for m in models.list_models()}:
        raise RunError(f"Unknown model: {model!r}")
    depth = req.get("depth") or "none"
    if depth not in constants.DEPTH_MODELS:
        raise RunError(f"depth must be one of {list(constants.DEPTH_MODELS)}")
    request = {"recording": rec["id"], "start": start, "end": end, "model": model, "profile": profile, "fps": fps}
    if depth != "none":  # omitted for "none" so ids of depth-less requests stay stable
        request["depth"] = depth
    if orientation != "landscape":  # a landscape run is the full frame: its request (and id) stay as they were
        request["orientation"] = orientation
        request["side"] = side  # the window depends on the side
    return request


def request_side(req: dict[str, Any], rec: dict[str, Any]) -> str:
    """Camera side of a request: its own `side`, else the recording's saved Camera side."""
    side = req.get("side") or recordings.get_settings(rec["id"], "")["cameraSide"]
    if side not in profiles.SIDES:
        raise RunError(f"side must be one of {list(profiles.SIDES)}")
    return str(side)


def run_window(rec: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Source-pixel window of a run's request ({x0, y0, w, h})."""
    window: dict[str, Any] = profiles.camera_window(
        rec["width"], rec["height"], request.get("orientation", "landscape"), request.get("side", "center")
    )
    return window


DEVICES = ["gpu", "cpu"]


def _parse_device(req: dict[str, Any]) -> str:
    """The execution device of a request. Not part of the hashed request: it changes speed, not results."""
    # HACKEYE_LAB_DEFAULT_DEVICE: default for requests that name no device (staging Lab runs on CPU); unset = "gpu".
    device = req.get("device") or os.environ.get("HACKEYE_LAB_DEFAULT_DEVICE") or "gpu"
    if device not in DEVICES:
        raise RunError(f"device must be one of {DEVICES}")
    return str(device)


def _cpu_threads() -> int:
    return int(os.environ.get("HACKEYE_LAB_CPU_THREADS") or max(1, (os.cpu_count() or 2) - 2))


def _run_id(request: dict[str, Any]) -> str:
    mtime = Path(request["model"]).stat().st_mtime
    canon = (
        json.dumps({**request, "analysisVersion": constants.ANALYSIS_VERSION}, sort_keys=True, separators=(",", ":"))
        + f"|{mtime}"
    )
    return hashlib.sha1(canon.encode()).hexdigest()[:12]
