"""World map spike (v26.2 step 1): synthetic scenes rendered with the collision pass's own ground geometry."""
import math

import numpy as np
import pytest

import collision
import worldmap
from collision import focal_px

NAMES = ["flat sidewalk", "building", "pole", "person", "nature sky"]
SW, BLD, POLE, PERSON, SKY = range(5)
GH, GW, HFOV, CAM_H, HORIZON = 135, 240, 118.0, 1.3, 0.45
FPS = 6.0


def render(scene, x, y, heading_deg):
    """Class grid seen from (x, y, heading): ground pixels take the scene's class at their ground point; every column
    above its lowest building / pole pixel is filled with it (a standing object), the rest above the horizon is sky."""
    f = focal_px(GW, HFOV)
    th = math.radians(heading_deg)
    grid = np.full((GH, GW), SKY, dtype=np.uint8)
    rows, cols = np.mgrid[0:GH, 0:GW]
    yb = (rows + 1.0) / GH
    below = yb > HORIZON + 1e-9
    d = np.where(below, CAM_H * f / (np.maximum(yb - HORIZON, 1e-9) * GH), 1.0)
    lat = (((cols + 0.5) / GW) - 0.5) * GW * d / f
    wx = x + math.sin(th) * d + math.cos(th) * lat
    wy = y + math.cos(th) * d - math.sin(th) * lat
    cls = scene(wx, wy)
    grid[below] = cls[below]
    for c in range(GW):
        col = grid[:, c]
        objs = np.flatnonzero(np.isin(col, (BLD, POLE)))
        if objs.size:
            lowest = objs.max()
            col[:lowest] = col[lowest]
    return grid


def make_map(scene, seconds, speed=1.2, heading=0.0, stationary=False):
    n = int(seconds * FPS)
    times = np.arange(n) / FPS
    grids = np.stack([render(scene, 0.0, 0.0 if stationary else speed * t, heading) for t in times])
    egos = [{"speedMps": 0.0 if stationary else speed, "headingDeg": heading, "stationary": stationary} for _ in times]
    frames = [{"horizon": HORIZON, "scale": 1.0, "depthScale": None, "ego": e} for e in egos]
    settings = {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "lateralOffsetM": 0.0, "projection": "rectilinear",
                "distanceSource": "ground"}
    wm = worldmap.WorldMap(grids, times, NAMES, frames, settings, collision.load_config(), worldmap.load_config())
    return wm


def run_all(wm):
    snaps = []
    for i in range(wm.n):
        obs, classes, conf, ms = wm.step(i)
        snaps.append((obs, classes, conf))
    return snaps


def to_world(wm, i, rows, cols):
    o = wm.observer
    f, r = (o.orow - rows) * o.cell, (cols - o.oc) * o.cell
    x, y, th = wm.pose[i][0], wm.pose[i][1], math.radians(wm.pose[i][2])
    return x + math.sin(th) * f + math.cos(th) * r, y + math.cos(th) * f - math.sin(th) * r


def l_wall(wx, wy):
    out = np.full(wx.shape, SW, dtype=np.uint8)
    out[(np.abs(wx - 2.5) <= 0.15) & (wy >= 0)] = BLD                   # wall along the right, x = 2.5
    out[(np.abs(wy - 9.0) <= 0.15) & (wx >= -0.5) & (wx <= 2.5)] = BLD   # a face across the corridor at y = 9
    return out


def test_straight_wall_and_corridor_face():
    wm = make_map(l_wall, 7.0)
    snaps = run_all(wm)
    i = wm.n - 1
    classes = snaps[i][1]
    rows, cols = np.nonzero(classes == BLD)
    wx, wy = to_world(wm, i, rows, cols)
    side = wx > 1.5
    assert side.sum() > 100
    assert abs(float(np.median(wx[side])) - 2.5) < 0.2
    pts = np.stack([wx[side], wy[side]], axis=1)
    c = pts - pts.mean(axis=0)
    resid = c @ np.linalg.svd(c, full_matrices=False)[2][1]
    assert math.sqrt(float(np.mean(resid ** 2))) < 0.2                       # a straight line
    j = int(5 * FPS)                                                         # 3 m before the face
    rows, cols = np.nonzero(snaps[j][1] == BLD)
    fx, fy = to_world(wm, j, rows, cols)
    face = fx < 1.5
    assert face.sum() >= 15
    assert abs(float(np.median(fy[face])) - 9.0) < 0.5                       # the face stands across the corridor at 9 m
    assert fx[face].min() < -0.2 and fx[face].max() > 1.0                    # and spans the +-0.6 m corridor


def test_pole_stays_in_one_place():
    def scene(wx, wy):
        out = np.full(wx.shape, SW, dtype=np.uint8)
        out[(np.abs(wx - 1.0) <= 0.15) & (np.abs(wy - 8.0) <= 0.5)] = POLE
        return out
    wm = make_map(scene, 6.0)
    seen = []
    for i in range(wm.n):
        _, classes, _, _ = wm.step(i)
        rows, cols = np.nonzero(classes == POLE)
        if rows.size >= 3:
            wx, wy = to_world(wm, i, rows, cols)
            seen.append((float(np.mean(wx)), float(np.mean(wy))))
    assert len(seen) >= 10
    xy = np.array(seen)
    assert xy[:, 0].std() < 0.15 and xy[:, 1].std() < 0.3
    assert abs(xy[:, 0].mean() - 1.0) < 0.3 and abs(xy[:, 1].mean() - 8.0) < 0.6


