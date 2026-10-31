"""v26.2.7: the map through the lens, walls calibrate the depth, buildings block the view, gaps closed (plan docs/plans/v26.2.7.md)."""
import numpy as np
import pytest

import collision
import groundfuse
import worldmap

NAMES = ["flat sidewalk", "building", "pole", "person", "nature sky"]
SW, BLD, POLE, PERSON, SKY = range(5)
GH, GW, HFOV, CAM_H, HORIZON = 135, 240, 118.0, 1.28, 0.45
UNK = worldmap.UNKNOWN


def _geo(projection="fisheye", cam_h=CAM_H):
    return groundfuse.Geometry(GH, GW, HFOV if projection == "fisheye" else 90.0, projection, cam_h)


def _observer(projection="fisheye", **over):
    cfg = {**worldmap.load_config(), **over}
    kind = worldmap.class_kinds(cfg, NAMES)
    settings = {"hfovDeg": HFOV if projection == "fisheye" else 90.0, "cameraHeightM": CAM_H, "lateralOffsetM": 0.0, "projection": projection,
                "distanceSource": "depth", "objectDistance": "depth"}
    return worldmap.Observer(cfg, settings, kind, GH, GW, None, NAMES)


# ---------------------------------------------------------------- 1. the lens ground geometry

@pytest.mark.parametrize("projection", ["fisheye", "rectilinear"])
def test_ground_point_and_ground_pixel_are_exact_inverses(projection):
    geo = _geo(projection)
    rows, cols = np.meshgrid(np.arange(62.0, 135.0, 3.0), np.arange(1.0, 240.0, 7.0), indexing="ij")
    for horizon in (0.45, 0.5, 0.41):
        fwd, right = groundfuse.ground_point(geo, rows + 0.5, cols + 0.5, horizon)
        ok = np.isfinite(fwd)
        assert ok.sum() > 300
        row, col = groundfuse.ground_pixel(geo, fwd, right, horizon)
        assert np.nanmax(np.abs(row - rows - 0.5)[ok]) < 0.01 and np.nanmax(np.abs(col - cols - 0.5)[ok]) < 0.01
        f2, r2 = groundfuse.ground_point(geo, row, col, horizon)                      # and back: 1 mm
        assert np.nanmax(np.abs(f2 - fwd)[ok]) < 1e-3 and np.nanmax(np.abs(r2 - right)[ok]) < 1e-3
        assert np.nanmax(np.abs(groundfuse.lateral_at(geo, rows + 0.5, cols + 0.5, fwd, horizon) - right)[ok]) < 1e-9


def test_ground_point_above_the_horizon_is_nan_and_the_camera_height_can_be_passed():
    geo = _geo()
    f, r = groundfuse.ground_point(geo, np.array([10.0, 100.0]), np.array([120.0, 120.0]), 0.45)
    assert np.isnan(f[0]) and np.isnan(r[0]) and np.isfinite(f[1])
    row, col = np.array([100.5]), np.array([120.5])
    z = groundfuse.ground_z(geo, row, col, 0.45)
    assert groundfuse.ground_z(geo, row, col, 0.45, cam_h=CAM_H)[0] == z[0]
    assert groundfuse.ground_z(geo, row, col, 0.45, cam_h=2 * CAM_H)[0] == pytest.approx(2 * z[0])
    assert groundfuse.ground_point(geo, row, col, 0.45, cam_h=2 * CAM_H)[0][0] == pytest.approx(2 * groundfuse.ground_point(geo, row, col, 0.45)[0][0])


def test_the_fisheye_lens_sees_the_ground_further_and_wider_than_the_pinhole_formulas():
    geo = _geo()
    f = collision.focal_px(GW, HFOV)
    row, col = 100.0, 60.5                                                      # a quarter of the width off centre
    fwd, right = groundfuse.ground_point(geo, row, col, HORIZON)
    pin = collision.ground_distance_m(row / GH, HORIZON, CAM_H, GH, f)
    assert fwd > 1.3 * pin                                                      # pinhole: too near
    lens_lat = groundfuse.lateral_at(geo, row, col, 5.0, HORIZON)
    assert abs(collision.lateral_m(col / GW, 5.0, GW, f)) > 1.3 * abs(float(lens_lat))      # and too wide off axis at the same distance (~45 %)


