"""Recordings router: listing, proxy build and media, per-recording settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

import groundfuse
from lab import recordings
from lab.api.deps import _collision, _recording

router = APIRouter()


@router.get("/api/recordings")
def list_recordings() -> list[dict[str, Any]]:
    return recordings.list_recordings()  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.post("/api/recordings/{rec_id}/proxy")
def build_proxy(rec_id: str) -> dict[str, Any]:
    return recordings.start_proxy(_recording(rec_id))  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.api_route("/media/{name}", methods=["GET", "HEAD"])
def get_proxy(name: str) -> FileResponse:
    rec_id = name[:-4] if name.endswith(".mp4") else None
    path = recordings.proxy_path(rec_id) if rec_id and "/" not in rec_id and ".." not in rec_id else None
    # `.part` files never match: only a finished build has the final name.
    if path is None or not path.exists():
        raise HTTPException(404, "Proxy not ready")
    return FileResponse(path, media_type="video/mp4")


# --- settings ---------------------------------------------------------------


def _opt_number(body: dict[str, Any], key: str, lo: float, hi: float, hi_inclusive: bool = True) -> Any:
    v = body.get(key)
    if v is None:
        return None
    ok = not isinstance(v, bool) and isinstance(v, (int, float)) and lo <= v and (v <= hi if hi_inclusive else v < hi)
    if not ok:
        bracket = "]" if hi_inclusive else ")"
        raise HTTPException(422, f"{key} must be null or a number in [{lo:g}, {hi:g}{bracket}")
    return v


PROJECTIONS = ("auto", "rectilinear", "fisheye")
DISTANCE_SOURCES = ("ground", "depth")
OBJECT_DISTANCES = ("depth", "ground-contact", "ground+depth")
CAMERA_SIDES = ("left", "center", "right")
ORIENTATIONS = ("landscape", "portrait")


def _location(body: dict[str, Any], config: dict[str, Any]) -> Any:
    """cameraLocation: null (legacy mount) or a key of collision.json body.cameraLocations."""
    v = body.get("cameraLocation")
    if v is None:
        return None
    options = list((config.get("body") or {}).get("cameraLocations", {}))
    if v not in options:
        raise HTTPException(422, f"cameraLocation must be null or one of {options}")
    return v


def _choice(body: dict[str, Any], key: str, options: tuple[str, ...], default: str) -> str:
    v = body.get(key)
    if v is None:
        return default
    if v not in options:
        raise HTTPException(422, f"{key} must be one of {list(options)}")
    return v  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


def _bool(body: dict[str, Any], key: str, default: bool) -> bool:
    v = body.get(key)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise HTTPException(422, f"{key} must be true or false")
    return v


def _validated_settings(body: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Validate a settings body (§4). A legacy `corridor` key is ignored."""
    mount = body.get("mount") or config["defaultMount"]
    if mount not in config["mountPresets"]:
        raise HTTPException(422, f"Unknown mount {mount!r}; expected one of {list(config['mountPresets'])}")
    return {
        "mount": mount,
        "hfovDeg": _opt_number(body, "hfovDeg", 10, 180, hi_inclusive=False),
        "cameraHeightM": _opt_number(body, "cameraHeightM", 0.5, 2.5),
        "stepLengthM": _opt_number(body, "stepLengthM", 0.3, 2.0),
        "projection": _choice(body, "projection", PROJECTIONS, "auto"),
        "distanceSource": _choice(body, "distanceSource", DISTANCE_SOURCES, "depth"),
        "userHeightM": _opt_number(body, "userHeightM", 1.0, 2.3),
        "cameraLocation": _location(body, config),
        "cameraSide": _choice(body, "cameraSide", CAMERA_SIDES, "center"),
        "orientation": _choice(body, "orientation", ORIENTATIONS, "landscape"),
        "objectDistance": _choice(
            body, "objectDistance", OBJECT_DISTANCES, config.get("distance", {}).get("objectDistance", "depth")
        ),
        "useHorizon": _bool(body, "useHorizon", bool(config.get("distance", {}).get("useHorizon", True))),
    }


def _settings_response(rec_id: str) -> dict[str, Any]:
    collision = _collision()
    config = collision.load_config()
    stored = recordings.get_settings(rec_id, config["defaultMount"])
    rs = collision.resolve_settings(
        config,
        stored["mount"],
        stored["hfovDeg"],
        stored["cameraHeightM"],
        stored["stepLengthM"],
        projection=stored["projection"],
        distance_source=stored["distanceSource"],
        user_height_m=stored["userHeightM"],
        camera_location=stored["cameraLocation"],
        camera_side=stored["cameraSide"],
        object_distance=stored["objectDistance"],
        use_horizon=stored["useHorizon"],
    )
    resolved = {
        "hfovDeg": rs.hfov_deg,
        "projection": rs.projection,
        "cameraHeightM": rs.camera_height_m,
        "stepLengthM": rs.step_length_m,  # null = auto
        "horizon": rs.horizon_default,
        "userHeightM": rs.user_height_m,
        "cameraLocation": rs.camera_location,
        "cameraSide": rs.camera_side,
        "lateralOffsetM": rs.lateral_offset_m,
        "objectDistance": rs.object_distance,
        "useHorizon": rs.use_horizon,
        "objectDistanceEffective": groundfuse.resolved_mode(rs.object_distance, rs.use_horizon),  # v26.2.11
    }
    return {**stored, "resolved": resolved}


@router.get("/api/recordings/{rec_id}/settings")
def get_settings(rec_id: str) -> dict[str, Any]:
    _recording(rec_id)
    return _settings_response(rec_id)


@router.put("/api/recordings/{rec_id}/settings")
def put_settings(rec_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _recording(rec_id)
    config = _collision().load_config()
    recordings.save_settings(rec_id, _validated_settings(body, config))
    return _settings_response(rec_id)
