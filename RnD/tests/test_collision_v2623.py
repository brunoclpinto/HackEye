"""v26.2.3: ground + depth distance (range-corrected depth fused with the ground ray of a base on a surface) and the horizon switch
(plan ``docs/plans/v26.2.3.md``)."""

from __future__ import annotations

import copy
import hashlib
import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

import collision as col
import groundfuse
import worldmap
from lab import analysis, recordings, server
from tests.test_collision_regression import FIXTURES
from tests.test_orientation import GOLDEN_CHEST0004_REVIEW7

GOLDEN_V2622 = "3d5d983c180bcc2bbfc5d1379a5cb3b670a00d89334a969b12f8aec86a21a8a4"      # the v26.2.2 collision output; re-pinned v26.2.4: same events, 2 of 120 frames differ in item values at the 20 m snapshot edge (was e356b6ec...) of chest0004_review7
GH, GW, HFOV, CAM_H, HORIZON = 135, 240, 118.0, 1.3, 0.45
F_PX = col.focal_px(GW, HFOV)
GEO = groundfuse.Geometry(GH, GW, HFOV, "fisheye", CAM_H)
GD = groundfuse.settings(col.load_config()["distance"])
REP = {"ref": 1.45, "sigmaRows": 0.6, "curve": [[5.0, 1.0], [12.0, 1.0]]}


# ---------------------------------------------------------------- config and settings

def test_config_and_defaults():
    cfg = col.load_config()
    assert cfg["version"] == "v26.2.4" == worldmap.load_config()["version"]
    d = cfg["distance"]
    assert d["objectDistance"] == "depth" and d["useHorizon"] is True      # measured worse than depth on the user's ticks (DECISIONS v26.2.3)
    assert set(d["groundDepth"]) >= {"minRowsBelowHorizon", "binEdgesM", "emaSeconds", "holdSeconds", "extrapolate", "priorCurve", "depthRelErr",
                                     "sanityFactor", "rowSigma"}
    assert "objectDistance" not in worldmap.load_config()            # the one setting lives in collision.json (the map reads the pass's own)
    s = col.resolve_settings(cfg, "chest", 118.0, None, None)
    assert (s.object_distance, s.use_horizon) == ("depth", True)
    s = col.resolve_settings(cfg, "chest", 118.0, None, None, object_distance="ground-contact", use_horizon=False)
    assert (s.object_distance, s.use_horizon) == ("ground-contact", False)
    assert col.resolve_settings(cfg, "chest", 118.0, None, None, object_distance="nonsense").object_distance == "depth"
    assert groundfuse.resolved_mode("ground+depth", False) == "depth" and groundfuse.resolved_mode("ground+depth", True) == "ground+depth"


# ---------------------------------------------------------------- the correction curve

def _squashed_ground(q=1.1, squash_from=10.0, slope=0.25):
    """A depth map of a flat floor whose depth is q x the ground ray (the lens geometry) up to ``squash_from`` m and then squashed (DA2 beyond ~12 m)."""
    rows = np.arange(GH)[:, None] * np.ones((1, GW))
    cols = np.arange(GW)[None, :] * np.ones((GH, 1))
    g = groundfuse.ground_z(GEO, rows + 0.5, cols + 0.5, HORIZON)
    mask = np.isfinite(g) & (rows + 0.5 - HORIZON * GH >= 4.0)
    g = np.where(mask, g, 1e3)
    d = q * np.where(g <= squash_from, g, squash_from + (g - squash_from) * slope)
    return d, g, mask


