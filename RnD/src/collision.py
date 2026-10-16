"""Collision context, hazards and audio warning events from class grids (v26.1.5).

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


def load_config(path: Path | None = None) -> dict:
    path = path or (find_common_dir() / "config" / "collision.json")
    with open(path) as f:
        return json.load(f)


def resolve_settings(config: dict, mount: str | None = None, hfov_deg: float | None = None,
                     camera_height_m: float | None = None,
                     step_length_m: float | None = None) -> CollisionSettings:
    """Explicit values win over the mount preset; None falls back to defaults."""
    mount = mount or config["defaultMount"]
    if mount not in config["mountPresets"]:
        _warn_once(f"unknown mount '{mount}', using '{config['defaultMount']}'")
        mount = config["defaultMount"]
    preset = config["mountPresets"][mount]
    return CollisionSettings(
        mount=mount,
        hfov_deg=float(config["defaultHfovDeg"] if hfov_deg is None else hfov_deg),
        camera_height_m=float(preset["cameraHeightM"] if camera_height_m is None else camera_height_m),
        step_length_m=None if step_length_m is None else float(step_length_m),
        horizon_default=float(preset["horizon"]))


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def bearing_deg(x_norm: float, hfov_deg: float) -> float:
    """Pinhole model: atan((x - 0.5) * 2 * tan(hfov / 2)); positive = right."""
    t = math.tan(math.radians(hfov_deg) / 2.0)
    return math.degrees(math.atan((x_norm - 0.5) * 2.0 * t))


def clock_from_bearing(bearing: float) -> int:
    """12 + round(bearing / 30), clamped to +-90 deg, as 9..12 and 1..3."""
    b = max(-90.0, min(90.0, bearing))
    k = int(math.floor(b / 30.0 + 0.5))
    if k == 0:
        return 12
    return 12 + k if k < 0 else k


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
        names=list(class_names))


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
    below: np.ndarray                         # (H,) rows whose bottom edge is below the horizon
    lane: np.ndarray                          # (H, W) danger lane
    lane_region: np.ndarray                   # lane within the dilated walking region
    region_dilated: np.ndarray                # (H, W)
    floor_below: np.ndarray                   # (H, W) True where the pixel below is walking region


def _frame_geometry(gh: int, gw: int, horizon: float, camera_height_m: float, f: float, hfov_deg: float,
                    lane_half_m: float, region: Region | None, margin_px: int) -> _FrameGeo:
    rows_bottom = (np.arange(gh) + 1.0) / gh
    below = rows_bottom > horizon + 1e-9
    # half width of the lane in px at each row = lane_half * f / distance
    half_px = np.where(below, lane_half_m * (rows_bottom - horizon) * gh / camera_height_m, -1.0)
    col_c = np.arange(gw) + 0.5 - gw / 2.0
    lane = np.abs(col_c)[None, :] <= half_px[:, None]
    if region is not None:
        dil = ndimage.binary_dilation(region.mask, structure=ndimage.generate_binary_structure(2, 1),
                                      iterations=max(1, margin_px)) if margin_px > 0 else region.mask
    else:
        dil = np.zeros((gh, gw), dtype=bool)
    floor = np.zeros((gh, gw), dtype=bool)
    if region is not None:
        floor[:-1] = region.mask[1:]
    return _FrameGeo(gh, gw, f, horizon, camera_height_m, hfov_deg, below, lane, lane & dil, dil, floor)


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
                bearing = bearing_deg(x, geo.hfov_deg)
                items.append(_Item(
                    group=group, class_name=ids.names[cid],
                    bbox=[cc.min() / gw, rr.min() / gh, (cc.max() + 1) / gw, (rr.max() + 1) / gh],
                    contact_y=contact_y, distance_m=dist, lateral_m=lateral_m(x, dist, gw, geo.f),
                    bearing=bearing, clock=clock_from_bearing(bearing), pan=_pan_from_bearing(bearing),
                    area_frac=rr.size / (gh * gw), clipped=bool(rr.max() == gh - 1),
                    touches=bool(inreg.any()), lane_hit=lane_hit,
                    along_path=along, lane_cover=cover, contact_y_raw=contact_y,
                    area_m2=rr.size * (dist / geo.f) ** 2))
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
    # confirmation: consecutive analysed frames holding the same role (v26.1.5)
    role: str = "none"
    role_run: int = 0


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
    step_est: float | None = None
    cadence: float | None = None
    heading: float | None = None
    ref_heading: float | None = None
    exceed_since: float | None = None
    step_is_estimated: bool = False

    def update_speed(self, closings: list[float], t: float, cfg: dict) -> None:
        if len(closings) >= cfg["speedMinTracks"]:
            v = float(np.median(closings))
            self.speed = v if self.speed is None else (1 - cfg["speedEma"]) * self.speed + cfg["speedEma"] * v
            self.speed_t = t
        elif self.speed is not None and t - self.speed_t > 5.0:
            self.speed = None                  # stale: do not judge parked-vs-moving on it

    def step_length(self, settings: CollisionSettings, cfg: dict, default: float) -> float:
        if settings.step_length_m is not None:
            self.step_is_estimated = False
            return settings.step_length_m
        if self.speed is not None and self.cadence:
            lo, hi = cfg["stepLengthRangeM"]
            v = self.speed / self.cadence
            if lo <= v <= hi:                      # an implausible ratio is dropped, not clamped:
                self.step_est = v if self.step_est is None else 0.7 * self.step_est + 0.3 * v   # a clamp would pin 0.3
        if self.step_est is not None:
            self.step_is_estimated = True
            return self.step_est
        self.step_is_estimated = False
        return default

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


class _SurfaceTracker:
    """Debounced surface group: a change must persist ``debounceSeconds``."""

    def __init__(self, debounce_s: float):
        self.debounce_s = debounce_s
        self.stable: str | None = None
        self._cand: str | None = None
        self._since = 0.0

    def update(self, t: float, group: str | None) -> tuple[str | None, str] | None:
        """Returns (old, new) when a new group is adopted (old is None for the first), else None.

        Starting up, a surface is only adopted once it has persisted ``debounceSeconds`` too:
        the first frame's seed box is as likely to straddle a lane edge as any other.
        """
        if group is None:
            self._cand = None
            return None
        if group == self.stable:
            self._cand = None
            return None
        if self._cand != group:
            self._cand, self._since = group, t
        if t - self._since >= self.debounce_s - 1e-9:
            old, self.stable, self._cand = self.stable, group, None
            return old, group
        return None


# --------------------------------------------------------------------------
# Steps and roles
# --------------------------------------------------------------------------

def steps_to(distance_m: float, ego_speed: float | None, cadence: float | None, step_length_m: float) -> float:
    """Steps until we reach the item: ``distance * cadence / speed``, else ``distance / step length``.

    Distance and ego speed are both proportional to the assumed camera height,
    so the first form is height independent. It is a *proximity* measure ("ten
    of your steps away"), deliberately not a per-object time to contact: the
    per-object closing speed is too noisy near the horizon to trust for that.
    """
    if ego_speed is not None and ego_speed >= 0.3 and cadence:
        return distance_m * cadence / ego_speed
    return distance_m / step_length_m


def _speed_witness(it: _Item) -> bool:
    """Can this item tell us our own speed? Only something that stands on the ground at a point:
    a pole, sign or lamp (tall and thin). The contact row of a wall, hedge or building is where the
    segmentation happens to end, so its "closing" is mostly zero or random and would drag the median."""
    if it.group != "static" or it.closing is None or it.clipped or it.along_path:
        return False
    w, h = it.bbox[2] - it.bbox[0], it.bbox[3] - it.bbox[1]
    return h >= POINT_ASPECT * w


POINT_ASPECT = 3.0   # bbox height / width (normalised units, ~1.7 in pixels) of a pole-like item


def _is_static_like(it: _Item) -> bool:
    """Unknown movers (moving None) count as static: they never become "approaching"."""
    return it.group == "static" or (it.group == "moving" and it.moving is not True)


def _not_approaching(it: _Item, ego_speed: float | None) -> bool:
    """A ground object we walk towards closes at our speed. One whose contact row stays put while we
    move is the end of a line running along the path (a median cut into pieces), not an obstacle."""
    return (it.closing is not None and ego_speed is not None and ego_speed >= 0.5
            and it.closing < 0.3 * ego_speed)


def _assign_role(it: _Item, span: tuple[float, float] | None, roles: dict, lane_half_m: float) -> None:
    danger_steps, final_steps = roles["dangerSteps"], roles["finalSteps"]
    it.role, it.urgency = "none", "none"
    big_enough = it.area_m2 >= roles.get("minObstacleAreaM2", 0.0)   # a 15 px blip 4 m away is segmentation noise
    if _is_static_like(it):
        if big_enough and it.lane_hit and not it.along_path and it.steps <= danger_steps:
            it.role = "danger"
        elif (it.touches and it.distance_m <= roles["contextMaxDistanceM"]
              and it.area_frac >= roles.get("contextMinAreaFraction", 0.0)):
            it.role = "context"
    elif it.group == "moving":
        in_span = span is not None and span[0] <= it.contact_y <= span[1] + 1e-9
        if (big_enough and in_span and abs(it.lateral_m) <= lane_half_m + 1.0
                and (it.approaching or abs(it.lateral_m) <= lane_half_m)
                and it.steps <= danger_steps):
            it.role = "danger"
    elif it.group == "feature":
        # a feature must cross the lane; a curb or median running along the path is boundary.
        # One already under our feet (touching the bottom edge) is not "ahead".
        if (it.lane_hit and not it.along_path and not it.clipped
                and it.lane_cover >= roles["featureMinLaneCover"] and it.steps <= roles["featureSteps"]):
            it.role = "feature"
    if it.role == "danger":
        it.urgency = "final" if it.steps <= final_steps else "danger"


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
        self.last_t: float | None = None
        self.memory: dict[str, float] = {}                      # context label (family) -> last seen
        self.pending_since: dict[str, float] = {}               # context waiting for the gap
        self.feature_label_t: dict[str, float] = {}
        self.danger_label_t: dict[str, float] = {}
        self.surface_pending: tuple[str, str] | None = None   # (group, label) waiting to be spoken
        self.context_speak = set(config.get("contextSpeak", []))
        # start summary: the first context phrase of a run (and after a path change) needs only
        # ``confirmFrames`` frames, no track age and no adopted surface, so it comes within ~1 s
        self.summary = True
        self.summary_since: float | None = None

    # -- memory ----------------------------------------------------------
    def clear_context(self, t: float | None = None) -> None:
        """Forget what was said (a turn): the next context phrase is a fresh summary of the new view."""
        self.memory.clear()
        self.pending_since.clear()
        self.summary, self.summary_since = True, t

    @staticmethod
    def _key(it: _Item) -> str:
        """Memory key: the item's label family ("vehicle" and "parked car" are one thing), not its side."""
        return it.family or it.label

    def _known(self, key: str) -> bool:
        return key in self.memory

    def observe_context(self, t: float, keys: set[str]) -> None:
        """Refresh memory for labels seen now; forget labels unseen for forgetAfterSeconds."""
        for k in keys:
            if k in self.memory:
                self.memory[k] = t
        for k in [k for k, seen in self.memory.items() if t - seen > self.forget_s]:
            del self.memory[k]

    def surface_adopted(self, old: str | None, new: str, surfaces: dict) -> None:
        """A debounced surface change. Only road/rail matter: those are where the user must be told
        (starting on one, or moving into or out of one). Sidewalk <-> bike lane relabels stay silent."""
        announce = set(surfaces.get("announceGroups", []))
        if new in announce or (old is not None and old in announce):
            self.surface_pending = (new, surfaces["groups"][new]["label"])

    # -- phrases ---------------------------------------------------------
    @staticmethod
    def _n(steps: float) -> int:
        return max(1, int(round(steps)))

    def _text(self, template: str, it: _Item | None = None, label: str = "") -> str:
        tpl = self.cfg["templates"][template]
        if it is None:
            return tpl.format(label=label)
        text = tpl.format(label=it.label, clock=it.clock, steps=self._n(it.steps))
        return text.replace(" 1 steps", " 1 step")

    def _gap_ok(self, t: float) -> bool:
        return self.last_t is None or t - self.last_t >= self.cfg["globalMinGapSeconds"] - 1e-9

    def _event(self, t: float, role: str, text: str, it: _Item | None, urgency: str = "none") -> dict:
        self.last_t = t
        return {"t": round(t, 4), "type": "speech", "role": role, "text": text,
                "trackId": None if it is None else it.track_id, "urgency": urgency,
                "clock": None if it is None else it.clock, "pan": 0.0 if it is None else round(it.pan, 4)}

    def step(self, t: float, items: list[_Item], tracks: dict[int, _Track],
             surface_known: bool = True) -> dict | None:
        """``surface_known``: a surface has been adopted (context waits for it)."""
        if self.summary_since is None:
            self.summary_since = t
        if self.summary and t - self.summary_since > WARMUP_S + 1e-9 and surface_known:
            self.summary = False                # the scene had its chance to be summarised; back to normal
        everything = items
        items = [i for i in items if i.settled]
        ok = lambda i: i.role_run >= self.confirm          # noqa: E731  (confirmed over consecutive frames)
        danger = sorted((i for i in items if i.role == "danger" and ok(i)), key=lambda i: i.steps)
        # 1. final: once per track, ignores the global gap
        for it in danger:
            tr = tracks[it.track_id]
            if it.urgency == "final" and not tr.final_done:
                tr.final_done = tr.danger_done = True
                self.memory_if_spoken(t, it)
                return self._event(t, "final", self._text("final", it), it, "final")
        # 2. danger
        pending = [i for i in danger if not tracks[i.track_id].danger_done
                   and t - self.danger_label_t.get(i.label, -math.inf) >= self.LABEL_COOLDOWN_S]
        if pending:
            if not self._gap_ok(t):
                return None
            it = pending[0]
            tracks[it.track_id].danger_done = True
            self.danger_label_t[it.label] = t
            self.memory_if_spoken(t, it)
            if it.approaching:
                return self._event(t, "danger", self._text("approach", it), it, "danger")
            return self._event(t, "danger", self._text("danger", it), it, "danger")
        # 3. feature
        feats = sorted((i for i in items if i.role == "feature" and ok(i) and not tracks[i.track_id].feature_done
                        and t - self.feature_label_t.get(i.label, -math.inf) >= self.LABEL_COOLDOWN_S),
                       key=lambda i: i.steps)
        if feats:
            if not self._gap_ok(t):
                return None
            it = feats[0]
            tracks[it.track_id].feature_done = True
            self.feature_label_t[it.label] = t
            return self._event(t, "feature", self._text("feature", it), it)
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
        elif surface_known:
            pool = items
        else:
            return None
        cands: dict[str, _Item] = {}                 # one per label, the nearest
        for it in pool:
            if it.role == "context" and it.label in self.context_speak:
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
        self.summary = False
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

def _tone_params(steps: float, by_steps: list[list[float]]) -> tuple[float, float]:
    """(intervalSeconds, frequencyHz) linearly interpolated by steps, clamped to the table ends."""
    table = sorted(by_steps, key=lambda r: r[0])
    xs = [r[0] for r in table]
    return (float(np.interp(steps, xs, [r[1] for r in table])),
            float(np.interp(steps, xs, [r[2] for r in table])))


def _tone_events(frame_danger: list[_Item | None], times: np.ndarray, tones_cfg: dict) -> list[dict]:
    """One phase-continuous beep stream driven by the nearest danger item of each frame."""
    last_dt = float(np.median(np.diff(times))) if len(times) > 1 else 1.0
    events: list[dict] = []
    next_due = -math.inf
    last_beep = -math.inf
    for i, top in enumerate(frame_danger):
        if top is None:
            continue
        t0 = float(times[i])
        t1 = float(times[i + 1]) if i + 1 < len(times) else t0 + last_dt
        interval, freq = _tone_params(top.steps, tones_cfg["bySteps"])
        # a faster stream must not wait out the previous slower interval
        due = max(t0, min(next_due, last_beep + interval))
        while due < t1 - 1e-9:
            events.append({"t": round(due, 4), "type": "tone", "role": "danger", "trackId": top.track_id,
                           "urgency": top.urgency, "pan": round(top.pan, 4), "frequencyHz": round(freq, 1),
                           "durationSeconds": tones_cfg["durationSeconds"]})
            last_beep = due
            due += interval
        next_due = due
    return events


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

def _lane_polygon(geo: _FrameGeo, lane_half_m: float, far_distance_m: float) -> list[list[float]]:
    def half(y: float) -> float:
        return lane_half_m * (y - geo.horizon) * geo.gh / geo.camera_height_m / geo.gw

    y_far = min(1.0, geo.horizon + geo.camera_height_m * geo.f / (far_distance_m * geo.gh))
    y_far = max(y_far, geo.horizon)

    def cl(x: float) -> float:
        return round(min(1.0, max(0.0, x)), 4)

    return [[cl(0.5 - half(1.0)), 1.0], [cl(0.5 + half(1.0)), 1.0],
            [cl(0.5 + half(y_far)), round(y_far, 4)], [cl(0.5 - half(y_far)), round(y_far, 4)]]


def _region_rows(region: Region | None, step: int = 4) -> list[list[float]]:
    if region is None:
        return []
    gh = len(region.left)
    return [[round((r + 0.5) / gh, 3), round(float(region.left[r]), 3), round(float(region.right[r]), 3)]
            for r in range(gh - 1, -1, -step) if not np.isnan(region.left[r])]


def _r(v: float | None, nd: int) -> float | None:
    return None if v is None else round(float(v), nd)


def _hazard_json(it: _Item) -> dict:
    return {"trackId": it.track_id, "className": it.class_name, "group": it.group, "label": it.label,
            "role": it.role, "moving": it.moving if it.group == "moving" else False,
            "bbox": [round(v, 4) for v in it.bbox], "contactY": round(it.contact_y, 4),
            "bearingDeg": round(it.bearing, 2), "clock": it.clock, "pan": round(it.pan, 4),
            "distanceM": round(it.distance_m, 2), "lateralM": round(it.lateral_m, 2),
            "stepsTo": round(it.steps, 1), "closingMps": _r(it.closing, 2),
            "urgency": it.urgency, "areaFrac": round(it.area_frac, 5)}


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


def run_collision(grids, times, class_names, config, settings, motion=None) -> tuple[dict, dict]:
    """Per-frame hazards and the speech/tone event list. ``motion`` = {"t","dx","dy"} arrays or None."""
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
    ego_cfg = config["ego"]

    mser = _motion_series(motion, settings.hfov_deg, ego_cfg)
    ego = _Ego()
    surface = _SurfaceTracker(config["surfaces"]["debounceSeconds"])
    policy = SpeechPolicy(config)
    tracks: dict[int, _Track] = {}
    next_id = 1
    prev_group: str | None = None
    prev_left = prev_right = None
    horizon = settings.horizon_default
    raws: list[float] = []
    last_estimate_t = -math.inf
    first_t: float | None = None
    frames_out: list[dict] = []
    frame_danger: list[_Item | None] = []
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
            policy.surface_adopted(*adopted, config["surfaces"])
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

        # 3. items
        geo = _frame_geometry(gh, gw, horizon, settings.camera_height_m, f, settings.hfov_deg, lane_half,
                              region, roles["boundaryMarginPx"])
        items = detect_items(grid, ids, geo, config)

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
            tr.closing = _closing_mps(tr.history, horizon, settings.camera_height_m, gh, f,
                                      trk["motionMinRowsBelowHorizon"], trk["motionMinSeconds"])
            it.track_id, it.closing = tid, tr.closing
            it.settled = t - tr.first_t >= MIN_TRACK_AGE_S - 1e-9

        # 5. ego
        cadence = heading = None
        if mser is not None:
            mt, cad, hcum = mser
            j = int(np.clip(np.searchsorted(mt, t), 0, len(mt) - 1))
            if j > 0 and abs(mt[j - 1] - t) < abs(mt[j] - t):
                j -= 1
            cadence = None if np.isnan(cad[j]) else float(cad[j])
            heading = float(np.interp(t, mt, hcum))
        ego.cadence = cadence
        ego.update_speed([it.closing for it in items
                          if _speed_witness(it) and 0.0 <= it.closing <= ego_cfg["speedMaxMps"]], t, ego_cfg)
        step_len = ego.step_length(settings, ego_cfg, default_step)
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
            if it.group == "static" or it.group == "feature":
                it.moving = False
            elif it.closing is not None and ego.speed is not None:
                ground = it.closing - ego.speed
                limit = roles["stationaryMps"] * (1.5 if tr.moving is False else 1.0)   # hysteresis
                it.moving = abs(ground) >= limit
                it.approaching = it.moving and ground > roles["approachingMps"]
            tr.moving = it.moving
            it.steps = steps_to(it.distance_m, ego.speed, cadence, step_len)
            base = labels.get(it.class_name, it.class_name.replace("-", " "))
            it.family = base
            it.label = parked_labels.get(it.class_name, base) if (it.group == "moving" and it.moving is False) else base
            if _not_approaching(it, ego.speed) and it.group != "moving":
                it.along_path = True
            _assign_role(it, span, roles, lane_half)
            if not warm and it.role in ("danger", "feature"):
                it.role, it.urgency = "none", "none"   # distances are meaningless on a guessed horizon

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
                tr.role, tr.role_run = "none", 0

        # 9. path change
        path_change = turned or (config["pathChange"]["onSurfaceChange"] and adopted is not None
                                 and adopted[0] is not None)
        if path_change:
            policy.clear_context(t)
            _log(f"t={t:.1f}s path change ({'turn' if turned else 'surface'}); context memory cleared")
        policy.observe_context(t, {it.family or it.label for it in items
                                   if it.role in ("context", "danger") and _is_static_like(it)})

        # speech
        speech = policy.step(t, items, tracks, surface.stable is not None)
        if speech:
            events.append(speech)

        danger = [it for it in items if it.role == "danger" and it.settled]
        frame_danger.append(min(danger, key=lambda it: it.steps) if danger else None)

        speed_known = ego.speed is not None
        frames_out.append({
            "index": i, "t": round(t, 4),
            "horizonY": round(horizon, 4), "horizonEstimated": raw is not None,
            "region": None if region is None else {"surface": region.group, "label": region.label,
                                                   "rows": _region_rows(region)},
            "lane": _lane_polygon(geo, lane_half, roles["dangerSteps"] * step_len),
            "ego": {"speedMps": _r(ego.speed, 2), "cadenceHz": _r(cadence, 2), "stepLengthM": round(step_len, 2),
                    "headingDeg": _r(heading, 1),
                    "estimated": {"speed": speed_known, "cadence": cadence is not None,
                                  "stepLength": ego.step_is_estimated}},
            "pathChange": bool(path_change),
            "hazards": [_hazard_json(it) for it in sorted(items, key=lambda it: it.steps)],
        })

    events.extend(_tone_events(frame_danger, times, config["tones"]))
    events.sort(key=lambda e: (e["t"], e["type"] != "speech"))
    version = config["version"]
    hazards_doc = {
        "version": version,
        "settings": {"mount": settings.mount, "hfovDeg": settings.hfov_deg,
                     "cameraHeightM": settings.camera_height_m, "stepLengthM": settings.step_length_m,
                     "laneHalfWidthM": lane_half},
        "gridW": gw, "gridH": gh, "egoAvailable": mser is not None, "frames": frames_out,
    }
    return hazards_doc, {"version": version, "events": events}
