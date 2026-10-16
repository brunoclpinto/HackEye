"""Synthetic-grid tests for collision.py v26.1.8 (no model, no GPU).

The scenes use real geometry: a camera at height H, horizon row ``HV``, a
walking surface that is a perspective trapezoid converging to the vanishing
point, and objects placed so that their contact row corresponds to a chosen
ground distance (the inverse of ``ground_distance_m``).
"""

from __future__ import annotations

import copy
import json
import math
import re

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


def test_gait_calibration_makes_distances_and_steps_independent_of_camera_height():
    """A wrong camera height scales the raw metres and the raw ego speed alike; the gait scale k
    (cadence x step length / raw speed) takes the error out, so calibrated distances and steps agree."""
    frames = approach_frames(d0=28.0, seconds=19)
    mot = motion(19)
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
        if ta > 15.0 and fa["scaleSource"] == "gait" and fb["scaleSource"] == "gait":
            assert hb["distanceM"] == pytest.approx(ha["distanceM"], rel=0.2)
            assert hb["stepsTo"] == pytest.approx(ha["stepsTo"], rel=0.2, abs=0.5)
            assert fb["scale"] < fa["scale"]                 # the taller assumed camera needs the smaller k
            compared += 1
    assert compared > 5


def test_scale_k_is_gait_calibrated_and_steps_are_distance_over_step_length():
    frames = approach_frames(seconds=13)
    doc, _ = run(frames, mot=motion(13))
    last = doc["frames"][-1]["ego"]
    assert last["scaleSource"] == "gait"
    # cadence 1.8 Hz x 0.70 m = 1.26 m/s is the ego speed by definition; the scene moves at 1.4 m/s, and
    # the pole closings read it a little low (quantised contact rows), so k lands within about 40 percent of 0.9
    assert 0.6 < last["scale"] < 1.5
    assert last["speedMps"] == pytest.approx(1.8 * 0.70, rel=0.1)
    assert last["stepLengthM"] == 0.70
    for _, h in hz(doc, "pole"):
        assert h["stepsTo"] == pytest.approx(h["distanceM"] / 0.70, abs=0.06)
    assert doc["frames"][0]["ego"]["scaleSource"] == "none" and doc["frames"][0]["ego"]["scale"] == 1.0


def test_scale_is_held_without_cadence_and_changes_slowly():
    sc = col._Scale(CONFIG["ego"], 0.70)
    t = 0.0
    for _ in range(80):                       # 8 s of walking at cadence 2 Hz, raw speed 0.7 -> k = 2
        t += 0.1
        sc.update(t, 2.0, 0.7, 0.1)
    assert sc.k == pytest.approx(2.0, rel=0.05) and sc.value == pytest.approx(sc.k, rel=0.05) or sc.value < sc.k
    k0 = sc.k
    for _ in range(100):                      # standing still: no cadence -> nothing learnt, k held
        t += 0.1
        sc.update(t, None, 0.7, 0.1)
    assert sc.k == k0
    prev = sc.value
    for _ in range(30):                       # a sudden raw speed change moves k slowly, never more than 25 %/s
        t += 0.1
        sc.update(t, 2.0, 0.35, 0.1)
        assert sc.value / prev < math.exp(0.25 * 0.1) + 1e-9
        prev = sc.value


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
    assert len(ctx) == 1 and re.fullmatch(r"obstacle at 1 in \d+", ctx[0]["text"]), ctx      # v26.1.7: position and distance
    assert speech(ev, "surface") == []                      # a sidewalk is not announced
    assert speech(ev, "danger") == [] and speech(ev, "final") == [] and tones(ev) == []


def test_context_spoken_again_after_a_turn_when_it_is_a_different_wall():
    """v26.1.5 re-announced the wall after a turn. v26.1.7 remembers announced objects in the world: the wall of this
    scene is drawn at the same place in the image whatever the heading (so after the 40 degree turn it is, in the
    world, a wall some metres further along) and it is gone from view during the turn, so it is a NEW object and is
    announced again. (The same object seen again after a turn is not: see section 15.)"""
    present = lambda t: t < 8.0 or t >= 13.0
    doc, ev = run(_wall_frames(24, present=present, fragment=False), mot=motion(24, turn=(8.0, 11.0, 40.0)))
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

