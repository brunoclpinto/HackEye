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

import json
import math
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from scipy import ndimage

from common_paths import find_common_dir
from geometry import Box, iou
import faceedge

_4_CONNECTIVITY = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
ITEM_GROUPS = ("static", "moving", "feature")
HORIZON_HOLD_S = 3.0      # keep the last good horizon this long when the estimate fails (not in the contract)
NO_DATA = 255            # grid cell outside the analysed window (a portrait run): no class, never a surface or an item
WARMUP_S = 1.5            # the horizon is the mean of the raw estimates until it has had time to settle (no silence: v26.1.15)
MIN_TRACK_AGE_S = 0.5     # a track must have lived this long before it may speak or beep (not in the first WARMUP_S of a run)
_WARNED: set[str] = set()


def _log(msg: str) -> None:
    print(f"[collision] {msg}", file=sys.stderr)


def _warn_once(msg: str) -> None:
    if msg not in _WARNED:
        _WARNED.add(msg)
        _log(msg)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

@dataclass
class CollisionSettings:
    mount: str
    hfov_deg: float
    camera_height_m: float
    step_length_m: float | None        # None = estimate, fall back to the default
    horizon_default: float
    projection: str = "rectilinear"    # resolved lens model: "rectilinear" (pinhole) or "fisheye" (equidistant)
    distance_source: str = "ground"    # "ground" | "depth" (v26.1.10 depth experiment)
    depth_level_prior: float | str | None = None   # mount override of distance.depthLevelPrior (number | "ground")
    user_height_m: float | None = None             # body mode (None = legacy mount mode)
    camera_location: str | None = None             # "waist" | "chest" | "eye" | "head"
    camera_side: str | None = None                 # "left" | "center" | "right"
    lateral_offset_m: float = 0.0                  # camera centre relative to the body centre (+ = camera right of body)


def load_config(path: Path | None = None) -> dict:
    path = path or (find_common_dir() / "config" / "collision.json")
    with open(path) as f:
        return json.load(f)


AUTO_FISHEYE_HFOV_DEG = 100.0
DISTANCE_SOURCES = ("ground", "depth")


def resolve_projection(projection: str | None, hfov_deg: float) -> str:
    """"rectilinear" / "fisheye" pass through; None or "auto": fisheye from HFOV 100 deg up (wide action cams)."""
    if projection in ("rectilinear", "fisheye"):
        return projection
    return "fisheye" if hfov_deg >= AUTO_FISHEYE_HFOV_DEG else "rectilinear"


SIDE_SIGN = {"left": -1.0, "center": 0.0, "right": 1.0}


def resolve_settings(config: dict, mount: str | None = None, hfov_deg: float | None = None,
                     camera_height_m: float | None = None,
                     step_length_m: float | None = None, projection: str | None = None,
                     distance_source: str = "ground", user_height_m: float | None = None,
                     camera_location: str | None = None, camera_side: str | None = None) -> CollisionSettings:
    """Explicit values win over the mount preset / body geometry; None falls back to defaults.

    Body mode (``camera_location`` or ``user_height_m`` given, ``config["body"]``): camera height =
    heightRatio x height + heightOffsetM, step length = stepLengthRatio x height, horizon from the location,
    lateral offset = side sign x sideOffsetM. Otherwise the legacy mount preset (lateral offset 0)."""
    mount = mount or config["defaultMount"]
    if mount not in config["mountPresets"]:
        _warn_once(f"unknown mount '{mount}', using '{config['defaultMount']}'")
        mount = config["defaultMount"]
    preset = config["mountPresets"][mount]
    hfov = float(config["defaultHfovDeg"] if hfov_deg is None else hfov_deg)
    if distance_source not in DISTANCE_SOURCES:
        _warn_once(f"unknown distance source '{distance_source}', using 'ground'")
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
            _warn_once(f"unknown camera location '{loc}', using '{body.get('defaultCameraLocation', 'chest')}'")
            loc = body.get("defaultCameraLocation", "chest")
        spec = locs[loc]
        body_h = float(user_height_m if user_height_m is not None else body["defaultUserHeightM"])
        side = camera_side or "center"
        if side not in SIDE_SIGN:
            _warn_once(f"unknown camera side '{side}', using 'center'")
            side = "center"
        cam_h = float(spec["heightRatio"]) * body_h + float(spec.get("heightOffsetM", 0.0))
        step = float(body["stepLengthRatio"]) * body_h
        horizon = float(spec["horizon"])
        lat_off = SIDE_SIGN[side] * float(spec.get("sideOffsetM", 0.0))
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
        projection=resolve_projection(projection, hfov), distance_source=distance_source,
        depth_level_prior=preset.get("depthLevelPrior"),
        user_height_m=body_h, camera_location=loc, camera_side=side, lateral_offset_m=lat_off)


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def bearing_deg(x_norm: float, hfov_deg: float, projection: str = "rectilinear") -> float:
    """Bearing, positive = right. Rectilinear (pinhole): atan((x - 0.5) * 2 * tan(hfov / 2));
    fisheye (equidistant): (x - 0.5) * hfov."""
    if projection == "fisheye":
        return (x_norm - 0.5) * hfov_deg
    t = math.tan(math.radians(hfov_deg) / 2.0)
    return math.degrees(math.atan((x_norm - 0.5) * 2.0 * t))


def clock_from_bearing(bearing: float) -> int:
    """12 + round(bearing / 30), clamped to +-90 deg, as 9..12 and 1..3."""
    b = max(-90.0, min(90.0, bearing))
    k = int(math.floor(b / 30.0 + 0.5))
    if k == 0:
        return 12
    return 12 + k if k < 0 else k


def clock_quarter(bearing: float) -> int:
    """Quarter-hour clock index: round(bearing / 7.5), half away from zero, clamped to +-12 (+-90 deg)."""
    v = bearing / 7.5
    q = int(math.floor(abs(v) + 0.5))
    q = -q if v < 0 else q
    return max(-12, min(12, q))


def clock_text(q: int) -> str:
    """Spoken clock position of quarter index ``q`` (0 = "12", 1 = "12:15", -1 = "11:45", 4 = "1", -12 = "9")."""
    m = (720 + 15 * int(q)) % 720
    hour = m // 60 or 12
    minutes = m % 60
    return f"{hour}" if minutes == 0 else f"{hour}:{minutes:02d}"


def _quarter_of_hour(clock: int) -> int:
    """Quarter index of a whole clock hour (12 -> 0, 1 -> 4, 11 -> -4)."""
    return 0 if clock == 12 else 4 * clock if clock <= 3 else 4 * (clock - 12)


def _pan_from_bearing(bearing: float) -> float:
    return max(-1.0, min(1.0, math.sin(math.radians(bearing))))


def focal_px(grid_w: float, hfov_deg: float) -> float:
    """Focal length in grid pixels: (W / 2) / tan(hfov / 2)."""
    return (grid_w / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)


def ground_distance_m(y_norm: float, horizon_y: float, camera_height_m: float,
                      grid_h: float, f_px: float) -> float | None:
    """Distance to a ground point seen at ``y_norm``: H * f / ((y - horizon) * grid_h)."""
    if y_norm <= horizon_y:
        return None
    return camera_height_m * f_px / ((y_norm - horizon_y) * grid_h)


def lateral_m(x_norm: float, distance_m: float, grid_w: float, f_px: float) -> float:
    """Sideways offset in metres (+ = right): (x - 0.5) * W * d / f."""
    return (x_norm - 0.5) * grid_w * distance_m / f_px


def _side_of_clock(clock: int) -> str:
    if clock in (9, 10):
        return "left"
    if clock in (11, 12, 1):
        return "ahead"
    return "right"


# --------------------------------------------------------------------------
# Ego motion: cadence
# --------------------------------------------------------------------------

