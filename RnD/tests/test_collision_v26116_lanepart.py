"""v26.1.16 follow-up (review 8, 10.9 s "building at 12"): the lane part of a wall / building (``roles.laneBase*``).

A wall whose side runs along the sidewalk and whose face juts out across the lane is ONE component measured at its lowest pixel (the side
wall's base, context). The extra item measures the face's ground base: component pixels with walking region directly below that lie in the lane.
"""

from __future__ import annotations

import numpy as np
import pytest

import collision as col
import copy

from tests.test_collision import CONFIG as _CONFIG, F, H, HC, HV, ID, NAMES, SPEED, W, base_grid, dist_at_row, motion, place, row_for, run as _run
from tests.test_collision_regression import _run_windows

# v26.2.1: these tests pin the v26.1.16 lane-part rule, which is the ``staticSource: image`` behaviour (the map replaces it by default)
CONFIG = copy.deepcopy(_CONFIG)
CONFIG["roles"]["staticSource"] = "image"


def run(frames, **kw):
    kw.setdefault("config", CONFIG)
    return _run(frames, **kw)


ROLES = CONFIG["roles"]
FPS = 10.0


def add_wall(g, d_far=7.0, d_near=2.5, inner_m=2.0, thick_m=0.6):
    """A building wall strip just outside the walking region's right edge between two distances (the side wall)."""
    for r in range(int(row_for(d_far)), int(row_for(d_near))):
        d = dist_at_row(r + 1)
        c0 = int(W / 2 + inner_m * F / d) + 1
        c1 = c0 + max(1, int(round(thick_m * F / d)))
        g[r, min(W, c0):min(W, c1)] = ID["building"]


def _lane_parts(doc):
    return [(f["t"], h) for f in doc["frames"] for h in f["hazards"] if h.get("lanePart")]


def _frames(face: bool, seconds=14.0, d0=22.0):
    """We walk at SPEED along a sidewalk with a wall strip beside it; ``face``: an extra wall face stands across the lane."""
    base = base_grid(half_w_m=2.0)
    out = []
    for i in range(int(seconds * FPS)):
        g = base.copy()
        d = d0 - SPEED * i / FPS
        place(g, "pole", d + 3.0, -1.3, 0.6, 3.0)        # a speed witness: the ego speed (and so "closing in") is only known with one
        add_wall(g, d_far=d + 12.0, d_near=2.5, inner_m=1.9, thick_m=1.2)
        if face:
            place(g, "building", d, 1.25, 2.6, 2.0)            # from the lane edge to the side wall: ONE component with the strip
        out.append(g)
    return out


def test_config_and_hazard_field():
    assert ROLES["laneBaseClasses"] == ["building"]
    assert ROLES["laneBaseMinColumns"] >= 2 and CONFIG["version"] == "v26.2.4"
    it = col._Item(group="static", class_name="building", bbox=[0, 0, 1, 1], contact_y=0.6, distance_m=5.0, lateral_m=0.0, bearing=0.0, clock=12,
                   pan=0.0, area_frac=0.1, clipped=False, touches=True, lane_hit=True, along_path=False, lane_cover=0.5, lane_part=True)
    assert col._hazard_dict(it)["lanePart"] is True
    it.lane_part = False
    assert "lanePart" not in col._hazard_dict(it)


def test_a_plain_side_wall_has_no_lane_part():
    doc, ev = run(_frames(face=False), mot=motion(14))
    assert not _lane_parts(doc)
    assert not [e for e in ev["events"] if e["type"] == "beeps"]


def test_an_l_shaped_wall_is_a_context_side_wall_plus_a_lane_part_danger():
    doc, ev = run(_frames(face=True), mot=motion(14))
    lp = _lane_parts(doc)
    assert lp, "the face across the lane is measured"
    assert {h["className"] for _, h in lp} == {"building"}
    ids = {h["trackId"] for _, h in lp}
    assert min(ids) >= col.LANE_PART_ID_BASE                              # its own tracks, in their own id range
    others = {h["trackId"] for f in doc["frames"] for h in f["hazards"] if h["className"] == "building" and not h.get("lanePart")}
    assert others and not (ids & others)                                   # the side wall (if it is detected as a separate component or not) never shares it
    dangers = [(t, h) for t, h in lp if h["role"] == "danger"]
    assert dangers
    t0, h0 = dangers[0]
    assert h0["stepsTo"] <= ROLES["dangerSteps"] + 0.5 and abs(h0["lateralM"]) <= 0.9 and h0["collision"]
    speech = [e for e in ev["events"] if e["type"] == "speech" and e["text"].startswith("building at") and "at 12" in e["text"]]
    assert speech and speech[0]["t"] >= t0 - 1e-6
    assert any(e["type"] == "beeps" and e["kind"] == "collision-center" for e in ev["events"])          # collision beeps near the end


