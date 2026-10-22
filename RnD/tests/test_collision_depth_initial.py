"""Initial depth anchor (``anchor: "initial"``, DA2 metric): one-shot ground calibration, then frozen."""

from __future__ import annotations

import copy
import dataclasses

import numpy as np
import pytest

import collision as col
from tests.test_collision import CONFIG, FPS, HC, NAMES, motion
from tests.test_collision_depth import with_source
from tests.test_collision_depth_scale import relative_doc, scene


def biased(frames, zs, bias=2.2, noise=0.04, seed=5, drop=lambda i: False, bias_of=None, hc=HC):
    """Metric-looking maps: true z x bias (x +-noise per frame), flagged ``anchor: initial``."""
    doc = relative_doc(frames, zs, hc=hc, jitter=0.0)
    rng = np.random.RandomState(seed)
    maps = doc["depth"] * 8.0                              # back to true z (relative_doc divides by BASE_SCALE)
    for i in range(len(maps)):
        b = bias if bias_of is None else bias_of(i)
        maps[i] = maps[i] * b * (1 + noise * rng.uniform(-1, 1))
        if drop(i):
            maps[i] = np.nan
    return {**doc, "depth": maps, "units": "metric", "anchor": "initial"}


def go(frames, depth, source="depth", mot=None, config=CONFIG, prior="ground"):   # prior: settings override
    """``prior`` "ground" = c is the ground k (1 here: the synthetic camera height is the preset's)."""
    return col.run_collision(np.stack(frames), np.arange(len(frames)) / FPS, NAMES, config,
                             with_source(source, depth_level_prior=prior), mot, depth)


def poles(doc):
    return [(f["index"], h) for f in doc["frames"] for h in f["hazards"] if h["className"] == "pole"]


def test_initial_anchor_calibrates_a_biased_metric_map_and_freezes():
    frames, zs = scene(seconds=8.0)
    doc, _ = go(frames, biased(frames, zs))
    got = [(i, h) for i, h in poles(doc) if i >= 3 and h["depthM"] is not None]
    assert len(got) > 30
    ratios = np.array([h["depthM"] / zs[i] for i, h in got])
    assert abs(np.median(ratios) - 1) < 0.03 and np.abs(ratios - 1).max() < 0.12   # +-4 % noise + row quantisation
    anchors = [f["ego"]["depthAnchor"] for f in doc["frames"]]
    assert all(f["ego"]["depthAnchorMode"] == "initial" for f in doc["frames"])
    assert anchors[0] is None and anchors[1] is None
    assert anchors[2] is not None and anchors[2] == pytest.approx(1 / 2.2, rel=0.08)
    assert len({round(a, 4) for a in anchors[5:]}) == 1          # frozen from the 6th valid ratio on
    assert anchors[5] == anchors[-1]


def test_initial_anchor_needs_three_valid_frames():
    frames, zs = scene(seconds=4.0)
    doc, _ = go(frames, biased(frames, zs, drop=lambda i: i >= 2))      # only 2 valid frames
    assert all(f["ego"]["depthAnchor"] is None for f in doc["frames"])
    assert all(h["depthM"] is None for _, h in poles(doc))
    ground, _ = go(frames, None, source="ground")
    for (_, a), (_, b) in zip(poles(doc), poles(ground)):               # depth mode fell back to ground
        assert a["distanceM"] == pytest.approx(b["distanceM"], rel=1e-6)


def test_invalid_frames_do_not_count_and_anchor_is_usable_at_three():
    frames, zs = scene(seconds=4.0)
    bad = {0, 1, 3, 4}
    doc, _ = go(frames, biased(frames, zs, drop=lambda i: i in bad))
    a = [f["ego"]["depthAnchor"] for f in doc["frames"]]
    
    assert a[5] is None and a[6] is not None                           # valid frames 2, 5, 6
    assert a[6] == pytest.approx(1 / 2.2, rel=0.08)


def test_other_modes_unchanged():
    frames, zs = scene(seconds=4.0)
    d = biased(frames, zs)
    for mode, anch in (("per-frame", True), ("none", False)):
        doc, _ = go(frames, {**d, "anchor": mode})
        assert all(f["ego"]["depthAnchorMode"] == mode for f in doc["frames"])
        assert (doc["frames"][-1]["ego"]["depthAnchor"] is not None) == anch
    # default when "anchor" is missing: relative -> per-frame, metric -> none
    rel = {k: v for k, v in relative_doc(frames, zs).items() if k != "anchor"}
    assert go(frames, rel)[0]["frames"][-1]["ego"]["depthAnchorMode"] == "per-frame"
    met = {k: v for k, v in d.items() if k != "anchor"}
    assert go(frames, met)[0]["frames"][-1]["ego"]["depthAnchorMode"] == "none"


def _recal(flag):
    cfg = copy.deepcopy(CONFIG)
    cfg["distance"]["recalibrateOnPathChange"] = flag
    frames, zs = scene(seconds=12.0)
    d = biased(frames, zs, bias_of=lambda i: 2.2 if i < 7 * FPS else 1.5, noise=0.0)
    doc, _ = go(frames, d, mot=motion(12.0, turn=(5.0, 6.0, 70.0)), config=cfg)
    assert any(f["pathChange"] for f in doc["frames"])
    return doc["frames"][0]["ego"]["depthAnchor"], doc["frames"][-1]["ego"]["depthAnchor"]


