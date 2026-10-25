"""v26.1.12 (review 5): movers within 10 steps, beeps from 5 steps, "approaching" re-announced once, motion states that say
nothing when unsure, motion available earlier for people, unknown motion near the user beeps.

Synthetic units for every rule, then the real-footage block on ``4929_review5.{json,npz}`` (one window, 0-110 s, no depth maps)."""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

import collision as col
from tests.test_collision import CONFIG, _item, _policy, _rated, _tracks
from tests.test_collision_regression import FIXTURES, _all, _load, _near, _produced, _run_windows
from tests.test_collision_v26111 import _mover

ROLES = CONFIG["roles"]


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def test_the_v26112_numbers():
    assert CONFIG["version"] == "v26.2.2"            # (the file keeps the v26.1.12 rules; the version is the current one)
    assert ROLES["movingDangerSteps"] == ROLES["dangerSteps"] == 10
    assert CONFIG["tones"]["maxSteps"] == 5 and CONFIG["tones"]["bySteps"][0][0] == 5
    assert ROLES["approachingMps"] == 0.4 and ROLES["standingMps"] == 0.3 and ROLES["standingHoldSeconds"] == 1.0
    assert "unknownMotionBeepSteps" not in ROLES        # v26.1.13: unknown motion no longer beeps (``beepLateralM``)
    assert CONFIG["tracking"]["peopleMotionMinSeconds"] < CONFIG["tracking"]["motionMinSeconds"]


# --------------------------------------------------------------------------
# 1. Reach: movers are spoken within 10 steps
# --------------------------------------------------------------------------

def test_movers_are_spoken_within_10_steps_not_15():
    assert _rated("person", "moving", 10, 0.3, moving=None).role == "danger"
    assert _rated("person", "moving", 11, 0.3, moving=None).role == "none"
    assert _rated("person", "moving", 12, 0.3, moving=True, receding=True, closing=0.3).role == "none"      # 54.7 / 63.5 s
    assert _rated("person", "moving", 9, 0.3, moving=True, receding=True, closing=0.3).role == "danger"
    assert _rated("person", "moving", 11, 0.3, moving=True, approaching=True, closing=2.0).role == "none"


# --------------------------------------------------------------------------
# 2. Beeps: a collision course within 5 steps only
# --------------------------------------------------------------------------

def test_beeps_start_at_5_steps_and_carry_a_table_that_ends_there():
    from tests.test_collision import approach_frames, hz, motion, run, tones
    doc, ev = run(approach_frames(seconds=15), mot=motion(15))
    tn = tones(ev)
    assert tn
    pole = dict(hz(doc, "pole"))
    steps = [min((h["stepsTo"] for t, h in hz(doc, "pole") if abs(t - e["t"]) < 0.2), default=None) for e in tn]
    assert max(s for s in steps if s is not None) <= 5.5, steps       # (the frame the tone belongs to is up to 0.17 s older)
    gaps = np.diff([e["t"] for e in tn])
    assert gaps.max() <= 0.55                                           # no interval longer than the 5-step one (0.5 s)
    by = CONFIG["tones"]["bySteps"]
    assert col._tone_interval(5, by) == 0.5 and col._tone_interval(9, by) == 0.5


# --------------------------------------------------------------------------
# 3. "approaching" is announced again, once
# --------------------------------------------------------------------------

def test_a_mover_announced_before_is_announced_again_once_when_it_turns_to_approaching():
    p = _policy()
    tr = _tracks(1)
    far = _mover(1, "person", 9, 12, "receding")
    far.clock_q, far.clock_text = 1, "12:15"
    assert p.step(0.0, [far], tr)["text"] == "person moving away at 12:15 in 9"          # (v26.1.13: with the distance)
    assert p.step(1.0, [far], tr) is None
    it = _mover(1, "person", 8, 12, "approach")
    it.clock_q, it.clock_text = 1, "12:15"
    assert p.step(2.0, [it], tr) is None                             # (the label gap: same label, 5 s)
    e = p.step(6.0, [it], tr)
    assert e["text"] == "person approaching at 12:15 in 8" and e["trackId"] == 1
    assert tr[1].approach_done
    assert p.step(12.0, [it], tr) is None and p.step(20.0, [it], tr) is None            # once per track and state
    back = _mover(1, "person", 7, 12, "receding")
    assert p.step(30.0, [back], tr) is None                           # no other re-announcement


def test_a_plain_phrase_is_followed_by_approaching_and_a_first_approaching_counts_as_done():
    p = _policy()
    tr = _tracks(1, 2)
    plain = _mover(1, "person", 9, 12, "unknown")
    assert p.step(0.0, [plain], tr)["text"] == "person at 12 in 9"
    plain2 = _mover(1, "person", 8, 12, "approach")
    assert p.step(6.0, [plain2], tr)["text"] == "person approaching at 12 in 8"
    fresh = _mover(2, "person", 8, 12, "approach")
    assert p.step(12.0, [fresh], tr)["text"] == "person approaching at 12 in 8"
    assert tr[2].approach_done and not tr[2].final_done
    assert p.step(18.0, [fresh], tr) is None


