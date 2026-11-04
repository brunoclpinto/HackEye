"""v26.2.11 (W2): collision source image | map and predictive speech (plan ``docs/plans/v26.2.11.md``, W2)."""
from __future__ import annotations

import types

import numpy as np

import collision as col
from tests.test_collision import _item, _policy, _tracks

CONFIG = col.load_config()          # conftest: the defaults of this version (predictive on) for this module


def _pol(rate=1.0):
    p = _policy(CONFIG)
    p.speech_rate = rate
    return p


def test_defaults():
    assert CONFIG["source"]["mode"] == "image" and CONFIG["source"]["imageNetSteps"] == 3.0
    pr = CONFIG["speech"]["predictive"]
    assert pr["enabled"] is True and pr["startLatencyS"] == 0.2 and pr["wordsPerSecond"] == 2.8 and pr["minSteps"] == 1 and pr["passedM"] == 0.3


def test_static_item_is_said_at_its_position_when_the_phrase_ends_v26211():
    """6 steps (4.2 m), walking 1.2 m/s, the 5-word phrase lasts 0.2 + 5 / 2.8 = 1.99 s: 2.4 m walked -> 1.8 m left, said as 3 steps."""
    p = _pol()
    p.ego_u = 1.2
    it = _item(1, "danger", 6, "pole", dist=4.2)
    it.urgency = "danger"
    e = p.step(10.0, [it], _tracks(1))
    assert e["text"] == "pole at 12 in 3", e["text"]
    pr = e["predicted"]
    assert pr["steps"] == 3 and pr["stepsNow"] == 6 and pr["textNow"] == "pole at 12 in 6" and abs(pr["dt"] - 1.99) < 0.01 and pr["phraseS"] == pr["dt"]
    assert abs(pr["fwd"] - (4.2 - 1.2 * pr["dt"])) < 0.01
    assert e["clock"] == 12 and it.steps == 6                    # the unpredicted values stay on the event / item


def test_each_item_is_timed_to_the_end_of_its_own_mention_v26211():
    p = _pol()
    p.ego_u = 1.0
    a, b = _item(1, "danger", 8, "sign", dist=5.6, clock=12), _item(2, "danger", 12, "pole", dist=8.4, clock=11)
    for i in (a, b):
        i.urgency = "danger"
    e = p.step(10.0, [a, b], _tracks(1, 2))
    pr = e["predicted"]
    first, second = pr["dts"]
    assert first < second == pr["phraseS"] and abs(first - (0.2 + 5 / 2.8)) < 0.02          # "sign at 12 in 8" is 5 words
    assert pr["dt"] == first                                                             # the lead is the first item
    assert e["text"].startswith("sign at 12 in 5") and "pole at" in e["text"]


def test_slower_speech_rate_predicts_further_v26211():
    fast, slow = _pol(2.0), _pol(0.5)
    for p in (fast, slow):
        p.ego_u = 1.0
    a = fast.step(10.0, [_item(1, "danger", 8, "pole", dist=5.6)], _tracks(1))
    b = slow.step(10.0, [_item(1, "danger", 8, "pole", dist=5.6)], _tracks(1))
    assert b["predicted"]["dt"] > a["predicted"]["dt"] and b["predicted"]["steps"] < a["predicted"]["steps"]


def test_a_passed_item_is_dropped_from_the_phrase_v26211():
    p = _pol()
    p.ego_u = 1.2
    e = p.step(10.0, [_item(1, "danger", 3.5, "pole", dist=2.0)], _tracks(1))     # 2.4 m walked > 2.0 m: passed, the beeps carry it
    assert e is None
    # ... and only the passed one of two is dropped
    p = _pol()
    p.ego_u = 1.2
    near, far = _item(1, "danger", 3.5, "pole", dist=2.0), _item(2, "danger", 9, "sign", dist=6.3)
    for i in (near, far):
        i.urgency = "danger"
    e = p.step(10.0, [near, far], _tracks(1, 2))
    assert e is not None and "pole" not in e["text"] and e["text"].startswith("sign at 12 in")


def test_a_trusted_mover_moves_with_its_world_velocity_v26211():
    p = _pol()
    p.ego_u = 1.0
    it = _item(1, "danger", 14, "person", group="moving", dist=9.8, approaching=True)
    it.urgency, it.people, it.pred_v = "danger", True, (-1.0, 0.0)          # walks towards us at 1 m/s
    e = p.step(10.0, [it], _tracks(1))
    dt = e["predicted"]["dt"]
    assert abs(e["predicted"]["fwd"] - (9.8 - 2.0 * dt)) < 0.02
    still = _pol()
    still.ego_u = 1.0
    it2 = _item(1, "danger", 14, "person", group="moving", dist=9.8, approaching=True)
    it2.urgency, it2.people = "danger", True
    e2 = still.step(10.0, [it2], _tracks(1))
    assert e["predicted"]["steps"] < e2["predicted"]["steps"]