def test_recalibration_on_path_change_only_with_the_flag():
    _, off = _recal(False)
    assert off == pytest.approx(1 / 2.2, rel=0.1)
    _, on = _recal(True)
    assert on == pytest.approx(1 / 1.5, rel=0.1)


def test_initial_anchor_unit():
    a = col._InitialAnchor({"anchorMinCells": 10})
    for v in (1.0, 2.0):
        a.update(0, 0, v, 50)
    a.update(0, 0, 9.0, 5)                      # too few cells: ignored
    a.update(0, 0, None, 0)
    assert a.value is None
    a.update(0, 0, 3.0, 50)
    assert a.value == 2.0
    for v in (4.0, 5.0, 6.0):
        a.update(0, 0, v, 50)
    frozen = a.value
    a.update(0, 0, 100.0, 50)
    assert a.value == frozen == 3.5
    a.reset()
    assert a.value is None


# --- level c: prior, freeze ---------------------------------------------------------------------------

def level_run(prior=2.0, mode=None, anchor="initial", config=CONFIG, seconds=12.0):
    cfg = copy.deepcopy(config)
    if mode:
        cfg["distance"]["levelModeByAnchor"][anchor] = mode
    hc = HC * 1.25                                   # real camera higher than the preset: c should settle ~1.25
    frames, zs = scene(seconds=seconds, hc=hc)
    d = biased(frames, zs, hc=hc, noise=0.0)
    d["anchor"] = anchor
    doc, _ = go(frames, d, mot=motion(seconds), config=cfg, prior=prior)
    return [f["ego"] for f in doc["frames"]]


def test_level_prior_number_is_used_before_the_first_estimate():
    egos = level_run(prior=2.0)
    assert egos[5]["depthLevel"] == 2.0 and egos[5]["depthLevelSource"] == "prior"
    assert egos[5]["depthScale"] == pytest.approx(2.0 * egos[5]["depthAnchor"], rel=1e-3)


def test_level_prior_ground_borrows_k():
    egos = level_run(prior="ground")
    assert egos[5]["depthLevelSource"] == "ground" and egos[5]["depthLevel"] == pytest.approx(egos[5]["scale"], abs=1e-3)


def test_freeze_mode_ramps_at_the_slew_limit_then_holds():
    egos = level_run(prior=3.0)
    src = [e["depthLevelSource"] for e in egos]
    assert "prior" in src and "gait" in src and src[-1] == "frozen"
    assert src.index("prior") < src.index("gait") < src.index("frozen")
    p0 = src.index("prior")
    lv = np.array([e["depthLevel"] or np.nan for e in egos], float)
    first = src.index("gait")
    assert lv[first] == pytest.approx(3.0, rel=0.25)                       # starts at the prior, no hard step
    steps = np.abs(np.diff(np.log(lv[max(first - 1, p0):])))
    assert steps.max() <= 0.25 * (1 / FPS) * 1.05 + 1e-6                   # scaleMaxChangePerSecond
    held = src.index("frozen")
    assert len(set(lv[held:])) == 1 and lv[-1] == pytest.approx(1.25, rel=0.15)
    assert lv[-1] < 3.0


def test_continuous_mode_never_freezes():
    egos = level_run(prior=2.0, mode="continuous")
    src = {e["depthLevelSource"] for e in egos}
    assert "gait" in src and "frozen" not in src


def test_level_mode_per_anchor_defaults():
    assert CONFIG["distance"]["levelModeByAnchor"] == {"plane": "none", "initial": "freeze", "per-frame": "continuous", "none": "continuous"}
    frames, zs = scene(seconds=6.0)
    pf, _ = go(frames, {**relative_doc(frames, zs), "anchor": "per-frame"}, mot=motion(6.0))
    e = pf["frames"][-1]["ego"]
    assert e["depthLevelSource"] in ("ground", "gait") and e["depthLevelSource"] != "frozen"   # prior never applies
    nn, _ = go(frames, {**biased(frames, zs), "anchor": "none"})
    assert nn["frames"][-1]["ego"]["depthLevel"] is None


def test_mount_override_takes_precedence_over_the_config_prior():
    cfg = copy.deepcopy(CONFIG)
    assert CONFIG["distance"]["depthLevelPrior"] == "ground"          # no camera-specific default
    assert all("depthLevelPrior" not in p for p in CONFIG["mountPresets"].values())
    cfg["distance"]["depthLevelPrior"] = 1.5
    cfg["mountPresets"]["head"]["depthLevelPrior"] = 2.5
    head = col.resolve_settings(cfg, "head")
    chest = col.resolve_settings(cfg, "chest")
    assert head.depth_level_prior == 2.5 and chest.depth_level_prior is None
    frames, zs = scene(seconds=2.0)
    d = biased(frames, zs)
    def first_level(settings):
        doc, _ = col.run_collision(np.stack(frames), np.arange(len(frames)) / FPS, NAMES, cfg, settings, None, d)
        return doc["frames"][5]["ego"]["depthLevel"]
    assert first_level(with_source("depth", depth_level_prior=3.0)) == 3.0                  # mount override
    assert first_level(with_source("depth", depth_level_prior=None)) == 1.5                                             # config prior
