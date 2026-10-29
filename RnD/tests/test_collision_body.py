"""Body settings (height / camera location / side) and the plane depth anchor (``anchor: "plane"``)."""

from __future__ import annotations

import copy
import dataclasses
import math

import numpy as np
import pytest

import collision as col
from tests.test_collision import CONFIG, FPS, H, HFOV, NAMES, SETTINGS, W, base_grid, hz, motion, place, run
from tests.test_collision_depth import DH, DW

HC_REAL = 1.28
HEIGHT = CONFIG["body"]["defaultUserHeightM"]      # user height 1.78 m, user correction 2026-10-25 (was 1.70)


# --- body settings -> geometry ------------------------------------------------------------------------

def test_body_settings_resolution():
    s = col.resolve_settings(CONFIG, user_height_m=1.78, camera_location="chest", camera_side="center")
    assert s.camera_height_m == pytest.approx(1.2816) and s.step_length_m == pytest.approx(0.7387)
    assert s.horizon_default == 0.45 and s.lateral_offset_m == 0.0
    assert (s.user_height_m, s.camera_location, s.camera_side) == (1.78, "chest", "center")
    h = col.resolve_settings(CONFIG, user_height_m=1.78, camera_location="head", camera_side="right")
    assert h.camera_height_m == pytest.approx(1.78 + 0.05) and h.horizon_default == 0.48
    assert h.lateral_offset_m == pytest.approx(0.07)
    assert HEIGHT == 1.78
    w = col.resolve_settings(CONFIG, camera_location="waist", camera_side="left")        # the default height (config: 1.78 m, user correction 2026-10-25)
    assert w.camera_height_m == pytest.approx(0.58 * HEIGHT) and w.lateral_offset_m == pytest.approx(-0.15)
    assert w.step_length_m == pytest.approx(0.415 * HEIGHT)
    e = col.resolve_settings(CONFIG, user_height_m=1.60, camera_side="right")            # location defaults to chest
    assert e.camera_location == "chest" and e.camera_height_m == pytest.approx(0.72 * 1.60)
    assert e.lateral_offset_m == pytest.approx(0.15)


def test_explicit_values_win_over_body_geometry():
    s = col.resolve_settings(CONFIG, camera_height_m=1.1, step_length_m=0.6, user_height_m=1.78, camera_location="eye")
    assert s.camera_height_m == 1.1 and s.step_length_m == 0.6 and s.horizon_default == 0.50


def test_legacy_mount_mode_is_unchanged():
    s = col.resolve_settings(CONFIG, "head", 118.0)
    assert (s.camera_height_m, s.horizon_default, s.step_length_m) == (1.65, 0.40, None)
    assert s.lateral_offset_m == 0.0 and s.user_height_m is None and s.camera_location is None


# --- side offset ---------------------------------------------------------------------------------------

def _pole_frames(lat, w=0.2, seconds=6.0):
    base = base_grid(half_w_m=3.0)
    frames = []
    for i in range(int(seconds * FPS)):
        g = base.copy()
        place(g, "pole", 12.0 - 1.4 * i / FPS, lat, w, 3.0)
        frames.append(g)
    return frames


def test_center_body_mode_equals_legacy_geometry():
    body = col.resolve_settings(CONFIG, hfov_deg=HFOV, user_height_m=1.78, camera_location="chest")
    legacy = dataclasses.replace(SETTINGS, camera_height_m=body.camera_height_m, step_length_m=body.step_length_m)
    frames = _pole_frames(0.3)
    a, ea = run(frames, mot=motion(6.0), settings=body)
    b, eb = run(frames, mot=motion(6.0), settings=legacy)
    assert ea == eb
    a["settings"], b["settings"] = None, None
    assert a == b


def test_side_offset_moves_items_into_and_out_of_the_lane():
    def go(lat, off):
        s = dataclasses.replace(SETTINGS, lateral_offset_m=off)
        doc, ev = run(_pole_frames(lat), settings=s)
        return doc, ev

    def danger(doc):
        return any(h["role"] == "danger" for _, h in hz(doc, "pole"))

    d0, _ = go(0.8, 0.0)
    assert not danger(d0)
    dl, _ = go(0.8, -0.15)                       # camera left of the body centre: the item is closer to the centre line
    assert danger(dl)
    dr, _ = go(-0.8, +0.15)
    assert danger(dr) and not danger(go(-0.8, 0.0)[0])
    # lateralM = camera lateral + offset, everything else unchanged
    for (t, a), (_, b) in zip(hz(d0, "pole"), hz(dl, "pole")):
        assert b["lateralM"] - a["lateralM"] == pytest.approx(-0.15, abs=0.011)
        assert a["distanceM"] == b["distanceM"] and a["bearingDeg"] == b["bearingDeg"] and a["clock"] == b["clock"]
    assert dl["settings"]["lateralOffsetM"] == -0.15
    # the drawn lane follows the body centre
    lane0, lane_l = d0["frames"][0]["lane"], dl["frames"][0]["lane"]
    assert lane_l[0][0] > lane0[0][0] and lane_l[1][0] > lane0[1][0]
    assert lane_l[0][1] == lane0[0][1] == 1.0


