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
    assert math.sqrt(float(np.mean(resid ** 2))) < 0.25                      # a straight line (v26.2.4: 0.2 -> 0.25, the 18-20 m cells that the snapshot now holds are the blurriest)
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
    assert meta["exists"] and meta["frames"] == wm.n and meta["origin"] == [100, 200] and meta["width"] == 200
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
    # v26.2.4: the cell endpoint returns the surface and the object layer on their own; nothing behind the user
    cell = c.get(f"/api/runs/{run}/worldmap/cell?i=5&col=100&row=150").json()
    assert cell["layers"] and cell["aheadM"] == 5.0 and cell["rightM"] == 0.0 and cell["surface"] == SW and cell["object"] is None
    assert c.get(f"/api/runs/{run}/worldmap/cell?i=5&col=100&row=199").json()["aheadM"] == 0.1
    assert c.get(f"/api/runs/{run}/worldmap/cell?i=5&col=100&row=200").status_code == 422
    assert c.get(f"/api/runs/{run}/worldmap/cell?i={wm.n}&col=1&row=1").status_code == 404
    with np.load(d / "worldmap.npz") as z:
        assert z["surface"].shape == z["object"].shape == z["classes"].shape and list(z["origin"]) == [100, 200]
    pose = c.get(f"/api/runs/{run}/worldmap/pose.json").json()
    assert len(pose["pose"]) == wm.n and pose["pose"][-1][1] > 1.0
    (d / "hazards.json").unlink()
    assert c.post(f"/api/runs/{run}/worldmap").status_code == 404


def test_forward_only_snapshot_and_separate_layers():
    """v26.2.4: the user stands on the bottom edge (20 m ahead, nothing behind); an object keeps the surface under it in the surface layer."""
    def scene(wx, wy):
        out = np.full(wx.shape, SW, dtype=np.uint8)
        out[(np.abs(wx - 0.0) <= 0.4) & (np.abs(wy - 6.0) <= 0.3)] = POLE
        return out
    wm = make_map(scene, 3.0, stationary=True)
    o = wm.observer
    assert (o.oc, o.orow, o.size) == (100, 200, 200) and o.fwd.min() > 0.0 and abs(o.fwd.max() - 20.0) < 1e-6
    for i in range(wm.n):
        wm.step(i, layers=True)
    surf, objs = wm.last_layers
    _, classes, _, _ = wm.step(wm.n - 1, layers=True)
    ps = np.argwhere(objs == POLE)
    assert len(ps) >= 3
    r, c = ps[0]
    assert surf[r, c] in (SW, 255) and (classes == POLE).any()
    assert (surf[objs == 255] != POLE).all()
    # without layers the snapshot is exactly the combined classes (the collision rules read these)
    again = wm.fusion.snapshot(float(wm.times[-1]), wm.last_pose, o)
    assert (again[0] == classes).all()


# --- v26.2.5: wall faces, objects win their cells, frame-0 depth scale ---------------------------------------------

FACE_NAMES = ["flat sidewalk", "building", "pole", "person", "nature sky"]


def _face_observer(**over):
    cfg = {**worldmap.load_config(), **over}
    kind = worldmap.class_kinds(cfg, FACE_NAMES)
    settings = {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "lateralOffsetM": 0.0, "projection": "rectilinear", "distanceSource": "depth",
                "objectDistance": "depth"}
    return worldmap.Observer(cfg, settings, kind, GH, GW, None, FACE_NAMES)


def _facade(c0=60, c1=140, wall_m=10.0, seed=3):
    """A facade 10 m away: the building column stands on the sidewalk, its base row jitters by +-2 rows (segmentation noise), the depth map
    holds the wall's depth everywhere except the edge pixel of each run, which reads the (nearer) ground below it."""
    rng = np.random.RandomState(seed)
    grid = np.full((GH, GW), SKY, dtype=np.uint8)
    grid[70:, :] = SW
    depth = np.full((GH, GW), wall_m, dtype=np.float32)
    for c in range(c0, c1):
        base = 88 + int(rng.randint(-2, 3))
        grid[20:base + 1, c] = BLD
        depth[base, c] = 4.0
    frame = {"horizon": HORIZON, "scale": 1.0, "depthScale": 1.0, "ego": {}, "dcorr": None}
    return grid, depth, frame