# --------------------------------------------------------------------------
# 4. Motion states
# --------------------------------------------------------------------------

def _state(track, t, along, side=0.0, cross=None):
    track.mstate = col._motion_state(track, t, along, side, cross, ROLES)
    return track.mstate


def _fresh_track():
    return _tracks(1)[1]


def test_standing_needs_a_second_below_03_mps():
    tr = _fresh_track()
    states = [_state(tr, 0.17 * i, 0.1) for i in range(8)]
    assert states[:6] == [None] * 6 and states[6] == "still" and states[7] == "still"      # 1 s later
    # once standing it stays so up to 0.4, leaves above
    assert _state(tr, 1.5, 0.35) == "still"
    assert _state(tr, 1.7, 0.45) == "approach"


def test_the_band_between_03_and_04_is_unknown_not_standing_and_a_break_restarts_the_hold():
    tr = _fresh_track()
    assert [_state(tr, 0.17 * i, 0.35) for i in range(10)] == [None] * 10               # in between: never "standing"
    tr = _fresh_track()
    for i in range(5):
        _state(tr, 0.17 * i, 0.05)
    assert _state(tr, 0.9, 0.36) is None and tr.still_t0 is None                          # a break
    assert [_state(tr, 1.0 + 0.17 * i, 0.05) for i in range(7)][-1] == "still"


def test_a_person_walking_away_at_06_is_not_standing():
    """Review 5, 105.1 s: "person standing ... person is moving away" (own speed -0.6 m/s)."""
    tr = _fresh_track()
    states = [_state(tr, 0.17 * i, -0.6) for i in range(10)]
    assert set(states) == {"recede"}
    # the hysteresis: once receding it stays down to 0.3
    assert _state(tr, 2.0, -0.32) == "recede" and _state(tr, 2.2, -0.2) is None


def test_possible_sideways_motion_vetoes_standing():
    """Review 5, 41.8 s: "not standing, it's moving towards left"."""
    tr = _fresh_track()
    states = [_state(tr, 0.17 * i, -0.1, cross=-0.7) for i in range(10)]
    assert set(states) == {None}
    tr = _fresh_track()
    assert [_state(tr, 0.17 * i, -0.1, cross=-0.3) for i in range(8)][-1] == "still"
    assert _state(tr, 3.0, 0.0, side=-3.0) == "side"


def test_cross_velocity_of_a_static_item_is_zero_while_we_walk_and_turn_and_of_a_mover_is_its_own():
    speed, window = 1.4, 1.0
    for lat0, d0 in ((1.0, 8.0), (-3.0, 5.0), (1.0, 9.0)):
        hist = []
        for i in range(12):
            t = i / 6
            heading = 8.0 * t                                      # we turn right at 8 deg/s
            d = d0 - speed * t
            bearing = math.degrees(math.atan2(lat0, d)) - heading  # a turn to the right moves the scene left
            hist.append((t, lat0, d, heading, bearing))
        assert col._cross_velocity(hist, speed, window) == pytest.approx(0.0, abs=0.4)       # (the parallax term uses the observed bearing)
        straight = [(t, la, d, 0.0, math.degrees(math.atan2(la, d))) for t, la, d, _, _ in hist]
        assert col._cross_velocity(straight, speed, window) == pytest.approx(0.0, abs=0.1)
        moving = []
        for t, lat, d, h, _ in hist:                               # (walking straight: the camera axis is the walking direction)
            lat_m = lat + 1.0 * t                                  # walks right at 1 m/s
            moving.append((t, lat_m, d, 0.0, math.degrees(math.atan2(lat_m, d))))
        assert col._cross_velocity(moving, speed, window) == pytest.approx(1.0, abs=0.3)      # (cos of the bearing: 0.6-1.0)
    assert col._cross_velocity(hist[:3], speed, window) is None                             # too short
    assert col._cross_velocity(hist, None, window) is None                                  # our speed unknown
    assert col._cross_velocity([(t, la, d, None, b) for t, la, d, _, b in hist], speed, window) is None


# --------------------------------------------------------------------------
# 5. Unknown motion near the user
# --------------------------------------------------------------------------

def test_unknown_motion_and_arms_length_approach_no_longer_beep_v26113():
    """v26.1.12 beeped for these (review 5, 90.8 s); review 6 (four beep entries at 1.2-3.0 m) took it back: beeps need a
    real collision course (``beepLateralM``, see ``test_collision_v26113.py``); the person is spoken at 5-10 steps instead."""
    assert not _rated("person", "moving", 4.8, 2.15, moving=None).collision
    assert _rated("person", "moving", 4.8, 0.5, moving=None).collision
    assert not _rated("person", "moving", 4.5, 2.2, moving=True, approaching=True, closing=2.0).collision


