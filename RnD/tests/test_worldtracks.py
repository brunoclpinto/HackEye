"""World tracks in shadow mode (v26.2.9): the filter, the association, the unseen states, the path test, and that speech / beeps / every other
hazards key are byte-identical to v26.2.8 on every fixture window (hashes computed on v26.2.8 in tests/fixtures/worldtracks_baseline_v2628.json)."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

import worldtracks as wtm
from tests import worldtracks_fixtures as wf

DT = 1.0 / 6.0


def _meas(tid, wx, wy, pose, cls="person", group="moving", static=False, family=None):
    """The measurement of a world point seen from ``pose`` (x, y, heading deg)."""
    x, y, th = pose
    s, c = math.sin(math.radians(th)), math.cos(math.radians(th))
    dx, dy = wx - x, wy - y
    return {"tid": tid, "cls": cls, "family": family or cls, "group": group, "static": static,
            "fwd": dx * s + dy * c, "right": dx * c - dy * s, "depth": True}


def _wt(**kw):
    return wtm.WorldTracks(kw or None, 0.6, 118.0)


def _walk(wt, seconds, items, noise=0.1, seed=0, hidden=None, start=0.0):
    """User walks north at 1.4 m/s; ``items(t)`` -> list of (tid, wx, wy, kwargs) for the frame. Returns the per-frame outputs."""
    rng = np.random.default_rng(seed)
    out = []
    for k in range(int(seconds / DT)):
        t = start + k * DT
        pose = (0.0, 1.4 * t, 0.0)
        ms = []
        for tid, wx, wy, kw in items(t):
            m = _meas(tid, wx + rng.normal(0, noise), wy + rng.normal(0, noise), pose, **kw)
            ms.append(m)
        out.append(wt.step(t, pose, ms, 0.0, hidden(t, pose) if hidden else None))
    return out


def test_static_pole_has_no_world_speed_and_a_stable_position():
    wt = _wt()
    out = _walk(wt, 8, lambda t: [(1, 2.0, 25.0, {"cls": "pole", "group": "static", "static": True})])
    last = out[-1][0]
    assert last["state"] == "seen" and last["staticLike"]
    assert last["speedMps"] < 0.15
    xs = np.array([[o[0]["x"], o[0]["y"]] for o in out[12:]])
    assert xs.std(axis=0).max() < 0.15 and abs(xs[-1, 0] - 2.0) < 0.2 and abs(xs[-1, 1] - 25.0) < 0.3


def test_person_crossing_in_front_velocity_and_course():
    wt = _wt()
    # at t = 0 the person is 5.6 m ahead and 4.8 m left; walks east at 1.2 m/s while we walk north at 1.4: we meet at t = 4 s
    out = _walk(wt, 3.0, lambda t: [(1, -4.8 + 1.2 * t, 5.6, {})], noise=0.05)
    o = out[-1][0]
    assert abs(o["vx"] - 1.2) < 0.2 and abs(o["vy"]) < 0.2
    assert o["onCourse"] and o["ttcS"] is not None
    t_now = (len(out) - 1) * DT
    assert abs(o["ttcS"] - (3.79 - t_now)) < 0.5
    # a person walking away on our side of the road is not on course
    wt2 = _wt()
    out2 = _walk(wt2, 3.0, lambda t: [(1, 6.0 + 0 * t, 8.0 + 1.4 * t, {})])
    assert not out2[-1][0]["onCourse"]


def test_hidden_person_is_reidentified_with_a_new_image_track():
    wt = _wt()

    def items(t):
        if 2.0 <= t < 3.0:
            return []
        return [(1 if t < 2.0 else 2, 1.5, 8.0 + 0.5 * t, {})]
    out = _walk(wt, 5, items, hidden=lambda t, pose: (lambda f, r: True) if 2.0 <= t < 3.0 else None)
    states = [o[0]["state"] for o in out if o]
    assert "out-of-view" in states
    ids = {o[0]["id"] for o in out if o}
    assert ids == {"W1"}
    assert out[-1][0]["imageTracks"] == [1, 2] and out[-1][0]["trackId"] == 2 and out[-1][0]["state"] == "seen"


def test_detection_vanishing_in_plain_view_is_missing_then_dropped_after_three_frames():
    wt = _wt(missDropS=0.0, reviveS=0.0)          # v26.2.10 drop rule (v26.2.11 default: three frames AND 1 s, then revivable)

    def items(t):
        return [(1, 1.0, 12.0, {"cls": "pole", "group": "static", "static": True})] if t < 1.0 else []
    out = _walk(wt, 2.0, items)
    k = int(round(1.0 / DT))
    assert [o[0]["state"] for o in out[k:k + 3]] == ["missing", "missing", "dropped"]
    assert out[k + 3] == []


def test_a_jump_beyond_the_gate_starts_a_new_world_track():
    wt = _wt()

    def items(t):
        return [(1, 0.0, 10.0 if t < 1.0 else 18.0, {"cls": "pole", "group": "static", "static": True})]
    out = _walk(wt, 1.6, items, noise=0.02)
    last = out[-1]
    assert {o["id"] for o in last} >= {"W2"}
    new = [o for o in last if o["id"] == "W2"][0]
    assert new["state"] == "seen" and new["imageTracks"] == [1]


def test_skipped_classes_have_no_track():
    wt = _wt()
    out = _walk(wt, 1, lambda t: [(1, 0.0, 10.0, {"cls": "building", "group": "static", "static": True})])
    assert all(o == [] for o in out)


def test_out_of_view_beyond_the_field_of_view_coasts_then_drops():
    wt = _wt()
    out = _walk(wt, 8, lambda t: [(1, 0.0, 6.0, {"cls": "pole", "group": "static", "static": True})] if t < 0.5 else [])
    states = [o[0]["state"] if o else None for o in out]
    assert "missing" in states or "out-of-view" in states
    assert out[-1] == []                                              # behind the user by then


# ---------------------------------------------------------------- the pass: nothing it decides changes

@pytest.fixture(scope="module")
def baseline():
    return json.load(open(wf.FIXTURES / "worldtracks_baseline_v2628.json"))


def test_events_and_every_other_hazards_key_are_byte_identical_to_v2628_on_every_fixture_window(baseline):
    # (also pins that the v26.2.9 settings restore the old map and items exactly: decay time, no confrontation, no alignment, personSplit off)
    seen = 0
    cfg, wcfg = wf.v2629_configs()        # v26.2.10 changes the map and the people split by design; with the v26.2.9 settings nothing moved
    for label, meta, doc, ev in wf.all_runs(cfg, wcfg):
        assert wf.events_hash(ev) == baseline[label]["events"], label
        assert wf.hazards_hash(doc) == baseline[label]["hazards"], label
        seen += 1
    assert seen == len(baseline) and seen > 30


def test_the_hazards_doc_carries_world_tracks_and_their_settings():
    meta, doc, ev = wf.run_window("chest0004_review7", 0, "ground+depth")
    assert doc["worldTracksSettings"]["gateChi2"] == 9.21 and doc["worldTracksSettings"]["enabled"] is True
    tracks = [w for f in doc["frames"] for w in f["worldTracks"]]
    assert tracks and {"id", "class", "state", "imageTracks", "trackId", "x", "y", "vx", "vy", "fwd", "right", "speedMps", "headingDeg",
                       "relHeadingDeg", "sigmaM", "cpaM", "cpaS", "onCourse", "ttcS", "age", "unseenS"} <= set(tracks[0])
    assert all(len(f["worldTracks"]) <= 40 for f in doc["frames"])
    json.dumps(doc)
    assert {w["state"] for w in tracks} <= {"seen", "out-of-view", "missing", "dropped"}


def test_disabled_adds_nothing():
    import collision as col
    cfg = col.load_config()
    cfg["worldTracks"]["enabled"] = False
    meta, doc, ev = wf.run_window("chest0004_review7", 0, "depth", cfg)
    assert "worldTracksSettings" not in doc and all("worldTracks" not in f for f in doc["frames"])
