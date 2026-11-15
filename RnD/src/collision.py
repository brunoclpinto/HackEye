"""Collision context, hazards and audio warning events from class grids (v26.1.13).

Why this was rewritten
----------------------
v26.1.0 used a fixed trapezoid corridor and said "wall, 1 o'clock" thirty
times: a wall *alongside* the path clipped the corridor and segmentation
fragmented it into many short tracks. v26.1.1 replaces the corridor with the
real walking region and replaces "warn about every obstacle" with a small
speech policy.

Model
-----
* **Input** is a stack of semantic class grids already mapped 1:1 onto the
  video frame (CONTRACTS.md section 1), so grid (row, col) -> normalised (y, x).
* **Walking region.** The surface under the feet is the largest hint about
  where the user can really go. We take the majority surface class in a small
  box at the bottom centre (the "seed"), flood-fill the 4-connected region of
  that surface group (plus markings, curbs, covers inside it) and call it the
  walking region. Per grid row its left/right bounds are the boundary.
* **Horizon from the region.** Parallel path edges converge at the horizon, so
  lines fitted to the region's left and right bounds intersect on the true
  horizon row. That removes the tilt/mount guess; the preset is only a
  fallback when the region is not a converging shape.
* **Flat-ground pinhole distance.** A point on the ground seen ``dy`` rows below
  the horizon is at ``H * f / dy`` metres (H = camera height, f = focal length
  in pixels). The contact point (lowest pixel) of an item therefore gives its
  distance, and its column gives its lateral offset ``(x - 0.5) * W * d / f``.
* **Steps, not metres.** What the user can act on is "how many steps". The
  spoken number is ``time-to-reach * cadence`` = ``(d / closing) * cadence``.
  Distance ``d`` and closing speed ``closing = -dd/dt`` are both proportional
  to the assumed camera height H, so H cancels, and so does step length: the
  number depends only on the image-space approach rate and the measured
  cadence. Only when cadence or closing is unknown do we fall back to
  ``d / step_length``, which does depend on both.
* **Ego motion.** Cadence is the step rate seen in the vertical camera bob
  (spectral peak in 0.8-3.5 Hz). A chest camera bobs asymmetrically, so the
  dominant peak is often the *stride* (left+right, ~1 Hz) and the step rate is
  its second harmonic; ``estimate_cadence`` is stride aware (see
  ``_window_cadence``). Speed is the median closing speed of static items (the
  world is stationary, so it all approaches at our speed). Step length =
  speed / cadence when both are known. Heading integrates horizontal image
  motion, to notice turns.
* **Three roles** for an item: *danger* (static or parked item inside the
  walking region where we will actually hit it, or a mover approaching us),
  *feature* (curb, crosswalk, ... crossing the danger lane) and *context*
  (static item at the region edge: the "wall at 1 o'clock" spatial awareness).
* **Less is more.** Context and the surface are spoken once and then stay
  silent until the path changes (a turn, a surface change) or they have not
  been seen for a long time. Danger is spoken only within ``dangerSteps``,
  then accelerating panned beeps, then one final call at ``finalSteps``. At
  most one phrase per frame, and a global minimum gap except for final calls.

v26.1.1 revisions (CONTRACTS.md section 7a) and further robustness
------------------------------------------------------------------
* Steps are ``distance * cadence / ego speed`` (fallback ``distance / step length``):
  a proximity measure, not a per-object time to contact.
* A track keeps contact *rows*; closing speed re-projects them through the current
  smoothed horizon, so horizon wobble cannot fake motion. Unknown movers count as
  static and never "approach".
* Things that run along the path (a wall's or median's base spans a long stretch of
  floor) are boundary, never danger or feature; a feature must cross the lane.
* Only ``contextSpeak`` labels are spoken; surface only for road/rail changes.

v26.1.5 (CONTRACTS.md section 12.3, from the user's review of real footage)
---------------------------------------------------------------------------
* Danger, final and feature speech need the track to hold that role for ``roles.confirmFrames``
  consecutive analysed frames (a one-frame false detection is never spoken).
* The final call includes the clock: "person, 12 o'clock, 2 steps".
* A static/parked/unknown-motion item is danger only if its contact point (its lowest pixel)
  is in the danger lane inside the walking region; pixels intruding from a car beside the path
  do not count.
* Context memory is keyed by label family ("vehicle"/"parked car" are one), not by side; it is
  kept while seen within ``forgetAfterSeconds`` and cleared by a turn.
* Newly announceable context labels are one grouped phrase ("obstacle at 12, building at 2"),
  nearest first, at most ``speech.contextMaxItems``. Barrier-type classes and sidewalk-obstacle
  are spoken as "obstacle"; "building" and "obstacle" are in ``contextSpeak``.
* Start summary: the first context phrase of a run and after a turn needs only the confirmation
  (no track age, no adopted surface) and is held ``speech.summaryHoldSeconds`` so one phrase
  covers the whole first view.

v26.1.6 (CONTRACTS.md section 14, from the user's second review)
-----------------------------------------------------------------
* **Gait-calibrated scale k.** The pinhole metres assume a camera height and field of view that
  are only roughly right (real footage: 2-4x too small). Walking gives a ruler: the median
  cadence times a prior step length (0.70 m) is the ego speed in real metres, the median of the
  witness-based raw ego speed is the same speed in model metres, and their ratio is k. All
  distances/laterals/areas are multiplied by k (equivalently, the camera height is ``H * k``);
  the raw closing speeds used for it stay uncalibrated, so there is no feedback loop. k is held
  while the user stands still and is 1 until the first estimate.
* Steps are ``distance / step length`` with the prior (or per-recording) step length: no division
  by a noisy instantaneous ego speed, so they do not swing.
* Context only when near (``contextMaxSteps``, ``contextMaxLateralM``). People/riders/animals are
  movers unless measured stationary, with a wider and earlier danger zone. A crosswalk is a
  landmark (announced once, direction and steps). Thin objects (poles, lights, signs) are
  warned about when noticed ("beware poles"). Phrases have no "o'clock" and same-label items are
  merged ("person at 1 and 2"). A surface change needs persistence plus a curb/crosswalk
  crossing. Beeps are parking-sensor beeps for collision tracks only (constant pitch, interval
  by steps, gapless tones when very close) and are summarised as ``beeps`` episode events.

v26.1.7 (CONTRACTS.md section 15, from the user's third review: 27 right, 6 "should not be said")
------------------------------------------------------------------------------------------------
* **World memory by dead reckoning** (``_WorldMemory``). Identity used to exist only as image tracks, so a
  fragmented detection or a camera turn made the same real object "new" and it was announced again. We now
  integrate the user's ground position (calibrated ego speed = cadence x step length, along the heading of the
  motion track) and store every announced object (any role, every member of a "poles" cluster or a grouped
  context phrase) as ``(label family, world x/y)``. A candidate of the same family within
  ``memory.matchRadiusM`` + 10 percent of its distance of a remembered object is that object and is not
  announced again; a track that matched keeps the link and refreshes the object's position. Objects are
  forgotten when passed (behind the user) or more than ``memory.maxRangeM`` away. Without motion data the old
  per-track and per-label rules apply unchanged.
* **Final call only for the never-named.** A final (<= 3 steps) is spoken only when no remembered object
  matches; otherwise the (unchanged) parking-sensor beeps carry the proximity.
* **Every announced object phrase has position and distance**: "poles at 11 and 1 in 8", "building at 2 in 6",
  "person approaching at 12 in 6". Steps are left out only when the distance is unknown.
* **Stricter surface evidence.** A surface change is announced only when a curb or crosswalk really passed
  *under* the user (``_SurfaceTracker``, ``surfaces.passUnderRows``) and the new surface holds >= 70 percent of a
  sliding 10 s window; otherwise the old surface is kept silently (the region still follows the model).

v26.1.11 (CONTRACTS.md sections 5-7, from the user's fourth review: 52 right, 2 wrong, 9 "should not be said")
------------------------------------------------------------------------------------------------------------
* **Motion state is spoken** for people and riders ("person standing at 12 in 7", "cyclist approaching at 12" without a
  distance, "person moving away at 12"), from the mover's own ground velocity (``_assign_role`` / ``SpeechPolicy._kind``).
* **Only a collision course is a danger for a measured mover** (``_on_collision_course``): where it will be when we get
  there (closing speed, sideways velocity), not where it is now; vehicles are never context (``contextSpeak``).
* **Stationary user** (``estimate_stationary``, from the residual image flow of ``egoflow.py``): the ego speed is 0 and
  nothing static is announced; only a mover on a collision course is.
* **Ego speed** is held when the cadence drops out (no witness guess), the cadence refine cannot leave its band, depth
  closing rates are put on the gait's scale, a curb / crosswalk is said once per crossing and a surface change needs a
  lane-crossing curb / crosswalk that belongs to the change (``_SurfaceTracker``).

v26.1.12 (CONTRACTS.md sections 6-7, from the user's fifth review: 12 right, 3 wrong, 2 "should not be said")
-----------------------------------------------------------------------------------------------------------
* **Movers within 10 steps** (``movingDangerSteps``); **beeps only on a collision course and within 5 steps**
  (``tones.maxSteps``, ``bySteps``): farther away the speech carries the warning.
* **"approaching" is announced once more** for a mover that was announced before (``_Track.approach_done``).
* **Motion states say nothing when unsure** (``_motion_state``): "standing" needs |speed along the line of sight| < 0.3 m/s
  held for 1 s and no sideways motion; approaching / moving away need 0.4 m/s; in between the plain phrase is said. The
  bearing rate across the view (``_cross_velocity``) is too weak to name a direction; it only vetoes "standing".
* **Unknown motion near the user beeps** (a person within 5 steps and the 3 m zone), a person measured approaching
  within 5 steps beeps at arm's length, and a person's motion is measured after 0.45 s (``peopleMotionMinSeconds``).

v26.1.13 (CONTRACTS.md sections 7.9, 7.10, 7.13, from the user's sixth review: 36 right, 10 "should not be said", 2 added)
------------------------------------------------------------------------------------------------------------------
* **People are spoken once at 5-10 steps** (``peopleSpeakMinSteps`` 4.5, ``movingDangerSteps``), inside ``peopleSpeakLateralM``
  (2.75 m), whatever their direction, with the distance ("person approaching at 12:15 in 9"); closer they only beep.
* **Riders and vehicles approaching on or near the path are announced as early as possible** (``_fast_warning``: meeting within
  ``fastWarnSeconds``, no step limit), without a distance ("cyclist approaching at 11"). A rider's position is the middle of its
  lowest row.
* **A soft proximity sound** (v26.1.13 follow-up): a person / animal measured approaching, within ``proximitySteps`` (5) and
  ``proximityLateralM`` (2.6 m), on no collision course, gets a lower, softer double chirp at a fixed slow rhythm
  (``tones.proximity``); riders and vehicles never; the parking beeps always win and the track switches to them on a course.
* **Beeps only on a real collision course** (``beepLateralM`` 0.9 m on the lateral position, or on the predicted one for a measured
  mover): no more unknown-motion or arm's-length beeps.
* **Context beside the path** within 2.5 m (3.0 m within 3 steps); the motion states use the median ego speed of 3 s (``_robust_speed``).

v26.1.14 (CONTRACTS.md sections 14.1.9, 14.1.11, from the user's request "warn when stepping into / out of a crosswalk")
------------------------------------------------------------------------------------------------------------------
* **Crosswalk enter / exit tones.** ``_CrosswalkTracker`` follows the crosswalk-class fraction of the surface seed box (bottom
  centre, under the user's feet): >= ``enterFraction`` for ``enterSeconds`` while walking = in, <= ``exitFraction`` for
  ``exitSeconds`` = out. Tone kinds ``crosswalk-enter`` (one deep, long tone) and ``crosswalk-exit`` (two deep short tones),
  ``tones.crosswalk``; the speech phrases are unchanged.

v26.2.12 (CONTRACTS.md section 7.11d, from the user's review 9 and notes 2026-11-07; every rule is behind a config key)
------------------------------------------------------------------------------------------------------------------
* **c2 is the default** (map source, IMU heading / cadence, fused horizon); **the step length comes from the GPS** when it has a good fix long
  enough (``ego.stepLength``); **voice**: nothing spoken about a beeping item <= 2 steps away (``speech.minVoiceSteps``), thin statics only inside
  the collision zone (``speech.zoneOnly``), a thin item whose distance jumps stays quiet (``thinStableS``), a static announced before is announced
  again when its place changed a lot (``speech.reannounce``), co-located collision items are one phrase with the closest one's numbers
  (``speech.colocatedM``); **predictive**: the advance is capped (``maxAdvanceM``) and the clock does not swing (``clockHoldQuarters``);
  **distance jumps** cut a vehicle's motion history (``distance.jump``); a pole under a canopy is a **tree** (``tree``); a wall that is being
  followed starts no new beep episode (``beeps.follow``); **"blocked ahead"** from the map (``blocked``); hazards carry ``bboxFull`` /
  ``outlineFull`` (the whole component above the horizon too).

Beyond the contract (small constants at the top / config): a track must live
``MIN_TRACK_AGE_S`` before it may speak or beep (v26.1.15: not during the first
``WARMUP_S`` of a run, where the 2-frame confirmation is the only gate); during that start the horizon
is the mean of the raw estimates so far (else the mount / body preset); the last good horizon is held ``HORIZON_HOLD_S`` when an estimate
fails; a repeated label is quiet for ``LABEL_COOLDOWN_S``; context "ahead" matches
"left"/"right" of the same label; ego speed is judged only from pole-like static
items (``_speed_witness``); an implausible speed/cadence step length is dropped, not
clamped; a static item that does not close at our speed is a line along the path;
a danger needs ``roles.minObstacleAreaM2`` (a 15 px blip is not an obstacle).

Pure logic (numpy, scipy, stdlib) so it can be ported to Swift.
"""