def _detect(grid, config=CONFIG):
    ids = col.resolve_class_ids(config, NAMES)
    region = col.walking_region(grid, ids, config)
    geo = col._frame_geometry(H, W, HV, HC, F, 118.0, 0.6, region, config["roles"]["boundaryMarginPx"])
    return col.detect_items(grid, ids, geo, config)


def test_the_face_across_the_lane_gives_an_extra_item_measured_at_its_base():
    g = base_grid(half_w_m=2.0)
    add_wall(g, d_far=18.0, d_near=2.5, inner_m=2.0, thick_m=1.0)
    place(g, "building", 7.0, 0.0, 1.8, 2.0)
    items = [i for i in _detect(g) if i.class_name == "building"]
    parts = [i for i in items if i.lane_part]
    assert len(parts) == 1 and len(items) >= 2
    p = parts[0]
    assert p.lane_hit and not p.along_path and abs(p.lateral_m) < 0.6 and p.distance_m == pytest.approx(7.0, rel=0.1)
    assert p.shape is not None and p.area_frac > 0
    side = [i for i in items if not i.lane_part]
    assert all(not i.lane_hit or i.along_path for i in side) or all(i.distance_m != p.distance_m for i in side)


def test_a_plain_wall_beside_the_lane_gives_no_extra_item():
    g = base_grid(half_w_m=2.0)
    add_wall(g, d_far=18.0, d_near=2.5, inner_m=2.0, thick_m=1.0)
    assert not [i for i in _detect(g) if i.lane_part]


def test_a_face_that_is_a_lane_hit_by_itself_needs_no_extra_item():
    g = base_grid(half_w_m=2.0)
    place(g, "building", 7.0, 0.0, 1.8, 2.0)
    assert not [i for i in _detect(g) if i.lane_part]


def test_the_classes_and_the_minimum_columns_are_configurable():
    import copy
    cfg = copy.deepcopy(CONFIG)
    cfg["roles"]["laneBaseClasses"] = []
    g2 = base_grid(half_w_m=2.0)
    add_wall(g2, d_far=18.0, d_near=2.5, inner_m=2.0, thick_m=1.0)
    place(g2, "building", 7.0, 0.0, 1.8, 2.0)
    assert not [i for i in _detect(g2, cfg) if i.lane_part]
    cfg = copy.deepcopy(CONFIG)
    cfg["roles"]["laneBaseMinColumns"] = 500
    assert not [i for i in _detect(g2, cfg) if i.lane_part]


# ---- review 8 fixture ---------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def review8():
    return _run_windows("chest0004_review8", CONFIG)


def test_review8_the_building_in_the_lane_at_12_is_announced_and_beeped(review8):
    _, _, windows = review8
    ev = windows[0]["events"]
    speech = [e for e in ev if e["type"] == "speech" and e["text"].startswith("building at 12 in")]
    assert [round(e["t"], 1) for e in speech if 9.9 <= e["t"] <= 12.0], speech
    beeps = [e for e in ev if e["type"] == "beeps" and e["kind"] == "collision-center" and 10.0 <= e["t"] <= 17.0]
    assert beeps, "center collision beeps while we close in on the building"
    lp = [(f["t"], h) for f in windows[0]["doc"]["frames"] for h in f["hazards"] if h.get("lanePart") and h["className"] == "building"]
    assert lp and all(h["trackId"] >= col.LANE_PART_ID_BASE for _, h in lp)
    assert min(t for t, h in lp if h["role"] == "danger") <= 12.0


def test_review8_no_lane_part_danger_on_a_wall_along_the_sidewalk(review8):
    """The earlier attempts made every wall along a sidewalk beep (11 -> 23-29 episodes); the lane part adds only the one building."""
    _, _, windows = review8
    old = {(round(e["t"], 1)) for e in windows[0]["events"] if e["type"] == "beeps" and e["kind"].startswith("collision")}
    dangers = {}
    for f in windows[0]["doc"]["frames"]:
        for h in f["hazards"]:
            if h.get("lanePart") and h["role"] == "danger":
                dangers.setdefault(h["trackId"], []).append(f["t"])
    assert len(dangers) <= 3, {k: (v[0], v[-1]) for k, v in dangers.items()}
    assert old
