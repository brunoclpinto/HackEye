"""Greedy frame-to-frame matching of items to tracks (same group and class; IoU or the ground gate)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from engine.core.geom import Box, iou

if TYPE_CHECKING:
    from engine.core.types import Item, Track

__all__ = ["match"]


def match(
    tracks: dict[int, Track],
    items: list[Item],
    t: float,
    trk: dict[str, Any],
    pan_shift: float = 0.0,
    people: frozenset[str] = frozenset(),
) -> dict[int, int]:
    """Greedy matching, same group+class; IoU or the ground gate. Returns {item index: track id}.

    ``pan_shift`` (v26.1.16, review 8, 27.3 s): how far the whole scene moved sideways in the image since the
    previous frame because
    the camera turned (normalised x; + = scene moved right). A person at 5.7 m jumped a full box width in one frame
    while the head
    turned 9 degrees: no overlap, so the track was lost, restarted (age 0, no motion, confirmation from 1) three
    times and the
    announcement came 1.2 s late. For people (they walk and fragment under a pan; a pole or a building is re-found by
    the ground gate) and only in a hard turn
    (``tracking.panMatchMinShift``) the IoU is also taken against the track's box moved by the pan."""
    pairs = []
    for tid, tr in tracks.items():
        dt = t - tr.last_t
        expected = -(tr.closing or 0.0) * dt
        moved = (
            Box(tr.box.x1 + pan_shift, tr.box.y1, tr.box.x2 + pan_shift, tr.box.y2)
            if abs(pan_shift) >= trk.get("panMatchMinShift", 0.0) and tr.class_name in people
            else None
        )
        for ii, it in enumerate(items):
            if it.group != tr.group or it.class_name != tr.class_name or it.lane_part != tr.lane_part:
                # a lane part (v26.1.16 follow-up) is its own track, never the side wall's
                continue
            v = iou(tr.box, Box(*it.bbox))
            if moved is not None:
                v = max(v, iou(moved, Box(*it.bbox)))
            gate = (
                abs(it.lateral_m - tr.last_lateral) <= trk["groundGateLateralM"]
                and abs((it.distance_m - tr.last_distance) - expected) <= trk["groundGateDistanceFrac"] * it.distance_m
            )
            if v >= trk["iouMatch"] or gate:
                pairs.append((v + (0.5 if gate else 0.0), tid, ii))
    pairs.sort(key=lambda p: -p[0])
    used: set[int] = set()
    out: dict[int, int] = {}
    for _, tid, ii in pairs:
        if tid in used or ii in out:
            continue
        used.add(tid)
        out[ii] = tid
    return out