from __future__ import annotations

import math
import time

import numpy as np

from common_paths import find_common_dir  # noqa: F401  (worldmap calls collision.find_common_dir)
import faceedge  # noqa: F401  (kept: the legacy facade stays imported here)
import groundfuse
import sensors as sensor_lib
import worldtracks
from engine.core.clock import (  # noqa: F401
    bearing_deg,
    clock_from_bearing,
    clock_quarter,
    clock_text,
    pan_from_bearing as _pan_from_bearing,
    quarter_of_hour as _quarter_of_hour,
)
from engine.core.geom import (  # noqa: F401
    Box,
    focal_px,
    ground_distance_m,
    iou,
    lateral_m,
    round_opt as _r,
    steps_to,
)
from engine.core.types import (  # noqa: F401
    LANE_PART_ID_BASE,
    POINT_ASPECT,
    Item as _Item,
    Region,
    Track as _Track,
    trusted_track as _trusted_track,
)
from engine.core.log import WARNED as _WARNED, log as _log, warn_once as _warn_once  # noqa: F401
from engine.core.settings import (  # noqa: F401
    AUTO_FISHEYE_HFOV_DEG,
    DISTANCE_SOURCES,
    HORIZON_HOLD_S,
    MIN_TRACK_AGE_S,
    OBJECT_DISTANCES,
    SIDE_SIGN,
    WARMUP_S,
    CollisionSettings,
    resolve_projection,
    resolve_settings,
)
from engine.core.groundgeom import (  # noqa: F401
    FrameGeo as _FrameGeo,
    bottom_point as _bottom_point,
    ego_frame as _ego_frame,
    frame_geometry as _frame_geometry,
    ground_dist as _ground_dist,
    lateral_of as _lateral_of,
    walking_axis_offset_m as _walking_axis_offset_m,
)

from engine.core.classes import (  # noqa: F401
    ITEM_GROUPS,
    NO_DATA,
    ClassIds,
    FOUR_CONNECTIVITY as _4_CONNECTIVITY,
    resolve_class_ids,
)

from engine.depthscale.anchors import (  # noqa: F401
    DepthAnchor as _DepthAnchor,
    InitialAnchor as _InitialAnchor,
    PlaneAnchor as _PlaneAnchor,
    PlaneFit as _PlaneFit,
    ground_anchor as _ground_anchor,
    plane_fit as _plane_fit,
)
from engine.depthscale.scale import (  # noqa: F401
    DepthScale as _DepthScale,
    ground_depth_distance as _ground_depth_distance,
    item_depth_m as _item_depth_m,
)


LAST_WORLD_TRACKS_MS: list[float] = []     # ms of the world-track step per frame of the last run_collision (metrics tool; not in the output)


def _bottom_distance(ob, horizon: float, cam_h: float, gh: int, f: float) -> float:
    """Forward distance of the last image row on the centre column (the ground seen at the bottom), as the map's ``objectClearBottomM`` uses it."""
    try:
        if ob is not None and getattr(ob, "geometry", False):
            d = float(groundfuse.ground_point(ob.geo, float(ob.gh), ob.gw / 2.0, float(horizon), ob.cam_h)[0])
            return d if math.isfinite(d) else 0.0
        return float(cam_h) * f / (max(1.0 - float(horizon), 1e-6) * gh)
    except Exception:
        return 0.0


def _hidden_fn(ob):
    """``(fwd, right) -> bool``: the online map's cell there is hidden behind a building in this frame (None without a map)."""
    if ob is None or getattr(ob, "ray_hidden", None) is None:
        return None
    hid = ob.ray_hidden

    def hidden(fwd: float, right: float) -> bool:
        r, c = ob.orow - int(round(fwd / ob.cell)), ob.oc + int(round(right / ob.cell))
        return 0 <= r < hid.shape[0] and 0 <= c < hid.shape[1] and bool(hid[r, c])
    return hidden


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

# Settings moved to engine.core.settings (re-exported here, same objects).
from engine.core.config import load_config  # noqa: E402, F401  (plain module attribute: tests replace it)


# --------------------------------------------------------------------------
# Ego motion: cadence
# --------------------------------------------------------------------------

from engine.gait.scale import GpsSpeedScale, Scale as _Scale  # noqa: E402, F401
from engine.egosignals.cadence import (  # noqa: E402, F401
    CORROBORATED_RATIO_FRAC,
    estimate_cadence,
    estimate_stationary,
    hold_last as _hold_last,
    peak as _peak,
    refine as _refine,
    spectrum as _spectrum,
    window_cadence as _window_cadence,
)
from engine.egosignals.series import (  # noqa: E402, F401
    IMU_STATIONARY_DEFAULT,
    auto_stationary as _auto_stationary,
    gps_at as _gps_at,
    motion_series as _motion_series,
    nearest as _nearest,
    sensor_heading as _sensor_heading,
    sensor_series as _sensor_series,
)
from engine.surface.horizon import HorizonGravity, estimate_horizon  # noqa: E402, F401
from engine.surface.region import smooth_bounds as _smooth_bounds, walking_region  # noqa: E402, F401
from engine.surface.trackers import (  # noqa: E402, F401
    CrosswalkTracker as _CrosswalkTracker,
    SurfaceTracker as _SurfaceTracker,
    seed_fraction as _seed_fraction,
)


# --------------------------------------------------------------------------
# Walking region
# --------------------------------------------------------------------------



# --------------------------------------------------------------------------
# Per-frame geometry and items
# --------------------------------------------------------------------------



from engine.detection.items import (  # noqa: E402, F401
    detect_items,
    lane_part_item as _lane_part_item,
    split_people as _split_people,
    tree_trunk as _tree_trunk,
)



# --------------------------------------------------------------------------
# Tracking
# --------------------------------------------------------------------------

from engine.tracking.coast import Coast as _Coast  # noqa: E402, F401
from engine.tracking.match import match as _match  # noqa: E402, F401
from engine.tracking.velocity import (  # noqa: E402, F401
    closing_mps as _closing_mps,
    cross_velocity as _cross_velocity,
    depth_closing as _depth_closing,
    lateral_velocity as _lateral_velocity,
)




# --------------------------------------------------------------------------
# Ego state
# --------------------------------------------------------------------------

