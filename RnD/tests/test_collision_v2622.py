"""v26.2.2: the map judges wall-like classes (face / edge test), items inside a solid area are snapped to its near border (depth correction),
movers that leave the image coast on their last world velocity (plan ``docs/plans/v26.2.2.md``)."""

from __future__ import annotations

import types

import numpy as np

import collision as col
import faceedge
from tests.test_collision import CONFIG


def _item(cls="pole", dist=8.0, lat=0.0, group="static", **kw):
    return col._Item(group=group, class_name=cls, bbox=[0.4, 0.4, 0.5, 0.6], contact_y=0.6, distance_m=dist, lateral_m=lat, bearing=0.0,
                     clock=12, pan=0.0, area_frac=0.01, clipped=False, touches=True, lane_hit=True, along_path=False, lane_cover=0.3, **kw)


def _stub_map(mode="snap"):
    sm = col._StaticMap.__new__(col._StaticMap)
    sm.ob = types.SimpleNamespace(orow=200, oc=100, cell=0.1, size=200)
    wall = np.zeros((200, 200), dtype=bool)
    wall[140:145, 70:130] = True                       # a wall face 5.6-6.0 m ahead, 6 m wide
    sm.wall_solid, sm.solid_depth, sm.solid_rays = wall, 0.8, 3
    sm.solid_mode, sm.solid_on = mode, mode in ("snap", "suppress")
    sm.judged = frozenset({"building"})
    return sm


def test_config():
    r = CONFIG["roles"]
    assert CONFIG["version"] == "v26.2.5"
    assert r["staticSource"] == "map" and r["faceEdge"]["enabled"] and r["faceEdge"]["minFaceCells"] == 3
    assert "building" in r["mapJudgedClasses"] and "mapMinCells" not in r and "mapMinClosingMps" not in r
    assert r["insideSolid"]["mode"] == "snap" and CONFIG["coast"]["enabled"]


def test_an_item_behind_a_wall_is_snapped_to_the_wall_face():
    sm = _stub_map()
    it = _item("pole", dist=8.0, lat=0.4)
    sm.snap_solid(it)
    assert it.inside_solid and it.solid_corrected and it.raw_distance_m == 8.0
    assert abs(it.distance_m - 5.6) <= 0.12                      # the near border of the solid area, on the item's own bearing
    assert it.lateral_m > 0 and abs(it.lateral_m / it.distance_m - 0.4 / 8.0) < 0.02            # same bearing
    assert it.clock_text and col._hazard_dict(it)["solidCorrected"] and col._hazard_dict(it)["rawDistanceM"] == 8.0


def test_nothing_is_snapped_in_front_of_the_wall_at_the_face_or_for_wall_like_items():
    sm = _stub_map()
    for kw in (dict(dist=4.0), dict(dist=6.2), dict(cls="building", dist=8.0)):    # in front / within the 0.8 m margin / its own class
        it = _item(**kw)
        sm.snap_solid(it)
        assert not it.solid_corrected and it.distance_m == kw["dist"]
    off = _stub_map("off")
    it = _item(dist=8.0)
    off.snap_solid(it)
    assert not it.inside_solid


def test_suppress_mode_marks_and_mutes():
    sm = _stub_map("suppress")
    it = _item("person", dist=8.0, group="moving")
    it.role, it.collision = "danger", True
    sm.snap_solid(it)
    col._mute_solid(it, sm)
    assert it.inside_solid and not it.solid_corrected and it.role == "none" and not it.collision and it.distance_m == 8.0


def test_face_cell_across_the_path_is_a_face_and_a_wall_line_is_an_edge():
    n = 200
    rows, cols = np.mgrid[0:n, 0:n]
    fwd = ((200 - rows) * 0.1).astype(np.float64)
    right = ((cols - 100) * 0.1).astype(np.float64)
    wall = (np.abs(right - 0.5) <= 0.1) & (fwd > 0.5) & (fwd < 8.0)             # a wall beside the path, 0.5 m to the right (its blur is inside the corridor)
    cfg = faceedge.settings({})
    cand = wall & (fwd > 3.0) & (fwd < 4.0)                     # its blur: some cells just inside the corridor
    res = faceedge.classify(cand, wall, fwd, right, 0.1, cfg)
    assert (res["verdict"] == faceedge.EDGE).all() and faceedge.summarize(res, cfg)["verdict"] == "edge"
    across = wall | ((np.abs(fwd - 5.0) <= 0.1) & (np.abs(right) <= 0.4))       # plus a section sticking out across the path at 5 m
    cand2 = across & (np.abs(fwd - 5.0) <= 0.1) & (np.abs(right) <= 0.4)
    res2 = faceedge.classify(cand2, across, fwd, right, 0.1, cfg)
    s2 = faceedge.summarize(res2, cfg)
    assert s2["verdict"] == "face" and s2["face"] >= 3 and abs(s2["nearestFaceM"] - 4.9) < 0.3


def test_a_mover_that_leaves_the_image_coasts_and_is_never_spoken():
    coast = col._Coast(CONFIG["coast"])
    world = col._WorldMemory({}, enabled=True)
    world.advance(0.0, 0.0, 0.0, 0.0)                                          # standing, heading 0, at the origin
    tracks = {}
    for k in range(6):                                                         # a person crossing from the left at 1.5 m/s, 6 m ahead
        t = 0.2 * k
        it = _item("person", dist=6.0, lat=-3.0 + 1.5 * t, group="moving")
        it.track_id = 1
        it.moving = True
        coast.observe(it, t, world)
        tracks[1] = types.SimpleNamespace(last_t=t, last_distance=6.0, last_lateral=it.lateral_m, present_run=k)
    out = coast.items(1.4, {}, world, tracks, 0.7)                             # 0.4 s after the last sighting, not seen now
    assert len(out) == 1
    g = out[0]
    assert g.coasting and not g.speak and abs(g.distance_m - 6.0) < 0.3 and abs(g.lateral_m - (-3.0 + 1.5 * 1.4)) < 0.3
    assert coast.items(4.0, {}, world, tracks, 0.7) == []                       # past the 2 s horizon
    assert coast.episodes and coast.episodes[-1]["end"] == "expired"
