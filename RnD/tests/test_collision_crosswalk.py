"""v26.1.14: warn when stepping onto and off a crosswalk (deeper, longer tone in; the same deep tone twice out).

Units for the state machine (``_CrosswalkTracker``), the tone / episode events and their overlap rule, then the real-footage block:
``chest0002_crosswalk.{json,npz}`` (Lab run 341fd5511f4d, recording Chest-center-0002, six windows with crossings and one
single-frame flicker) and ``4929_review6`` (the same footage, 0-452 s, from the start)."""

from __future__ import annotations

import re

import numpy as np
import pytest

import collision as col
from tests.test_collision import CONFIG
from tests.test_collision_regression import _run_windows

CW = CONFIG["crosswalk"]
TONES = CONFIG["tones"]
DT = 1 / 6


def _feed(tracker, fractions, stationary=False, t0=0.0, dt=DT):
    """[(t, change)] for a list of fractions, one per frame."""
    out = []
    for i, f in enumerate(fractions):
        ch = tracker.update(t0 + i * dt, f, stationary(i) if callable(stationary) else stationary)
        if ch:
            out.append((round(t0 + i * dt, 3), ch))
    return out


def test_the_crosswalk_numbers():
    assert CONFIG["version"] == "v26.2.4"
    assert (CW["enterFraction"], CW["enterSeconds"], CW["exitFraction"], CW["exitSeconds"]) == (0.3, 0.5, 0.15, 0.7)
    assert CW["enterFraction"] > CW["exitFraction"]                     # hysteresis
    assert CONFIG["surfaces"]["seedBox"] == [0.40, 0.90, 0.60, 1.00]    # the box the share is measured in (under the feet)
    snd = TONES["sounds"]
    # deeper than the collision beeps (660-1100 Hz) and the proximity chirp (440 Hz); in is one long tone, out two short ones
    assert snd["crosswalk-in"]["pitchHz"] == snd["crosswalk-out"]["pitchHz"] == 330 < snd["proximity"]["pitchHz"] < snd["collision-left"]["pitchHz"]
    assert snd["crosswalk-in"]["durationMs"] == 600 and TONES["crosswalk"]["in"]["count"] == 1
    assert snd["crosswalk-out"]["durationMs"] == 200 and TONES["crosswalk"]["out"]["count"] == 2 and snd["crosswalk-out"]["intervalS"] == 0.12
    assert TONES["crosswalk"]["in"]["gain"] == TONES["crosswalk"]["out"]["gain"] == 0.5     # the collision beeps' gain (audio.js PEAK_GAIN)
    assert snd["crosswalk-in"]["durationMs"] > snd["collision-center"]["durationMs"] and TONES["crosswalk"]["maxOffsetSeconds"] <= 0.3


# --------------------------------------------------------------------------
# The state machine
# --------------------------------------------------------------------------

def test_enter_needs_the_share_held_for_half_a_second():
    tr = col._CrosswalkTracker(CW)
    got = _feed(tr, [0.0, 0.0] + [0.6] * 6)
    assert got == [(0.833, "enter")]                       # first frame above at 2/6 s, +0.5 s (the frame 3/6 s later)
    assert tr.inside


def test_a_flicker_or_a_weak_share_never_enters():
    tr = col._CrosswalkTracker(CW)
    assert _feed(tr, [0.0, 0.9, 0.9, 0.0, 0.0, 0.8, 0.0] * 3) == []                   # runs of 1-2 frames (0.17-0.33 s)
    assert _feed(tr, [0.29] * 30, t0=10) == []                                         # below enterFraction
    assert not tr.inside
    assert _feed(tr, [0.35] * 6, t0=20) == [(20.5, "enter")]                           # 0.3 is enough


def test_exit_needs_the_share_low_for_0_7_seconds_with_hysteresis():
    tr = col._CrosswalkTracker(CW)
    _feed(tr, [0.8] * 6)
    assert tr.inside
    assert _feed(tr, [0.2] * 30, t0=2) == []                                            # between the levels: still on the crosswalk
    got = _feed(tr, [0.1] * 8, t0=10)
    assert got == [(10.833, "exit")] and not tr.inside                                 # 4/6 s = 0.667 < 0.7: the frame at 5/6 s decides


def test_a_gap_in_the_crossing_does_not_end_it():
    tr = col._CrosswalkTracker(CW)
    _feed(tr, [0.8] * 6)
    assert _feed(tr, [0.0] * 3 + [0.6] + [0.0] * 3 + [0.5] + [0.0] * 3, t0=2) == []    # a stripe gap of <= 0.5 s


