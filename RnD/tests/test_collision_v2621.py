"""v26.2.1: the collision rules read the world map (plan ``docs/plans/v26.2.1.md``, user decision "1+3").

* a building / wall section standing in the walking corridor on the fused map replaces the v26.1.16 lane part (core +-0.3 m, >= 10 cells,
  on the map for 0.5 s and closing at >= 0.6 m/s); a plain wall beside the sidewalk is no danger;
* a static danger that leaves the bottom of the image keeps beeping from the map until it is passed (ghost);
* ``staticSource: "image"`` is exactly v26.2.0;
* the stored ``worldmap.npz`` (offline ``worldmap.build`` from hazards.json) equals the map the collision pass saw.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

import dataclasses

import collision as col
import worldmap
from tests.test_collision import CONFIG, ID, NAMES, SETTINGS, H, HV, SPEED, base_grid, motion, place, row_for
from tests.test_collision import F, HC, W
from tests.test_collision_regression import _run_windows
from tests.test_collision_v26116_lanepart import _frames, add_wall

def _ground_depth(n):
    """A metric depth map per frame that is the ground distance of every row (flat ground: what a perfect depth model reads at a base)."""
    rows = np.arange(H)
    z = np.where(rows + 1 > HV * H + 1, HC * F / np.maximum(rows + 1 - HV * H, 1e-6), 60.0).astype(np.float32)
    return {"t": np.arange(n) / FPS, "depth": np.repeat(z[None, :, None], n, axis=0).repeat(W, axis=2), "units": "metric", "anchor": "none"}


DSET = dataclasses.replace(SETTINGS, distance_source="depth")


def _run(frames, mot=None, config=CONFIG, depth=None):
    """Collision pass with the true metric depth: the ego speed (and so the map's pose) is known from the start."""
    grids = np.stack(frames)
    return col.run_collision(grids, np.arange(len(frames)) / FPS, NAMES, config, DSET, mot, depth or _ground_depth(len(frames)))


IMAGE = copy.deepcopy(CONFIG)
IMAGE["roles"]["staticSource"] = "image"
FPS = 10.0


def test_config_keys():
    r = CONFIG["roles"]
    assert CONFIG["version"] == "v26.2.4" and r["staticSource"] == "map"
    # v26.2.2: the building section gates (mapMinCells, mapCorridorMarginM, mapMinAgeSeconds, mapMinClosingMps) are gone: the map judges every wall-like
    # class with the face / edge test (tests/test_collision_v2622.py)
    assert "mapMinCells" not in r and "mapMinClosingMps" not in r and r["mapJudgedClasses"]
    assert "mapUnion" not in r


def test_plain_wall_beside_the_sidewalk_is_no_danger():
    doc, ev = _run(_frames(face=False), mot=motion(14))
    assert not [e for e in ev["events"] if e["type"] == "beeps"]
    assert not any(h.get("mapCells") for f in doc["frames"] for h in f["hazards"])
    assert all(h["role"] != "danger" for f in doc["frames"] for h in f["hazards"] if h["className"] == "building")


def _leaving_pole_frames(seconds=8.0, d0=9.0, leave_d=1.45):
    base = base_grid(half_w_m=2.0)
    out = []
    for i in range(int(seconds * FPS)):
        g = base.copy()
        d = d0 - SPEED * i / FPS
        if d > leave_d:                                     # the pole's base goes under the bottom of the frame
            place(g, "pole", d, 0.0, 0.6, 3.0)
        out.append(g)
    return out


def test_pole_leaving_the_bottom_of_the_frame_keeps_beeping_until_passed():
    frames = _leaving_pole_frames()
    doc, ev = _run(frames, mot=motion(8))
    ghosts = [(f["t"], h) for f in doc["frames"] for h in f["hazards"] if h.get("ghost")]
    assert ghosts, "the pole is followed on the map after the image lost it"
    assert all(h["className"] == "pole" and h["role"] == "danger" and h["collision"] for _, h in ghosts)
    assert all(h["distanceM"] > 0 for _, h in ghosts)
    steps = [h["stepsTo"] for _, h in ghosts]
    assert steps == sorted(steps, reverse=True)                # it gets nearer
    last_image = max(f["t"] for f in doc["frames"] for h in f["hazards"] if h["className"] == "pole" and not h.get("ghost"))
    assert min(t for t, _ in ghosts) <= last_image + 0.5
    tones = [e for e in ev["events"] if e["type"] == "tone" and e["kind"].startswith("collision") and e["t"] > last_image + 0.6]
    assert tones, "the collision beeps continue after the image lost the pole"
    img_doc, img_ev = _run(frames, mot=motion(8), config=IMAGE)
    assert not [1 for f in img_doc["frames"] for h in f["hazards"] if h.get("ghost")]
    img_tones = [e for e in img_ev["events"] if e["type"] == "tone" and e["kind"].startswith("collision") and e["t"] > last_image + 0.6]
    assert len(tones) >= 4 and not img_tones


def test_a_pole_beside_the_lane_is_never_a_ghost_danger():
    base = base_grid(half_w_m=2.0)
    frames = []
    for i in range(80):
        g = base.copy()
        d = 9.0 - SPEED * i / FPS
        if d > 1.45:
            place(g, "pole", d, 1.4, 0.6, 3.0)
        frames.append(g)
    doc, _ = _run(frames, mot=motion(8))
    assert not [1 for f in doc["frames"] for h in f["hazards"] if h.get("ghost") or h["role"] == "danger"]


def test_a_mover_is_unaffected_by_the_map():
    frames = [base_grid(half_w_m=2.0).copy() for _ in range(60)]
    for i, g in enumerate(frames):
        place(g, "person", 8.0 - 1.0 * i / FPS, 0.0, 0.5, 1.7)
    a, ea = _run(frames, mot=motion(6))
    b, eb = _run(frames, mot=motion(6), config=IMAGE)
    ka = [(e["t"], e.get("text")) for e in ea["events"] if "person" in (e.get("text") or "") or e.get("label") == "person"]
    kb = [(e["t"], e.get("text")) for e in eb["events"] if "person" in (e.get("text") or "") or e.get("label") == "person"]
    assert ka == kb


def test_image_source_is_the_v2620_behaviour():
    doc, ev = _run(_frames(face=True), mot=motion(14), config=IMAGE)
    assert not any("corridor" in f for f in doc["frames"])
    assert not any("source" in h or "mapCells" in h for f in doc["frames"] for h in f["hazards"])
    assert any(h.get("lanePart") for f in doc["frames"] for h in f["hazards"])        # the v26.1.16 lane part is back


@pytest.fixture(scope="module")
def review7():
    cfg = col.load_config()                                               # v26.2.2: the default (map) config; the regression helper's own CONFIG is the image rule
    cfg["distance"]["objectDistance"] = "depth"                           # v26.2.3: the new default ground+depth is pinned in test_collision_v2623.py
    return _run_windows("chest0004_review7", cfg)


@pytest.fixture(scope="module")
def review7_image():
    return _run_windows("chest0004_review7", IMAGE)


def test_review7_the_building_section_is_still_spoken_and_beeps(review7, review7_image):
    old = [e for e in review7_image[2][0]["events"] if e["type"] == "speech" and e["text"].startswith("building at 12 in")]
    assert [round(e["t"], 2) for e in old] == [11.83]                             # v26.2.0 (lane part)
    ev = review7[2][0]["events"]
    sp = [e for e in ev if e["type"] == "speech" and e["text"].startswith("building at 11:45 in")]
    # v26.2.2 (re-pinned): the face / edge test judges it; still 13.50 "in 8" (the first face frame is 12.33 at 10 steps, the speech policy needs the
    # confirmed face), the clock reads 11:45 instead of 12 because the nearest FACE cell, not the nearest corridor cell, is the measurement
    assert [(round(e["t"], 2), e["text"]) for e in sp] == [(13.5, "building at 11:45 in 8")]
    beeps = [e for e in ev if e["type"] == "beeps" and e["kind"] == "collision-center" and "building" in e["text"] and 14.0 <= e["t"] <= 17.0]
    assert beeps and beeps[0]["minSteps"] <= 5               # 15.33 "center · building at 12:15 · 5→4 steps" (the clock moved with the measurement)
    # the wall is judged on the map: face cells in the corridor, its own image contact point kept for the Lab, no lane part item
    frames = review7[2][0]["doc"]["frames"]
    mp = [(f["t"], h) for f in frames for h in f["hazards"] if h["className"] == "building" and h.get("mapCells") and h["role"] == "danger"]
    assert mp and all(h["source"] == "map" and h["faceEdge"]["verdict"] == "face" and h["faceEdge"]["face"] >= CONFIG["roles"]["faceEdge"]["minFaceCells"] for _, h in mp)
    assert min(t for t, h in mp) == pytest.approx(12.33, abs=0.2)
    assert abs(mp[0][1]["lateralM"]) <= 0.6 and mp[0][1]["stepsTo"] <= CONFIG["roles"]["dangerSteps"]
    assert not any(h.get("lanePart") for f in frames for h in f["hazards"])
    assert all("corridor" in f for f in frames)


def test_online_map_equals_the_offline_build():
    """The collision pass's map and ``worldmap.build`` over its hazards.json are the same fusion (same pose, same observations)."""
    frames = _frames(face=True, seconds=6.0)
    grids = np.stack(frames)
    times = np.arange(len(frames)) / FPS
    mot = motion(6)
    doc, _ = col.run_collision(grids, times, NAMES, CONFIG, DSET, mot, _ground_depth(len(frames)))
    wcfg = worldmap.load_config()
    smap = {}
    orig = col._StaticMap.update

    def spy(self, i, frame, dmap, grid):
        orig(self, i, frame, dmap, grid)
        smap[i] = (self.classes.copy(), self.conf.copy())
    col._StaticMap.update = spy
    try:
        col.run_collision(grids, times, NAMES, CONFIG, DSET, mot, _ground_depth(len(frames)))
    finally:
        col._StaticMap.update = orig
    out = worldmap.build(grids, times, NAMES, doc, CONFIG, wcfg, _ground_depth(len(frames)))
    for i in range(len(frames)):
        assert np.array_equal(out["classes"][i], smap[i][0]) and np.array_equal(out["conf"][i], smap[i][1]), i
