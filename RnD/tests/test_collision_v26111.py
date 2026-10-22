"""v26.1.11 (review 4): motion state, collision course, vehicles, curbs, surface evidence, ego speed, stationary user.

Synthetic units for every rule (the real-footage checks are the review-4 block of test_collision_regression.py)."""

from __future__ import annotations

import copy
import math
import re

import numpy as np
import pytest

import collision as col
from tests.test_collision import (CONFIG, FPS, H, ID, W, _curb_band, _item, _policy, _poles_for_speed, _rated, _surface_frames,
                                  _tracks, approach_frames, base_grid, motion, run, speech, tones)

ROLES = CONFIG["roles"]


# --------------------------------------------------------------------------
# Item 8: the cadence refine can no longer leave the band (a -16.3 Hz reading at 336 s)
# --------------------------------------------------------------------------

def test_refine_rejects_a_parabola_that_leaves_the_bin_or_the_band():
    freqs = np.arange(0, 6.0, 0.1)
    power = np.zeros_like(freqs)
    k = 35                                                  # 3.5 Hz: the top of the search band
    power[k - 1], power[k], power[k + 1] = 10.0, 5.01, 0.0   # a bigger neighbour below: denom -0.02, shift -25 Hz
    assert col._refine(freqs, power, k) == pytest.approx(freqs[k])             # a move of 25 Hz is no refine
    assert col._refine(freqs, power, k, 0.8, 3.5) == pytest.approx(freqs[k])
    # an ordinary peak between two bins is still interpolated, within one bin
    power[:] = 0.0
    power[19], power[20], power[21] = 1.0, 4.0, 3.0
    f = col._refine(freqs, power, 20, 0.8, 3.5)
    assert freqs[20] < f < freqs[21]


def test_a_dead_cadence_never_reports_a_negative_or_out_of_band_rate():
    t = np.arange(0, 40, 1 / 24)
    rng = np.random.RandomState(3)
    dy = 0.002 * rng.randn(len(t)) + 0.0015 * np.sin(2 * math.pi * 3.45 * t)          # a faint peak at the band edge
    cad = col.estimate_cadence(t, dy, 4.0, (0.8, 3.5), 3.0)
    ok = cad[~np.isnan(cad)]
    assert len(ok) == 0 or (ok.min() > 0.7 and ok.max() < 7.5)


# --------------------------------------------------------------------------
# Item 6: stationary detector (residual flow -> state)
# --------------------------------------------------------------------------

def _resid(fps=24.0, spans=((0, 6, 2.7), (6, 16, 0.12), (16, 24, 2.7))):
    t = np.arange(0, spans[-1][1], 1 / fps)
    r = np.zeros(len(t))
    for a, b, v in spans:
        r[(t >= a) & (t < b)] = v
    return t, r


def test_stationary_is_entered_after_1_5_s_of_stillness_and_left_after_1_s_of_walking():
    t, r = _resid()
    rng = np.random.RandomState(1)
    r = r * (1 + 0.25 * rng.randn(len(r)))
    st = col.estimate_stationary(t, r, CONFIG["ego"]["stationary"])
    on = t[np.argmax(st)]
    off = t[len(st) - 1 - np.argmax(st[::-1])]
    assert not st[t < 6.0].any()                                    # walking: never
    assert 7.4 <= on <= 8.6                                         # 6 s + median window + 1.5 s
    assert 16.4 <= off <= 18.0 and not st[t > 18.2].any()


def test_stationary_ignores_a_spike_and_unknown_texture_never_enters_it():
    t, r = _resid(spans=((0, 12, 0.12),))
    r[int(5 * 24)] = 4.0                                            # one noisy frame
    st = col.estimate_stationary(t, r, CONFIG["ego"]["stationary"])
    assert st[t > 3.0].all()
    nan = np.full(len(t), np.nan)
    assert not col.estimate_stationary(t, nan, CONFIG["ego"]["stationary"]).any()
    # unknown texture while standing counts as walking evidence: the state is left, not held on a guess
    r2 = r.copy()
    r2[t >= 8.0] = np.nan
    st2 = col.estimate_stationary(t, r2, CONFIG["ego"]["stationary"])
    assert st2[(t > 3.0) & (t < 8.0)].all() and not st2[t > 10.0].any()


def test_without_the_residual_flow_the_user_is_never_stationary():
    doc, _ = run(approach_frames(seconds=8), mot=motion(8))
    assert not any(f["ego"]["stationary"] for f in doc["frames"])


def _stand_motion(seconds, still_from):
    m = motion(seconds)
    t = m["t"]
    m["resid"] = np.where(t < still_from, 2.7, 0.1)
    return m


