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

import math  # noqa: F401
import time  # noqa: F401

import numpy as np  # noqa: F401

from common_paths import find_common_dir  # noqa: F401  (worldmap calls collision.find_common_dir)
import faceedge  # noqa: F401  (kept: the legacy facade stays imported here)
import groundfuse  # noqa: F401
import sensors as sensor_lib  # noqa: F401
import worldtracks  # noqa: F401
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


from engine.pipeline.glue import (  # noqa: F401
    LAST_WORLD_TRACKS_MS,
    bottom_distance as _bottom_distance,
    hidden_fn as _hidden_fn,
    predict_velocities as _predict_velocities,
)


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

from engine.pipeline.run import run_collision  # noqa: E402, F401