def test_pole_in_lane_is_named_once_and_the_beeps_carry_the_proximity():
    """v26.1.6 said "beware poles" at 15 steps, "pole at 12 in 9" and a final "pole at 12 in 2". v26.1.7 names the pole
    once, with position and distance, at the first notice; the later danger and final phrases would be repeats of an
    object that was named (CONTRACTS.md 15), so the parking-sensor beeps (unchanged) are all that follows."""
    doc, ev = run(approach_frames(seconds=15), mot=motion(15))
    sp = speech(ev)
    assert [e["role"] for e in sp] == ["feature"]
    m = re.fullmatch(r"pole at 12 in (\d+)", sp[0]["text"])
    assert m and 11 <= int(m.group(1)) <= 15, sp[0]["text"]
    assert "o'clock" not in sp[0]["text"]
    # beeps only while it is a collision course; constant pitch, interval shrinking as steps fall
    pole = hz(doc, "pole")
    t_danger = min(t for t, h in pole if h["role"] == "danger")
    assert sp[0]["t"] < t_danger
    tn = tones(ev)
    assert len(tn) >= 8 and all(e["role"] == "danger" for e in tn)
    assert min(e["t"] for e in tn) >= t_danger - 1e-6
    gaps = np.diff([e["t"] for e in tn])
    assert gaps[: len(gaps) // 3].mean() > gaps[-(len(gaps) // 3):].mean()
    assert {e["frequencyHz"] for e in tn} == {float(CONFIG["tones"]["frequencyHz"])}
    assert all(abs(e["pan"]) <= 1 for e in tn)
    assert all(h["collision"] for _, h in pole if h["role"] == "danger")
    assert any(h["urgency"] == "final" for _, h in pole)          # the final range is reached, it is just not spoken again


def test_beep_episodes_one_track_each_and_every_tone_inside_exactly_one_episode():
    """Lab contract: a beeps episode belongs to ONE trackId, and every tone event lies in exactly one episode
    of the same trackId: [t - 0.05, tEnd + 0.05]. Two poles in the lane one after the other = two episodes."""
    def extra(g, t):
        place(g, "pole", 15.0 - SPEED * t, 0.0, 0.5, 3.0)
        place(g, "pole", 18.0 - SPEED * t, 0.3, 0.5, 3.0)
    doc, ev = run(approach_frames(cls="pole", d0=500, seconds=16, extra=extra), mot=motion(16))
    eps = [e for e in ev["events"] if e["type"] == "beeps"]
    tn = tones(ev)
    assert eps and tn
    for e in eps:
        assert e["role"] == "danger" and e["tEnd"] > e["t"] and e["minSteps"] >= 1
        assert re.fullmatch(r"beeps \u00b7 \w+ at \d+ \u00b7 \d+(\u2192\d+)? steps", e["text"]), e["text"]
        mine = [x for x in tn if x["trackId"] == e["trackId"] and e["t"] - 0.05 <= x["t"] <= e["tEnd"] + 0.05]
        assert mine and abs(min(x["t"] for x in mine) - e["t"]) < 1e-6
        assert abs(max(x["t"] + x["durationSeconds"] for x in mine) - e["tEnd"]) < 1e-3
    for x in tn:
        owners = [e for e in eps if e["trackId"] == x["trackId"] and e["t"] - 0.05 <= x["t"] <= e["tEnd"] + 0.05]
        assert len(owners) == 1, (x, eps)
    assert len({e["trackId"] for e in eps}) == len(eps)


def test_very_close_collision_beeps_are_a_gapless_continuous_tone():
    """At <= continuousSteps the stream is back-to-back tone events with no gap (the audio engine is unchanged)."""
    n = 40
    times = np.arange(n) / FPS
    frames = []
    for i in range(n):
        it = _item(7, "danger", max(0.5, 5.0 - i * 0.12), "pole")
        it.collision = True
        frames.append((it, {7}))
    tn, eps = col._tone_events(frames, times, CONFIG["tones"])
    chunk, cont = CONFIG["tones"]["continuousChunkSeconds"], CONFIG["tones"]["continuousSteps"]
    steps_at = lambda t: max(0.5, 5.0 - round(t * FPS) * 0.12)       # noqa: E731
    run_ = [e for e in tn if e["durationSeconds"] >= chunk - 1e-9]
    assert len(run_) >= 4
    assert all(steps_at(e["t"]) <= cont + 0.2 for e in run_)
    for a_, b_ in zip(run_, run_[1:]):
        assert b_["t"] == pytest.approx(a_["t"] + a_["durationSeconds"], abs=2e-4)     # gapless
    assert len(eps) == 1 and eps[0]["minSteps"] <= cont
    # the beeps before it are short, with intervals that shrink
    short = [e["t"] for e in tn if e["durationSeconds"] < chunk]
    assert np.diff(short)[0] > np.diff(short)[-1]


def test_features_and_context_never_beep():
    doc, ev = run(_curb_scene(), mot=motion(12))
    assert speech(ev, "feature") and tones(ev) == []
    assert [e for e in ev["events"] if e["type"] == "beeps"] == []


def _curb_scene():
    def extra(g, t):
        d = 14.0 - SPEED * t
        r = int(round(row_for(d))) if d > 0.5 else H
        if r <= int(HV * H) + 1 or r >= H:
            return
        for rr in range(r - 1, r + 1):
            region = g[rr] == ID["flat sidewalk"]
            g[rr][region] = ID["curb"]
    return approach_frames(cls="pole", d0=500, seconds=12, extra=extra)


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
    assert speech(ev, "danger") == [] and speech(ev, "final") == [] and tones(ev) == []   # a one-frame blip does not beep
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
    assert re.fullmatch(r"cyclist approaching at 12 in \d+", dsp[0]["text"]), dsp[0]["text"]
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
    assert re.fullmatch(r"crosswalk at 12 in (\d+)", text)          # a landmark: direction and steps
    assert 1 <= int(text.split()[-1]) <= CONFIG["roles"]["landmarkSteps"]
    assert speech(ev, "danger") == []
    assert tones(ev) == []


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


def _curb_band(grid, rows=(H - 5, H - 4, H - 3)):
    """A curb crossing the whole walking region just below our feet (within 2 steps)."""
    g = grid.copy()
    for r in rows:
        region = (g[r] == ID["flat sidewalk"]) | (g[r] == ID["flat road"])
        g[r][region] = ID["curb"]
    return g


def test_surface_change_needs_a_curb_passing_under_and_a_majority():
    side, road = base_grid("flat sidewalk"), base_grid("flat road")
    window = CONFIG["surfaces"]["windowSeconds"]
    # no curb crossed: sidewalk -> road for 25 s is a model relabel and stays silent (review items 120.83 s and 199.16 s)
    doc, ev = run(_surface_frames([(10, side), (35, road)]))
    assert speech(ev, "surface") == []
    assert not any(f["pathChange"] for f in doc["frames"])        # surface change does not reset context
    # with a curb that passed under the user at the change: announced once the new surface holds 70 percent of 10 s
    spans = [(10, side), (10.6, _curb_band(side)), (25, road), (25.6, _curb_band(road)), (50, side)]
    doc, ev = run(_surface_frames(spans, flicker=[(160, side), (300, road)]))
    sf = speech(ev, "surface")
    assert [e["text"] for e in sf] == ["road", "sidewalk"]       # into road, then out of it
    assert sf[0]["trackId"] is None and sf[0]["clock"] is None and sf[0]["role"] == "surface"
    assert sf[0]["t"] >= 10.6 + CONFIG["surfaces"]["majority"] * window - 0.3
    assert sf[1]["t"] >= 25.6 + CONFIG["surfaces"]["majority"] * window - 0.3
    assert CONFIG["surfaces"]["minPersistSeconds"] >= 8.0 and CONFIG["surfaces"]["passUnderRows"] == 6


def _curb_sliver(grid, cols=5, col0=None):
    """A thin curb fragment in the lane just below our feet (5 px = 0.02 of the image wide, like the pieces at 189-198 s)."""
    g = grid.copy()
    for r in (H - 6, H - 5, H - 4, H - 3):
        c = W // 2 if col0 is None else col0
        g[r, c:c + cols] = ID["curb"]
    return g


def test_surface_is_kept_silently_for_curb_fragments_and_curbs_beside_the_lane():
    """Review 199.16 s: the model says road for a long time while the user walks on the sidewalk; curb pieces flicker in
    the lane just ahead (5-12 px wide, 1-2 s) but no curb went under the user. The old surface is kept and nothing is said."""
    side, road = base_grid("flat sidewalk"), base_grid("flat road")
    spans = [(12, side), (50, road)]
    fragments = {i: _curb_sliver(road) for i in range(130, 400, 17)}            # 5 px wide, in the lane, bottom rows
    doc, ev = run(_surface_frames(spans, flicker=fragments))
    assert hz(doc, "curb"), "the fragments must be detected, or this test proves nothing"
    assert speech(ev, "surface") == []
    # a full-width curb whose contact is NOT in the bottom 6 rows (it stays 2 m or more ahead) is no evidence either
    ahead = road.copy()
    for r in (H - 14, H - 13, H - 12):
        ahead[r][ahead[r] == ID["flat road"]] = ID["curb"]
    flick = {i: ahead for i in range(130, 400, 3)}
    doc, ev = run(_surface_frames(spans, flicker=flick))
    assert speech(ev, "surface") == []
    # ... while the same band within the bottom rows that then goes away IS evidence
    band = _curb_band(road)
    doc, ev = run(_surface_frames([(12, side), (13, band), (50, road)]))
    assert [e["text"] for e in speech(ev, "surface")] == ["road"]


def test_surface_flicker_never_reaches_persistence():
    """road <-> sidewalk every 3-6 s (116-125 s of the review): never uninterrupted for 8 s -> silent."""
    side, road = base_grid("flat sidewalk"), base_grid("flat road")
    spans, t = [], 0.0
    for k in range(12):
        t += 3.0 + (k % 3)
        spans.append((t, side if k % 2 == 0 else road))
    doc, ev = run(_surface_frames(spans))
    assert speech(ev, "surface") == []


def test_first_surface_is_adopted_silently_unless_configured_and_bike_lane_sidewalk_flip_is_silent():
    """v26.1.7: with nothing to compare with, a start on "road" cannot be told from a sidewalk read as road (192-200 s of the
    review, cold start), so the first surface is silent; ``surfaces.announceFirstSurface`` brings back the v26.1.6 behaviour."""
    doc, ev = run([base_grid("flat road")] * 150)
    assert speech(ev, "surface") == []
    cfg = copy.deepcopy(CONFIG)
    cfg["surfaces"]["announceFirstSurface"] = True
    doc, ev = run([base_grid("flat road")] * 150, config=cfg)
    assert [e["text"] for e in speech(ev, "surface")] == ["road"]
    assert speech(ev, "surface")[0]["t"] >= CONFIG["surfaces"]["minPersistSeconds"] - 0.3
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
    assert len(speech(ev)) == 1 and re.fullmatch(r"obstacle at 1 in \d+", speech(ev)[0]["text"])
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
    assert e["role"] == "danger" and e["text"] == "pole at 12 in 8, curb at 12 in 6"   # danger leads, then the feature
    assert p.step(10.1, [danger, feat, ctx], tr) is None          # context never overtakes
    feat.role = "none"                                            # (the feature was spoken with the danger)
    assert p.step(10.1, [danger, feat, ctx], tr) is None          # nothing within the global gap
    assert p.step(11.9, [danger, feat, ctx], tr) is None
    # a final call ignores the gap
    danger.steps, danger.urgency = 2.4, "final"
    e = p.step(12.0, [danger, feat, ctx], tr)
    assert e["role"] == "final" and e["text"] == "pole at 12 in 2"
    # the context is held while a danger is active
    assert p.step(14.6, [danger, feat, ctx], tr) is None
    assert p.step(18.0, [danger, feat, ctx], tr) is None
    assert p.step(18.1, [feat, ctx], tr)["text"] == "obstacle at 2 in 20"
    # once heard, never again while remembered
    assert p.step(25.0, [feat, ctx], tr) is None


def test_surface_waits_for_gap_and_beats_context():
    p = _policy()
    tr = _tracks(1)
    ctx = _item(1, "context", 10, "obstacle", clock=2)
    p.surface_adopted(None, "road", CONFIG["surfaces"])
    assert p.step(0.0, [ctx], tr)["text"] == "road"
    assert p.step(1.0, [ctx], tr) is None                         # gap
    assert p.step(2.6, [ctx], tr)["text"] == "obstacle at 2 in 10"
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
    assert p.step(5.0, quiet + [_item(3, "context", 10, "parked car", clock=10)], tr)["text"] == "parked car at 10 in 10"


def test_stale_context_is_dropped_and_approach_template_used():
    p = _policy()
    tr = _tracks(1, 2, 3)
    p.max_items = 1                                      # one label per phrase: the other must wait for the gap
    a, b = _item(1, "context", 10, "obstacle", clock=10), _item(2, "context", 12, "building", clock=2)
    assert p.step(0.0, [a, b], tr)["text"] == "obstacle at 10 in 10"
    # building waits for the gap but is older than contextMaxDelaySeconds by then
    assert p.step(2.0, [b], tr) is None
    assert p.step(3.6, [b], tr) is None
    assert p.step(6.0, [b], tr) is None                  # dropped (and remembered as known)
    mover = _item(3, "danger", 9, "cyclist", group="moving", approaching=True)
    assert p.step(7.0, [mover], tr)["text"] == "cyclist approaching at 12 in 9"


def test_context_memory_is_by_label_not_side_or_clock():
    p = _policy()
    tr = _tracks(1, 2, 3)
    assert p.step(0.0, [_item(1, "context", 10, "obstacle", clock=1)], tr)["text"] == "obstacle at 1 in 10"
    for t, clock in ((5.0, 2), (10.0, 10), (15.0, 12)):         # any side, any clock position: already referenced
        assert p.step(t, [_item(2, "context", 10, "obstacle", clock=clock)], tr) is None
    # still remembered while seen, even 40 s on; forgotten after 30 s unseen
    for t in range(16, 41):
        p.observe_context(float(t), {"obstacle"})
    assert p.step(40.0, [_item(2, "context", 10, "obstacle", clock=10)], tr) is None
    p.observe_context(75.0, set())
    assert p.step(75.0, [_item(2, "context", 10, "obstacle", clock=10)], tr)["text"] == "obstacle at 10 in 10"
    # a turn clears the memory
    p.clear_context(80.0)
    assert p.step(86.0, [_item(2, "context", 10, "obstacle", clock=11)], tr)["text"] == "obstacle at 11 in 10"


def test_vehicle_and_parked_car_are_one_context_label():
    p = _policy()
    tr = _tracks(1, 2)
    v = _item(1, "context", 10, "vehicle", clock=10)
    v.family = "vehicle"
    assert p.step(0.0, [v], tr)["text"] == "vehicle at 10 in 10"
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
    assert e["role"] == "context" and e["text"] == "obstacle at 12 in 10, building at 2 in 10, vehicle at 11 in 10"
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
    assert e is not None and e["text"] == "building at 2 in 10"
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
    assert p3.step(5.2, [it], _tracks(1), surface_known=True)["text"] == "building at 2 in 10"


def test_danger_final_and_feature_need_two_consecutive_frames():
    p = col.SpeechPolicy(CONFIG)
    tr = _tracks(1, 2)
    d = _item(1, "danger", 8, "pole")
    d.role_run = 1
    f = _item(2, "feature", 6, "curb", group="feature")
    f.role_run = 1
    assert p.step(10.0, [d, f], tr) is None
    d.role_run = f.role_run = 2
    assert p.step(10.2, [d, f], tr)["text"] == "pole at 12 in 8, curb at 12 in 6"
    q = col.SpeechPolicy(CONFIG)
    fin = _item(1, "danger", 2, "person")
    fin.role_run, fin.collision = 1, True
    assert q.step(0.0, [fin], _tracks(1)) is None               # the false "person, 3 steps" of the review
    fin.role_run = 2
    assert q.step(0.2, [fin], _tracks(1))["text"] == "person at 12 in 2"


def test_danger_first_announced_inside_final_range_speaks_only_final():
    p = col.SpeechPolicy(CONFIG)
    tr = _tracks(1)
    it = _item(1, "danger", 2.0, "pole")
    assert p.step(0.0, [it], tr)["role"] == "final"
    assert p.step(5.0, [it], tr) is None


def test_tone_interpolation_table():
    by = CONFIG["tones"]["bySteps"]          # [[10, 1.0], [6, 0.5], [3, 0.25], [2, 0.12]]
    assert col._tone_interval(12, by) == 1.0
    assert col._tone_interval(10, by) == 1.0
    assert col._tone_interval(8, by) == pytest.approx(0.75)
    assert col._tone_interval(6, by) == pytest.approx(0.5)
    assert col._tone_interval(4.5, by) == pytest.approx(0.375)
    assert col._tone_interval(3, by) == pytest.approx(0.25)
    assert col._tone_interval(0.2, by) == 0.12


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
        assert e["scale"] == 1.0 and e["scaleSource"] == "none"
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


def test_prior_step_length_and_scale_prior():
    """No per-frame step-length estimate any more: the gait scale k carries it (CONTRACTS.md 14.1.1)."""
    doc, _ = run(approach_frames(seconds=15), mot=motion(15))
    e = doc["frames"][-1]["ego"]
    assert e["estimated"]["cadence"] and e["estimated"]["speed"] and e["estimated"]["stepLength"] is False
    assert e["speedMps"] == pytest.approx(1.8 * 0.70, rel=0.1)      # calibrated ego speed = cadence x step length
    assert e["stepLengthM"] == 0.70
    # a warm start from a known scale is used from the first frame and reported as "prior"
    cfg = copy.deepcopy(CONFIG)
    cfg["ego"]["scalePrior"] = 2.0
    doc1, _ = run(approach_frames(d0=10.0, seconds=3), mot=motion(3))
    doc2, _ = run(approach_frames(d0=10.0, seconds=3), mot=motion(3), config=cfg)
    assert doc2["frames"][0]["ego"]["scale"] == 2.0 and doc2["frames"][0]["ego"]["scaleSource"] == "prior"
    d1 = [h["distanceM"] for _, h in hz(doc1, "pole")][:3]
    d2 = [h["distanceM"] for _, h in hz(doc2, "pole")][:3]
    assert d2 and d1 and d2[0] == pytest.approx(d1[0] * 2.0, rel=0.03)


# --------------------------------------------------------------------------
# 13. Output documents
# --------------------------------------------------------------------------

def test_output_documents_are_serializable_and_complete():
    doc, ev = run(approach_frames(seconds=15), mot=motion(15))
    json.dumps(doc)
    json.dumps(ev)
    assert set(doc) == {"version", "settings", "gridW", "gridH", "egoAvailable", "frames"}
    assert doc["version"] == "v26.1.8" == ev["version"]
    assert set(doc["settings"]) == {"mount", "hfovDeg", "cameraHeightM", "stepLengthM", "laneHalfWidthM", "priorStepLengthM"}
    assert (doc["gridW"], doc["gridH"]) == (W, H)
    assert len(doc["frames"]) == 150
    frame_keys = {"index", "t", "horizonY", "horizonEstimated", "region", "lane", "ego", "pathChange", "hazards"}
    ego_keys = {"speedMps", "cadenceHz", "stepLengthM", "headingDeg", "estimated", "scale", "scaleSource"}
    hazard_keys = {"trackId", "className", "group", "label", "role", "moving", "bbox", "contactY", "bearingDeg",
                   "clock", "pan", "distanceM", "lateralM", "stepsTo", "closingMps", "urgency", "areaFrac", "collision"}
    seen_hazard = False
    for f in doc["frames"]:
        assert set(f) == frame_keys
        assert set(f["ego"]) == ego_keys and set(f["ego"]["estimated"]) == {"speed", "cadence", "stepLength"}
        assert len(f["lane"]) == 4 and all(len(p) == 2 for p in f["lane"])
        if f["region"]:
            assert set(f["region"]) == {"surface", "label", "rows"}
            assert all(len(r) == 3 for r in f["region"]["rows"])
        for h in f["hazards"]:
            assert set(h) == hazard_keys | ({"outline"} if h["role"] != "none" else set())
            assert h["role"] in ("danger", "feature", "context", "none")
            assert h["urgency"] in ("none", "danger", "final")
            seen_hazard = True
    assert seen_hazard
    speech_keys = {"t", "type", "role", "text", "trackId", "urgency", "clock", "pan"}
    tone_keys = {"t", "type", "role", "trackId", "urgency", "pan", "frequencyHz", "durationSeconds"}
    beeps_keys = {"t", "tEnd", "type", "role", "trackId", "label", "clock", "minSteps", "urgency", "text"}
    for e in ev["events"]:
        assert set(e) == {"speech": speech_keys, "tone": tone_keys, "beeps": beeps_keys}[e["type"]]
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


# --------------------------------------------------------------------------
# 14. v26.1.6 rules at the unit level
# --------------------------------------------------------------------------

def _rated(cls, group, steps, lat, **kw):
    """An _Item run through _assign_role with the real config."""
    it = col._Item(group=group, class_name=cls, bbox=[0.4, 0.5, 0.5, 0.6], contact_y=0.6, distance_m=steps * 0.7,
                   lateral_m=lat, bearing=0.0, clock=12, pan=0.0, area_frac=0.01, clipped=False,
                   touches=kw.pop("touches", True), lane_hit=kw.pop("lane_hit", False), along_path=False,
                   lane_cover=kw.pop("lane_cover", 0.0), area_m2=1.0)
    it.steps, it.label = steps, cls
    it.people = cls in ("person", "rider", "animal")
    it.landmark = cls == "crosswalk"
    for k, v in kw.items():
        setattr(it, k, v)
    col._assign_role(it, (0.4, 1.0), CONFIG["roles"], CONFIG["geometry"]["laneHalfWidthM"], 0.70)
    return it


def test_context_only_when_near_in_steps_and_sideways():
    r = CONFIG["roles"]
    near = _rated("building", "static", 5, 2.0)
    assert near.role == "context"
    far_ahead = _rated("building", "static", r["contextMaxSteps"] + 1, 1.0)     # review 52.3 / 58.0 s
    assert far_ahead.role == "none"
    far_side = _rated("building", "static", 5, r["contextMaxLateralM"] + 2.0)    # review 55.5 s
    assert far_side.role == "none" and far_side.summary_ok                       # (only the first scene summary may say it)
    # a vehicle of unknown motion is "vehicle" (never "parked car"), and context only when near
    v = _rated("vehicle", "moving", 5, 1.5, moving=None)
    assert v.role == "context"
    assert _rated("vehicle", "moving", 12, 1.5, moving=None).role == "none"


def test_people_are_movers_with_a_wider_earlier_danger_zone():
    r = CONFIG["roles"]
    p = _rated("person", "moving", 12, 2.5, moving=None)
    assert p.role == "danger" and not p.collision                      # beside the path, 12 steps away: a warning, no beeps
    assert _rated("person", "moving", r["movingDangerSteps"] + 1, 0.3, moving=None).role == "none"
    assert _rated("person", "moving", 8, r["movingLaneHalfWidthM"] + 0.5, moving=None).role == "none"
    on_path = _rated("person", "moving", 8, 0.3, moving=None)
    assert on_path.role == "danger" and on_path.collision
    # measured "stationary" does not make a person static (review 48-49 s): still a danger beside the path
    assert _rated("person", "moving", 8, 1.0, moving=False).role == "danger"
    # approaching towards the lane beeps; walking away beside us is no threat
    assert _rated("person", "moving", 8, 1.2, moving=True, approaching=True).collision
    assert _rated("person", "moving", 8, 1.2, moving=True, receding=True).role == "none"
    # the same distance for a static pole beside the lane is not danger
    assert _rated("pole", "static", 8, 1.2).role != "danger"


def test_crosswalk_is_a_landmark_without_crossing_the_lane():
    assert _rated("crosswalk", "feature", 12, 4.0).role == "feature"           # anywhere in the region, <= landmarkSteps
    assert _rated("crosswalk", "feature", CONFIG["roles"]["landmarkSteps"] + 1, 0.0).role == "none"
    assert _rated("curb", "feature", 8, 0.0, lane_hit=True, lane_cover=0.6).role == "feature"
    assert _rated("curb", "feature", 8, 4.0, lane_hit=False).role == "none"    # a curb beside the path stays silent


def test_same_label_items_are_grouped_and_danger_leads():
    p = col.SpeechPolicy(CONFIG)
    tr = _tracks(1, 2, 3, 4)
    obstacle = _item(1, "danger", 6, "obstacle", clock=12)
    p1 = _item(2, "danger", 7, "person", group="moving", clock=1)
    p2 = _item(3, "danger", 9, "person", group="moving", clock=2)
    for it in (p1, p2):
        it.people = True
    crosswalk = _item(4, "feature", 10, "crosswalk", group="feature", clock=12)
    e = p.step(10.0, [obstacle, p1, p2, crosswalk], tr)
    assert e["role"] == "danger"
    assert e["text"] == "obstacle at 12 in 6, person at 1 and 2 in 7, crosswalk at 12 in 10"
    assert "o'clock" not in e["text"]
    # at most three entries
    q = col.SpeechPolicy(CONFIG)
    items = [_item(1, "danger", 6, "obstacle"), _item(2, "danger", 7, "pole", clock=1),
             _item(3, "feature", 8, "curb", group="feature"), _item(4, "feature", 9, "crosswalk", group="feature")]
    assert len(q.step(0.0, items, _tracks(1, 2, 3, 4))["text"].split(", ")) == 3
    # approaching movers use their own template, also grouped
    a = col.SpeechPolicy(CONFIG)
    m1, m2 = _item(1, "danger", 9, "person", group="moving", clock=12, approaching=True), \
        _item(2, "danger", 9, "person", group="moving", clock=2, approaching=True)
    m1.people = m2.people = True
    assert a.step(0.0, [m1, m2], _tracks(1, 2))["text"] == "person approaching at 12 and 2 in 9"


def _pole(i, steps=10, lat=1.0):
    it = _item(i, "none", steps, "pole", clock=12)
    it.thin, it.present_run, it.lateral_m = True, 2, lat
    return it


def test_thin_objects_are_announced_once_per_cluster_with_position_and_distance_and_rearm_after_8_s():
    p = col.SpeechPolicy(CONFIG)
    tr = _tracks(*range(1, 40))
    said = []
    # a cluster of poles in view for 15 s (new poles appear as old ones pass): exactly one notice, "poles at 12 in 12"
    for k in range(31):
        t = k * 0.5
        poles = [_pole(1 + k // 4, 12), _pole(2 + k // 4, 14)]
        e = p.step(t, poles, tr)
        if e:
            said.append((t, e["text"]))
    assert said == [(0.0, "poles at 12 in 12")], said
    # no thin object noticed for 8 s -> re-armed; the next cluster is announced once
    far = _pole(30, steps=CONFIG["roles"]["thinNoticeSteps"] + 5)          # out of range: not "noticed"
    for k in range(17):
        assert p.step(15.0 + k * 0.5, [far], tr) is None
    for k in range(10):
        e = p.step(24.0 + k * 0.5, [_pole(31 + k // 5, 9)], tr)
        if e:
            said.append((24.0 + k * 0.5, e["text"]))
    assert [x[1] for x in said] == ["poles at 12 in 12", "pole at 12 in 9"] and said[1][0] >= 23.0
    # a gap shorter than the re-arm time does not re-arm; a turn does
    q = col.SpeechPolicy(CONFIG)
    tr = _tracks(*range(1, 40))
    assert q.step(0.0, [_pole(1)], tr)["text"] == "pole at 12 in 10"
    assert q.step(5.0, [], tr) is None and q.step(6.0, [_pole(2)], tr) is None
    q.clear_context(7.0)
    assert q.step(12.0, [_pole(3)], tr)["text"] == "pole at 12 in 10"
    # several poles at different clocks: "poles at 11 and 1 in 8", the steps are those of the nearest
    m = col.SpeechPolicy(CONFIG)
    a, b = _pole(1, 8), _pole(2, 11)
    a.clock, b.clock = 11, 1
    assert m.step(0.0, [a, b], _tracks(1, 2))["text"] == "poles at 11 and 1 in 8"
    # a different thin label is its own entry: "pole at 12 in 8, traffic light at 1 in 10"
    n = col.SpeechPolicy(CONFIG)
    pl, tl = _pole(1, 8), _pole(2, 10)
    tl.label, tl.clock = "traffic light", 1
    assert n.step(0.0, [pl, tl], _tracks(1, 2))["text"] == "pole at 12 in 8, traffic light at 1 in 10"
    # a pole that is a danger is spoken as a danger, with no extra thin notice
    tr = _tracks(*range(1, 40))
    r = col.SpeechPolicy(CONFIG)
    d = _item(1, "danger", 8, "pole")
    d.thin, d.present_run = True, 2
    assert r.step(0.0, [d], _tracks(1))["text"] == "pole at 12 in 8"
    far_side = _pole(5, lat=3.0)
    assert col.SpeechPolicy(CONFIG).step(0.0, [far_side], tr) is None      # beyond thinNoticeLateralM: silent


def test_feature_label_not_repeated_for_fragments_of_the_same_crossing():
    p = col.SpeechPolicy(CONFIG)
    tr = _tracks(1, 2, 3, 4, 5)
    walk = 2.0                                                      # steps per second
    said = []
    # one curb at 10 steps ahead of t=0, re-tracked as 3 new fragments within 6 s: one phrase
    for tid, t in ((1, 0.0), (2, 2.0), (3, 4.0)):
        p.travel_steps = walk * t
        e = p.step(t, [_item(tid, "feature", 10 - walk * t, "curb", group="feature")], tr)
        if e:
            said.append(e["text"])
    assert said == ["curb at 12 in 10"]
    # a different curb 6 steps further on, within the 6 s gap: announced; the same label later: announced too
    p.travel_steps = walk * 4.5
    e = p.step(4.5, [_item(4, "feature", 10 - walk * 4.5 + 6, "curb", group="feature")], tr)
    assert e and e["text"].startswith("curb at 12 in 7")


def test_crosswalk_comes_before_curb_and_groups_only_when_both_new():
    p = col.SpeechPolicy(CONFIG)
    tr = _tracks(1, 2, 3)
    cw = _item(1, "feature", 6, "crosswalk", group="feature")
    cb = _item(2, "feature", 3, "curb", group="feature")
    assert p.step(0.0, [cb, cw], tr)["text"] == "crosswalk at 12 in 6, curb at 12 in 3"
    # both have been said: a fragment re-tracked under a new id says nothing
    cw2 = _item(3, "feature", 6, "crosswalk", group="feature")
    assert p.step(3.0, [cw2, cb], tr) is None


def test_no_oclock_in_any_phrase_of_the_synthetic_scenes():
    scenes = [approach_frames(seconds=15), approach_frames(lat=2.0, half_w=3.0, seconds=14), _curb_scene()]
    for frames in scenes:
        _, ev = run(frames, mot=motion(len(frames) / FPS))
        assert all("o'clock" not in e.get("text", "") for e in ev["events"])


# --------------------------------------------------------------------------
# 15. v26.1.7: world memory (dead reckoning), final only if never named, phrase completeness, surface pass-under
# --------------------------------------------------------------------------

WALK_CADENCE = 1.8
WALK_SPEED = WALK_CADENCE * 0.70             # the dead-reckoned speed: cadence x prior step length (m/s)


def walk(objects, seconds, fps=FPS, turns=(), hidden=lambda name, t: False, speed=WALK_SPEED):
    """A scripted walk through a world of standing objects, rendered from the walker's pose.

    ``objects``: dicts {name, cls, x, y[, w, h]} in metres (x right/east, y ahead/north of the start). The user walks at
    ``speed`` along the heading, which follows ``turns`` = [(t0, t1, degrees right)]. Returns (frames, motion): the motion
    track carries the camera bob (cadence ``WALK_CADENCE``) and the heading change as horizontal image motion, exactly what
    the on-device motion estimate would report.
    """
    mfps = 24.0
    tm = np.arange(0, seconds, 1 / mfps)
    heading = np.zeros(len(tm))
    for t0, t1, deg in turns:
        heading += np.clip((tm - t0) / (t1 - t0), 0.0, 1.0) * deg
    rng = np.random.RandomState(0)
    mot = {"t": tm, "dy": 0.01 * np.sin(2 * math.pi * WALK_CADENCE * tm) + 0.003 * rng.randn(len(tm)),
           "dx": -np.diff(heading, prepend=heading[0]) / HFOV}
    base = base_grid(half_w_m=2.0)
    frames, ux, uy, prev_t = [], 0.0, 0.0, 0.0
    for i in range(int(seconds * fps)):
        t = i / fps
        th = math.radians(float(np.interp(t, tm, heading)))
        ux += speed * (t - prev_t) * math.sin(th)
        uy += speed * (t - prev_t) * math.cos(th)
        prev_t = t
        g = base.copy()
        for o in objects:
            if hidden(o["name"], t):
                continue
            dx, dy = o["x"] - ux, o["y"] - uy
            fwd, right = dx * math.sin(th) + dy * math.cos(th), dx * math.cos(th) - dy * math.sin(th)
            if 1.3 <= fwd <= 28.0 and abs(right) <= 1.6 * fwd:
                place(g, o["cls"], fwd, right, o.get("w", 0.35), o.get("h", 3.0))
        frames.append(g)
    return frames, mot


def _no_memory():
    cfg = copy.deepcopy(CONFIG)
    cfg["memory"]["enabled"] = False
    return cfg


def _summary(ev):
    return [(e["role"], e["text"]) for e in speech(ev)]


POLE = {"name": "p", "cls": "pole", "x": 0.0, "y": 14.0}


def test_walk_scene_is_dead_reckoned_at_cadence_times_step_length():
    frames, mot = walk([POLE], 8)
    doc, _ = run(frames, mot=mot)
    ego = [f["ego"] for f in doc["frames"] if f["t"] >= 5.0]
    assert all(e["cadenceHz"] == pytest.approx(WALK_CADENCE, abs=0.15) for e in ego)
    assert all(e["speedMps"] == pytest.approx(WALK_SPEED, abs=0.2) for e in ego)


def test_fragmented_object_is_not_announced_again_and_there_is_no_repeated_final():
    """The 41.17 s pattern of the third review: the pole in the lane is named at the first notice; its detection breaks for
    1.4 s (a new track after the gap) and v26.1.6 called "pole at 12 in 9" and a final "pole at 12 in 3" for the SAME pole."""
    frames, mot = walk([POLE], 12, hidden=lambda n, t: 5.5 <= t < 6.9)
    doc, ev = run(frames, mot=mot)
    assert len(speech(ev)) == 1 and re.fullmatch(r"pole at 12 in 1[0-5]", speech(ev)[0]["text"]), _summary(ev)
    assert len({h["trackId"] for _, h in hz(doc, "pole")}) >= 2            # the fragmentation really happened
    assert any(h["urgency"] == "final" for _, h in hz(doc, "pole"))        # ... and the final range was reached
    # without the world memory (v26.1.6 / no motion data) the repeat is there ...
    _, old = run(frames, mot=mot, config=_no_memory())
    assert [r for r, _ in _summary(old)] == ["feature", "danger", "final"], _summary(old)
    # ... and the parking-sensor beeps are untouched by the memory
    assert tones(ev) == tones(old) and [b["text"] for b in ev["events"] if b["type"] == "beeps"] == \
        [b["text"] for b in old["events"] if b["type"] == "beeps"]
    assert tones(ev)
    # no motion track at all: the track rules of v26.1.6 apply (and the object is announced on each new track)
    _, nomot = run(frames)
    assert [r for r, _ in _summary(nomot)][-1] == "final"


def test_final_call_is_still_spoken_for_an_object_that_was_never_named():
    """Something that appears suddenly close has not been named: "pole at 12 in 2" as before (the rule is about repeats)."""
    frames, mot = walk([POLE], 12, hidden=lambda n, t: t < 9.5)
    doc, ev = run(frames, mot=mot)
    fin = speech(ev, "final")
    assert len(fin) == 1 and re.fullmatch(r"pole at 12 in [123]", fin[0]["text"]), _summary(ev)
    assert tones(ev)


def test_a_second_object_of_the_same_type_further_on_is_announced():
    poles = [{"name": "a", "cls": "pole", "x": 1.5, "y": 14.0}, {"name": "b", "cls": "pole", "x": 1.5, "y": 60.0}]
    frames, mot = walk(poles, 52)
    doc, ev = run(frames, mot=mot)
    sp = speech(ev)
    assert len(sp) == 2 and all(re.fullmatch(r"pole at 12 in 1[0-5]", e["text"]) for e in sp), _summary(ev)
    assert sp[0]["t"] < 6 and sp[1]["t"] > 35                 # the first when it came into view, the second 46 m further on


def test_object_in_view_throughout_is_named_once_however_often_it_is_re_tracked():
    """Fragments of the same pole under new track ids (every 0.9 s) and a turn of 30 degrees: one notice."""
    frames, mot = walk([POLE], 9, turns=[(4.0, 6.0, 30.0)], hidden=lambda n, t: (t * 10) % 9 < 1.2 and t > 4.0)
    doc, ev = run(frames, mot=mot)
    assert len({h["trackId"] for _, h in hz(doc, "pole")}) >= 3
    assert len([e for e in speech(ev) if "pole" in e["text"]]) == 1, _summary(ev)


# -- the memory itself ------------------------------------------------------

def _mem_item(track_id, label, dist, lat, steps=8, family=None, clock=12):
    it = _item(track_id, "context", steps, label, clock=clock, dist=dist)
    it.lateral_m = lat
    it.family = family or label
    return it


def _world():
    w = col._WorldMemory(CONFIG["memory"])
    w.advance(0.0, 0.0, 1.26, 0.0)
    return w


def test_memory_matches_same_family_within_radius_plus_ten_percent_of_distance():
    w = _world()
    tr = _tracks(*range(1, 8))
    named = _mem_item(1, "building", 10.0, 0.0)
    w.link([named], tr, 0.0)
    w.add(named, 0.0)
    r = CONFIG["memory"]["matchRadiusM"]
    # a candidate 2.4 m away at 10 m range is the same object (2.5 + 1.0 m), 3.4 m away is not; another label never is
    near = _mem_item(2, "building", 10.0, 2.4)
    far = _mem_item(3, "building", 10.0, r + 0.1 * 10.0 + 0.3)
    other = _mem_item(4, "obstacle", 10.0, 0.0)
    w.link([near, far, other], tr, 0.1)
    assert near.mem_id is not None and far.mem_id is None and other.mem_id is None
    # the vehicle / parked car family is one thing
    car = _mem_item(5, "vehicle", 12.0, 3.0)
    w.link([car], tr, 0.2)
    eid = w.add(car, 0.2)
    parked = _mem_item(6, "parked car", 12.0, 3.2, family="vehicle")
    w.link([parked], tr, 0.3)
    assert parked.mem_id == eid


def test_memory_forgets_objects_that_are_passed_or_too_far():
    w = _world()
    tr = _tracks(1, 2, 3)
    a, b, far = _mem_item(1, "pole", 6.0, 0.0), _mem_item(2, "pole", 25.0, 0.0), _mem_item(3, "pole", 35.0, 0.0)
    w.link([a, b, far], tr, 0.0)
    ids = [w.add(a, 0.0), w.add(b, 0.0), w.add(far, 0.0)]
    t = 0.0
    while t < 1.25:                                    # 35 m away is "too far": gone once it is not held as just seen
        t += 0.1
        w.advance(t, 0.1, 1.26, 0.0)
    assert set(w.entries) == set(ids[:2])
    # walk on: a is passed once it is more than 1 m behind us (6 m + 1 m = 7 m of walking, 5.6 s), b is still 17 m ahead
    while t < 5.0:
        t += 0.1
        w.advance(t, 0.1, 1.26, 0.0)
    assert set(w.entries) == set(ids[:2])             # 6.3 m walked: a is 0.3 m behind, not passed yet
    while t < 6.5:
        t += 0.1
        w.advance(t, 0.1, 1.26, 0.0)
    assert set(w.entries) == {ids[1]}
    # an object in view right now is not dropped on the dead reckoning's say-so (the camera outranks it) ...
    owner = _mem_item(2, "pole", 17.0, 0.0)
    owner.track_id = 2
    w.link([owner], tr, t)
    for _ in range(5):
        t += 0.1
        w.advance(t, 0.1, 1.26, 180.0)                 # (we "turn round": it is now behind us)
        w.link([owner], tr, t)
    assert set(w.entries) == {ids[1]}
    # ... until it is out of view for a second
    for _ in range(12):
        t += 0.1
        w.advance(t, 0.1, 1.26, 180.0)
    assert w.entries == {}


def test_memory_needs_a_heading_and_is_inactive_without_motion():
    w = col._WorldMemory(CONFIG["memory"])
    assert not w.active
    w.advance(0.0, 0.0, None, None)
    assert not w.active
    w.advance(0.1, 0.1, 1.2, 10.0)
    assert w.active
    assert not col._WorldMemory(CONFIG["memory"], enabled=False).active
    p = col.SpeechPolicy(CONFIG)
    assert p.world is None and not p._mem
    doc, _ = run(approach_frames(seconds=3))
    assert doc["egoAvailable"] is False


def test_object_seen_again_after_a_turn_is_not_announced_again_but_a_new_one_is():
    world = col._WorldMemory(CONFIG["memory"])
    policy = col.SpeechPolicy(CONFIG)
    policy.world, policy.summary = world, False
    tr = _tracks(*range(1, 6))
    world.advance(0.0, 0.0, 1.26, 0.0)
    b1 = _mem_item(1, "building", 6.0, 3.0, steps=9, clock=2)
    world.link([b1], tr, 0.0)
    e = policy.step(0.0, [b1], tr)
    assert e and e["text"] == "building at 2 in 9"
    # 3 s later we have walked 3.8 m and turned 60 degrees right: the same building is now straight ahead, a new track
    for k in range(1, 31):
        world.advance(k * 0.1, 0.1, 1.26, 60.0 * min(1.0, k / 20))
    fwd, right = 3.0 * math.sin(math.radians(60)) + (6.0 - 3.78) * math.cos(math.radians(60)), \
        3.0 * math.cos(math.radians(60)) - (6.0 - 3.78) * math.sin(math.radians(60))
    b2 = _mem_item(2, "building", fwd, right, steps=5, clock=12)
    world.link([b2], tr, 3.0)
    assert b2.mem_id is not None
    policy.clear_context(3.0)                        # the turn forgets the label memory (v26.1.5) ...
    assert policy.step(8.0, [b2], tr) is None        # ... but not the object: nothing is said
    # a second building 20 m further on, same label, is a new object (the label memory of v26.1.5 lapses after 30 s unseen
    # or on a turn; it is the second gate that this object memory adds to)
    for k in range(80):
        world.advance(3.0 + k * 0.1, 0.1, 1.26, 60.0)
    b3 = _mem_item(3, "building", 5.0, 2.5, steps=7, clock=2)
    world.link([b3], tr, 12.0)
    assert b3.mem_id is None
    policy.observe_context(45.0, set())
    assert policy.step(45.0, [b3], tr)["text"] == "building at 2 in 7"


def test_grouped_context_and_thin_cluster_members_are_all_remembered():
    world = col._WorldMemory(CONFIG["memory"])
    policy = col.SpeechPolicy(CONFIG)
    policy.world, policy.summary = world, False
    tr = _tracks(*range(1, 8))
    world.advance(0.0, 0.0, 1.26, 0.0)
    a, b = _mem_item(1, "building", 5.0, -2.0, clock=11), _mem_item(2, "obstacle", 4.0, 2.0, clock=1)
    p1, p2 = _pole(3, 8, lat=-1.0), _pole(4, 9, lat=1.5)
    for it, (d, lat) in ((p1, (5.6, -1.0)), (p2, (6.3, 1.5))):
        it.distance_m, it.lateral_m, it.family, it.role = d, lat, "pole", "none"
    p1.clock, p2.clock = 11, 1
    world.link([a, b, p1, p2], tr, 0.0)
    e = policy.step(0.0, [a, b, p1, p2], tr)
    assert e["text"] == "poles at 11 and 1 in 8"
    e2 = policy.step(3.0, [a, b], tr)
    assert e2 and set(e2["text"].split(", ")) == {"obstacle at 1 in 8", "building at 11 in 8"}
    # a minute later (re-detections under new track ids, nothing passed yet) nothing is announced again
    tr2 = _tracks(11, 12, 13, 14)
    again = [_mem_item(11, "building", 5.0, -2.0, clock=11), _mem_item(12, "obstacle", 4.0, 2.0, clock=1)]
    pp1, pp2 = _pole(13, 8, lat=-1.0), _pole(14, 9, lat=1.5)
    for it, (d, lat) in ((pp1, (5.6, -1.0)), (pp2, (6.3, 1.5))):
        it.distance_m, it.lateral_m, it.family, it.role = d, lat, "pole", "none"
    world.link(again + [pp1, pp2], tr2, 3.5)
    assert all(i.mem_id is not None for i in again + [pp1, pp2])
    policy.clear_context(4.0)
    assert policy.step(20.0, again + [pp1, pp2], tr2) is None


def test_final_needs_no_earlier_name_but_a_covered_pole_counts_as_named():
    """A thin object that was only covered by an earlier notice (never spoken for itself) is not new either."""
    world = col._WorldMemory(CONFIG["memory"])
    policy = col.SpeechPolicy(CONFIG)
    policy.world, policy.summary = world, False
    tr = _tracks(1, 2)
    world.advance(0.0, 0.0, 1.26, 0.0)
    fin = _item(1, "danger", 2.0, "pole")
    fin.family, fin.distance_m, fin.collision = "pole", 1.4, True
    world.link([fin], tr, 0.0)
    assert policy.step(0.0, [fin], tr)["role"] == "final"                 # never named: spoken
    fin2 = _item(2, "danger", 2.0, "pole")
    fin2.family, fin2.distance_m, fin2.collision = "pole", 1.4, True
    world2 = col._WorldMemory(CONFIG["memory"])
    policy2 = col.SpeechPolicy(CONFIG)
    policy2.world, policy2.summary = world2, False
    world2.advance(0.0, 0.0, 1.26, 0.0)
    world2.link([fin2], tr, 0.0)
    world2.add(fin2, 0.0, named=False)                                   # covered by a cluster notice
    world2.link([fin2], tr, 0.1)
    assert policy2.step(0.1, [fin2], tr) is None                         # the beeps carry it


def test_approaching_after_being_named_standing_is_news_but_only_once():
    """201.33 s of the review: "person at 12 in 14" at 196.3, then "person approaching at 12" at 201.3 - the user ticked both."""
    world = col._WorldMemory(CONFIG["memory"])
    policy = col.SpeechPolicy(CONFIG)
    policy.world, policy.summary = world, False
    tr = _tracks(1, 2, 3)
    world.advance(0.0, 0.0, 1.26, 0.0)
    walker = _item(1, "danger", 12, "person", group="moving")
    walker.people, walker.family, walker.distance_m = True, "person", 8.0
    world.link([walker], tr, 0.0)
    assert policy.step(0.0, [walker], tr)["text"] == "person at 12 in 12"
    # the same person under a new track (a hand-off within a second), now measured to approach: news, once
    again = _item(2, "danger", 9, "person", group="moving", approaching=True)
    again.people, again.family, again.distance_m = True, "person", 6.0
    world.link([again], tr, 0.8)
    assert again.mem_id is not None and not again.mem_approach
    assert policy.step(8.0, [again], tr)["text"] == "person approaching at 12 in 9"
    third = _item(2, "danger", 7, "person", group="moving", approaching=True)      # (the same track goes on)
    third.people, third.family, third.distance_m = True, "person", 5.0
    world.link([third], tr, 8.5)
    assert third.mem_id is not None and third.mem_approach
    assert policy.step(16.0, [third], tr) is None
    # a person who left our sight for more than a second is a new person (people walk on)
    stranger = _item(4, "danger", 9, "person", group="moving")
    stranger.people, stranger.family, stranger.distance_m = True, "person", 6.0
    world.link([stranger], _tracks(4), 11.0)
    assert stranger.mem_id is None


# -- phrases ----------------------------------------------------------------

ENTRY = r"[a-z ]+? (?:approaching )?at \d+(?:, \d+)*(?: and \d+)? in \d+(?: steps?)?"


def test_every_object_phrase_has_a_position_and_a_distance():
    scenes = [approach_frames(seconds=15), approach_frames(lat=2.0, half_w=3.0, seconds=14), _curb_scene(),
              _wall_frames(10)]
    for frames in scenes:
        _, ev = run(frames, mot=motion(len(frames) / FPS))
        for e in speech(ev):
            if e["role"] != "surface":
                assert re.fullmatch(f"{ENTRY}(?:, {ENTRY})*", e["text"]), e["text"]
    p = col.SpeechPolicy(CONFIG)
    assert p.step(0.0, [_pole(1, 8)], _tracks(1))["text"] == "pole at 12 in 8"
    one = _item(1, "context", 1, "building", clock=2)
    assert col.SpeechPolicy(CONFIG)._text("context", one) == "building at 2 in 1 step"


def test_steps_are_left_out_only_when_the_distance_is_unknown():
    p = col.SpeechPolicy(CONFIG)
    it = _item(1, "context", 8, "building", clock=2)
    it.steps = float("nan")
    assert p._text("context", it) == "building at 2"
    it.steps = None
    assert p._text("context", it) == "building at 2"
    a, b = _item(1, "danger", 7, "person", group="moving", clock=1), _item(2, "danger", 9, "person", group="moving", clock=2)
    a.steps = b.steps = float("nan")
    assert p._entry("danger", [a, b]) == "person at 1 and 2"


# --------------------------------------------------------------------------
# Outlines (v26.1.8)
# --------------------------------------------------------------------------

def _l_mask():
    m = np.zeros((20, 30), bool)
    m[3:15, 5:9] = True          # vertical bar
    m[11:15, 5:20] = True        # foot: an L with its inner corner at (9, 11)
    return m


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def test_l_shape_outline_keeps_its_inner_corner():
    poly = col.simplify_polygon(col.trace_outline(_l_mask()))
    assert len(poly) >= 5 and (9.0, 11.0) in poly
    signs = [np.sign(_cross(poly[i - 2], poly[i - 1], poly[i])) for i in range(len(poly))]
    assert -1 in signs and 1 in signs                      # a reflex (concave) vertex exists: not a convex hull
    assert poly == [(5.0, 3.0), (9.0, 3.0), (9.0, 11.0), (20.0, 11.0), (20.0, 15.0), (5.0, 15.0)]


def test_outline_is_capped_at_32_points_and_follows_a_blob():
    yy, xx = np.mgrid[:60, :60]
    ang = np.arctan2(yy - 30, xx - 30)
    blob = np.hypot(yy - 30, xx - 30) < 18 + 6 * np.sin(7 * ang)        # a wavy disc
    poly = col.simplify_polygon(col.trace_outline(blob))
    assert 8 <= len(poly) <= 32
    assert len(col.trace_outline(np.ones((1, 1), bool))) == 4


def test_item_outlines_in_a_run_match_bbox_and_roles():
    doc, _ = run(approach_frames(seconds=15), mot=motion(15))
    n_out = 0
    for f in doc["frames"]:
        for h in f["hazards"]:
            if h["role"] == "none":
                assert "outline" not in h
                continue
            o = h["outline"]
            n_out += 1
            assert 4 <= len(o) <= 32
            assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in o)
            xs, ys = [p[0] for p in o], [p[1] for p in o]
            tol_x, tol_y = 1.0 / W + 1e-4, 1.0 / H + 1e-4
            x0, y0, x1, y1 = h["bbox"]
            assert abs(min(xs) - x0) <= tol_x and abs(max(xs) - x1) <= tol_x
            assert abs(min(ys) - y0) <= tol_y and abs(max(ys) - y1) <= tol_y
    assert n_out > 0


def test_role_none_items_have_no_outline():
    doc, _ = run(approach_frames(seconds=15), mot=motion(15))
    items = [h for f in doc["frames"] for h in f["hazards"]]
    quiet = [h for h in items if h["role"] == "none"]
    assert quiet and any(h["role"] != "none" for h in items)
    assert all("outline" not in h for h in quiet)


def test_outline_change_leaves_hazards_and_events_unchanged_vs_committed_v26_1_7(tmp_path):
    """Everything but the new field is identical to the committed v26.1.7 module on the review fixtures."""
    import importlib.util
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    baseline = os.environ.get("HACKEYE_COLLISION_V26_1_7")      # path to `git show 5ff8e98:RnD/src/collision.py`
    try:
        if baseline:
            old_src = Path(baseline).read_text()
        else:
            old_src = subprocess.run(["git", "show", "5ff8e98:RnD/src/collision.py"], cwd=root, check=True,
                                     capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):   # e.g. inside the container: no git, no history
        pytest.skip("git history for v26.1.7 not available")
    path = tmp_path / "collision_v26_1_7.py"
    path.write_text(old_src)
    spec = importlib.util.spec_from_file_location("collision_v26_1_7", path)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old                                # dataclasses look the module up by name
    spec.loader.exec_module(old)
    fx = root / "tests" / "fixtures"
    for name in ("4929_review1", "4929_review2", "4929_review3"):
        meta = json.load(open(fx / f"{name}.json"))
        npz = np.load(fx / f"{name}.npz")
        s = meta["settings"]
        cfg_new = col.load_config()
        cfg_old = json.loads(json.dumps(cfg_new))
        cfg_old["version"] = "v26.1.7"
        for i, _w in enumerate(meta["windows"][:2]):
            motion_ = {"t": npz[f"w{i}_mt"], "dx": npz[f"w{i}_mdx"], "dy": npz[f"w{i}_mdy"]}
            args = (npz[f"w{i}_grids"], npz[f"w{i}_t"], meta["classNames"])
            d_new, e_new = col.run_collision(*args, cfg_new, col.resolve_settings(cfg_new, s["mount"], s["hfovDeg"], s["cameraHeightM"], s["stepLengthM"]), motion_)
            d_old, e_old = old.run_collision(*args, cfg_old, old.resolve_settings(cfg_old, s["mount"], s["hfovDeg"], s["cameraHeightM"], s["stepLengthM"]), motion_)
            assert e_new["events"] == e_old["events"]
            for f in d_new["frames"]:
                for h in f["hazards"]:
                    h.pop("outline", None)
            assert d_new["frames"] == d_old["frames"]