def test_while_stationary_nothing_static_is_said_and_nothing_beeps():
    """The cadence detector still reads steps (bob), so only the picture says "standing": a pole in the lane ahead is
    announced and beeped when walking, and silent when the same scene is watched standing still."""
    frames = approach_frames(d0=22.0, seconds=14)
    walk, ev_walk = run(frames, mot=motion(14))
    assert any(e["role"] in ("danger", "final", "feature") for e in speech(ev_walk)) and tones(ev_walk)
    still, ev_still = run(frames, mot=_stand_motion(14, still_from=0.0))
    assert [f for f in still["frames"] if f["t"] > 2.6 and f["ego"]["stationary"] is False] == []
    late = [e for e in speech(ev_still) if e["t"] > 2.6]
    assert late == [] and [x for x in tones(ev_still) if x["t"] > 2.6] == []
    assert all(h["role"] == "none" for f in still["frames"] if f["t"] > 2.6 for h in f["hazards"])
    # standing: our own speed is 0, not the bob's cadence
    assert all(f["ego"]["speedMps"] == 0.0 for f in still["frames"] if f["ego"]["stationary"])


def test_while_stationary_a_mover_on_a_collision_course_is_still_a_danger():
    it = _rated("rider", "moving", 8, 0.2, moving=True, approaching=True, closing=3.0, lat_vel=None)
    assert it.role == "danger" and it.collision
    # (the driver silences everything that is not a measured mover on a collision course; see the scene test above)


# --------------------------------------------------------------------------
# Item 7: ego speed when the cadence drops out
# --------------------------------------------------------------------------

def _motion_with_gap(gap_from, gap_to, seconds=22):
    m = motion(seconds)
    t = m["t"]
    quiet = (t >= gap_from) & (t < gap_to)
    m["dy"] = np.where(quiet, 0.0, m["dy"])
    m["dx"] = np.zeros(len(t))
    return m


def test_last_cadence_speed_is_held_for_the_cadence_window_then_unknown():
    frames = approach_frames(cls="pole", d0=500, seconds=30, extra=lambda g, t: _poles_for_speed(g, t, spacing=3.0, d0=40.0))
    doc, _ = run(frames, mot=_motion_with_gap(12.0, 30.0, seconds=30))
    by_t = {round(f["t"], 1): f["ego"] for f in doc["frames"]}
    assert by_t[11.0]["cadenceHz"] is not None and by_t[11.0]["scaleSource"] == "gait"
    gone = [t for t in sorted(by_t) if by_t[t]["cadenceHz"] is None and t > 12]
    assert gone, "the cadence should drop out in the gap"
    t0 = gone[0]
    last = max(t for t in by_t if t < t0 and by_t[t]["cadenceHz"] is not None)
    expected = by_t[last]["speedMps"]                          # the last cadence-based speed (the estimator fades before it quits)
    assert expected is not None
    window = CONFIG["ego"]["cadenceWindowSeconds"]
    for t in gone:
        if t - last <= window - 0.3:
            assert by_t[t]["speedMps"] == pytest.approx(expected, rel=0.02), (t, by_t[t])      # held, not the witness guess
        elif t - last >= window + 0.3:
            assert by_t[t]["speedMps"] is None, (t, by_t[t])
    assert any(t - last >= window + 0.3 for t in gone) and any(t - last <= window - 0.3 for t in gone)


# --------------------------------------------------------------------------
# Item 1/2: sideways velocity, collision course, motion state
# --------------------------------------------------------------------------

def test_sideways_velocity_of_a_static_object_is_zero_while_we_turn_and_of_a_mover_is_its_own():
    hist = []
    for i in range(10):
        t = i / 6
        heading = 5.0 * t                                     # we turn right at 5 deg/s
        d = 8.0 - 1.4 * t
        lat = 3.0 - math.radians(heading) * d                 # a static object drifts left in the picture while we turn
        hist.append((t, lat, d, heading))
    raw = np.polyfit([h[0] for h in hist], [h[1] for h in hist], 1)[0]
    assert abs(raw) > 0.3                                         # (without the correction the turn alone moves it)
    assert abs(col._lateral_velocity(hist, 0.75)) < 0.3          # (the first-order turn correction leaves ~1.4 sin(turn) m/s)
    mover = [(t, lat + 1.2 * t, d, h) for t, lat, d, h in hist]
    assert col._lateral_velocity(mover, 0.75) == pytest.approx(1.2, abs=0.3)
    assert col._lateral_velocity(hist[:3], 0.75) is None                                   # too short
    assert col._lateral_velocity([(t, lat, d, None) for t, lat, d, _ in hist], 0.75) is None   # no heading