def test_a_noisy_facade_is_one_continuous_line_at_the_wall_distance():
    ob = _face_observer()
    grid, depth, frame = _facade()
    rr, cc, dist, lat = ob.object_bases(grid, frame, depth)
    assert len(rr) >= 70 and np.all(np.abs(dist - 10.0) < 0.3)             # the edge pixel (4 m) no longer decides the distance
    obs, _ = ob.observe(grid, frame, depth)
    rows, cols = np.nonzero(obs == BLD)
    assert rows.size and np.all(np.abs((ob.orow - rows) * ob.cell - 10.0) < 0.6)
    line = np.unique(cols[np.abs((ob.orow - rows) * ob.cell - 10.0) < 0.2])
    assert line.size == line.max() - line.min() + 1                           # no gap along the facade


def test_an_outlier_column_is_dropped():
    ob = _face_observer()
    grid, depth, frame = _facade()
    depth[:, 100] = 20.0                                                       # one column reads twice the wall distance (a see-through)
    rr, cc, dist, _ = ob.object_bases(grid, frame, depth)
    assert 100 not in set(cc.tolist()) and 99 in set(cc.tolist()) and 101 in set(cc.tolist())
    assert np.all(np.abs(dist - 10.0) < 0.3)


def test_a_base_on_the_sky_is_dropped():
    ob = _face_observer()
    grid, depth, frame = _facade()
    grid[89:100, 80] = SKY                                                     # column 80: the building ends over the sky, not the ground
    rr, cc, _, _ = ob.object_bases(grid, frame, depth)
    assert 80 not in set(cc.tolist()) and 79 in set(cc.tolist())


def test_a_thin_wall_line_wins_its_cells_against_the_surface():
    def fusion(share):
        cfg = {**worldmap.load_config(), "objectWinShare": share}
        kind = worldmap.class_kinds(cfg, FACE_NAMES)
        ob = worldmap.Observer(cfg, {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "distanceSource": "ground"}, kind, GH, GW, None, FACE_NAMES)
        fu = worldmap.Fusion(cfg, kind, np.array([SW, BLD]), (0.0, 0.0))
        surf = np.full((ob.size, ob.size), worldmap.UNKNOWN, np.uint8)
        surf[100:180, 60:140] = SW
        wall = np.full((ob.size, ob.size), worldmap.UNKNOWN, np.uint8)
        wall[130:133, 60:140] = BLD
        for _ in range(3):                                                    # the surface is seen in 3 frames, the wall line in 2
            fu.update(0.0, (0.0, 0.0, 0.0), surf, np.full(surf.shape, 1.0, np.float32), ob)
        for _ in range(2):
            fu.update(0.0, (0.0, 0.0, 0.0), wall, np.full(wall.shape, 1.0, np.float32), ob)
        return fu.snapshot(0.0, (0.0, 0.0, 0.0), ob)
    cls, conf = fusion(0.35)                                                  # 2 of 5 votes = 0.4 of the cell
    assert (cls[131, 65:135] == BLD).all() and (cls[140:170, 65:135] == SW).all() and conf[131, 100] > 0
    cls, _ = fusion(0.0)                                                      # the old argmax: the surface hides the wall
    assert (cls[131, 65:135] == SW).all()


def test_a_frame_without_a_depth_scale_uses_the_nearest_one_of_the_run():
    wm = make_map(l_wall, 1.0)
    wm.frames[3]["depthScale"] = 0.4
    wm.first_ds = worldmap.first_depth_scale(wm.frames)
    assert wm.first_ds == 0.4
    assert wm.resolve_frame(wm.frames[0])["depthScale"] == 0.4                # offline: before the first known one, the first known one
    assert wm.resolve_frame(wm.frames[3])["depthScale"] == 0.4
    wm.frames[4]["depthScale"] = 0.5
    assert wm.resolve_frame(wm.frames[4])["depthScale"] == 0.5
    assert wm.resolve_frame(wm.frames[5])["depthScale"] == 0.5                # later gaps: the last known one
    online = make_map(l_wall, 1.0)
    online.first_ds = None
    assert online.resolve_frame(online.frames[0])["depthScale"] is None       # online, nothing known yet: none


def _clear_fusion(factor):
    cfg = {**worldmap.load_config(), "objectClearFactor": factor, "objectClearMarginM": 0.3, "objectClearRays": 0}
    kind = worldmap.class_kinds(cfg, FACE_NAMES)
    ob = worldmap.Observer(cfg, {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "distanceSource": "ground"}, kind, GH, GW, None, FACE_NAMES)
    return ob, worldmap.Fusion(cfg, kind, np.array([SW, BLD]), (0.0, 0.0))


