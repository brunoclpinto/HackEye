"""v26.1.10: relative depth: per-frame ground anchor + gait level (``_DepthAnchor``, ``_DepthScale``)."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import collision as col
from tests.test_collision import CONFIG, F, FPS, H, HC, HV, ID, NAMES, W, base_grid, hz, motion, place
from tests.test_collision_depth import DH, DW, strip, with_source

V = 1.8 * 0.70                     # motion() cadence 1.8 Hz x prior step length 0.70 m
BASE_SCALE = 8.0                   # metres per relative unit; drifts per frame


def scene(seconds=12.0, d0=22.0, hc=HC, cls="pole", half_w=3.0, lat=0.0):
    """A static pole approached at our walking speed; the camera is really ``hc`` high. Returns frames, true z."""
    base = base_grid(half_w_m=half_w, hc=hc)
    frames, zs = [], []
    for i in range(int(seconds * FPS)):
        z = d0 - V * i / FPS
        g = base.copy()
        place(g, cls, z, lat, 0.6, 3.0, hc=hc)
        frames.append(g)
        zs.append(z)
    return frames, np.array(zs)


def relative_doc(frames, zs, hc=HC, jitter=0.2, seed=3, drop=lambda i: False):
    """Relative z-depth maps = true z-depth / scale_i, the scale jumping randomly by +-``jitter`` per frame."""
    rng = np.random.RandomState(seed)
    maps = np.empty((len(frames), DH, DW), dtype=np.float32)
    yy = (np.arange(DH) + 0.5) / DH
    ground = np.where(yy > HV + 0.02, hc * F / (np.maximum(yy - HV, 1e-3) * H), 300.0)
    rows = np.minimum(H - 1, ((np.arange(DH) + 0.5) / DH * H).astype(int))
    cols_ = np.minimum(W - 1, ((np.arange(DW) + 0.5) / DW * W).astype(int))
    for i, g in enumerate(frames):
        z = np.repeat(ground[:, None], DW, axis=1)
        z[g[rows][:, cols_] == ID["pole"]] = zs[i]
        maps[i] = z / (BASE_SCALE * (1 + jitter * rng.uniform(-1, 1)))
        if drop(i):
            maps[i] = np.nan
    return {"t": np.arange(len(frames)) / FPS, "depth": maps, "units": "relative"}


# the synthetic scale jumps independently every frame, so the anchor must follow it frame by frame (the default
# 0.5 s EMA is for the slower drift of real maps)
FAST = copy.deepcopy(CONFIG)
FAST["distance"]["anchorEmaSeconds"] = 0.01


def go(frames, depth, source="depth", mot=True, seconds=12.0, config=FAST):
    return col.run_collision(np.stack(frames), np.arange(len(frames)) / FPS, NAMES, config, with_source(source),
                             motion(seconds) if mot else None, depth)


def test_jumping_scale_is_anchored_per_frame_and_depth_stays_metric():
    frames, zs = scene()
    doc, _ = go(frames, relative_doc(frames, zs))
    got = [(t, h) for t, h in hz(doc, "pole") if h["depthM"] is not None and t > 5.5]
    assert len(got) > 50
    for t, h in got:
        assert h["depthM"] == pytest.approx(zs[int(round(t * FPS))], rel=0.08)
        assert h["distanceM"] == pytest.approx(h["depthM"], abs=0.01)
    ego = doc["frames"][-1]["ego"]
    assert ego["depthAnchor"] > 0 and ego["depthScale"] == pytest.approx(ego["depthAnchor"], rel=0.15)   # c ~ 1 (true height)


def test_depth_is_usable_from_the_start_at_the_ground_level():
    frames, zs = scene()
    doc, _ = go(frames, relative_doc(frames, zs))
    first = next(f for f in doc["frames"] if any(h["depthM"] is not None for h in f["hazards"]))
    assert first["ego"]["depthScaleSource"] == "ground" and first["ego"]["depthScale"] is not None


def test_level_c_converges_to_the_true_height_ratio_from_gait():
    hc = HC * 1.25                                  # the camera is 25 percent higher than the preset says
    frames, zs = scene(hc=hc)
    doc, _ = go(frames, relative_doc(frames, zs, hc=hc))
    e = doc["frames"][-1]["ego"]
    assert e["depthScaleSource"] == "gait"
    assert e["depthScale"] / e["depthAnchor"] == pytest.approx(1.25, rel=0.10)
    for t, h in hz(doc, "pole")[-30:]:
        assert h["depthM"] == pytest.approx(zs[int(round(t * FPS))], rel=0.10)


def test_anchor_is_held_for_two_seconds_then_depth_goes_null():
    frames, zs = scene(seconds=10.0)
    doc, _ = go(frames, relative_doc(frames, zs, drop=lambda i: 50 <= i < 90), seconds=10.0)
    fr = doc["frames"]
    assert fr[60]["ego"]["depthAnchor"] is not None and fr[60]["ego"]["depthScale"] is not None   # 1.0 s into the gap
    assert fr[85]["ego"]["depthAnchor"] is None and fr[85]["ego"]["depthScaleSource"] == "none"
    assert all(h["depthM"] is None for h in fr[85]["hazards"])
    assert fr[95]["ego"]["depthAnchor"] is not None                                                 # recovered


def test_depth_mode_falls_back_to_ground_without_an_anchor():
    frames, zs = scene(seconds=6.0)
    nan = relative_doc(frames, zs, drop=lambda i: True)
    d, _ = go(frames, nan, seconds=6.0)
    g, _ = go(frames, None, source="ground", seconds=6.0)
    assert strip(d) == strip(g)


def test_ground_mode_with_relative_depth_equals_no_depth_apart_from_depth_keys():
    frames, zs = scene()
    a, ea = go(frames, None, source="ground")
    b, eb = go(frames, relative_doc(frames, zs), source="ground")
    assert ea == eb
    assert strip(a) == strip(b)
    assert any(h["depthM"] is not None for f in b["frames"] for h in f["hazards"])


def test_scale_estimator_unit():
    ds = col._DepthScale(CONFIG["ego"], CONFIG["distance"])
    assert ds.value is None
    assert ds.sample(0.3, [(0.0, 0.1)]) is None                    # too slow to be walking
    assert ds.sample(None, [(0.0, 0.1)]) is None
    assert ds.sample(1.0, [(60.0, 0.1), (0.0, -0.1)]) is None      # outside the bearing gate / receding
    assert ds.sample(1.26, [(0.0, 1.0), (60.0, 0.1)]) == pytest.approx(1.26)
    t = 0.0
    for _ in range(40):
        ds.update(t, 1.5, 0.1)
        t += 0.1
    assert ds.value == pytest.approx(1.5)
    for _ in range(10):
        ds.update(t, 3.0, 0.1)
        t += 0.1
    assert ds.value <= 1.5 * (1 + 0.25 * 0.1) ** 10 + 1e-6        # slew-limited
    for _ in range(300):
        ds.update(t, 100.0, 0.1)
        t += 0.1
    assert ds.value <= CONFIG["distance"]["depthLevelRange"][1] + 1e-9


def test_anchor_unit_ema_and_hold():
    an = col._DepthAnchor(CONFIG["distance"])
    an.update(0.0, 0.1, 5.0, 200)
    assert an.value == pytest.approx(5.0)
    an.update(0.1, 0.1, 5.0, 10)                                   # too few cells: held
    assert an.value == pytest.approx(5.0)
    an.update(0.2, 0.1, 10.0, 200)
    assert 5.0 < an.value < 10.0
    an.update(3.0, 0.1, None, 0)
    assert an.value is None


def test_no_cadence_keeps_the_ground_level():
    frames, zs = scene()
    doc, _ = go(frames, relative_doc(frames, zs), mot=False)
    assert all(f["ego"]["depthScaleSource"] in ("ground", "none") for f in doc["frames"])
    assert any(f["ego"]["depthScaleSource"] == "ground" for f in doc["frames"])


def test_default_smoothing_follows_a_slowly_drifting_scale():
    frames, zs = scene()
    maps = relative_doc(frames, zs, jitter=0.0)
    drift = 1 + 0.04 * np.sin(2 * np.pi * np.arange(len(frames)) / FPS / 8.0)     # +-4 percent over 8 s
    maps["depth"] = (maps["depth"] / drift[:, None, None]).astype(np.float32)
    doc, _ = go(frames, maps, config=CONFIG)
    got = [(t, h) for t, h in hz(doc, "pole") if h["depthM"] is not None and t > 5.5]
    assert got
    for t, h in got:
        assert h["depthM"] == pytest.approx(zs[int(round(t * FPS))], rel=0.10)


@pytest.mark.parametrize("horizon", ["fixed", "estimated", 0.45])
def test_anchor_horizon_options_all_anchor_the_jumping_scale(horizon):
    """distance.anchorHorizon: "fixed" (the mount preset's row; the default, no horizon jitter), "estimated"
    (the frame's smoothed horizon) or a row fraction. On a level synthetic scene all three agree."""
    cfg = copy.deepcopy(FAST)
    cfg["distance"]["anchorHorizon"] = horizon
    frames, zs = scene()
    doc, _ = go(frames, relative_doc(frames, zs), config=cfg)
    got = [(t, h) for t, h in hz(doc, "pole") if h["depthM"] is not None and t > 5.5]
    assert len(got) > 50
    assert all(h["depthM"] == pytest.approx(zs[int(round(t * FPS))], rel=0.08) for t, h in got)


def test_default_anchor_horizon_is_fixed():
    assert CONFIG["distance"]["anchorHorizon"] == "fixed"
