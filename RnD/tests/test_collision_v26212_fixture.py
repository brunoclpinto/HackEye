"""v26.2.12 W0: the review-9 fixture (``chest0004_review9``, run 5fda5626e808, collision re-run c2) and that the v26.2.11 code replays it.

The fixture is window w0 = 0-30 s of Chest-center-0004 from the run start (cold start) with the device sensors, replayed with the c2
overrides through ``tests/replay.py`` (the Lab's ``collision_pass`` inputs). Replay with the v26.2.11 rules reproduces the stored c2
speech, beeps and tones EXACTLY (65 events with t < 30 s). These replay tests pin the v26.2.11 behaviour: v26.2.12 changes the rules on
purpose, so the tests that compare with ``systemEventsV26_2_11`` are the ones to relax/update there (the fixture tests stay)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from tests.replay import fixture_sensors, load_fixture, replay

NAME = "chest0004_review9"
C2 = {"collision": {"source.mode": "map", "ego.headingSource": "imu", "horizon.source": "fused", "ego.cadenceSource": "imu"}}


@pytest.fixture(scope="module")
def fx():
    return load_fixture(NAME)


# the v26.2.12 rules switched off (the dotted keys of the Lab's overrides): what v26.2.11 did, so the stored events still pin its behaviour
V26211 = {"speech.minVoiceSteps": 0, "speech.thinStableS": 0, "speech.colocatedM": 0, "speech.zoneOnly.enabled": False,
          "speech.reannounce.enabled": False, "speech.predictive.maxAdvanceM": 0, "speech.predictive.clockHoldQuarters": 0,
          "speech.predictive.measuredFloor": 0, "distance.jump.enabled": False, "tree.enabled": False, "beeps.follow.enabled": False,
          "blocked.enabled": False}


@pytest.fixture(scope="module")
def run():
    return replay(NAME, overrides={"collision": {**C2["collision"], **V26211}})


def _key(e):
    return json.dumps(e, sort_keys=True)


def test_fixture_is_the_documented_one(fx):
    meta, z = fx
    assert meta["overrides"] == C2
    assert [w["key"] for w in meta["windows"]] == ["w0"] and meta["windows"][0]["end"] == 30.0
    t = z["w0_t"]
    assert t[0] == 0.0 and 29.8 <= t[-1] <= 30.0
    assert z["w0_grids"].shape == (len(t), meta["gridH"], meta["gridW"]) == (len(t), 135, 240)
    assert z["w0_depth"].shape == (len(t), 68, 120) and z["w0_depth"].dtype == np.float16
    assert z["w0_mt"][0] < 0.1 and 149.9 <= z["w0_mt"][-1] <= 150.0               # motion far past the window: the gyro bias needs it
    assert len(z["w0_mt"]) == len(z["w0_mdx"]) == len(z["w0_mdy"]) == len(z["w0_mresid"])
    s = fixture_sensors(z)
    assert {"gyro", "gyro_t", "accl", "accl_t", "gps", "gps_t", "gps_fix", "gps_dop"} <= set(s)
    assert s["gyro_t"][0] <= 0.1 and 155.0 <= s["gyro_t"][-1] <= 156.0 and 155.0 <= s["accl_t"][-1] <= 156.0
    assert len(s["gyro"]) == len(s["gyro_t"])
    assert meta["settings"]["userHeightM"] == 1.78 and meta["settings"]["cameraLocation"] == "chest"


def test_fixture_annotations_and_events(fx):
    meta, _ = fx
    a = meta["annotations"]
    assert len(a) == 24 and meta["summary"] == {"correct": 16, "incorrect": 1, "remove": 5, "added": 2}
    assert all(isinstance(x["predicted"], bool) for x in a)
    assert all(x["collisionId"] == "c2" and x["runId"] == "5fda5626e808" for x in a)
    # the predicted phrases the user judged without knowing they were predicted (note 5)
    pred = {x["t"]: x["event"]["text"] for x in a if x["predicted"]}
    assert 1.1678 in pred and 18.335 in pred and 23.5068 in pred and len(pred) == 5
    ev = meta["systemEventsV26_2_11"]
    assert len(ev) == 65 and all(e["t"] < 30.0 for e in ev)
    assert {e["type"] for e in ev} == {"speech", "beeps", "tone"}
    # a predicted annotation is a speech event with a predicted block; nothing else is
    by_t = {(e["t"], e["type"], e.get("text")): e for e in ev}
    for x in a:
        e = x.get("event")
        if e:
            assert bool(by_t[(e["t"], e["type"], e.get("text"))].get("predicted")) == x["predicted"]
    assert "speech speed" in meta["notes"] and "predictive speech" in meta["notes"]


def test_replay_with_the_v26_2_11_code_reproduces_the_stored_events(run, fx):
    """Exact: speech, beeps and tones with t < 30 s (the last, cut beep episode aside) (the sensors and the motion to 150 s make the gyro bias, the GPS course and the cadence
    the ones of the full run)."""
    meta, doc, ev = run
    stored = meta["systemEventsV26_2_11"]
    new = [e for e in ev["events"] if e["t"] < 30.0]
    # the one beep episode that runs past the end of the 30 s window (29.46 s, person 1016) is cut there: same start, kind and track, a shorter
    # tEnd / minSteps. Everything else is identical.
    cut = lambda e: e["type"] == "beeps" and e["tEnd"] >= 29.5
    for typ in ("speech", "beeps", "tone"):
        a = [_key(e) for e in stored if e["type"] == typ and not cut(e)]
        b = [_key(e) for e in new if e["type"] == typ and not cut(e)]
        assert a and a == b, (typ, len(a), len(b))
    edge = lambda es: [(e["t"], e["kind"], e["trackId"]) for e in es if cut(e)]
    assert edge(stored) == edge(new) == [(29.4614, "collision-center", 1016)]
    assert len(new) == len(stored) == 65
    assert doc["settings"]["gyroBiasSource"] == "stationary"                  # not the 'lowest' fallback of a bare 30 s clip
    assert doc["settings"]["headingSource"] == "imu+gps" and doc["settings"]["horizonSource"] == "fused"


def test_without_sensors_the_replay_differs(fx):
    """The sensors are part of the fixture on purpose: without them the same overrides are not the reviewed run."""
    meta, _ = fx
    _, _, ev = replay(NAME, use_sensors=False)
    stored = [_key(e) for e in meta["systemEventsV26_2_11"] if e["type"] == "beeps"]
    new = [_key(e) for e in ev["events"] if e["type"] == "beeps" and e["t"] < 30.0]
    assert stored != new
