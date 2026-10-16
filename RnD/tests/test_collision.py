"""Synthetic-grid tests for collision.py v26.1.1 (no model, no GPU).

The scenes use real geometry: a camera at height H, horizon row ``HV``, a
walking surface that is a perspective trapezoid converging to the vanishing
point, and objects placed so that their contact row corresponds to a chosen
ground distance (the inverse of ``ground_distance_m``).
"""

from __future__ import annotations

import copy
import json
import math

import numpy as np
import pytest

import collision as col
from common_paths import find_common_dir

W, H = 240, 135
HFOV = 118.0
F = col.focal_px(W, HFOV)
HV = 0.45                                    # true horizon (normalised y); equals the chest preset
HC = 1.3                                     # true camera height
FPS = 10.0

_MAPPING = json.load(open(find_common_dir() / "config" / "safety_mapping_hackeye48.json"))
NAMES = [c["name"] for c in sorted(_MAPPING["classes"], key=lambda c: c["id"])]
ID = {n: i for i, n in enumerate(NAMES)}

CONFIG = col.load_config()
SETTINGS = col.resolve_settings(CONFIG, "chest", HFOV, None, None)


# --------------------------------------------------------------------------
# Scene helpers
# --------------------------------------------------------------------------

def row_for(d: float, hv: float = HV, hc: float = HC) -> float:
    """Bottom-edge row (float) of a ground point at distance ``d`` (inverse of ground_distance_m)."""
    return hv * H + hc * F / d


def dist_at_row(bottom: int, hv: float = HV, hc: float = HC) -> float:
    return col.ground_distance_m(bottom / H, hv, hc, H, F)


def base_grid(surface: str = "flat sidewalk", half_w_m: float = 2.0, hv: float = HV, hc: float = HC,
              outside: str = "terrain") -> np.ndarray:
    """Sky above the horizon; below it a perspective trapezoid of ``surface``, ``outside`` around it."""
    g = np.full((H, W), ID["nature sky"], dtype=np.uint8)
    for r in range(H):
        y = (r + 1) / H
        if y <= hv:
            continue
        half = half_w_m * (y - hv) * H / hc            # px = half_w * f / d
        g[r, :] = ID[outside]
        c0, c1 = int(math.ceil(W / 2 - half)), int(math.floor(W / 2 + half))
        g[r, max(0, c0):min(W, c1 + 1)] = ID[surface]
    return g


def place(g: np.ndarray, cls: str, d: float, lat: float, w_m: float, h_m: float,
          hv: float = HV, hc: float = HC) -> None:
    """Paint a ``w_m`` x ``h_m`` object standing on the ground at distance ``d``, lateral ``lat``."""
    bottom = int(round(row_for(d, hv, hc)))
    if bottom <= int(hv * H) + 1 or bottom - 1 >= H + 40:
        return
    top = bottom - max(1, int(round(h_m * F / d)))
    wpx = max(1, int(round(w_m * F / d)))
    cx = W / 2 + lat * F / d
    x0 = int(round(cx - wpx / 2))
    g[max(0, top):min(H, bottom), max(0, x0):max(0, min(W, x0 + wpx))] = ID[cls]


def add_wall(g: np.ndarray, d_far: float = 7.0, d_near: float = 2.5, inner_m: float = 2.0,
             thick_m: float = 0.6, cut_rows: tuple[int, ...] = ()) -> None:
    """A wall strip just outside the region's right edge between two distances."""
    for r in range(int(row_for(d_far)), int(row_for(d_near))):
        if r in cut_rows:
            continue
        d = dist_at_row(r + 1)
        c0 = int(W / 2 + inner_m * F / d) + 1
        c1 = c0 + max(1, int(round(thick_m * F / d)))
        g[r, min(W, c0):min(W, c1)] = ID["barrier wall"]


def motion(t_end: float, fps: float = 24.0, cadence: float = 1.8, turn: tuple[float, float, float] | None = None,
           seed: int = 0) -> dict:
    """dy = A sin(2 pi f t) + noise; dx per-sample (zero, or a ramp: turn = (t0, t1, degrees right))."""
    rng = np.random.RandomState(seed)
    t = np.arange(0, t_end, 1 / fps)
    dy = 0.01 * np.sin(2 * math.pi * cadence * t) + 0.003 * rng.randn(len(t))
    dx = np.zeros(len(t))
    if turn:
        t0, t1, deg = turn
        ramp = (t >= t0) & (t < t1)
        dx[ramp] = -(deg / HFOV) / ramp.sum()
    return {"t": t, "dx": dx, "dy": dy}


def run(frames, fps=FPS, mot=None, settings=SETTINGS, config=CONFIG):
    grids = np.stack(frames)
    times = np.arange(len(frames)) / fps
    return col.run_collision(grids, times, NAMES, config, settings, mot)


def speech(events, role=None):
    out = [e for e in events["events"] if e["type"] == "speech"]
    return [e for e in out if role is None or e["role"] == role]


def tones(events):
    return [e for e in events["events"] if e["type"] == "tone"]


def hz(doc, class_name):
    """Per-frame (t, hazard) pairs of one class."""
    return [(f["t"], h) for f in doc["frames"] for h in f["hazards"] if h["className"] == class_name]


SPEED = 1.4


def approach_frames(cls="pole", lat=0.0, d0=22.0, seconds=14.0, fps=FPS, w=0.6, h=3.0, half_w=2.0,
                    speed=SPEED, extra=None):
    """The object comes towards us at ``speed`` m/s (we walk, it is static)."""
    base = base_grid(half_w_m=half_w)
    frames = []
    for i in range(int(seconds * fps)):
        g = base.copy()
        place(g, cls, d0 - speed * i / fps, lat, w, h)
        if extra:
            extra(g, i / fps)
        frames.append(g)
    return frames