from engine.egostate.ego import Ego as _Ego  # noqa: E402, F401


from engine.memory.world import WorldMemory as _WorldMemory  # noqa: E402, F401
from engine.motion.own import OwnMotion as _OwnMotion  # noqa: E402, F401
from engine.motion.state import motion_state as _motion_state, robust_speed as _robust_speed  # noqa: E402, F401


# --------------------------------------------------------------------------
# Steps and roles
# --------------------------------------------------------------------------

from engine.roles.roles import (  # noqa: E402, F401
    assign_role as _assign_role,
    course as _course,
    fast_warning as _fast_warning,
    is_static_like as _is_static_like,
    not_approaching as _not_approaching,
    on_collision_course as _on_collision_course,
    pole_like as _pole_like,
    sideways_mps as _sideways_mps,
    speed_witness as _speed_witness,
)


# --------------------------------------------------------------------------
# Movers that left the image (v26.2.2): _Coast moved to engine.tracking.coast (re-exported above)
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Speech policy (engine.speech: policy + text / context / walls / movers mixins)
# --------------------------------------------------------------------------

from engine.speech.policy import SpeechPolicy  # noqa: E402, F401
from engine.speech.walls import (  # noqa: E402, F401
    WallFollow as _WallFollow,
    followed_wall as _followed_wall,
    passing_close as _passing_close,
)


# --------------------------------------------------------------------------
# Tones
# --------------------------------------------------------------------------

from engine.sounds.tones import (  # noqa: E402, F401
    COLLISION_KINDS,
    SIDE_WORD,
    SOUND_KINDS,
    collision_kind,
    crosswalk_tones as _crosswalk_tones,
    resolve_sounds,
    tone_events as _tone_events,
    tone_interval as _tone_interval,
)


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

from engine.output.hazards import (  # noqa: E402, F401
    hazard_dict as _hazard_dict,
    hazard_json as _hazard_json,
    lane_polygon as _lane_polygon,
    region_rows as _region_rows,
)
from engine.output.outline import (  # noqa: E402, F401
    DIRS as _DIRS,
    OUTLINE_EPS_PX,
    OUTLINE_MAX_POINTS,
    dp_open as _dp_open,
    item_full,
    item_outline,
    simplify_polygon,
    trace_outline,
)

from engine.worldmap.staticmap import (  # noqa: E402, F401
    StaticMap as _StaticMap,
    mute_solid as _mute_solid,
    set_position as _set_position,
)
from engine.worldmap.source import map_source as _map_source  # noqa: E402, F401


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Static items on the fused world map (v26.2.1)
# --------------------------------------------------------------------------



def _predict_velocities(items: list[_Item], wtracks, t: float, theta: float, pcfg: dict) -> None:
    """Predictive speech: a mover with a trusted, moving world track carries its velocity in our frame (``pred_v``)."""
    top = float(pcfg.get("maxMoverMps", 12.0))
    for it in items:
        if it.group != "moving" or it.lane_part or it.ghost:
            continue
        e = _trusted_track(wtracks, it.track_id, t)
        if e is None or e["static"] or math.hypot(e["vx"], e["vy"]) > top:
            continue
        it.pred_v = _ego_frame((0.0, 0.0, math.degrees(theta)), e["vx"], e["vy"])