# ---------------------------------------------------------------- rectilinear runs stay exactly as they were

def test_rectilinear_collision_geometry_is_the_pinhole_one():
    for projection, lens in (("rectilinear", False), ("fisheye", True)):
        f = collision.focal_px(GW, HFOV)
        geo = collision._frame_geometry(GH, GW, HORIZON, CAM_H, f, HFOV, 0.6, None, 0, projection, 0.0)
        assert (geo.lens is not None) == lens
        d = collision._ground_dist(geo, 100.0 / GH, 60)
        pin = collision.ground_distance_m(100.0 / GH, HORIZON, CAM_H, GH, f)
        if lens:
            assert d == pytest.approx(float(groundfuse.ground_point(geo.lens, 100.0, 60.5, HORIZON)[0])) and d != pin
        else:
            assert d == pin                                                      # bit for bit
            assert collision._lateral_of(geo, 100.0, 60, d) == collision.lateral_m(60.5 / GW, d, GW, f)
        assert collision._ground_dist(geo, HORIZON, 60) is None                  # at the horizon: nothing


def test_rectilinear_map_ignores_the_geometry_switch():
    """lateralModel "geometry" on a rectilinear run is the collision pass's own pinhole map, byte for byte."""
    rng = np.random.RandomState(1)
    grid = np.full((GH, GW), SKY, np.uint8)
    grid[70:, :] = SW
    grid[20:90, 60:120] = BLD
    grid[30:100, 150:156] = POLE
    depth = (6.0 + 8.0 * rng.rand(GH, GW)).astype(np.float32)
    frame = {"horizon": HORIZON, "scale": 1.0, "depthScale": 1.0, "ego": {}, "dcorr": None}
    outs = []
    for model in ("collision", "geometry"):
        ob = _observer("rectilinear", lateralModel=model)
        assert ob.geometry is False and ob.face_ground is False
        outs.append((ob.observe(grid, frame, depth), ob.object_bases(grid, frame, depth)))
    assert (outs[0][0][0] == outs[1][0][0]).all() and (outs[0][0][1] == outs[1][0][1]).all()
    for a, b in zip(outs[0][1], outs[1][1]):
        assert np.array_equal(a, b)


# ---------------------------------------------------------------- 2. a fisheye scene: the sidewalk and the building meet

def _fisheye_scene(wall_m=8.0):
    """A flat sidewalk up to a facade ``wall_m`` ahead, rendered through the lens (every ground pixel takes the class of its ground point; the
    facade stands on its base row up to row 20), and the depth map a perfect z-depth would give."""
    geo = _geo()
    rows, cols = np.mgrid[0:GH, 0:GW]
    fwd, _ = groundfuse.ground_point(geo, rows + 0.5, cols + 0.5, HORIZON)
    z = groundfuse.ground_z(geo, rows + 0.5, cols + 0.5, HORIZON)
    grid = np.full((GH, GW), SKY, np.uint8)
    below = np.isfinite(fwd)
    grid[below & (fwd < wall_m)] = SW
    grid[below & (fwd >= wall_m)] = BLD
    depth = np.where(np.isfinite(z), z, 30.0).astype(np.float32)
    for c in range(GW):
        b = np.flatnonzero(grid[:, c] == BLD)
        if b.size:
            grid[20:b.min(), c] = BLD
            depth[20:b.max() + 1, c] = float(z[b.max(), c])                      # a facade: one depth over the whole column (the wall's base)
    frame = {"horizon": HORIZON, "scale": 1.0, "depthScale": 1.0, "ego": {}, "dcorr": None}
    return grid, depth, frame


def _face_gap(obs, col, ob):
    """(nearest face row on this column, class of the cell just nearer to the user after skipping unknown cells, number of unknown cells)."""
    r = int(np.flatnonzero(obs[:, col] == BLD).max())                            # the nearest face cell = the largest row
    k = 1
    while r + k < ob.size and obs[r + k, col] == UNK:
        k += 1
    return r, int(obs[r + k, col]) if r + k < ob.size else None, k - 1