def test_standing_still_never_enters_and_a_stop_restarts_the_hold():
    tr = col._CrosswalkTracker(CW)
    assert _feed(tr, [0.9] * 30, stationary=True) == []
    assert _feed(tr, [0.9] * 8, t0=10, stationary=lambda i: i == 2) == [(11.0, "enter")]   # the stop at frame 2 restarts the hold at frame 3 (10.5 s) -> 11.0
    # leaving while standing still is still reported
    tr2 = col._CrosswalkTracker(CW)
    _feed(tr2, [0.9] * 6)
    assert [c for _, c in _feed(tr2, [0.0] * 8, t0=2, stationary=True)] == ["exit"]


def test_it_can_enter_again_after_exit():
    tr = col._CrosswalkTracker(CW)
    got = _feed(tr, [0.8] * 6 + [0.0] * 6 + [0.8] * 6)
    assert [c for _, c in got] == ["enter", "exit", "enter"]


def test_seed_fraction_counts_the_class_in_the_seed_box_only():
    g = np.zeros((100, 200), dtype=np.uint8)
    box = CONFIG["surfaces"]["seedBox"]
    assert col._seed_fraction(g, 8, box) == 0.0
    g[90:100, 80:120] = 8                                  # exactly the box
    assert col._seed_fraction(g, 8, box) == 1.0
    g[:, :] = 0
    g[0:60, :] = 8                                         # a crosswalk seen ahead, not under the feet
    assert col._seed_fraction(g, 8, box) == 0.0
    g[90:100, 80:100] = 8
    assert col._seed_fraction(g, 8, box) == pytest.approx(0.5)
    assert col._seed_fraction(g, None, box) == 0.0


# --------------------------------------------------------------------------
# The sounds
# --------------------------------------------------------------------------

def _tone_marks(marks, busy=()):
    return col._crosswalk_tones(marks, TONES["crosswalk"], list(busy), col.resolve_sounds(TONES)["kinds"])


def test_enter_is_one_deep_long_tone_and_exit_two_deep_short_ones():
    ev, eps = _tone_marks([(10.0, "enter"), (20.0, "exit")])
    enter, exit_ = ev
    assert enter["type"] == exit_["type"] == "tone" and (enter["kind"], exit_["kind"]) == ("crosswalk-in", "crosswalk-out")
    assert (enter["t"], enter["frequencyHz"], enter["durationSeconds"], enter["gain"]) == (10.0, 330.0, 0.6, 0.5)
    assert enter["chirp"]["count"] == 1
    assert (exit_["t"], exit_["frequencyHz"], exit_["durationSeconds"], exit_["gain"]) == (20.0, 330.0, 0.2, 0.5)
    assert exit_["chirp"] == {"count": 2, "gapSeconds": 0.12, "attackSeconds": 0.02}
    assert [e["type"] for e in eps] == ["beeps", "beeps"] and [e["kind"] for e in eps] == ["crosswalk-in", "crosswalk-out"]
    assert eps[0]["tEnd"] == pytest.approx(10.6) and eps[1]["tEnd"] == pytest.approx(20.52)    # 2 x 0.2 + 0.12
    assert "crosswalk in" in eps[0]["text"] and "crosswalk out" in eps[1]["text"]
    assert all(e["role"] == "feature" for e in ev + eps)


def test_a_crosswalk_tone_waits_for_a_busy_collision_tone_but_is_never_dropped():
    busy = [(10.0, 10.08, None), (10.2, 10.28, None)]
    ev, eps = _tone_marks([(10.0, "enter")], busy)
    assert len(ev) == 1 and 10.0 < ev[0]["t"] <= 10.3 + 1e-9                      # shifted, by at most 0.3 s
    ev, _ = _tone_marks([(10.0, "enter")], [(9.0, 12.0, None)])                  # a long continuous stream: capped
    assert len(ev) == 1 and ev[0]["t"] == pytest.approx(10.3)
    ev, _ = _tone_marks([(10.0, "exit")], [(11.0, 11.08, None)])                  # not overlapping: not moved
    assert ev[0]["t"] == 10.0


def test_run_collision_events_carry_the_crosswalk_tones_in_the_tone_list():
    marks = [(5.0, "enter"), (9.0, "exit")]
    events, eps = col._tone_events([], np.array([0.0, 1.0]), TONES, None, marks)
    assert [e["kind"] for e in events] == ["crosswalk-in", "crosswalk-out"] and len(eps) == 2
    events, eps = col._tone_events([], np.array([0.0, 1.0]), TONES, None, None)
    assert events == [] and eps == []


