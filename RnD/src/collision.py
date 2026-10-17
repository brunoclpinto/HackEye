"""Collision context, hazards and audio warning events from class grids (v26.1.8).

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

Beyond the contract (small constants at the top / config): a track must live
``MIN_TRACK_AGE_S`` before it may speak or beep; no danger/feature role during the
first ``WARMUP_S`` while the horizon settles (it is the mean of the raw estimates
until then); the last good horizon is held ``HORIZON_HOLD_S`` when an estimate
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
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage

from common_paths import find_common_dir
from geometry import Box, iou

_4_CONNECTIVITY = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
ITEM_GROUPS = ("static", "moving", "feature")
HORIZON_HOLD_S = 3.0      # keep the last good horizon this long when the estimate fails (not in the contract)
WARMUP_S = 1.5            # no danger/feature roles until the horizon has had time to settle
MIN_TRACK_AGE_S = 0.5     # a track must have lived this long before it may speak or beep
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


def _refine(freqs: np.ndarray, power: np.ndarray, k: int) -> float:
    """Parabolic interpolation around bin k."""
    f = float(freqs[k])
    if 0 < k < len(power) - 1:
        a, b, c = power[k - 1], power[k], power[k + 1]
        denom = a - 2 * b + c
        if denom < 0:
            f += 0.5 * (a - c) / denom * (freqs[1] - freqs[0])
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
    f0 = _refine(freqs, power, k0)
    fx = None                                  # stride rhythm seen in dx, if any
    if seg_dx is not None and len(seg_dx) == len(seg):
        xf, xp = _spectrum(seg_dx, dt, pad)
        px = _peak(xf, xp, 0.7, 1.7, lobe)
        if px is not None and px[1] >= CORROBORATED_RATIO_FRAC * min_peak_ratio:
            fx = _refine(xf, xp, px[0])
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
    doubled = _refine(freqs, power, k2)
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


def estimate_horizon(left: np.ndarray, right: np.ndarray, config: dict) -> float | None:
    """Intersection of lines fitted to the left/right bounds, or None when not credible.

    Each line uses the lowest 70 percent of that side's rows where the bound is
    a real path edge. Rows where a bound is clamped to the image border are
    dropped first: a clamped bound is a crop (the path is wider than the
    picture), not an edge, and would flatten the line.
    """
    geo = config["geometry"]
    gh = len(left)
    fits = []
    for bound, clamped in ((left, left <= 1e-6), (right, right >= 1 - 1e-6)):
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
    summary_ok: bool = False                  # would be context but for the lateral cap: allowed in the first scene summary
    people: bool = False                      # person / rider / animal: a mover unless measured stationary
    thin: bool = False                        # pole, light, sign: easy to miss, warned about when noticed
    collision: bool = False                   # a danger on a collision course: the only thing that beeps
    present_run: int = 0                      # consecutive analysed frames the track has been seen
    wx: float = 0.0                           # dead-reckoned world position (m), see _WorldMemory
    wy: float = 0.0
    mem_id: int | None = None                 # the remembered object this item is, if any
    mem_named: bool = False                   # ... and it was named (False: only covered by a cluster notice)
    mem_approach: bool = False                # ... and it was announced as "approaching"
    shape: tuple | None = None                # (cropped component mask, col0, row0): source of the outline (v26.1.8)
    clock_q: int | None = None                # quarter-hour clock index (v26.1.10); derived from ``clock`` if not given
    clock_text: str = ""                      # spoken clock position, "12", "12:15", "11:45"
    depth_m: float | None = None              # metric depth under the item's lower rows (experiment), if a depth map exists
    depth_on: bool = False                    # a depth map exists for this frame (``depthM`` is reported, maybe null)
    depth_raw: float | None = None            # depth under the item's lower rows in the map's own units (metres or relative)
    from_depth: bool = False                  # distance_m was taken from the depth map

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
                items.append(_Item(
                    group=group, class_name=ids.names[cid],
                    bbox=[cc.min() / gw, rr.min() / gh, (cc.max() + 1) / gw, (rr.max() + 1) / gh],
                    contact_y=contact_y, distance_m=dist, lateral_m=lateral_m(x, dist, gw, geo.f) + geo.lateral_offset_m,
                    bearing=bearing, clock=clock_from_bearing(bearing),
                    clock_q=(cq := clock_quarter(bearing)), clock_text=clock_text(cq), pan=_pan_from_bearing(bearing),
                    area_frac=rr.size / (gh * gw), clipped=bool(rr.max() == gh - 1),
                    touches=bool(inreg.any()), lane_hit=lane_hit,
                    along_path=along, lane_cover=cover, contact_y_raw=contact_y,
                    area_m2=rr.size * (dist / geo.f) ** 2,
                    people=ids.names[cid] in ids.people, thin=ids.names[cid] in ids.thin,
                    landmark=ids.names[cid] in ids.landmark,
                    shape=(labels[sl] == k, sl[1].start, sl[0].start)))
    return items


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


def _item_depth_m(it: _Item, dmap: np.ndarray, gh: int, gw: int, lowest_frac: float) -> float | None:
    """Median metric depth under the lowest ``lowest_frac`` of the item's rows (component pixels, mapped by
    normalised coordinates onto the depth grid); None without a valid pixel."""
    mask, c0, r0 = it.shape
    rr, cc = np.nonzero(mask)
    if rr.size == 0:
        return None
    rr = rr + r0
    cc = cc + c0
    h = int(rr.max() - rr.min() + 1)
    keep = rr >= rr.max() + 1 - max(1, int(math.ceil(lowest_frac * h)))
    dh, dw = dmap.shape
    dr = np.minimum(dh - 1, ((rr[keep] + 0.5) / gh * dh).astype(int))
    dc = np.minimum(dw - 1, ((cc[keep] + 0.5) / gw * dw).astype(int))
    v = dmap[dr, dc].astype(float)
    v = v[np.isfinite(v) & (v > 0.0)]
    return None if v.size == 0 else float(np.median(v))


def _match(tracks: dict[int, _Track], items: list[_Item], t: float, trk: dict) -> dict[int, int]:
    """Greedy matching, same group+class; IoU or the ground gate. Returns {item index: track id}."""
    pairs = []
    for tid, tr in tracks.items():
        dt = t - tr.last_t
        expected = -(tr.closing or 0.0) * dt
        for ii, it in enumerate(items):
            if it.group != tr.group or it.class_name != tr.class_name:
                continue
            v = iou(tr.box, Box(*it.bbox))
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


class _SurfaceTracker:
    """Surface group with strict evidence (CONTRACTS.md 15 design 4; supersedes 14.1.8).

    A change of the adopted (stable) surface needs ALL of
      * the new surface holds at least ``majority`` (70 percent) of the frames of a sliding
        ``windowSeconds`` (10 s) window (and the window spans at least ``minPersistSeconds``),
      * (kept from v26.1.6, so this is only ever stricter) it has also run without interruption for
        ``minPersistSeconds``, and
      * a curb or crosswalk edge *passed under the user* no earlier than ``evidenceLookbackSeconds`` before the
        new surface's current uninterrupted run began
        (``note_evidence``: the driver reports it when the contact of such a track reached the bottom
        ``passUnderRows`` grid rows inside the lane and the track was gone within 1.5 s).
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
        self.stable: str | None = None
        self._window: list[tuple[float, str]] = []
        self._evidence: list[float] = []
        self._run: str | None = None             # the surface currently running without interruption ...
        self._run_since = 0.0                    # ... since

    def note_evidence(self, t: float) -> None:
        self._evidence.append(t)
        self._evidence = [e for e in self._evidence if e >= t - 60.0]

    def update(self, t: float, group: str | None) -> tuple[str | None, str, bool] | None:
        """Returns (old, new, announce) when a new group is adopted (old is None for the first), else None."""
        if group is not None:
            self._window.append((t, group))
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
        crossed = any(self._run_since - self.lookback_s - 1e-9 <= e <= t for e in self._evidence)
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
        self.entries[eid] = {"family": it.family or it.label, "x": it.wx, "y": it.wy, "named": named, "approach": False, "seen": t, "fresh": t,
                                "owner": it.track_id}
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
    if it.group != "static" or it.clipped or it.along_path:
        return False
    w, h = it.bbox[2] - it.bbox[0], it.bbox[3] - it.bbox[1]
    return h >= POINT_ASPECT * w


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