# --------------------------------------------------------------------------
# 1. Distance / lateral / steps independence from camera height
# --------------------------------------------------------------------------

def test_ground_distance_and_lateral_closed_form():
    f = col.focal_px(240, 118)
    assert f == pytest.approx(120 / math.tan(math.radians(59)))
    d = col.ground_distance_m(0.70, 0.45, 1.3, 135, f)
    assert d == pytest.approx(1.3 * f / (0.25 * 135))
    assert col.ground_distance_m(0.45, 0.45, 1.3, 135, f) is None
    assert col.ground_distance_m(0.30, 0.45, 1.3, 135, f) is None
    assert col.lateral_m(0.75, d, 240, f) == pytest.approx(0.25 * 240 * d / f)
    assert col.lateral_m(0.5, d, 240, f) == 0.0
    # round trip through the scene helper
    assert dist_at_row(int(round(row_for(8.0)))) == pytest.approx(8.0, rel=0.1)


def test_steps_for_approached_pole_independent_of_camera_height():
    frames = approach_frames(seconds=13)
    mot = motion(13)
    docs = []
    for h in (1.3, 1.7):
        s = col.resolve_settings(CONFIG, "chest", HFOV, h, None)
        docs.append(run(frames, mot=mot, settings=s)[0])
    a, b = hz(docs[0], "pole"), hz(docs[1], "pole")
    assert a and len(a) == len(b)
    compared = 0
    for (ta, ha), (tb, hb) in zip(a, b):
        assert ta == tb
        fa = next(fr for fr in docs[0]["frames"] if fr["t"] == ta)["ego"]
        fb = next(fr for fr in docs[1]["frames"] if fr["t"] == ta)["ego"]
        if fa["cadenceHz"] and fa["speedMps"] and fa["speedMps"] >= 0.3 and fb["speedMps"] >= 0.3:
            # steps = distance * cadence / ego speed: height cancels, metres do not
            assert ha["stepsTo"] == pytest.approx(ha["distanceM"] * fa["cadenceHz"] / fa["speedMps"], rel=0.03)
            assert ha["stepsTo"] == pytest.approx(hb["stepsTo"], abs=0.5)
            assert hb["distanceM"] > ha["distanceM"] * 1.2
            compared += 1
    assert compared > 20


# --------------------------------------------------------------------------
# 2. Cadence
# --------------------------------------------------------------------------

def _cadence(sig, t, dx=None):
    e = CONFIG["ego"]
    return col.estimate_cadence(t, sig, e["cadenceWindowSeconds"], e["cadenceBandHz"], e["cadenceMinPeakRatio"],
                                dx=dx, min_step_hz=e["minStepHz"], harmonic_ratio=e["harmonicMinRatio"])


def test_cadence_recovers_steady_walk():
    t = np.arange(0, 30, 1 / 24)
    rng = np.random.RandomState(1)
    dy = 0.01 * np.sin(2 * math.pi * 1.8 * t) + 0.006 * rng.randn(len(t))
    c = _cadence(dy, t)
    ok = c[t > 6]
    assert np.mean(~np.isnan(ok)) > 0.9
    assert np.nanmedian(ok) == pytest.approx(1.8, abs=0.1)


def test_cadence_nan_for_pure_noise():
    t = np.arange(0, 60, 1 / 24)
    rng = np.random.RandomState(2)
    c = _cadence(rng.randn(len(t)), t, dx=rng.randn(len(t)))
    assert np.mean(np.isnan(c)) > 0.9


def test_cadence_is_stride_aware():
    t = np.arange(0, 30, 1 / 24)
    rng = np.random.RandomState(3)
    stride = np.sin(2 * math.pi * 1.05 * t) + 0.4 * np.sin(2 * math.pi * 2.1 * t) + 0.15 * rng.randn(len(t))
    assert np.nanmedian(_cadence(stride, t)[t > 6]) == pytest.approx(2.1, abs=0.1)
    # a lone 1.5 Hz peak is above minStepHz and has no harmonic: it is the step rate
    lone = np.sin(2 * math.pi * 1.5 * t) + 0.1 * rng.randn(len(t))
    assert np.nanmedian(_cadence(lone, t)[t > 6]) == pytest.approx(1.5, abs=0.1)
    run_ = np.sin(2 * math.pi * 2.8 * t) + 0.15 * rng.randn(len(t))
    assert np.nanmedian(_cadence(run_, t)[t > 6]) == pytest.approx(2.8, abs=0.1)
    # a stride-only dy at 1.6 Hz (above minStepHz) is doubled when dx sways at the same rhythm
    dx = np.sin(2 * math.pi * 1.6 * t + 1.0) + 0.1 * rng.randn(len(t))
    slow = np.sin(2 * math.pi * 1.6 * t) + 0.1 * rng.randn(len(t))
    assert np.nanmedian(_cadence(slow, t)[t > 6]) == pytest.approx(1.6, abs=0.1)
    assert np.nanmedian(_cadence(slow, t, dx=dx)[t > 6]) == pytest.approx(3.2, abs=0.15)


# --------------------------------------------------------------------------
# 3. Horizon
# --------------------------------------------------------------------------

@pytest.mark.parametrize("hv", [0.40, 0.45, 0.52])
def test_horizon_from_converging_path(hv):
    g = base_grid(hv=hv)
    ids = col.resolve_class_ids(CONFIG, NAMES)
    reg = col.walking_region(g, ids, CONFIG)
    assert reg is not None and reg.label == "sidewalk"
    est = col.estimate_horizon(reg.left, reg.right, CONFIG)
    assert est == pytest.approx(hv, abs=0.03)


