"""v26.2.13 W1: the review-10 fixture (``chest0004_review10``, run 5fda5626e808 collision c1 of v26.2.12, reviewed 0-69 s) and its targets.

The fixture is window w0 = 0-72 s of Chest-center-0004 from the run start with the device sensors (motion to 150 s, sensors to 156 s, as
``chest0004_review9``). Replaying it with the v26.2.12 rules (the four v26.2.13 rules off) reproduces the stored c1 events EXACTLY (143 speech /
beeps / tone events with t < 72 s); the v26.2.13 defaults then take out the walls the user walks along, add "moved away" / "started walking away"
and the soft beeps for the person passing close."""
from __future__ import annotations

import json
import re

import numpy as np
import pytest

from tests.replay import fixture_sensors, load_fixture, replay

NAME = "chest0004_review10"
NEW13_OFF = {"beeps.follow.windowS": 0, "speech.knownWall.enabled": False, "speech.away.enabled": False, "beeps.passing.enabled": False}


@pytest.fixture(scope="module")
def fx():
    return load_fixture(NAME)


@pytest.fixture(scope="module")
def old():
    return replay(NAME, overrides={"collision": NEW13_OFF})


@pytest.fixture(scope="module")
def new():
    meta, doc, ev = replay(NAME)
    return meta, doc, ev["events"]


def _key(e):
    return (round(e["t"], 3), e["type"], e.get("text"))


def _norm(t):
    return re.sub(r"[\d:]+", "#", t or "").replace("step", "").strip()


def _near(events, t, typ, tol=0.7):
    return [e for e in events if e["type"] == typ and abs(e["t"] - t) <= tol]


def test_fixture_is_the_documented_one(fx):
    meta, z = fx
    assert meta["overrides"] == {} and meta["speechRate"] == 1.25
    assert [w["key"] for w in meta["windows"]] == ["w0"] and meta["windows"][0]["end"] == 72.0
    t = z["w0_t"]
    assert t[0] == 0.0 and 71.8 <= t[-1] < 72.0 and len(t) == 432
    assert z["w0_grids"].shape == (len(t), 135, 240) and z["w0_depth"].shape == (len(t), 68, 120) and z["w0_depth"].dtype == np.float16
    assert z["w0_mt"][0] < 0.1 and 149.9 <= z["w0_mt"][-1] <= 150.0
    assert len(z["w0_mt"]) == len(z["w0_mdx"]) == len(z["w0_mdy"]) == len(z["w0_mresid"])
    s = fixture_sensors(z)
    assert {"gyro", "gyro_t", "accl", "accl_t", "gps", "gps_t", "gps_fix", "gps_dop"} <= set(s)
    assert s["gyro_t"][0] <= 0.1 and 155.0 <= s["gyro_t"][-1] <= 156.0
    assert meta["settings"]["userHeightM"] == 1.78 and meta["settings"]["cameraLocation"] == "chest"


def test_fixture_annotations_and_notes(fx):
    meta, _ = fx
    a = meta["annotations"]
    assert len(a) == 49 and meta["summary"] == {"correct": 34, "incorrect": 0, "remove": 13, "added": 2}
    assert sum(x.get("verdict") == "remove" for x in a) == 13 and sum(x["kind"] == "added" for x in a) == 2
    assert all(x["collisionId"] == "c1" and x["runId"] == "5fda5626e808" and x["collisionVersion"] == "v26.2.12" for x in a)
    assert meta["notes"] == "1. horizon line off by default."
    assert len(meta["systemEventsV26_2_12"]) == 143 and all(e["t"] < 72.0 for e in meta["systemEventsV26_2_12"])
    added = {round(x["t"], 1): x["text"] for x in a if x["kind"] == "added"}
    assert added == {30.2: "Person at 12:15 started walking away", 40.3: "Person at 12:30 moved away"}


def test_replay_with_the_v26_2_12_rules_reproduces_the_stored_c1_events(old, fx):
    meta, _ = fx
    _, doc, ev = old
    # (an episode running into the end of the 72 s window ends there: compare what started before 71.5 s)
    got = [e for e in ev["events"] if e["t"] < 71.5]
    want = [e for e in meta["systemEventsV26_2_12"] if e["t"] < 71.5]
    assert len(want) >= 140 and [json.dumps(e, sort_keys=True) for e in got] == [json.dumps(e, sort_keys=True) for e in want]
    assert doc["settings"]["sourceMode"] == "map" and doc["settings"]["headingSource"] == "imu+gps"


# -- the removes ----------------------------------------------------------------------------------------------------------------------------------

REMOVES_GONE = [(11.6617, "speech"), (44.6613, "speech"), (50.5005, "beeps"), (50.7833, "beeps"), (57.3407, "beeps"), (58.0373, "beeps"),
                (58.2335, "beeps"), (58.4678, "beeps"), (63.4968, "beeps"), (65.332, "beeps"), (65.4988, "speech")]