def _spectrum(seg: np.ndarray, dt: float, pad: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """Power spectrum of a detrended, Hann-windowed window, zero-padded ``pad`` times."""
    n = len(seg)
    x = seg - np.polyval(np.polyfit(np.arange(n), seg, 1), np.arange(n))
    x = x * np.hanning(n)
    nfft = pad * n
    return np.fft.rfftfreq(nfft, dt), np.abs(np.fft.rfft(x, nfft)) ** 2


def _refine(freqs: np.ndarray, power: np.ndarray, k: int, lo: float | None = None, hi: float | None = None) -> float:
    """Parabolic interpolation around bin k.

    v26.1.11 (review 4: one -16.3 Hz cadence at 336 s): the peak search is limited to a band, so bin k can sit on the band
    edge with a larger neighbour outside it, and the parabola then extrapolates far away. A refine that moves by more than
    one bin, or leaves the search band ``[lo, hi]`` (bin-width tolerance), is rejected and the bin centre is kept."""
    f = float(freqs[k])
    if 0 < k < len(power) - 1:
        a, b, c = power[k - 1], power[k], power[k + 1]
        denom = a - 2 * b + c
        if denom < 0:
            df = freqs[1] - freqs[0]
            shift = 0.5 * (a - c) / denom * df
            cand = f + shift
            inside = (lo is None or cand >= lo - df) and (hi is None or cand <= hi + df)
            if abs(shift) <= df and inside:
                f = cand
    return f


def _peak(freqs: np.ndarray, power: np.ndarray, lo: float, hi: float, lobe: int) -> tuple[int, float] | None:
    """(bin, ratio) of the strongest peak in [lo, hi].

    The ratio is peak amplitude over the RMS amplitude of the rest of the
    spectrum (the peak's main lobe and slow drift excluded), so pure noise
    gives a small ratio while a steady bob stands out whatever its amplitude.
    """
    band = (freqs >= lo) & (freqs <= hi)
    if not band.any():
        return None
    k = int(np.flatnonzero(band)[np.argmax(power[band])])
    rest_mask = freqs >= 0.25
    rest_mask[max(0, k - lobe):k + lobe + 1] = False
    if rest_mask.sum() < 4:
        return None
    rest = float(power[rest_mask].mean())
    if rest <= 0:
        return None
    return k, math.sqrt(power[k] / rest)


# A weaker dy peak is accepted when the horizontal sway peaks at the same rhythm:
# noise rarely produces matching peaks in two independent signals.
CORROBORATED_RATIO_FRAC = 0.7


def _window_cadence(seg: np.ndarray, dt: float, band_hz: tuple[float, float], min_peak_ratio: float,
                    seg_dx: np.ndarray | None = None, min_step_hz: float = 1.4,
                    harmonic_ratio: float = 0.25) -> float:
    """Step cadence of one uniformly sampled window, or nan when there is no clear peak.

    Stride awareness: a chest camera sways and bobs asymmetrically, so the
    dominant vertical peak ``f0`` is often the *stride* (left+right cycle,
    ~1.0-1.1 Hz) and the true step rate is its second harmonic. The step rate is
    taken as the peak near ``2*f0`` when
      * ``f0 < min_step_hz`` (too slow to be walking or running steps), or
      * the spectrum really has a peak there with power >= ``harmonic_ratio``
        times the ``f0`` peak, or
      * the horizontal motion ``dx`` (which sways once per stride) peaks within
        0.15 Hz of ``f0``, i.e. ``f0`` is the stride too.
    Otherwise ``f0`` itself is the step rate (a steady 1.8 Hz walk or a 2.8 Hz run,
    whose double falls outside the band).
    """
    pad = 4
    lobe = 2 * pad + 2                        # Hann main lobe half-width in padded bins
    lo, hi = band_hz
    freqs, power = _spectrum(seg, dt, pad)
    found = _peak(freqs, power, lo, hi, lobe)
    if found is None:
        return math.nan
    k0, ratio0 = found
    f0 = _refine(freqs, power, k0, lo, hi)
    fx = None                                  # stride rhythm seen in dx, if any
    if seg_dx is not None and len(seg_dx) == len(seg):
        xf, xp = _spectrum(seg_dx, dt, pad)
        px = _peak(xf, xp, 0.7, 1.7, lobe)
        if px is not None and px[1] >= CORROBORATED_RATIO_FRAC * min_peak_ratio:
            fx = _refine(xf, xp, px[0], 0.7, 1.7)
    if ratio0 < min_peak_ratio:
        weak_ok = (fx is not None and ratio0 >= CORROBORATED_RATIO_FRAC * min_peak_ratio
                   and (abs(fx - f0) <= 0.15 or abs(2 * fx - f0) <= 0.2))
        if not weak_ok:
            return math.nan
    if 2 * f0 > hi:
        return f0
    win = (freqs >= 2 * f0 - 0.15) & (freqs <= min(2 * f0 + 0.15, hi))
    if not win.any():
        return f0
    k2 = int(np.flatnonzero(win)[np.argmax(power[win])])
    doubled = _refine(freqs, power, k2, lo, hi)
    if f0 < min_step_hz or power[k2] >= harmonic_ratio * power[k0]:
        return doubled
    if fx is not None and abs(fx - f0) <= 0.15:
        return doubled
    return f0


def estimate_cadence(t, dy, window_s: float, band_hz, min_peak_ratio: float, dx=None,
                     min_step_hz: float = 1.4, harmonic_ratio: float = 0.25) -> np.ndarray:
    """Per-sample step cadence in Hz (nan while unknown) from the vertical camera bob.

    Stride-aware (see ``_window_cadence``); ``dx`` is the optional cross-check.
    Causal: the estimate at time ``t`` only uses samples in (t - window_s, t],
    as the on-device version must. Needs at least 60 percent of the window. A
    value is held for one window length when a later window has no clear peak.
    """
    t = np.asarray(t, dtype=float)
    dy = np.asarray(dy, dtype=float)
    out = np.full(len(t), np.nan)
    if len(t) < 8:
        return out
    dt = float(np.median(np.diff(t)))
    if not dt > 0:
        return out
    tu = np.arange(t[0], t[-1] + 1e-9, dt)    # uniform resampling for the FFT
    yu = np.interp(tu, t, dy)
    xu = None if dx is None else np.interp(tu, t, np.asarray(dx, dtype=float))
    win = max(8, int(round(window_s / dt)))
    min_n = max(8, int(0.6 * win))
    stride = max(1, int(round(0.1 / dt)))
    band = (float(band_hz[0]), float(band_hz[1]))
    est_t, est_f = [], []
    for j in range(min_n - 1, len(tu), stride):
        sl = slice(max(0, j - win + 1), j + 1)
        est_t.append(tu[j])
        est_f.append(_window_cadence(yu[sl], dt, band, min_peak_ratio,
                                     None if xu is None else xu[sl], min_step_hz, harmonic_ratio))
    if not est_t:
        return out
    est_t, est_f = np.array(est_t), np.array(est_f)
    idx = np.searchsorted(est_t, t + 1e-9, side="right") - 1   # latest estimate <= t
    ok = idx >= 0
    out[ok] = est_f[idx[ok]]
    return _hold_last(t, out, window_s)


def _hold_last(t: np.ndarray, series: np.ndarray, hold_s: float) -> np.ndarray:
    """Forward-fill nan for up to ``hold_s`` after the last valid value: cadence changes slowly,
    and a window that momentarily has no clear peak should not blank the estimate."""
    out = series.copy()
    last, last_t = math.nan, -math.inf
    for i in range(len(t)):
        if not math.isnan(series[i]):
            last, last_t = series[i], t[i]
        elif t[i] - last_t <= hold_s:
            out[i] = last
    return out


def estimate_stationary(t, resid, cfg: dict) -> np.ndarray:
    """Per-sample "the user is standing still" flag from the residual image flow (``egoflow``; v26.1.11, review 4).

    The cadence detector cannot tell standing from walking (a standing user's chest camera bobs at 1-2 Hz too: review 4,
    286-345 s read 1.3-2.2 Hz and 1.1 m/s), the picture can: walking expands it, standing leaves the scene rigid.
    ``m`` = causal median of the residual flow (px) over ``medianSeconds`` (needs half the window valid). Stationary is
    entered after ``m < enterPx`` for ``enterSeconds`` and left after ``m >= leavePx`` for ``leaveSeconds``. A frame
    without texture (m unknown) never enters, and counts as walking evidence when leaving (a false "stationary" silences
    the warnings, a false "walking" only says too much). 4929: standing 308-346 s m 0.07-0.58, walking m >= 1.34."""
    t = np.asarray(t, dtype=float)
    r = np.asarray(resid, dtype=float)
    out = np.zeros(len(t), dtype=bool)
    if len(t) < 2:
        return out
    dt = float(np.median(np.diff(t)))
    if not dt > 0:
        return out
    n = max(3, int(round(float(cfg.get("medianSeconds", 1.0)) / dt)))
    enter_px, leave_px = float(cfg.get("enterPx", 0.8)), float(cfg.get("leavePx", 1.0))
    enter_s, leave_s = float(cfg.get("enterSeconds", 1.5)), float(cfg.get("leaveSeconds", 1.0))
    state, since = False, None
    for i in range(len(t)):
        w = r[max(0, i - n + 1):i + 1]
        w = w[~np.isnan(w)]
        m = float(np.median(w)) if len(w) >= 0.5 * n else math.nan
        if not state:
            if m < enter_px:
                since = t[i] if since is None else since
                if t[i] - since >= enter_s - 1e-9:
                    state, since = True, None
            else:
                since = None
        else:
            if math.isnan(m) or m >= leave_px:
                since = t[i] if since is None else since
                if t[i] - since >= leave_s - 1e-9:
                    state, since = False, None
            else:
                since = None
        out[i] = state
    return out


# --------------------------------------------------------------------------
# Class ids
# --------------------------------------------------------------------------

@dataclass
class ClassIds:
    """Config class names resolved to ids of this model."""
    surface_groups: dict[str, np.ndarray]
    inside: np.ndarray
    items: dict[str, list[int]]               # group -> class ids (static/moving/feature)
    names: list[str]                          # class id -> name
    people: frozenset = frozenset()           # class names treated as movers unless measured stationary
    fast: frozenset = frozenset()             # class names that cover 5-10 m/s (rider, vehicle): warned about early (v26.1.13)
    thin: frozenset = frozenset()             # class names warned about as "beware poles"
    landmark: frozenset = frozenset()         # feature class names announced as a landmark (crosswalk)


def resolve_class_ids(config: dict, class_names: list[str]) -> ClassIds:
    index = {n: i for i, n in enumerate(class_names)}

    def ids_of(names) -> np.ndarray:
        out = []
        for name in names:
            if name in index:
                out.append(index[name])
            else:
                _warn_once(f"class '{name}' not in this model, skipped")
        return np.array(out, dtype=np.int64)

    surf = config["surfaces"]
    return ClassIds(
        surface_groups={g: ids_of(v["classes"]) for g, v in surf["groups"].items()},
        inside=ids_of(surf["inside"]),
        items={g: [int(i) for i in ids_of(config["classes"].get(g, []))] for g in ITEM_GROUPS},
        names=list(class_names),
        people=frozenset(config["classes"].get("people", [])),
        fast=frozenset(config["classes"].get("fast", [])),
        thin=frozenset(config["classes"].get("thin", [])),
        landmark=frozenset(config["classes"].get("landmark", [])))


# --------------------------------------------------------------------------
# Walking region
# --------------------------------------------------------------------------

@dataclass
class Region:
    group: str
    label: str
    mask: np.ndarray                          # (H, W) bool
    left: np.ndarray                          # (H,) normalised x, nan = row has no region
    right: np.ndarray


def walking_region(grid: np.ndarray, ids: ClassIds, config: dict) -> Region | None:
    """Region of the surface group under the seed box, or None without surface pixels."""
    gh, gw = grid.shape
    x0, y0, x1, y1 = config["surfaces"]["seedBox"]
    box = grid[int(y0 * gh):max(int(math.ceil(y1 * gh)), int(y0 * gh) + 1),
               int(x0 * gw):max(int(math.ceil(x1 * gw)), int(x0 * gw) + 1)]
    counts = np.bincount(box.ravel(), minlength=int(grid.max()) + 1)
    best: tuple[int, int, str] | None = None
    for group, cls in ids.surface_groups.items():
        if cls.size == 0:
            continue
        per_class = counts[cls[cls < len(counts)]]
        if per_class.size == 0 or per_class.max() == 0:
            continue
        key = (int(per_class.max()), int(per_class.sum()), group)  # ties: more group pixels
        if best is None or key[:2] > best[:2]:
            best = key
    if best is None:
        return None
    group = best[2]
    group_ids = ids.surface_groups[group]
    seed = np.isin(grid, group_ids)
    seed_box = np.zeros_like(seed)
    seed_box[int(y0 * gh):max(int(math.ceil(y1 * gh)), int(y0 * gh) + 1),
             int(x0 * gw):max(int(math.ceil(x1 * gw)), int(x0 * gw) + 1)] = True
    allowed = seed | np.isin(grid, ids.inside)
    labels, _ = ndimage.label(allowed, structure=_4_CONNECTIVITY)
    keep = np.unique(labels[seed & seed_box])
    keep = keep[keep > 0]
    mask = np.isin(labels, keep)
    left = np.full(gh, np.nan)
    right = np.full(gh, np.nan)
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size:
        first = mask[rows].argmax(axis=1)
        last = gw - 1 - mask[rows][:, ::-1].argmax(axis=1)
        left[rows] = first / gw
        right[rows] = (last + 1) / gw
    return Region(group, config["surfaces"]["groups"][group]["label"], mask, left, right)


def _smooth_bounds(prev: np.ndarray | None, cur: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    """Per-row EMA; a row that is invalid now stays invalid, a new row starts at its value."""
    if prev is None:
        return cur.copy()
    out = cur.copy()
    both = ~np.isnan(prev) & ~np.isnan(cur)
    out[both] = (1 - alpha) * prev[both] + alpha * cur[both]
    return out


def estimate_horizon(left: np.ndarray, right: np.ndarray, config: dict,
                     bounds: tuple[float, float] = (0.0, 1.0)) -> float | None:
    """Intersection of lines fitted to the left/right bounds, or None when not credible.

    Each line uses the lowest 70 percent of that side's rows where the bound is
    a real path edge. Rows where a bound is clamped to the image border are
    dropped first: a clamped bound is a crop (the path is wider than the
    picture), not an edge, and would flatten the line. ``bounds`` are the left and right edge of the analysed
    window (a portrait window of the frame: its edges are crops too).
    """
    geo = config["geometry"]
    gh = len(left)
    fits = []
    for bound, clamped in ((left, left <= bounds[0] + 1e-6), (right, right >= bounds[1] - 1e-6)):
        rows = np.flatnonzero(~np.isnan(bound) & ~clamped)
        if rows.size < geo["minRegionRows"]:
            return None
        rows = rows[rows.size - int(math.ceil(0.7 * rows.size)):]
        if rows.size < geo["minRegionRows"]:
            return None
        fits.append(np.polyfit((rows + 0.5) / gh, bound[rows], 1))
    (a_l, b_l), (a_r, b_r) = fits
    if not (a_l < -0.02 and a_r > 0.02):          # must converge upward
        return None
    hy = (b_r - b_l) / (a_l - a_r)
    lo, hi = geo["horizonValidRange"]
    return float(hy) if lo <= hy <= hi else None


# --------------------------------------------------------------------------
# Per-frame geometry and items
# --------------------------------------------------------------------------

@dataclass
class _FrameGeo:
    """Everything derived from the horizon, shared by all items of one frame."""
    gh: int
    gw: int
    f: float
    horizon: float
    camera_height_m: float
    hfov_deg: float
    projection: str
    below: np.ndarray                         # (H,) rows whose bottom edge is below the horizon
    lane: np.ndarray                          # (H, W) danger lane
    lane_region: np.ndarray                   # lane within the dilated walking region
    region_dilated: np.ndarray                # (H, W)
    floor_below: np.ndarray                   # (H, W) True where the pixel below is walking region
    lateral_offset_m: float = 0.0             # walking axis relative to the camera axis (+ = right), see _walking_axis_offset_m


def _walking_axis_offset_m(settings: "CollisionSettings", heading_deg: float | None = None) -> float:
    """Lateral position (m, + = right) of the camera relative to the body centre line that the danger lane,
    the collision-course test and the reported laterals are centred on.

    The ONE place the lane's direction is decided. Today the lane runs straight along the camera's optical axis,
    shifted by the mounting side offset. With head or glasses mounting the camera heading differs from the
    walking direction when the head turns; a body heading (IMU) is meant to replace this (``heading_deg`` is the
    future hook: the body-vs-camera yaw), and only this function has to change."""
    return float(getattr(settings, "lateral_offset_m", 0.0))


def _frame_geometry(gh: int, gw: int, horizon: float, camera_height_m: float, f: float, hfov_deg: float,
                    lane_half_m: float, region: Region | None, margin_px: int,
                    projection: str = "rectilinear", lateral_offset_m: float = 0.0) -> _FrameGeo:
    rows_bottom = (np.arange(gh) + 1.0) / gh
    below = rows_bottom > horizon + 1e-9
    # half width of the lane in px at each row = lane_half * f / distance
    half_px = np.where(below, lane_half_m * (rows_bottom - horizon) * gh / camera_height_m, -1.0)
    col_c = np.arange(gw) + 0.5 - gw / 2.0
    if lateral_offset_m:
        # body lateral = camera lateral + offset; lane = |body lateral| <= half: its centre sits -offset*f/d px from the axis
        shift_px = np.where(below, lateral_offset_m * (rows_bottom - horizon) * gh / camera_height_m, 0.0)
        lane = np.abs(col_c[None, :] + shift_px[:, None]) <= half_px[:, None]
    else:
        lane = np.abs(col_c)[None, :] <= half_px[:, None]
    if region is not None:
        dil = ndimage.binary_dilation(region.mask, structure=ndimage.generate_binary_structure(2, 1),
                                      iterations=max(1, margin_px)) if margin_px > 0 else region.mask
    else:
        dil = np.zeros((gh, gw), dtype=bool)
    floor = np.zeros((gh, gw), dtype=bool)
    if region is not None:
        floor[:-1] = region.mask[1:]
    return _FrameGeo(gh, gw, f, horizon, camera_height_m, hfov_deg, projection, below, lane, lane & dil, dil, floor,
                     lateral_offset_m)


@dataclass
class _Item:
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
    clipped: bool                             # touches the bottom image edge: distance is a lower bound
    touches: bool                             # touches the dilated walking region
    lane_hit: bool                            # (static/moving) in lane within region; (feature) in lane
    along_path: bool                          # long stretch of path inside the region: a boundary, not an obstacle
    lane_cover: float                         # share of the lane's width at the contact row that it covers
    contact_y_raw: float = 0.0
    area_m2: float = 0.0                      # component area scaled to square metres at its distance
    # filled in by tracking / roles
    track_id: int = 0
    closing: float | None = None
    moving: bool | None = None
    approaching: bool = False
    steps: float = 0.0
    label: str = ""
    role: str = "none"
    urgency: str = "none"
    settled: bool = False                     # track old enough to speak or beep
    family: str = ""                          # label family used as context-memory key ("" = use label)
    role_run: int = 0                         # consecutive frames the track has held ``role`` (incl. this one)
    closing_raw: float | None = None          # closing speed in uncalibrated model metres (k = 1)
    landmark: bool = False                    # a crosswalk: announced once as a location marker
    receding: bool = False                    # a mover measured to walk away from us
    ego_known: bool = False                   # our own speed is known, so this item's motion can be measured
    own_fast: bool = False                    # a rider / vehicle closing faster than any walking speed could explain (v26.1.16)
    ego_settled: bool = False                 # ...and the robust ego speed has its full window: motion words / the motion wait apply (v26.1.15)
    summary_ok: bool = False                  # would be context but for the lateral cap: allowed in the first scene summary
    people: bool = False                      # person / rider / animal: a mover unless measured stationary
    fast: bool = False                        # rider / vehicle: announced as early as possible, without a distance (v26.1.13)
    speak: bool = True                        # may be spoken; False = beeps only (a person within 5 steps, v26.1.13)
    thin: bool = False                        # pole, light, sign: easy to miss, warned about when noticed
    collision: bool = False                   # a danger on a collision course: the only thing that beeps (parking beeps)
    prox_run: int = 0                         # consecutive frames the track has been a proximity item (confirmFrames)
    proximity: bool = False                   # a person / animal measured approaching, close and not on a collision course: soft sound (v26.1.13 follow-up)
    present_run: int = 0                      # consecutive analysed frames the track has been seen
    wx: float = 0.0                           # dead-reckoned world position (m), see _WorldMemory
    wy: float = 0.0
    mem_id: int | None = None                 # the remembered object this item is, if any
    mem_named: bool = False                   # ... and it was named (False: only covered by a cluster notice)
    mem_approach: bool = False                # ... and it was announced as "approaching"
    mem_danger: bool = False                  # ... and it was announced as a danger / final (v26.1.16: only that mutes a later danger)
    shape: tuple | None = None                # (cropped component mask, col0, row0): source of the outline (v26.1.8)
    clock_q: int | None = None                # quarter-hour clock index (v26.1.10); derived from ``clock`` if not given
    clock_text: str = ""                      # spoken clock position, "12", "12:15", "11:45"
    depth_m: float | None = None              # metric depth under the item's lower rows (experiment), if a depth map exists
    depth_on: bool = False                    # a depth map exists for this frame (``depthM`` is reported, maybe null)
    depth_raw: float | None = None            # depth under the item's lower rows in the map's own units (metres or relative)
    from_depth: bool = False                  # distance_m was taken from the depth map
    lat_vel: float | None = None              # own sideways ground velocity (m/s, + = right), see _lateral_velocity (v26.1.11)
    cross_mps: float | None = None            # velocity across the line of sight from the bearing rate (m/s, + = right), see _cross_velocity (v26.1.12)
    depth_cells: tuple | None = None          # (rows, cols) the depth is read from instead of the component's lowest rows (lane part: its base)
    lane_part_weak: bool = False              # ...whose base is not flat: it only continues a lane part that was flat a moment ago (laneBaseHoldSeconds)
    lane_part: bool = False                   # the extra item of a wall / building whose ground base crosses the lane (v26.1.16 follow-up)
    map_source: str = ""                      # "map": a static item judged on the fused world map (v26.2.1); "image": no map cells to read (its contact point); "": staticSource image
    map_cells: int = 0                        # (map) cells of the item's family inside the walking corridor
    map_world: tuple | None = None            # (map) world position of its nearest corridor cell (a ghost is followed from it)
    image_dl: tuple | None = None             # (map, in the corridor) the image contact point's (distance, lateral, bearing, clock, clock_q, clock_text, pan) the map measurement replaced
    solid_corrected: bool = False             # (v26.2.2, insideSolid.mode "snap") its distance was moved to the near border of the solid area
    raw_distance_m: float | None = None       # ...the measured distance before the correction
    inside_solid: bool = False                # (v26.2.2) its map position is inside / behind a solid wall face: impossible, so it is muted (no speech, beeps, proximity)
    coasting: bool = False                    # (v26.2.2) a mover that left the image: predicted on its last world velocity, beeps / course only
    ghost: bool = False                       # (map) no longer in the image (under the frame): kept alive by its map cells
    map_judged: bool = False                  # (v26.2.2) a wall-like static item judged on the map alone (no image lane rule)
    face_edge: dict | None = None             # (v26.2.2, roles.faceEdge.enabled) the face / edge test of its corridor cells: diagnostics only

    def __post_init__(self) -> None:
        if self.clock_q is None:
            self.clock_q = _quarter_of_hour(self.clock)
        if not self.clock_text:
            self.clock_text = clock_text(self.clock_q)


def _bottom_point(rows: np.ndarray, cols: np.ndarray, sel: np.ndarray, gw: int) -> tuple[int, int]:
    """Lowest selected pixel; on that row the column nearest the image centre."""
    r = rows[sel].max()
    on_row = sel & (rows == r)
    c_all = cols[on_row]
    c = int(c_all[np.argmin(np.abs(c_all + 0.5 - gw / 2.0))])
    return int(r), c


def detect_items(grid: np.ndarray, ids: ClassIds, geo: _FrameGeo, config: dict) -> list[_Item]:
    """Components (per class, 4-connected, below the horizon) with contact geometry.

    Per class rather than per class *group*: a pole standing against a wall is
    two items, not one wall-labelled blob that hides the pole.
    """
    gh, gw = geo.gh, geo.gw
    min_pixels = config["minComponentFraction"] * gw * gh
    max_range = config["geometry"]["maxRangeM"]
    items: list[_Item] = []
    lane_base_classes = frozenset(config["roles"].get("laneBaseClasses", ()))
    if config["roles"].get("staticSource", "image") == "map":
        lane_base_classes = frozenset()           # v26.2.1: the corridor test of the map covers the lane part
    present = np.bincount(grid.ravel(), minlength=int(grid.max()) + 1)
    for group in ITEM_GROUPS:
        for cid in ids.items[group]:
            if cid >= len(present) or present[cid] == 0:
                continue
            mask = (grid == cid) & geo.below[:, None]
            if not mask.any():
                continue
            labels, n = ndimage.label(mask, structure=_4_CONNECTIVITY)
            for k, sl in enumerate(ndimage.find_objects(labels), start=1):
                rr, cc = np.nonzero(labels[sl] == k)
                if rr.size < min_pixels:
                    continue
                rr = rr + sl[0].start
                cc = cc + sl[1].start
                in_lane_region = geo.lane_region[rr, cc]
                in_lane = geo.lane[rr, cc]
                everything = np.ones(rr.size, dtype=bool)
                if group == "feature":
                    sel = in_lane if in_lane.any() else everything
                    lane_hit = bool(in_lane.any())
                else:
                    # v26.1.5: the contact point is the item's true lowest pixel (where it stands). It
                    # counts as "in the lane" only if that lowest row itself touches the lane inside the
                    # walking region; a car beside the path whose roof or bumper pixels intrude does not.
                    sel = everything
                    lane_hit = bool(in_lane_region[rr == rr.max()].any())
                row, col = _bottom_point(rr, cc, sel, gw)
                if ids.names[cid] == "rider":
                    # v26.1.13 (review 6, 445.3 s "position is wrong"): the lowest row of a bicycle + rider is the wheels, and the column
                    # nearest the image centre on it is the wheel's far edge, up to a quarter-hour clock position off the body. A rider's
                    # horizontal position is the middle of that row.
                    on_row = cc[rr == rr.max()]
                    col = int((on_row.min() + on_row.max()) // 2)
                contact_y = (row + 1) / gh
                dist = ground_distance_m(contact_y, geo.horizon, geo.camera_height_m, gh, geo.f)
                if dist is None or dist > max_range:
                    continue
                inreg = geo.region_dilated[rr, cc]
                # "Runs along the path" is judged on where the item stands on the floor: its pixels
                # with walking region directly below. A wall's or median's base spans a long stretch of
                # path; a pole touches the floor on one row. (Its upper pixels would all look like far
                # ground, which is why every row of a thin pole is NOT used.)
                base = geo.floor_below[rr, cc]
                along = False
                if base.any():
                    d_far = ground_distance_m((rr[base].min() + 1) / gh, geo.horizon, geo.camera_height_m, gh, geo.f)
                    d_near = ground_distance_m((rr[base].max() + 1) / gh, geo.horizon, geo.camera_height_m, gh, geo.f)
                    along = bool(d_far and d_near and d_near / d_far < config["roles"]["alongPathRatio"])
                lane_row = geo.lane[row]
                cover = 0.0
                if lane_row.any():
                    cover = float(np.count_nonzero((rr == row) & in_lane)) / float(lane_row.sum())
                x = (col + 0.5) / gw
                bearing = bearing_deg(x, geo.hfov_deg, geo.projection)
                main = _Item(
                    group=group, class_name=ids.names[cid],
                    bbox=[cc.min() / gw, rr.min() / gh, (cc.max() + 1) / gw, (rr.max() + 1) / gh],
                    contact_y=contact_y, distance_m=dist, lateral_m=lateral_m(x, dist, gw, geo.f) + geo.lateral_offset_m,
                    bearing=bearing, clock=clock_from_bearing(bearing),
                    clock_q=(cq := clock_quarter(bearing)), clock_text=clock_text(cq), pan=_pan_from_bearing(bearing),
                    area_frac=rr.size / (gh * gw), clipped=bool(rr.max() == gh - 1),
                    touches=bool(inreg.any()), lane_hit=lane_hit,
                    along_path=along, lane_cover=cover, contact_y_raw=contact_y,
                    area_m2=rr.size * (dist / geo.f) ** 2,
                    people=ids.names[cid] in ids.people, fast=ids.names[cid] in ids.fast, thin=ids.names[cid] in ids.thin,
                    landmark=ids.names[cid] in ids.landmark,
                    shape=(labels[sl] == k, sl[1].start, sl[0].start))
                items.append(main)
                if group == "static" and ids.names[cid] in lane_base_classes and (not lane_hit or along):
                    part = _lane_part_item(main, rr, cc, geo, config)
                    if part is not None:
                        items.append(part)
    return items


def _lane_part_item(main: _Item, rr: np.ndarray, cc: np.ndarray, geo: _FrameGeo,
                    config: dict) -> _Item | None:
    """v26.1.16 follow-up (review 8, 10.9 s): the part of a wall / building that stands IN the lane.

    A static item is measured at its lowest pixel, so a building whose side wall runs along the sidewalk and whose scaffolded
    section juts out across the path is measured at the side wall's base (context) and the section in the lane is never
    judged. Its ground base is: the component's pixels with walking region directly below them (``floor_below``, the same
    test as ``along_path``) that lie inside the lane within the walking region. Pixels ABOVE such a base never count (the
    earlier attempt, "any pixel over a lane cell", made every wall along a sidewalk a danger). With at least
    ``laneBaseMinColumns`` columns of it, the extra item has its contact at the lowest base cell (on that row the column
    nearest the lane centre), ``lane_hit`` True and ``along_path`` False; area and outline are the whole component's."""
    roles = config["roles"]
    gh, gw = geo.gh, geo.gw
    sel = geo.floor_below[rr, cc] & geo.lane_region[rr, cc]
    if not sel.any() or np.unique(cc[sel]).size < roles.get("laneBaseMinColumns", 2):
        return None
    # a wall seen edge-on along the path has a DIAGONAL base (one or two cells per row, over many rows); a face across the
    # lane has a FLAT one: enough cells in one row, and that row holding a good share of all the base cells
    widest = int(np.bincount(rr[sel]).max())
    flat = widest >= roles.get("laneBaseMinRowColumns", 1) and widest >= roles.get("laneBaseMinConcentration", 0.0) * np.count_nonzero(sel)
    row = int(rr[sel].max())
    on_row = cc[sel & (rr == row)]
    lane_cols = np.flatnonzero(geo.lane[row])
    centre = float(lane_cols.mean()) if lane_cols.size else gw / 2.0 - 0.5
    col = int(on_row[np.argmin(np.abs(on_row - centre))])
    contact_y = (row + 1) / gh
    dist = ground_distance_m(contact_y, geo.horizon, geo.camera_height_m, gh, geo.f)
    if dist is None or dist > config["geometry"]["maxRangeM"]:
        return None
    x = (col + 0.5) / gw
    bearing = bearing_deg(x, geo.hfov_deg, geo.projection)
    return replace(
        main, contact_y=contact_y, contact_y_raw=contact_y, distance_m=dist,
        lateral_m=lateral_m(x, dist, gw, geo.f) + geo.lateral_offset_m,
        bearing=bearing, clock=clock_from_bearing(bearing), clock_q=(cq := clock_quarter(bearing)), clock_text=clock_text(cq),
        pan=_pan_from_bearing(bearing), clipped=bool(row == gh - 1), touches=True, lane_hit=True, along_path=False,
        lane_cover=float(np.count_nonzero(sel & (rr == row))) / float(max(1, lane_cols.size)), lane_part=True, lane_part_weak=not flat,
        depth_cells=(rr[sel], cc[sel]))


# --------------------------------------------------------------------------
# Tracking
# --------------------------------------------------------------------------

@dataclass
class _Track:
    id: int
    group: str
    class_name: str
    box: Box
    last_t: float
    first_t: float
    last_distance: float
    last_lateral: float
    history: list[tuple[float, float]] = field(default_factory=list)   # (t, distanceM)
    closing: float | None = None
    moving: bool | None = None
    # speech bookkeeping, set only when the phrase is really spoken
    danger_done: bool = False
    final_done: bool = False
    feature_done: bool = False
    thin_done: bool = False
    contact_s: float | None = None            # smoothed contact row: the distance (and so the steps) is read from it
    present_run: int = 0                      # consecutive analysed frames this track was matched
    # confirmation: consecutive analysed frames holding the same role (v26.1.5)
    role: str = "none"
    role_run: int = 0
    mem_id: int | None = None                 # world-memory object this track was matched to (v26.1.7)
    linked_t: float = 0.0                     # when it was matched to it
    under_last: float | None = None           # last time a curb/crosswalk track had its contact under our feet
    under_fired: bool = False
    dhist: list[tuple[float, float]] = field(default_factory=list)     # (t, depthM) of the depth experiment
    lhist: list[tuple] = field(default_factory=list)                    # (t, lateral m, distance m, heading deg): v26.1.11 own sideways velocity
    lp_strong_t: float | None = None          # last time the lane part had a flat base
    lane_part: bool = False                   # track of a wall's / building's lane part (v26.1.16 follow-up)
    along_s: float | None = None              # smoothed speed along the line of sight over the ground (m/s, + = towards us), v26.1.11
    along_t: float = 0.0
    feature_frames: int = 0                   # frames it held role "feature" in the lane, not along the path: a real crossing (v26.1.11)
    approach_done: bool = False               # announced as "approaching" (v26.1.12): the one re-announcement after an earlier phrase
    mstate: str | None = None                 # motion state with hysteresis: "still" | "approach" | "recede" | "side" | None (v26.1.12)
    prox_run: int = 0                         # consecutive analysed frames the item was a proximity item (v26.1.13 follow-up)
    context_seen: bool = False                # the track has been a context item (v26.1.16)
    ghost_src: "_Item | None" = None          # a static danger that may be followed on in the map once the image loses it (v26.2.1)
    ghost_t0: float | None = None             # since when it has been a ghost
    still_t0: float | None = None             # since when |own along speed| < standingMps without a break (v26.1.12)


def _closing_mps(history: list[tuple[float, float]], horizon: float, camera_height_m: float, gh: int, f: float,
                 min_rows: float, min_span_s: float, min_points: int = 3) -> float | None:
    """-slope of distance over time, with every history row re-projected through the CURRENT horizon.

    A track stores contact rows, not distances: the per-frame horizon wobbles
    (up to +-0.03 near the vanishing point), and distances computed with a
    different horizon each frame would turn a parked car at a fixed row into
    something "approaching at 6 m/s". Rows close to the horizon (< ``min_rows``
    grid rows) are too coarse to differentiate: such points are left out, and the answer is None
    while the latest point is one of them or too few remain.
    """
    t = np.array([h[0] for h in history])
    y = np.array([h[1] for h in history])
    keep = (y - horizon) * gh >= min_rows           # older points nearer the horizon are simply left out
    t, y = t[keep], y[keep]
    if len(t) < min_points or t[-1] - t[0] < min_span_s or t[-1] != history[-1][0]:
        return None
    d = camera_height_m * f / ((y - horizon) * gh)
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    if denom <= 0:
        return None
    return -float((tc * (d - d.mean())).sum() / denom)


def _depth_closing(history: list[tuple[float, float]], t_now: float, min_span_s: float,
                   min_points: int = 3) -> float | None:
    """-slope of the metric depth history; needs >= 3 points, >= ``min_span_s`` of history, latest point = now."""
    if len(history) < min_points or history[-1][0] != t_now or history[-1][0] - history[0][0] < min_span_s:
        return None
    t = np.array([h[0] for h in history])
    d = np.array([h[1] for h in history])
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    return None if denom <= 0 else -float((tc * (d - d.mean())).sum() / denom)


def _lateral_velocity(hist: list[tuple], min_span_s: float, min_points: int = 3) -> float | None:
    """Sideways ground velocity (m/s, + = right) of a track in the camera frame of its newest sample, from its
    (t, lateral m, distance m, heading deg) history; None without >= 3 points over >= ``min_span_s`` s or a heading.

    Our own turn moves everything sideways in the picture (a pole at 6 m turns by 1 m/s while we turn 10 deg/s), so every
    point is first re-expressed in the newest heading: ``lat - (heading_now - heading_then) * distance`` (heading + = a
    right turn, which shifts the scene left). Forward walking does not change a static object's lateral position, so
    for a static item the result is ~0 plus noise (see ``_sideways_mps``: 0.5 m/s median, 1.4-2.4 at p90 on 4929) and
    for a mover it is its own sideways speed (v26.1.11). The correction is first order: the old samples are rotated
    but not shifted by our own forward step, which leaves ~1.4 m/s x sin(turn) over a 2 s window."""
    if len(hist) < min_points or hist[-1][0] - hist[0][0] < min_span_s or any(h[3] is None for h in hist):
        return None
    t = np.array([h[0] for h in hist])
    th_now = hist[-1][3]
    lat = np.array([h[1] - math.radians(th_now - h[3]) * h[2] for h in hist])
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    return None if denom <= 0 else float((tc * (lat - lat.mean())).sum() / denom)


def _cross_velocity(hist: list[tuple], speed: float | None, window_s: float) -> float | None:
    """Velocity across the line of sight (m/s, + = right) from the bearing rate of the track (v26.1.12, review 5).

    ``hist`` = (t, lateral m, distance m, heading deg, bearing deg of the bbox centre). The heading (the camera's yaw, from the
    motion series) is added back to the bearings, so our own turn cancels. A STATIC point at bearing theta and range R seen
    by someone walking at ``speed`` drifts outwards at ``speed * sin(theta) / R`` rad/s; what is left over after
    ``R * rate - speed * sin(theta)`` is the item's own sideways speed. Needs >= 4 points over >= 0.7 of ``window_s`` and a
    heading; None otherwise. Unlike the lateral-offset derivative this never differentiates the noisy distance, but it is
    still weak (numbers: see DECISIONS v26.1.12), so it is used only as a veto for "standing" (``standingMaxCrossMps``)."""
    pts = [h for h in hist if h[0] >= hist[-1][0] - window_s - 1e-9] if hist else []
    if speed is None or len(pts) < 4 or pts[-1][0] - pts[0][0] < 0.7 * window_s or any(h[3] is None for h in pts):
        return None
    t = np.array([h[0] for h in pts])
    th = np.radians(np.array([h[4] for h in pts]) + np.array([h[3] for h in pts]))
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    if denom <= 0:
        return None
    rate = float((tc * (th - th.mean())).sum() / denom)                       # rad/s
    # range and bearing at the middle of the window, where the fitted rate belongs (distance_m is the forward distance)
    rng = float(np.mean([math.hypot(h[2], h[1]) for h in pts]))
    return rng * rate - speed * math.sin(math.radians(float(np.mean([h[4] for h in pts]))))


def _item_depth_m(it: _Item, dmap: np.ndarray, gh: int, gw: int, lowest_frac: float) -> float | None:
    """Median metric depth under the lowest ``lowest_frac`` of the item's rows (component pixels, mapped by
    normalised coordinates onto the depth grid); None without a valid pixel."""
    if it.depth_cells is not None:                 # a lane part stands where its base is, not where the whole building's lowest rows are
        rr, cc = it.depth_cells
    else:
        mask, c0, r0 = it.shape
        rr, cc = np.nonzero(mask)
        rr = rr + r0
        cc = cc + c0
    if rr.size == 0:
        return None
    h = int(rr.max() - rr.min() + 1)
    keep = rr >= rr.max() + 1 - max(1, int(math.ceil(lowest_frac * h)))
    dh, dw = dmap.shape
    dr = np.minimum(dh - 1, ((rr[keep] + 0.5) / gh * dh).astype(int))
    dc = np.minimum(dw - 1, ((cc[keep] + 0.5) / gw * dw).astype(int))
    v = dmap[dr, dc].astype(float)
    v = v[np.isfinite(v) & (v > 0.0)]
    return None if v.size == 0 else float(np.median(v))


def _match(tracks: dict[int, _Track], items: list[_Item], t: float, trk: dict, pan_shift: float = 0.0,
           people: frozenset = frozenset()) -> dict[int, int]:
    """Greedy matching, same group+class; IoU or the ground gate. Returns {item index: track id}.

    ``pan_shift`` (v26.1.16, review 8, 27.3 s): how far the whole scene moved sideways in the image since the previous frame because
    the camera turned (normalised x; + = scene moved right). A person at 5.7 m jumped a full box width in one frame while the head
    turned 9 degrees: no overlap, so the track was lost, restarted (age 0, no motion, confirmation from 1) three times and the
    announcement came 1.2 s late. For people (they walk and fragment under a pan; a pole or a building is re-found by the ground gate) and only in a hard turn
    (``tracking.panMatchMinShift``) the IoU is also taken against the track's box moved by the pan."""
    pairs = []
    for tid, tr in tracks.items():
        dt = t - tr.last_t
        expected = -(tr.closing or 0.0) * dt
        moved = (Box(tr.box.x1 + pan_shift, tr.box.y1, tr.box.x2 + pan_shift, tr.box.y2)
                 if abs(pan_shift) >= trk.get("panMatchMinShift", 0.0) and tr.class_name in people else None)
        for ii, it in enumerate(items):
            if it.group != tr.group or it.class_name != tr.class_name or it.lane_part != tr.lane_part:
                continue                           # a lane part (v26.1.16 follow-up) is its own track, never the side wall's
            v = iou(tr.box, Box(*it.bbox))
            if moved is not None:
                v = max(v, iou(moved, Box(*it.bbox)))
            gate = (abs(it.lateral_m - tr.last_lateral) <= trk["groundGateLateralM"]
                    and abs((it.distance_m - tr.last_distance) - expected)
                    <= trk["groundGateDistanceFrac"] * it.distance_m)
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


# --------------------------------------------------------------------------
# Ego state
# --------------------------------------------------------------------------

@dataclass
class _Ego:
    speed: float | None = None
    speed_t: float = -math.inf
    cadence: float | None = None
    heading: float | None = None
    ref_heading: float | None = None
    exceed_since: float | None = None

    def update_speed(self, closings: list[float], t: float, cfg: dict) -> None:
        if len(closings) >= cfg["speedMinTracks"]:
            v = float(np.median(closings))
            self.speed = v if self.speed is None else (1 - cfg["speedEma"]) * self.speed + cfg["speedEma"] * v
            self.speed_t = t
        elif self.speed is not None and t - self.speed_t > 5.0:
            self.speed = None                  # stale: do not judge parked-vs-moving on it

    def update_heading(self, heading: float | None, t: float, cfg: dict, dt: float) -> bool:
        """True when the heading has stayed more than headingDeg off the slow reference for sustainSeconds."""
        self.heading = heading
        if heading is None:
            return False
        if self.ref_heading is None:
            self.ref_heading = heading
        self.ref_heading += (heading - self.ref_heading) * min(1.0, dt / cfg["referenceTauSeconds"])
        if abs(heading - self.ref_heading) <= cfg["headingDeg"]:
            self.exceed_since = None
            return False
        if self.exceed_since is None:
            self.exceed_since = t
        if t - self.exceed_since >= cfg["sustainSeconds"]:
            self.ref_heading, self.exceed_since = heading, None
            return True
        return False


class _Scale:
    """Gait calibration of the metric scale (CONTRACTS.md section 14.1.1).

    ``k = median(cadence) * priorStepLengthM / median(raw ego speed)`` over the last
    ``calibrationWindowSeconds`` of frames where both are known. Walking is the ruler: whatever
    camera height / field of view error makes the raw metres wrong, the ratio absorbs it. The first
    estimate is taken as soon as ``calibrationMinSamples`` frames exist (a cold start must not wait
    20 s); later estimates are blended in with a slow, evidence-growing time constant. Without cadence (standing still)
    nothing is added, so the last k is held; before the first estimate k is 1.
    """

    def __init__(self, cfg: dict, prior_step_m: float):
        self.window_s = float(cfg.get("calibrationWindowSeconds", 20.0))
        self.min_samples = int(cfg.get("calibrationMinSamples", 18))
        self.tau_min_s = float(cfg.get("calibrationEmaMinSeconds", 3.0))
        self.tau_s = float(cfg.get("calibrationEmaSeconds", 40.0))
        self.age_s = 0.0                                          # seconds of estimates blended so far
        self.lo, self.hi = cfg.get("scaleRange", [0.5, 4.0])
        self.min_raw = float(cfg.get("calibrationMinRawSpeed", 0.2))
        self.prior_step_m = prior_step_m
        self.samples: list[tuple[float, float, float]] = []      # (t, cadence Hz, raw speed m/s)
        self.k: float | None = None                               # the measured target (None until the first estimate)
        self.applied = 1.0                                        # what the geometry uses: k slewed towards the target
        self.max_rate = float(cfg.get("scaleMaxChangePerSecond", 0.25))
        self.from_gait = False
        prior = cfg.get("scalePrior")
        if prior:                                                 # optional warm start (null = k 1 until measured)
            self.k = self.applied = float(prior)
            self.age_s = float(cfg.get("scalePriorSeconds", 30.0))

    def update(self, t: float, cadence: float | None, raw_speed: float | None, dt: float) -> None:
        if cadence is not None and cadence > 0 and raw_speed is not None and raw_speed > 0:
            self.samples.append((t, cadence, raw_speed))
        self.samples = [x for x in self.samples if x[0] >= t - self.window_s - 1e-9]
        self._estimate(dt)
        if self.k is not None and self.applied != self.k:
            # steps are distance / step length, so a sudden change of k would make every step count jump:
            # the applied scale moves towards the target at most ``scaleMaxChangePerSecond`` (25 percent/s)
            lim = self.max_rate * max(dt, 0.0)
            self.applied = math.exp(
                math.log(self.applied) + max(-lim, min(lim, math.log(self.k) - math.log(self.applied))))

    def _estimate(self, dt: float) -> None:
        if len(self.samples) < self.min_samples:
            return
        v = float(np.median([x[2] for x in self.samples]))
        if v < self.min_raw:
            return
        k_inst = min(self.hi, max(self.lo, float(np.median([x[1] for x in self.samples])) * self.prior_step_m / v))
        if self.k is None:
            self.k = k_inst
            self.from_gait = True
        else:
            self.from_gait = True
            # slow smoothing, but a young estimate (a cold start) may still move quickly: the time
            # constant grows with the evidence, from ``calibrationEmaMinSeconds`` to ``calibrationEmaSeconds``
            self.age_s += max(dt, 0.0)
            tau = min(self.tau_s, max(self.tau_min_s, self.age_s))
            a = 1.0 - math.exp(-max(dt, 0.0) / tau)
            self.k = math.exp(math.log(self.k) + a * (math.log(k_inst) - math.log(self.k)))

    @property
    def value(self) -> float:
        return self.applied


class _DepthAnchor:
    """Per-frame scale of a RELATIVE depth map from the ground under our feet.

    The relative maps match the metric ones up to ONE scale per frame, but that scale drifts from frame to
    frame. Walking-region pixels at least ``motionMinRowsBelowHorizon`` rows below the horizon have a flat-
    ground z-distance ``g`` (uncalibrated camera height, k = 1); ``a_t = median(g / rel)`` maps relative units
    onto that ground metre. Smoothed lightly in log space (``anchorEmaSeconds``); a frame without enough
    cells (``anchorMinCells``) holds the last anchor for ``anchorHoldSeconds``, then there is none.
    """

    def __init__(self, dist_cfg: dict):
        self.min_cells = int(dist_cfg.get("anchorMinCells", 150))
        self.tau_s = float(dist_cfg.get("anchorEmaSeconds", 0.5))
        self.hold_s = float(dist_cfg.get("anchorHoldSeconds", 2.0))
        self.log_a: float | None = None
        self.last_t = -math.inf

    def update(self, t: float, dt: float, raw: float | None, cells: int) -> None:
        if raw is not None and cells >= self.min_cells and math.isfinite(raw) and raw > 0:
            x = math.log(raw)
            if self.log_a is None or t - self.last_t > self.hold_s or self.tau_s <= 0:
                self.log_a = x                                       # tau 0 = no smoothing
            else:
                self.log_a += (1.0 - math.exp(-max(dt, 0.0) / self.tau_s)) * (x - self.log_a)
            self.last_t = t
        elif self.log_a is not None and t - self.last_t > self.hold_s:
            self.log_a = None

    @property
    def value(self) -> float | None:
        return None if self.log_a is None else math.exp(self.log_a)


class _InitialAnchor:
    """One-shot depth anchor (``anchor: "initial"``, DA2 metric): a stable but biased absolute level.

    Collects the per-frame ground ratios (as ``_DepthAnchor`` would use) of valid frames (>= ``anchorMinCells``
    cells; invalid frames do not count). The running median is usable from ``initialAnchorMinFrames`` (3) valid
    ratios; at ``initialAnchorFrames`` (6) it is frozen and held for the rest of the run. ``reset()`` starts a
    new collection (path change, only when ``recalibrateOnPathChange``). Same interface as ``_DepthAnchor``.
    """

    def __init__(self, dist_cfg: dict):
        self.min_cells = int(dist_cfg.get("anchorMinCells", 150))
        self.n_freeze = int(dist_cfg.get("initialAnchorFrames", 6))
        self.n_min = min(int(dist_cfg.get("initialAnchorMinFrames", 3)), self.n_freeze)
        self.reset()

    def reset(self) -> None:
        self.ratios: list[float] = []
        self.frozen: float | None = None
        self._run: float | None = None

    def update(self, t: float, dt: float, raw: float | None, cells: int) -> None:
        if self.frozen is not None:
            return
        if raw is not None and cells >= self.min_cells and math.isfinite(raw) and raw > 0:
            self.ratios.append(float(raw))
            self._run = float(np.median(self.ratios)) if len(self.ratios) >= self.n_min else None
            if len(self.ratios) >= self.n_freeze:
                self.frozen = self._run

    @property
    def value(self) -> float | None:
        return self.frozen if self.frozen is not None else self._run


def _ground_anchor(region: Region | None, dmap: np.ndarray, horizon: float, camera_height_m: float,
                   gh: int, gw: int, f: float, min_rows: float) -> tuple[float | None, int]:
    """(median of flat-ground z-distance / relative depth, cell count) over walking-region cells."""
    if region is None:
        return None, 0
    rr, cc = np.nonzero(region.mask)
    keep = rr + 0.5 - horizon * gh >= min_rows
    rr, cc = rr[keep], cc[keep]
    if rr.size == 0:
        return None, 0
    dh, dw = dmap.shape
    rel = dmap[np.minimum(dh - 1, ((rr + 0.5) / gh * dh).astype(int)),
               np.minimum(dw - 1, ((cc + 0.5) / gw * dw).astype(int))].astype(float)
    ok = np.isfinite(rel) & (rel > 0.0)
    if not ok.any():
        return None, 0
    g = camera_height_m * f / (rr[ok] + 0.5 - horizon * gh)
    return float(np.median(g / rel[ok])), int(ok.sum())


@dataclass
class _PlaneFit:
    height_units: float                       # camera height above the fitted plane, in depth units
    pitch_deg: float                          # + = looking down
    inliers: int
    fraction: float


def _plane_fit(region: Region | None, dmap: np.ndarray, horizon: float, gh: int, gw: int, f: float,
               min_rows: float, hfov_deg: float, projection: str, dist_cfg: dict) -> _PlaneFit | None:
    """Ground plane through the walking-region cells, from the z-depth map and the pixel rays (None = invalid frame).

    Cells: region cells >= ``min_rows`` below the anchor horizon with finite depth > 0, back-projected to camera
    coordinates (X right, Y down, Z forward): rectilinear X = (u-0.5)W/f z, Y = (v-0.5)H/f z; fisheye (equidistant,
    f = W / hfov rad) ray = (sin t cos p, sin t sin p, cos t), t = r/f, scaled so its Z equals z.
    Fit in normalised form ``Y/Z = c/Z + a X/Z + b`` (plane Y = c + aX + bZ; linear, residuals are image-like and
    independent of range): deterministic RANSAC (3-point, fixed seed) for a clutter-proof start, then least
    squares on the inliers with 3 rounds rejecting residuals > 2.5x the median absolute residual.
    Valid: >= ``anchorMinCells`` inliers, inlier fraction >= ``planeMinInlierFraction`` (0.6), normal within
    ``planeMaxNormalDeg`` (35) of the camera's down axis and the plane below the camera.
    Height h = c / sqrt(1+a^2+b^2); pitch = asin(-b / sqrt(1+a^2+b^2)) (+ = looking down)."""
    if region is None:
        return None
    rr, cc = np.nonzero(region.mask)
    keep = rr + 0.5 - horizon * gh >= min_rows
    rr, cc = rr[keep], cc[keep]
    if rr.size == 0:
        return None
    dh, dw = dmap.shape
    z = dmap[np.minimum(dh - 1, ((rr + 0.5) / gh * dh).astype(int)),
             np.minimum(dw - 1, ((cc + 0.5) / gw * dw).astype(int))].astype(float)
    ok = np.isfinite(z) & (z > 0.0)
    min_cells = int(dist_cfg.get("anchorMinCells", 150))
    if ok.sum() < min_cells:
        return None
    z, px, py = z[ok], cc[ok] + 0.5 - gw / 2.0, rr[ok] + 0.5 - gh / 2.0
    if projection == "fisheye":
        f_eq = gw / math.radians(hfov_deg)
        r = np.hypot(px, py)
        theta = r / f_eq
        c_t = np.cos(theta)
        if np.any(c_t <= 1e-3):
            m = c_t > 1e-3
            z, px, py, r, theta, c_t = z[m], px[m], py[m], r[m], theta[m], c_t[m]
        sin_over_r = np.where(r > 0, np.sin(theta) / np.maximum(r, 1e-12), 0.0)
        xn = sin_over_r * px / c_t                    # X/Z, Y/Z of the ray
        yn = sin_over_r * py / c_t
    else:
        xn, yn = px / f, py / f
    n = z.size
    if n < min_cells:
        return None
    w = 1.0 / z
    A = np.stack([w, xn, np.ones(n)], axis=1)         # y_n = c w + a x_n + b
    # --- RANSAC start (deterministic)
    rng = np.random.RandomState(12345)
    tau = float(dist_cfg.get("planeRansacTol", 0.02))
    best, best_cnt = None, -1
    for _ in range(int(dist_cfg.get("planeRansacTrials", 60))):
        idx = rng.choice(n, 3, replace=False)
        try:
            sol = np.linalg.solve(A[idx], yn[idx])
        except np.linalg.LinAlgError:
            continue
        cnt = int(np.count_nonzero(np.abs(A @ sol - yn) <= tau))
        if cnt > best_cnt:
            best, best_cnt = sol, cnt
    if best is None:
        return None
    inl = np.abs(A @ best - yn) <= tau
    sol = best
    for _ in range(3):
        if inl.sum() < 3:
            return None
        sol = np.linalg.lstsq(A[inl], yn[inl], rcond=None)[0]
        res = np.abs(A @ sol - yn)
        thr = max(2.5 * float(np.median(res[inl])), 1e-3)
        new = res <= thr
        if np.array_equal(new, inl):
            break
        inl = new
    n_in = int(inl.sum())
    if n_in < min_cells or n_in / n < float(dist_cfg.get("planeMinInlierFraction", 0.6)):
        return None
    c, a, b = (float(v) for v in sol)
    norm = math.sqrt(1.0 + a * a + b * b)
    if c <= 0 or math.degrees(math.atan(math.hypot(a, b))) > float(dist_cfg.get("planeMaxNormalDeg", 35.0)):
        return None
    return _PlaneFit(c / norm, math.degrees(math.asin(max(-1.0, min(1.0, -b / norm)))), n_in, n_in / n)


class _PlaneAnchor:
    """One-shot plane anchor (``anchor: "plane"``, DA2 metric): scale = camera height / fitted camera height.

    Each valid plane fit gives s_t = camera_height_m / h_d. The running median is usable from
    ``initialAnchorMinFrames`` (3) valid frames and frozen at ``initialAnchorFrames`` (6); invalid frames do not
    count. ``reset()`` restarts the collection. Also keeps the median pitch and camera height (depth units)."""

    def __init__(self, dist_cfg: dict, camera_height_m: float):
        self.camera_height_m = float(camera_height_m)
        self.n_freeze = int(dist_cfg.get("initialAnchorFrames", 6))
        self.n_min = min(int(dist_cfg.get("initialAnchorMinFrames", 3)), self.n_freeze)
        self.reset()

    def reset(self) -> None:
        self.scales: list[float] = []
        self.pitches: list[float] = []
        self.heights: list[float] = []
        self.frozen = False
        self.fit: _PlaneFit | None = None

    def update(self, fit: _PlaneFit | None) -> None:
        self.fit = fit
        if self.frozen or fit is None or not fit.height_units > 0:
            return
        self.scales.append(self.camera_height_m / fit.height_units)
        self.pitches.append(fit.pitch_deg)
        self.heights.append(fit.height_units)
        self.frozen = len(self.scales) >= self.n_freeze

    def _med(self, v: list[float]) -> float | None:
        return float(np.median(v)) if len(v) >= self.n_min else None

    @property
    def value(self) -> float | None:
        return self._med(self.scales)

    @property
    def pitch_deg(self) -> float | None:
        return self._med(self.pitches)

    @property
    def height_units(self) -> float | None:
        return self._med(self.heights)


class _DepthScale:
    """Absolute level ``c`` of the anchored depth (``a_t * rel``, ground-metre units): a dimensionless
    correction, gait calibrated.

    Depth maps are z-depth (planar, along the optical axis), so walking along the axis a static witness's
    anchored depth falls at ``v / c`` with ``v = cadence * step length`` whatever its bearing (no cosine
    factor); one sample is ``v / r`` with ``r`` the closing rate of the witness's anchored depth (without
    ``c``, so no feedback). The bearing gate only limits the effect of a heading off the optical axis.
    Per frame the median over the witnesses is one sample; the estimate is the median of the samples of the
    last ``calibrationWindowSeconds`` (first one at once, later ones blended in log space with the
    ``_Scale`` time constant) and the applied level slews at <= ``scaleMaxChangePerSecond``.
    ``value`` is None until the first estimate (the caller then uses the ground scale k).
    Never uses the ground closing speeds.
    """

    def __init__(self, ego_cfg: dict, dist_cfg: dict):
        self.window_s = float(ego_cfg.get("calibrationWindowSeconds", 20.0))
        self.min_samples = int(dist_cfg.get("depthLevelMinSamples", ego_cfg.get("calibrationMinSamples", 12)))
        self.tau_min_s = float(ego_cfg.get("calibrationEmaMinSeconds", 3.0))
        self.tau_s = float(ego_cfg.get("calibrationEmaSeconds", 40.0))
        self.max_rate = float(ego_cfg.get("scaleMaxChangePerSecond", 0.25))
        self.lo, self.hi = dist_cfg.get("depthLevelRange", [0.3, 5.0])
        self.max_bearing = float(dist_cfg.get("depthWitnessMaxBearingDeg", 40.0))
        self.min_speed = float(dist_cfg.get("depthWitnessMinEgoSpeed", 0.5))
        self.freeze = False                       # "freeze" level mode: first estimate is held for the run
        self.age_s = 0.0
        self.samples: list[tuple[float, float]] = []
        self.target: float | None = None
        self.applied: float | None = None

    def sample(self, ego_speed: float | None, witnesses: list[tuple[float, float]]) -> float | None:
        """witnesses = [(bearing deg, closing rate of the anchored depth)]; the frame's level sample or None."""
        if ego_speed is None or ego_speed < self.min_speed:
            return None
        vals = [ego_speed / r for b, r in witnesses
                if r > 0 and abs(b) <= self.max_bearing]
        return float(np.median(vals)) if vals else None

    def update(self, t: float, sample: float | None, dt: float, start: float | None = None) -> None:
        """``start`` (freeze mode): the level in use before the first estimate; ``applied`` then ramps from it
        to the frozen target at the slew limit and the target never changes again."""
        if self.freeze and self.target is not None:
            sample = None                           # frozen: no further estimates
        if sample is not None and math.isfinite(sample) and sample > 0:
            self.samples.append((t, sample))
        self.samples = [x for x in self.samples if x[0] >= t - self.window_s - 1e-9]
        if len(self.samples) >= self.min_samples and not (self.freeze and self.target is not None):
            inst = min(self.hi, max(self.lo, float(np.median([x[1] for x in self.samples]))))
            if self.target is None:
                self.target = inst
                self.applied = start if (self.freeze and start is not None and start > 0) else inst
            else:
                self.age_s += max(dt, 0.0)
                tau = min(self.tau_s, max(self.tau_min_s, self.age_s))
                a = 1.0 - math.exp(-max(dt, 0.0) / tau)
                self.target = math.exp(math.log(self.target) + a * (math.log(inst) - math.log(self.target)))
        if self.target is not None and self.applied != self.target:
            lim = self.max_rate * max(dt, 0.0)
            self.applied = math.exp(
                math.log(self.applied) + max(-lim, min(lim, math.log(self.target) - math.log(self.applied))))

    @property
    def value(self) -> float | None:
        return self.applied

    @property
    def holding(self) -> bool:
        """Freeze mode and the ramp to the frozen level is done."""
        return self.freeze and self.target is not None and math.isclose(self.applied, self.target, rel_tol=1e-9)


class _CrosswalkTracker:
    """Is the user standing on a crosswalk? (v26.1.14, ``config["crosswalk"]``).

    The signal is the share of crosswalk-class cells in the surface seed box (bottom centre of the picture, under the feet), so a
    crosswalk merely seen ahead never counts and a crossing that runs along the walking direction keeps counting. In: the share
    is >= ``enterFraction`` for ``enterSeconds`` without a break, never while the user stands still. Out: <= ``exitFraction`` for
    ``exitSeconds`` without a break. ``update`` returns "enter" / "exit" on the frame that decides, else None.
    """

    def __init__(self, cfg: dict):
        self.enter_f = float(cfg["enterFraction"])
        self.enter_s = float(cfg["enterSeconds"])
        self.exit_f = float(cfg["exitFraction"])
        self.exit_s = float(cfg["exitSeconds"])
        self.inside = False
        self._since: float | None = None          # start of the current run above the enter / below the exit level

    def update(self, t: float, fraction: float, stationary: bool) -> str | None:
        if not self.inside:
            if stationary or fraction < self.enter_f:
                self._since = None
                return None
            self._since = t if self._since is None else self._since
            if t - self._since >= self.enter_s - 1e-9:
                self.inside, self._since = True, None
                return "enter"
            return None
        if fraction > self.exit_f:
            self._since = None
            return None
        self._since = t if self._since is None else self._since
        if t - self._since >= self.exit_s - 1e-9:
            self.inside, self._since = False, None
            return "exit"
        return None


def _seed_fraction(grid: np.ndarray, class_id: int | None, seed_box: list[float]) -> float:
    """Share of cells of ``class_id`` in the seed box (the box ``walking_region`` seeds from)."""
    if class_id is None:
        return 0.0
    gh, gw = grid.shape
    x0, y0, x1, y1 = seed_box
    box = grid[int(y0 * gh):max(int(math.ceil(y1 * gh)), int(y0 * gh) + 1),
               int(x0 * gw):max(int(math.ceil(x1 * gw)), int(x0 * gw) + 1)]
    return float(np.count_nonzero(box == class_id)) / max(1, box.size)


class _SurfaceTracker:
    """Surface group with strict evidence (CONTRACTS.md 15 design 4; supersedes 14.1.8).

    A change of the adopted (stable) surface needs ALL of
      * the new surface holds at least ``majority`` (70 percent) of the frames of a sliding
        ``windowSeconds`` (10 s) window (and the window spans at least ``minPersistSeconds``),
      * (kept from v26.1.6, so this is only ever stricter) it has also run without interruption for
        ``minPersistSeconds``, and
      * a curb or crosswalk edge *passed under the user* that belongs to the change: no earlier than
        ``evidenceLookbackSeconds`` (3 s) before and no later than ``evidenceLeadSeconds`` (2 s) after the new surface's
        stretch began (v26.1.11; ``note_evidence``: the driver reports it when the contact of a track that had crossed the
        lane for ``confirmFrames`` frames reached the bottom ``passUnderRows`` grid rows inside the lane and the track
        was gone within 1.5 s).
    Otherwise the previous surface is kept, silently: the region still follows the model frame by frame,
    but nothing is announced and (see the driver) the context memory is not reset. The first surface of a
    run needs only the majority and is adopted silently (``announceFirstSurface``): with nothing to compare with,
    a model that reads a sidewalk as road for the first seconds (192-200 s of the review) cannot be told from a
    real start on the road. Announced surfaces are road / rail only, see ``SpeechPolicy``.
    """

    def __init__(self, cfg: dict):
        self.window_s = float(cfg.get("windowSeconds", 10.0))
        self.majority = float(cfg.get("majority", 0.7))
        self.persist_s = float(cfg.get("minPersistSeconds", 8.0))
        self.need_evidence = bool(cfg.get("requireCrossingEvidence", True))
        self.announce_first = bool(cfg.get("announceFirstSurface", False))
        self.lookback_s = float(cfg.get("evidenceLookbackSeconds", self.window_s))
        self.lead_s = float(cfg.get("evidenceLeadSeconds", 1e9))     # v26.1.11: evidence later than this after the run began did not cause it
        self.stable: str | None = None
        self._window: list[tuple[float, str]] = []
        self._evidence: list[float] = []
        self._run: str | None = None             # the surface currently running without interruption ...
        self._run_since = 0.0                    # ... since
        self._seen: dict[str, tuple[float, float]] = {}   # group -> (since, last seen): its stretch, gaps up to 1.5 s (a flicker) bridged

    def note_evidence(self, t: float) -> None:
        self._evidence.append(t)
        self._evidence = [e for e in self._evidence if e >= t - 60.0]

    def update(self, t: float, group: str | None) -> tuple[str | None, str, bool] | None:
        """Returns (old, new, announce) when a new group is adopted (old is None for the first), else None."""
        if group is not None:
            self._window.append((t, group))
            since, last = self._seen.get(group, (t, t))
            self._seen[group] = (since if t - last <= 1.5 + 1e-9 else t, t)
            if group != self._run:
                self._run, self._run_since = group, t
        lo = t - self.window_s - 1e-9
        while self._window and self._window[0][0] < lo:
            self._window.pop(0)
        if not self._window or t - self._window[0][0] < self.persist_s - 1e-9:
            return None                         # not enough history to call anything a majority
        counts: dict[str, int] = {}
        for _, g in self._window:
            counts[g] = counts.get(g, 0) + 1
        leader = max(counts, key=lambda g: counts[g])
        if counts[leader] < self.majority * len(self._window) - 1e-9 or leader == self.stable:
            return None
        if leader != self._run or t - self._run_since < self.persist_s - 1e-9:
            return None                         # kept from v26.1.6: the new surface must also run uninterrupted for minPersistSeconds
        if self.stable is None:
            self.stable = leader
            return None, leader, self.announce_first
        began = self._seen[leader][0]            # the change began where the new surface's stretch (flickers bridged) did
        crossed = any(began - self.lookback_s - 1e-9 <= e <= min(t, began + self.lead_s) + 1e-9 for e in self._evidence)
        if self.need_evidence and not crossed:
            return None                         # a model relabel of the same pavement: keep the old surface
        old, self.stable = self.stable, leader
        self._evidence.clear()
        return old, leader, True


class _WorldMemory:
    """Object permanence by dead reckoning (CONTRACTS.md 15 design 1).

    The user's ground position is integrated from the calibrated ego speed (cadence x step length, the
    witness speed as a fallback, the last speed held ``speedHoldSeconds``) along the camera heading of the
    motion track (x east / y north in an arbitrary frame; heading 0 = the initial direction, positive =
    right turn). Every announced item is stored as ``(label family, world x, y)``. A candidate of the same
    family within ``matchRadiusM`` + ``matchRangeFraction`` x its distance (per-family override in
    ``radiusOverrides``) of a stored object is that object. Objects are forgotten when behind the user
    (``ahead < behindM``) or farther than ``maxRangeM``.

    Inactive (``active`` False) without motion data: the policy then keeps the track / label rules of
    v26.1.6. Dead reckoning drifts (heading integration, step length), which is why the match radius grows
    with the item's distance and why a matched track keeps refreshing its object's position, so a drift
    only matters between two sightings separated by a gap.
    """

    def __init__(self, cfg: dict, enabled: bool = True):
        self.enabled = enabled and bool(cfg.get("enabled", True))
        self.radius = float(cfg.get("matchRadiusM", 2.5))
        self.range_frac = float(cfg.get("matchRangeFraction", 0.10))
        self.max_range = float(cfg.get("maxRangeM", 30.0))
        self.behind = float(cfg.get("behindM", -1.0))
        self.hold_s = float(cfg.get("speedHoldSeconds", 5.0))
        self.seen_hold_s = float(cfg.get("seenHoldSeconds", 1.0))
        self.takeover_s = float(cfg.get("moverTakeoverSeconds", 1.0))
        self.adopt_s = float(cfg.get("ownerAdoptSeconds", 3.0))
        self.overrides = dict(cfg.get("radiusOverrides", {}))
        self.x = self.y = 0.0
        self.theta: float | None = None          # heading, degrees
        self.speed: float | None = None
        self.speed_t = -math.inf
        self.entries: dict[int, dict] = {}
        self._next = 1

    @property
    def active(self) -> bool:
        return self.enabled and self.theta is not None

    def advance(self, t: float, dt: float, speed: float | None, heading_deg: float | None) -> None:
        if heading_deg is None:
            self.theta = None
            return
        if speed is not None:
            self.speed, self.speed_t = speed, t
        v = self.speed if (self.speed is not None and t - self.speed_t <= self.hold_s + 1e-9) else 0.0
        mid = heading_deg if self.theta is None else 0.5 * (self.theta + heading_deg)
        self.x += v * dt * math.sin(math.radians(mid))
        self.y += v * dt * math.cos(math.radians(mid))
        self.theta = heading_deg
        fx, fy = math.sin(math.radians(self.theta)), math.cos(math.radians(self.theta))
        for eid in list(self.entries):
            e = self.entries[eid]
            dx, dy = e["x"] - self.x, e["y"] - self.y
            if t - e["seen"] <= self.seen_hold_s:
                continue                         # in view right now: the camera outranks the dead reckoning
            if dx * fx + dy * fy < self.behind or math.hypot(dx, dy) > self.max_range:
                del self.entries[eid]            # passed (behind us) or too far to matter

    def locate(self, it: _Item) -> tuple[float, float]:
        th = math.radians(self.theta or 0.0)
        return (self.x + math.sin(th) * it.distance_m + math.cos(th) * it.lateral_m,
                self.y + math.cos(th) * it.distance_m - math.sin(th) * it.lateral_m)

    def match(self, it: _Item, t: float = 0.0) -> int | None:
        best, best_d = None, math.inf
        mover = it.people or it.moving is True
        fam = it.family or it.label
        reach = self.overrides.get(fam, self.radius) + self.range_frac * it.distance_m
        for eid, e in self.entries.items():
            if e["family"] != fam:
                continue
            if mover and t - e["fresh"] > self.takeover_s:
                continue                         # a person walks on: only a hand-off within a second is the same person
            d = math.hypot(e["x"] - it.wx, e["y"] - it.wy)
            if d <= reach and d < best_d:
                best, best_d = eid, d
        return best

    def refresh(self, eid: int, it: _Item, t: float) -> None:
        e = self.entries[eid]
        e["x"], e["y"], e["seen"], e["fresh"], e["owner"] = it.wx, it.wy, t, t, it.track_id

    def add(self, it: _Item, t: float, named: bool = True) -> int:
        eid, self._next = self._next, self._next + 1
        self.entries[eid] = {"family": it.family or it.label, "x": it.wx, "y": it.wy, "named": named, "approach": False, "danger": False,
                                "seen": t, "fresh": t, "owner": it.track_id}
        return eid

    def link(self, items: list[_Item], tracks: dict[int, _Track], t: float) -> None:
        """Locate every item and connect it to a remembered object (via its track, else by position)."""
        for it in items:
            it.mem_id = None
            if not self.active:
                continue
            it.wx, it.wy = self.locate(it)
            tr = tracks[it.track_id]
            if tr.mem_id is None or tr.mem_id not in self.entries:
                tr.mem_id = self.match(it, t)
                tr.linked_t = t
            if tr.mem_id is not None:
                it.mem_id = tr.mem_id
                it.mem_named = self.entries[tr.mem_id]["named"]
                it.mem_approach = self.entries[tr.mem_id]["approach"]
                it.mem_danger = self.entries[tr.mem_id]["danger"]
                e = self.entries[tr.mem_id]
                if e["owner"] != it.track_id and t - tr.linked_t >= self.adopt_s:
                    e["owner"] = it.track_id                 # a track that has shown it for seconds is as good an owner as the first one
                if e["owner"] == it.track_id:
                    e["seen"] = t                            # its own track still sees it: in view, however the dead reckoning drifts
                # a standing object stays where it was first put (a refresh would let a long curb or wall drag its
                # entry along as we walk, so that it is never "passed"); a mover is followed by whichever track
                # currently shows it, so that a fragmented person is still the same person
                if (it.people or it.moving is True) and (e["owner"] == it.track_id or t - e["fresh"] <= self.takeover_s):
                    self.refresh(tr.mem_id, it, t)


# --------------------------------------------------------------------------
# Steps and roles
# --------------------------------------------------------------------------

def steps_to(distance_m: float, step_length_m: float) -> float:
    """Steps until we reach the item: ``distance / step length`` (v26.1.6).

    The distance is gait calibrated (see ``_Scale``) and the step length is the prior or the
    per-recording value, so the number is stable: it no longer divides by a noisy instantaneous ego
    speed (v26.1.5 steps swung 25.9 -> 12.7 in 0.2 s).
    """
    return distance_m / step_length_m


def _speed_witness(it: _Item) -> bool:
    """Can this item tell us our own speed? Only something that stands on the ground at a point:
    a pole, sign or lamp (tall and thin). The contact row of a wall, hedge or building is where the
    segmentation happens to end, so its "closing" is mostly zero or random and would drag the median."""
    return it.closing_raw is not None and _pole_like(it)


def _pole_like(it: _Item) -> bool:
    """Static, tall and thin, not clipped, not running along the path (also the depth-scale witnesses)."""
    if it.group != "static" or it.clipped or it.along_path or it.lane_part:
        return False
    w, h = it.bbox[2] - it.bbox[0], it.bbox[3] - it.bbox[1]
    return h >= POINT_ASPECT * w


LANE_PART_ID_BASE = 1_000_000   # first track id of the lane parts of walls / buildings (v26.1.16 follow-up)
POINT_ASPECT = 3.0   # bbox height / width (normalised units, ~1.7 in pixels) of a pole-like item


def _is_static_like(it: _Item) -> bool:
    """Static things, and vehicles of unknown or measured-stationary motion ("unknown movers count as
    static": they never become "approaching"). People/riders/animals are movers, never
    "stationary" (v26.1.6). Their motion is hard to
    measure from a bobbing chest camera (people waiting at a crossing read as "stationary" at 48 s of the
    review footage while they walked on) and they are the ones that step into the path, so their measured
    motion only decides "approaching" / "receding"."""
    if it.group == "static":
        return True
    if it.group == "moving":
        return False if it.people else it.moving is not True
    return False


def _not_approaching(it: _Item, ego_speed_raw: float | None) -> bool:
    """A ground object we walk towards closes at our speed. One whose contact row stays put while we
    move is the end of a line running along the path (a median cut into pieces), not an obstacle.
    Both speeds are raw (uncalibrated) model metres per second."""
    return (it.closing_raw is not None and ego_speed_raw is not None and ego_speed_raw >= 0.5
            and it.closing_raw < 0.3 * ego_speed_raw)


def _sideways_mps(it: _Item, roles: dict) -> float:
    """The item's sideways velocity if it is clearly there, else 0 (v26.1.11).

    The lateral-position derivative is a weak measurement here: on review 4 a STANDING pole or building reads
    |v| 0.5 m/s median and 1.4-2.4 m/s at the 90th percentile (contact row and depth noise times the bearing, the chest
    sway), turn-corrected or not. Only a velocity above ``lateralVelDeadbandMps`` (2) counts, so a vehicle crossing the
    crosswalk (5-8 m/s) is seen as the mover it is and a person walking across (1-1.5 m/s) is not guessed at: for them
    the lane rule on the current lateral position applies, as before."""
    v = it.lat_vel
    if v is None or abs(v) < roles.get("lateralVelDeadbandMps", 2.0):
        return 0.0
    cap = roles.get("lateralVelMaxMps", 8.0)
    return max(-cap, min(cap, v))


def _robust_speed(hist: list[tuple[float, float]], t: float, speed: float, window_s: float) -> float:
    """Median of our cadence-based speed over the last ``window_s`` seconds (``hist`` is updated in place), the speed the motion
    states are judged against (v26.1.13, review 6, 374.0 s: a momentary spike of the ego speed (2.07 against 1.1 m/s two seconds
    later) turned a closing person into a "standing" one). ``window_s`` <= 0: the speed itself."""
    hist.append((t, speed))
    hist[:] = [h for h in hist if h[0] >= t - window_s - 1e-9] or hist[-1:]
    return float(np.median([h[1] for h in hist]))


def _motion_state(tr: "_Track", t: float, along: float, side: float, cross: float | None, roles: dict, vehicle: bool = False) -> str | None:
    """Motion state of a mover from its smoothed own speed along the line of sight (v26.1.12, review 5), with hysteresis.

    * ``"side"``: clearly moving sideways (``_sideways_mps``).
    * ``"approach"`` / ``"recede"``: ``along`` >= ``approachingMps`` (0.4) towards / away; kept down to ``motionLeaveMps`` (0.3).
    * ``"still"``: ``|along|`` < ``standingMps`` (0.3) held for ``standingHoldSeconds`` (1 s) without a break AND no sideways
      motion (``|cross|`` < ``standingMaxCrossMps``); kept while ``|along|`` < ``approachingMps`` and no sideways motion.
    * ``None``: anything else: in between, too short a measurement, or a possible sideways motion. The caller says the plain
      phrase: a wrong state is worse than none (review 5: a person walking left was "standing", a person walking away
      at 0.6 m/s was "standing")."""
    prev = tr.mstate
    enter, leave = roles.get("approachingMps", 0.4), roles.get("motionLeaveMps", 0.3)
    if vehicle and "vehicleApproachingMps" in roles:
        # v26.1.16 (review 8, 52.2 s: a parked car was "approaching"): the along speed of a car is measured from the contact row of a big,
        # fragmenting component and reads 1-3 m/s off for a parked one in a row of cars (1.0 for the one called approaching, 3.0 for its
        # neighbour); a car that really approaches closes at 4+ m/s. Cyclists keep the person levels: their early warning is wanted
        enter = float(roles["vehicleApproachingMps"])
        leave = 0.7 * enter
    still_max, hold = roles.get("standingMps", 0.3), roles.get("standingHoldSeconds", 1.0)
    cross_max = roles.get("standingMaxCrossMps", 0.6)
    sideways = cross is not None and abs(cross) >= cross_max
    if side != 0.0:
        tr.still_t0 = None
        return "side"
    if along >= enter or (prev == "approach" and along >= leave):
        tr.still_t0 = None
        return "approach"
    if along <= -enter or (prev == "recede" and along <= -leave):
        tr.still_t0 = None
        return "recede"
    if sideways or abs(along) >= (enter if prev == "still" else still_max):
        tr.still_t0 = None
        return None
    if tr.still_t0 is None:
        tr.still_t0 = t
    return "still" if (prev == "still" or t - tr.still_t0 >= hold - 1e-9) else None


def _course(it: _Item, roles: dict) -> tuple[float, float] | None:
    """(time to meet, lateral position at the meeting) of a measured mover that is closing, else None (v26.1.11, review 4).

    ``closing`` is the rate at which the gap shrinks (it already contains our own speed), so we meet at
    ``T = distance / closing``; by then the mover has moved sideways by ``lat_vel * T``. Not closing at
    ``courseMinClosingMps`` (a mover that keeps its distance or walks away) has no meeting. An unmeasured sideways velocity
    counts as 0 (see ``_sideways_mps``)."""
    c = it.closing
    if c is None or c < roles.get("courseMinClosingMps", 0.2):
        return None
    t_meet = it.distance_m / c
    return t_meet, it.lateral_m + _sideways_mps(it, roles) * t_meet


def _on_collision_course(it: _Item, roles: dict) -> bool:
    """Will this measured mover be in our way when we get there? (v26.1.11; v26.1.13: ``beepLateralM`` is the body width)

    Collision course iff the lateral position at the meeting is within ``beepLateralM`` (0.9 m: lane half-width 0.6 plus the
    body) and the meeting is not further off than ``courseMaxSeconds`` (a far, slow closing would extrapolate a noisy
    velocity over a long time)."""
    m = _course(it, roles)
    return m is not None and m[0] <= roles.get("courseMaxSeconds", 8.0) and abs(m[1]) <= roles.get("beepLateralM", 0.9)


def _fast_warning(it: _Item, roles: dict) -> bool:
    """A rider / vehicle measured approaching on or near our path is announced as early as possible (v26.1.13, review 6, 191.5 and
    445.3 s: "warn as soon as possible, the 10-step rule does not apply to cyclists or vehicles on or close to a collision course").

    No step limit: it is about to reach us within ``fastWarnSeconds`` (distance / closing) and be inside the walking zone
    (``movingLaneHalfWidthM``) at that moment, up to ``fastWarnMaxM``. A cyclist passing at arm's length (1.9 m) counts as
    near; whether it also beeps is ``_on_collision_course``."""
    m = _course(it, roles)
    return (m is not None and not it.receding and it.distance_m <= roles.get("fastWarnMaxM", 30.0)
            and m[0] <= roles.get("fastWarnSeconds", 6.0) and abs(m[1]) <= roles.get("movingLaneHalfWidthM", 3.0))


def _assign_role(it: _Item, span: tuple[float, float] | None, roles: dict, lane_half_m: float,
                 step_length_m: float, stationary: bool = False) -> None:
    danger_steps, final_steps = roles["dangerSteps"], roles["finalSteps"]
    it.role, it.urgency, it.collision, it.summary_ok, it.proximity = "none", "none", False, False, False
    big_enough = it.area_m2 >= roles.get("minObstacleAreaM2", 0.0)   # a 15 px blip 4 m away is segmentation noise
    if _is_static_like(it):
        # v26.1.11 (review 4, 39.0 s): a vehicle whose motion is not measured yet (a new track: a moving car re-detected in
        # fragments has no closing speed for ~0.75 s) is no static danger while we CAN measure motion; it waits
        unmeasured_mover = it.group == "moving" and it.moving is None and it.ego_known
        in_lane = it.map_cells > 0 if it.map_judged else (it.lane_hit and not it.along_path) or it.map_cells > 0
        if big_enough and in_lane and it.steps <= danger_steps and not unmeasured_mover:
            it.role, it.collision = "danger", True
        elif (it.touches and it.distance_m <= roles["contextMaxDistanceM"]
              and it.area_frac >= roles.get("contextMinAreaFraction", 0.0)
              and it.distance_m <= roles.get("contextMaxSteps", 1e9) * step_length_m):
            # v26.1.6: only what is near; things far to the side stay silent, except in the very first
            # scene summary of a run, which names the whole view (the user ticked "building at 2" there)
            # v26.1.13 (review 6, 132.3 / 179.5 s: "not on a collision course"): lateral limit lowered from 3.0 to 2.5 m;
            # right under us (``contextNearSteps``) the older 3.0 m still counts (the 59.2 s obstacle at 2.9 m, 2.6 steps)
            lat_ok = (abs(it.lateral_m) <= roles.get("contextMaxLateralM", 1e9)
                      or (it.steps <= roles.get("contextNearSteps", 0.0) and abs(it.lateral_m) <= roles.get("contextNearLateralM", 0.0)))
            if lat_ok:
                it.role = "context"
            else:
                it.summary_ok = True
    elif it.group == "moving":
        in_span = (span is not None and span[0] <= it.contact_y <= span[1] + 1e-9) or it.coasting      # a predicted mover has no image row
        lat = abs(it.lateral_m)
        if it.people:
            in_span = in_span or span is None                  # on a crosswalk there is no surface seed, hence no region
        # (as before: only what is near the path NOW; a car crossing in the distance has cleared it by the time we get there)
        now_reach = roles.get("movingLaneHalfWidthM", lane_half_m + 1.0) if it.people else lane_half_m + 1.0
        if it.fast and it.moving is True and in_span and big_enough and lat <= now_reach and _fast_warning(it, roles):
            # v26.1.13 (review 6, 191.5 / 445.3 s): a rider / vehicle approaching on or near the path is announced as early as
            # possible, with no step limit; it beeps only on a real collision course
            it.role, it.collision = "danger", _on_collision_course(it, roles)
        elif it.people:
            # v26.1.13 (review 6): people are spoken once at ``peopleSpeakMinSteps``..``movingDangerSteps`` (5-10 steps), whatever
            # their direction, inside the people zone (``peopleSpeakLateralM``), with the distance; under 5 steps they only
            # beep, and only on a real collision course: |lateral| (standing / unknown) or the predicted |lateral| at the
            # meeting (moving) within ``beepLateralM``. Unknown motion or a measured approach at arm's length no longer beeps.
            if it.moving is True:
                course = _on_collision_course(it, roles) and not it.receding
            else:
                course = lat <= roles.get("beepLateralM", lane_half_m)
            near_steps = it.steps < roles.get("peopleSpeakMinSteps", 0.0)
            if big_enough and in_span and it.steps <= roles.get("movingDangerSteps", danger_steps):
                if not near_steps and lat <= roles.get("peopleSpeakLateralM", lane_half_m):
                    it.role, it.collision = "danger", course
                elif near_steps and course:
                    it.role, it.collision, it.speak = "danger", True, False
            # v26.1.13 follow-up (the user chose "a softer sound for an approaching person nearby"): a person / animal measured
            # approaching, within ``proximitySteps`` and ``proximityLateralM``, not on a collision course: the soft proximity
            # sound. Not a role (speech and context are untouched); riders and vehicles are spoken early and beep on a course.
            if (not it.fast and big_enough and in_span and it.moving is True and it.approaching and not it.receding and not course
                    and it.steps <= roles.get("proximitySteps", 0.0) and lat <= roles.get("proximityLateralM", 0.0)):
                it.proximity = True
    elif it.group == "feature":
        if it.landmark:
            # a landmark (crosswalk) anywhere in or touching the walking region, once, with direction and steps
            if it.touches and not it.clipped and it.steps <= roles.get("landmarkSteps", roles["featureSteps"]):
                it.role = "feature"
        # a feature must cross the lane; a curb or median running along the path is boundary.
        # One already under our feet (touching the bottom edge) is not "ahead".
        elif (it.lane_hit and not it.along_path and not it.clipped
                and it.lane_cover >= roles["featureMinLaneCover"] and it.steps <= roles["featureSteps"]):
            it.role = "feature"
    if it.role == "danger":
        # the final call is for a collision course; a person merely beside the path is a plain danger
        it.urgency = "final" if (it.collision and it.steps <= final_steps) else "danger"


# --------------------------------------------------------------------------
# Movers that left the image (v26.2.2)
# --------------------------------------------------------------------------

class _Coast:
    """A mover (person, rider, animal, vehicle) that disappears (out of frame, occluded, a segmentation dropout) keeps its last world
    velocity for a bounded time: its position is predicted linearly in world coordinates (dead-reckoned pose) and it stays an item
    of the collision logic (collision course, beeps, proximity) but is never spoken (``speak`` False). It stops when the object is matched
    again (the same track, or a new item of its class near the prediction), when it is passed, out of range or the time is up.

    The velocity is the least-squares line through the last ``histSeconds`` of its measured world positions (at least ``minPoints`` over
    ``minSpanSeconds``); a mover without such a measurement is not coasted."""

    def __init__(self, cfg: dict):
        self.on = bool(cfg.get("enabled", False))
        self.seconds = float(cfg.get("seconds", 2.0))
        self.vehicle_seconds = float(cfg.get("vehicleSeconds", self.seconds))
        self.hist_s = float(cfg.get("histSeconds", 1.0))
        self.min_points = int(cfg.get("minPoints", 3))
        self.min_span = float(cfg.get("minSpanSeconds", 0.5))
        self.max_speed = float(cfg.get("maxSpeedMps", 15.0))
        self.max_range = float(cfg.get("maxRangeM", 30.0))
        self.rematch = float(cfg.get("rematchRadiusM", 2.0))
        self.hist: dict[int, list[tuple[float, float, float]]] = {}
        self.last: dict[int, tuple[_Item, float]] = {}          # track -> (last measured item, its time)
        self.active: dict[int, dict] = {}                        # track -> the running coasting episode
        self.episodes: list[dict] = []

    def observe(self, it: _Item, t: float, world: "_WorldMemory") -> None:
        if not self.on or it.group != "moving" or it.coasting or it.clipped or world.theta is None:
            return
        th = math.radians(world.theta)
        s_, c_ = math.sin(th), math.cos(th)
        h = self.hist.setdefault(it.track_id, [])
        h.append((t, world.x + s_ * it.distance_m + c_ * it.lateral_m, world.y + c_ * it.distance_m - s_ * it.lateral_m))
        self.hist[it.track_id] = [p for p in h if p[0] >= t - self.hist_s - 1e-9]
        self.last[it.track_id] = (it, t)

    def _velocity(self, tid: int):
        h = self.hist.get(tid, [])
        if len(h) < self.min_points or h[-1][0] - h[0][0] < self.min_span - 1e-9:
            return None
        a = np.asarray(h)
        tt = a[:, 0] - a[:, 0].mean()
        den = float((tt * tt).sum())
        if den <= 1e-9:
            return None
        vx, vy = float((tt * (a[:, 1] - a[:, 1].mean())).sum() / den), float((tt * (a[:, 2] - a[:, 2].mean())).sum() / den)
        if math.hypot(vx, vy) > self.max_speed:
            return None
        return vx, vy

    def _end(self, tid: int, t: float, why: str) -> None:
        ep = self.active.pop(tid, None)
        if ep is not None:
            ep["t1"], ep["end"] = round(t, 2), why
            self.episodes.append(ep)

    def items(self, t: float, seen: dict[int, _Item], world: "_WorldMemory", tracks: dict, step_len: float, blocked=None) -> list[_Item]:
        """The coasting items of this frame (``seen``: the real items by track id)."""
        out: list[_Item] = []
        if not self.on or world.theta is None:
            return out
        th = math.radians(world.theta)
        s_, c_ = math.sin(th), math.cos(th)
        for tid in list(self.last):
            it0, t_last = self.last[tid]
            if tid in seen:
                self._end(tid, t, "rematch")
                continue
            if tid not in tracks:
                self._end(tid, t, "lost")
                self.last.pop(tid, None); self.hist.pop(tid, None)
                continue
            v = self._velocity(tid)
            horizon_s = self.vehicle_seconds if it0.class_name == "vehicle" else self.seconds
            if v is None or t - t_last > horizon_s + 1e-9 or t - t_last <= 0:
                if t - t_last > horizon_s + 1e-9:
                    self._end(tid, t, "expired")
                    self.last.pop(tid, None); self.hist.pop(tid, None)
                continue
            _, wx0, wy0 = self.hist[tid][-1]
            wx, wy = wx0 + v[0] * (t - self.hist[tid][-1][0]), wy0 + v[1] * (t - self.hist[tid][-1][0])
            dx, dy = wx - world.x, wy - world.y
            fwd, right = dx * s_ + dy * c_, dx * c_ - dy * s_
            if fwd <= 0.0:
                self._end(tid, t, "passed"); self.last.pop(tid, None); self.hist.pop(tid, None)
                continue
            rng = math.hypot(fwd, right)
            if blocked is not None and blocked(fwd, right):
                self._end(tid, t, "solid"); self.last.pop(tid, None); self.hist.pop(tid, None)
                continue
            if rng > self.max_range:
                self._end(tid, t, "range"); self.last.pop(tid, None); self.hist.pop(tid, None)
                continue
            if any(o.class_name == it0.class_name and not o.coasting
                   and math.hypot(o.distance_m - fwd, o.lateral_m - right) <= self.rematch + 0.1 * rng for o in seen.values()):
                self._end(tid, t, "rematch")                 # the same object came back under another track
                self.last.pop(tid, None); self.hist.pop(tid, None)
                continue
            ev = (world.speed or 0.0) if world.speed is not None and t - world.speed_t <= world.hold_s + 1e-9 else 0.0
            vrel = (v[0] - ev * s_, v[1] - ev * c_)               # relative to us, world axes
            closing = -((dx * vrel[0] + dy * vrel[1]) / max(rng, 1e-6))
            bearing = math.degrees(math.atan2(right, fwd))
            g = replace(it0, coasting=True, shape=None, clipped=True, speak=False, distance_m=fwd, lateral_m=right, bearing=bearing,
                        clock=clock_from_bearing(bearing), clock_q=clock_quarter(bearing), clock_text=clock_text(clock_quarter(bearing)),
                        pan=_pan_from_bearing(bearing), closing=closing, closing_raw=closing, map_cells=0, map_world=None, image_dl=None)
            if tid not in self.active:
                self.active[tid] = {"track": tid, "class": it0.class_name, "t0": round(t, 2), "steps0": round(steps_to(fwd, step_len), 1),
                                    "speedMps": round(math.hypot(*v), 2), "moving": it0.moving}
            tr = tracks[tid]
            tr.last_t, tr.last_distance, tr.last_lateral = t, fwd, right
            tr.present_run += 1
            g.present_run = tr.present_run
            out.append(g)
        return out


# --------------------------------------------------------------------------
# Speech policy
# --------------------------------------------------------------------------

class SpeechPolicy:
    """At most one phrase per frame; see the module docstring ("Less is more").

    Priority: final > danger > feature > surface > context. Only the highest
    priority class that has candidates is considered in a frame, so a danger
    that waits for the global gap is never overtaken by lower priorities.
    """

    LABEL_COOLDOWN_S = 5.0                    # same label again (a fragmented track) stays quiet this long

    def __init__(self, config: dict):
        self.cfg = config["speech"]
        self.forget_s = config["contextMemory"]["forgetAfterSeconds"]
        self.final_steps = config["roles"]["finalSteps"]
        self.confirm = int(config["roles"].get("confirmFrames", 1))
        self.max_items = int(self.cfg.get("contextMaxItems", 1))
        self.max_entries = int(self.cfg.get("maxEntries", 3))
        self.thin_rearm_s = float(self.cfg.get("thinRearmSeconds", 8.0))
        self.feature_gap_s = float(self.cfg.get("featureLabelGapSeconds", 6.0))
        self.feature_new_steps = float(self.cfg.get("featureNewCrossingSteps", 5.0))
        self.travel_steps = 0.0                                 # our own walking, in steps (set by the driver)
        self.landmarks = frozenset(config["classes"].get("landmark", []))
        self.thin_armed = True
        self.last_thin_seen = -math.inf
        self.thin_range = (float(config["roles"].get("thinNoticeSteps", 15)),
                           float(config["roles"].get("thinNoticeLateralM", 2.5)))
        self.danger_first: dict[int, float] = {}                # track id -> when it first was a confirmed danger
        self.motion_wait_s = float(self.cfg.get("peopleMotionWaitSeconds", 1.5))
        self.motion_wait_steps = float(self.cfg.get("peopleMotionWaitSteps", 6))
        self.last_t: float | None = None
        self.last_prio_t: float | None = None
        self.last_danger_t: float | None = None                 # last danger / final phrase (v26.1.15)
        self.last_beep_t: float | None = None                   # last frame with a collision beep driver (v26.1.16, set by the driver)
        self.after_danger_s = float(config["roles"].get("contextAfterDangerSeconds", 0.0))
        self.memory: dict[str, float] = {}                      # context label (family) -> last seen
        self.pending_since: dict[str, float] = {}               # context waiting for the gap
        self.feature_label_t: dict[str, tuple[float, float]] = {}   # label -> (time, position in steps along our walk)
        self.danger_label_t: dict[str, float] = {}
        self.surface_pending: tuple[str, str] | None = None   # (group, label) waiting to be spoken
        self.context_speak = set(config.get("contextSpeak", []))
        # start summary: the first context phrase of a run (and after a path change) needs only
        # ``confirmFrames`` frames, no track age and no adopted surface, so it comes within ~1 s
        self.summary = True
        self.first_summary = True                # the run's first summary: not limited to near-lateral items
        self.summary_since: float | None = None
        self.world: _WorldMemory | None = None   # object permanence (v26.1.7); set by the driver, None = track/label rules
        self.stationary = False                  # the user stands still (v26.1.11); set by the driver each frame

    # -- memory ----------------------------------------------------------
    def clear_context(self, t: float | None = None) -> None:
        """Forget what was said (a turn): the next context phrase is a fresh summary of the new view."""
        self.memory.clear()
        self.pending_since.clear()
        self.thin_armed = True                   # a turn: a new view, "beware poles" may be said again
        self.first_summary = False
        self.summary, self.summary_since = True, t

    @staticmethod
    def _key(it: _Item) -> str:
        """Memory key: the item's label family ("vehicle" and "parked car" are one thing), not its side."""
        return it.family or it.label

    def _known(self, key: str) -> bool:
        return key in self.memory

    @property
    def _mem(self) -> bool:
        """World memory is in charge (motion data available)."""
        return self.world is not None and self.world.active

    def _seen_before(self, it: _Item, named: bool = True, approach: bool = False, danger: bool = False) -> bool:
        """The item is a remembered object (only with world memory). ``named``: it must have been announced by
        name, not merely covered by a "poles" notice that was never spoken for it. ``approach``: an object that was
        named but not as "approaching" is news again once it approaches (a person who was standing, or walking away).
        ``danger`` (v26.1.16, review 8, 10.9 s: collision and danger supersede notify-once): the question is for a danger / final
        phrase, which only an earlier danger / final phrase for the same object mutes; having been named as context or feature does not."""
        if danger:
            return self._mem and it.mem_id is not None and it.mem_danger and (it.mem_approach or not approach)
        return (self._mem and it.mem_id is not None and (it.mem_named or not named)
                and (it.mem_approach or not approach))

    def _register(self, t: float, it: _Item, tracks: dict[int, _Track], named: bool = True, approach: bool = False,
                  danger: bool = False) -> None:
        """Remember an announced object so that neither its fragments nor a later view of it are announced again."""
        if not self._mem:
            return
        if it.mem_id is None:
            it.mem_id = self.world.add(it, t, named)
            tracks[it.track_id].mem_id = it.mem_id
        e = self.world.entries[it.mem_id]
        e["named"] = e["named"] or named
        e["approach"] = e["approach"] or approach
        e["danger"] = e["danger"] or danger
        it.mem_named, it.mem_approach, it.mem_danger = e["named"], e["approach"], e["danger"]

    def observe_context(self, t: float, keys: set[str]) -> None:
        """Refresh memory for labels seen now; forget labels unseen for forgetAfterSeconds."""
        for k in keys:
            if k in self.memory:
                self.memory[k] = t
        for k in [k for k, seen in self.memory.items() if t - seen > self.forget_s]:
            del self.memory[k]

    def surface_adopted(self, old: str | None, new: str, surfaces: dict, announce: bool = True) -> None:
        """A debounced surface change. Only road/rail matter: those are where the user must be told
        (starting on one, or moving into or out of one). Sidewalk <-> bike lane relabels stay silent, and
        so does any change the tracker could not back with crossing evidence (``announce`` False)."""
        if not announce:
            return
        announce_groups = set(surfaces.get("announceGroups", []))
        if new in announce_groups or (old is not None and old in announce_groups):
            self.surface_pending = (new, surfaces["groups"][new]["label"])

    # -- phrases ---------------------------------------------------------
    @staticmethod
    def _n(steps: float) -> int:
        return max(1, int(round(steps)))

    @staticmethod
    def _join_clocks(items) -> str:
        """Distinct clock texts of ``items``, left to right (by quarter index): "1", "12:15 and 1:30"."""
        cs = [txt for _, txt in sorted({(i.clock_q, i.clock_text) for i in items})]
        return cs[0] if len(cs) == 1 else ", ".join(cs[:-1]) + " and " + cs[-1]

    def _steps_txt(self, it: _Item) -> str | None:
        """Steps as spoken ("1 step", "8"); None when the distance is unknown."""
        if it.steps is None or not math.isfinite(it.steps):
            return None
        n = self._n(it.steps)
        return "1 step" if n == 1 else str(n)

    def _fmt(self, template: str, **kw) -> str:
        """Format a template; without steps the " in {steps}" part is left out (only for an unknown distance)."""
        tpl = self.cfg["templates"][template]
        if kw.get("steps") is None:
            tpl = tpl.replace(" in {steps}", "")
        return tpl.format(**kw)

    def _text(self, template: str, it: _Item | None = None, label: str = "") -> str:
        if it is None:
            return self.cfg["templates"][template].format(label=label)
        if template == "approach" and it.fast:
            return self._fmt("approachFast", label=it.label, clock=it.clock_text, steps=None)
        return self._fmt(template, label=it.label, clock=it.clock_text, steps=self._steps_txt(it))

    @staticmethod
    def _plural(label: str) -> str:
        return label if label.endswith("s") else label + "s"

    STATE_WORDS = {"standing": "standing", "stopped": "stopped", "receding": "moving away", "approach": "approaching"}

    @staticmethod
    def _kind(it: _Item, base: str) -> str:
        """Phrase template of a danger/final item (v26.1.11, review 4: "need to know if static, approaching or moving away").

        A mover measured approaching is "approaching" (v26.1.13: a person with the distance, a rider / vehicle without it: at
        their speed the number means nothing), a person walking away is "moving away", a person (rider: "stopped") measured
        standing is "standing". Anything whose motion is not measured keeps ``base`` ("{label} at {clock} in {steps}")."""
        approach = it.moving is True and not it.receding and (it.approaching or (it.fast and it.role in ("danger", "final")))
        if approach and (it.ego_settled or it.own_fast):
            return "approach"           # v26.1.16: a rider / vehicle on an unsettled ego speed only if it closes faster than we could walk
        if not it.ego_settled:          # v26.1.15 (review 7): a ramping ego speed gives wrong states; the plain phrase, now
            return base
        if it.people and it.moving is True and it.receding:
            return "receding"
        if it.people and it.moving is False:
            return "stopped" if it.class_name == "rider" else "standing"
        return base

    def _entry(self, template: str, group: list[_Item]) -> str:
        """One phrase entry for same-label items: "pole at 12 in 6", merged "person at 1 and 2 in 4", "poles at 11 and 1 in 8".
        The steps are those of the nearest item; a rider / vehicle "approaching" has none (``approachFast``)."""
        near = min(group, key=lambda i: i.steps if i.steps is not None and math.isfinite(i.steps) else math.inf)
        clocks = {i.clock_q for i in group}
        steps = self._steps_txt(near)
        if template in self.STATE_WORDS:
            if template == "approach" and near.fast:
                return self._fmt("approachFast", label=near.label, clock=self._join_clocks(group), steps=None)
            if len(clocks) == 1 or template in ("approach", "receding"):
                return self._fmt(template, label=near.label, clock=self._join_clocks(group), steps=steps)
            return self._fmt("multi", label=f"{near.label} {self.STATE_WORDS[template]}", clocks=self._join_clocks(group), steps=steps)
        if template == "thin":
            label = self._plural(near.label) if len(group) > 1 else near.label
            return self._fmt("thinNotice", label=label, clocks=self._join_clocks(group), steps=steps)
        if len(clocks) == 1:
            return self._text(template, near)
        return self._fmt("multi", label=near.label, clocks=self._join_clocks(group), steps=steps)

    def _feature_allowed(self, t: float, it: _Item) -> bool:
        """The same label is not repeated within featureLabelGapSeconds unless it is a different crossing: its
        position along our walk (calibrated steps ahead plus steps walked) differs by >= featureNewCrossingSteps.
        Fragments of one curb re-tracked under new ids sit at the same position and stay quiet."""
        last = self.feature_label_t.get(it.label)
        over = self.cfg.get("featureLabelOverrides", {}).get(it.class_name, {})
        if last is None or t - last[0] >= over.get("gapSeconds", self.feature_gap_s):
            return True
        return abs(self.travel_steps + it.steps - last[1]) >= over.get("newCrossingSteps", self.feature_new_steps)

    def _motion_pending(self, t: float, it: _Item, tracks: dict[int, _Track]) -> bool:
        """A person whose motion is not measured yet may "approach": wait a moment (the closing speed needs
        ~0.75 s of history) so that the phrase can say "approaching" - unless they are already close."""
        return (it.people and it.moving is None and it.ego_known and it.ego_settled and it.steps > self.motion_wait_steps
                and t - self.danger_first.get(it.track_id, t) < self.motion_wait_s)

    def _danger_recent(self, t: float) -> bool:
        """A danger / final phrase or a collision beep within ``contextAfterDangerSeconds`` (v26.1.16, review 8, 107.0 s: "in the middle
        of multiple danger notifications, no need for context")."""
        last = max((x for x in (self.last_danger_t, self.last_beep_t) if x is not None), default=None)
        return last is not None and t - last < self.after_danger_s - 1e-9

    def _gap_ok(self, t: float, priority: bool = False, danger: bool = False) -> bool:
        """Global minimum gap between phrases. A danger/feature phrase (``priority``) waits only the
        shorter ``priorityMinGapSeconds``: it must not queue behind a scene-context phrase. A phrase with a
        danger in it (``danger``, v26.1.15, review 7: a person was held 0.8 s behind a pole) only counts
        earlier danger / final phrases: a feature or context phrase never delays a danger."""
        gap = self.cfg["globalMinGapSeconds"]
        if danger:
            gap = min(gap, self.cfg.get("priorityMinGapSeconds", gap))
            return self.last_danger_t is None or t - self.last_danger_t >= gap - 1e-9
        if priority:
            # only earlier danger/feature phrases count: a context phrase never delays a danger
            gap = min(gap, self.cfg.get("priorityMinGapSeconds", gap))
            return self.last_prio_t is None or t - self.last_prio_t >= gap - 1e-9
        return self.last_t is None or t - self.last_t >= gap - 1e-9

    def _event(self, t: float, role: str, text: str, it: _Item | None, urgency: str = "none") -> dict:
        self.last_t = t
        if role in ("danger", "final", "feature"):
            self.last_prio_t = t
        if role in ("danger", "final"):
            self.last_danger_t = t
        return {"t": round(t, 4), "type": "speech", "role": role, "text": text,
                "trackId": None if it is None else it.track_id, "urgency": urgency,
                "clock": None if it is None else it.clock,
                "clockText": None if it is None else it.clock_text, "pan": 0.0 if it is None else round(it.pan, 4)}

    def step(self, t: float, items: list[_Item], tracks: dict[int, _Track],
             surface_known: bool = True) -> dict | None:
        """``surface_known``: a surface has been adopted (context waits for it)."""
        if self.summary_since is None:
            self.summary_since = t
        if self.summary and t - self.summary_since > WARMUP_S + 1e-9 and surface_known:
            self.summary = self.first_summary = False   # the scene had its chance to be summarised; back to normal
        everything = items
        # "beware poles" is said once, then not again while any thin object stays noticed (within thinNoticeSteps);
        # it re-arms after thinRearmSeconds with none noticed, or on a turn
        if any(i.thin and i.steps <= self.thin_range[0] for i in everything):
            self.last_thin_seen = t
        elif not self.thin_armed and t - self.last_thin_seen >= self.thin_rearm_s:
            self.thin_armed = True
        items = [i for i in items if i.settled]
        ok = lambda i: i.role_run >= self.confirm          # noqa: E731  (confirmed over consecutive frames)
        danger = sorted((i for i in items if i.role == "danger" and ok(i)), key=lambda i: i.steps)
        for i in danger:
            self.danger_first.setdefault(i.track_id, t)
        # 1. final: once per track, ignores the global gap
        for it in danger:
            tr = tracks[it.track_id]
            if it.urgency == "final" and not tr.final_done and it.speak:
                tr.final_done = tr.danger_done = True
                tr.approach_done = tr.approach_done or self._kind(it, "final") == "approach"
                tr.thin_done = tr.thin_done or it.thin
                self.memory_if_spoken(t, it)
                # v26.1.7: a final is only for what was never named. The slot is consumed all the same (the state
                # machine runs exactly as in v26.1.6, so nothing else moves earlier), but nothing is said: the
                # parking-sensor beeps carry the proximity.
                mute = self._seen_before(it, danger=True)        # v26.1.16: only an earlier danger / final for it mutes (not a context phrase)
                # ... and a never-named context-class thing (vegetation, a wall) reached in the middle of other dangers: its beeps are enough
                mute = mute or (it.group == "static" and not it.thin and tr.context_seen and not it.mem_named and self._danger_recent(t))
                if not mute:
                    self._register(t, it, tracks, danger=True)
                ev = self._event(t, "final", self._text(self._kind(it, "final"), it), it, "final")
                return None if mute else ev
        # 2./3. danger, features and the notice for thin objects, one phrase: danger leads, then features, then thin
        # v26.1.12 (review 5, 76.5 s): a mover announced before is announced again, once, when it turns to "approaching" on a
        # collision course ("moving away" at 63 s, then walking towards us); this is the only re-announcement
        pend_d = [i for i in danger if i.speak and (not tracks[i.track_id].danger_done
                                        or (not tracks[i.track_id].approach_done and self._kind(i, "danger") == "approach"))
                  and t - self.danger_label_t.get(i.label, -math.inf) >= self.LABEL_COOLDOWN_S
                  and not self._motion_pending(t, i, tracks)]
        pend_f = sorted((i for i in items if i.role == "feature" and ok(i) and not tracks[i.track_id].feature_done
                         and self._feature_allowed(t, i)),
                        key=lambda i: (i.class_name not in self.landmarks, i.steps))   # crosswalks before curbs
        pend_t = [i for i in items if i.thin and i.present_run >= self.confirm and not tracks[i.track_id].thin_done
                  and i.steps <= self.thin_range[0] and abs(i.lateral_m) <= self.thin_range[1] and not self.stationary]
        in_danger = {i.track_id for i in pend_d}
        note = [i for i in pend_t if i.track_id not in in_danger]
        if not self.thin_armed:
            for i in note:                      # covered by the earlier notice: not named, but not new either
                self._register(t, i, tracks, named=False)
            note = []                           # said already; a noticed thin object keeps it quiet
        if pend_d or pend_f or note:
            if not self._gap_ok(t, priority=True, danger=bool(pend_d)):
                return None
            entries: list[tuple[str, list[_Item]]] = []      # (kind, same-label items)
            for kind, pool in (("danger", pend_d), ("feature", pend_f)):
                by: dict[tuple, list[_Item]] = {}
                for i in pool:
                    by.setdefault((i.label, self._kind(i, "danger") if kind == "danger" else "feature"), []).append(i)
                for (_, template), grp in by.items():
                    entries.append((template, grp))
            by_thin: dict[str, list[_Item]] = {}     # "poles at 11 and 1 in 8": same-label thin objects, nearest steps
            for i in note:
                by_thin.setdefault(i.label, []).append(i)
            entries.extend(("thin", grp) for grp in sorted(by_thin.values(), key=lambda g: min(i.steps for i in g)))
            entries = entries[:self.max_entries]
            cover: list[_Item] = []
            for kind, grp in entries:                # the v26.1.6 bookkeeping, for everything the phrase would cover
                if kind == "thin":
                    for i in grp:
                        tracks[i.track_id].thin_done = True
                    mine = {i.track_id for i in grp}
                    for i in items:                 # the whole cluster in view counts as warned about
                        if i.thin:
                            tracks[i.track_id].thin_done = True
                            if self._mem and i.steps <= self.thin_range[0] and i.track_id not in mine:
                                cover.append(i)     # ... covered, if near enough to be noticed
                    self.thin_armed = False
                    continue
                for i in grp:
                    tr = tracks[i.track_id]
                    if kind == "feature":
                        tr.feature_done = True
                        self.feature_label_t[i.label] = (t, self.travel_steps + i.steps)
                    else:
                        tr.danger_done = True
                        tr.approach_done = tr.approach_done or kind == "approach"
                        tr.thin_done = tr.thin_done or i.thin
                        self.danger_label_t[i.label] = t
                        self.memory_if_spoken(t, i)
            # v26.1.7: only what is not a remembered object is said. Objects remembered already leave the phrase; when
            # nothing is left the slot is consumed silently (same pacing as v26.1.6, see the final above).
            voiced: list[tuple[str, list[_Item]]] = []
            for kind, grp in entries:
                is_danger = kind not in ("feature", "thin")
                vg = [i for i in grp if not self._seen_before(i, named=(kind != "thin"), approach=(kind == "approach"), danger=is_danger)]
                if vg:
                    voiced.append((kind, vg))
                    for i in vg:
                        self._register(t, i, tracks, approach=(kind == "approach"), danger=is_danger)
            for i in cover:
                self._register(t, i, tracks, named=False)
            if not voiced:
                self._event(t, "feature", "", None)
                return None
            lead = next((grp[0] for kind, grp in voiced if kind != "thin"), voiced[0][1][0])
            texts = [self._entry(kind, grp) for kind, grp in voiced]
            if any(kind not in ("feature", "thin") for kind, _ in voiced):
                return self._event(t, "danger", ", ".join(texts), lead, "danger")
            return self._event(t, "feature", ", ".join(texts), lead)
        if danger:                              # context and surface wait while a danger is active
            self.pending_since.clear()
            return None
        # 4. surface
        if self.surface_pending is not None:
            if not self._gap_ok(t):
                return None
            label = self.surface_pending[1]
            self.surface_pending = None
            return self._event(t, "surface", self._text("surface", label=label), None)
        if self._danger_recent(t):              # v26.1.16: no context just after a danger / final phrase or a collision beep
            self.pending_since.clear()
            return None
        # 5. context (after the first surface: the user hears where they walk before what is around;
        #    the start summary does not wait for it and needs no track age, only the confirmation)
        if self.summary:
            pool = [i for i in everything if i.role_run >= self.confirm]
            if self.first_summary:
                pool = [i for i in pool if i.role == "context" or i.summary_ok]
        elif surface_known:
            pool = items
        else:
            return None
        cands: dict[str, _Item] = {}                 # one per label, the nearest
        for it in pool:
            if (it.role == "context" or (self.summary and self.first_summary and it.summary_ok)) \
                    and it.label in self.context_speak:
                key = self._key(it)
                if not self._known(key) and (key not in cands or it.distance_m < cands[key].distance_m):
                    cands[key] = it
        for key in list(self.pending_since):
            if key not in cands:
                del self.pending_since[key]
        for key in cands:
            self.pending_since.setdefault(key, t)
        for key in [k for k in cands if t - self.pending_since[k] > self.cfg["contextMaxDelaySeconds"] + 1e-9]:
            self.memory[key] = t                # too stale to say: treat as known, never spoken
            del cands[key]
            del self.pending_since[key]
        if not cands or not self._gap_ok(t):
            return None
        if self.summary and t - min(self.pending_since[k] for k in cands) < self.cfg.get("summaryHoldSeconds", 0.0) - 1e-9:
            return None                         # let the rest of the first view get confirmed: one phrase, not three
        # one grouped phrase: all newly announceable labels, nearest first, at most contextMaxItems
        chosen = sorted(cands, key=lambda k: cands[k].distance_m)[:self.max_items]
        for key in chosen:
            self.memory[key] = t
            self.pending_since.pop(key, None)
        self.summary = self.first_summary = False
        # v26.1.7: a remembered object (turned back to, re-detected) is not named again; the slot is still consumed
        chosen = [k for k in chosen if not self._seen_before(cands[k])]
        if not chosen:
            self._event(t, "context", "", None)
            return None
        for key in chosen:
            self._register(t, cands[key], tracks)
        first = cands[chosen[0]]
        items_txt = ", ".join(self._text("context", cands[k]) for k in chosen)
        text = self.cfg["templates"].get("contextGroup", "{items}").format(items=items_txt)
        return self._event(t, "context", text, first)

    def memory_if_spoken(self, t: float, it: _Item) -> None:
        """A danger/final call that names a context label counts as having referenced it."""
        if it.label in self.context_speak:
            self.memory[self._key(it)] = t


# --------------------------------------------------------------------------
# Tones
# --------------------------------------------------------------------------

COLLISION_KINDS = ("collision-left", "collision-center", "collision-right")
SOUND_KINDS = COLLISION_KINDS + ("crosswalk-in", "crosswalk-out", "proximity")
SIDE_WORD = {"collision-left": "left", "collision-center": "center", "collision-right": "right"}


def collision_kind(quarter: int, center_quarters: int = 1) -> str:
    """Sound kind of a collision tone from the item's clock quarter (v26.1.16): center = 11:45-12:15 (quarters -1..+1), left =
    9:00-11:30 (<= -2), right = 12:30-3:00 (>= +2). The boundaries 11:45 and 12:15 belong to the center."""
    return "collision-center" if abs(quarter) <= center_quarters else "collision-left" if quarter < 0 else "collision-right"


def resolve_sounds(tones_cfg: dict, profile: dict | None = None) -> dict:
    """The Lab-wide sound profile: ``tones.sounds`` defaults overridden by ``profile`` ({"kinds": {kind: {pitchHz, durationMs, intervalS}},
    "speechRate"}), every value clamped to ``tones.soundRanges``; unknown kinds / fields and non-numbers are ignored. A field that is
    ``null`` in the defaults (the crosswalk-in repeat interval) stays unused."""
    rng = tones_cfg["soundRanges"]
    kinds = {k: dict(v) for k, v in tones_cfg["sounds"].items()}

    def num(v):
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None

    for k, ent in ((profile or {}).get("kinds") or {}).items():
        if k not in kinds or not isinstance(ent, dict):
            continue
        for f in ("pitchHz", "durationMs", "intervalS"):
            v = num(ent.get(f))
            if v is not None and kinds[k].get(f) is not None:
                kinds[k][f] = max(rng[f][0], min(rng[f][1], v))
    rate = num((profile or {}).get("speechRate"))
    rate = float(tones_cfg.get("speechRate", 1.0)) if rate is None else max(rng["speechRate"][0], min(rng["speechRate"][1], rate))
    return {"kinds": kinds, "speechRate": rate}


def _tone_interval(steps: float, by_steps: list[list[float]]) -> float:
    """Beep interval in seconds, linearly interpolated by steps, clamped to the table ends.
    ``by_steps`` rows are ``[steps, intervalSeconds]`` (extra columns are ignored)."""
    table = sorted(by_steps, key=lambda r: r[0])
    return float(np.interp(steps, [r[0] for r in table], [r[1] for r in table]))


def _tone_events(frame_collision: list[tuple[_Item | None, bool]], times: np.ndarray,
                 tones_cfg: dict, frame_proximity: list[tuple[_Item | None, set]] | None = None,
                 crosswalk: list[tuple[float, str]] | None = None, sounds: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Notification sounds (CONTRACTS.md 14.1.9/10) -> (tone events, beeps-episode events).

    ``collision-left`` / ``-center`` / ``-right`` (v26.1.16; ``collision`` before): parking-sensor beeps. One phase-continuous stream
    driven by the nearest collision track of each frame: interval shrinking with steps, a gapless continuous tone at ``continuousSteps``
    or closer. The kind of each tone is that of the driving item's clock quarter at that moment (``collision_kind``), so the pitch
    changes where the item changes sector. A track that is merely lost from view (absent from the frame, not changed to a
    non-collision) keeps beeping for ``holdSeconds``. ``frame_collision`` holds, per frame, (nearest collision item or None, track ids
    present in that frame).

    ``proximity`` (v26.1.13 follow-up): a soft double chirp at a fixed slow rhythm for the nearest person measured approaching nearby
    (``frame_proximity``, same shape). It never plays while a collision stream is active (the collision beeps win) and a track that
    turns into a collision course simply continues as collision beeps.

    ``crosswalk`` (v26.1.14): ``(t, "enter" | "exit")`` marks from ``_CrosswalkTracker`` -> kinds ``crosswalk-in`` (one deep, long tone)
    and ``crosswalk-out`` (the same deep tone twice, short). They are never dropped: one that would sound over a collision /
    proximity tone waits for it to end, at most ``maxOffsetSeconds``.

    ``sounds`` = ``resolve_sounds`` output (the Lab profile): pitch, duration and interval per kind. The collision interval is the one
    at ``maxSteps`` (5 steps); ``bySteps`` is scaled by ``intervalS / bySteps(maxSteps)`` (the continuous chunk is not scaled). The
    proximity interval is its repeat period, the crosswalk-out interval the gap between its two tones.
    """
    sounds = sounds or resolve_sounds(tones_cfg)
    kinds = sounds["kinds"]
    last_dt = float(np.median(np.diff(times))) if len(times) > 1 else 1.0
    hold_s = float(tones_cfg.get("holdSeconds", 0.5))
    gap_s = float(tones_cfg.get("episodeGapSeconds", 1.5))
    by_steps = tones_cfg["bySteps"]
    ref_interval = _tone_interval(float(tones_cfg.get("maxSteps", 5)), by_steps)
    center_q = int(tones_cfg.get("centerQuarters", 1))
    prox = tones_cfg.get("proximity") or {}
    chirp = dict(prox.get("chirp") or {})
    n_chirp = int(chirp.get("count", 2))
    chirp_gap = float(chirp.get("gapSeconds", 0.1))

    def stream(frames, name: str) -> tuple[list[dict], list[tuple[float, float, _Item, str]], list[tuple[float, float]]]:
        soft = name == "proximity"
        chunk = float(tones_cfg.get("continuousChunkSeconds", 0.25))
        cont_steps = float(tones_cfg.get("continuousSteps", 1.5))
        events: list[dict] = []
        marks: list[tuple[float, float, _Item, str]] = []       # (t, tEnd, driving item, kind) per tone event
        active: list[tuple[float, float]] = []                  # frame spans in which the stream is driven
        next_due = -math.inf
        last_beep = -math.inf
        held: tuple[_Item, float] | None = None
        for i, (top, present) in enumerate(frames):
            t0 = float(times[i])
            t1 = float(times[i + 1]) if i + 1 < len(times) else t0 + last_dt
            if top is not None:
                held = (top, t0)
            elif held is not None and held[0].track_id not in present and t0 - held[1] <= hold_s:
                top = held[0]
            else:
                held = None
                continue
            active.append((t0, t1))
            kind = "proximity" if soft else collision_kind(top.clock_q, center_q)
            snd = kinds[kind]
            freq, dur = float(snd["pitchHz"]), float(snd["durationMs"]) / 1000.0
            if soft:
                interval, length = float(snd["intervalS"]), n_chirp * dur + (n_chirp - 1) * chirp_gap
            else:
                continuous = top.steps <= cont_steps
                interval = chunk if continuous else _tone_interval(top.steps, by_steps) * float(snd["intervalS"]) / ref_interval
                length = chunk if continuous else dur
            # a faster stream must not wait out the previous slower interval
            due = max(t0, min(next_due, last_beep + interval))
            while due < t1 - 1e-9:
                ev = {"t": round(due, 4), "type": "tone", "kind": kind, "role": "danger", "trackId": top.track_id,
                      "urgency": top.urgency, "pan": round(top.pan, 4), "frequencyHz": round(freq, 1),
                      "durationSeconds": round(dur if soft else length, 4)}
                if not soft and top.steps <= cont_steps:
                    ev["continuous"] = True            # a gapless chunk: the player keeps its length whatever the profile's duration
                if soft:
                    ev["gain"] = float(prox.get("gain", 0.25))
                    ev["chirp"] = {"count": n_chirp, "gapSeconds": chirp_gap,
                                   "attackSeconds": float(chirp.get("attackSeconds", 0.03))}
                events.append(ev)
                marks.append((due, due + length, top, kind))
                last_beep = due
                due += interval
            next_due = due
        return events, marks, active

    events, marks, busy = stream(frame_collision, "collision")
    soft_events: list[dict] = []
    soft_marks: list[tuple[float, float, _Item, str]] = []
    if frame_proximity and prox:
        # the collision beeps win: a collision stream is active in these frame spans (held tracks included)
        soft_events, soft_marks, _ = stream(frame_proximity, "proximity")
        keep = [k for k, e in enumerate(soft_events) if not any(a - 1e-9 <= e["t"] < b + 1e-9 for a, b in busy)]
        soft_events = [soft_events[k] for k in keep]
        soft_marks = [soft_marks[k] for k in keep]
    # episodes: one per continuous stream of one track (gap < episodeGapSeconds) and kind
    episodes: list[dict] = []
    cw_events, cw_episodes = _crosswalk_tones(crosswalk or [], tones_cfg.get("crosswalk") or {}, marks + soft_marks, kinds)

    def build(marks_: list[tuple[float, float, _Item, str]]) -> None:
        cur: list[tuple[float, float, _Item, str]] = []

        def flush() -> None:
            if not cur:
                return
            nearest = min(cur, key=lambda m: m[2].steps)[2]
            first = cur[0][2]
            kind = cur[0][3]
            lo, hi = max(1, int(round(nearest.steps))), max(1, int(round(first.steps)))
            steps_txt = f"{hi}→{lo} steps" if hi != lo else f"{lo} steps"
            head = "soft" if kind == "proximity" else f"beeps · {SIDE_WORD[kind]}"
            episodes.append({"t": round(cur[0][0], 4), "tEnd": round(cur[-1][1], 4), "type": "beeps", "kind": kind,
                             "role": "danger", "trackId": nearest.track_id, "label": nearest.label, "clock": nearest.clock,
                             "clockText": nearest.clock_text,
                             "minSteps": round(nearest.steps, 1), "urgency": nearest.urgency,
                             "text": f"{head} · {nearest.label} at {nearest.clock_text} · {steps_txt}"})

        for m in marks_:
            # a new episode when the track changes, after a gap, or where the item changes sector (the kind)
            if cur and (m[2].track_id != cur[-1][2].track_id or m[3] != cur[-1][3] or m[0] - cur[-1][1] >= gap_s):
                flush()
                cur = []
            cur.append(m)
        flush()

    build(marks)
    build(soft_marks)
    episodes.extend(cw_episodes)
    episodes.sort(key=lambda e: e["t"])
    return events + soft_events + cw_events, episodes


def _crosswalk_tones(marks: list[tuple[float, str]], cfg: dict, other_marks: list[tuple], kinds: dict) -> tuple[list[dict], list[dict]]:
    """Tone events + beeps-style episodes for the crosswalk enter / exit marks (see ``_tone_events``): kinds ``crosswalk-in`` /
    ``crosswalk-out``; pitch and duration from the profile, the gap of the two ``crosswalk-out`` tones is its interval."""
    if not marks or not cfg:
        return [], []
    busy = sorted((m[0], m[1]) for m in other_marks)               # spans in which a collision / proximity tone sounds
    max_off = float(cfg.get("maxOffsetSeconds", 0.3))
    events: list[dict] = []
    episodes: list[dict] = []
    for t, what in marks:
        kind = "crosswalk-in" if what == "enter" else "crosswalk-out"
        c, snd = cfg["in" if what == "enter" else "out"], kinds[kind]
        count = int(c.get("count", 1))
        dur = float(snd["durationMs"]) / 1000.0
        gap = float(snd["intervalS"] or 0.0) if count > 1 else 0.0
        length = count * dur + (count - 1) * gap
        start = t
        for a, b in busy:                                          # wait out a tone we would sound over (<= maxOffsetSeconds)
            if a < start + length + 1e-9 and b > start - 1e-9:
                start = min(b + 0.02, t + max_off)
        ev = {"t": round(start, 4), "type": "tone", "kind": kind, "role": "feature", "urgency": "none", "pan": 0.0,
              "frequencyHz": round(float(snd["pitchHz"]), 1), "durationSeconds": round(dur, 4),
              "gain": float(c.get("gain", 0.5)),
              "chirp": {"count": count, "gapSeconds": gap, "attackSeconds": float(c.get("attackSeconds", 0.03))}}
        events.append(ev)
        arrow = "⇥ crosswalk in" if what == "enter" else "⇤ crosswalk out"
        episodes.append({"t": ev["t"], "tEnd": round(start + length, 4), "type": "beeps", "kind": kind, "role": "feature",
                         "urgency": "none", "text": f"{arrow} · {'one deep tone' if count == 1 else 'two deep tones'}"})
    return events, episodes


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

def _lane_polygon(geo: _FrameGeo, lane_half_m: float, far_distance_m: float) -> list[list[float]]:
    def half(y: float) -> float:
        return lane_half_m * (y - geo.horizon) * geo.gh / geo.camera_height_m / geo.gw

    def mid(y: float) -> float:
        return 0.5 - geo.lateral_offset_m * (y - geo.horizon) * geo.gh / geo.camera_height_m / geo.gw

    y_far = min(1.0, geo.horizon + geo.camera_height_m * geo.f / (far_distance_m * geo.gh))
    y_far = max(y_far, geo.horizon)

    def cl(x: float) -> float:
        return round(min(1.0, max(0.0, x)), 4)

    return [[cl(mid(1.0) - half(1.0)), 1.0], [cl(mid(1.0) + half(1.0)), 1.0],
            [cl(mid(y_far) + half(y_far)), round(y_far, 4)], [cl(mid(y_far) - half(y_far)), round(y_far, 4)]]


def _region_rows(region: Region | None, step: int = 4) -> list[list[float]]:
    if region is None:
        return []
    gh = len(region.left)
    return [[round((r + 0.5) / gh, 3), round(float(region.left[r]), 3), round(float(region.right[r]), 3)]
            for r in range(gh - 1, -1, -step) if not np.isnan(region.left[r])]


def _r(v: float | None, nd: int) -> float | None:
    return None if v is None else round(float(v), nd)

# --------------------------------------------------------------------------
# Outlines (v26.1.8): the outer contour of an item's own connected component
# --------------------------------------------------------------------------

OUTLINE_EPS_PX = 0.75     # Douglas-Peucker tolerance in grid pixels
OUTLINE_MAX_POINTS = 32   # epsilon is raised until the outline fits

_DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))   # east, south, west, north (x right, y down)


def trace_outline(mask: np.ndarray) -> list[tuple[int, int]]:
    """Outer boundary of the 4-connected component ``mask`` (bool, True = member) as pixel-corner vertices.

    Walks the pixel borders with the component on the right-hand side (square tracing on the corner lattice),
    starting at the top-left corner of the first pixel in row-major order. The result is a closed polygon in
    (x, y) = (column, row) corner coordinates, collinear vertices dropped; holes are ignored. Corner
    coordinates make the extent equal ``bbox`` exactly (``[min col, min row, max col + 1, max row + 1]``), and
    diagonal-only contacts are not crossed (the walk turns right there: 4-connectivity, as in detect_items).
    """
    m = np.pad(np.asarray(mask, dtype=bool), 1)           # padded: pixel (c, r) is m[r + 1, c + 1]
    r0, c0 = np.argwhere(m)[0]
    x0, y0 = int(c0) - 1, int(r0) - 1

    def inside(c: int, r: int) -> bool:
        return bool(m[r + 1, c + 1])

    # pixels ahead of vertex (x, y) when moving in direction d: (left, right)
    ahead = (lambda x, y: ((x, y - 1), (x, y)),           # east
             lambda x, y: ((x, y), (x - 1, y)),           # south
             lambda x, y: ((x - 1, y), (x - 1, y - 1)),   # west
             lambda x, y: ((x - 1, y - 1), (x, y - 1)))   # north
    x, y, d = x0, y0, 3                                   # arrive at the start corner heading north
    pts: list[tuple[int, int]] = []
    limit = 4 * m.size + 8
    for _ in range(limit):
        (lc, lr), (rc, rr_) = ahead[d](x, y)
        if not inside(rc, rr_):
            nd = (d + 1) % 4                               # right: the wall ends
        elif inside(lc, lr):
            nd = (d + 3) % 4                               # left: blocked
        else:
            nd = d
        if nd != d:
            pts.append((x, y))
        d = nd
        x, y = x + _DIRS[d][0], y + _DIRS[d][1]
        if (x, y, d) == (x0, y0, 3):
            break
    return pts


def _dp_open(pts: np.ndarray, eps: float) -> list[int]:
    """Douglas-Peucker on an open polyline: indices of the kept points (both ends always kept)."""
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = pts[b] - pts[a]
        n = float(np.hypot(*seg))
        rel = pts[a + 1:b] - pts[a]
        dist = np.hypot(rel[:, 0], rel[:, 1]) if n == 0 else np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / n
        i = int(np.argmax(dist))
        if dist[i] > eps:
            k = a + 1 + i
            keep.add(k)
            stack += [(a, k), (k, b)]
    return sorted(keep)


def simplify_polygon(pts: list[tuple[float, float]], eps: float = OUTLINE_EPS_PX,
                     max_points: int = OUTLINE_MAX_POINTS) -> list[tuple[float, float]]:
    """Douglas-Peucker for a closed polygon; ``eps`` grows (x1.25) until at most ``max_points`` remain.

    The ring is split at vertex 0 and the vertex farthest from it, so both anchors survive. Concavities
    deeper than ``eps`` are kept (no convex hull). Polygons already within the cap and below 4 points pass through.
    """
    a = np.asarray(pts, dtype=float)
    if len(a) <= 3:
        return [(float(x), float(y)) for x, y in a]
    far = int(np.argmax(np.hypot(*(a - a[0]).T)))
    h1, h2 = a[:far + 1], np.vstack([a[far:], a[:1]])
    while True:
        k1, k2 = _dp_open(h1, eps), _dp_open(h2, eps)
        out = [(float(h1[i][0]), float(h1[i][1])) for i in k1] + [(float(h2[i][0]), float(h2[i][1])) for i in k2[1:-1]]
        if len(out) <= max_points:
            return out
        eps *= 1.25


def item_outline(it: _Item, gh: int, gw: int) -> list[list[float]] | None:
    """Normalised, simplified outline ``[[x, y], ...]`` of the item's component (4 decimals), or None."""
    if it.shape is None:
        return None
    mask, c0, r0 = it.shape
    poly = simplify_polygon([(x + c0, y + r0) for x, y in trace_outline(mask)])
    return [[round(x / gw, 4), round(y / gh, 4)] for x, y in poly]


def _mute_solid(it: _Item, smap: "_StaticMap | None") -> None:
    """``insideSolid.mode`` "suppress" (the v26.2.2 first design, kept for A/B): an item inside / behind a wall face gets no role, speech, beeps or
    proximity sound. The shipped mode "snap" corrects its position instead (``_StaticMap.snap_solid``)."""
    if smap is None or smap.solid_mode != "suppress" or not it.inside_solid:
        return
    it.role, it.urgency, it.collision, it.summary_ok, it.proximity, it.speak = "none", "none", False, False, False, False


def _hazard_json(it: _Item, gh: int = 0, gw: int = 0) -> dict:
    out = _hazard_dict(it)
    if it.role != "none" and gh and gw:
        outline = item_outline(it, gh, gw)
        if outline:
            out["outline"] = outline
    return out


def _hazard_dict(it: _Item) -> dict:
    return {"trackId": it.track_id, "className": it.class_name, "group": it.group, "label": it.label,
            "role": it.role, "moving": it.moving if it.group == "moving" else False,
            "bbox": [round(v, 4) for v in it.bbox], "contactY": round(it.contact_y, 4),
            "bearingDeg": round(it.bearing, 2), "clock": it.clock, "clockText": it.clock_text, "pan": round(it.pan, 4),
            "distanceM": round(it.distance_m, 2), "lateralM": round(it.lateral_m, 2),
            "stepsTo": round(it.steps, 1), "closingMps": _r(it.closing, 2),
            "urgency": it.urgency, "areaFrac": round(it.area_frac, 5), "collision": bool(it.collision),
            "latVelMps": _r(it.lat_vel, 2), "crossMps": _r(it.cross_mps, 2),
            **({"depthM": _r(it.depth_m, 2)} if it.depth_on else {}),
            **({"lanePart": True} if it.lane_part else {}),
            **({"source": it.map_source, "mapCells": it.map_cells} if it.group == "static" and it.map_source else {}),
            **({"imageDistanceM": round(it.image_dl[0], 2), "imageLateralM": round(it.image_dl[1], 2)} if it.image_dl else {}),
            **({"ghost": True} if it.ghost else {}),
            **({"coasting": True} if it.coasting else {}),
            **({"insideSolid": True} if it.inside_solid else {}),
            **({"solidCorrected": True, "rawDistanceM": round(it.raw_distance_m, 2)} if it.solid_corrected else {}),
            **({"faceEdge": it.face_edge} if it.face_edge else {})}


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Static items on the fused world map (v26.2.1)
# --------------------------------------------------------------------------

class _StaticMap:
    """The collision pass's online world map (``worldmap.WorldMap``, causal: this frame and the past) and what the static rules
    read from it.

    Per static item: its footprint = the map cells of its own ground-base pixels (the pixels the map projects: the lowest pixel of each
    vertical run of the item, at its depth), grown by ``mapFootprintRadiusM``. The item's cells are the fused map's object cells of its
    family (spoken label) on that footprint with a fused confidence >= ``mapMinConf`` (a cell seen in two frames, not a one-frame
    blip). Those inside the walking corridor (|lateral| <= laneHalfWidthM, ahead > 0) make it a danger; the nearest one is the item's
    distance, lateral, bearing and clock. A static danger that is clipped / leaves the bottom of the image is followed on in the map
    (``ghost``): its cells are looked up again at the dead-reckoned position until they are passed or decayed."""

    def __init__(self, wmod, grids, times, class_names, config: dict, settings, lat_off: float, projection: str, source: str,
                 lane_half: float, step_len: float):
        roles = config["roles"]
        wcfg = wmod.load_config()
        wsettings = {"hfovDeg": settings.hfov_deg, "cameraHeightM": settings.camera_height_m, "lateralOffsetM": lat_off,
                     "projection": projection, "distanceSource": source}
        self.wm = wmod.WorldMap(grids, times, class_names, None, wsettings, config, wcfg, None)
        self.ob = self.wm.observer
        self.object_kind = wmod.KIND_OBJECT
        ob = self.ob
        self.cell = ob.cell
        self.step_len = step_len
        self.corr_full = (ob.fwd > 0.0) & (np.abs(ob.right) <= lane_half + float(roles.get("mapCorridorMarginM", 0.0)))   # the corridor the map judges
        self.min_conf = int(math.ceil(float(roles.get("mapMinConf", 0.7)) * 255.0 - 1e-9))
        self.ghost_conf = int(math.ceil(float(roles.get("mapGhostMinConf", 0.3)) * 255.0 - 1e-9))     # the image already confirmed the item
        self.rad = max(0, int(round(float(roles.get("mapFootprintRadiusM", 0.3)) / ob.cell)))
        yy, xx = np.mgrid[-self.rad:self.rad + 1, -self.rad:self.rad + 1]
        self.disk = (yy * yy + xx * xx) <= self.rad * self.rad + 0.5
        self.image_fallback = bool(roles.get("mapImageFallback", True))
        self.judged = frozenset(roles.get("mapJudgedClasses", ()))          # wall-like classes the map judges (face / edge test)
        isd = roles.get("insideSolid") or {}
        self.solid_mode = str(isd.get("mode", "off"))                      # "snap" | "suppress" | "off"
        self.solid_on = self.solid_mode in ("snap", "suppress")
        self.solid_depth = float(isd.get("solidDepthM", 0.5))
        self.solid_rays = max(1, int(isd.get("minRayCells", 2)))
        self.wall_lut = np.zeros(256, dtype=bool)
        for cid, name in enumerate(class_names):
            if name in self.judged:
                self.wall_lut[cid] = True
        self.wall_solid = None
        self.ghost_s = float(roles.get("mapGhostSeconds", 2.0))
        self.ghost_near_m = float(roles.get("mapGhostNearM", 2.0))
        labels = config.get("spokenLabels", {})
        self.labels = labels
        self.fam: dict[str, np.ndarray] = {}
        for cid, name in enumerate(class_names):
            if self.wm.kind[cid] == self.object_kind:
                self.fam.setdefault(labels.get(name, name.replace("-", " ")), np.zeros(256, dtype=bool))[cid] = True
        self._names = list(class_names)
        fe = roles.get("faceEdge") or {}
        self.fe_cfg = faceedge.settings(fe) if fe.get("enabled") else None      # v26.2.2 phase A: diagnostics only, default off
        self.fe_lines: dict | None = None
        self.stationary = False
        self.fe_res: dict = {}
        self._fe_cache: dict = {}
        self.ms = 0.0
        self.classes = self.conf = self.solid = None
        self.pose = (0.0, 0.0, 0.0)
        self.b_rr = self.b_cc = self.b_row = self.b_col = np.zeros(0, dtype=np.int64)

    def update(self, i: int, frame: dict, dmap, grid: np.ndarray) -> None:
        """Fuse frame i (pose, observation, votes, snapshot) and index the object-base points of its image."""
        _, self.classes, self.conf, self.ms = self.wm.step(i, frame, dmap)
        self.frame_i = i
        self.stationary = bool((frame.get("ego") or {}).get("stationary"))
        self.fe_lines, self.fe_res, self._fe_cache = None, {}, {}
        self.pose = self.wm.last_pose
        is_obj = self.wm.kind[self.classes] == self.object_kind
        self.solid = is_obj & (self.conf >= self.min_conf)
        self.solid_ghost = is_obj & (self.conf >= self.ghost_conf)
        self.wall_solid = self.wall_lut[self.classes] & (self.conf >= self.min_conf) if self.solid_on else None     # solid = fused wall-like cells
        ob = self.ob
        rr, cc, dist, lat = ob.object_bases(grid, frame, dmap)
        row = ob.orow - np.rint(dist / ob.cell).astype(np.int64)
        col = ob.oc + np.rint(lat / ob.cell).astype(np.int64)
        ok = (row >= 0) & (row < ob.size) & (col >= 0) & (col < ob.size)
        self.b_rr, self.b_cc, self.b_row, self.b_col = rr[ok], cc[ok], row[ok], col[ok]

    # -- solid areas (v26.2.2) -----------------------------------------------------------------------------
    def solid_border(self, fwd: float, right: float) -> tuple[float, float] | None:
        """If the map point lies inside solid cells of the wall-like classes (or behind a confirmed face: >= ``minRayCells`` consecutive solid
        cells on the ray from us) by more than ``solidDepthM`` along its own bearing, the point where that ray first enters the solid: the
        near border (forward m, right m). None when the point is not inside / behind a solid area."""
        if self.wall_solid is None or fwd <= 0.0:
            return None
        ob = self.ob
        dist = math.hypot(fwd, right)
        n = int(dist / ob.cell)
        if n < 4 + self.solid_rays:
            return None
        k = np.arange(4, n + 1)
        rr = np.rint(ob.orow - fwd / dist * k).astype(np.int64)
        cc = np.rint(ob.oc + right / dist * k).astype(np.int64)
        ok = (rr >= 0) & (rr < ob.size) & (cc >= 0) & (cc < ob.size)
        hit = np.zeros(k.size, dtype=bool)
        hit[ok] = self.wall_solid[rr[ok], cc[ok]]
        if self.solid_rays > 1:
            run = np.convolve(hit.astype(np.int8), np.ones(self.solid_rays, dtype=np.int8), mode="valid") >= self.solid_rays
            idx = np.flatnonzero(run)
        else:
            idx = np.flatnonzero(hit)
        if not idx.size:
            return None
        k0 = int(k[idx[0]])
        if dist - k0 * ob.cell <= self.solid_depth:
            return None
        return fwd / dist * k0 * ob.cell, right / dist * k0 * ob.cell

    def point_in_solid(self, fwd: float, right: float) -> bool:
        return self.solid_border(fwd, right) is not None

    def snap_solid(self, it: _Item) -> None:
        """v26.2.2 (user decision): an item whose map position is inside / behind a wall face is a depth error, not an impossible warning: it is moved
        along its own bearing to the near border of the solid area and every later rule (steps, clock, role, speech, beeps) sees the corrected point.
        Wall-like items are measured at their own face and never count against it."""
        if not self.solid_on or it.ghost or it.class_name in self.judged:
            return
        b = self.solid_border(it.distance_m, it.lateral_m)
        if b is None:
            return
        it.inside_solid = True
        if self.solid_mode == "snap":
            it.raw_distance_m = it.distance_m
            fwd, right = b
            bearing = math.degrees(math.atan2(right, fwd))
            it.distance_m, it.lateral_m, it.bearing = fwd, right, bearing
            it.clock, it.clock_q = clock_from_bearing(bearing), clock_quarter(bearing)
            it.clock_text = clock_text(it.clock_q)
            it.pan = _pan_from_bearing(bearing)
            it.solid_corrected = True

    # -- measurement ---------------------------------------------------------------------------------------
    def _lut(self, it: _Item) -> np.ndarray | None:
        return self.fam.get(self.labels.get(it.class_name, it.class_name.replace("-", " ")))

    def _corridor_cells(self, patch, lut: np.ndarray, r0: int, c0: int, full: bool = False):   # full: the ghost's search (whole corridor, lower confidence)
        """(forward m, right m, corridor count, family count) of the nearest corridor cell of the family inside the boolean ``patch``
        (offset r0, c0); the position is None when no cell of the family is in the corridor."""
        sl = (slice(r0, r0 + patch.shape[0]), slice(c0, c0 + patch.shape[1]))
        fam = patch & (self.solid_ghost if full else self.solid)[sl] & lut[self.classes[sl]]
        nf = int(np.count_nonzero(fam))
        inc = fam & self.corr_full[sl]
        n = int(np.count_nonzero(inc))
        if not n:
            return None, None, 0, nf
        fwd, right = self.ob.fwd[sl][inc], self.ob.right[sl][inc]
        k = int(np.argmin(fwd + 1e-3 * np.abs(right)))
        return float(fwd[k]), float(right[k]), n, nf

    def _apply(self, it: _Item, fwd: float, right: float, n: int) -> None:
        bearing = math.degrees(math.atan2(right, fwd))
        if it.image_dl is None:
            it.image_dl = (it.distance_m, it.lateral_m, it.bearing, it.clock, it.clock_q, it.clock_text, it.pan)
        it.distance_m, it.lateral_m, it.bearing = fwd, right, bearing
        it.clock = clock_from_bearing(bearing)
        it.clock_q = clock_quarter(bearing)
        it.clock_text = clock_text(it.clock_q)
        it.pan = _pan_from_bearing(bearing)
        it.map_cells = n
        x, y, th = self.pose
        s_, c_ = math.sin(math.radians(th)), math.cos(math.radians(th))
        it.map_world = (x + s_ * fwd + c_ * right, y + c_ * fwd - s_ * right)

    def _footprint(self, it: _Item, lut):
        """(footprint mask, row0, col0) of a static item's ground-base pixels on the map, grown by the footprint radius; None if it has none."""
        if lut is None or it.shape is None or not self.b_rr.size:
            return None
        mask, c0, r0 = it.shape
        rb, cb = self.b_rr - r0, self.b_cc - c0
        ok = (rb >= 0) & (rb < mask.shape[0]) & (cb >= 0) & (cb < mask.shape[1])
        ok[ok] = mask[rb[ok], cb[ok]]
        if not ok.any():
            return None
        row, col = self.b_row[ok], self.b_col[ok]
        R, size = self.rad, self.ob.size
        pr0, pr1 = max(0, int(row.min()) - R), min(size, int(row.max()) + R + 1)
        pc0, pc1 = max(0, int(col.min()) - R), min(size, int(col.max()) + R + 1)
        fp = np.zeros((pr1 - pr0, pc1 - pc0), dtype=bool)
        fp[row - pr0, col - pc0] = True
        if R:
            fp = ndimage.binary_dilation(fp, structure=self.disk)
        return fp, pr0, pc0

    def faceedge(self, it: _Item) -> None:
        """The face / edge test (``roles.faceEdge``) on the corridor cells (the full +-laneHalfWidthM corridor, fused confidence >= ``mapMinConf``)
        of a static item's family on its footprint. Sets ``it.face_edge`` (the verdict and its numbers, the wall lines, the free-space
        contradictions, the image rule's inputs; it goes into hazards.json) and ``self.fe_res[track_id]`` (per-cell results). ``measure`` judges on it."""
        it.face_edge = None
        if self.fe_cfg is None or it.group != "static":
            return
        lut = self._lut(it)
        fpr = self._footprint(it, lut)
        if fpr is None:
            return
        fp, pr0, pc0 = fpr
        sl = (slice(pr0, pr0 + fp.shape[0]), slice(pc0, pc0 + fp.shape[1]))
        fam_full = self.solid & lut[self.classes]
        cand = np.zeros_like(fam_full)
        cand[sl] = fp & fam_full[sl] & self.corr_full[sl]
        if not cand.any():
            return
        cfg = self.fe_cfg
        key = id(lut)
        if key not in self._fe_cache:
            fam = fam_full & (self.ob.fwd <= cfg["maxAheadM"])
            orient, _ = faceedge.local_orientation(fam, self.cell, cfg)
            self._fe_cache[key] = (fam, faceedge.fit_wall_lines(fam, self.ob.fwd, self.ob.right, cfg), orient)
        fam, lines, orient = self._fe_cache[key]
        res = faceedge.classify(cand, fam, self.ob.fwd, self.ob.right, self.cell, cfg, lines, orient)
        out = faceedge.summarize(res, cfg)
        out["lines"] = faceedge.lines_json(lines)
        for name, code in (("faceCells", faceedge.FACE), ("edgeCells", faceedge.EDGE)):      # for the Lab's wall-line view (capped)
            k = np.flatnonzero(res["verdict"] == code)[:60]
            if k.size:
                out[name] = [[round(float(res["fwd"][j]), 2), round(float(res["right"][j]), 2)] for j in k]
        out["stationary"] = self.stationary
        out["imageLaneHit"] = bool(it.lane_hit)
        out["imageAlongPath"] = bool(it.along_path)
        it.face_edge = out
        self.fe_res[it.track_id] = res
        self.fe_lines = out["lines"]

    def measure(self, it: _Item) -> None:
        """A static item of a wall-like class (``roles.mapJudgedClasses``: building, wall, fence, barrier, guard-rail, hedge vegetation) is judged
        on the map alone (v26.2.2): the face / edge test (``faceedge``) on the corridor cells of its family on its footprint; at least
        ``faceEdge.minFaceCells`` face cells make it a lane danger, measured at the nearest face cell (distance, lateral, clock, steps). A wall
        beside the path (edge cells), a user standing still, or an item with no footprint on the map is no lane danger. Other static items keep
        the image rule (their ``map_source`` stays "image")."""
        if it.group != "static":
            return
        it.map_source = "image"
        self.faceedge(it)
        if it.class_name not in self.judged or self.fe_cfg is None:
            return
        fe = it.face_edge
        if fe is None and self.image_fallback:
            return                                       # the map has no cells of this item in the corridor to judge: the image rule decides
        it.map_judged = True
        if fe is None:
            return
        it.map_source = "map"
        if self.stationary or fe["verdict"] != "face":
            return
        self._apply(it, fe["nearestFaceM"], fe["nearestFaceRightM"], fe["face"])

    def locate(self, it: _Item) -> None:
        """World position of the item's image measurement (a ghost is followed from it when the map did not place it)."""
        x, y, th = self.pose
        s_, c_ = math.sin(math.radians(th)), math.cos(math.radians(th))
        it.map_world = (x + s_ * it.distance_m + c_ * it.lateral_m, y + c_ * it.distance_m - s_ * it.lateral_m)

    def ghost(self, tr: "_Track", t: float) -> _Item | None:
        """A static danger that left the image keeps its place in the map: the item again, measured from the cells near where it was."""
        src = tr.ghost_src
        if src is None or src.map_world is None:
            return None
        if tr.ghost_t0 is not None and t - tr.ghost_t0 > self.ghost_s + 1e-9:
            return None
        lut = self._lut(src)
        if lut is None:
            return None
        x, y, th = self.pose
        s_, c_ = math.sin(math.radians(th)), math.cos(math.radians(th))
        dx, dy = src.map_world[0] - x, src.map_world[1] - y
        fwd, right = dx * s_ + dy * c_, dx * c_ - dy * s_
        if fwd <= 0.0:
            return None                                   # passed
        size, ob = self.ob.size, self.ob
        row, col = ob.orow - int(round(fwd / ob.cell)), ob.oc + int(round(right / ob.cell))
        R = self.rad + 3                                  # the dead reckoning drifts a little
        pr0, pr1 = max(0, row - R), min(size, row + R + 1)
        pc0, pc1 = max(0, col - R), min(size, col + R + 1)
        if pr1 <= pr0 or pc1 <= pc0:
            return None
        fwd, right, n, _ = self._corridor_cells(np.ones((pr1 - pr0, pc1 - pc0), dtype=bool), lut, pr0, pc0, full=True)
        if n < 1:
            return None
        g = replace(src, ghost=True, shape=None, clipped=True, map_source="map")
        self._apply(g, fwd, right, n)
        return g

    def keeps(self, it: _Item) -> bool:
        """May this item's track be followed as a ghost once the image loses it?"""
        return (it.group == "static" and it.role == "danger" and it.collision
                and (it.clipped or it.distance_m <= self.ghost_near_m))

    def corridor(self) -> dict | None:
        """The nearest object cell of any class in the walking corridor (Lab readout)."""
        m = self.solid & self.corr_full
        if not m.any():
            return None
        fwd = np.where(m, self.ob.fwd, np.inf)
        k = np.unravel_index(int(np.argmin(fwd)), fwd.shape)
        d = float(fwd[k])
        return {"nearestM": round(d, 2), "nearestSteps": round(d / self.step_len, 1),
                "className": self.classes_name(int(self.classes[k]))}

    def classes_name(self, cid: int) -> str:
        return self._names[cid] if cid < len(self._names) else str(cid)


def _motion_series(motion: dict | None, hfov_deg: float, ego_cfg: dict):
    """(t, cadence per sample, cumulative heading degrees per sample, stationary flag per sample or None) or None."""
    if motion is None:
        return None
    mt = np.asarray(motion["t"], dtype=float)
    if len(mt) < 2:
        return None
    dx = np.nan_to_num(np.asarray(motion["dx"], dtype=float))
    dy = np.nan_to_num(np.asarray(motion["dy"], dtype=float))
    cad = estimate_cadence(mt, dy, ego_cfg["cadenceWindowSeconds"], ego_cfg["cadenceBandHz"],
                           ego_cfg["cadenceMinPeakRatio"], dx=dx,
                           min_step_hz=ego_cfg.get("minStepHz", 1.4),
                           harmonic_ratio=ego_cfg.get("harmonicMinRatio", 0.25))
    stat = None
    if motion.get("resid") is not None and len(motion["resid"]) == len(mt):
        stat = estimate_stationary(mt, motion["resid"], ego_cfg.get("stationary", {}))   # v26.1.11; old runs: never stationary
    return mt, cad, np.cumsum(-dx * hfov_deg), stat


def run_collision(grids, times, class_names, config, settings, motion=None, depth=None,
                  window=None, sounds=None) -> tuple[dict, dict]:
    """Per-frame hazards and the speech/tone event list. ``motion`` = {"t","dx","dy"} arrays or None.

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
    if depth is not None and len(depth["t"]):
        depth_t = np.asarray(depth["t"], dtype=float)
        depth_maps = depth["depth"]

    win_bounds = (0.0, 1.0)
    if window is not None:
        win_bounds = (window["c0"] / gw, (window["c0"] + window["cols"]) / gw)
    mser = _motion_series(motion, settings.hfov_deg, ego_cfg)
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
    smap = None                                # v26.2.1: the online world map the static rules read (roles.staticSource "map")
    if roles.get("staticSource", "image") == "map" and n:
        import worldmap
        smap = _StaticMap(worldmap, grids, times, class_names, config, settings, lat_off, projection, source, lane_half, step_len)
    map_ms: list[float] = []
    under_rows = int(config["surfaces"].get("passUnderRows", 6))
    under_gone_s = float(config["surfaces"].get("passUnderGoneSeconds", 1.5))
    under_min_w = float(config["surfaces"].get("passUnderMinWidth", 0.15))
    tracks: dict[int, _Track] = {}
    next_id = 1
    next_lane_part_id = LANE_PART_ID_BASE            # lane parts have their own id range: they do not shift the ids of the ordinary tracks
    prev_group: str | None = None
    prev_left = prev_right = None
    horizon = settings.horizon_default
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
        if not warm:
            horizon = float(np.mean(raws)) if raws else settings.horizon_default
        elif raw is None and t - last_estimate_t <= HORIZON_HOLD_S:
            pass                                  # a brief failed estimate keeps the last good horizon
        else:
            target = settings.horizon_default if raw is None else raw
            step = geo_cfg["horizonEma"] * (target - horizon)
            horizon += max(-geo_cfg["horizonMaxStep"], min(geo_cfg["horizonMaxStep"], step))

        cadence = heading = None
        stationary = False
        if mser is not None:
            mt, cad, hcum, stat = mser
            j = int(np.clip(np.searchsorted(mt, t), 0, len(mt) - 1))
            if j > 0 and abs(mt[j - 1] - t) < abs(mt[j] - t):
                j -= 1
            cadence = None if np.isnan(cad[j]) else float(cad[j])
            heading = float(np.interp(t, mt, hcum))
            stationary = stat is not None and bool(stat[j])
        walk_cadence = None if stationary else cadence      # a standing user's bob is not a gait
        # v26.1.14: stepping onto / off a crosswalk (the crosswalk share under the feet)
        cw_change = crosswalk.update(t, _seed_fraction(grid, cw_class, config["surfaces"]["seedBox"]), stationary)
        if cw_change:
            cw_marks.append((t, cw_change))

        # 3. items
        k = scale.value                            # gait scale from the frames so far: metres are real-world
        geo = _frame_geometry(gh, gw, horizon, settings.camera_height_m * k, f, settings.hfov_deg, lane_half,
                              region, roles["boundaryMarginPx"], projection, lat_off)
        items = detect_items(grid, ids, geo, config)
        dmap = None
        if depth_maps is not None:
            j = int(np.clip(np.searchsorted(depth_t, t), 0, len(depth_t) - 1))
            if j > 0 and abs(depth_t[j - 1] - t) < abs(depth_t[j] - t):
                j -= 1
            dmap = np.asarray(depth_maps[j])
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
        if heading is not None and prev_heading is not None and settings.hfov_deg > 0:
            pan_shift = max(-0.25, min(0.25, -(heading - prev_heading) / settings.hfov_deg))
        prev_heading = heading
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
                d_s = ground_distance_m(tr.contact_s, horizon, settings.camera_height_m * k, gh, f)
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
        for it in items:
            if it.depth_raw is None or ds is None:
                continue
            tr = tracks[it.track_id]
            it.depth_m = ds * it.depth_raw             # metric: ds = 1; relative: depth_raw is anchored, ds the level c
            if source == "depth":
                # metric now: no ground scale. Lateral keeps its bearing at the new distance.
                if it.distance_m > 0:
                    it.lateral_m = (it.lateral_m - lat_off) * (it.depth_m / it.distance_m) + lat_off
                it.distance_m, it.from_depth = it.depth_m, True
                raw_c = _depth_closing(tr.dhist, t, trk.get("peopleMotionMinSeconds", trk["motionMinSeconds"])
                                       if it.people else trk["motionMinSeconds"])
                tr.closing = None if raw_c is None else ds * raw_c
                it.closing = tr.closing

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

        depth_scale_out = None if depth_maps is None or ds is None else _r(ds * a_now, 4) if relative else ds
        corridor_out = None
        if smap is not None:
            # v26.2.1: the map of this frame (causal), fed with the same ego values the hazards.json stores, so that the offline
            # ``worldmap.build`` reproduces it; static items are then judged on it; a static danger that left the image is a ghost
            frame_in = {"horizon": round(horizon, 4), "scale": round(scale.value, 3), "depthScale": depth_scale_out,
                        "ego": {"speedMps": _r(ego_speed, 2), "headingDeg": _r(heading, 1), "stationary": stationary}}
            smap.update(i, frame_in, dmap, grid)
            map_ms.append(smap.ms)
            for it in items:
                smap.measure(it)
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
            items.extend(coast.items(t, real, world, tracks, step_len, smap.point_in_solid if smap is not None and smap.solid_on else None))

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
                if tr.along_s is None or tau <= 0 or t - tr.along_t > trk["maxMissedSeconds"]:
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
            tr.moving = it.moving
            if smap is not None:
                smap.snap_solid(it)
            it.steps = steps_to(it.distance_m, step_len)
            base = labels.get(it.class_name, it.class_name.replace("-", " "))
            it.family = base
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
        world.advance(t, dt, 0.0 if stationary else (walk_cadence * step_len if walk_cadence else ego_speed), heading)
        world.link(items, tracks, t)

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
        speech = policy.step(t, items, tracks, surface_known)
        if speech:
            events.append(speech)

        beeping = [it for it in items if it.role == "danger" and it.collision and it.settled
                   and it.role_run >= policy.confirm and it.steps <= config["tones"].get("maxSteps", roles["dangerSteps"])]
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
            **({"corridor": corridor_out} if smap is not None else {}),
            **({"faceEdgeLines": smap.fe_lines} if smap is not None and smap.fe_lines else {}),
            "hazards": [_hazard_json(it, gh, gw) for it in sorted(items, key=lambda it: it.steps)],
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
                     "cameraHeightM": settings.camera_height_m, "stepLengthM": settings.step_length_m,
                     "laneHalfWidthM": lane_half, "priorStepLengthM": step_len,
                     "userHeightM": settings.user_height_m, "cameraLocation": settings.camera_location,
                     "cameraSide": settings.camera_side, "lateralOffsetM": lat_off},
        "gridW": gw, "gridH": gh, "egoAvailable": mser is not None, "frames": frames_out,
    }
    if coast.on:
        for tid in list(coast.active):
            coast._end(tid, float(times[-1]) if n else 0.0, "end")
        hazards_doc["coast"] = {"episodes": coast.episodes}
    if window is not None:                    # absent for full-frame runs (their output is unchanged)
        hazards_doc["window"] = dict(window)
    return hazards_doc, {"version": version, "events": events}