def test_horizon_falls_back_to_preset_for_full_width_blob():
    g = np.full((H, W), ID["flat sidewalk"], dtype=np.uint8)
    g[: int(0.45 * H)] = ID["nature sky"]
    ids = col.resolve_class_ids(CONFIG, NAMES)
    reg = col.walking_region(g, ids, CONFIG)
    assert col.estimate_horizon(reg.left, reg.right, CONFIG) is None
    doc, _ = run([g] * 12)
    assert all(not f["horizonEstimated"] for f in doc["frames"])
    assert all(f["horizonY"] == pytest.approx(SETTINGS.horizon_default) for f in doc["frames"])


def test_region_picks_majority_group_and_none_without_surface():
    ids = col.resolve_class_ids(CONFIG, NAMES)
    g = base_grid("flat bike-lane")
    reg = col.walking_region(g, ids, CONFIG)
    assert reg.group == "bikeLane" and reg.label == "bike lane"
    assert col.walking_region(np.full((H, W), ID["nature sky"], dtype=np.uint8), ids, CONFIG) is None
    doc, ev = run([np.full((H, W), ID["nature sky"], dtype=np.uint8)] * 5)
    assert all(f["region"] is None for f in doc["frames"]) and not speech(ev)


# --------------------------------------------------------------------------
# 4 / 5. Context: a wall alongside the path
# --------------------------------------------------------------------------

def _wall_frames(seconds, fps=FPS, present=lambda t: True, fragment=True, seed=5):
    rng = np.random.RandomState(seed)
    base = base_grid(half_w_m=2.0)
    frames = []
    for i in range(int(seconds * fps)):
        t = i / fps
        g = base.copy()
        if present(t) and not (fragment and rng.rand() < 0.15):          # 15 percent of frames: wall missing
            cuts = tuple(int(r) for r in rng.randint(int(row_for(7.0)), int(row_for(3.2)), 2)) if fragment else ()
            add_wall(g, cut_rows=cuts)
        frames.append(g)
    return frames


def test_wall_alongside_is_context_spoken_once():
    doc, ev = run(_wall_frames(20))
    walls = hz(doc, "barrier wall")
    assert len(walls) > 100
    assert all(h["role"] in ("context", "none") for _, h in walls)
    assert any(h["role"] == "context" for _, h in walls)
    assert not any(h["role"] == "danger" for _, h in walls)
    ctx = speech(ev, "context")
    assert [e["text"] for e in ctx] == ["obstacle at 1"]
    assert speech(ev, "surface") == []                      # a sidewalk is not announced
    assert speech(ev, "danger") == [] and speech(ev, "final") == [] and tones(ev) == []


def test_context_spoken_again_after_a_turn():
    doc, ev = run(_wall_frames(24), mot=motion(24, turn=(8.0, 11.0, 40.0)))
    walls = [e for e in speech(ev, "context") if e["text"].startswith("obstacle")]
    assert len(walls) == 2
    turn_frames = [f for f in doc["frames"] if f["pathChange"]]
    assert len(turn_frames) == 1
    assert 9.5 <= turn_frames[0]["t"] <= 13.5
    assert walls[1]["t"] > turn_frames[0]["t"] - 1e-6
    assert doc["egoAvailable"] is True
    assert doc["frames"][-1]["ego"]["headingDeg"] == pytest.approx(40.0, abs=1.0)


def test_small_heading_change_is_not_a_path_change():
    doc, ev = run(_wall_frames(24), mot=motion(24, turn=(8.0, 11.0, 15.0)))
    assert not any(f["pathChange"] for f in doc["frames"])
    assert len([e for e in speech(ev, "context") if e["text"].startswith("obstacle")]) == 1


def test_context_spoken_again_after_30_seconds_unseen():
    fps = 5.0
    doc, ev = run(_wall_frames(52, fps=fps, present=lambda t: t < 8 or t >= 46, fragment=False), fps=fps)
    ctx = [e for e in speech(ev, "context") if e["text"].startswith("obstacle")]
    assert len(ctx) == 2
    assert ctx[0]["t"] < 8 and ctx[1]["t"] >= 46


def test_context_not_repeated_when_gap_shorter_than_30_seconds():
    fps = 5.0
    doc, ev = run(_wall_frames(40, fps=fps, present=lambda t: t < 8 or t >= 25, fragment=False), fps=fps)
    assert len([e for e in speech(ev, "context") if e["text"].startswith("obstacle")]) == 1


# --------------------------------------------------------------------------
# 6 / 7. Danger lane
# --------------------------------------------------------------------------