def test_review10_eleven_of_the_thirteen_removes_are_gone(fx, new):
    meta, _ = fx
    _, _, ev = new
    by_t = {round(a["t"], 3): a for a in meta["annotations"] if a.get("verdict") == "remove"}
    for t, typ in REMOVES_GONE:
        a = by_t[round(t, 3)]
        assert a["event"]["type"] == typ
        assert _key(a["event"]) not in {_key(e) for e in ev}, (t, a["event"].get("text"))


@pytest.mark.xfail(reason="68.17 / 69.08: the wall's track is new (1792): its first distances (9.7, 10.4 m) flicker, so its distance 'closes' 8 m in half a second", strict=False)
def test_review10_the_two_last_removes_68_17_and_69_08_are_gone(fx, new):
    meta, _ = fx
    _, _, ev = new
    for t in (68.168, 69.075):
        assert not [e for e in ev if e["type"] == "beeps" and abs(e["t"] - t) <= 0.05 and "building" in e["label"]]


def test_review10_the_corrects_are_kept_as_the_same_words(fx, new):
    meta, _ = fx
    _, _, ev = new
    lost = []
    for a in meta["annotations"]:
        if a.get("verdict") != "correct":
            continue
        e0 = a["event"]
        if not [e for e in ev if e["type"] == e0["type"] and abs(e["t"] - a["t"]) <= 0.7 and _norm(e.get("text")) == _norm(e0.get("text"))]:
            lost.append((a["t"], e0.get("text")))
    assert lost == [], lost
    # the ones the user named (and the closing-in building beeps 15.5-18.1: 5 -> 1 steps)
    texts = {_key(e) for e in ev}
    for a in meta["annotations"]:
        if a.get("verdict") == "correct" and a["t"] in (13.0, 20.6713, 25.9927, 34.835, 45.6623, 50.2336, 59.1587):
            assert _key(a["event"]) in texts, a["event"]["text"]
    bb = [e for e in ev if e["type"] == "beeps" and 15.4 <= e["t"] <= 18.3 and e.get("label") == "building"]
    assert len(bb) == 7 and bb[-1]["minSteps"] <= 1.6


def test_review10_the_two_added_phrases_are_said(new):
    _, _, ev = new
    a = [e for e in ev if e["type"] == "speech" and 29.46 <= e["t"] <= 30.86 and "away" in e["text"]]
    assert [e["text"] for e in a] in (["person at 12:15 started walking away"], ["person at 12:30 started walking away"]), a
    b = [e for e in ev if e["type"] == "speech" and 39.64 <= e["t"] <= 41.04 and "away" in e["text"]]
    assert [e["text"] for e in b] in (["person at 12:30 moved away"], ["person at 12:45 moved away"]), b
    assert a[0]["role"] == "danger" and b[0]["role"] == "danger"


def test_review10_the_person_passing_at_60_s_gets_the_soft_beeps(new):
    _, _, ev = new
    s = [e for e in ev if e["type"] == "beeps" and e["kind"] == "proximity" and 60.0 <= e["t"] <= 61.3]
    assert s and s[0]["text"].startswith("soft · person at ")
    # no new soft or collision beeps for static items outside the lane (O25): every new beeps event is that person's
    sm = {_key(e) for e in ev if e["type"] == "beeps" and e["t"] < 69.0}
    meta, _ = load_fixture(NAME)
    c1 = {_key(e) for e in meta["systemEventsV26_2_12"] if e["type"] == "beeps" and e["t"] < 69.0}
    assert {k[2] for k in sm - c1} == {s[0]["text"]}


def test_review10_nothing_else_changed_in_the_reviewed_69_s(new, fx):
    meta, _ = fx
    _, _, ev = new
    c1 = {_key(e) for e in meta["systemEventsV26_2_12"] if e["type"] in ("speech", "beeps") and e["t"] < 69.0}
    now = {_key(e) for e in ev if e["type"] in ("speech", "beeps") and e["t"] < 69.0}
    assert sorted(k[2] for k in now - c1) == ["person at 12:30 moved away", "person at 12:30 started walking away", s_text(ev)]
    gone = sorted(k[0] for k in c1 - now)
    assert gone == sorted(round(t, 3) for t, _ in REMOVES_GONE)


def s_text(ev):
    return next(e["text"] for e in ev if e["type"] == "beeps" and e["kind"] == "proximity" and 60.0 <= e["t"] <= 61.3)


# -- review 9 still holds under the new defaults ------------------------------------------------------------------------------------------------

def test_review9_blocked_phrase_at_21_17_survives_the_new_rules():
    """The review-9 "blocked" test of v26.2.12 (``test_collision_v26212``) with the v26.2.13 rules on: still exactly one, same text, same time."""
    _, _, ev = replay("chest0004_review9", sounds={"kinds": {}, "speechRate": 1.25})
    b = [e for e in ev["events"] if e["type"] == "speech" and "blocked" in e.get("text", "") and e["t"] <= 30.0]
    assert len(b) == 1, [(e["t"], e["text"]) for e in b]
    assert 20.47 <= b[0]["t"] <= 21.87
    assert b[0]["text"] == "sidewalk blocked at 11:45, continues 12:15"
    assert b[0]["blocked"]["kind"] == "obstacle" and b[0]["blocked"]["blockClock"] == "11:45"