def _assign_role(it: _Item, span: tuple[float, float] | None, roles: dict, lane_half_m: float,
                 step_length_m: float) -> None:
    danger_steps, final_steps = roles["dangerSteps"], roles["finalSteps"]
    it.role, it.urgency, it.collision, it.summary_ok = "none", "none", False, False
    big_enough = it.area_m2 >= roles.get("minObstacleAreaM2", 0.0)   # a 15 px blip 4 m away is segmentation noise
    if _is_static_like(it):
        if big_enough and it.lane_hit and not it.along_path and it.steps <= danger_steps:
            it.role, it.collision = "danger", True
        elif (it.touches and it.distance_m <= roles["contextMaxDistanceM"]
              and it.area_frac >= roles.get("contextMinAreaFraction", 0.0)
              and it.distance_m <= roles.get("contextMaxSteps", 1e9) * step_length_m):
            # v26.1.6: only what is near; things far to the side stay silent, except in the very first
            # scene summary of a run, which names the whole view (the user ticked "building at 2" there)
            if abs(it.lateral_m) <= roles.get("contextMaxLateralM", 1e9):
                it.role = "context"
            else:
                it.summary_ok = True
    elif it.group == "moving":
        in_span = span is not None and span[0] <= it.contact_y <= span[1] + 1e-9
        lat = abs(it.lateral_m)
        if it.people:
            wide = roles.get("movingLaneHalfWidthM", lane_half_m + 1.0)
            limit = roles.get("movingDangerSteps", danger_steps)
            receding = it.receding and lat > lane_half_m       # walking away beside us is no threat
            in_span = in_span or span is None                  # on a crosswalk there is no surface seed, hence no region
            if big_enough and in_span and lat <= wide and not receding and it.steps <= limit:
                it.role = "danger"
                it.collision = lat <= lane_half_m or (it.approaching and lat <= roles.get("movingCollisionHalfWidthM", wide))
        elif (big_enough and in_span and lat <= lane_half_m + 1.0 and (it.approaching or lat <= lane_half_m)
              and it.steps <= danger_steps):
            it.role = "danger"
            it.collision = True
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

    def _seen_before(self, it: _Item, named: bool = True, approach: bool = False) -> bool:
        """The item is a remembered object (only with world memory). ``named``: it must have been announced by
        name, not merely covered by a "poles" notice that was never spoken for it. ``approach``: an object that was
        named but not as "approaching" is news again once it approaches (a person who was standing, or walking away)."""
        return (self._mem and it.mem_id is not None and (it.mem_named or not named)
                and (it.mem_approach or not approach))

    def _register(self, t: float, it: _Item, tracks: dict[int, _Track], named: bool = True, approach: bool = False) -> None:
        """Remember an announced object so that neither its fragments nor a later view of it are announced again."""
        if not self._mem:
            return
        if it.mem_id is None:
            it.mem_id = self.world.add(it, t, named)
            tracks[it.track_id].mem_id = it.mem_id
        e = self.world.entries[it.mem_id]
        e["named"] = e["named"] or named
        e["approach"] = e["approach"] or approach
        it.mem_named, it.mem_approach = e["named"], e["approach"]

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
        return self._fmt(template, label=it.label, clock=it.clock_text, steps=self._steps_txt(it))

    @staticmethod
    def _plural(label: str) -> str:
        return label if label.endswith("s") else label + "s"

    def _entry(self, template: str, group: list[_Item]) -> str:
        """One phrase entry for same-label items: "pole at 12 in 6", merged "person at 1 and 2 in 4", "poles at 11 and 1 in 8".
        The steps are those of the nearest item."""
        near = min(group, key=lambda i: i.steps if i.steps is not None and math.isfinite(i.steps) else math.inf)
        clocks = {i.clock_q for i in group}
        steps = self._steps_txt(near)
        if template == "approach":
            return self._fmt("approach", label=near.label, clock=self._join_clocks(group), steps=steps)
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
        return (it.people and it.moving is None and it.ego_known and it.steps > self.motion_wait_steps
                and t - self.danger_first.get(it.track_id, t) < self.motion_wait_s)

    def _gap_ok(self, t: float, priority: bool = False) -> bool:
        """Global minimum gap between phrases. A danger/feature phrase (``priority``) waits only the
        shorter ``priorityMinGapSeconds``: it must not queue behind a scene-context phrase."""
        gap = self.cfg["globalMinGapSeconds"]
        if priority:
            # only earlier danger/feature phrases count: a context phrase never delays a danger
            gap = min(gap, self.cfg.get("priorityMinGapSeconds", gap))
            return self.last_prio_t is None or t - self.last_prio_t >= gap - 1e-9
        return self.last_t is None or t - self.last_t >= gap - 1e-9

    def _event(self, t: float, role: str, text: str, it: _Item | None, urgency: str = "none") -> dict:
        self.last_t = t
        if role in ("danger", "final", "feature"):
            self.last_prio_t = t
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
            if it.urgency == "final" and not tr.final_done:
                tr.final_done = tr.danger_done = True
                tr.thin_done = tr.thin_done or it.thin
                self.memory_if_spoken(t, it)
                # v26.1.7: a final is only for what was never named. The slot is consumed all the same (the state
                # machine runs exactly as in v26.1.6, so nothing else moves earlier), but nothing is said: the
                # parking-sensor beeps carry the proximity.
                mute = self._seen_before(it, named=False)
                if not mute:
                    self._register(t, it, tracks)
                ev = self._event(t, "final", self._text("final", it), it, "final")
                return None if mute else ev
        # 2./3. danger, features and the notice for thin objects, one phrase: danger leads, then features, then thin
        pend_d = [i for i in danger if not tracks[i.track_id].danger_done
                  and t - self.danger_label_t.get(i.label, -math.inf) >= self.LABEL_COOLDOWN_S
                  and not self._motion_pending(t, i, tracks)]
        pend_f = sorted((i for i in items if i.role == "feature" and ok(i) and not tracks[i.track_id].feature_done
                         and self._feature_allowed(t, i)),
                        key=lambda i: (i.class_name not in self.landmarks, i.steps))   # crosswalks before curbs
        pend_t = [i for i in items if i.thin and i.present_run >= self.confirm and not tracks[i.track_id].thin_done
                  and i.steps <= self.thin_range[0] and abs(i.lateral_m) <= self.thin_range[1]]
        in_danger = {i.track_id for i in pend_d}
        note = [i for i in pend_t if i.track_id not in in_danger]
        if not self.thin_armed:
            for i in note:                      # covered by the earlier notice: not named, but not new either
                self._register(t, i, tracks, named=False)
            note = []                           # said already; a noticed thin object keeps it quiet
        if pend_d or pend_f or note:
            if not self._gap_ok(t, priority=True):
                return None
            entries: list[tuple[str, list[_Item]]] = []      # (kind, same-label items)
            for kind, pool in (("danger", pend_d), ("feature", pend_f)):
                by: dict[tuple, list[_Item]] = {}
                for i in pool:
                    by.setdefault((i.label, kind == "danger" and i.approaching), []).append(i)
                for (_, approaching), grp in by.items():
                    entries.append(("approach" if approaching else "danger" if kind == "danger" else "feature", grp))
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
                        tr.thin_done = tr.thin_done or i.thin
                        self.danger_label_t[i.label] = t
                        self.memory_if_spoken(t, i)
            # v26.1.7: only what is not a remembered object is said. Objects remembered already leave the phrase; when
            # nothing is left the slot is consumed silently (same pacing as v26.1.6, see the final above).
            voiced: list[tuple[str, list[_Item]]] = []
            for kind, grp in entries:
                vg = [i for i in grp if not self._seen_before(i, named=(kind != "thin"), approach=(kind == "approach"))]
                if vg:
                    voiced.append((kind, vg))
                    for i in vg:
                        self._register(t, i, tracks, approach=(kind == "approach"))
            for i in cover:
                self._register(t, i, tracks, named=False)
            if not voiced:
                self._event(t, "feature", "", None)
                return None
            lead = next((grp[0] for kind, grp in voiced if kind != "thin"), voiced[0][1][0])
            texts = [self._entry(kind, grp) for kind, grp in voiced]
            if any(kind in ("danger", "approach") for kind, _ in voiced):
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