def test_hazards_settings_report_the_body():
    s = col.resolve_settings(CONFIG, hfov_deg=HFOV, user_height_m=1.78, camera_location="chest", camera_side="right")
    doc, _ = run(_pole_frames(0.0, seconds=1.0), settings=s)
    st = doc["settings"]
    assert (st["userHeightM"], st["cameraLocation"], st["cameraSide"], st["lateralOffsetM"]) == (1.78, "chest", "right", 0.15)


# --- plane anchor ----------------------------------------------------------------------------------------

def _rays(projection):
    j, i = np.meshgrid(np.arange(DW), np.arange(DH))
    px, py = (j + 0.5) * W / DW - W / 2, (i + 0.5) * H / DH - H / 2
    if projection == "fisheye":
        f = W / math.radians(HFOV)
        r = np.hypot(px, py)
        th = r / f
        k = np.where(r > 0, np.tan(th) / np.maximum(r, 1e-9), 0.0)
        return px * k, py * k
    f = col.focal_px(W, HFOV)
    return px / f, py / f


def ground_z(projection, hc=HC_REAL, pitch_deg=10.0):
    """z-depth of a flat ground plane for a camera ``hc`` high pitched down ``pitch_deg``."""
    xn, yn = _rays(projection)
    ta = math.tan(math.radians(pitch_deg))
    c = hc / math.cos(math.radians(pitch_deg))
    den = yn + ta
    return np.where(den > 0.02, c / np.maximum(den, 0.02), 300.0)


def plane_doc(n, projection, bias=2.2, noise=0.04, seed=5, pitch=10.0, hc=HC_REAL, pole=None, wall=False, bad=lambda i: False):
    rng = np.random.RandomState(seed)
    z0 = ground_z(projection, hc, pitch)
    maps = np.empty((n, DH, DW), dtype=np.float32)
    for i in range(n):
        z = z0.copy()
        if wall:                                   # a vertical wall on the left third of the lower image
            z[40:, :38] = 4.0
        if pole is not None:
            z[pole(i)[1]] = pole(i)[0]
        m = z * bias * (1 + noise * rng.uniform(-1, 1))
        if bad(i) == "empty":
            m[:] = np.nan
        elif bad(i) == "steep":
            m = ground_z(projection, hc, 60.0) * bias
        maps[i] = m
    return {"t": np.arange(n) / FPS, "depth": maps, "units": "metric", "anchor": "plane"}


def plane_settings(projection, **kw):
    return dataclasses.replace(SETTINGS, camera_height_m=HC_REAL, projection=projection, distance_source="depth", **kw)


LENS_RAYS = copy.deepcopy(CONFIG)
LENS_RAYS["distance"]["depthRayModel"] = "lens"      # back-project with the real lens (synthetic maps hold true geometry)
PINHOLE_RAYS = copy.deepcopy(CONFIG)
PINHOLE_RAYS["distance"]["depthRayModel"] = "pinhole"


def plane_run(doc, frames, projection, mot=None, **kw):
    return col.run_collision(np.stack(frames), np.arange(len(frames)) / FPS, NAMES, kw.pop("config", LENS_RAYS),
                             plane_settings(projection, **kw), mot, doc)


def static_frames(n):
    return [base_grid(half_w_m=3.0) for _ in range(n)]


