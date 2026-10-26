"""v26.1.15 (review 7, Chest-center-0004, run 180acf11eedb, fixture ``chest0004_review7``): speech on time.

* Motion words (standing / approaching / moving away) and the people motion wait need a settled ego speed (the robust ego speed has its
  full ``egoMedianSeconds`` window): the person at 2.0 s was held back and then said "approaching" at 3.2 s from a ramping median.
* No start silence: the first WARMUP_S of a run no longer forces danger / feature roles to none, and a track needs no age (the 2-frame
  confirmation is the gate). A phrase with a danger in it is not delayed by an earlier feature phrase.
* The audio player's queue (priorities, preemption, late drops) is covered by the browser tests (tests/e2e/test_lab.py).
"""

from __future__ import annotations

import re

import numpy as np
import pytest

import collision as col
from tests.test_collision import (CONFIG, SPEED, _item, _policy, _rated, _tracks, approach_frames, motion, run, speech)
from tests.test_collision_regression import _run_windows

ROLES = CONFIG["roles"]


def test_version_and_config_are_unchanged_in_the_numbers_that_matter():
    assert CONFIG["version"] == "v26.2.4"
    assert ROLES["egoMedianSeconds"] == 3.0 and CONFIG["speech"]["peopleMotionWaitSeconds"] == 1.5
    assert CONFIG["speech"]["priorityMinGapSeconds"] == 1.0


# ---- unit: the warm-up rule -------------------------------------------------------------------

def _person(settled: bool, **kw):
    it = _rated("person", "moving", 9, 0.1, ego_known=True, **kw)
    it.ego_settled = settled
    return it


def test_motion_words_need_a_settled_ego_speed():
    kinds = {}
    for settled in (False, True):
        for name, kw in (("standing", dict(moving=False)), ("approach", dict(moving=True, approaching=True, closing=1.5)),
                         ("receding", dict(moving=True, receding=True, closing=0.3))):
            kinds[(name, settled)] = col.SpeechPolicy._kind(_person(settled, **kw), "danger")
    assert [kinds[(n, False)] for n in ("standing", "approach", "receding")] == ["danger"] * 3          # the plain phrase
    assert [kinds[(n, True)] for n in ("standing", "approach", "receding")] == ["standing", "approach", "receding"]


def test_a_rider_or_vehicle_approaching_keeps_its_word_without_a_settled_ego_speed():
    """It closes at several m/s: a ramping ego speed does not make it a different phrase (and the warning must not wait 3 s)."""
    r = _rated("rider", "moving", 12, 0.1, ego_known=True, moving=True, approaching=True, closing=4.0, urgency="danger")
    r.ego_settled = False
    r.own_fast = True                                             # v26.1.16: closing 4.0 - 2.0 (walking) >= approachingMps: set by the driver
    assert r.fast and col.SpeechPolicy._kind(r, "danger") == "approach"
    r.moving, r.approaching = False, False                        # but a stopped cyclist is a state word: it needs the settled speed
    assert col.SpeechPolicy._kind(r, "danger") == "danger"
    r.ego_settled = True
    assert col.SpeechPolicy._kind(r, "danger") == "stopped"


def test_the_people_motion_wait_does_not_apply_before_the_ego_speed_is_settled():
    p = _policy()
    tr = _tracks(1)
    p.danger_first[1] = 0.0
    unsettled, settled = _person(False, moving=None), _person(True, moving=None)
    for it in (unsettled, settled):
        it.track_id = 1
    assert not p._motion_pending(0.5, unsettled, tr)               # said at once, plain
    assert p._motion_pending(0.5, settled, tr)                     # (as before: ~1.5 s for the motion to be measured)
    assert not p._motion_pending(2.0, settled, tr)


# ---- unit: no start silence -------------------------------------------------------------------

def test_a_pole_in_the_lane_is_spoken_and_beeped_from_the_first_confirmed_frames():
    """Before v26.1.15 nothing danger / feature was said for the first 1.5 s (a guessed horizon) and a track needed 0.5 s of age."""
    frames = approach_frames(cls="pole", d0=6.5, seconds=4)
    doc, ev = run(frames, mot=motion(4))
    first = [e for e in ev["events"] if e["type"] in ("speech", "tone") and e["role"] in ("danger", "final", "feature")]
    assert first, ev["events"]
    assert min(e["t"] for e in first) < 0.5, [(e["t"], e.get("text")) for e in first]