def _tone_interval(steps: float, by_steps: list[list[float]]) -> float:
    """Beep interval in seconds, linearly interpolated by steps, clamped to the table ends.
    ``by_steps`` rows are ``[steps, intervalSeconds]`` (extra columns are ignored)."""
    table = sorted(by_steps, key=lambda r: r[0])
    return float(np.interp(steps, [r[0] for r in table], [r[1] for r in table]))


def _tone_events(frame_collision: list[tuple[_Item | None, bool]], times: np.ndarray,
                 tones_cfg: dict) -> tuple[list[dict], list[dict]]:
    """Parking-sensor beeps (CONTRACTS.md 14.1.9/10) -> (tone events, beep-episode events).

    One phase-continuous stream driven by the nearest collision track of each frame: constant pitch,
    interval shrinking with steps, a gapless continuous tone at ``continuousSteps`` or closer. A track
    that is merely lost from view (absent from the frame, not changed to a non-collision) keeps beeping
    for ``holdSeconds``. ``frame_collision`` holds, per frame, (nearest collision item or None, track ids
    present in that frame).
    """
    last_dt = float(np.median(np.diff(times))) if len(times) > 1 else 1.0
    freq = float(tones_cfg.get("frequencyHz", 880.0))
    dur = float(tones_cfg["durationSeconds"])
    chunk = float(tones_cfg.get("continuousChunkSeconds", 0.25))
    cont_steps = float(tones_cfg.get("continuousSteps", 1.5))
    hold_s = float(tones_cfg.get("holdSeconds", 0.5))
    gap_s = float(tones_cfg.get("episodeGapSeconds", 1.5))
    by_steps = tones_cfg["bySteps"]
    events: list[dict] = []
    marks: list[tuple[float, float, _Item]] = []            # (t, tEnd, driving item) per tone event
    next_due = -math.inf
    last_beep = -math.inf
    held: tuple[_Item, float] | None = None
    for i, (top, present) in enumerate(frame_collision):
        t0 = float(times[i])
        t1 = float(times[i + 1]) if i + 1 < len(times) else t0 + last_dt
        if top is not None:
            held = (top, t0)
        elif held is not None and held[0].track_id not in present and t0 - held[1] <= hold_s:
            top = held[0]
        else:
            held = None
            continue
        continuous = top.steps <= cont_steps
        interval = chunk if continuous else _tone_interval(top.steps, by_steps)
        length = chunk if continuous else dur
        # a faster stream must not wait out the previous slower interval
        due = max(t0, min(next_due, last_beep + interval))
        while due < t1 - 1e-9:
            events.append({"t": round(due, 4), "type": "tone", "role": "danger", "trackId": top.track_id,
                           "urgency": top.urgency, "pan": round(top.pan, 4), "frequencyHz": round(freq, 1),
                           "durationSeconds": round(length, 4)})
            marks.append((due, due + length, top))
            last_beep = due
            due += interval
        next_due = due
    # episodes: one per continuous stream of one track (gap < episodeGapSeconds)
    episodes: list[dict] = []
    cur: list[tuple[float, float, _Item]] = []

    def flush() -> None:
        if not cur:
            return
        nearest = min(cur, key=lambda m: m[2].steps)[2]
        first = cur[0][2]
        lo, hi = max(1, int(round(nearest.steps))), max(1, int(round(first.steps)))
        steps_txt = f"{hi}\u2192{lo} steps" if hi != lo else f"{lo} steps"
        episodes.append({"t": round(cur[0][0], 4), "tEnd": round(cur[-1][1], 4), "type": "beeps", "role": "danger",
                         "trackId": nearest.track_id, "label": nearest.label, "clock": nearest.clock,
                         "clockText": nearest.clock_text,
                         "minSteps": round(nearest.steps, 1), "urgency": nearest.urgency,
                         "text": f"beeps \u00b7 {nearest.label} at {nearest.clock_text} \u00b7 {steps_txt}"})

    for m in marks:
        if cur and (m[2].track_id != cur[-1][2].track_id or m[0] - cur[-1][1] >= gap_s):
            flush()
            cur = []
        cur.append(m)
    flush()
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
            **({"depthM": _r(it.depth_m, 2)} if it.depth_on else {})}


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def _motion_series(motion: dict | None, hfov_deg: float, ego_cfg: dict):
    """(t, cadence per sample, cumulative heading degrees per sample) or Nones."""
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
    return mt, cad, np.cumsum(-dx * hfov_deg)