def test_a_sideways_velocity_inside_the_noise_is_not_believed():
    it = _rated("person", "moving", 8, 1.0, moving=True, closing=2.0, lat_vel=1.5)
    assert col._sideways_mps(it, ROLES) == 0.0
    it = _rated("person", "moving", 8, 1.0, moving=True, closing=2.0, lat_vel=-5.0)
    assert col._sideways_mps(it, ROLES) == -5.0


def test_a_vehicle_crossing_the_lane_ahead_is_not_on_a_collision_course():
    """Review 4, 39.0 s: "vehicle is passing over the crosswalk in a non-collision direction": it is in front of us NOW,
    it will have left the lane when we get there. Same vehicle with no sideways speed (coming at us): danger."""
    crossing = _rated("vehicle", "moving", 6, 0.4, moving=True, approaching=True, closing=1.5, lat_vel=6.0)
    assert crossing.role == "none" and not crossing.collision
    coming = _rated("vehicle", "moving", 6, 0.4, moving=True, approaching=True, closing=3.0, lat_vel=0.2)
    assert coming.role == "danger" and coming.collision and coming.urgency == "danger"
    assert _rated("vehicle", "moving", 2.5, 0.4, moving=True, approaching=True, closing=3.0).urgency == "final"


def test_collision_course_needs_closing_a_near_meeting_and_a_lane_position_at_the_meeting():
    base = dict(moving=True, approaching=True, lat_vel=None)
    assert _rated("person", "moving", 8, 0.8, closing=1.0, **base).collision                    # in the beep zone (0.9 m), closing
    assert not _rated("person", "moving", 8, 1.0, closing=1.0, **base).collision                  # (v26.1.13: 1.5 -> 0.9 m)
    assert not _rated("person", "moving", 8, 0.8, closing=0.1, **base).collision                  # keeps its distance
    assert not _rated("person", "moving", 8, 0.8, closing=None, **base).collision                # unknown
    # a person 2.8 m to the side walking straight at us along their own line is not on our course; v26.1.13: outside the
    # people zone (2.75 m) it is silent, not even a warning
    side = _rated("person", "moving", 8, 2.8, closing=2.8, **base)
    assert side.role == "none" and not side.collision
    # a meeting more than courseMaxSeconds away is not extrapolated
    assert not _rated("person", "moving", 14, 0.5, closing=0.7, **base).collision


def test_a_person_walking_away_inside_the_lane_is_a_danger_without_beeps_beside_it_nothing():
    inside = _rated("person", "moving", 8, 0.4, moving=True, receding=True, closing=0.3)
    assert inside.role == "danger" and not inside.collision
    # v26.1.13: a person walking away is spoken (not beeped) anywhere in the people zone, "good to know someone is there"
    beside = _rated("person", "moving", 8, 1.5, moving=True, receding=True, closing=0.3)
    assert beside.role == "danger" and not beside.collision
    assert _rated("person", "moving", 8, 3.2, moving=True, receding=True, closing=0.3).role == "none"


def test_a_static_person_beside_the_path_keeps_the_lane_rule():
    p = _rated("person", "moving", 8, 2.5, moving=False)
    assert p.role == "danger" and not p.collision
    assert _rated("person", "moving", 8, 0.3, moving=False).collision


def test_an_unmeasured_vehicle_waits_while_motion_can_be_measured():
    """Review 4, 39.0 s: a moving car re-detected as fragments has no closing speed for ~0.75 s and was a "static danger"."""
    wait = _rated("vehicle", "moving", 6, 0.1, moving=None, lane_hit=True, ego_known=True)
    assert wait.role != "danger" and not wait.collision
    cannot = _rated("vehicle", "moving", 6, 0.1, moving=None, lane_hit=True, ego_known=False)
    assert cannot.role == "danger" and cannot.collision                  # no ego speed: as before
    parked = _rated("vehicle", "moving", 6, 0.1, moving=False, lane_hit=True, ego_known=True)
    assert parked.role == "danger" and parked.collision                  # a parked car IN the lane stays a static danger


def test_vehicles_are_never_spoken_as_context():
    assert "vehicle" not in CONFIG["contextSpeak"] and "parked car" not in CONFIG["contextSpeak"]
    p = _policy()
    tr = _tracks(1)
    v = _item(1, "context", 6, "vehicle", group="moving", clock=11)
    assert p.step(0.0, [v], tr) is None and p.step(5.0, [v], tr) is None


# --------------------------------------------------------------------------
# Item 1: phrases
# --------------------------------------------------------------------------

