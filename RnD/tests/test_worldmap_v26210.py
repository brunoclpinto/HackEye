"""v26.2.10 (plan A): the map keeps facts only: seen cells, no time decay, confrontation, nothing past 20 m, no gap closing, pose alignment."""
import math

import numpy as np
import pytest

import collision
import worldmap
from collision import focal_px

NAMES = ["flat sidewalk", "building", "pole", "person", "nature sky", "flat road"]
SW, BLD, POLE, PERSON, SKY, ROAD = range(6)
GH, GW, HFOV, CAM_H, HORIZON = 135, 240, 118.0, 1.3, 0.45
FPS = 6.0
UNK = worldmap.UNKNOWN


def _cfg(**over):
    return {**worldmap.load_config(), **over}


def _observer(**over):
    cfg = _cfg(**over)
    kind = worldmap.class_kinds(cfg, NAMES)
    return worldmap.Observer(cfg, {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "distanceSource": "ground"}, kind, GH, GW, None, NAMES)


def _fusion(ob, **over):
    cfg = {**ob.cfg, **over}
    return worldmap.Fusion(cfg, ob.kind, np.array([SW, BLD, ROAD]), (0.0, 0.0))


def _flat(cls):
    f = np.full((GH, GW), SKY, np.uint8)
    f[int(HORIZON * GH) + 1:] = cls
    return f


def _frame():
    return {"horizon": HORIZON, "scale": 1.0, "depthScale": None, "ego": {"speedMps": 0.0, "headingDeg": 0.0, "stationary": True}}


def test_a_cell_behind_a_person_is_not_seen_and_keeps_its_votes_for_30_seconds():
    ob = _observer()
    fu = _fusion(ob)
    pose = (0.0, 0.0, 0.0)
    clear = _flat(SW)
    obs, w = ob.observe(clear, _frame(), None)
    assert ob.seen[170:180, 95:105].all()
    fu.update(0.0, pose, obs, w, ob)
    person = clear.copy()
    person[70:135, 105:135] = PERSON                                          # a person standing in the middle of the view
    for k in range(1, 31 * 6):
        obs, w = ob.observe(person, _frame(), None)
        if k == 1:
            hidden = ~ob.seen & (ob.fwd > 3.0) & (ob.fwd < 12.0) & (np.abs(ob.right) < 0.3)
            assert hidden.sum() > 50                                          # the cells right behind the person are not seen
        fu.update(float(k) / FPS, pose, obs, w, ob)
    cls, conf = fu.snapshot(30.0, pose, ob)
    assert (cls[hidden] == SW).all() and (conf[hidden] > 0).all()
    assert fu.votes[0][fu.votes[0] > 0].max() <= 6.0 + 1e-4                  # the cap


def test_a_stored_road_that_is_seen_as_sidewalk_for_two_frames_is_sidewalk():
    ob = _observer()
    fu = _fusion(ob)
    pose = (0.0, 0.0, 0.0)
    for k in range(30):                                                      # a long history of road: the cap bounds it
        obs, w = ob.observe(_flat(ROAD), _frame(), None)
        fu.update(k / FPS, pose, obs, w, ob)
    cell = (np.abs(ob.fwd - 4.0) < 0.06) & (np.abs(ob.right) < 0.3)
    assert (fu.snapshot(5.0, pose, ob)[0][cell] == ROAD).all()
    for k in range(2):
        obs, w = ob.observe(_flat(SW), _frame(), None)
        fu.update(6.0 + k / FPS, pose, obs, w, ob)
    assert (fu.snapshot(6.4, pose, ob)[0][cell] == SW).all()
    # without the confrontation (v26.2.9 add-up) the old class still wins
    fu2 = _fusion(ob, conflictFactor=1.0, voteCap=0.0)
    for k in range(30):
        obs, w = ob.observe(_flat(ROAD), _frame(), None)
        fu2.update(k / FPS, pose, obs, w, ob)
    for k in range(2):
        obs, w = ob.observe(_flat(SW), _frame(), None)
        fu2.update(6.0 + k / FPS, pose, obs, w, ob)
    assert (fu2.snapshot(6.4, pose, ob)[0][cell] == ROAD).all()