def test_ground_ray_is_the_lens_geometry():
    row = GH / 2.0 + 30.0
    z = groundfuse.ground_z(GEO, np.array([row]), np.array([GW / 2.0]), 0.5)[0]            # horizon on the axis: level camera
    assert z == pytest.approx(CAM_H / math.tan(30.0 / GEO.f_eq))                           # equidistant: angle = pixels / f_eq
    rect = groundfuse.Geometry(GH, GW, HFOV, "rectilinear", CAM_H)
    assert groundfuse.ground_z(rect, np.array([row]), np.array([GW / 2.0]), 0.5)[0] == pytest.approx(CAM_H * rect.f_pin / 30.0)
    rows = np.arange(80, 130, dtype=float)
    zc = groundfuse.ground_z(GEO, rows, np.full(rows.shape, GW / 2.0), HORIZON)
    assert (np.diff(zc) < 0).all()                                                          # lower in the image = nearer
    assert np.isnan(groundfuse.ground_z(GEO, np.array([HORIZON * GH - 3.0]), np.array([GW / 2.0]), HORIZON)[0])        # above the horizon
    g_side = groundfuse.ground_z(GEO, np.array([100.0]), np.array([GW - 5.0]), HORIZON)[0]  # the same row near the image side: a nearer z (off the axis)
    assert g_side < groundfuse.ground_z(GEO, np.array([100.0]), np.array([GW / 2.0]), HORIZON)[0]


def test_correction_curve_recovers_the_near_field_factor_and_the_squash():
    d, g, mask = _squashed_ground()
    cor = groundfuse.Corrector(GD, GEO)
    rep = cor.update(0.0, mask, d, 1.0, HORIZON, 0.6)
    assert rep is not None and abs(rep["ref"] - 1.1) < 0.04 and rep["sigmaRows"] == 0.6
    curve = np.array(rep["curve"])
    assert abs(curve[0, 1] - 1.0) < 0.05 and curve[-1, 1] < 0.8 and (np.diff(curve[:, 1]) <= 1e-9).all()      # ~1 near, falls with range, never rises
    far = d[67, 100]                                                                                             # a row about 14 m away
    fixed, rho = groundfuse.correct_depth(np.array([far]), rep, GD)
    truth = 1.1 * g[67, 100]
    assert abs(fixed[0] - truth) / truth < 0.12 and abs(far - truth) / truth > 0.15 and rho[0] < 0.85
    near = groundfuse.correct_depth(np.array([4.0]), rep, GD)[0][0]
    assert abs(near - 4.0) < 0.2                                                                                 # the near field is unchanged


def test_curve_is_smoothed_held_two_seconds_and_then_dropped():
    d, g, mask = _squashed_ground()
    cor = groundfuse.Corrector(GD, GEO)
    r0 = cor.update(0.0, mask, d, 1.0, HORIZON, 0.5)
    assert cor.update(1.5, None, None, 1.0, HORIZON, 0.5) is not None            # too few samples: held
    assert cor.update(2.6, None, None, 1.0, HORIZON, 0.5) is None                # ... for holdSeconds only
    d2, _, _ = _squashed_ground(q=1.3)
    cor.update(3.0, mask, d, 1.0, HORIZON, 0.5)
    r1 = cor.update(3.1, mask, d2, 1.0, HORIZON, 0.5)                           # 0.1 s of a new level: the EMA (1 s) only moves part of the way
    assert r0["ref"] < r1["ref"] < 1.25
    sparse = np.zeros_like(mask)
    sparse[100, :10] = True
    assert groundfuse.Corrector(GD, GEO).update(0.0, sparse, d, 1.0, HORIZON, 0.5) is None        # too few near samples: no ref


def test_beyond_the_fit_the_prior_or_the_last_ratio_continues():
    rep = {"ref": 1.45, "sigmaRows": 0.5, "curve": [[5.0, 1.0], [12.0, 0.9]]}
    prior = groundfuse.rho_at(np.array([12.0, 15.0, 17.5]), rep, GD)
    last = groundfuse.rho_at(np.array([12.0, 15.0, 17.5]), rep, {**GD, "extrapolate": "last"})
    assert prior[0] == pytest.approx(0.9) and (np.diff(prior) < 0).all() and prior[2] < 0.5
    assert (last == pytest.approx(0.9))
    assert (groundfuse.rho_at(np.array([3.0, 30.0]), None, GD) == 1.0).all()


def test_horizon_sigma_is_the_row_floor_for_a_steady_horizon_and_larger_for_a_jittery_one():
    steady, jit = groundfuse.HorizonSigma(GD, GH), groundfuse.HorizonSigma(GD, GH)
    for k in range(20):
        s = steady.update(k / 6.0, 0.45)
        j = jit.update(k / 6.0, 0.45 + (0.01 if k % 2 else -0.01))
    assert s == pytest.approx(GD["rowSigma"]) and j > 1.3