def test_off_or_unknown_speed_says_today_v26211():
    off = _pol()
    off.pred_on, off.ego_u = False, 1.2
    e = off.step(10.0, [_item(1, "danger", 6, "pole", dist=4.2)], _tracks(1))
    assert e["text"] == "pole at 12 in 6" and "predicted" not in e
    unk = _pol()                                    # our speed is unknown: nothing is predicted
    e = unk.step(10.0, [_item(1, "danger", 6, "pole", dist=4.2)], _tracks(1))
    assert e["text"] == "pole at 12 in 6" and "predicted" not in e


# -- source.mode map -------------------------------------------------------------------------------------
def _stub_map(region=None):
    sm = col._StaticMap.__new__(col._StaticMap)
    sm.pose, sm.judged = (0.0, 0.0, 0.0), frozenset({"building"})
    sm.region = lambda it, pad, n: region
    return sm


class _WT:
    on = True

    def __init__(self, **kw):
        self.e = kw

    def lookup(self, tid, t):
        return self.e or None


def _track(trusted=True, **kw):
    return {"x": 0.4, "y": 8.3, "vx": 0.0, "vy": -1.0, "trusted": trusted, "state": "seen", "static": False, "promoted": False, "seenS": 2.0, **kw}


def _run_src(items, sm, wt):
    tracks = {it.track_id: col._Track(it.track_id, it.group, it.class_name, col.Box(0.4, 0.5, 0.5, 0.6), 0.0, 0.0, it.distance_m, 0.0) for it in items}
    for tr in tracks.values():
        tr.present_run = 5
    counts = {"map": 0, "track": 0, "image": 0}
    col._map_source(items, tracks, sm, wt, CONFIG["source"], 10.0, 0.7, 1.2, counts)
    return counts


def test_a_static_map_region_becomes_the_items_position_v26211():
    it = _item(1, "context", 0, "pole", dist=9.0)
    it.distance_m, it.lateral_m = 9.0, 0.0
    counts = _run_src([it], _stub_map((7.4, 1.1, 2, 9, 0.3)), _WT())
    assert it.srcsel == "map" and abs(it.distance_m - 7.4) < 1e-9 and abs(it.lateral_m - 1.1) < 1e-9 and it.map_cells == 2
    assert it.image_dl[0] == 9.0 and col._hazard_dict(it)["source"] == "map" and counts["map"] == 1
    assert it.clock_text != "12"


def test_a_mover_comes_from_its_trusted_world_track_v26211():
    it = _item(1, "none", 0, "person", group="moving", dist=8.0)
    it.people = True
    _run_src([it], _stub_map(), _WT(**_track()))
    assert it.srcsel == "track" and abs(it.distance_m - 8.3) < 1e-6 and abs(it.lateral_m - 0.4) < 1e-6
    along, lat, cross = it.track_motion
    assert along > 0.9 and abs(lat) < 0.1                       # walks towards us at ~1 m/s, straight
    assert it.closing > 1.9                                     # the gap shrinks by its own 1 + our 1.2 m/s


def test_the_image_safety_net_v26211():
    near = _item(1, "none", 0, "person", group="moving", dist=2.0)       # 2.0 m = 2.9 steps: the image keeps it
    untrusted = _item(2, "none", 0, "person", group="moving", dist=8.0)
    jump = _item(3, "none", 0, "person", group="moving", dist=8.0)
    pole = _item(4, "none", 0, "pole", dist=2.0)                         # static within 3 steps
    for i in (near, untrusted, jump, pole):
        i.people = True
    tr_near = _track(y=2.2)
    assert _run_src([near], _stub_map(), _WT(**tr_near))["image"] == 1 and near.srcsel == "image" and near.distance_m == 2.0
    _run_src([untrusted], _stub_map(), _WT(**_track(trusted=False)))
    assert untrusted.srcsel == "image" and untrusted.distance_m == 8.0
    _run_src([jump], _stub_map(), _WT(**_track(y=14.0)))                    # the track is 6 m from the image: not the same object
    assert jump.srcsel == "image"
    _run_src([pole], _stub_map((1.5, 0.0, 1, 4, 0.2)), _WT())
    assert pole.srcsel == "image" and pole.distance_m == 2.0
    young = _item(5, "none", 0, "pole", dist=9.0)
    tracks = {5: col._Track(5, "static", "pole", col.Box(0.4, 0.5, 0.5, 0.6), 0.0, 0.0, 9.0, 0.0)}
    tracks[5].present_run = 1
    col._map_source([young], tracks, _stub_map((7.0, 0.0, 1, 4, 0.2)), _WT(), CONFIG["source"], 10.0, 0.7, 1.2, {"map": 0, "track": 0, "image": 0})
    assert young.srcsel == "image" and young.distance_m == 9.0