def _mover(i, label, steps, clock, state, cls=None):
    it = _item(i, "danger", steps, label, group="moving", clock=clock)
    it.people = label in ("person", "cyclist")
    it.fast = label in ("cyclist", "vehicle")
    it.class_name = cls or ("rider" if label == "cyclist" else label)
    it.moving, it.collision, it.receding = {"standing": (False, False, False), "approach": (True, True, False),
                                            "receding": (True, False, True), "unknown": (None, False, False)}[state]
    it.approaching = state == "approach"
    return it


@pytest.mark.parametrize("label,state,expected", [
    ("person", "standing", "person standing at 12:15 in 9"),
    ("cyclist", "standing", "cyclist stopped at 12:15 in 9"),
    ("person", "approach", "person approaching at 12:15 in 9"),
    ("cyclist", "approach", "cyclist approaching at 12:15"),
    ("person", "receding", "person moving away at 12:15 in 9"),
    ("person", "unknown", "person at 12:15 in 9"),
])
def test_person_and_rider_phrases_carry_their_motion_state(label, state, expected):
    it = _mover(1, label, 9, 12, state)
    it.clock_q, it.clock_text = 1, "12:15"
    e = col.SpeechPolicy(CONFIG)
    e.summary = False
    assert e.step(0.0, [it], _tracks(1))["text"] == expected


def test_several_people_of_one_state_are_merged_and_states_are_not_mixed():
    p = col.SpeechPolicy(CONFIG)
    a, b = _mover(1, "person", 7, 1, "standing"), _mover(2, "person", 9, 2, "standing")
    assert p.step(0.0, [a, b], _tracks(1, 2))["text"] == "person standing at 1 and 2 in 7"
    q = col.SpeechPolicy(CONFIG)
    c, d = _mover(1, "person", 7, 1, "standing"), _mover(2, "person", 9, 2, "approach")
    text = q.step(0.0, [c, d], _tracks(1, 2))["text"]
    assert "person standing at 1 in 7" in text and "person approaching at 2" in text and text.count("person") == 2


def test_the_final_call_of_an_approaching_mover_has_no_distance():
    it = _mover(1, "cyclist", 2.0, 12, "approach")
    it.urgency = "final"
    p = col.SpeechPolicy(CONFIG)
    p.summary = False
    e = p.step(0.0, [it], _tracks(1))
    assert e["role"] == "final" and e["text"] == "cyclist approaching at 12"


# --------------------------------------------------------------------------
# Item 4: one curb per crossing
# --------------------------------------------------------------------------

def test_a_curb_is_announced_once_per_crossing_the_far_side_included():
    over = CONFIG["speech"]["featureLabelOverrides"]
    assert over["curb"]["gapSeconds"] == 20 and over["curb"]["newCrossingSteps"] > over["crosswalk"]["newCrossingSteps"] - 1
    p = col.SpeechPolicy(CONFIG)
    p.summary = False
    tr = _tracks(1, 2, 3, 4)
    assert p.step(0.0, [_item(1, "feature", 5, "curb", group="feature")], tr)["text"] == "curb at 12 in 5"
    p.travel_steps = 14.0                                       # 14 steps and 6 s later: the far curb of the same crossing
    assert p.step(6.0, [_item(2, "feature", 4, "curb", group="feature")], tr) is None
    p.travel_steps = 60.0                                       # a minute on: another street
    assert p.step(45.0, [_item(3, "feature", 6, "curb", group="feature")], tr)["text"] == "curb at 12 in 6"


# --------------------------------------------------------------------------
# Item 5: surface evidence
# --------------------------------------------------------------------------

def test_a_curb_that_only_flickers_under_the_feet_is_no_crossing_evidence():
    side, road = base_grid("flat sidewalk"), base_grid("flat road")
    flick = _curb_band(side)
    # one frame of curb at the change: the track never held the feature role for confirmFrames frames
    spans = [(10, side), (10.1, flick), (35, road)]
    doc, ev = run(_surface_frames(spans))
    assert speech(ev, "surface") == []


def test_crossing_evidence_must_belong_to_the_change_not_be_far_before_or_after_it():
    side, road = base_grid("flat sidewalk"), base_grid("flat road")
    # a curb crossed at 10 s, the model reads road only from 20 s on: that is a relabel, not the crossing
    spans = [(10, side), (10.6, _curb_band(side)), (20, side), (45, road)]
    doc, ev = run(_surface_frames(spans))
    assert speech(ev, "surface") == []
    # evidence long after the road run began did not cause it either (159.8 s of review 4: a crosswalk at the left edge)
    spans = [(10, side), (22, road), (22.6, _curb_band(road)), (50, road)]
    doc, ev = run(_surface_frames(spans))
    assert speech(ev, "surface") == []