def test_a_danger_is_not_delayed_by_an_earlier_feature_phrase():
    p = _policy()
    p.last_prio_t = 1.0                  # a feature phrase just now
    assert not p._gap_ok(1.4, priority=True)
    assert p._gap_ok(1.4, priority=True, danger=True)
    p.last_danger_t = 1.0                # ... but an earlier danger still holds the next one back for priorityMinGapSeconds
    assert not p._gap_ok(1.4, priority=True, danger=True)
    assert p._gap_ok(2.0, priority=True, danger=True)


# ---- review 7 (Chest-center-0004, 0-20 s from the start of the run) ---------------------------

@pytest.fixture(scope="module")
def review7():
    return _run_windows("chest0004_review7")


def test_review7_fixture_is_the_documented_one(review7):
    meta, npz, windows = review7
    assert [(w["start"], w["end"]) for w in meta["windows"]] == [(0.0, 20.0)]
    t = npz["w0_t"]
    assert t[0] < 0.05 and t[-1] >= 19.5 and npz["w0_grids"].shape == (len(t), meta["gridH"], meta["gridW"])
    ann = meta["annotations"]
    assert [a["kind"] for a in ann].count("added") == 1 and sum(a.get("verdict") == "correct" for a in ann) == 4
    assert [a["t"] for a in ann if a.get("verdict") == "remove"] == [3.1698]
    assert [e["text"] for e in meta["systemEventsV26_1_14"] if e["type"] == "speech" and e["t"] < 4] == [
        "building at 1:15 in 2, obstacle at 12:45 in 2", "pole at 11:45 in 9", "person approaching at 12:15 in 8"]


def test_review7_the_person_is_said_once_at_about_2_s_with_no_motion_word(review7):
    """The user added "Person static at 12 in 9" at 2.0 s and removed the "approaching" at 3.2 s ("same person"): one plain phrase
    at 2.0 s (the persons come within 10 steps at 1.8 s), nothing for them at 3.2 s."""
    _, _, windows = review7
    sp = windows[0]["speech"]
    people = [e for e in sp if "person" in e["text"] and e["t"] < 8]
    assert len(people) == 1 and 1.8 <= people[0]["t"] <= 2.6, [(e["t"], e["text"]) for e in sp]
    assert re.fullmatch(r"person at \d+(?::\d\d)? in \d+", people[0]["text"]), people[0]["text"]
    assert not [e for e in sp if "approaching" in e["text"] and e["t"] < 8]
    assert not [e for e in sp if 2.5 <= e["t"] <= 4.0]


def test_review7_the_persons_are_in_view_from_the_first_frames_and_become_dangers_within_10_steps(review7):
    _, _, windows = review7
    seen = {}
    for f in windows[0]["doc"]["frames"]:
        for h in f["hazards"]:
            if h["className"] == "person":
                seen.setdefault(h["trackId"], (f["t"], h["stepsTo"]))
    assert seen[28][0] < 0.3 and seen[44][0] < 0.5                    # first detected at 0.17 / 0.33 s, 13 steps away
    first_danger = min(f["t"] for f in windows[0]["doc"]["frames"] for h in f["hazards"] if h["className"] == "person" and h["role"] == "danger")
    assert first_danger < 2.0 and seen[44][1] > ROLES["movingDangerSteps"]      # ... and a danger as soon as they are within the 10 steps


def test_review7_nothing_is_silenced_at_the_start_of_the_run(review7):
    _, _, windows = review7
    sp = windows[0]["speech"]
    assert sp[0]["t"] < 0.5 and sp[0]["role"] in ("final", "danger", "context", "feature"), [(e["t"], e["text"]) for e in sp]
    assert [e for e in windows[0]["tones"] if e["t"] < 1.0]                          # beeps for the obstacle 2-3 steps ahead, no longer from 1.5 s


def test_review7_the_kept_entries_after_the_start_are_unchanged(review7):
    """4 x correct: the opening context phrase and the pole (now said as the obstacle at 0.17 s, the pole at 1.17 s and the building
    later: see DECISIONS v26.1.15), the beeps for the person at 6.0 s and the vegetation at 7.84 s are kept exactly."""
    _, _, windows = review7
    assert [e for e in windows[0]["speech"] if abs(e["t"] - 7.8412) < 0.05 and e["text"] == "vegetation at 12 in 9"]
    assert [e for e in windows[0]["beeps"] if abs(e["t"] - 6.006) < 0.05 and e["text"] == "beeps · center · person at 12 · 5 steps"]
