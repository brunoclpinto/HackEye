"""Where each real item's position comes from in the collision pass (``source.mode`` "map"): ``map_source``."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Protocol

from engine.core.groundgeom import ego_frame
from engine.core.types import trusted_track
from engine.worldmap.staticmap import set_position

if TYPE_CHECKING:
    from engine.core.types import Item

__all__ = ["map_source"]


class _SourceMap(Protocol):
    """What ``map_source`` reads of the static map."""

    pose: tuple[float, float, float]
    judged: Any

    def region(self, it: Any, pad: float, min_cells: int) -> Any: ...

    def _apply(self, it: Any, *args: Any) -> Any: ...


class _WorldTracks(Protocol):
    """What ``map_source`` reads of the world tracks."""

    on: bool

    def lookup(self, tid: int, t: float) -> Any: ...


def map_source(
    items: list[Item],
    tracks: dict[int, Any],
    smap: _SourceMap,
    wtracks: _WorldTracks,
    cfg: dict[str, Any],
    t: float,
    step_len: float,
    u: float | None,
    counts: dict[str, int],
) -> None:
    """source.mode "map" (v26.2.11): where each real item's position comes from, ``item.srcsel``.

    * a static item (not judged by the face / edge test, which already is the map's) -> its 8-connected region of
      fused map cells (``_StaticMap.region``): the nearest cell is its distance / lateral / clock; ``map``;
    * a mover with a TRUSTED world track -> the track's position at ``t`` and its velocity (``track``): the closing
      speed, the sideways velocity and the own speed along the line of sight come from the track instead of the
      image's contact-row history;
    * the image safety net (``imageNetSteps`` / ``imageNetFrames``): an item within 3 steps, a new track (< 2
      frames) or a mover whose world track is not trusted (or jumps from the image by more than ``maxTrackJumpM``)
      stays as the image measured it (``image``).
    The image item stays the carrier of the identity, the overlay (bbox, outline), the confirmation and the speech
    bookkeeping."""
    net_steps, net_frames = float(cfg.get("imageNetSteps", 3.0)), int(cfg.get("imageNetFrames", 2))
    pad, min_cells = float(cfg.get("regionPadM", 2.0)), int(cfg.get("regionMinCells", 2))
    jump_m, jump_frac = float(cfg.get("maxTrackJumpM", 3.0)), float(cfg.get("maxTrackJumpFrac", 0.35))
    pose = smap.pose
    for it in items:
        if it.lane_part or it.ghost or it.coasting:
            continue
        tr = tracks[it.track_id]
        it.srcsel = "image"
        net = it.distance_m / step_len <= net_steps or tr.present_run < net_frames
        if it.group == "static":
            if it.map_judged or it.class_name in smap.judged:  # the face / edge test: already the map's
                it.srcsel = "map" if it.image_dl is not None else "image"
            elif not net:
                reg = smap.region(it, pad, min_cells)
                if reg is not None:
                    smap._apply(it, reg[0], reg[1], reg[2])
                    it.map_source, it.srcsel = "map", "map"
        elif it.group == "moving" and not net and u is not None and wtracks.on:
            e = trusted_track(wtracks, it.track_id, t)
            if e is not None:
                fwd, right = ego_frame(pose, e["x"], e["y"])
                if fwd > 0.0 and math.hypot(fwd - it.distance_m, right - it.lateral_m) <= max(
                    jump_m, jump_frac * it.distance_m
                ):
                    vf, vr = ego_frame((0.0, 0.0, pose[2]), e["vx"], e["vy"])
                    rng = max(math.hypot(fwd, right), 1e-6)
                    uf, ur = fwd / rng, right / rng
                    set_position(it, fwd, right)
                    it.pred_v = (vf, vr)
                    it.closing = -(uf * (vf - u) + ur * vr)  # the gap's shrink rate, our own speed included
                    it.track_motion = (-(uf * vf + ur * vr), vr, -ur * vf + uf * vr)
                    it.srcsel = "track"
        counts[it.srcsel] += 1