# ---------------------------------------------------------------- fusion

def _resolve(d, g, rb, contact, mode="ground+depth", rep=REP):
    out, src = groundfuse.resolve([d], [g], [g * 0.6 / rb if rb > 0 else 1.0], [rb], [contact], rep, GD, mode)
    return float(out[0]), int(src[0])


def test_fusion_is_inverse_variance_weighted():
    d, g, rb = 10.5, 10.0, 20.0
    sg, sd = g * 0.6 / rb, d * GD["depthRelErr"]
    expect = (g / sg ** 2 + d / sd ** 2) / (1 / sg ** 2 + 1 / sd ** 2)
    got, src = _resolve(d, g, rb, True)
    assert got == pytest.approx(expect) and src == groundfuse.SRC_FUSED and abs(got - g) < abs(got - d)       # many rows below the horizon: the ground ray leads
    got4, _ = _resolve(10.0, 8.0, 4.0, True)                                                                    # at the band edge the ground ray is as noisy as the depth
    sg4, sd4 = 8.0 * 0.6 / 4.0, 10.0 * GD["depthRelErr"]
    assert got4 == pytest.approx((8.0 / sg4 ** 2 + 10.0 / sd4 ** 2) / (1 / sg4 ** 2 + 1 / sd4 ** 2))
    assert abs(got4 - 10.0) < abs(got4 - 8.0) + 1.0 and 8.0 < got4 < 10.0


def test_no_contact_or_outside_the_band_uses_the_corrected_depth_only():
    assert _resolve(10.5, 10.0, 20.0, False) == (pytest.approx(10.5), groundfuse.SRC_DEPTH)         # occluded base / not on a surface
    assert _resolve(10.5, 10.0, 3.0, True) == (pytest.approx(10.5), groundfuse.SRC_DEPTH)           # fewer than minRowsBelowHorizon rows below the horizon
    assert _resolve(10.5, float("nan"), 20.0, True)[1] == groundfuse.SRC_DEPTH                      # no ground ray (no ref)
    squash = {"ref": 1.45, "sigmaRows": 0.5, "curve": [[5.0, 1.0], [12.0, 1.0], [16.0, 0.5]]}
    assert _resolve(16.0, 30.0, 3.0, False, rep=squash)[0] == pytest.approx(32.0)                   # corrected = depth / rho


def test_sanity_gate_ground_wins_when_a_base_in_contact_is_nearer_than_0_7_ground():
    got, src = _resolve(2.0, 10.0, 20.0, True)
    assert got == pytest.approx(10.0) and src == groundfuse.SRC_GROUND
    got, src = _resolve(2.0, 10.0, 20.0, False)                                  # not on a surface: the ground ray is only an upper bound, no gate
    assert got == pytest.approx(2.0) and src == groundfuse.SRC_DEPTH
    got, src = _resolve(7.5, 10.0, 20.0, True)                                   # 0.75 x ground: the fusion stands
    assert src == groundfuse.SRC_FUSED and got > 7.0


def test_ground_contact_and_depth_modes():
    assert _resolve(10.5, 10.0, 20.0, True, "ground-contact") == (pytest.approx(10.0), groundfuse.SRC_GROUND)
    assert _resolve(10.5, 10.0, 20.0, False, "ground-contact") == (pytest.approx(10.5), groundfuse.SRC_DEPTH)
    assert _resolve(10.5, 10.0, 20.0, True, "depth") == (pytest.approx(10.5), groundfuse.SRC_DEPTH)
    assert _resolve(10.5, 10.0, 20.0, True, rep=None) == (pytest.approx(10.5), groundfuse.SRC_DEPTH)


def test_ground_ray_is_in_depth_metres_with_its_sigma():
    row, col = np.array([100.0]), np.array([GW / 2.0])
    g, sg = groundfuse.ground_m(GEO, row, col, HORIZON, REP, 0.6)
    assert g[0] == pytest.approx(REP["ref"] * groundfuse.ground_z(GEO, row, col, HORIZON)[0])
    assert 0 < sg[0] < 0.2 * g[0] and groundfuse.ground_m(GEO, row, col, HORIZON, REP, 1.2)[1][0] > 1.8 * sg[0]
    assert np.isnan(groundfuse.ground_m(GEO, row, col, HORIZON, None)[0]).all()