def test_building_and_sidewalk_meet_on_a_fisheye_frame_and_the_old_pinhole_map_leaves_a_gap():
    grid, depth, frame = _fisheye_scene()
    new = _observer(lateralModel="geometry")
    assert new.geometry and new.face_ground
    obs, _ = new.observe(grid, frame, depth)
    for col in (80, 100, 120):
        r, nearer, gap = _face_gap(obs, col, new)
        assert gap == 0 and nearer == SW, (col, r, nearer, gap)                  # the sidewalk reaches the building, no unknown cell between
        assert abs((new.orow - r) * new.cell - 8.0) < 0.5                        # and the building is where the scene put it (the face is 0.3 m thick)
    old = _observer(lateralModel="collision", faceGroundContact=False)
    obs_old, _ = old.observe(grid, frame, depth)
    gaps = [_face_gap(obs_old, c, old)[2] for c in (96, 100, 104)]
    assert max(gaps) >= 3, gaps                                                   # the pinhole sidewalk stops short of the (depth-placed) building


def test_the_faces_laterals_come_through_the_lens():
    grid, depth, frame = _fisheye_scene()
    ob = _observer()
    rr, cc, dist, lat = ob.object_bases(grid, frame, depth)
    fwd, right = groundfuse.ground_point(_geo(), rr + 1.0, cc + 0.5, HORIZON)
    assert np.isfinite(right).all() and np.abs(lat - right).max() < 0.3          # a base at its ground point: lateral = the lens ground lateral
    assert np.abs(dist - fwd).max() < 0.3


# ---------------------------------------------------------------- 5. occluded faces follow the contact ratio

def _occluded_scene():
    grid, depth, frame = _fisheye_scene()
    depth = (depth * 1.25).astype(np.float32)                                    # the depth reads 25 % too far everywhere
    for c in range(150, 170):                                                     # something stands at the facade's base: the run ends on a mover
        b = np.flatnonzero(grid[:, c] == BLD).max()
        grid[b + 1:b + 8, c] = PERSON
    return grid, depth, frame


def test_an_occluded_facade_part_is_scaled_by_the_ground_to_depth_ratio():
    grid, depth, frame = _occluded_scene()
    ob = _observer(faceSmoothCols=0)
    rr, cc, dist, lat = ob.object_bases(grid, frame, depth)
    occl = (cc >= 150) & (cc < 170)
    free = ~occl
    g = groundfuse.ground_point(_geo(), rr + 1.0, cc + 0.5, HORIZON)[0]
    assert free.sum() > 100 and occl.sum() >= 10 and np.abs(dist[free] - g[free]).max() < 0.3       # contact bases: the ground-contact distance
    # the occluded part: depth x ratio (ground / depth of the contact bases, ~0.8) = about the true distance, not the 25 % far depth
    assert np.abs(np.median(dist[occl]) - np.median(dist[free])) < 0.8
    ob2 = _observer(faceSmoothCols=0, faceScaleOccluded=False)
    assert np.median(ob2.object_bases(grid, frame, depth)[2][occl]) > 1.15 * np.median(dist[free])


def test_too_few_contact_bases_leave_the_depth_alone():
    grid, depth, frame = _occluded_scene()
    ob = _observer(faceSmoothCols=0, faceRatioMinBases=5000)
    rr, cc, dist, _ = ob.object_bases(grid, frame, depth)
    occl = (cc >= 150) & (cc < 170)
    assert np.median(dist[occl]) > 1.15 * np.median(dist[~occl])


# ---------------------------------------------------------------- 4. the walls calibrate the depth curve

def _region_scene(g_max=11.0):
    geo = _geo()
    rows, cols = np.mgrid[0:GH, 0:GW]
    z = groundfuse.ground_z(geo, rows + 0.5, cols + 0.5, HORIZON)
    mask = np.isfinite(z) & (z <= g_max) & (z >= 1.5) & (cols > 60) & (cols < 180)
    return geo, mask, np.where(np.isfinite(z), z, 1.0).astype(np.float32)        # a perfect metric depth: ratio 1 on the region


