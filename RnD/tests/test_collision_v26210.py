"""v26.2.10 (plan B): people that touch are separate items (``personSplit``)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

import collision as col
from tests.test_collision import CONFIG, F, H, HC, HV, ID, NAMES, W, base_grid, row_for

D = 6.0


def _person(g, d, lat, w_m=0.5, h_m=1.7, head_w_m=0.2, shoulder_drop_m=0.25):
    """A person: head (narrow, tallest) over wider shoulders / torso."""
    bottom = int(round(row_for(d)))
    top = bottom - int(round(h_m * F / d))
    cx = W / 2 + lat * F / d
    wpx = max(2, int(round(w_m * F / d)))
    hpx = max(1, int(round(head_w_m * F / d)))
    x0 = int(round(cx - wpx / 2))
    drop = int(round(shoulder_drop_m * F / d))
    g[top + drop:bottom, x0:x0 + wpx] = ID["person"]
    hx = int(round(cx - hpx / 2))
    g[top:top + drop, hx:hx + hpx] = ID["person"]


def _items(g, config=None, dmap=None):
    config = config or _cfg()
    ids = col.resolve_class_ids(config, NAMES)
    region = col.walking_region(g, ids, config)
    geo = col._frame_geometry(H, W, HV, HC, F, 118.0, 0.6, region, config["roles"]["boundaryMarginPx"])
    return [i for i in col.detect_items(g, ids, geo, config, dmap) if i.class_name == "person"]


def _cfg(**over):
    c = copy.deepcopy(CONFIG)
    c["personSplit"] = {**c["personSplit"], "enabled": True, **over}
    return c


def test_config():
    ps = col.load_config()["personSplit"]
    assert ps["enabled"] is True and ps["personWidthM"] == 0.55 and ps["splitWidthFactor"] == 1.4 and ps["splitDepthJumpM"] == 0.6
    assert col.load_config()["version"] == "v26.2.12"


def test_three_people_standing_together_are_three_items_and_off_is_one():
    g = base_grid()
    for lat in (-0.5, 0.05, 0.6):                      # touching shoulders
        _person(g, D, lat, w_m=0.55)
    on = _items(g)
    assert len(on) == 3
    assert [round(i.lateral_m, 1) for i in sorted(on, key=lambda i: i.lateral_m)] == pytest.approx([-0.5, 0.05, 0.6], abs=0.2)
    assert all(i.distance_m == pytest.approx(D, rel=0.1) and i.shape is not None for i in on)
    assert len(_items(g, _cfg(enabled=False))) == 1


def test_a_single_person_with_arms_wide_is_one_item():
    g = base_grid()
    _person(g, D, 0.0, w_m=0.5)
    bottom = int(round(row_for(D)))
    top = bottom - int(round(1.7 * F / D))
    arm_row = top + int(round(0.45 * F / D))
    g[arm_row:arm_row + max(2, int(0.15 * F / D)), int(W / 2 - 0.85 * F / D):int(W / 2 + 0.85 * F / D)] = ID["person"]       # T-pose, 1.7 m
    assert len(_items(g)) == 1


def test_a_single_ordinary_person_is_one_item():
    for lat in (-1.0, 0.0, 0.8):
        g = base_grid()
        _person(g, D, lat, w_m=0.55)
        assert len(_items(g)) == 1


def test_a_person_in_front_of_another_splits_on_the_depth_jump():
    g = base_grid()
    top = int(round(row_for(D))) - int(round(1.7 * F / D))
    lo, hi = int(W / 2 - 0.6 * F / D), int(W / 2 + 0.6 * F / D)
    g[top:int(round(row_for(D))), lo:hi] = ID["person"]                                # a flat-topped 1.2 m wide blob: no head valley
    dmap = np.full((H, W), D)
    dmap[:, W // 2:] = D + 1.5                                                         # the right half is 1.5 m further away
    assert len(_items(g, dmap=None)) == 1
    assert len(_items(g, dmap=dmap)) == 2


@pytest.mark.skipif(not Path("/debug/lab/runs/5fda5626e808/collisions/c2/hazards.json").exists(), reason="the Chest-center-0004 run is not present")
def test_chest0004_at_zero_seconds_has_three_people():
    z = np.load("/debug/lab/runs/5fda5626e808/grids.npz")
    doc = json.load(open("/debug/lab/runs/5fda5626e808/run.json"))
    ids = col.resolve_class_ids(CONFIG, doc["classNames"])
    hz = json.load(open("/debug/lab/runs/5fda5626e808/collisions/c2/hazards.json"))
    horizon = hz["frames"][0]["horizonY"]
    s = hz["settings"]
    region = col.walking_region(z["grids"][0], ids, CONFIG)
    geo = col._frame_geometry(135, 240, horizon, s["cameraHeightM"], col.focal_px(240, 118.0), 118.0, 0.6, region,
                              CONFIG["roles"]["boundaryMarginPx"], hz.get("projection") or "rectilinear")
    items = [i for i in col.detect_items(z["grids"][0], ids, geo, _cfg()) if i.class_name == "person"]
    assert len([i for i in items if i.area_frac > 0.0004]) == 3