# ---------------------------------------------------------------- the collision pass on a real window

def _fixture(cfg, **kw):
    meta = json.load(open(FIXTURES / "chest0004_review7.json"))
    s = meta["settings"]
    st = col.resolve_settings(cfg, s["mount"], s["hfovDeg"], s["cameraHeightM"], s["stepLengthM"], projection=s.get("projection"),
                              distance_source=s.get("distanceSource", "ground"), user_height_m=s.get("userHeightM"),
                              camera_location=s.get("cameraLocation"), camera_side=s.get("cameraSide"), **kw)
    npz = np.load(FIXTURES / "chest0004_review7.npz")
    motion = {"t": npz["w0_mt"], "dx": npz["w0_mdx"], "dy": npz["w0_mdy"], "resid": npz["w0_mresid"]}
    dm = meta["depth"]
    depth = {"t": npz["w0_t"], "depth": npz["w0_depth"], "units": dm["units"], "anchor": dm["anchor"]}
    return col.run_collision(npz["w0_grids"], npz["w0_t"], meta["classNames"], cfg, st, motion, depth)


@pytest.fixture(scope="module")
def outputs():
    cfg = col.load_config()
    return {"gd": _fixture(cfg, object_distance="ground+depth"), "depth": _fixture(cfg, object_distance="depth"), "gc": _fixture(cfg, object_distance="ground-contact"),
            "off": _fixture(cfg, use_horizon=False)}


def _stripped(out):
    doc, ev = copy.deepcopy(out[0]), copy.deepcopy(out[1])
    doc["version"] = ev["version"] = "v26.2.2"
    del doc["settings"]["objectDistance"], doc["settings"]["useHorizon"]
    return hashlib.sha256(json.dumps([doc, ev], sort_keys=True).encode()).hexdigest()


def test_depth_reproduces_v2622_byte_for_byte_and_horizon_off_keeps_the_depth_distances(outputs):
    assert _stripped(outputs["depth"]) == GOLDEN_V2622
    # horizon off: the item distances are the depth ones (the map, which judges walls, is built through the depth map, so events may differ)
    base = {(f["index"], h["trackId"]): h for f in outputs["depth"][0]["frames"] for h in f["hazards"]}
    same = tot = 0
    for f in outputs["off"][0]["frames"]:
        for h in f["hazards"]:
            b = base.get((f["index"], h["trackId"]))
            if b is None or b["className"] != h["className"] or h.get("source") == "map" or h.get("ghost") or h.get("coasting") or h.get("solidCorrected"):
                continue
            tot += 1
            same += b["distanceM"] == h["distanceM"] and b.get("depthM") == h.get("depthM")
    assert tot > 200 and same / tot > 0.97
    for k in ("depth", "off"):
        assert not any("depthCorrection" in f for f in outputs[k][0]["frames"])
        assert not any("distanceSource" in h for f in outputs[k][0]["frames"] for h in f["hazards"])
    assert outputs["off"][0]["settings"]["useHorizon"] is False and outputs["off"][0]["settings"]["objectDistance"] == "depth"
    assert outputs["depth"][0]["settings"]["objectDistance"] == "depth" and outputs["depth"][0]["settings"]["useHorizon"] is True
    assert GOLDEN_CHEST0004_REVIEW7 != GOLDEN_V2622           # (the pinned default-config golden carries the new settings keys)