def test_mover_is_not_mapped():
    def scene(wx, wy):
        out = np.full(wx.shape, SW, dtype=np.uint8)
        out[(np.abs(wx) <= 0.5) & (np.abs(wy - 6.0) <= 0.5)] = PERSON
        return out
    wm = make_map(scene, 3.0, stationary=True)
    snaps = run_all(wm)
    assert (snaps[0][0] == PERSON).sum() == 0 and all((s[1] == PERSON).sum() == 0 for s in snaps)
    assert not np.isin(PERSON, wm.fusion.classes)
    o = wm.observer
    r, c = o.orow - 60, o.oc                          # 6 m ahead on the line of the person: no sidewalk invented under it
    assert snaps[-1][1][r, c] == worldmap.UNKNOWN
    assert snaps[-1][1][o.orow - 30, o.oc] == SW      # the ground in front of it is mapped


def test_stationary_pose_does_not_drift():
    wm = make_map(lambda wx, wy: np.full(wx.shape, SW, dtype=np.uint8), 5.0, stationary=True)
    assert np.allclose(wm.pose[:, :2], 0.0)
    assert np.allclose(wm.pose[:, 2], 0.0)


def test_pose_matches_world_memory():
    times = np.arange(60) / FPS
    egos = [{"speedMps": 1.3, "headingDeg": 3.0 * t, "stationary": bool(i > 40)} for i, t in enumerate(times)]
    pose = worldmap.integrate_pose(times, egos, collision.load_config())
    wm = collision._WorldMemory(collision.load_config()["memory"])
    for i, (t, e) in enumerate(zip(times, egos)):
        wm.advance(float(t), 0.0 if i == 0 else float(t - times[i - 1]), 0.0 if e["stationary"] else e["speedMps"], e["headingDeg"])
    assert (pose[-1, 0], pose[-1, 1]) == pytest.approx((wm.x, wm.y))
    assert pose[41:, :2].std(axis=0).max() == pytest.approx(0.0, abs=1e-9) or np.allclose(pose[41:, :2], pose[41, :2])


def test_votes_decay_and_unknown_floor():
    cfg = worldmap.load_config()
    kind = worldmap.class_kinds(cfg, NAMES)
    fu = worldmap.Fusion(cfg, kind, np.array([SW, BLD]), (0.0, 0.0))
    ob = worldmap.Observer(cfg, {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "distanceSource": "ground"}, kind, GH, GW)
    obs = np.full((ob.size, ob.size), worldmap.UNKNOWN, np.uint8)
    obs[169:172, 99:102] = BLD
    w = np.where(obs != worldmap.UNKNOWN, 1.0, 0.0).astype(np.float32)
    fu.update(0.0, (0.0, 0.0, 0.0), obs, w, ob)
    cls0, _ = fu.snapshot(0.0, (0.0, 0.0, 0.0), ob)
    assert cls0[170, 100] == BLD
    cls1, _ = fu.snapshot(40.0, (0.0, 0.0, 0.0), ob)          # ~7 half-lives later: below the floor
    assert cls1[170, 100] == worldmap.UNKNOWN


# --- Lab endpoints ------------------------------------------------------------------------------------------------

def test_worldmap_endpoints(tmp_path, monkeypatch):
    import json

    import cv2
    from fastapi.testclient import TestClient

    from lab import analysis, server

    run = "0123456789ab"
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    monkeypatch.setattr(server, "_wm_cache", server.OrderedDict())
    d = tmp_path / "runs" / run
    d.mkdir(parents=True)
    wm = make_map(l_wall, 2.0)
    np.savez(d / "grids.npz", grids=wm.grids, t=wm.times, index=np.arange(wm.n, dtype=np.int32))
    hazards = {"settings": {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "lateralOffsetM": 0.0}, "projection": "rectilinear",
               "distanceSource": "ground", "frames": [{"t": float(t), "horizonY": HORIZON, "ego": f["ego"]} for t, f in zip(wm.times, wm.frames)]}
    (d / "hazards.json").write_text(json.dumps(hazards))
    (d / "run.json").write_text(json.dumps({"id": run, "request": {"recording": "x"}, "status": "done", "classNames": NAMES}))
    c = TestClient(server.app)
    assert c.get(f"/api/runs/{run}/worldmap").json() == {"exists": False}
    assert c.get(f"/api/runs/{run}/worldmap/0.png").status_code == 404
    r = c.post(f"/api/runs/{run}/worldmap")
    assert r.status_code == 200 and r.json()["frames"] == wm.n
    meta = c.get(f"/api/runs/{run}/worldmap").json()
    assert meta["exists"] and meta["frames"] == wm.n and meta["origin"] == [100, 180] and meta["width"] == 200
    assert meta["cellM"] == pytest.approx(0.1)
    png = c.get(f"/api/runs/{run}/worldmap/5.png")
    img = cv2.imdecode(np.frombuffer(png.content, np.uint8), cv2.IMREAD_UNCHANGED)
    assert img.shape == (200, 200, 4)
    known = img[:, :, 3] == 255
    assert known.any() and set(np.unique(img[:, :, 2][known])) <= {SW, BLD}                  # red channel = class id
    assert (img[:, :, 3][~known] == 0).all()
    gray = cv2.imdecode(np.frombuffer(c.get(f"/api/runs/{run}/worldmap/5.png?alpha=gray").content, np.uint8), cv2.IMREAD_UNCHANGED)
    assert gray.shape == (200, 200) and ((gray == 255) == ~known).all()
    assert c.get(f"/api/runs/{run}/worldmap/{wm.n}.png").status_code == 404
    pose = c.get(f"/api/runs/{run}/worldmap/pose.json").json()
    assert len(pose["pose"]) == wm.n and pose["pose"][-1][1] > 1.0
    (d / "hazards.json").unlink()
    assert c.post(f"/api/runs/{run}/worldmap").status_code == 404