def test_map_region_on_a_real_grid_v26211():
    """_StaticMap.region: the 8-connected region touching the item's footprint, nearest cell, width across the line of sight."""
    sm = col._StaticMap.__new__(col._StaticMap)
    n = 200
    fwd = np.repeat(((150 - np.arange(n))[:, None] * 0.1), n, axis=1)
    right = np.repeat(((np.arange(n) - 100)[None, :] * 0.1), n, axis=0)
    sm.ob = types.SimpleNamespace(size=n, fwd=fwd, right=right)
    sm.cell = 0.1
    sm.solid = np.zeros((n, n), dtype=bool)
    sm.solid[100:104, 110:113] = True            # region A: rows 100-103 (fwd 4.7-5.0), cols 110-112 (right 1.0-1.2)
    sm.solid[60:62, 150:152] = True              # a different region far away
    sm.classes = np.zeros((n, n), dtype=np.int64)
    sm.corr_full = (fwd > 0) & (np.abs(right) <= 0.6)
    sm._lut = lambda it: np.ones(256, dtype=bool)
    sm._footprint = lambda it, lut: (np.ones((3, 3), dtype=bool), 101, 110)
    r = sm.region(_item(1, "none", 0, "pole"), 2.0, 2)
    assert r is not None and abs(r[0] - 4.7) < 0.01 and abs(r[1] - 1.0) < 0.05 and r[2] == 0 and r[3] == 12
    assert 0.3 <= r[4] <= 0.7
    assert sm.region(_item(1, "none", 0, "pole"), 2.0, 13) is None          # fewer cells than the minimum: the image stays


# -- whole passes ------------------------------------------------------------------------------------------
def _pass(**ov):
    import copy
    from tests.worldtracks_fixtures import run_window
    cfg = copy.deepcopy(CONFIG)
    cfg["personSplit"]["enabled"] = False
    for k, v in ov.items():
        a, b = k.split("__")
        cfg[a][b] = v
    return run_window("chest0002_crosswalk", 0, None, cfg)


def test_image_mode_without_prediction_is_the_old_pass_v26211():
    import copy
    from tests.worldtracks_fixtures import run_window
    cfg = copy.deepcopy(CONFIG)
    cfg["personSplit"]["enabled"] = False
    cfg["speech"]["predictive"]["enabled"] = False
    _, doc, ev = run_window("chest0002_crosswalk", 0, None, cfg)
    old = copy.deepcopy(cfg)
    del old["source"], old["speech"]["predictive"]                       # a config of v26.2.10 has neither key
    _, doc0, ev0 = run_window("chest0002_crosswalk", 0, None, old)
    assert ev == ev0 and doc == doc0
    assert "sourceMode" not in doc["settings"] and not any("source" in h and h["source"] == "track" for f in doc["frames"] for h in f["hazards"])


def test_map_mode_pass_labels_every_item_with_its_source_v26211():
    _, doc, ev = _pass(source__mode="map")
    assert doc["settings"]["sourceMode"] == "map"
    srcs = {h.get("source") for f in doc["frames"] for h in f["hazards"] if not h.get("ghost") and not h.get("lanePart")}
    assert srcs <= {"map", "track", "image"} and "image" in srcs
    c = doc["settings"]["sourceCounts"]
    assert sum(c.values()) > 0


def test_predictive_events_carry_both_values_v26211():
    _, doc, ev = _pass()
    sp = [e for e in ev["events"] if e["type"] == "speech" and "predicted" in e]
    assert doc["settings"]["predictive"]["phrases"] >= len(sp) > 0
    assert all({"dt", "textNow"} <= set(e["predicted"]) for e in sp)
    assert any(e["text"] != e["predicted"]["textNow"] for e in sp)


def _events_hash(**ov) -> str:
    import copy
    import hashlib
    import json
    from tests.worldtracks_fixtures import run_window
    cfg = copy.deepcopy(CONFIG)
    for k, v in ov.items():
        a, b = k.split("__")
        cfg[a][b] = v
    _, _, ev = run_window("chest0004_review7", 0, "depth", cfg)
    return hashlib.sha256(json.dumps(ev["events"], sort_keys=True).encode()).hexdigest()


# Goldens of the v26.2.11 defaults on chest0004_review7 (window 0, depth). Every older golden is pinned with predictive off (tests/conftest.py),
# so none of them moved; these two pin the new behaviour.
# image + predictive on (each item timed to the end of its own mention): the phrases carry the positions at the end of the phrase (+ the `predicted` block); see CONTRACTS 7.11c
GOLDEN_IMAGE_PREDICTIVE = "6abedb3c721ec97f1e0956f2d39ce8a31971569c650e3a7c145a20f88dd2dfd0"
# map source + predictive on: map statics / track movers; the beeps of poles and signs beside the path come from the map region's corridor cells
GOLDEN_MAP_PREDICTIVE = "608ea76d4570ba232589b0e286acd1c9ae9180278079f26c3d2e0d2429356d19"


def test_goldens_of_the_new_defaults_v26211():
    h = (_events_hash(), _events_hash(source__mode="map"))
    assert h[0] == GOLDEN_IMAGE_PREDICTIVE, h[0]
    assert h[1] == GOLDEN_MAP_PREDICTIVE, h[1]