def test_wall_samples_extend_the_curve_past_the_walking_region_and_leave_ref_alone():
    geo, mask, dmap = _region_scene()
    cfg = groundfuse.settings({"groundDepth": {"wallSampleWeight": 5}})
    plain = groundfuse.Corrector(cfg, geo).update(0.0, mask, dmap, 1.0, HORIZON, 0.5)
    walls = (np.full(40, 16.0), np.full(40, 20.0))                                # 40 wall bases: depth 16 m, the ground says 20 m (ratio 0.8)
    with_walls = groundfuse.Corrector(cfg, geo).update(0.0, mask, dmap, 1.0, HORIZON, 0.5, extra=walls)
    assert plain["curve"][-1][0] <= 12.5 and "wallSamples" not in plain
    assert with_walls["curve"][-1][0] > 15.0 and with_walls["wallSamples"] == 40
    assert with_walls["ref"] == plain["ref"]                                      # ref (q) stays the walking region's
    assert with_walls["curve"][-1][1] == pytest.approx(0.8, abs=0.03)             # rho at the wall range = its depth / ground ratio
    assert with_walls["curve"][:len(plain["curve"])] == plain["curve"]            # nearer bins are untouched
    few = groundfuse.Corrector(cfg, geo).update(0.0, mask, dmap, 1.0, HORIZON, 0.5, extra=(np.full(4, 16.0), np.full(4, 20.0)))
    assert few["curve"][-1][0] <= 12.5                                            # 4 bases x 5 = 20 < minBinSamples (25): no bin
    assert groundfuse.Corrector(cfg, geo).update(0.0, mask, dmap, 1.0, HORIZON, 0.5, extra=(np.zeros(0), np.zeros(0))) == plain


def test_face_contact_samples_are_the_wall_bases_on_a_surface():
    grid, depth, frame = _fisheye_scene()
    ob = _observer()
    v, g = worldmap.face_contact_samples(ob, grid, depth * 1.25, 1.0, HORIZON)
    assert v.size > 150 and v.size == g.size
    assert np.median(v / g) == pytest.approx(1.25, abs=0.06)                      # depth / lens ground z at the wall bases
    assert np.all(g <= 40.0) and np.all(g > 0)
    for c in range(150, 170):                                                     # a wall base on a person (no surface below) is not a sample
        grid[np.flatnonzero(grid[:, c] == BLD).max() + 1:, c] = PERSON
    assert worldmap.face_contact_samples(ob, grid, depth, 1.0, HORIZON)[0].size == v.size - 20
    assert worldmap.face_contact_samples(ob, grid, None, 1.0, HORIZON)[0].size == 0
    assert worldmap.face_contact_samples(ob, grid, depth, None, HORIZON)[0].size == 0


# ---------------------------------------------------------------- 6. buildings block the view

def _fusion(ob, factor=0.3):
    return worldmap.Fusion({**ob.cfg, "surfaceHiddenFactor": factor}, ob.kind, np.array([SW, BLD]), (0.0, 0.0))


def test_cells_behind_a_building_are_hidden_but_not_the_ones_the_frame_sees_as_ground():
    ob = _observer()
    d = np.full(41, 5.0)
    lat = np.linspace(-1.5, 1.5, 41)                                                # a facade 5 m ahead
    obs = np.full((ob.size, ob.size), UNK, np.uint8)
    own = (ob.fwd > 8.0) & (np.abs(ob.right) < 0.2)
    obs[own] = SW                                                                    # a strip behind the facade this frame itself sees as ground
    ob._hidden_cells(np.full(41, BLD, np.uint8), d, lat, obs)
    h = ob.ray_hidden
    assert h is not None
    behind = (ob.fwd > 6.0) & (np.abs(ob.right) < 0.9)
    assert h[behind & ~own].all()                                                    # behind the face
    assert not h[(ob.fwd < 4.9) & (ob.fwd > 0.5)].any()                              # in front of it
    assert not h[own].any()                                                          # visible ground wins
    assert not h[np.abs(np.degrees(np.arctan2(ob.right, ob.fwd))) > 20.0].any()      # beside the facade's span (+-16.7 deg)
    ob.ray_hidden = None                                                             # a class that is not an occluder hides nothing
    ob._hidden_cells(np.full(41, POLE, np.uint8), d, lat, obs)
    assert ob.ray_hidden is None