def test_ground_depth_records_the_curve_and_the_source_of_every_distance(outputs):
    doc = outputs["gd"][0]
    with_curve = [f for f in doc["frames"] if "depthCorrection" in f]
    assert len(with_curve) > 0.5 * len(doc["frames"])
    rep = with_curve[-1]["depthCorrection"]
    assert set(rep) == {"ref", "sigmaRows", "curve"} and 0.5 < rep["ref"] < 2.2 and rep["curve"] and len(rep["curve"][0]) == 2
    items = [h for f in doc["frames"] for h in f["hazards"] if "distanceSource" in h]
    assert items and {h["distanceSource"] for h in items} <= {"depth", "ground", "fused"}
    assert any(h["distanceSource"] == "fused" for h in items)
    for h in items:
        assert h["rawDepthM"] is not None and h["rawDepthM"] == h["depthM"]
        if h["groundM"] is not None and not (h.get("solidCorrected") or h.get("ghost") or h.get("coasting")) and h.get("source") != "map":
            assert h["distanceM"] >= 0.7 * h["groundM"] - 0.02                       # the sanity gate
    assert [h["distanceSource"] for f in doc["frames"] for h in f["hazards"] if h.get("distanceSource") == "ground"] is not None


def test_ground_contact_uses_the_ground_ray_for_a_base_on_a_surface(outputs):
    items = [h for f in outputs["gc"][0]["frames"] for h in f["hazards"] if h.get("distanceSource") == "ground"
             and not (h.get("solidCorrected") or h.get("coasting") or h.get("ghost")) and h.get("source") != "map"]
    assert items and all(abs(h["distanceM"] - h["groundM"]) < 0.02 for h in items)


def test_the_world_map_reads_the_curve_and_settings_of_the_pass(outputs):
    doc = outputs["gd"][0]
    frames = worldmap.frames_from_hazards(doc)
    assert [fr["dcorr"] for fr in frames] == [f.get("depthCorrection") for f in doc["frames"]]
    s = worldmap.settings_from_hazards(doc)
    assert (s["objectDistance"], s["useHorizon"]) == ("ground+depth", True)
    old = worldmap.settings_from_hazards({"settings": {"hfovDeg": 118, "cameraHeightM": 1.3}})        # a run made before v26.2.3
    assert (old["objectDistance"], old["useHorizon"]) == ("depth", True)


# ---------------------------------------------------------------- the world map

NAMES = ["flat sidewalk", "building", "person", "nature sky"]
SW, BLD, PERSON, SKY = range(4)


def _observer(mode, use_horizon, projection="rectilinear"):
    cfg = worldmap.load_config()
    kind = worldmap.class_kinds(cfg, NAMES)
    settings = {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "lateralOffsetM": 0.0, "projection": projection, "distanceSource": "depth",
                "objectDistance": mode, "useHorizon": use_horizon}
    return worldmap.Observer(cfg, settings, kind, GH, GW, GD)


def _building_scene():
    grid = np.full((GH, GW), SKY, dtype=np.uint8)
    grid[70:, :] = SW
    grid[40:101, 100:140] = BLD                          # a building whose base (row 100) stands on the sidewalk
    return grid


def test_map_object_bases_follow_the_object_distance_setting():
    grid, dmap = _building_scene(), np.full((GH, GW), 8.0)
    frame = {"horizon": HORIZON, "depthScale": 1.0, "ego": {}, "dcorr": REP}
    cols = np.arange(100, 140) + 0.5
    ground = groundfuse.ground_m(GEO, np.full(cols.shape, 101.0), cols, HORIZON, REP)[0]
    for mode, expect in (("depth", np.full(40, 8.0)), ("ground-contact", ground), ("ground+depth", ground)):
        _, _, dist, _ = _observer(mode, True, "fisheye").object_bases(grid, frame, dmap)
        assert dist.size == 40 and np.allclose(dist, expect, atol=0.25 if mode == "ground+depth" else 1e-6), mode
    _, _, dist, _ = _observer("ground+depth", True, "fisheye").object_bases(grid, {**frame, "dcorr": None}, dmap)      # no curve (no ref yet): the depth
    assert np.allclose(dist, 8.0)