@pytest.mark.parametrize("projection", ["rectilinear", "fisheye"])
def test_plane_anchor_recovers_scale_pitch_and_freezes(projection):
    n = 14
    frames = static_frames(n)
    # a pole 8 m away (true z): the map holds 8 * bias there
    from tests.test_collision import ID
    for g in frames:
        g[100:120, 116:124] = ID["pole"]
    zs = ground_z(projection)[55, 60]
    doc, _ = plane_run(plane_doc(n, projection, pole=lambda i: (zs, (slice(50, 60), slice(58, 62)))), frames, projection)
    egs = [f["ego"] for f in doc["frames"]]
    assert all(e["depthAnchorMode"] == "plane" for e in egs)
    assert egs[0]["depthAnchor"] is None and egs[1]["depthAnchor"] is None
    assert egs[2]["depthAnchor"] == pytest.approx(1 / 2.2, rel=0.05)           # usable from the 3rd valid frame
    assert egs[2]["depthPitchDeg"] == pytest.approx(10.0, abs=2.0)
    assert egs[2]["depthCameraHeightUnits"] == pytest.approx(HC_REAL * 2.2, rel=0.05)
    assert len({e["depthAnchor"] for e in egs[5:]}) == 1                        # frozen at the 6th valid frame
    assert egs[-1]["depthPitchDeg"] == pytest.approx(10.0, abs=2.0)
    assert egs[5]["depthScale"] == egs[5]["depthAnchor"] and egs[5]["depthScaleSource"] == "plane"
    assert egs[5]["depthLevel"] == 1.0
    got = [h["depthM"] for f in doc["frames"][2:] for h in f["hazards"] if h["className"] == "pole"]
    assert got and all(d == pytest.approx(zs, rel=0.10) for d in got)


@pytest.mark.parametrize("projection", ["rectilinear", "fisheye"])
def test_first_frames_carry_the_depth_scale_of_their_own_plane_fit(projection):
    """v26.2.5: the anchor itself is usable from the 3rd valid frame, but frames 0-1 report the scale of their own fit (the world map reads
    it; without it the first facade was placed by the horizon alone)."""
    doc, _ = plane_run(plane_doc(8, projection), static_frames(8), projection)
    egs = [f["ego"] for f in doc["frames"]]
    assert egs[0]["depthAnchor"] is None and egs[1]["depthAnchor"] is None          # the anchor and everything else is unchanged
    for e in egs[:2]:
        assert e["depthScale"] == pytest.approx(1 / 2.2, rel=0.08)
    assert egs[2]["depthScale"] == pytest.approx(egs[0]["depthScale"], rel=0.08)


@pytest.mark.parametrize("projection", ["rectilinear", "fisheye"])
def test_wall_clutter_is_rejected_as_outliers(projection):
    frames = static_frames(10)
    clean, _ = plane_run(plane_doc(10, projection, noise=0.0), frames, projection)
    wall, _ = plane_run(plane_doc(10, projection, noise=0.0, wall=True), frames, projection)
    a, b = clean["frames"][-1]["ego"], wall["frames"][-1]["ego"]
    assert b["depthAnchor"] is not None
    assert b["depthAnchor"] == pytest.approx(a["depthAnchor"], rel=0.03)
    assert b["depthPitchDeg"] == pytest.approx(10.0, abs=2.0)


def test_invalid_frames_do_not_count():
    frames = static_frames(12)
    bad = {0: "empty", 1: "steep", 3: "empty", 4: "steep"}
    doc, _ = plane_run(plane_doc(12, "rectilinear", bad=lambda i: bad.get(i, False)), frames, "rectilinear")
    a = [f["ego"]["depthAnchor"] for f in doc["frames"]]
    assert a[5] is None and a[6] is not None                    # valid frames: 2, 5, 6 -> usable at index 6
    assert a[6] == pytest.approx(1 / 2.2, rel=0.05)


def test_plane_fit_validity_unit():
    frames = static_frames(1)
    from tests.test_collision import ID
    from collision import walking_region
    ids = col.resolve_class_ids(CONFIG, NAMES)
    region = walking_region(frames[0], ids, CONFIG)
    f = col.focal_px(W, HFOV)
    dist = CONFIG["distance"]
    fit = col._plane_fit(region, ground_z("rectilinear") * 2.0, 0.45, H, W, f, 8, HFOV, "rectilinear", dist)
    assert fit is not None and fit.fraction > 0.95 and fit.height_units == pytest.approx(2 * HC_REAL, rel=0.02)
    assert col._plane_fit(None, ground_z("rectilinear"), 0.45, H, W, f, 8, HFOV, "rectilinear", dist) is None
    assert col._plane_fit(region, np.full((DH, DW), np.nan), 0.45, H, W, f, 8, HFOV, "rectilinear", dist) is None
    assert col._plane_fit(region, ground_z("rectilinear", pitch_deg=60.0), 0.45, H, W, f, 8, HFOV, "rectilinear", dist) is None
    noise = np.random.RandomState(1).uniform(1, 30, (DH, DW))                  # no plane at all
    assert col._plane_fit(region, noise, 0.45, H, W, f, 8, HFOV, "rectilinear", dist) is None
    a = col._PlaneAnchor(dist, 1.28)
    for h in (2.0, 2.0, 2.0):
        a.update(col._PlaneFit(h, 5.0, 500, 0.9))
    assert a.value == pytest.approx(0.64) and a.pitch_deg == 5.0
    for h in (2.0, 2.0, 2.0, 99.0):
        a.update(col._PlaneFit(h, 5.0, 500, 0.9))
    assert a.frozen and a.value == pytest.approx(0.64)
    a.reset()
    assert a.value is None