def test_pole_in_lane_danger_final_and_accelerating_tones():
    doc, ev = run(approach_frames(seconds=15), mot=motion(15))
    sp = speech(ev)
    roles = [e["role"] for e in sp]
    assert roles.count("danger") == 1 and roles.count("final") == 1
    danger = next(e for e in sp if e["role"] == "danger")
    final = next(e for e in sp if e["role"] == "final")
    n = int(danger["text"].split(", ")[2].split()[0])
    assert danger["text"].startswith("pole, 12 o'clock, ") and 8 <= n <= 10
    m = int(final["text"].split(", ")[2].split()[0])
    assert final["text"].startswith("pole, 12 o'clock, ") and 1 <= m <= 3 and final["text"].endswith("steps")
    assert final["t"] > danger["t"]
    assert final["urgency"] == "final" and danger["urgency"] == "danger"
    # tones only while it is a danger, interval shrinking as steps fall
    pole = hz(doc, "pole")
    t_danger = min(t for t, h in pole if h["role"] == "danger")
    tn = tones(ev)
    assert len(tn) >= 8 and all(e["role"] == "danger" for e in tn)
    assert min(e["t"] for e in tn) >= t_danger - 1e-6
    gaps = np.diff([e["t"] for e in tn])
    assert gaps[: len(gaps) // 3].mean() > gaps[-(len(gaps) // 3):].mean()
    freqs = [e["frequencyHz"] for e in tn]
    assert freqs[-1] > freqs[0]
    assert all(abs(e["pan"]) <= 1 for e in tn)
    assert [e["role"] for e in sp if e["role"] != "danger" and e["role"] != "final"] == []   # nothing else spoken


def test_vehicle_beside_path_with_pixels_intruding_into_lane_is_not_danger():
    """v26.1.5: a non-moving item is danger only if its contact point (lowest pixel) is in the lane."""
    def extra(g, t):
        d = 14.0 - SPEED * t
        place(g, "vehicle", d, 2.0, 1.0, 1.5)                 # stands beside the path, lowest row at lat 1.5..2.5
        place(g, "vehicle", d, 0.65, 1.9, 0.8, hc=HC - 0.5)   # an overhang higher up, joined to it, reaching into the lane
    frames = approach_frames(cls="pole", d0=500, seconds=9, half_w=3.0, extra=extra)
    doc, ev = run(frames, mot=motion(9))
    cars = hz(doc, "vehicle")
    assert any(h["stepsTo"] <= 10 and h["areaFrac"] > 0.003 for _, h in cars)      # it does get close
    assert all(h["role"] != "danger" for _, h in cars)
    assert speech(ev, "danger") == [] and speech(ev, "final") == [] and tones(ev) == []


def test_one_frame_role_flicker_is_never_spoken_two_frames_are():
    """An established pole beside the lane jumps into it for n frames (segmentation noise)."""
    def scene(n):
        frames = approach_frames(cls="pole", d0=6.0, speed=0.0, seconds=6, lat=0.9)
        for i in range(35, 35 + n):
            frames[i] = base_grid()
            place(frames[i], "pole", 6.0, 0.45, 0.4, 2.5)
        return frames
    doc, ev = run(scene(1))
    assert any(h["role"] == "danger" for _, h in hz(doc, "pole"))                  # the role itself did flicker on
    assert speech(ev, "danger") == [] and speech(ev, "final") == [] and tones(ev) != []   # (beeps are not speech)
    doc, ev = run(scene(3))
    assert [e["text"][:4] for e in speech(ev, "danger")] == ["pole"]


def test_pole_beside_the_lane_is_not_danger():
    frames = approach_frames(lat=2.0, half_w=3.0, seconds=14)
    doc, ev = run(frames, mot=motion(14))
    pole = hz(doc, "pole")
    assert any(h["stepsTo"] <= 10 for _, h in pole)            # it does get close
    assert all(h["role"] != "danger" for _, h in pole)
    assert speech(ev, "danger") == [] and speech(ev, "final") == [] and tones(ev) == []


# --------------------------------------------------------------------------
# 8. Movers
# --------------------------------------------------------------------------

def _poles_for_speed(g, t, spacing=6.0, d0=26.0):
    """Static poles at both sides (outside the region): they approach at ego speed."""
    for k in range(8):
        d = d0 - SPEED * t - k * spacing + 4
        if d > 1.8:
            place(g, "pole", d, 3.0, 0.3, 3.0)
            place(g, "pole", d + 3, -3.0, 0.3, 3.0)


def test_parked_vehicle_at_region_edge_is_context_with_parked_label():
    def extra(g, t):
        _poles_for_speed(g, t)
        place(g, "vehicle", 22.0 - SPEED * t, 2.95, 1.8, 1.5)

    frames = approach_frames(cls="pole", d0=500, seconds=13, extra=extra)
    doc, ev = run(frames, mot=motion(13))
    cars = hz(doc, "vehicle")
    parked = [h for _, h in cars if h["moving"] is False]
    assert len(parked) > 30
    assert all(h["label"] == "parked car" for h in parked)
    assert all(h["role"] in ("context", "none") for h in parked)
    ctx = [e["text"] for e in speech(ev, "context")]
    # one phrase names the car (as "vehicle" while its motion is unknown, "parked car" once judged stationary);
    # the label family is remembered, so the relabel does not repeat it
    assert len([t for t in ctx if "vehicle at" in t or "parked car at" in t]) == 1
    assert speech(ev, "danger") == [] and tones(ev) == []


def test_approaching_cyclist_in_region_is_danger_with_approach_template():
    cyc_speed = 2.5

    def extra(g, t):
        _poles_for_speed(g, t)
        place(g, "rider", 24.0 - (SPEED + cyc_speed) * t, 0.2, 0.8, 1.8)

    frames = approach_frames(cls="pole", d0=500, seconds=6, extra=extra)
    doc, ev = run(frames, mot=motion(6))
    dsp = speech(ev, "danger")
    assert len(dsp) == 1
    assert dsp[0]["text"] == "cyclist approaching, 12 o'clock"
    rider = [h for _, h in hz(doc, "rider") if h["role"] == "danger"]
    assert rider and any(h["moving"] is True for h in rider)
    assert tones(ev)


def test_far_car_with_fixed_contact_row_and_jittering_horizon_never_approaches():
    """The v26.1.1 bug: horizon wobble turned a parked/far car into 'approaching at 6 m/s'."""
    rng = np.random.RandomState(7)
    frames = []
    for i in range(150):
        hv = HV + rng.uniform(-0.03, 0.03)                 # the region (hence the horizon estimate) wobbles
        g = base_grid(hv=hv)
        place(g, "vehicle", 11.0, 0.3, 1.8, 1.5)           # contact row fixed in the image
        _poles_for_speed(g, i / FPS)                       # we are walking: static witnesses approach
        frames.append(g)
    doc, ev = run(frames, mot=motion(15))
    car = hz(doc, "vehicle")
    assert len(car) > 100
    assert all(h["closingMps"] is None or abs(h["closingMps"]) < 0.5 for _, h in car)
    assert all(h["role"] != "danger" for _, h in car)
    assert not [e for e in speech(ev) if "approaching" in e["text"] or e["role"] in ("danger", "final")]
    assert tones(ev) == []
    assert any(abs(f["horizonY"] - HV) < 0.04 for f in doc["frames"])


def test_unknown_mover_is_treated_as_static_never_approaching():
    frames = approach_frames(cls="rider", d0=22, seconds=14)       # no motion, no static witnesses
    doc, ev = run(frames)
    riders = [h for _, h in hz(doc, "rider")]
    assert riders and all(h["moving"] is None for h in riders)
    assert not [e for e in speech(ev) if "approaching" in e["text"]]


def test_median_along_the_path_is_not_a_feature_or_danger():
    def median(g, t):
        for cls in ("divider", "curb"):
            lat = 0.0 if cls == "divider" else 0.25
            for r in range(int(row_for(14.0)), min(H, int(row_for(1.8)))):
                d = dist_at_row(r + 1)
                c = int(W / 2 + lat * F / d)
                g[r, c:c + max(1, int(round(0.12 * F / d)))] = ID[cls]
                if cls == "divider":
                    g[r, c:c + 1] = ID["divider"]

    doc, ev = run(approach_frames(d0=500, seconds=12, extra=median), mot=motion(12))
    items = hz(doc, "divider") + hz(doc, "curb")
    assert items
    assert all(h["role"] not in ("danger", "feature") for _, h in items)
    assert speech(ev, "feature") == [] and speech(ev, "danger") == [] and tones(ev) == []


def test_vegetation_and_manhole_are_silent():
    def extra(g, t):
        d = 14.0 - SPEED * t
        place(g, "utility-cover", d, 0.0, 0.7, 0.05)
        for r in range(int(row_for(7.0)), int(row_for(3.0))):          # hedge along the edge
            dd = dist_at_row(r + 1)
            c0 = int(W / 2 + 2.0 * F / dd) + 1
            g[r, c0:c0 + 8] = ID["nature vegetation"]

    doc, ev = run(approach_frames(d0=500, seconds=10, extra=extra), mot=motion(10))
    veg = hz(doc, "nature vegetation")
    assert any(h["role"] == "context" for _, h in veg)               # still drawn as context ...
    assert speech(ev) == []                                           # ... but not spoken


# --------------------------------------------------------------------------
# 9. Feature
# --------------------------------------------------------------------------

def test_crosswalk_band_is_announced_once_with_steps():
    def extra(g, t):
        d_near = 17.0 - SPEED * t
        d_far = d_near + 2.5
        r0, r1 = int(row_for(d_far)), int(round(row_for(d_near)))
        if r1 <= int(HV * H) + 1:
            return
        for r in range(max(r0, int(HV * H) + 1), min(r1, H)):
            region = g[r] == ID["flat sidewalk"]
            g[r][region] = ID["crosswalk"]

    doc, ev = run(approach_frames(d0=500, seconds=12, extra=extra), mot=motion(12))
    feat = speech(ev, "feature")
    assert len(feat) == 1
    text = feat[0]["text"]
    assert text.startswith("crosswalk in ") and text.endswith(" steps")
    assert 1 <= int(text.split()[2]) <= 10
    assert speech(ev, "danger") == []


# --------------------------------------------------------------------------
# 10. Surface
# --------------------------------------------------------------------------

def _surface_frames(spans, flicker=()):
    """spans: [(t_end, grid)]; flicker: {frame index: grid} one-frame replacements."""
    frames = []
    for i in range(int(spans[-1][0] * FPS)):
        t = i / FPS
        g = next(grid for t_end, grid in spans if t < t_end)
        frames.append(dict(flicker).get(i, g))
    return frames


def test_surface_spoken_only_for_road_changes_debounced():
    side, road = base_grid("flat sidewalk"), base_grid("flat road")
    frames = _surface_frames([(6, side), (16, road), (24, side)], flicker=[(30, road), (200, side)])
    doc, ev = run(frames)
    sf = speech(ev, "surface")
    assert [e["text"] for e in sf] == ["road", "sidewalk"]       # into road, then out of it
    assert sf[0]["trackId"] is None and sf[0]["clock"] is None and sf[0]["role"] == "surface"
    debounce = CONFIG["surfaces"]["debounceSeconds"]
    assert sf[0]["t"] >= 6.0 + debounce - 0.2 and sf[1]["t"] >= 16.0 + debounce - 0.2
    assert not any(f["pathChange"] for f in doc["frames"])        # surface change does not reset context


def test_start_on_road_is_announced_and_bike_lane_sidewalk_flip_is_silent():
    doc, ev = run([base_grid("flat road")] * 50)
    assert [e["text"] for e in speech(ev, "surface")] == ["road"]
    side, bike = base_grid("flat sidewalk"), base_grid("flat bike-lane")
    doc, ev = run(_surface_frames([(6, side), (14, bike), (22, side)]))
    assert speech(ev) == []
    assert {f["region"]["label"] for f in doc["frames"]} == {"sidewalk", "bike lane"}


def test_bike_lane_flip_does_not_retrigger_wall():
    base_side, base_bike = base_grid("flat sidewalk"), base_grid("flat bike-lane")
    frames = []
    for i in range(240):
        g = (base_side if i < 100 else base_bike).copy()
        add_wall(g)
        frames.append(g)
    doc, ev = run(frames)
    assert [e["text"] for e in speech(ev)] == ["obstacle at 1"]
    assert not any(f["pathChange"] for f in doc["frames"])


# --------------------------------------------------------------------------
# 11. Speech policy: priority, gap, hold
# --------------------------------------------------------------------------

def _item(track_id, role, steps, label="thing", group="static", clock=12, dist=None, urgency=None, approaching=False):
    it = col._Item(group=group, class_name=label, bbox=[0.4, 0.5, 0.5, 0.6], contact_y=0.6,
                   distance_m=steps * 0.7 if dist is None else dist, lateral_m=0.0, bearing=0.0, clock=clock, pan=0.0,
                   area_frac=0.01, clipped=False, touches=True, lane_hit=True, along_path=False, lane_cover=1.0)
    it.track_id, it.role, it.steps, it.label, it.settled = track_id, role, steps, label, True
    it.role_run = 2                                   # confirmed (roles.confirmFrames)
    it.moving = False
    it.approaching = approaching
    it.urgency = urgency or ("final" if role == "danger" and steps <= 3 else "danger" if role == "danger" else "none")
    return it


def _policy():
    """A policy past its start summary (which has its own hold and gates; see the start-summary test)."""
    p = col.SpeechPolicy(CONFIG)
    p.summary = False
    return p


def _tracks(*ids):
    box = col.Box(0.4, 0.5, 0.5, 0.6)
    return {i: col._Track(i, "static", "x", box, 0.0, 0.0, 0.0, 5.0, 0.0) for i in ids}


def test_global_gap_priority_and_context_hold():
    p = _policy()
    tr = _tracks(1, 2, 3, 4)
    danger, feat, ctx = _item(1, "danger", 8, "pole"), _item(2, "feature", 6, "curb", group="feature"), \
        _item(3, "context", 20, "obstacle", clock=2)
    # all three candidates in the same second: only the danger is spoken
    e = p.step(10.0, [danger, feat, ctx], tr)
    assert e["role"] == "danger" and e["text"] == "pole, 12 o'clock, 8 steps"
    assert p.step(10.1, [danger, feat, ctx], tr) is None          # nothing within the global gap
    assert p.step(11.9, [danger, feat, ctx], tr) is None
    # a final call ignores the gap
    danger.steps, danger.urgency = 2.4, "final"
    e = p.step(12.0, [danger, feat, ctx], tr)
    assert e["role"] == "final" and e["text"] == "pole, 12 o'clock, 2 steps"
    # next: the feature (gap passed), the context is held while a danger is active
    e = p.step(14.6, [danger, feat, ctx], tr)
    assert e["role"] == "feature" and e["text"] == "curb in 2 steps" or e["text"] == "curb in 6 steps"
    assert p.step(18.0, [danger, feat, ctx], tr) is None
    assert p.step(18.1, [feat, ctx], tr)["text"] == "obstacle at 2"
    # once heard, never again while remembered
    assert p.step(25.0, [feat, ctx], tr) is None


def test_surface_waits_for_gap_and_beats_context():
    p = _policy()
    tr = _tracks(1)
    ctx = _item(1, "context", 10, "obstacle", clock=2)
    p.surface_adopted(None, "road", CONFIG["surfaces"])
    assert p.step(0.0, [ctx], tr)["text"] == "road"
    assert p.step(1.0, [ctx], tr) is None                         # gap
    assert p.step(2.6, [ctx], tr)["text"] == "obstacle at 2"
    p2 = _policy()
    p2.surface_adopted(None, "pedestrian", CONFIG["surfaces"])    # not announced
    assert p2.surface_pending is None
    p2.surface_adopted("pedestrian", "bikeLane", CONFIG["surfaces"])
    assert p2.surface_pending is None
    p2.surface_adopted("bikeLane", "road", CONFIG["surfaces"])
    assert p2.surface_pending == ("road", "road")
    p2.surface_adopted("road", "pedestrian", CONFIG["surfaces"])  # out of a road is announced too
    assert p2.surface_pending == ("pedestrian", "sidewalk")


def test_only_listed_context_labels_are_spoken():
    p = _policy()
    tr = _tracks(1, 2, 3)
    quiet = [_item(1, "context", 10, "vegetation", clock=1), _item(2, "context", 10, "manhole", clock=2)]
    assert p.step(0.0, quiet, tr) is None
    assert p.step(5.0, quiet + [_item(3, "context", 10, "parked car", clock=10)], tr)["text"] == "parked car at 10"


def test_stale_context_is_dropped_and_approach_template_used():
    p = _policy()
    tr = _tracks(1, 2, 3)
    p.max_items = 1                                      # one label per phrase: the other must wait for the gap
    a, b = _item(1, "context", 10, "obstacle", clock=10), _item(2, "context", 12, "building", clock=2)
    assert p.step(0.0, [a, b], tr)["text"] == "obstacle at 10"
    # building waits for the gap but is older than contextMaxDelaySeconds by then
    assert p.step(2.0, [b], tr) is None
    assert p.step(3.6, [b], tr) is None
    assert p.step(6.0, [b], tr) is None                  # dropped (and remembered as known)
    mover = _item(3, "danger", 9, "cyclist", group="moving", approaching=True)
    assert p.step(7.0, [mover], tr)["text"] == "cyclist approaching, 12 o'clock"


def test_context_memory_is_by_label_not_side_or_clock():
    p = _policy()
    tr = _tracks(1, 2, 3)
    assert p.step(0.0, [_item(1, "context", 10, "obstacle", clock=1)], tr)["text"] == "obstacle at 1"
    for t, clock in ((5.0, 2), (10.0, 10), (15.0, 12)):         # any side, any clock position: already referenced
        assert p.step(t, [_item(2, "context", 10, "obstacle", clock=clock)], tr) is None
    # still remembered while seen, even 40 s on; forgotten after 30 s unseen
    for t in range(16, 41):
        p.observe_context(float(t), {"obstacle"})
    assert p.step(40.0, [_item(2, "context", 10, "obstacle", clock=10)], tr) is None
    p.observe_context(75.0, set())
    assert p.step(75.0, [_item(2, "context", 10, "obstacle", clock=10)], tr)["text"] == "obstacle at 10"
    # a turn clears the memory
    p.clear_context(80.0)
    assert p.step(86.0, [_item(2, "context", 10, "obstacle", clock=11)], tr)["text"] == "obstacle at 11"


def test_vehicle_and_parked_car_are_one_context_label():
    p = _policy()
    tr = _tracks(1, 2)
    v = _item(1, "context", 10, "vehicle", clock=10)
    v.family = "vehicle"
    assert p.step(0.0, [v], tr)["text"] == "vehicle at 10"
    parked = _item(2, "context", 10, "parked car", clock=12)
    parked.family = "vehicle"
    assert p.step(5.0, [parked], tr) is None


def test_new_context_labels_are_one_grouped_phrase_nearest_first_max_three():
    p = _policy()
    tr = _tracks(1, 2, 3, 4, 5)
    its = [_item(1, "context", 10, "building", clock=2, dist=6.0), _item(2, "context", 10, "obstacle", clock=12, dist=3.0),
           _item(3, "context", 10, "vehicle", clock=11, dist=9.0), _item(4, "context", 10, "parked car", clock=1, dist=12.0),
           _item(5, "context", 10, "obstacle", clock=10, dist=20.0)]
    its[3].family = its[2].family = "vehicle"
    e = p.step(30.0, its, tr)
    assert e["role"] == "context" and e["text"] == "obstacle at 12, building at 2, vehicle at 11"
    assert e["trackId"] == 2
    # the rest (one per label: the 4th label would be a second "vehicle") is already known
    assert p.step(40.0, its, tr) is None


def test_start_summary_needs_only_confirmation_not_age_or_surface():
    """v26.1.5: the first context phrase may precede the 0.5 s track age and the adopted surface."""
    it = _item(1, "context", 10, "building", clock=2)
    it.settled = False
    p = col.SpeechPolicy(CONFIG)
    assert p.step(0.2, [it], _tracks(1), surface_known=False) is None            # held 0.5 s to gather the view
    e = p.step(0.7, [it], _tracks(1), surface_known=False)
    assert e is not None and e["text"] == "building at 2"
    it.role_run = 1                                                              # not yet confirmed
    p2 = col.SpeechPolicy(CONFIG)
    assert p2.step(0.2, [it], _tracks(1), surface_known=False) is None
    assert p2.step(0.9, [it], _tracks(1), surface_known=False) is None
    # outside the summary the old gates apply again
    it.role_run = 2
    p3 = col.SpeechPolicy(CONFIG)
    p3.summary = False
    assert p3.step(5.0, [it], _tracks(1), surface_known=True) is None             # not settled
    it.settled = True
    assert p3.step(5.1, [it], _tracks(1), surface_known=False) is None            # surface unknown
    assert p3.step(5.2, [it], _tracks(1), surface_known=True)["text"] == "building at 2"


def test_danger_final_and_feature_need_two_consecutive_frames():
    p = col.SpeechPolicy(CONFIG)
    tr = _tracks(1, 2)
    d = _item(1, "danger", 8, "pole")
    d.role_run = 1
    f = _item(2, "feature", 6, "curb", group="feature")
    f.role_run = 1
    assert p.step(10.0, [d, f], tr) is None
    d.role_run = f.role_run = 2
    assert p.step(10.2, [d, f], tr)["text"] == "pole, 12 o'clock, 8 steps"
    q = col.SpeechPolicy(CONFIG)
    fin = _item(1, "danger", 2, "person")
    fin.role_run = 1
    assert q.step(0.0, [fin], _tracks(1)) is None               # the false "person, 3 steps" of the review
    fin.role_run = 2
    assert q.step(0.2, [fin], _tracks(1))["text"] == "person, 12 o'clock, 2 steps"


def test_danger_first_announced_inside_final_range_speaks_only_final():
    p = col.SpeechPolicy(CONFIG)
    tr = _tracks(1)
    it = _item(1, "danger", 2.0, "pole")
    assert p.step(0.0, [it], tr)["role"] == "final"
    assert p.step(5.0, [it], tr) is None


def test_tone_interpolation_table():
    by = CONFIG["tones"]["bySteps"]
    assert col._tone_params(12, by) == (1.0, 660)
    assert col._tone_params(10, by) == (1.0, 660)
    assert col._tone_params(8, by)[0] == pytest.approx(0.8)
    assert col._tone_params(4.5, by)[0] == pytest.approx(0.45)
    assert col._tone_params(0.2, by) == (0.15, 1100)


# --------------------------------------------------------------------------
# 12. No motion
# --------------------------------------------------------------------------

def test_runs_without_motion():
    frames = approach_frames(seconds=14)
    doc, ev = run(frames, mot=None)
    assert doc["egoAvailable"] is False
    for f in doc["frames"]:
        e = f["ego"]
        assert e["cadenceHz"] is None and e["headingDeg"] is None
        assert e["stepLengthM"] == pytest.approx(0.7)
        assert e["estimated"]["cadence"] is False and e["estimated"]["stepLength"] is False
    pole = [h for _, h in hz(doc, "pole") if h["stepsTo"] is not None]
    assert pole and all(h["stepsTo"] == pytest.approx(h["distanceM"] / 0.7, abs=0.06) for h in pole)
    assert speech(ev, "danger")


def test_explicit_step_length_is_used():
    s = col.resolve_settings(CONFIG, "chest", HFOV, None, 0.5)
    doc, _ = run(approach_frames(seconds=8), settings=s)
    assert doc["settings"]["stepLengthM"] == 0.5
    pole = [h for _, h in hz(doc, "pole")]
    assert all(h["stepsTo"] == pytest.approx(h["distanceM"] / 0.5, abs=0.06) for h in pole)
    assert doc["frames"][-1]["ego"]["stepLengthM"] == 0.5
    assert doc["frames"][-1]["ego"]["estimated"]["stepLength"] is False


def test_step_length_estimated_from_speed_and_cadence():
    doc, _ = run(approach_frames(seconds=15), mot=motion(15))
    e = doc["frames"][-1]["ego"]
    assert e["estimated"]["cadence"] and e["estimated"]["speed"] and e["estimated"]["stepLength"]
    assert e["speedMps"] == pytest.approx(SPEED, abs=0.4)
    assert e["stepLengthM"] == pytest.approx(SPEED / 1.8, abs=0.25)


# --------------------------------------------------------------------------
# 13. Output documents
# --------------------------------------------------------------------------

def test_output_documents_are_serializable_and_complete():
    doc, ev = run(approach_frames(seconds=15), mot=motion(15))
    json.dumps(doc)
    json.dumps(ev)
    assert set(doc) == {"version", "settings", "gridW", "gridH", "egoAvailable", "frames"}
    assert doc["version"] == "v26.1.5" == ev["version"]
    assert set(doc["settings"]) == {"mount", "hfovDeg", "cameraHeightM", "stepLengthM", "laneHalfWidthM"}
    assert (doc["gridW"], doc["gridH"]) == (W, H)
    assert len(doc["frames"]) == 150
    frame_keys = {"index", "t", "horizonY", "horizonEstimated", "region", "lane", "ego", "pathChange", "hazards"}
    ego_keys = {"speedMps", "cadenceHz", "stepLengthM", "headingDeg", "estimated"}
    hazard_keys = {"trackId", "className", "group", "label", "role", "moving", "bbox", "contactY", "bearingDeg",
                   "clock", "pan", "distanceM", "lateralM", "stepsTo", "closingMps", "urgency", "areaFrac"}
    seen_hazard = False
    for f in doc["frames"]:
        assert set(f) == frame_keys
        assert set(f["ego"]) == ego_keys and set(f["ego"]["estimated"]) == {"speed", "cadence", "stepLength"}
        assert len(f["lane"]) == 4 and all(len(p) == 2 for p in f["lane"])
        if f["region"]:
            assert set(f["region"]) == {"surface", "label", "rows"}
            assert all(len(r) == 3 for r in f["region"]["rows"])
        for h in f["hazards"]:
            assert set(h) == hazard_keys
            assert h["role"] in ("danger", "feature", "context", "none")
            assert h["urgency"] in ("none", "danger", "final")
            seen_hazard = True
    assert seen_hazard
    speech_keys = {"t", "type", "role", "text", "trackId", "urgency", "clock", "pan"}
    tone_keys = {"t", "type", "role", "trackId", "urgency", "pan", "frequencyHz", "durationSeconds"}
    for e in ev["events"]:
        assert set(e) == (speech_keys if e["type"] == "speech" else tone_keys)
        assert e["role"] in ("context", "surface", "feature", "danger", "final")
    ts = [e["t"] for e in ev["events"]]
    assert ts == sorted(ts)
    # the lane polygon: near edge wider than far edge, far edge at dangerSteps x step length
    lane = doc["frames"][50]["lane"]
    assert lane[0][1] == lane[1][1] == 1.0 and lane[2][1] < 1.0
    assert lane[1][0] - lane[0][0] > lane[2][0] - lane[3][0] > 0


def test_unknown_classes_are_skipped_not_fatal():
    names = [n for n in NAMES if n not in ("animal", "traffic-light pedestrians")]
    grid = np.full((H, W), 0, dtype=np.uint8)
    doc, _ = col.run_collision(np.stack([grid] * 3), np.arange(3) / 10, names, CONFIG, SETTINGS, None)
    assert len(doc["frames"]) == 3


def test_bearing_and_clock_unchanged_from_v26_1_0():
    assert col.bearing_deg(0.5, 118) == 0.0
    assert col.bearing_deg(1.0, 118) == pytest.approx(math.degrees(math.atan(math.tan(math.radians(59)))))
    assert [col.clock_from_bearing(b) for b in (0, 14, 16, 45, 75, 90, -16, -45, -90, 120)] == \
        [12, 12, 1, 2, 3, 3, 11, 11, 9, 3]


def test_resolve_settings_defaults_and_overrides():
    s = col.resolve_settings(CONFIG)
    assert (s.mount, s.hfov_deg, s.camera_height_m, s.step_length_m, s.horizon_default) == ("chest", 118.0, 1.3, None, 0.45)
    s = col.resolve_settings(CONFIG, "head", 90, 1.8, 0.8)
    assert (s.mount, s.hfov_deg, s.camera_height_m, s.step_length_m, s.horizon_default) == ("head", 90.0, 1.8, 0.8, 0.40)
    assert col.resolve_settings(CONFIG, "nonsense").mount == "chest"
