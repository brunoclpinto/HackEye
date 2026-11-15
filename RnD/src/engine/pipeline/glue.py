"""Glue helpers of the frame pipeline: bottom-row distance, hidden-cell lookup, mover velocity, world-track timing."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from engine.core import groundgeom
from engine.core.groundgeom import ego_frame
from engine.core.types import Item, trusted_track

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["LAST_WORLD_TRACKS_MS", "bottom_distance", "hidden_fn", "predict_velocities"]


# ms of the world-track step per frame of the last run_collision (metrics tool; not in the output)
LAST_WORLD_TRACKS_MS: list[float] = []


def bottom_distance(ob: Any, horizon: float, cam_h: float, gh: int, f: float) -> float:
    """Forward distance of the last image row on the centre column (the ground seen at the bottom),
    as the map's ``objectClearBottomM`` uses it."""
    try:
        if ob is not None and getattr(ob, "geometry", False):
            d = float(groundgeom.ground_point(ob.geo, float(ob.gh), ob.gw / 2.0, float(horizon), ob.cam_h)[0])
            return d if math.isfinite(d) else 0.0
        return float(cam_h) * f / (max(1.0 - float(horizon), 1e-6) * gh)
    except Exception:
        return 0.0


def hidden_fn(ob: Any) -> Callable[[float, float], bool] | None:
    """``(fwd, right) -> bool``: the online map's cell there is hidden behind a building in this frame
    (None without a map)."""
    if ob is None or getattr(ob, "ray_hidden", None) is None:
        return None
    hid = ob.ray_hidden

    def hidden(fwd: float, right: float) -> bool:
        r, c = ob.orow - int(round(fwd / ob.cell)), ob.oc + int(round(right / ob.cell))  # noqa: RUF046
        return 0 <= r < hid.shape[0] and 0 <= c < hid.shape[1] and bool(hid[r, c])

    return hidden


def predict_velocities(items: list[Item], wtracks: Any, t: float, theta: float, pcfg: dict[str, Any]) -> None:
    """Predictive speech: a mover with a trusted, moving world track carries its velocity in our frame (``pred_v``)."""
    top = float(pcfg.get("maxMoverMps", 12.0))
    for it in items:
        if it.group != "moving" or it.lane_part or it.ghost:
            continue
        e = trusted_track(wtracks, it.track_id, t)
        if e is None or e["static"] or math.hypot(e["vx"], e["vy"]) > top:
            continue
        it.pred_v = ego_frame((0.0, 0.0, math.degrees(theta)), e["vx"], e["vy"])