def test_hidden_cells_cut_stored_surface_votes_only():
    ob = _observer()
    fu = _fusion(ob)
    one = np.ones((ob.size, ob.size), np.float32)
    surf = np.full((ob.size, ob.size), UNK, np.uint8)
    surf[60:180, 80:120] = SW
    wall = np.full((ob.size, ob.size), UNK, np.uint8)
    wall[70:73, 80:120] = BLD
    fu.update(0.0, (0.0, 0.0, 0.0), surf, one, ob)
    fu.update(0.0, (0.0, 0.0, 0.0), wall, one, ob)
    k_surf, k_obj = int(np.flatnonzero(fu.is_surface)[0]), int(np.flatnonzero(~fu.is_surface)[0])
    before = fu.votes.copy()
    ob.ray_hidden = np.zeros((ob.size, ob.size), bool)
    ob.ray_hidden[60:68, 90:100] = True                                              # behind the wall line (rows < 70)
    fu.update(0.0, (0.0, 0.0, 0.0), np.full((ob.size, ob.size), UNK, np.uint8), one, ob)
    iy, ix = fu._ego_to_world_idx(ob.fwd, ob.right, (0.0, 0.0, 0.0))
    sel = np.zeros_like(ob.ray_hidden)
    sel[62:66, 92:98] = True                                                         # (interior: the world cells sit on the ego cells' borders)
    assert np.allclose(fu.votes[k_surf][iy[sel], ix[sel]], 0.3 * before[k_surf][iy[sel], ix[sel]])
    sel = np.zeros_like(ob.ray_hidden)
    sel[100:150, 85:115] = True                                                      # not hidden: untouched
    assert np.allclose(fu.votes[k_surf][iy[sel], ix[sel]], before[k_surf][iy[sel], ix[sel]])
    assert np.allclose(fu.votes[k_obj], before[k_obj])                               # object votes untouched


def test_a_street_seen_through_a_building_fades_while_the_building_stands():
    """On a synthetic fisheye scene: the surface an older frame put behind a facade is cut by the next frames."""
    grid, depth, frame = _fisheye_scene(wall_m=6.0)
    ob = _observer()
    fu = _fusion(ob)
    one = np.ones((ob.size, ob.size), np.float32)
    stale = np.full((ob.size, ob.size), UNK, np.uint8)
    stale[100:140, 85:115] = SW                                                      # 6 - 10 m ahead: behind the 6 m facade
    for _ in range(2):
        fu.update(0.0, (0.0, 0.0, 0.0), stale, one, ob)
    assert (fu.snapshot(0.0, (0.0, 0.0, 0.0), ob, True)[2][105:135, 90:110] == SW).all()
    for _ in range(4):
        obs, w = ob.observe(grid, frame, depth)
        fu.update(0.0, (0.0, 0.0, 0.0), obs, w, ob)
    assert (fu.snapshot(0.0, (0.0, 0.0, 0.0), ob, True)[2][105:135, 90:110] == UNK).all()      # 2 * 0.3^4 is below the weight floor


# ---------------------------------------------------------------- 7. gaps between a surface and a face are closed

def _seam(width, with_face=True, with_surface=True):
    ob = _observer()
    fu = _fusion(ob, 1.0)
    o = np.full((ob.size, ob.size), UNK, np.uint8)
    if with_surface:
        o[160:200, 60:140] = SW                                                       # the sidewalk, rows 160..199
    top = 160 - width                                                                 # `width` unknown rows, then the building above them
    if with_face:
        o[top - 8:top, 60:140] = BLD
    for _ in range(3):
        fu.update(0.0, (0.0, 0.0, 0.0), o, np.ones(o.shape, np.float32), ob)
    return fu.snapshot(0.0, (0.0, 0.0, 0.0), ob, True), top


@pytest.mark.parametrize("width", [2, 5])
def test_a_narrow_seam_between_sidewalk_and_building_is_closed(width):
    (cls, conf, surf, objs), top = _seam(width)
    seam = (slice(top, 160), slice(95, 106))
    assert (cls[seam] == BLD).all() and (objs[seam] == BLD).all() and (conf[seam] > 0).all()
    assert (surf[seam] == UNK).all()                                                  # the surface layer is left alone


def test_a_wide_seam_or_a_missing_side_stays_unknown():
    (cls, _, _, objs), top = _seam(8)
    assert (cls[top + 1:159, 95:106] == UNK).all() and (objs[top + 1:159, 95:106] == UNK).all()
    (cls, _, _, _), top = _seam(2, with_face=False)                                    # no face behind the gap
    assert (cls[158:160, 95:106] == UNK).all()
    (cls, _, _, _), top = _seam(2, with_surface=False)                                 # no surface on the user's side
    assert (cls[158:160, 95:106] == UNK).all()


def test_gap_closing_can_be_switched_off():
    assert _observer(gapCloseM=0.0).gap_tab is None