def test_a_person_gets_a_closing_speed_after_half_a_second_and_a_pole_still_after_three_quarters():
    horizon, ch, gh, f = 0.45, 1.3, 135, 150.0
    hist = [(0.1667 * i, 0.60 + 0.004 * i) for i in range(4)]                 # 4 samples over 0.5 s
    trk = CONFIG["tracking"]
    assert col._closing_mps(hist, horizon, ch, gh, f, trk["motionMinRowsBelowHorizon"], trk["peopleMotionMinSeconds"]) is not None
    assert col._closing_mps(hist, horizon, ch, gh, f, trk["motionMinRowsBelowHorizon"], trk["motionMinSeconds"]) is None


# --------------------------------------------------------------------------
# 6. Pronunciation lives in audio.js (Lab only); the text of the events is untouched
# --------------------------------------------------------------------------

def test_audio_js_has_the_pronunciation_map_and_the_phrase_text_is_not_changed():
    js = (FIXTURES.parent.parent / "lab" / "static" / "js" / "audio.js").read_text(encoding="utf-8")
    assert re.search(r"PRONUNCIATIONS\s*=\s*\[\[/\\bcurb\\b/gi,\s*\"kerb\"\]\]", js)
    assert "new SpeechSynthesisUtterance(spoken)" in js and "spoken, voice" in js
    assert CONFIG["spokenLabels"]["curb"] == "curb"                           # display text unchanged


# --------------------------------------------------------------------------
# Review 5 (v26.1.11, 4929 0-110 s; fixtures 4929_review5)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def review5():
    return _run_windows("4929_review5")


def _ann(meta, t, kind=None):
    return [a for a in meta["annotations"] if abs(a["t"] - t) < 0.01 and (kind is None or a["event"]["type"] == kind)]


def test_review5_fixture_is_the_documented_one():
    meta, settings = _load("4929_review5")
    npz = np.load(FIXTURES / "4929_review5.npz")
    assert [(w["start"], w["end"]) for w in meta["windows"]] == [(0.0, 110.0)]
    t = npz["w0_t"]
    assert t[0] < 0.2 and 109.5 <= t[-1] <= 110.0
    assert npz["w0_grids"].shape == (len(t), meta["gridH"], meta["gridW"])
    assert len(npz["w0_mt"]) == len(npz["w0_mdx"]) == len(npz["w0_mresid"]) > 2000
    ann = meta["annotations"]
    assert len(ann) == 17 and meta["summary"] == {"correct": 12, "incorrect": 3, "remove": 2, "added": 0}
    assert (sum(a["verdict"] == "correct" for a in ann), sum(a["verdict"] == "incorrect" for a in ann),
            sum(a["verdict"] == "remove" for a in ann)) == (12, 3, 2)
    assert max(a["t"] for a in ann) < 110.0 and all(a["runId"] == "2ced2e0f2909" for a in ann)
    assert any("kerb" in a["note"].lower() or "tarmack" in a["note"] for a in ann)
    assert meta["depth"] is None and settings.user_height_m == 1.78
    # the v26.1.11 events of the run, as the user heard them
    old = [e["text"] for e in meta["systemEventsV26_1_11"] if e["type"] in ("speech", "beeps")]
    assert "person standing at 1 in 4" in old and "person standing at 12:15 in 14" in old and len(old) == 19


def test_review5_window_run_reproduces_the_user_run_before_the_changes_in_what_did_not_change(review5):
    meta, _, windows = review5
    new = {(e["t"], e["text"]) for e in _all(windows) + _all(windows, "beeps")}
    for t, text in ((0.6673, "obstacle at 11:15 in 5"), (3.1698, "building at 12:45 in 4"), (15.5155, "pole at 12:15 in 11"),
                    (18.3517, "obstacle at 12:45 in 4"), (28.8205, "pole at 12 in 8"), (39.331, "curb at 12 in 3"),
                    (52.344, "crosswalk at 10:15 in 4"), (39.4978, "beeps · center · obstacle at 12 · 5 steps")):
        assert (t, text) in new, (t, text)


def test_review5_curb_is_still_said_as_curb_in_the_text(review5):
    """39.3 s ("text says curb, speech says tarmack"): the Lab's speech is "kerb" (audio.js), the event text stays."""
    assert [e for e in _near(_all(review5[2]), 39.331, 0.1) if e["text"] == "curb at 12 in 3"]