def test_level_mode_for_plane_is_none():
    assert CONFIG["distance"]["levelModeByAnchor"]["plane"] == "none"


def test_gait_check_is_reported_but_never_applied():
    secs = 12.0
    n = int(secs * FPS)
    v = 1.8 * 0.70
    base = base_grid(half_w_m=3.0, hc=HC_REAL)
    from tests.test_collision import ID
    frames, zs = [], []
    z0 = ground_z("rectilinear")
    for i in range(n):
        g = base.copy()
        d = 22.0 - v * i / FPS
        place(g, "pole", d, 0.0, 0.6, 3.0, hc=HC_REAL)
        frames.append(g)
        zs.append(d)
    rows = np.minimum(H - 1, ((np.arange(DH) + 0.5) / DH * H).astype(int))
    cols_ = np.minimum(W - 1, ((np.arange(DW) + 0.5) / DW * W).astype(int))
    doc = plane_doc(n, "rectilinear", noise=0.0)
    for i in range(n):
        m = frames[i][rows][:, cols_] == ID["pole"]
        doc["depth"][i][m] = zs[i] * 2.2

    def go(step):
        return plane_run(doc, frames, "rectilinear", mot=motion(secs), step_length_m=step)[0]

    a, b = go(0.70), go(1.40)                    # b: walking says twice the speed, the camera height does not change
    ca = [f["ego"]["depthGaitCheck"] for f in a["frames"]]
    cb = [f["ego"]["depthGaitCheck"] for f in b["frames"]]
    assert ca[0] is None and ca[-1] == pytest.approx(1.0, rel=0.10)
    assert cb[-1] == pytest.approx(2.0, rel=0.10)
    for (_, x), (_, y) in zip(hz(a, "pole"), hz(b, "pole")):
        assert x["depthM"] == y["depthM"]
    d = [h["depthM"] for _, h in hz(a, "pole") if h["depthM"] is not None]
    assert d and d[-1] == pytest.approx(zs[len(d) - 1 + (n - len(d))], rel=0.1)


def test_other_anchor_modes_report_no_plane_keys():
    frames = static_frames(4)
    d = plane_doc(4, "rectilinear")
    d["anchor"] = "initial"
    doc, _ = plane_run(d, frames, "rectilinear")
    e = doc["frames"][-1]["ego"]
    assert e["depthAnchorMode"] == "initial" and e["depthPitchDeg"] is None and e["depthGaitCheck"] is None


def test_pinhole_depth_rays_option_for_a_fisheye_lens():
    """``depthRayModel: pinhole`` back-projects depth with pinhole rays whatever the lens: a fisheye-lens recording whose
    depth map follows pinhole geometry is anchored correctly; the default ``lens`` reads it with the fisheye model."""
    assert CONFIG["distance"]["depthRayModel"] == "lens"                 # default: the real lens (measured better on 4929)
    n = 10
    frames = static_frames(n)
    doc_map = plane_doc(n, "rectilinear", noise=0.0)                     # pinhole-geometry depth
    pin, _ = plane_run(doc_map, frames, "fisheye", config=PINHOLE_RAYS)
    lens, _ = plane_run(doc_map, frames, "fisheye", config=CONFIG)
    e = pin["frames"][-1]["ego"]
    assert e["depthAnchor"] == pytest.approx(1 / 2.2, rel=0.03) and e["depthPitchDeg"] == pytest.approx(10.0, abs=1.0)
    el = lens["frames"][-1]["ego"]
    assert el["depthAnchor"] is None or abs(el["depthPitchDeg"] - 10.0) > 1.0 or abs(el["depthAnchor"] * 2.2 - 1) > 0.03