def run_collision(grids, times, class_names, config, settings, motion=None, depth=None) -> tuple[dict, dict]:
    """Per-frame hazards and the speech/tone event list. ``motion`` = {"t","dx","dy"} arrays or None.

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

    mser = _motion_series(motion, settings.hfov_deg, ego_cfg)
    ego = _Ego()
    surface = _SurfaceTracker(config["surfaces"])
    scale = _Scale(ego_cfg, step_len)
    policy = SpeechPolicy(config)
    world = _WorldMemory(config.get("memory", {}), enabled=mser is not None)
    policy.world = world
    under_rows = int(config["surfaces"].get("passUnderRows", 6))
    under_gone_s = float(config["surfaces"].get("passUnderGoneSeconds", 1.5))
    under_min_w = float(config["surfaces"].get("passUnderMinWidth", 0.15))
    tracks: dict[int, _Track] = {}
    next_id = 1
    prev_group: str | None = None
    prev_left = prev_right = None
    horizon = settings.horizon_default
    raws: list[float] = []
    last_estimate_t = -math.inf
    first_t: float | None = None
    frames_out: list[dict] = []
    frame_collision: list[tuple[_Item | None, set]] = []
    events: list[dict] = []
    prev_t = float(times[0]) if n else 0.0

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
        raw = None if region is None else estimate_horizon(region.left, region.right, config)
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
        if mser is not None:
            mt, cad, hcum = mser
            j = int(np.clip(np.searchsorted(mt, t), 0, len(mt) - 1))
            if j > 0 and abs(mt[j - 1] - t) < abs(mt[j] - t):
                j -= 1
            cadence = None if np.isnan(cad[j]) else float(cad[j])
            heading = float(np.interp(t, mt, hcum))

        # 3. items
        k = scale.value                            # gait scale from the frames so far: metres are real-world
        geo = _frame_geometry(gh, gw, horizon, settings.camera_height_m * k, f, settings.hfov_deg, lane_half,
                              region, roles["boundaryMarginPx"], projection, lat_off)
        items = detect_items(grid, ids, geo, config)
        if depth_maps is not None:
            j = int(np.clip(np.searchsorted(depth_t, t), 0, len(depth_t) - 1))
            if j > 0 and abs(depth_t[j - 1] - t) < abs(depth_t[j] - t):
                j -= 1
            dmap = np.asarray(depth_maps[j])
            if relative:
                a_hz = anchor_horizon if anchor_horizon is not None else horizon   # fixed: no horizon jitter
                if plane:
                    anchor.update(_plane_fit(region, dmap, a_hz, gh, gw, f, anchor_rows, settings.hfov_deg,
                                             projection, dist_cfg))
                else:
                    a_raw, a_cells = _ground_anchor(region, dmap, a_hz, settings.camera_height_m, gh, gw, f, anchor_rows)
                    anchor.update(t, dt, a_raw, a_cells)
            for it in items:
                it.depth_on = True
                it.depth_raw = _item_depth_m(it, dmap, gh, gw, depth_rows_frac)

        # 4. tracking
        tracks = {k: v for k, v in tracks.items() if t - v.last_t <= trk["maxMissedSeconds"]}
        matches = _match(tracks, items, t, trk)
        for ii, it in enumerate(items):
            tid = matches.get(ii)
            if tid is None:
                tid, next_id = next_id, next_id + 1
                tracks[tid] = _Track(tid, it.group, it.class_name, Box(*it.bbox), t, t,
                                     it.distance_m, it.lateral_m)
            tr = tracks[tid]
            tr.box, tr.last_t, tr.last_distance, tr.last_lateral = Box(*it.bbox), t, it.distance_m, it.lateral_m
            if it.clipped:                        # distance is only a lower bound: no closing from it
                tr.history.clear()
            else:
                tr.history.append((t, it.contact_y_raw))
                tr.history = [h for h in tr.history if h[0] >= t - trk["historySeconds"] - 1e-9]
            raw_closing = _closing_mps(tr.history, horizon, settings.camera_height_m, gh, f,
                                       trk["motionMinRowsBelowHorizon"], trk["motionMinSeconds"])
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
            it.settled = t - tr.first_t >= MIN_TRACK_AGE_S - 1e-9

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
                gait_check.update(t, gait_check.sample(cadence * step_len if cadence else None, wit), dt)
                level, c_source, depth_scale_source = 1.0, "plane", "plane"
            else:
                dscale.update(t, dscale.sample(cadence * step_len if cadence else None, wit), dt, start=prior_c)
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
                raw_c = _depth_closing(tr.dhist, t, trk["motionMinSeconds"])
                tr.closing = None if raw_c is None else ds * raw_c
                it.closing = tr.closing

        # 5. ego
        ego.cadence = cadence
        ego.update_speed([it.closing_raw for it in items
                          if _speed_witness(it) and 0.0 <= it.closing_raw <= ego_cfg["speedMaxMps"]], t, ego_cfg)
        scale.update(t, cadence, ego.speed, dt)
        # ego speed in the units of the (calibrated) distances: walking cadence times the step length once
        # the scale is known, else the witness speed times the scale
        if scale.k is not None and cadence:
            ego_speed = cadence * step_len
        elif ego.speed is not None:
            ego_speed = ego.speed * scale.value
        else:
            ego_speed = None
        turned = ego.update_heading(heading, t, config["pathChange"], dt)

        # 6-8. steps, parked vs moving, roles
        span = None
        if region is not None:
            valid = np.flatnonzero(~np.isnan(region.left))
            if valid.size:
                span = (valid.min() / gh, (valid.max() + 1) / gh)
        for it in items:
            tr = tracks[it.track_id]
            it.moving, it.approaching = (None, False)
            it.ego_known = ego_speed is not None
            if it.group == "static" or it.group == "feature":
                it.moving = False
            elif it.closing is not None and ego_speed is not None:
                ground = it.closing - ego_speed
                limit = roles["stationaryMps"] * (1.5 if tr.moving is False else 1.0)   # hysteresis
                it.moving = abs(ground) >= limit
                it.approaching = it.moving and ground > roles["approachingMps"]
                it.receding = it.moving and ground < -roles["approachingMps"]
            tr.moving = it.moving
            it.steps = steps_to(it.distance_m, step_len)
            base = labels.get(it.class_name, it.class_name.replace("-", " "))
            it.family = base
            it.label = parked_labels.get(it.class_name, base) if (it.group == "moving" and it.moving is False) else base
            if _not_approaching(it, ego.speed) and it.group != "moving":
                it.along_path = True
            _assign_role(it, span, roles, lane_half, step_len)
            if not warm and it.role in ("danger", "feature"):
                it.role, it.urgency, it.collision = "none", "none", False   # no distances on a guessed horizon
            if (it.group == "feature" and it.class_name in ("curb", "crosswalk") and it.lane_hit
                    and it.contact_y * gh > gh - under_rows and it.bbox[2] - it.bbox[0] >= under_min_w):
                tr.under_last = t                      # contact in the bottom rows inside the lane: under our feet

        # confirmation: how many consecutive analysed frames each track has held its role
        seen_tracks = set()
        for it in items:
            tr = tracks[it.track_id]
            tr.role_run = tr.role_run + 1 if tr.role == it.role else 1
            tr.role = it.role
            it.role_run = tr.role_run
            seen_tracks.add(it.track_id)
        for tid, tr in tracks.items():
            if tid not in seen_tracks:
                tr.role, tr.role_run, tr.present_run = "none", 0, 0
                if tr.under_last is not None and not tr.under_fired and t - tr.under_last <= under_gone_s + 1e-9:
                    tr.under_fired = True              # a curb / crosswalk edge went under the user and out of view
                    surface.note_evidence(t)

        # world memory: where are we, and which remembered (announced) object is each item?
        world.advance(t, dt, cadence * step_len if cadence else ego_speed, heading)
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
        speech = policy.step(t, items, tracks, surface_known)
        if speech:
            events.append(speech)

        beeping = [it for it in items if it.role == "danger" and it.collision and it.settled
                   and it.role_run >= policy.confirm and it.steps <= config["tones"].get("maxSteps", roles["dangerSteps"])]
        frame_collision.append((min(beeping, key=lambda it: it.steps) if beeping else None,
                                {it.track_id for it in items}))

        speed_known = ego_speed is not None
        frames_out.append({
            "index": i, "t": round(t, 4),
            "horizonY": round(horizon, 4), "horizonEstimated": raw is not None,
            "region": None if region is None else {"surface": region.group, "label": region.label,
                                                   "rows": _region_rows(region)},
            "lane": _lane_polygon(geo, lane_half, roles["dangerSteps"] * step_len),
            "ego": {"speedMps": _r(ego_speed, 2), "cadenceHz": _r(cadence, 2), "stepLengthM": round(step_len, 2),
                    "headingDeg": _r(heading, 1),
                    "depthAnchor": _r(a_now, 4),
                    "depthAnchorMode": anchor_mode,
                    "depthPitchDeg": _r(anchor.pitch_deg, 1) if plane else None,
                    "depthCameraHeightUnits": _r(anchor.height_units, 4) if plane else None,
                    "depthGaitCheck": _r(gait_check.value, 3) if plane else None,
                    "depthScale": (None if depth_maps is None or ds is None else _r(ds * a_now, 4) if relative else ds),
                    "depthScaleSource": "none" if depth_maps is None or ds is None else depth_scale_source,
                    "depthLevel": None if not relative or ds is None else _r(ds, 4),
                    "depthLevelSource": None if not relative or ds is None else c_source,
                    "scale": round(scale.value, 3), "scaleSource": "gait" if scale.from_gait else "prior" if scale.k is not None else "none",
                    "estimated": {"speed": speed_known, "cadence": cadence is not None,
                                  "stepLength": False}},
            "pathChange": bool(path_change),
            "hazards": [_hazard_json(it, gh, gw) for it in sorted(items, key=lambda it: it.steps)],
        })

    tone_events, episodes = _tone_events(frame_collision, times, config["tones"])
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
    return hazards_doc, {"version": version, "events": events}
