"""Shared per-frame data types: Item, Track, Region, their constants and trusted_track."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from engine.core.clock import clock_text
from engine.core.clock import quarter_of_hour as _quarter_of_hour

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    from engine.core.geom import Box

__all__ = ["LANE_PART_ID_BASE", "POINT_ASPECT", "Item", "Region", "Track", "trusted_track"]

LANE_PART_ID_BASE = 1_000_000  # first track id of the lane parts of walls / buildings (v26.1.16 follow-up)
POINT_ASPECT = 3.0  # bbox height / width (normalised units, ~1.7 in pixels) of a pole-like item


@dataclass
class Region:
    group: str
    label: str
    mask: npt.NDArray[np.bool_]  # (H, W) bool
    left: npt.NDArray[np.float64]  # (H,) normalised x, nan = row has no region
    right: npt.NDArray[np.float64]


@dataclass
class Item:
    """One connected component of an item class in one frame."""

    group: str
    class_name: str
    bbox: list[float]
    contact_y: float
    distance_m: float
    lateral_m: float
    bearing: float
    clock: int
    pan: float
    area_frac: float
    clipped: bool  # touches the bottom image edge: distance is a lower bound
    touches: bool  # touches the dilated walking region
    lane_hit: bool  # (static/moving) in lane within region; (feature) in lane
    along_path: bool  # long stretch of path inside the region: a boundary, not an obstacle
    lane_cover: float  # share of the lane's width at the contact row that it covers
    contact_y_raw: float = 0.0
    area_m2: float = 0.0  # component area scaled to square metres at its distance
    # filled in by tracking / roles
    track_id: int = 0
    closing: float | None = None
    moving: bool | None = None
    approaching: bool = False
    steps: float = 0.0
    label: str = ""
    role: str = "none"
    urgency: str = "none"
    settled: bool = False  # track old enough to speak or beep
    family: str = ""  # label family used as context-memory key ("" = use label)
    role_run: int = 0  # consecutive frames the track has held ``role`` (incl. this one)
    closing_raw: float | None = None  # closing speed in uncalibrated model metres (k = 1)
    landmark: bool = False  # a crosswalk: announced once as a location marker
    receding: bool = False  # a mover measured to walk away from us
    ego_known: bool = False  # our own speed is known, so this item's motion can be measured
    # a rider / vehicle closing faster than any walking speed could explain (v26.1.16)
    own_fast: bool = False
    # ...and the robust ego speed has its full window: motion words / the motion wait apply (v26.1.15)
    ego_settled: bool = False
    # would be context but for the lateral cap: allowed in the first scene summary
    summary_ok: bool = False
    people: bool = False  # person / rider / animal: a mover unless measured stationary
    # rider / vehicle: announced as early as possible, without a distance (v26.1.13)
    fast: bool = False
    speak: bool = True  # may be spoken; False = beeps only (a person within 5 steps, v26.1.13)
    thin: bool = False  # pole, light, sign: easy to miss, warned about when noticed
    # a danger on a collision course: the only thing that beeps (parking beeps)
    collision: bool = False
    prox_run: int = 0  # consecutive frames the track has been a proximity item (confirmFrames)
    # a person / animal measured approaching, close and not on a collision course: soft sound (v26.1.13 follow-up)
    proximity: bool = False
    present_run: int = 0  # consecutive analysed frames the track has been seen
    wx: float = 0.0  # dead-reckoned world position (m), see _WorldMemory
    wy: float = 0.0
    mem_id: int | None = None  # the remembered object this item is, if any
    mem_named: bool = False  # ... and it was named (False: only covered by a cluster notice)
    mem_approach: bool = False  # ... and it was announced as "approaching"
    # ... and it was announced as a danger / final (v26.1.16: only that mutes a later danger)
    mem_danger: bool = False
    shape: tuple[Any, ...] | None = None  # (cropped component mask, col0, row0): source of the outline (v26.1.8)
    clock_q: int | None = None  # quarter-hour clock index (v26.1.10); derived from ``clock`` if not given
    clock_text: str = ""  # spoken clock position, "12", "12:15", "11:45"
    # metric depth under the item's lower rows (experiment), if a depth map exists
    depth_m: float | None = None
    depth_on: bool = False  # a depth map exists for this frame (``depthM`` is reported, maybe null)
    # depth under the item's lower rows in the map's own units (metres or relative)
    depth_raw: float | None = None
    from_depth: bool = False  # distance_m was taken from the depth map
    # own sideways ground velocity (m/s, + = right), see _lateral_velocity (v26.1.11)
    lat_vel: float | None = None
    # velocity across the line of sight from the bearing rate (m/s, + = right), see _cross_velocity (v26.1.12)
    cross_mps: float | None = None
    # (rows, cols) the depth is read from instead of the component's lowest rows (lane part: its base)
    depth_cells: tuple[Any, ...] | None = None
    # ...whose base is not flat: it only continues a lane part that was flat a moment ago (laneBaseHoldSeconds)
    lane_part_weak: bool = False
    # the extra item of a wall / building whose ground base crosses the lane (v26.1.16 follow-up)
    lane_part: bool = False
    # "map": a static item judged on the fused world map (v26.2.1); "image": no map cells to read (its contact point);
    # "": staticSource image
    map_source: str = ""
    map_cells: int = 0  # (map) cells of the item's family inside the walking corridor
    # (map) world position of its nearest corridor cell (a ghost is followed from it)
    map_world: tuple[Any, ...] | None = None
    # (map, in the corridor) the image contact point's (distance, lateral, bearing, clock, clock_q, clock_text, pan)
    # the map measurement replaced
    image_dl: tuple[Any, ...] | None = None
    # (v26.2.2, insideSolid.mode "snap") its distance was moved to the near border of the solid area
    solid_corrected: bool = False
    raw_distance_m: float | None = None  # ...the measured distance before the correction
    # (v26.2.2) its map position is inside / behind a solid wall face: impossible, so it is muted (no speech, beeps,
    # proximity)
    inside_solid: bool = False
    # (v26.2.2) a mover that left the image: predicted on its last world velocity, beeps / course only
    coasting: bool = False
    # (map) no longer in the image (under the frame): kept alive by its map cells
    ghost: bool = False
    # (v26.2.2) a wall-like static item judged on the map alone (no image lane rule)
    map_judged: bool = False
    # (v26.2.2, roles.faceEdge.enabled) the face / edge test of its corridor cells: diagnostics only
    face_edge: dict[str, Any] | None = None
    # (v26.2.3) the grid pixel of its contact point (lowest pixel); -1 = unknown
    base_row: int = -1
    base_col: int = -1
    # (v26.2.3, objectDistance != "depth") "depth" | "ground" | "fused": where distance_m came from
    dist_source: str = ""
    raw_depth_m: float | None = None  # ... the scaled depth before the range correction
    # ... its ground ray in depth metres (None: not in contact / outside the band)
    ground_m: float | None = None
    # (v26.2.11, source.mode "map") where its position came from: "map" | "track" | "image"; "" = image mode
    srcsel: str = ""
    # (source "track") (own speed towards us along the line of sight, sideways velocity, velocity across the line of
    # sight) m/s, from its world track
    track_motion: tuple[Any, ...] | None = None
    # (v26.2.12) a "pole" whose top meets a vegetation canopy: a tree trunk (label "tree", family vegetation)
    tree: bool = False
    # (v26.2.12) its distance jumped within the last ``speech.thinStableS``: a thin item stays unspoken
    unstable: bool = False
    # (v26.2.12) its distance jumped THIS frame (measurement glitch): no motion history, no coasting from it
    jumped: bool = False
    # (v26.2.12) (labelled full-class grid, the component's slices, its label): the whole component incl. rows above
    # the horizon
    full_ref: tuple[Any, ...] | None = None
    # (v26.2.11, predictive speech) a trusted mover's world velocity in our frame (forward, right) m/s
    pred_v: tuple[Any, ...] | None = None
    # (v26.2.13) a wall the user walks along (its distance does not close at the walking speed): no beep episode, no
    # phrase
    followed: bool = False
    # (v26.2.14) the mover's own ground velocity (forward, right) m/s in our frame and its sigma, see _OwnMotion
    own: tuple[Any, ...] | None = None
    # ... the estimate is usable (enough frames, sigma small): the motion words come from it, not from the closing rate
    own_ok: bool = False
    own_closing: float | None = None  # ... the rate the gap shrinks at: our speed minus its forward speed
    # ... an approaching mover that passes within ``motion.nearPassM`` of us within ``motion.nearPassS``: a collision
    # danger
    near_pass: bool = False
    # ... "right" / "left": it comes across our path from that side (own lateral speed >= ``motion.sideMps``)
    from_side: str = ""

    def __post_init__(self) -> None:
        if self.clock_q is None:
            self.clock_q = _quarter_of_hour(self.clock)
        if not self.clock_text:
            self.clock_text = clock_text(self.clock_q)


@dataclass
class Track:
    id: int
    group: str
    class_name: str
    box: Box
    last_t: float
    first_t: float
    last_distance: float
    last_lateral: float
    history: list[tuple[float, float]] = field(default_factory=list)  # (t, distanceM)
    closing: float | None = None
    moving: bool | None = None
    # speech bookkeeping, set only when the phrase is really spoken
    danger_done: bool = False
    final_done: bool = False
    feature_done: bool = False
    thin_done: bool = False
    contact_s: float | None = None  # smoothed contact row: the distance (and so the steps) is read from it
    present_run: int = 0  # consecutive analysed frames this track was matched
    # confirmation: consecutive analysed frames holding the same role (v26.1.5)
    role: str = "none"
    role_run: int = 0
    mem_id: int | None = None  # world-memory object this track was matched to (v26.1.7)
    linked_t: float = 0.0  # when it was matched to it
    under_last: float | None = None  # last time a curb/crosswalk track had its contact under our feet
    under_fired: bool = False
    dhist: list[tuple[float, float]] = field(default_factory=list)  # (t, depthM) of the depth experiment
    # (t, lateral m, distance m, heading deg): v26.1.11 own sideways velocity
    lhist: list[tuple[Any, ...]] = field(default_factory=list)
    lp_strong_t: float | None = None  # last time the lane part had a flat base
    lane_part: bool = False  # track of a wall's / building's lane part (v26.1.16 follow-up)
    # smoothed speed along the line of sight over the ground (m/s, + = towards us), v26.1.11
    along_s: float | None = None
    along_t: float = 0.0
    # frames it held role "feature" in the lane, not along the path: a real crossing (v26.1.11)
    feature_frames: int = 0
    # announced as "approaching" (v26.1.12): the one re-announcement after an earlier phrase
    approach_done: bool = False
    # motion state with hysteresis: "still" | "approach" | "recede" | "side" | None (v26.1.12)
    mstate: str | None = None
    # consecutive analysed frames the item was a proximity item (v26.1.13 follow-up)
    prox_run: int = 0
    context_seen: bool = False  # the track has been a context item (v26.1.16)
    # a static danger that may be followed on in the map once the image loses it (v26.2.1)
    ghost_src: Item | None = None
    ghost_t0: float | None = None  # since when it has been a ghost
    still_t0: float | None = None  # since when |own along speed| < standingMps without a break (v26.1.12)
    # (v26.2.12) the previous frame's measured distance and when: a jump in it is a measurement glitch
    d_prev: float | None = None
    d_prev_t: float = -math.inf
    df_prev: float | None = None  # ... the same for the final distance (after the map / solid snap)
    df_prev_t: float = -math.inf
    # ... the last frame whose distance jumped (the motion history is cut, a thin item stays quiet)
    jump_t: float = -math.inf
    # (v26.2.12) (distance m, clock quarter, steps, t) of the last danger phrase for this track (re-announcement)
    said: tuple[Any, ...] | None = None


def trusted_track(wtracks: Any, tid: int, t: float) -> dict[str, Any] | None:
    e = wtracks.lookup(tid, t)
    return e if (e is not None and e["trusted"]) else None