def test_review5_person_is_no_longer_standing_at_41_8_s(review5):
    meta, _, windows = review5
    assert not [e for e in _all(windows) if "standing" in e["text"] and 38 <= e["t"] <= 46]
    assert not _produced(meta, windows, _ann(meta, 41.8335)[0])
    f = min((f for f in windows[0]["doc"]["frames"]), key=lambda f: abs(f["t"] - 41.83))
    hz = [h for h in f["hazards"] if h["trackId"] == 743][0]
    assert hz["moving"] is not False                                   # unknown, or moving away: never "standing"


def test_review5_far_movers_are_silent_at_54_7_and_63_5_s(review5):
    meta, _, windows = review5
    # v26.1.15: a feature phrase no longer holds a danger back for a second (priority gap): "person moving away at 11:45 in 9" is said at 53.0 s,
    # within the user's 10 steps; what stays silent is everything farther
    said = [e for e in _all(windows) if "person" in e["text"] and 53 <= e["t"] <= 76 and e["t"] != 76.4932]
    assert all(int(re.search(r" in (\d+)$", e["text"]).group(1)) <= CONFIG["roles"]["movingDangerSteps"] for e in said), said
    for t in (54.6797, 63.4801):
        assert not _produced(meta, windows, _ann(meta, t)[0])


def test_review5_approaching_is_said_instead_of_the_beeps_at_9_steps_at_76_5_s(review5):
    meta, _, windows = review5
    sp = [e for e in _near(_all(windows), 76.4932, 0.2) if e["text"].startswith("person approaching")]      # (ids shift with the tracking: v26.1.16)
    assert [e["text"] for e in sp] == ["person approaching at 12:15 in 9"]
    assert not [b for b in _all(windows, "beeps") if 70 <= b["t"] <= 80]                     # 9 steps: speech, no beeps
    assert not _produced(meta, windows, _ann(meta, 76.4932)[0])


def test_review5_the_person_at_90_8_s_is_announced_as_approaching_at_5_steps(review5):
    meta, _, windows = review5
    sp = [e for e in _near(_all(windows), 90.8408, 0.3) if e["text"].startswith("person approaching")]
    assert [e["text"] for e in sp] == ["person approaching at 12:45 in 5"]
    tid = sp[0]["trackId"]
    # v26.1.13: the speech carries it (5 steps, with the distance); the person is at 2.1 m, not on a collision course: no beeps
    assert not [b for b in _near(_all(windows, "beeps"), 90.84, 1.5) if b["trackId"] == tid]
    f = min(windows[0]["doc"]["frames"], key=lambda f: abs(f["t"] - 90.84))
    hz = [h for h in f["hazards"] if h["trackId"] == tid][0]
    assert hz["closingMps"] is not None and hz["moving"] is True                  # the motion is known 0.5 s after the first sighting


def test_review5_no_standing_phrase_at_105_1_s(review5):
    meta, _, windows = review5
    assert not [e for e in _all(windows) if "standing" in e["text"]]
    assert not _produced(meta, windows, _ann(meta, 105.1468)[0])


def test_review5_beeps_only_within_5_steps_and_only_for_collision_tracks(review5):
    _, _, windows = review5
    w = windows[0]
    for b in w["beeps"]:
        assert b["minSteps"] <= 5.0 + 1e-9 and b["role"] == "danger", b
        assert all(re.search(r"(\d+)(?:→(\d+))? steps?$", b["text"]) for _ in [0])
    steps_by_frame = {f["t"]: {h["trackId"]: h for h in f["hazards"]} for f in w["doc"]["frames"]}
    for tone in w["tones"]:
        t0 = max(t for t in steps_by_frame if t <= tone["t"] + 1e-9)
        h = steps_by_frame[t0].get(tone["trackId"])
        assert h is None or h["stepsTo"] <= 5.5, (tone, h)
    # no mover phrase beyond 10 steps
    for e in w["speech"]:
        m = re.search(r" in (\d+)$", e["text"])
        if m and re.match(r"(person|cyclist)", e["text"]):
            assert int(m.group(1)) <= 10, e


def test_review5_ticks_that_stay_and_ticks_that_move(review5):
    meta, _, windows = review5
    stay = [(0.6673, None), (3.1698, None), (15.5155, None), (18.3517, None), (28.8205, "speech"), (39.331, None),
            (39.4978, None), (52.344, None), (90.8408, None)]
    for t, kind in stay:
        for a in _ann(meta, t, kind):
            assert _produced(meta, windows, a), (t, a["event"]["text"])
    # moved on purpose: 28.8 pole beeps at 8 steps (beeps start at 5), 43.2 beeps for a person who is walking away (said as
    # "moving away"), 49.8 obstacle (context, held back by the dangers around it)
    for t, kind in ((28.8205, "beeps"), (43.1682, None), (49.8415, None)):
        for a in _ann(meta, t, kind):
            assert not _produced(meta, windows, a), (t, a["event"]["text"])
