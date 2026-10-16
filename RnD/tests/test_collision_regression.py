"""Regression tests on the user's first real-footage review (recording 4929, collision v26.1.1 -> v26.1.5).

Fixture: ``tests/fixtures/4929_review1.{json,npz}`` (see CONTRACTS.md section 12.3). Three
non-contiguous windows of the recording (0-10 s, 14-21 s, 27-31 s), each run as its own
independent sequence, so the start summary applies at each window start. Windows 1 and 2
therefore have no memory of what was said before them in the full run.

Note on the t=29.15 "person, 3 steps" annotation: run as a window, v26.1.1 does not reproduce it
(the ego state is cold, so the item is 4.9 steps away, not 3); in the full run it does. The person is a
single-frame danger flicker of a 50 px component, which is what the confirmation rule targets; the
unit tests in test_collision.py cover the rule itself on synthetic grids.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import collision as col

FIXTURES = Path(__file__).resolve().parent / "fixtures"
META = json.load(open(FIXTURES / "4929_review1.json"))
CONFIG = col.load_config()
_S = META["settings"]
SETTINGS = col.resolve_settings(CONFIG, _S["mount"], _S["hfovDeg"], _S["cameraHeightM"], _S["stepLengthM"])
VEHICLE_WORDS = ("vehicle", "parked car")


@pytest.fixture(scope="module")
def npz():
    return np.load(FIXTURES / "4929_review1.npz")


@pytest.fixture(scope="module")
def windows(npz):
    out = []
    for i in range(3):
        motion = {"t": npz[f"w{i}_mt"], "dx": npz[f"w{i}_mdx"], "dy": npz[f"w{i}_mdy"]}
        doc, ev = col.run_collision(npz[f"w{i}_grids"], npz[f"w{i}_t"], META["classNames"], CONFIG, SETTINGS, motion)
        out.append({"doc": doc, "speech": [e for e in ev["events"] if e["type"] == "speech"]})
    return out


def _near(events, t, tol):
    return [e for e in events if abs(e["t"] - t) <= tol]


def test_fixture_is_the_documented_one(npz):
    assert [w["key"] for w in META["windows"]] == ["w0", "w1", "w2"]
    for i, w in enumerate(META["windows"]):
        t = npz[f"w{i}_t"]
        assert t[0] >= w["start"] - 0.5 and t[-1] <= w["end"] + 0.5
        assert npz[f"w{i}_grids"].shape == (len(t), META["gridH"], META["gridW"])
    assert CONFIG["version"] == "v26.1.5"


def test_start_summary_names_building_and_obstacle_within_the_first_1_5_s(windows):
    """Annotation f8a55082: expected "Obstacle at 12, Building at 2" and nothing was said.

    The scene really has both: a sidewalk-obstacle (a context item at 11-12 o'clock, 3-4 m) and a
    building at 2 o'clock in the first frames, so both must be named, in one grouped phrase.
    """
    w0 = windows[0]
    first_hazards = [h for f in w0["doc"]["frames"] if f["t"] <= 1.0 for h in f["hazards"]]
    assert any(h["className"] == "sidewalk-obstacle" and h["role"] == "context" for h in first_hazards)
    assert any(h["className"] == "building" and h["role"] == "context" for h in first_hazards)
    ctx = [e for e in w0["speech"] if e["role"] == "context" and e["t"] <= 1.5]
    assert ctx, "no context phrase in the first 1.5 s"
    text = ctx[0]["text"].lower()
    assert "building" in text and "obstacle" in text
    assert text.count(" at ") >= 2 and "o'clock" not in text      # one grouped phrase, "{label} at {clock}"


def test_vehicle_and_building_context_after_the_turn_near_6_6_s(windows):
    """The data supports annotation 302fe78c: the model sees a vehicle at 11 o'clock (4.5 m, area ~2 percent)
    and a building at 1 o'clock; the user turned at 5.8 s, which clears the memory."""
    w0 = windows[0]
    hz = [(f["t"], h) for f in w0["doc"]["frames"] if 6.0 <= f["t"] <= 7.2 for h in f["hazards"]]
    assert any(h["className"] == "vehicle" and h["role"] == "context" and h["clock"] in (11, 12) for _, h in hz)
    assert any(h["className"] == "building" and h["role"] == "context" and h["clock"] in (1, 2) for _, h in hz)
    near = [e for e in _near(w0["speech"], 6.6, 2.0) if e["role"] == "context"]
    assert any(any(w in e["text"].lower() for w in VEHICLE_WORDS) for e in near), near
    assert any("building" in e["text"].lower() for e in near), near


def test_static_vehicle_is_no_danger_and_context_is_not_repeated_in_window_1(windows):
    sp = windows[1]["speech"]
    # 16.35 s "vehicle, 10 o'clock, 5 steps": a vehicle beside the path, already referenced
    bad = [e for e in _near(sp, 16.35, 1.5) if e["role"] in ("danger", "final")
           and any(w in e["text"].lower() for w in VEHICLE_WORDS)]
    assert bad == []
    assert not [e for e in sp if e["role"] in ("danger", "final") and any(w in e["text"] for w in VEHICLE_WORDS)]
    # 18.85 s "parked car at 12 o'clock": a repeat of what the start summary / earlier phrase named
    rep = [e for e in _near(sp, 18.85, 1.5) if "parked car" in e["text"].lower()]
    assert rep == []
    assert len([e for e in sp if e["role"] == "context" and any(w in e["text"].lower() for w in VEHICLE_WORDS)]) <= 1
    # the vehicle in that window is never a danger hazard on the first sighting at 16.35
    veh = [h for f in windows[1]["doc"]["frames"] if 16.0 <= f["t"] <= 16.7 for h in f["hazards"]
           if h["className"] == "vehicle"]
    assert veh and all(h["role"] != "danger" for h in veh)


def test_no_false_person_final_in_window_2(windows):
    sp = windows[2]["speech"]
    assert not [e for e in _near(sp, 29.15, 1.5) if e["role"] == "final" and "person" in e["text"].lower()]
    assert not [e for e in sp if "person" in e["text"].lower()]
    # the person was a single-frame danger: never confirmed over two consecutive frames
    run = best = 0
    for f in windows[2]["doc"]["frames"]:
        if 28.5 <= f["t"] <= 30.0 and any(h["className"] == "person" and h["role"] == "danger" for h in f["hazards"]):
            run += 1
            best = max(best, run)
        else:
            run = 0
    assert best <= 1


def test_every_final_phrase_has_the_clock_in_every_window(windows):
    finals = [e for w in windows for e in w["speech"] if e["role"] == "final"]
    assert all("o'clock" in e["text"] for e in finals)
    assert all("o'clock" in e["text"] for w in windows for e in w["speech"] if e["role"] in ("danger", "final"))


def test_context_phrases_use_the_grouped_template(windows):
    for w in windows:
        for e in w["speech"]:
            if e["role"] == "context":
                items = e["text"].split(", ")
                assert 1 <= len(items) <= CONFIG["speech"]["contextMaxItems"]
                assert all(" at " in it and "o'clock" not in it for it in items)
