"""Hazards output: the per-item hazards.json dict, the walking-lane polygon and the region rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from engine.core.geom import round_opt as _r
from engine.output.outline import item_full, item_outline

if TYPE_CHECKING:
    from engine.core.groundgeom import FrameGeo
    from engine.core.types import Item, Region

__all__ = ["hazard_dict", "hazard_json", "lane_polygon", "region_rows"]


def lane_polygon(geo: FrameGeo, lane_half_m: float, far_distance_m: float) -> list[list[float]]:
    def half(y: float) -> float:
        return lane_half_m * (y - geo.horizon) * geo.gh / geo.camera_height_m / geo.gw

    def mid(y: float) -> float:
        return 0.5 - geo.lateral_offset_m * (y - geo.horizon) * geo.gh / geo.camera_height_m / geo.gw

    y_far = min(1.0, geo.horizon + geo.camera_height_m * geo.f / (far_distance_m * geo.gh))
    y_far = max(y_far, geo.horizon)

    def cl(x: float) -> float:
        return round(min(1.0, max(0.0, x)), 4)

    return [
        [cl(mid(1.0) - half(1.0)), 1.0],
        [cl(mid(1.0) + half(1.0)), 1.0],
        [cl(mid(y_far) + half(y_far)), round(y_far, 4)],
        [cl(mid(y_far) - half(y_far)), round(y_far, 4)],
    ]


def region_rows(region: Region | None, step: int = 4) -> list[list[float]]:
    if region is None:
        return []
    gh = len(region.left)
    return [
        [round((r + 0.5) / gh, 3), round(float(region.left[r]), 3), round(float(region.right[r]), 3)]
        for r in range(gh - 1, -1, -step)
        if not np.isnan(region.left[r])
    ]


def hazard_json(it: Item, gh: int = 0, gw: int = 0, full_all: bool = False) -> dict[str, Any]:
    out = hazard_dict(it)
    if gh and gw and (it.role != "none" or full_all):
        if it.role != "none":
            outline = item_outline(it, gh, gw)
            if outline:
                out["outline"] = outline
        # v26.2.14 (``output.fullAllItems``) (review 11, Lab note 1: "not able to click on objects above the horizon
        # line"): the whole component of EVERY item that has a shape, not only of those with a role (a no-role building
        # was cut at the horizon, so it could not be selected above it)
        full = item_full(it, gh, gw)
        if full is not None:
            out["bboxFull"] = full[0]
            if full[1]:
                out["outlineFull"] = full[1]
    return out


def hazard_dict(it: Item) -> dict[str, Any]:
    return {
        "trackId": it.track_id,
        "className": it.class_name,
        "group": it.group,
        "label": it.label,
        "role": it.role,
        "moving": it.moving if it.group == "moving" else False,
        "bbox": [round(v, 4) for v in it.bbox],
        "contactY": round(it.contact_y, 4),
        "bearingDeg": round(it.bearing, 2),
        "clock": it.clock,
        "clockText": it.clock_text,
        "pan": round(it.pan, 4),
        "distanceM": round(it.distance_m, 2),
        "lateralM": round(it.lateral_m, 2),
        "stepsTo": round(it.steps, 1),
        "closingMps": _r(it.closing, 2),
        "urgency": it.urgency,
        "areaFrac": round(it.area_frac, 5),
        "collision": bool(it.collision),
        "latVelMps": _r(it.lat_vel, 2),
        "crossMps": _r(it.cross_mps, 2),
        **({"depthM": _r(it.depth_m, 2)} if it.depth_on else {}),
        **({"lanePart": True} if it.lane_part else {}),
        **({"source": it.map_source, "mapCells": it.map_cells} if it.group == "static" and it.map_source else {}),
        **({"source": it.srcsel} if it.srcsel else {}),
        **(
            {"imageDistanceM": round(it.image_dl[0], 2), "imageLateralM": round(it.image_dl[1], 2)}
            if it.image_dl
            else {}
        ),
        **({"ghost": True} if it.ghost else {}),
        **({"coasting": True} if it.coasting else {}),
        **({"insideSolid": True} if it.inside_solid else {}),
        **(
            {"solidCorrected": True, "rawDistanceM": round(it.raw_distance_m, 2)}  # type: ignore[arg-type]  # set with solid_corrected
            if it.solid_corrected
            else {}
        ),
        **({"faceEdge": it.face_edge} if it.face_edge else {}),
        **({"ownMps": list(it.own)} if it.own else {}),
        **({"fromSide": it.from_side} if it.from_side else {}),
        **({"nearPass": True} if it.near_pass else {}),
        **(
            {"distanceSource": it.dist_source, "rawDepthM": _r(it.raw_depth_m, 2), "groundM": _r(it.ground_m, 2)}
            if it.dist_source
            else {}
        ),
    }