def test_votes_do_not_decay_with_time_unless_asked_to():
    ob = _observer()
    obs, w = ob.observe(_flat(SW), _frame(), None)
    for decay, expect_known in (("none", True), ("time", False)):
        fu = _fusion(ob, decay=decay)
        fu.update(0.0, (0.0, 0.0, 0.0), obs, w, ob)
        cls, _ = fu.snapshot(1000.0, (0.0, 0.0, 0.0), ob)
        assert bool((cls[100, 100] == SW)) is expect_known


def test_nothing_is_observed_past_the_range_and_gap_closing_is_off():
    ob = _observer()
    obs, _ = ob.observe(_flat(SW), _frame(), None)
    assert ob.max_range == 20.0 and ob.size * ob.cell == 20.0
    assert not (obs[ob.fwd > 20.0] != UNK).any() and not ob.seen[ob.fwd > 20.0].any()
    assert ob.gap_tab is None and ob.cfg["gapCloseM"] == 0.0 and ob.cfg["faceThicknessM"] <= 0.1 and ob.cfg["hiddenThicknessM"] == 0.3
    assert ob.cfg["decay"] == "none" and ob.cfg["conflictFactor"] == 0.4 and ob.cfg["voteCap"] == 6.0


def _scene(wx, wy):
    cls = np.full(wx.shape, SW, np.uint8)
    cls[(np.floor(wx / 1.5) + np.floor(wy / 1.5)) % 2 == 0] = ROAD                    # a checker board: structure everywhere
    return cls


def _render(x, y, heading):
    f = focal_px(GW, HFOV)
    th = math.radians(heading)
    grid = np.full((GH, GW), SKY, np.uint8)
    rows, cols = np.mgrid[0:GH, 0:GW]
    yb = (rows + 1.0) / GH
    below = yb > HORIZON + 1e-9
    d = np.where(below, CAM_H * f / (np.maximum(yb - HORIZON, 1e-9) * GH), 1.0)
    lat = (((cols + 0.5) / GW) - 0.5) * GW * d / f
    wx = x + math.sin(th) * d + math.cos(th) * lat
    wy = y + math.cos(th) * d - math.sin(th) * lat
    grid[below] = _scene(wx, wy)[below]
    return grid


def _walk(align: bool, err_deg: float, seconds=20.0):
    n = int(seconds * FPS)
    times = np.arange(n) / FPS
    grids = np.stack([_render(0.0, 1.2 * t, 0.0) for t in times])
    egos = [{"speedMps": 1.2, "headingDeg": (err_deg if t > 3.0 else 0.0), "stationary": False} for t in times]
    frames = [{"horizon": HORIZON, "scale": 1.0, "depthScale": None, "ego": e} for e in egos]
    settings = {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "lateralOffsetM": 0.0, "projection": "rectilinear", "distanceSource": "ground"}
    wm = worldmap.WorldMap(grids, times, NAMES, frames, settings, collision.load_config(), _cfg(poseAlign=align))
    for i in range(n):
        wm.step(i)
    return wm


def test_pose_alignment_recovers_a_heading_error_of_1_5_degrees():
    off = _walk(False, 1.5)
    on = _walk(True, 1.5)
    assert off.align_deg[-1] == 0.0 and np.all(off.align_m == 0.0)
    assert -1.75 <= on.align_deg[-1] <= -0.75                                  # the correction undoes most of the drift (the map's own noise is ~0.5 deg)
    assert abs(on.pose[-1, 2]) <= 0.75 and abs(off.pose[-1, 2] - 1.5) < 1e-9         # the map's heading is the true one again (within the noise)
    assert abs(on.pose[-1, 0]) < abs(off.pose[-1, 0]) + 0.3