def _obs(ob, ground=None, wall=None):
    o = np.full((ob.size, ob.size), worldmap.UNKNOWN, np.uint8)
    if ground:
        o[ground] = SW
    if wall:
        o[wall] = BLD
    return o


def test_a_stale_wall_is_cleared_after_a_few_frames_of_seen_ground():
    """v26.2.5 negative evidence: object votes in cells the camera now sees as ground shrink by objectClearFactor per frame."""
    ob, fu = _clear_fusion(0.3)
    one = np.ones((ob.size, ob.size), np.float32)
    for _ in range(2):
        fu.update(0.0, (0.0, 0.0, 0.0), _obs(ob, wall=(slice(130, 133), slice(60, 140))), one, ob)
    _, _, _, objs = fu.snapshot(0.0, (0.0, 0.0, 0.0), ob, True)
    assert (objs[131, 70:130] == BLD).all()                                    # the wall is on the map
    for n in range(4):                                                        # the ground is seen there, with no wall in the frame
        fu.update(0.0, (0.0, 0.0, 0.0), _obs(ob, ground=(slice(100, 180), slice(60, 140))), one, ob)
    _, _, _, objs = fu.snapshot(0.0, (0.0, 0.0, 0.0), ob, True)
    assert (objs[131, 70:130] == worldmap.UNKNOWN).all()                       # 2 x 0.3^4 is below the weight floor
    cls, _, surf, _ = fu.snapshot(0.0, (0.0, 0.0, 0.0), ob, True)
    assert (surf[140:170, 70:130] == SW).all()                                 # surface votes are untouched


def test_a_current_wall_line_and_its_margin_are_not_cleared_by_the_ground_beside_it():
    ob, fu = _clear_fusion(0.0)                                                # factor 0: a cleared cell loses every object vote at once
    one = np.ones((ob.size, ob.size), np.float32)
    fu.update(0.0, (0.0, 0.0, 0.0), _obs(ob, wall=(slice(116, 134), slice(60, 140))), one, ob)       # an older, thicker wall
    cur = _obs(ob, ground=(slice(100, 180), slice(60, 140)), wall=(slice(130, 133), slice(60, 140)))   # now: a thin line and ground around it
    fu.update(0.0, (0.0, 0.0, 0.0), cur, one, ob)
    _, _, _, objs = fu.snapshot(0.0, (0.0, 0.0, 0.0), ob, True)
    assert (objs[130:133, 70:130] == BLD).all()                                # the line itself
    assert (objs[128:130, 70:130] == BLD).all() and (objs[133:135, 70:130] == BLD).all()      # within the 0.3 m margin: kept
    assert (objs[118:124, 70:130] == worldmap.UNKNOWN).all()                   # further away, ground is seen: cleared


def test_a_face_clears_the_free_space_on_its_ray_even_where_no_ground_is_visible():
    cfg = {**worldmap.load_config(), "objectClearFactor": 0.0, "objectClearRays": 1}
    kind = worldmap.class_kinds(cfg, FACE_NAMES)
    ob = worldmap.Observer(cfg, {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "lateralOffsetM": 0.0, "projection": "rectilinear",
                                 "distanceSource": "depth", "objectDistance": "depth"}, kind, GH, GW, None, FACE_NAMES)
    fu = worldmap.Fusion(cfg, kind, np.array([SW, BLD]), (0.0, 0.0))
    stale = np.full((ob.size, ob.size), worldmap.UNKNOWN, np.uint8)
    stale[148:152, 60:130] = BLD                                               # a stale wall 5 m ahead
    fu.update(0.0, (0.0, 0.0, 0.0), stale, np.ones(stale.shape, np.float32), ob)
    grid, depth, frame = _facade(c0=100, c1=140)
    grid[:, :] = np.where(grid == SW, PERSON, grid)                            # no ground in the frame at all (a mover hides it)
    obs, w = ob.observe(grid, frame, depth)
    assert (obs == SW).sum() == 0 and (obs == BLD).any()
    fu.update(0.1, (0.0, 0.0, 0.0), obs, w, ob)
    _, _, _, objs = fu.snapshot(0.1, (0.0, 0.0, 0.0), ob, True)
    assert (objs[149:151, 95:105] != BLD).all()                               # on the face's rays: cleared
    assert (objs[149:151, 62:75] == BLD).all()                                 # off the rays: kept