def test_horizon_off_the_map_uses_only_depth_for_bases_and_surfaces():
    grid, dmap = _building_scene(), np.full((GH, GW), 8.0)
    frame = {"horizon": HORIZON, "depthScale": 1.0, "ego": {}, "dcorr": REP}
    off = _observer("ground+depth", False)
    assert np.allclose(off.object_bases(grid, frame, dmap)[2], 8.0)
    assert off.object_bases(grid, {**frame, "depthScale": None}, None)[0].size == 0            # no depth, no horizon: no distance at all
    # surfaces through the depth map: a flat floor with the pitch of the horizon, z-depths from the exact ray / plane intersection
    phi = math.atan((0.5 - HORIZON) * GH / F_PX)
    rows = np.arange(GH)[:, None] * np.ones((1, GW))
    yn = (rows + 0.5 - GH / 2.0) / F_PX
    z = np.where(yn * math.cos(phi) + math.sin(phi) > 1e-3, CAM_H / np.maximum(yn * math.cos(phi) + math.sin(phi), 1e-3), 0.0)
    grid = np.full((GH, GW), SKY, dtype=np.uint8)
    grid[rows > GH * HORIZON + 5] = SW
    frame = {"horizon": HORIZON, "depthScale": 1.0, "ego": {"depthPitchDeg": math.degrees(phi)}, "dcorr": None}
    obs, w = off.observe(grid, frame, np.where(z > 0, z, 1.0))
    ref, _ = _observer("depth", True).observe(grid, frame, np.where(z > 0, z, 1.0))
    ahead = np.arange(30, 70)                                                                 # 3-7 m ahead on the centre line
    cells = off.orow - ahead
    assert (obs[cells, off.oc] == SW).mean() > 0.9 and (ref[cells, off.oc] == SW).mean() > 0.9
    both = (obs != worldmap.UNKNOWN) & (ref != worldmap.UNKNOWN)
    assert both.sum() > 500 and (obs[both] == ref[both]).all()


# ---------------------------------------------------------------- the Lab

REC = {"id": "rec1", "duration": 100.0, "width": 320, "height": 180, "fps": 10.0, "chapters": [], "name": "rec1"}
URL = "/api/recordings/rec1/settings"


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings, "get_recording", lambda i: REC if i == "rec1" else None)
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    return tmp_path


def test_lab_settings_carry_object_distance_and_horizon(fake):
    c = TestClient(server.app)
    got = c.get(URL).json()
    assert (got["objectDistance"], got["useHorizon"]) == ("depth", True)
    assert (got["resolved"]["objectDistance"], got["resolved"]["useHorizon"]) == ("depth", True)
    put = c.put(URL, json={"objectDistance": "ground-contact", "useHorizon": False}).json()
    assert (put["objectDistance"], put["useHorizon"]) == ("ground-contact", False)
    assert (put["resolved"]["objectDistance"], put["resolved"]["useHorizon"]) == ("ground-contact", False)
    again = c.get(URL).json()
    assert (again["objectDistance"], again["useHorizon"]) == ("ground-contact", False)
    assert c.put(URL, json={}).json()["objectDistance"] == "depth"
    for bad in ({"objectDistance": "radar"}, {"useHorizon": "no"}, {"useHorizon": 0}):
        assert c.put(URL, json=bad).status_code == 422


def test_collision_pass_passes_the_two_settings_on(fake, monkeypatch):
    (fake / "runs" / "0123456789ab").mkdir(parents=True)
    d = fake / "runs" / "0123456789ab"
    (d / "run.json").write_text(json.dumps({"id": "0123456789ab", "request": {"recording": "rec1"}, "status": "done", "classNames": ["a"]}))
    np.savez(d / "grids.npz", grids=np.zeros((3, 135, 240), np.uint8), t=np.arange(3.0), index=np.arange(3))
    recordings.save_settings("rec1", {**recordings.get_settings("rec1", "chest"), "objectDistance": "ground-contact", "useHorizon": False})
    seen = {}
    real = col.run_collision

    def spy(grids, times, names, config, settings, *a, **k):
        seen["s"] = settings
        return real(grids, times, names, config, settings, *a, **k)

    monkeypatch.setattr(col, "run_collision", spy)
    analysis.collision_pass("0123456789ab")
    assert (seen["s"].object_distance, seen["s"].use_horizon) == ("ground-contact", False)
    hz = json.loads((d / "hazards.json").read_text())
    assert (hz["settings"]["objectDistance"], hz["settings"]["useHorizon"]) == ("ground-contact", False)
