"""Collision settings: the resolved camera / body / distance configuration and the legacy timing constants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.core.log import warn_once

__all__ = [
    "AUTO_FISHEYE_HFOV_DEG",
    "DISTANCE_SOURCES",
    "HORIZON_HOLD_S",
    "MIN_TRACK_AGE_S",
    "OBJECT_DISTANCES",
    "SIDE_SIGN",
    "WARMUP_S",
    "CollisionSettings",
    "resolve_projection",
    "resolve_settings",
]

HORIZON_HOLD_S = 3.0  # keep the last good horizon this long when the estimate fails (not in the contract)
# the horizon is the mean of the raw estimates until it has had time to settle (no silence: v26.1.15)
WARMUP_S = 1.5
# a track must have lived this long before it may speak or beep (not in the first WARMUP_S of a run)
MIN_TRACK_AGE_S = 0.5


@dataclass
class CollisionSettings:
    mount: str
    hfov_deg: float
    camera_height_m: float
    step_length_m: float | None  # None = estimate, fall back to the default
    horizon_default: float
    projection: str = "rectilinear"  # resolved lens model: "rectilinear" (pinhole) or "fisheye" (equidistant)
    distance_source: str = "ground"  # "ground" | "depth" (v26.1.10 depth experiment)
    depth_level_prior: float | str | None = None  # mount override of distance.depthLevelPrior (number | "ground")
    user_height_m: float | None = None  # body mode (None = legacy mount mode)
    camera_location: str | None = None  # "waist" | "chest" | "eye" | "head"
    camera_side: str | None = None  # "left" | "center" | "right"
    # camera centre relative to the body centre (+ = camera right of body)
    lateral_offset_m: float = 0.0
    # v26.2.3: "depth" | "ground-contact" | "ground+depth" (distance.objectDistance), see groundfuse
    object_distance: str = "depth"
    # v26.2.3: False = no ground ray in any distance / map projection (distance.useHorizon)
    use_horizon: bool = True
    # v26.2.12: the step length was typed by the user (it wins over the GPS step length)
    step_length_user: bool = False


AUTO_FISHEYE_HFOV_DEG = 100.0
DISTANCE_SOURCES = ("ground", "depth")
OBJECT_DISTANCES = ("depth", "ground-contact", "ground+depth")


def resolve_projection(projection: str | None, hfov_deg: float) -> str:
    """ "rectilinear" / "fisheye" pass through; None or "auto": fisheye from HFOV 100 deg up (wide action cams)."""
    if projection in ("rectilinear", "fisheye"):
        return projection
    return "fisheye" if hfov_deg >= AUTO_FISHEYE_HFOV_DEG else "rectilinear"


SIDE_SIGN = {"left": -1.0, "center": 0.0, "right": 1.0}


def resolve_settings(
    config: dict[str, Any],
    mount: str | None = None,
    hfov_deg: float | None = None,
    camera_height_m: float | None = None,
    step_length_m: float | None = None,
    projection: str | None = None,
    distance_source: str = "ground",
    user_height_m: float | None = None,
    camera_location: str | None = None,
    camera_side: str | None = None,
    object_distance: str | None = None,
    use_horizon: bool | None = None,
) -> CollisionSettings:
    """Explicit values win over the mount preset / body geometry; None falls back to defaults.

    Body mode (``camera_location`` or ``user_height_m`` given, ``config["body"]``): camera height =
    heightRatio x height + heightOffsetM, step length = stepLengthRatio x height, horizon from the location,
    lateral offset = side sign x sideOffsetM. Otherwise the legacy mount preset (lateral offset 0)."""
    mount = mount or config["defaultMount"]
    if mount not in config["mountPresets"]:
        warn_once(f"unknown mount '{mount}', using '{config['defaultMount']}'")
        mount = config["defaultMount"]
    preset = config["mountPresets"][mount]
    hfov = float(config["defaultHfovDeg"] if hfov_deg is None else hfov_deg)
    if distance_source not in DISTANCE_SOURCES:
        warn_once(f"unknown distance source '{distance_source}', using 'ground'")
        distance_source = "ground"
    body = config.get("body")
    body_h = loc = side = None
    lat_off = 0.0
    cam_h = float(preset["cameraHeightM"])
    horizon = float(preset["horizon"])
    step = None
    if body and (camera_location is not None or user_height_m is not None):
        locs = body["cameraLocations"]
        loc = camera_location or body.get("defaultCameraLocation", "chest")
        if loc not in locs:
            warn_once(f"unknown camera location '{loc}', using '{body.get('defaultCameraLocation', 'chest')}'")
            loc = body.get("defaultCameraLocation", "chest")
        spec = locs[loc]
        body_h = float(user_height_m if user_height_m is not None else body["defaultUserHeightM"])
        side = camera_side or "center"
        if side not in SIDE_SIGN:
            warn_once(f"unknown camera side '{side}', using 'center'")
            side = "center"
        cam_h = float(spec["heightRatio"]) * body_h + float(spec.get("heightOffsetM", 0.0))
        step = float(body["stepLengthRatio"]) * body_h
        horizon = float(spec["horizon"])
        lat_off = SIDE_SIGN[side] * float(spec.get("sideOffsetM", 0.0))
    dcfg = config.get("distance", {})
    if object_distance is None:
        object_distance = dcfg.get("objectDistance", "depth")
    if object_distance not in OBJECT_DISTANCES:
        warn_once(f"unknown object distance '{object_distance}', using 'depth'")
        object_distance = "depth"
    use_h = bool(dcfg.get("useHorizon", True) if use_horizon is None else use_horizon)
    if camera_height_m is not None:
        cam_h = float(camera_height_m)
    if step_length_m is not None:
        step = float(step_length_m)
    return CollisionSettings(
        mount=mount,
        hfov_deg=hfov,
        camera_height_m=cam_h,
        step_length_m=step,
        horizon_default=horizon,
        projection=resolve_projection(projection, hfov),
        distance_source=distance_source,
        depth_level_prior=preset.get("depthLevelPrior"),
        user_height_m=body_h,
        camera_location=loc,
        camera_side=side,
        lateral_offset_m=lat_off,
        object_distance=object_distance,
        use_horizon=use_h,
        step_length_user=step_length_m is not None,
    )