def run_collision(grids, times, class_names, config, settings, motion=None, depth=None,
                  window=None, sounds=None, worldmap_config=None, progress=None, sensors=None) -> tuple[dict, dict]:
    """Per-frame hazards and the speech/tone event list. ``motion`` = {"t","dx","dy"} arrays or None.

    ``sensors`` (v26.2.11): the recording's device telemetry (``sensors.extract``, on the recording's time line) or None; with it the heading
    comes from the gyro (``ego.headingSource``), the cadence / stationary from the accelerometer, and the ego block gains the gravity pitch /
    roll and the GPS fix. Without it the pass is exactly the v26.2.10 one.

    ``sounds`` (v26.1.16): the Lab's sound profile ({"kinds": {...}, "speechRate"}, see ``resolve_sounds``) or None = the defaults of
    ``collision.json`` ``tones``; it sets the pitch, duration and repeat interval of the tone events.

    ``window`` (None = the grids cover the whole frame) = {"c0", "cols", "x0", "y0", "w", "h", "srcW", "srcH"}: the grids
    always span the FULL frame (bearings, focal length, principal point, seed box, horizon stay those of the source lens);
    cells outside the analysed window hold ``NO_DATA`` and the depth maps are NaN there. Only the horizon fit needs to
    know the window edges (they are crops, not path edges), and the output records the window.

    ``depth`` = {"t": (N,), "depth": (N, Dh, Dw), "units": "metric" | "relative",
    optional "anchor": "per-frame" | "initial" | "none"} or None (anchor default: per-frame for relative, none for metric): one depth map per
    analysed frame (nearest ``t``); missing units = metric (metres). Relative depth (scale only, drifting per
    frame) is anchored every frame on the ground under our feet (``_DepthAnchor``) and levelled by walking
    (``_DepthScale``, ground k until its first estimate); with no anchor ``depthM`` is null. It is always reported as ``depthM``; it drives the distances only when
    ``settings.distance_source`` is "depth"."""
    grids = np.asarray(grids)
    times = np.asarray(times, dtype=float)
    n, gh, gw = grids.shape
    ids = resolve_class_ids(config, class_names)
    f = focal_px(gw, settings.hfov_deg)
    geo_cfg, roles, trk = config["geometry"], config["roles"], config["tracking"]
    lane_half = geo_cfg["laneHalfWidthM"]
    labels = config.get("spokenLabels", {})
    parked_labels = config.get("parkedLabels", {})
    default_step = geo_cfg["defaultStepLengthM"]
    lat_off = _walking_axis_offset_m(settings)
    ego_cfg = config["ego"]
    # steps and the gait calibration use this step length: the per-recording value overrides the prior
    step_len = settings.step_length_m if settings.step_length_m is not None else float(
        ego_cfg.get("priorStepLengthM", default_step))
    step_len0 = step_len
    sl_cfg = ego_cfg.get("stepLength") or {}
    step_source = "user" if getattr(settings, "step_length_user", False) else "prior"
    step_windows_s = 0.0
    step_info = None
    gps_cfg = ego_cfg.get("gps") or {}
    gps_scale = GpsSpeedScale(gps_cfg) if (sensors is not None and ego_cfg.get("sensors", True) and gps_cfg.get("enabled", True)
                                           and gps_cfg.get("speedScale", False)) else None

    dist_cfg = config.get("distance", {})
    # anchor horizon: "estimated" (the frame's smoothed horizon), "fixed" (the mount preset's), or a row fraction
    _ah = dist_cfg.get("anchorHorizon", "estimated")
    anchor_horizon = (settings.horizon_default if _ah == "fixed" else float(_ah) if isinstance(_ah, (int, float)) else None)
    depth_rows_frac = float(dist_cfg.get("depthLowestRowsFrac", 0.25))
    source = getattr(settings, "distance_source", "ground")
    projection = getattr(settings, "projection", "rectilinear")
    # Rays for back-projecting depth-model output in the plane fit: "lens" (default, the resolved projection) or
    # "pinhole". Depth models are trained on pinhole images; on 4929 pinhole rays nevertheless fitted worse (level
    # further from the reference, gait check 1.87 vs 1.40), so "lens" stays the default -- see DECISIONS v26.1.10 f-up 5.
    depth_rays = "rectilinear" if dist_cfg.get("depthRayModel", "lens") == "pinhole" else projection
    depth_t = depth_maps = None
    anchor_mode = None
    if depth is not None:
        anchor_mode = depth.get("anchor") or ("per-frame" if depth.get("units", "metric") == "relative" else "none")
        if anchor_mode not in ("per-frame", "initial", "plane", "none"):
            anchor_mode = "none"
    relative = anchor_mode in ("per-frame", "initial", "plane")      # anchored on the ground (else plain metric metres)
    plane = anchor_mode == "plane"           # scale from the ground plane + camera height; no gait level (gait is a check)
    dscale = _DepthScale(ego_cfg, dist_cfg) if relative else None
    gait_check = _DepthScale(ego_cfg, dist_cfg) if plane else None
    anchor = (_PlaneAnchor(dist_cfg, settings.camera_height_m) if plane else
              _InitialAnchor(dist_cfg) if anchor_mode == "initial" else _DepthAnchor(dist_cfg)) if relative else None
    # level c (``_DepthScale``): mode "continuous" | "freeze", and the prior used before its first estimate.
    # The prior (number | "ground") only applies to the initial anchor; per-frame depth borrows the ground k.
    level_mode = dist_cfg.get("depthLevelMode") or dist_cfg.get("levelModeByAnchor", {}).get(
        anchor_mode, "freeze" if anchor_mode == "initial" else "continuous")
    level_prior = "ground"
    if anchor_mode == "initial":
        level_prior = settings.depth_level_prior if getattr(settings, "depth_level_prior", None) is not None \
            else dist_cfg.get("depthLevelPrior", "ground")
    if dscale is not None:
        dscale.freeze = level_mode == "freeze"
    recalibrate = anchor_mode in ("initial", "plane") and bool(dist_cfg.get("recalibrateOnPathChange", False))
    anchor_rows = float(trk["motionMinRowsBelowHorizon"])
    # v26.2.3: ground ray + depth (distance.objectDistance / useHorizon); active for depth distances with the horizon on
    gd_cfg = groundfuse.settings(dist_cfg)
    # v26.2.7 (distance.itemLens): "depth" (default) = an item with a depth distance takes its lateral from the lens ray at that distance (the
    # ground-distance fallback, tuned with the gait scale k on the pinhole formulas, stays as it was); "all" = also the ground distance of every
    # contact row through the lens (then k must not absorb the lens factor any more: experiment); "off" = pinhole laterals
    item_lens_mode = str(dist_cfg.get("itemLens", "depth"))
    lens_all = item_lens_mode == "all" and source == "depth"
    item_lens = (groundfuse.Geometry(gh, gw, settings.hfov_deg, projection, settings.camera_height_m)
                 if projection == "fisheye" and item_lens_mode in ("depth", "all") else None)
    obj_mode = groundfuse.resolved_mode(getattr(settings, "object_distance", "depth"), getattr(settings, "use_horizon", True))
    gd_on = source == "depth" and depth is not None and obj_mode != "depth"
    corrector = hsig = surf_lut = None
    if gd_on:
        import worldmap
        gd_geo = groundfuse.Geometry(gh, gw, settings.hfov_deg, projection, settings.camera_height_m)
        corrector = groundfuse.Corrector(gd_cfg, gd_geo)
        hsig = groundfuse.HorizonSigma(gd_cfg, gh)
        surf_lut = worldmap.class_kinds(worldmap_config if worldmap_config is not None else worldmap.load_config(), list(class_names)) == worldmap.KIND_SURFACE
    if depth is not None and len(depth["t"]):
        depth_t = np.asarray(depth["t"], dtype=float)
        depth_maps = depth["depth"]

    win_bounds = (0.0, 1.0)
    if window is not None:
        win_bounds = (window["c0"] / gw, (window["c0"] + window["cols"]) / gw)
    mser = _motion_series(motion, settings.hfov_deg, ego_cfg)
    flow_hcum = None if mser is None else mser[2]
    sser = _sensor_series(sensors, mser, times, ego_cfg, settings.hfov_deg) if (sensors is not None and ego_cfg.get("sensors", True)) else None
    heading_source = "flow"
    cadence_source = "image"
    stationary_source = "image"
    if sser is not None:
        mt_s = sser["mt"]
        c_src, st_src, h_src = (ego_cfg.get(k, "auto") for k in ("cadenceSource", "stationarySource", "headingSource"))
        flow_stat = None if mser is None else mser[3]
        cad_s = sser["cad"] if (c_src in ("auto", "imu") or mser is None) else mser[1]
        cadence_source = "imu" if cad_s is sser["cad"] else "image"
        if flow_stat is None or st_src == "imu":
            stat_s, stationary_source = sser["stat_imu"], "imu"
        elif st_src == "image":
            stat_s = flow_stat
        elif st_src == "both":
            stat_s, stationary_source = flow_stat & sser["stat_imu"], "both"
        elif st_src == "either":
            stat_s, stationary_source = flow_stat | sser["stat_imu"], "either"
        else:      # auto
            stat_s, stationary_source = _auto_stationary(flow_stat, sser["stat_imu"])
        _sensor_heading(sser, stat_s, ego_cfg)
        if h_src in ("auto", "imu", "gyro"):
            # v26.2.12: "auto" and "imu" are the gyro heading WITH the slow GPS course correction (ego.gps.course) -- the resolved label says
            # "imu+gps" when at least one GPS update was applied; "gyro" is the pure gyro heading (label "imu")
            use_gps = (h_src != "gyro" and bool((ego_cfg.get("gps") or {}).get("course", True))
                       and bool((ego_cfg.get("gps") or {}).get("enabled", True)))
            hcum_s = sser["heading_gps"] if use_gps else sser["heading_imu"]
            heading_source = "imu+gps" if use_gps and sser["info"].get("gpsUpdates") else "imu"
        else:
            hcum_s = flow_hcum if flow_hcum is not None else sser["heading_imu"]
        mser = (mt_s, cad_s, hcum_s, stat_s)
        # v26.2.12 (O18): the step length from the GPS (median of GPS speed / step cadence over the moving, good-fix samples); a typed one wins
        if sl_cfg.get("source", "auto") == "auto" and not getattr(settings, "step_length_user", False):
            gst = sensor_lib.gps_step_length(sser["s"], mt_s, cad_s, stat_s, {**(ego_cfg.get("gps") or {}), **sl_cfg})
            if gst is not None:
                step_len = step_len0 = gst["stepM"]
                gps_scale = None                       # the slow GPS speed scale would count the same correction twice
                step_source, step_windows_s = "gps", round(gst["windowsS"], 1)
                step_info = {k: round(v, 3) if isinstance(v, float) else v for k, v in gst.items()}
    ego = _Ego()
    surface = _SurfaceTracker(config["surfaces"])
    crosswalk = _CrosswalkTracker(config["crosswalk"])
    cw_name = config["crosswalk"].get("class", "crosswalk")
    cw_class = list(class_names).index(cw_name) if cw_name in class_names else None
    cw_marks: list[tuple[float, str]] = []
    scale = _Scale(ego_cfg, step_len)
    policy = SpeechPolicy(config)
    world = _WorldMemory(config.get("memory", {}), enabled=mser is not None)
    policy.world = world
    coast = _Coast(config.get("coast", {}))
    wtracks = worldtracks.WorldTracks(config.get("worldTracks"), lane_half, settings.hfov_deg)     # v26.2.9: shadow mode, feeds no decision
    _op = ego_cfg.get("onePose", "auto")        # v26.2.11: the world memory and the world tracks use the online map's corrected pose
    one_pose = bool(sser is not None) if _op == "auto" else _op in ("on", True)
    smap = None                                # v26.2.1: the online world map the static rules read (roles.staticSource "map")
    if roles.get("staticSource", "image") == "map" and n:
        import worldmap
        smap = _StaticMap(worldmap, grids, times, class_names, config, settings, lat_off, projection, source, lane_half, step_len, obj_mode, wcfg=worldmap_config)
    map_ms: list[float] = []
    jump_cfg = config.get("distance", {}).get("jump") or {}
    stable_s = float(config["speech"].get("thinStableS", 0.0))
    follow_cfg = config.get("beeps") or {}
    follow: dict = {}                          # (family, side) -> {"t": last activity, "t_real": last real beep, "lat": the episode's lateral}
    follow_cfg = {**follow_cfg, **(follow_cfg.get("follow") or {})}
    wfollow = _WallFollow(follow_cfg)          # v26.2.13: the ratio rule (the distance closes less than the walking speed)
    pass_cfg = follow_cfg.get("passing") or {}  # v26.2.13: soft beeps for a person passing close
    full_all = bool((config.get("output") or {}).get("fullAllItems", False))
    mover = _OwnMotion(config.get("motion") or {})     # v26.2.14: the own velocity of the movers
    policy.motion_on = mover.on
    blk_cfg = config.get("blocked") or {}
    blk_run, blk_last_t, blk_pos, blk_kind = 0, -math.inf, None, None
    blk_seen_t, blk_open = -math.inf, False         # follow-up (O26): one phrase per blockage; it ends after clearS s without one
    meas_hist: list[tuple[float, float]] = []
    meas_win = float((config["speech"].get("predictive") or {}).get("measuredWindowS", 1.5))
    reset_classes = frozenset(jump_cfg.get("resetClasses", ("vehicle", "rider")))
    tree_cfg_run = config.get("tree") or {}
    src_cfg = config.get("source") or {}                   # v26.2.11: where the items' positions come from
    map_mode = str(src_cfg.get("mode", "image")) == "map" and smap is not None
    src_counts = {"map": 0, "track": 0, "image": 0}
    policy.speech_rate = resolve_sounds(config["tones"], sounds)["speechRate"]
    under_rows = int(config["surfaces"].get("passUnderRows", 6))
    under_gone_s = float(config["surfaces"].get("passUnderGoneSeconds", 1.5))
    under_min_w = float(config["surfaces"].get("passUnderMinWidth", 0.15))
    tracks: dict[int, _Track] = {}
    next_id = 1
    next_lane_part_id = LANE_PART_ID_BASE            # lane parts have their own id range: they do not shift the ids of the ordinary tracks
    prev_group: str | None = None
    prev_left = prev_right = None
    horizon = settings.horizon_default
    h_state = horizon                         # the image horizon estimate's own state (the gravity horizon never feeds back into it)
    hz_cfg = config.get("horizon") or {}
    hz_source = str(hz_cfg.get("source", "image")) if sser is not None else "image"
    hz_off = HorizonGravity({**hz_cfg, "horizonValidRange": geo_cfg["horizonValidRange"]}, gh, gw, settings.hfov_deg, projection) if hz_source != "image" else None
    raws: list[float] = []
    last_estimate_t = -math.inf
    first_t: float | None = None
    frames_out: list[dict] = []
    frame_collision: list[tuple[_Item | None, set]] = []
    frame_proximity: list[tuple[_Item | None, set]] = []
    events: list[dict] = []
    prev_t = float(times[0]) if n else 0.0
    beep_run = 0                              # consecutive frames with a collision beep driver
    people_classes = frozenset(config["classes"].get("people", []))
    last_hard_pan_t = -math.inf               # the last frame with a hard camera pan (see ``_match`` / ``roles.panSettleSeconds``)
    prev_heading: float | None = None         # camera heading of the previous frame: the scene's pan since then moves the tracks' boxes
    held_speed: float | None = None           # last cadence-based ego speed and when (v26.1.11, item 7)
    held_t = -math.inf
    ego_hist: list[tuple[float, float]] = []  # recent ego speeds for the robust (median) speed of the motion states (v26.1.13)
    ego_hist_t0: float | None = None          # when the current continuous history began (v26.1.15: the window must be full)

    for i in range(n):
        if progress is not None:
            progress(i, n)           # v26.2.10: the Lab's job reports (and may cancel by raising) between frames
        t = float(times[i])
        dt = max(0.0, t - prev_t)
        prev_t = t
        grid = grids[i]

        # 1. walking region (+ debounced surface)
        region = walking_region(grid, ids, config)
        group = None if region is None else region.group
        adopted = surface.update(t, group)
        if adopted is not None:
            policy.surface_adopted(adopted[0], adopted[1], config["surfaces"], adopted[2])
        if group != prev_group:
            prev_left = prev_right = None         # smoothing restarts with a new surface
        prev_group = group
        # 2. horizon, fitted on the raw bounds: averaging a clamped row (0.0) with an
        #    unclamped one would fake an edge and tilt the line
        raw = None if region is None else estimate_horizon(region.left, region.right, config, win_bounds)
        if region is not None:
            region.left = prev_left = _smooth_bounds(prev_left, region.left)
            region.right = prev_right = _smooth_bounds(prev_right, region.right)
        first_t = t if first_t is None else first_t
        warm = t - first_t >= WARMUP_S - 1e-9      # until then: the mean of the raw estimates so far
        if raw is not None:
            raws.append(raw)
            last_estimate_t = t
        horizon = h_state
        if not warm:
            horizon = float(np.mean(raws)) if raws else settings.horizon_default
        elif raw is None and t - last_estimate_t <= HORIZON_HOLD_S:
            pass                                  # a brief failed estimate keeps the last good horizon
        else:
            target = settings.horizon_default if raw is None else raw
            step = geo_cfg["horizonEma"] * (target - horizon)
            horizon += max(-geo_cfg["horizonMaxStep"], min(geo_cfg["horizonMaxStep"], step))
        h_state = horizon

        cadence = heading = flow_heading = None
        stationary = False
        ego_sens: dict = {}
        if mser is not None:
            mt, cad, hcum, stat = mser
            j = int(np.clip(np.searchsorted(mt, t), 0, len(mt) - 1))
            if j > 0 and abs(mt[j - 1] - t) < abs(mt[j] - t):
                j -= 1
            cadence = None if np.isnan(cad[j]) else float(cad[j])
            heading = flow_heading = float(np.interp(t, mt, hcum))
            if sser is not None and flow_hcum is not None:
                flow_heading = float(np.interp(t, mt, flow_hcum))      # the image shift the track matching needs
            stationary = stat is not None and bool(stat[j])
            if sser is not None:
                pitch_now, roll_now = float(np.interp(t, mt, sser["pitch"])), float(np.interp(t, mt, sser["roll"]))
                ego_sens = {"pitchDeg": _r(pitch_now, 2), "rollDeg": _r(roll_now, 2), "gps": _gps_at(sser["s"], t, ego_cfg.get("gps") or {})}
                if ego_cfg.get("rollCorrect", False):
                    ego_sens["rollCorrectDeg"] = _r(roll_now, 2)          # the roll the ground geometry undoes (items here, the map in worldmap.Observer)
                if hz_off is not None:
                    horizon = hz_off.update(t, pitch_now, h_state, hz_source)
                    ego_sens["horizonImageY"] = round(h_state, 4)
        walk_cadence = None if stationary else cadence      # a standing user's bob is not a gait
        if sser is not None and ego_cfg.get("rollCorrect", False):
            _roll = math.radians(ego_sens.get("rollCorrectDeg") or 0.0)
            for _g in (item_lens, gd_geo if gd_on else None):
                if _g is not None:
                    _g.roll = _roll
        if gps_scale is not None and sser is not None:
            g_now = ego_sens.get("gps")
            step_len = step_len0 * gps_scale.update(t, g_now["speedMps"] if g_now and g_now["good"] else None,
                                                    walk_cadence * step_len0 if walk_cadence else None)
        # v26.1.14: stepping onto / off a crosswalk (the crosswalk share under the feet)
        cw_change = crosswalk.update(t, _seed_fraction(grid, cw_class, config["surfaces"]["seedBox"]), stationary)
        if cw_change:
            cw_marks.append((t, cw_change))

        # 3. items
        k = scale.value                            # gait scale from the frames so far: metres are real-world
        geo = _frame_geometry(gh, gw, horizon, settings.camera_height_m * k, f, settings.hfov_deg, lane_half,
                              region, roles["boundaryMarginPx"], projection, lat_off, lens_all)
        dmap = None
        if depth_maps is not None:
            j = int(np.clip(np.searchsorted(depth_t, t), 0, len(depth_t) - 1))
            if j > 0 and abs(depth_t[j - 1] - t) < abs(depth_t[j] - t):
                j -= 1
            dmap = np.asarray(depth_maps[j])
        items = detect_items(grid, ids, geo, config, None if relative else dmap)       # v26.2.10: the people split reads metric depth only
        if dmap is not None:
            if relative:
                a_hz = anchor_horizon if anchor_horizon is not None else horizon   # fixed: no horizon jitter
                if plane:
                    anchor.update(_plane_fit(region, dmap, a_hz, gh, gw, f, anchor_rows, settings.hfov_deg,
                                             depth_rays, dist_cfg))
                else:
                    a_raw, a_cells = _ground_anchor(region, dmap, a_hz, settings.camera_height_m, gh, gw, f, anchor_rows)
                    anchor.update(t, dt, a_raw, a_cells)
            for it in items:
                it.depth_on = True
                it.depth_raw = _item_depth_m(it, dmap, gh, gw, depth_rows_frac)

        # 4. tracking
        tracks = {k: v for k, v in tracks.items() if t - v.last_t <= trk["maxMissedSeconds"]}
        pan_shift = 0.0
        if flow_heading is not None and prev_heading is not None and settings.hfov_deg > 0:
            pan_shift = max(-0.25, min(0.25, -(flow_heading - prev_heading) / settings.hfov_deg))
        prev_heading = flow_heading
        if abs(pan_shift) >= trk.get("panMatchMinShift", math.inf):
            last_hard_pan_t = t
        matches = _match(tracks, items, t, trk, pan_shift, people_classes)
        for ii, it in enumerate(items):
            tid = matches.get(ii)
            if tid is None:
                if it.lane_part:
                    tid, next_lane_part_id = next_lane_part_id, next_lane_part_id + 1
                else:
                    tid, next_id = next_id, next_id + 1
                tracks[tid] = _Track(tid, it.group, it.class_name, Box(*it.bbox), t, t,
                                     it.distance_m, it.lateral_m, lane_part=it.lane_part)
            tr = tracks[tid]
            tr.box, tr.last_t, tr.last_distance, tr.last_lateral = Box(*it.bbox), t, it.distance_m, it.lateral_m
            if it.clipped:                        # distance is only a lower bound: no closing from it
                tr.history.clear()
            else:
                tr.history.append((t, it.contact_y_raw))
                tr.history = [h for h in tr.history if h[0] >= t - trk["historySeconds"] - 1e-9]
            # v26.1.12 (review 5, 90.8 s): a person's motion is available after ~0.5 s (a person who steps into view close by
            # has no 0.75 s to wait); everything else keeps motionMinSeconds
            min_span = trk.get("peopleMotionMinSeconds", trk["motionMinSeconds"]) if it.people else trk["motionMinSeconds"]
            raw_closing = _closing_mps(tr.history, horizon, settings.camera_height_m, gh, f,
                                       trk["motionMinRowsBelowHorizon"], min_span)
            tr.closing = None if raw_closing is None else raw_closing * k     # same units as the distances
            tr.present_run += 1
            # the contact row jumps by a row or two with segmentation noise (up to 20-50 percent of a near
            # item's steps): the distance, lateral and steps are read from a per-track smoothed row
            if it.clipped:
                tr.contact_s = None
            else:
                a_c = trk.get("contactEma", 0.5)
                tr.contact_s = it.contact_y if tr.contact_s is None else a_c * it.contact_y + (1 - a_c) * tr.contact_s
                d_s = _ground_dist(geo, tr.contact_s, it.base_col)
                if d_s is not None and it.distance_m > 0:
                    it.lateral_m = (it.lateral_m - lat_off) * (d_s / it.distance_m) + lat_off
                    it.distance_m = d_s
            if relative:                               # anchored ground metres (before the level c)
                a_t = anchor.value
                it.depth_raw = None if (a_t is None or it.depth_raw is None) else a_t * it.depth_raw
            if it.depth_raw is not None:
                tr.dhist.append((t, it.depth_raw))        # relative: anchored metres, the level c applies at use
                tr.dhist = [h for h in tr.dhist if h[0] >= t - trk["historySeconds"] - 1e-9]
            it.track_id, it.closing_raw, it.closing = tid, raw_closing, tr.closing
            it.present_run = tr.present_run
            # v26.1.15 (review 7): during the start warm-up the 2-frame confirmation (roles.confirmFrames) is the only gate
            it.settled = (not warm) or t - tr.first_t >= MIN_TRACK_AGE_S - 1e-9

        # 4b. depth in metres: metric maps as they are; relative maps anchored per frame, levelled by gait
        if relative:
            wit = []
            for it in items:
                if it.depth_raw is not None and _pole_like(it):
                    r = _depth_closing(tracks[it.track_id].dhist, t, trk["motionMinSeconds"])
                    if r is not None:
                        wit.append((it.bearing, r))
            prior_c = level_prior if isinstance(level_prior, (int, float)) else scale.value
            if plane:
                # the plane scale is final; the gait only checks it (~1 = camera height and walking agree)
                gait_check.update(t, gait_check.sample(walk_cadence * step_len if walk_cadence else None, wit), dt)
                level, c_source, depth_scale_source = 1.0, "plane", "plane"
            else:
                dscale.update(t, dscale.sample(walk_cadence * step_len if walk_cadence else None, wit), dt, start=prior_c)
                level = dscale.value
            if plane:
                pass
            elif level is not None:
                c_source = "frozen" if dscale.holding else "gait"
                depth_scale_source = "gait"
            else:
                level = prior_c
                c_source = "prior" if isinstance(level_prior, (int, float)) else "ground"
                depth_scale_source = "ground" if c_source == "ground" else "prior"
            a_now = anchor.value
            ds = None if a_now is None else level
        else:
            ds, a_now, c_source, depth_scale_source, level = 1.0, None, "metric", "metric", None
        dc_rep = None
        if gd_on:
            sig_rows = hsig.update(t, horizon)
            sc_total = None if (dmap is None or ds is None) else (ds * a_now if relative else ds)
            # v26.2.7: the walls' bases that stand on a surface calibrate the depth curve where the walking region does not reach
            walls = None
            if smap is not None and dmap is not None and sc_total and float(gd_cfg.get("wallSampleWeight", 0)) > 0:
                walls = worldmap.face_contact_samples(smap.ob, grid, dmap, sc_total, horizon)
            dc_rep = corrector.update(t, None if region is None else region.mask, dmap, sc_total or 0.0, horizon, sig_rows, extra=walls)
        for it in items:
            if it.depth_raw is None or ds is None:
                continue
            tr = tracks[it.track_id]
            it.depth_m = ds * it.depth_raw             # metric: ds = 1; relative: depth_raw is anchored, ds the level c
            if source == "depth":
                d_use = it.depth_m
                if dc_rep is not None:                 # v26.2.3: range-corrected depth fused with the ground ray of a base on a surface
                    d_use = _ground_depth_distance(it, tr, grid, surf_lut, horizon, gd_geo, gh, dc_rep, gd_cfg, obj_mode)
                # metric now: no ground scale. Lateral keeps its bearing at the new distance.
                if item_lens is not None and it.base_col >= 0:           # v26.2.7: the lens ray of the base pixel at the new distance
                    y_l = tr.contact_s if tr.contact_s is not None else it.contact_y
                    it.lateral_m = float(groundfuse.lateral_at(item_lens, y_l * gh, it.base_col + 0.5, d_use, horizon)) + lat_off
                elif it.distance_m > 0:
                    it.lateral_m = (it.lateral_m - lat_off) * (d_use / it.distance_m) + lat_off
                it.distance_m, it.from_depth = d_use, True
                raw_c = _depth_closing(tr.dhist, t, trk.get("peopleMotionMinSeconds", trk["motionMinSeconds"])
                                       if it.people else trk["motionMinSeconds"])
                tr.closing = None if raw_c is None else ds * raw_c
                it.closing = tr.closing

        # 4c. (v26.2.12) a distance that jumps between consecutive frames (review 9, 24.5 s: the top of a skip read 5.6 -> 2.65 -> 2.17 -> 0.96 m
        # with a frozen box) is a measurement glitch: no closing speed from the history across it, no coasting from it, and a thin item stays
        # unspoken for ``speech.thinStableS``
        if jump_cfg.get("enabled", False):
            for it in items:
                tr = tracks[it.track_id]
                d_before, d_before_t = tr.d_prev, tr.d_prev_t
                tr.d_prev, tr.d_prev_t = it.distance_m, t
                if (d_before is not None and not it.clipped and t - d_before_t <= jump_cfg.get("maxGapS", 0.4) + 1e-9
                        and min(d_before, it.distance_m) <= float(jump_cfg.get("nearM", 1e9))
                        and abs(it.distance_m - d_before) > max(float(jump_cfg.get("minM", 1.0)), float(jump_cfg.get("frac", 0.4)) * d_before)):
                    tr.jump_t = t
                    if it.class_name in reset_classes:           # a vehicle / rider: no speed from a history across the glitch
                        it.jumped = True
                        tr.history.clear(); tr.dhist.clear(); tr.lhist.clear()
                        tr.along_s, tr.mstate, tr.still_t0 = None, None, None
                        it.closing = it.closing_raw = None
                        tr.closing = None

        # 5. ego
        ego.cadence = cadence
        ego.update_speed([it.closing_raw for it in items
                          if _speed_witness(it) and 0.0 <= it.closing_raw <= ego_cfg["speedMaxMps"]], t, ego_cfg)
        scale.update(t, walk_cadence, ego.speed, dt)
        # ego speed in the units of the (calibrated) distances: walking cadence times the step length once
        # the scale is known (always, with metric depth distances). v26.1.11 (review 4): when the cadence drops out the
        # last cadence-based speed is held for ``cadenceWindowSeconds`` and then the speed is unknown; the pole-witness
        # speed is only the cold-start guess before any gait scale exists (it read 0.59 m/s while walking at 1.4, so a
        # standing person "approached"). A user measured standing still has speed 0.
        depth_distances = source == "depth" and depth_maps is not None and (not relative or a_now is not None)   # metres from depth now
        if stationary:
            ego_speed = 0.0
        elif walk_cadence and (scale.k is not None or depth_distances):
            ego_speed = held_speed = walk_cadence * step_len
            held_t = t
        elif held_speed is not None and t - held_t <= ego_cfg["cadenceWindowSeconds"] + 1e-9:
            ego_speed = held_speed
        elif held_speed is None and scale.k is None and ego.speed is not None:
            ego_speed = ego.speed * scale.value
        else:
            ego_speed = None
        # v26.1.13 (review 6, 374.0 s): motion states are judged against a robust ego speed, the median of the last
        # ``egoMedianSeconds`` of the cadence-based speed, so that a momentary spike does not turn "approaching" into "standing"
        # v26.1.15 (review 7, 2.0 / 3.2 s): while the history is shorter than the window the median is still ramping
        # (0.59 at 2.0 s, 1.28 at 3.2 s: a standing person read "approaching"), so the motion words and the people motion wait wait for
        # a full window. A user measured standing still has a known speed 0 at once.
        ego_win = roles.get("egoMedianSeconds", 0.0)
        if ego_speed is None or stationary:
            ego_hist.clear()
            ego_hist_t0 = None
            ego_motion = ego_speed
            ego_settled = ego_speed is not None
        else:
            if not ego_hist:
                ego_hist_t0 = t
            ego_motion = _robust_speed(ego_hist, t, ego_speed, ego_win)
            ego_settled = ego_win <= 0 or t - ego_hist_t0 >= ego_win - 1e-9
        # v26.1.16 (review 8, 27.3 s): a hard head turn throws the cadence / ego speed off (2.09 against 1.2 m/s in the two seconds around
        # it), so a person's motion state read "standing" while they crossed: no motion words for ``panSettleSeconds`` after a hard pan
        if t - last_hard_pan_t < roles.get("panSettleSeconds", 0.0) - 1e-9:
            ego_settled = False
        turned = ego.update_heading(heading, t, config["pathChange"], dt)
        if mover.on:
            mover.advance(t, dt, 0.0 if stationary else ego_speed, heading)

        depth_scale_out = None if depth_maps is None or ds is None else _r(ds * a_now, 4) if relative else ds
        if depth_scale_out is None and depth_maps is not None and plane and anchor.fit is not None and anchor.fit.height_units > 0:
            # v26.2.5: the plane anchor is usable from ``initialAnchorMinFrames`` valid fits; until then the frame's own fit seeds the scale
            # the world map reads (frames 0-1 had none, so the map placed the first facade by the horizon alone). Nothing else reads it.
            depth_scale_out = _r(settings.camera_height_m / anchor.fit.height_units * level, 4) if level else None
        corridor_out = None
        if smap is not None:
            # v26.2.1: the map of this frame (causal), fed with the same ego values the hazards.json stores, so that the offline
            # ``worldmap.build`` reproduces it; static items are then judged on it; a static danger that left the image is a ghost
            frame_in = {"horizon": round(horizon, 4), "scale": round(scale.value, 3), "depthScale": depth_scale_out, "dcorr": dc_rep,
                        "ego": {"speedMps": _r(ego_speed, 2), "headingDeg": _r(heading, 1), "stationary": stationary,
                                "depthPitchDeg": _r(anchor.pitch_deg, 1) if plane else None, **ego_sens}}
            smap.update(i, frame_in, dmap, grid)
            map_ms.append(smap.ms)
            for it in items:
                smap.measure(it)
            if map_mode:
                _map_source(items, tracks, smap, wtracks, src_cfg, t, step_len, ego_motion if ego_motion is not None else ego_speed, src_counts)
            seen_now = {it.track_id for it in items}
            for tid, tr in tracks.items():
                if tid in seen_now or tr.ghost_src is None:
                    continue
                g = smap.ghost(tr, t)
                if g is None:
                    tr.ghost_src = tr.ghost_t0 = None
                    continue
                tr.ghost_t0 = t if tr.ghost_t0 is None else tr.ghost_t0
                tr.last_t = t
                tr.present_run += 1
                g.present_run = tr.present_run
                items.append(g)
            corridor_out = smap.corridor()

        if coast.on:
            real = {it.track_id: it for it in items}
            items.extend(coast.items(t, real, world, tracks, step_len, smap.point_in_solid if smap is not None and smap.solid_on else None,
                                     (lambda tid: _trusted_track(wtracks, tid, t)) if (map_mode and src_cfg.get("coastFromTracks", True) and wtracks.on) else None))

        # 6-8. steps, parked vs moving, roles
        span = None
        if region is not None:
            valid = np.flatnonzero(~np.isnan(region.left))
            if valid.size:
                span = (valid.min() / gh, (valid.max() + 1) / gh)
        for it in items:
            tr = tracks[it.track_id]
            if it.coasting:
                # v26.2.2: a predicted mover keeps the motion state of its last measurement; only the geometry is new
                it.ego_known, it.ego_settled = ego_speed is not None, ego_settled
                it.steps = steps_to(it.distance_m, step_len)
                _assign_role(it, span, roles, lane_half, step_len, stationary)
                if stationary and not (it.moving is True and it.collision):
                    it.role, it.urgency, it.collision, it.summary_ok, it.proximity = "none", "none", False, False, False
                _mute_solid(it, smap)
                continue
            it.moving, it.approaching = (None, False)
            it.ego_known = ego_speed is not None
            it.ego_settled = ego_settled
            # v26.1.16 (review 8): a rider / vehicle may be called "approaching" on an unsettled ego speed only when it closes faster
            # than we could walk (closing - maxWalkingMps >= approachingMps); else the plain phrase
            it.own_fast = (it.fast and it.closing is not None
                           and it.closing - roles.get("maxWalkingMps", 2.0) >= roles.get("approachingMps", 0.4))
            if it.clipped:
                tr.lhist.clear()
            else:
                tr.lhist.append((t, it.lateral_m, it.distance_m, heading,
                                 bearing_deg((it.bbox[0] + it.bbox[2]) / 2.0, settings.hfov_deg, projection)))
                tr.lhist = [h for h in tr.lhist if h[0] >= t - trk["historySeconds"] - 1e-9]
            it.lat_vel = _lateral_velocity(tr.lhist, trk["motionMinSeconds"])
            it.cross_mps = _cross_velocity(tr.lhist, ego_motion, roles.get("crossWindowSeconds", 1.0))
            if it.track_motion is not None:                  # (source "track") the world track's velocity instead of the image's
                it.lat_vel, it.cross_mps = it.track_motion[1], it.track_motion[2]
            if mover.on and it.group == "moving":
                mover.observe(it, t)
            if it.group == "static" or it.group == "feature":
                it.moving = False
            elif it.closing is not None and ego_motion is not None:
                # ground velocity: along the line of sight (closing minus our own speed) and, when clearly there, sideways (v26.1.11)
                # v26.1.11: depth closing rates read LOW against the gait (review 4: depthGaitCheck 1.2-1.6, a standing
                # person's closing 0.85 m/s against our 1.4), so a static person looked like one walking away. The
                # witnesses' own level (``gait_check``, the median of walking speed / witness closing rate) puts
                # both on the gait's scale: ``(closing - v / c) * c``; c = 1 without an estimate (cold start, ground source).
                c_rate = gait_check.value if (plane and source == "depth" and gait_check.value) else 1.0
                c_rate = max(0.8, min(2.5, c_rate))
                along = (it.closing - ego_motion / c_rate) * c_rate
                # v26.1.11: a far person's depth closing swings 1.0 <-> 4.0 m/s from frame to frame (review 4, 87 s: a
                # person walking towards us read "standing"); judged on a smoothed speed (motionSmoothSeconds)
                tau = roles.get("motionSmoothSeconds", 0.0)
                if it.track_motion is not None:              # (source "track") the world track is a filtered velocity already
                    along = tr.along_s = it.track_motion[0]
                elif tr.along_s is None or tau <= 0 or t - tr.along_t > trk["maxMissedSeconds"]:
                    tr.along_s = along
                else:
                    tr.along_s += (1.0 - math.exp(-(t - tr.along_t) / tau)) * (along - tr.along_s)
                tr.along_t = t
                along = tr.along_s
                # v26.1.12 (review 5): three-way with hysteresis, see ``_motion_state``. Standing needs |along| < 0.3 m/s held for 1 s
                # and no sideways motion; approaching / moving away need 0.4 m/s; in between the motion is unknown (None) and the
                # plain phrase is said.
                tr.mstate = _motion_state(tr, t, along, _sideways_mps(it, roles), it.cross_mps, roles, it.class_name == "vehicle")
                it.moving = None if tr.mstate is None else tr.mstate != "still"
                it.approaching = tr.mstate == "approach"
                it.receding = tr.mstate == "recede"
            if mover.on and it.group == "moving" and it.ego_known:      # v26.2.14: the motion words from the mover's own positions (once our speed has settled)
                mover.classify(it, t, ego_motion if ego_motion is not None else ego_speed, it.ego_settled)
            tr.moving = it.moving
            if smap is not None:
                smap.snap_solid(it)
            it.steps = steps_to(it.distance_m, step_len)
            base = labels.get(it.class_name, it.class_name.replace("-", " "))
            it.family = base
            if it.tree:                                  # v26.2.12: a trunk in a tree pit: spoken "tree", the family of the vegetation
                base = str(tree_cfg_run.get("label", "tree"))
                it.family = labels.get(tree_cfg_run.get("canopyClass", "nature vegetation"), "vegetation")
            it.label = parked_labels.get(it.class_name, base) if (it.group == "moving" and it.moving is False) else base
            if _not_approaching(it, ego.speed) and it.group != "moving":
                it.along_path = True
            if it.lane_part and not it.lane_part_weak:
                tr.lp_strong_t = t
            weak_lost = (it.lane_part and it.lane_part_weak
                         and (tr.lp_strong_t is None or t - tr.lp_strong_t > roles.get("laneBaseHoldSeconds", 0.0) + 1e-9))
            if it.lane_part and (weak_lost or it.closing_raw is None or ego.speed is None or it.closing_raw < roles.get("laneBaseMinClosingMps", 0.0)
                                 or t - tr.first_t < roles.get("laneBaseMinAgeSeconds", 0.0) - 1e-9):
                # v26.1.16 follow-up: a lane part is only believed once it is measured to close on us as we walk (a wall that bends
                # across the camera axis keeps or gains distance: chest0002 51-52 s) and has been tracked for ``laneBaseMinAgeSeconds`` (a
                # burst of a few frames beside a path is segmentation noise: 4929 review 5, 51.0-51.3 s); until then it is no danger
                it.along_path = True
            _assign_role(it, span, roles, lane_half, step_len, stationary)
            _mute_solid(it, smap)
            if it.lane_part and it.role != "danger":
                it.role, it.urgency, it.collision, it.summary_ok = "none", "none", False, False   # context is the side wall's job
            if stationary and not (it.group == "moving" and it.moving is True and it.collision):
                # v26.1.11: standing still, nothing static is announced and only a mover on a collision course
                # (its own velocity: ours is 0) is a danger
                it.role, it.urgency, it.collision, it.summary_ok, it.proximity = "none", "none", False, False, False
            # v26.1.15 (review 7): no start silence on a prior horizon. Until the horizon has settled (WARMUP_S) it is the
            # mean of the raw estimates, else the mount / body preset; the plain ground-geometry distance serves until the depth
            # anchor has its first plane fit. The 2-frame confirmation stays the minimum.
            if it.role == "feature" and it.lane_hit and not it.along_path:
                tr.feature_frames += 1                 # it crosses the lane: what a surface change may be backed by
            if (it.group == "feature" and it.class_name in ("curb", "crosswalk") and it.lane_hit
                    and it.contact_y * gh > gh - under_rows and it.bbox[2] - it.bbox[0] >= under_min_w
                    and tr.feature_frames >= policy.confirm):
                # v26.1.11 (review 4, 159.8 s: the wrong "road"): only a curb / crosswalk that crossed the lane for
                # >= confirmFrames frames can go *under* us (a fragment along the path or a flicker cannot); the timing rule
                # of ``_SurfaceTracker`` does the rest
                tr.under_last = t                      # contact in the bottom rows inside the lane: under our feet

        # (v26.2.12) the FINAL distance (after the map / solid snap) jumping is a glitch too: a thin item stays unspoken for ``thinStableS``
        if jump_cfg.get("enabled", False):
            for it in items:
                if it.coasting or it.ghost:
                    continue
                tr = tracks[it.track_id]
                df, df_t = tr.df_prev, tr.df_prev_t
                tr.df_prev, tr.df_prev_t = it.distance_m, t
                if (df is not None and not it.clipped and t - df_t <= jump_cfg.get("maxGapS", 0.4) + 1e-9
                        and min(df, it.distance_m) <= float(jump_cfg.get("nearM", 1e9))
                        and abs(it.distance_m - df) > max(float(jump_cfg.get("minM", 1.0)), float(jump_cfg.get("frac", 0.4)) * df)):
                    tr.jump_t = t
                it.unstable = (it.thin or it.tree) and t - tr.jump_t < stable_s - 1e-9

        if pass_cfg.get("enabled", False) and not stationary:
            for it in items:
                if _passing_close(it, pass_cfg):
                    it.proximity = True

        # confirmation: how many consecutive analysed frames each track has held its role
        seen_tracks = set()
        for it in items:
            tr = tracks[it.track_id]
            tr.role_run = tr.role_run + 1 if tr.role == it.role else 1
            tr.role = it.role
            tr.context_seen = tr.context_seen or it.role == "context"
            it.role_run = tr.role_run
            tr.prox_run = tr.prox_run + 1 if it.proximity else 0
            it.prox_run = tr.prox_run
            seen_tracks.add(it.track_id)
            if it.jumped:
                coast.hist.pop(it.track_id, None)            # the glitch is not a position to extrapolate from
            else:
                coast.observe(it, t, world)
        if smap is not None:
            for it in items:
                if it.group != "static":
                    continue
                tr = tracks[it.track_id]
                if smap.keeps(it) and it.settled and it.role_run >= policy.confirm and not stationary:      # a confirmed danger only
                    if it.map_world is None:
                        smap.locate(it)
                    tr.ghost_src = it
                    tr.ghost_t0 = t if it.ghost and tr.ghost_t0 is None else (tr.ghost_t0 if it.ghost else None)
                else:
                    tr.ghost_src = tr.ghost_t0 = None

        for tid, tr in tracks.items():
            if tid not in seen_tracks:
                tr.role, tr.role_run, tr.present_run, tr.prox_run = "none", 0, 0, 0
                if tr.under_last is not None and not tr.under_fired and t - tr.under_last <= under_gone_s + 1e-9:
                    tr.under_fired = True              # a curb / crosswalk edge went under the user and out of view
                    surface.note_evidence(t)

        # world memory: where are we, and which remembered (announced) object is each item?
        world.advance(t, dt, 0.0 if stationary else (walk_cadence * step_len if walk_cadence else ego_speed), heading,
                      smap.pose if (one_pose and smap is not None) else None)
        world.link(items, tracks, t)
        wt_out = None
        if wtracks.on:
            _t_wt = time.perf_counter()
            wt_out = wtracks.step(t, (world.x, world.y, world.theta) if world.theta is not None else None,
                                  [{"tid": it.track_id, "cls": it.class_name, "family": it.family or it.label, "group": it.group,
                                    "static": _is_static_like(it),
                                    "fwd": it.image_dl[0] if (map_mode and it.image_dl) else it.distance_m,       # map mode: the image measurement, not what the track itself placed
                                    "right": it.image_dl[1] if (map_mode and it.image_dl) else it.lateral_m, "depth": bool(it.from_depth)}
                                   for it in items if not (it.lane_part or it.ghost or it.coasting)],
                                  _bottom_distance(smap.ob if smap is not None else None, horizon, settings.camera_height_m * k, gh, f),
                                  _hidden_fn(smap.ob if smap is not None else None))
            wtracks.ms.append((time.perf_counter() - _t_wt) * 1000.0)
            if policy.pred_on and world.theta is not None:
                _predict_velocities(items, wtracks, t, math.radians(world.theta), policy.cfg["predictive"])

        # 9. path change
        path_change = turned or (config["pathChange"]["onSurfaceChange"] and adopted is not None
                                 and adopted[0] is not None)
        if path_change:
            policy.clear_context(t)
            if recalibrate:
                anchor.reset()
                if plane:
                    gait_check = _DepthScale(ego_cfg, dist_cfg)
                elif dscale.freeze:
                    dscale = _DepthScale(ego_cfg, dist_cfg)
                    dscale.freeze = True
            _log(f"t={t:.1f}s path change ({'turn' if turned else 'surface'}); context memory cleared")
        policy.observe_context(t, {it.family or it.label for it in items
                                   if it.role in ("context", "danger") and _is_static_like(it)})

        # speech
        # context waits for the first surface (up to the old debounce, no longer: the persistence needed
        # to *announce* a surface is longer now, but the scene summary must not wait for it)
        surface_known = surface.stable is not None or t - first_t >= config["surfaces"]["debounceSeconds"] - 1e-9
        if ego_speed is not None:
            policy.travel_steps += ego_speed * dt / step_len
        policy.stationary = stationary
        policy.ego_u = ego_speed
        if wfollow.on:                           # v26.2.13: walls the user walks along (no phrase, no new beep episode)
            wfollow.advance(dt, 0.0 if stationary else ego_speed)
            wfollow.observe(t, items)
        if policy.pred_meas_floor > 0:           # v26.2.12: the speed the static witnesses really close at (over the last measuredWindowS)
            w_now = [it.closing for it in items if _speed_witness(it) and it.closing is not None and 0.0 <= it.closing <= ego_cfg["speedMaxMps"]]
            if w_now:
                meas_hist.append((t, float(np.median(w_now))))
            meas_hist[:] = [h for h in meas_hist if h[0] >= t - meas_win - 1e-9]
            policy.ego_meas = float(np.median([h[1] for h in meas_hist])) if len(meas_hist) >= 3 else None
        policy.observe_movers(t, items, tracks)
        speech = policy.step(t, items, tracks, surface_known)
        if speech is None:
            speech = policy.away_speech(t, items)       # v26.2.13: a danger that left the lane by its own motion
        if speech is None:
            speech = policy.motion_speech(t, items)     # v26.2.14: "cutting in front" / "moving away" ahead, from the person's own velocity
        if speech is None and policy.quiet_t == t:
            blk_run = 0
        elif speech is None and blk_cfg.get("enabled", False) and smap is not None and not stationary and ego_speed and world.theta is not None:
            blk = smap.blocked_ahead(blk_cfg)
            blk_run = blk_run + 1 if blk is not None and blk["kind"] == blk_kind else (1 if blk is not None else 0)      # confirmed as one kind
            blk_kind = blk["kind"] if blk is not None else None
            if t - blk_seen_t > float(blk_cfg.get("clearS", 2.0)):
                blk_open = False
            if blk is not None:
                blk_seen_t = t
            if blk is not None and not blk_open and blk.get("wideOk", True) and blk_run >= int(blk_cfg.get("confirmFrames", 2)) and t - blk_last_t >= float(blk_cfg.get("cooldownS", 5.0)) \
                    and policy._gap_ok(t, priority=True):
                th_ = math.radians(world.theta)
                bx = world.x + math.sin(th_) * blk["cfwd"] + math.cos(th_) * blk["cright"]
                by = world.y + math.cos(th_) * blk["cfwd"] - math.sin(th_) * blk["cright"]
                if blk_pos is None or math.hypot(bx - blk_pos[0], by - blk_pos[1]) > float(blk_cfg.get("sameSpotM", 3.0)):
                    txt = (blk_cfg["templates"]["free"].format(label=blk["label"], clock=blk["blockClock"], free=blk["clock"]) if blk.get("free")
                           else blk_cfg["templates"]["none"].format(label=blk["label"], clock=blk["blockClock"]))
                    speech = policy._event(t, "feature", txt, None)
                    speech["blocked"] = {k: blk[k] for k in ("kind", "share", "clearM", "bearingDeg", "clock", "blockClock", "endClass", "cfwd", "cright") if k in blk}
                    blk_last_t, blk_pos, blk_open = t, (bx, by), True
        elif speech is not None:
            blk_run = 0
        elif blk_cfg.get("enabled", False):
            blk_run = 0
        if speech:
            events.append(speech)

        beeping = [it for it in items if it.role == "danger" and it.collision and it.settled
                   and it.role_run >= policy.confirm and it.steps <= config["tones"].get("maxSteps", roles["dangerSteps"])]
        if wfollow.on:
            for it in beeping:                           # a wall due a beep, real or quiet, is a wall event (the memory of the quiet rules)
                if it.class_name in wfollow.classes and wfollow.candidate(t, it):
                    policy.note_wall(t, it)
        if follow_cfg.get("enabled", False) and beeping:
            beeping = [it for it in beeping if not _followed_wall(it, t, follow, follow_cfg)]
        if wfollow.on and beeping:
            beeping = [it for it in beeping if not wfollow.quiet(t, it, float(follow_cfg.get("gapS", 1.5)))]
        if wfollow.on:
            for it in beeping:
                if it.class_name in wfollow.classes:
                    wfollow.beeped(t, it)
        # a stream of beeps (>= 2 frames in a row) is danger activity; a single pass-by beep is not (review 8, 6.2 s: the building at 2
        # steps right after the first beep of a passing person was a wanted context phrase)
        beep_run = beep_run + 1 if beeping else 0
        if beep_run >= 2:
            policy.last_beep_t = t
        frame_collision.append((min(beeping, key=lambda it: it.steps) if beeping else None,
                                {it.track_id for it in items}))
        near_soft = [it for it in items if it.proximity and it.settled and it.prox_run >= policy.confirm]
        frame_proximity.append((min(near_soft, key=lambda it: it.steps) if near_soft else None,
                                {it.track_id for it in items}))

        speed_known = ego_speed is not None
        frames_out.append({
            "index": i, "t": round(t, 4),
            "horizonY": round(horizon, 4), "horizonEstimated": raw is not None,
            "region": None if region is None else {"surface": region.group, "label": region.label,
                                                   "rows": _region_rows(region)},
            "lane": _lane_polygon(geo, lane_half, roles["dangerSteps"] * step_len),
            "ego": {"speedMps": _r(ego_speed, 2), "cadenceHz": _r(cadence, 2), "stepLengthM": round(step_len, 2),
                    "headingDeg": _r(heading, 1), "stationary": stationary,
                    **ego_sens,
                    "depthAnchor": _r(a_now, 4),
                    "depthAnchorMode": anchor_mode,
                    "depthPitchDeg": _r(anchor.pitch_deg, 1) if plane else None,
                    "depthCameraHeightUnits": _r(anchor.height_units, 4) if plane else None,
                    "depthGaitCheck": _r(gait_check.value, 3) if plane else None,
                    "depthScale": depth_scale_out,
                    "depthScaleSource": "none" if depth_maps is None or ds is None else depth_scale_source,
                    "depthLevel": None if not relative or ds is None else _r(ds, 4),
                    "depthLevelSource": None if not relative or ds is None else c_source,
                    "scale": round(scale.value, 3), "scaleSource": "gait" if scale.from_gait else "prior" if scale.k is not None else "none",
                    "estimated": {"speed": speed_known, "cadence": cadence is not None,
                                  "stepLength": False}},
            "pathChange": bool(path_change),
            **({"depthCorrection": dc_rep} if dc_rep is not None else {}),
            **({"corridor": corridor_out} if smap is not None else {}),
            **({"faceEdgeLines": smap.fe_lines} if smap is not None and smap.fe_lines else {}),
            **({"worldTracks": wt_out} if wt_out is not None else {}),
            "hazards": [_hazard_json(it, gh, gw, full_all) for it in sorted(items, key=lambda it: it.steps)],
        })

    tone_events, episodes = _tone_events(frame_collision, times, config["tones"], frame_proximity, cw_marks,
                                         resolve_sounds(config["tones"], sounds))
    events.extend(tone_events)
    events.extend(episodes)
    events.sort(key=lambda e: (e["t"], e["type"] != "speech", e["type"] != "beeps"))
    version = config["version"]
    hazards_doc = {
        "version": version,
        "projection": projection, "distanceSource": source,
        "settings": {"mount": settings.mount, "hfovDeg": settings.hfov_deg,
                     "cameraHeightM": settings.camera_height_m,
                     "laneHalfWidthM": lane_half, "priorStepLengthM": step_len0,
                     "stepLengthM": step_len0 if step_source == "gps" else settings.step_length_m, "stepLengthSource": step_source, "gpsStepWindowsS": step_windows_s,
                     **({"gpsStep": step_info} if step_info else {}),
                     "userHeightM": settings.user_height_m, "cameraLocation": settings.camera_location,
                     "cameraSide": settings.camera_side, "lateralOffsetM": lat_off,
                     "objectDistance": getattr(settings, "object_distance", "depth"), "useHorizon": bool(getattr(settings, "use_horizon", True))},
        "gridW": gw, "gridH": gh, "egoAvailable": mser is not None, "frames": frames_out,
    }
    if one_pose and smap is not None:
        hazards_doc["settings"]["onePose"] = True
    if map_mode:
        hazards_doc["settings"]["sourceMode"] = "map"
        hazards_doc["settings"]["sourceCounts"] = dict(src_counts)
    if policy.pred_on:
        hazards_doc["settings"]["predictive"] = dict(policy.pred_stats)
    if sser is not None:
        hazards_doc["settings"].update({"headingSource": heading_source, "cadenceSource": cadence_source,
                                        "stationarySource": stationary_source, "horizonSource": hz_source,
                                        "gyroBiasDegPerS": sser["info"].get("biasDegPerS"), "gyroBiasSource": sser["info"].get("biasSource"),
                                        "gpsUpdates": sser["info"].get("gpsUpdates", 0) if heading_source == "imu+gps" else 0})
    if coast.on:
        for tid in list(coast.active):
            coast._end(tid, float(times[-1]) if n else 0.0, "end")
        hazards_doc["coast"] = {"episodes": coast.episodes}
    if wtracks.on:
        hazards_doc["worldTracksSettings"] = dict(wtracks.cfg)
        LAST_WORLD_TRACKS_MS[:] = wtracks.ms
    if window is not None:                    # absent for full-frame runs (their output is unchanged)
        hazards_doc["window"] = dict(window)
    return hazards_doc, {"version": version, "events": events}