# --------------------------------------------------------------------------
# Real footage
# --------------------------------------------------------------------------

def _marks(events):
    return sorted((e["t"], e["kind"].split("-")[1]) for e in events if e["type"] == "tone" and e["kind"].startswith("crosswalk-"))


def _pairs(marks):
    """[(in t, out t)]; asserts the strict alternation in/out/in/out."""
    assert [m[1] for m in marks] == ["in", "out"] * (len(marks) // 2), marks
    return [(marks[i][0], marks[i + 1][0]) for i in range(0, len(marks), 2)]


@pytest.fixture(scope="module")
def chest():
    return _run_windows("chest0002_crosswalk")


# (window start, expected enter / exit times) from the share of the seed box in Chest-center-0002 (run 341fd5511f4d)
EXPECTED = {
    36.0: [(41.3, 50.3), (62.0, 64.8)],           # the long crossing (9 s) and a short one
    136.0: [(142.7, 145.5), (155.3, 157.8)],
    350.0: [],                                   # a single frame of crosswalk at 354.2 s: no tone
    384.0: [(392.2, 394.9), (404.7, 407.3)],
    580.0: [(585.0, 587.7)],
    1034.0: [(1038.8, 1041.3), (1050.0, 1052.7)],
}


def test_chest_crossings_get_one_in_and_one_out_and_the_flicker_none(chest):
    meta, _, wins = chest
    for w, out in zip(meta["windows"], wins):
        got = _pairs(_marks(out["events"]))
        want = EXPECTED[w["start"]]
        assert len(got) == len(want), (w, got)
        for (a, b), (wa, wb) in zip(got, want):
            assert a == pytest.approx(wa, abs=0.3) and b == pytest.approx(wb, abs=0.3), (w, got)
            assert w["start"] <= a < b <= w["end"]


def test_chest_crossings_last_between_2_and_10_seconds(chest):
    durations = [b - a for out in chest[2] for a, b in _pairs(_marks(out["events"]))]
    assert len(durations) == 9
    assert min(durations) >= 2.0 and max(durations) <= 10.0, durations
    assert max(durations) > 8.0                                          # the 9 s crossing at 41-50 s


def test_chest_tones_and_episodes_are_consistent(chest):
    for out in chest[2]:
        tones = [e for e in out["events"] if e["type"] == "tone" and e["kind"].startswith("crosswalk-")]
        eps = [e for e in out["events"] if e["type"] == "beeps" and e["kind"].startswith("crosswalk-")]
        assert len(tones) == len(eps) and [e["t"] for e in tones] == [e["t"] for e in eps]
        assert all(e["frequencyHz"] == 330.0 for e in tones)
        # the old kinds are untouched by the new ones
        assert all(e["kind"] in ("collision-left", "collision-center", "collision-right", "proximity") for e in out["tones"] + out["softTones"])


def test_the_speech_phrase_for_the_crosswalk_is_unchanged(chest):
    texts = [e["text"] for out in chest[2] for e in out["speech"] if "crosswalk" in e["text"]]
    assert texts and all(re.search(r"(^|, )crosswalk at \d+(?::\d\d)?( and \d+(?::\d\d)?)? in \d+(,|$)", t) for t in texts), texts


@pytest.fixture(scope="module")
def review6():
    return _run_windows("4929_review6")


def test_review6_footage_0_452_s_has_eight_crossings_and_no_false_triggers(review6):
    _, _, wins = review6
    pairs = _pairs(_marks(wins[0]["events"]))
    # the crosswalk-share segments of this footage: 40.7-49.3 (long), 61, 142, 154.7, 218.7, 233.3, 391.3, 403.8 (2-3 s each);
    # 354.2 (one frame, 0.8 share) is the only flicker
    starts = [40.7, 61.0, 142.0, 154.7, 218.7, 233.3, 391.3, 403.8]
    assert len(pairs) == 8, pairs
    for (a, b), s in zip(pairs, starts):
        assert s <= a <= s + 1.5 and a < b, (a, b, s)
    assert not any(353.0 < a < 356.0 for a, _ in pairs)
    assert all(2.0 <= b - a <= 10.0 for a, b in pairs)
    # the review-6 speech and the old tones are not changed by the new tones
    assert {e["kind"] for e in wins[0]["beeps"]} <= {"collision-left", "collision-center", "collision-right"}
