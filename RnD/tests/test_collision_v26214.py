"""v26.2.14 (W1): movers by their own motion (``motion``: near-collision course, side they come from, cutting in front, moving away ahead, parked
vehicles), the whole component of every hazards item (``output.fullAllItems``). The review-11 targets are in ``test_collision_v26214_fixture.py``
(plan ``docs/plans/v26.2.14.md``)."""
from __future__ import annotations

import copy
import math

import numpy as np

import collision as col
from tests.test_collision import _item, _policy, _tracks

CONFIG = col.load_config()          # conftest: the v26.2.14 defaults for this module
MO = CONFIG["motion"]
U = 1.3                             # our walking speed


def _mover(cls="person", fast=False):
    it = _item(1, "none", 10, cls, group="moving", approaching=False)
    it.class_name, it.people, it.fast, it.moving, it.ego_known, it.ego_settled = cls, cls == "person", fast, None, True, True
    it.settled = True
    return it


def _feed(path, cls="person", dt=1 / 6, n=8, u=U, fast=False, cfg=None, jitter=None):
    """Walk ``n`` frames at ``u`` m/s along heading 0 while a mover follows ``path(t) -> (world x, world y)``; returns (_OwnMotion, last item, ego y)."""
    om = col._OwnMotion(cfg or MO)
    it = None
    for k in range(n):
        t = 10.0 + k * dt
        om.advance(t, dt, u, 0.0)
        wx, wy = path(t - 10.0)
        it = _mover(cls, fast)
        it.distance_m = wy - om.y + (0.0 if jitter is None else jitter[k % len(jitter)])
        it.lateral_m = wx - om.x
        it.steps = it.distance_m / 0.74
        om.observe(it, t)
    return om, it, 10.0 + (n - 1) * dt


# -- 1. the estimate ---------------------------------------------------------------------------------------------------------------------------

def test_the_own_velocity_of_a_walker_is_estimated_in_our_frame():
    # a person 9 m ahead, 1 m to the left, walking towards us at 1.2 m/s (world y decreasing) while we walk 1.3 m/s
    om, it, t = _feed(lambda s: (-1.0, 12.0 - 1.2 * s))
    vf, vr, sg = om.estimate(1, t)
    assert abs(vf + 1.2) < 0.05 and abs(vr) < 0.05 and sg <= 0.12 + 1e-9
    # a person walking the same way as us: positive forward velocity, the distance does not close
    om, it, t = _feed(lambda s: (0.0, 5.0 + 1.0 * s))
    assert abs(om.estimate(1, t)[0] - 1.0) < 0.05


def test_no_estimate_before_enough_frames_and_an_outlier_does_not_count():
    om, it, t = _feed(lambda s: (0.0, 8.0 - 1.0 * s), n=3)
    assert om.estimate(1, t) is None
    om = col._OwnMotion(MO)
    for k in range(8):
        tt = 10.0 + k / 6
        om.advance(tt, 1 / 6, U, 0.0)
        it = _mover()
        it.distance_m = 8.0 - 1.0 * (k / 6) - om.y + (3.0 if k == 4 else 0.0)        # one depth glitch of 3 m
        it.lateral_m = -1.0
        om.observe(it, tt)
    assert abs(om.estimate(1, tt)[0] + 1.0) < 0.35


def test_a_fragment_that_appears_where_a_lost_track_was_continues_its_history():
    om = col._OwnMotion(MO)
    for k in range(10):
        t = 10.0 + k / 6
        om.advance(t, 1 / 6, U, 0.0)
        it = _mover()
        it.track_id = 1 if k < 5 else 2
        it.distance_m, it.lateral_m = 9.0 - 1.0 * (k / 6) - om.y, -1.0
        om.observe(it, t)
    assert om.estimate(2, t) is not None and abs(om.estimate(2, t)[0] + 1.0) < 0.1


# -- 2. the motion words -----------------------------------------------------------------------------------------------------------------------

def test_a_person_walking_at_us_is_approaching_and_a_close_pass_is_a_collision_danger():
    om, it, t = _feed(lambda s: (-1.0, 9.0 - 1.0 * s))        # passes 1.0 m to the left
    om.classify(it, t, U)
    assert it.own_ok and it.moving is True and it.approaching and not it.receding
    assert it.near_pass                                         # within nearPassM (1.3) m, t_pass = d / (u + 1.0) <= 4 s
    om, it, t = _feed(lambda s: (-2.5, 9.0 - 1.0 * s))        # passes 2.5 m to the left
    om.classify(it, t, U)
    assert it.approaching and not it.near_pass
    om, it, t = _feed(lambda s: (-1.0, 20.0 - 1.0 * s), n=8)  # 20 m away: it passes in 9 s
    om.classify(it, t, U)
    assert it.approaching and not it.near_pass


def test_a_person_standing_or_walking_away_is_not_approaching_whatever_the_closing_rate():
    om, it, t = _feed(lambda s: (0.0, 6.0))                     # stands: the gap closes at our own speed
    it.moving, it.approaching = True, True                       # (what the closing-rate states said)
    om.classify(it, t, U)
    assert it.own_ok and it.moving is False and not it.approaching
    om, it, t = _feed(lambda s: (0.0, 6.0 + 1.5 * s))           # walks away faster than us
    om.classify(it, t, U)
    assert it.receding and not it.approaching and not it.near_pass


def test_a_parked_vehicle_is_static_and_a_noisy_one_has_no_motion_words():
    om, it, t = _feed(lambda s: (-1.5, 8.0), cls="vehicle", fast=True)
    it.moving, it.approaching = True, True
    om.classify(it, t, U)
    assert it.moving is False and not it.approaching            # < minSpeedMps.vehicle (0.8): parked
    jit = [0.0, 2.5, -2.0, 3.0, -2.5, 1.5]
    om, it, t = _feed(lambda s: (-1.5, 8.0), cls="vehicle", fast=True, jitter=jit)
    it.moving, it.approaching = True, True
    om.classify(it, t, U)
    assert it.own[2] > MO["sigmaMaxMps"] and it.moving is None and not it.approaching       # the review-11 70.84 s car: unknown, not "approaching"


def test_a_vehicle_never_gets_its_motion_words_from_its_own_estimate_alone():
    om, it, t = _feed(lambda s: (-1.5, 15.0 - 4.0 * s), cls="vehicle", fast=True)
    assert it.moving is None
    om.classify(it, t, U)                                       # the closing-rate state said nothing: parked cars read 2-4 m/s towards us
    assert it.moving is None and not it.approaching
    it.moving, it.approaching = True, True                      # ... but it confirms one that said approaching
    om, it2, t = _feed(lambda s: (-1.5, 15.0 - 4.0 * s), cls="vehicle", fast=True)
    it2.moving, it2.approaching = True, True
    om.classify(it2, t, U)
    assert it2.moving is True and it2.approaching


def test_the_side_a_mover_comes_from_is_named_when_it_moves_across_towards_our_line():
    om, it, t = _feed(lambda s: (1.5 - 0.9 * s, 9.0 - 0.8 * s))          # 1.5 m to the right, moving left at 0.9 m/s
    om.classify(it, t, U)
    assert it.from_side == "right"
    om, it, t = _feed(lambda s: (-1.5 + 0.9 * s, 9.0 - 0.8 * s))
    om.classify(it, t, U)
    assert it.from_side == "left"
    om, it, t = _feed(lambda s: (-1.5 - 0.9 * s, 9.0 - 0.8 * s))         # moving away sideways: no side
    om.classify(it, t, U)
    assert it.from_side == ""


# -- 3. the phrases ----------------------------------------------------------------------------------------------------------------------------

def test_the_approach_phrase_carries_the_steps_and_the_side():
    p = _policy(CONFIG)
    p.ego_u = None
    it = _item(1, "danger", 5, "vehicle", group="moving", clock=12)
    it.own_ok, it.moving, it.approaching, it.fast, it.clock_q, it.clock_text = True, True, True, True, 14, "12:30"
    assert p._kind(it, "danger") == "approach"
    assert p._text("approach", it) == "vehicle approaching at 12:30 in 5"           # fast, but measured: the steps stay
    it.from_side = "right"
    assert p._text("approach", it) == "vehicle approaching from right at 12:30 in 5"
    assert p._entry("approach", [it]) == "vehicle approaching from right at 12:30 in 5"
    it.own_ok, it.from_side = False, ""                                                # no own estimate: the v26.2.13 words (a fast item: no steps)
    assert p._text("approach", it) == "vehicle approaching at 12:30"


def test_without_the_own_estimate_the_closing_rate_states_stay_as_they_were():
    p = _policy(CONFIG)
    it = _item(1, "danger", 5, "vehicle", group="moving")
    it.fast, it.moving, it.approaching, it.own_ok = True, True, False, False
    assert p._kind(it, "danger") == "approach"                                          # v26.2.13: a fast item in danger is "approaching"
    it.own_ok = True
    assert p._kind(it, "danger") == "danger"                                            # v26.2.14: its own motion says not approaching


def test_a_mover_passing_close_is_said_again_as_it_closes_and_beeps_by_steps():
    p = _policy(CONFIG)
    p.ego_u = None
    tr = _tracks(1)
    it = _item(1, "danger", 9, "person", group="moving")
    it.own_ok = it.near_pass = it.approaching = it.moving = True
    it.people, it.collision, it.lateral_m, it.clock_q, it.clock_text = True, True, -1.0, 10, "11:15"
    first = p.step(10.0, [it], tr)
    assert first["text"] == "person approaching at 11:15 in 9"
    it.steps = 8.0
    assert p.step(10.5, [it], tr) is None                                                # not 2 steps closer yet
    it.steps = 6.5
    assert p.step(10.8, [it], tr) is None                                                # (< againGapS since the last phrase)
    assert p.step(11.6, [it], tr)["text"] == "person approaching at 11:15 in 6"          # 3 steps closer, 1.6 s later
    it.steps, it.urgency = 2.9, "final"
    assert p.step(13.5, [it], tr)["text"] == "person approaching at 11:15 in 3"          # the final: not muted as "said before"
    plain = _item(2, "danger", 9, "person", group="moving")                              # the same without near_pass: said once
    plain.moving = plain.approaching = plain.collision = True
    plain.people = True
    tr2 = _tracks(2)
    p2 = _policy(CONFIG)
    p2.ego_u = None
    assert p2.step(10.0, [plain], tr2) is not None
    plain.steps = 4.0
    assert p2.step(12.5, [plain], tr2) is None


# -- 4. cutting in front / moving away ahead ---------------------------------------------------------------------------------------------------

def _walker(lat, vr, steps=2.7, vf=1.0, close=0.0):
    it = _item(7, "none", steps, "person", group="moving")
    it.people, it.moving, it.own_ok, it.settled = True, True, True, True
    it.lateral_m, it.own, it.own_closing = lat, (vf, vr, 0.1), close
    it.distance_m = steps * 0.74
    return it


def test_a_person_stepping_into_the_lane_ahead_is_said_to_cut_in_front_once():
    p = _policy(CONFIG)
    p.ego_u = None
    out = []
    for k, lat in enumerate([1.3, 1.2, 1.0, 0.8, 0.6, 0.5, 0.4]):
        out.append(p.motion_speech(20.0 + k / 6, [_walker(lat, -0.45)]))
    texts = [e["text"] for e in out if e]
    assert texts == ["person cutting in front"] and [e["role"] for e in out if e] == ["final"]
    assert p.motion_speech(25.0, [_walker(0.2, -0.45)]) is None                          # once per track per cooldownS
    q = _policy(CONFIG)
    assert all(q.motion_speech(20.0 + k / 6, [_walker(0.3, -0.45)]) is None for k in range(6))          # was never outside the lane
    q = _policy(CONFIG)
    assert all(q.motion_speech(20.0 + k / 6, [_walker(1.0 + 0.1 * k, 0.45)]) is None for k in range(6))     # moving away from the lane
    q = _policy(CONFIG)
    assert all(q.motion_speech(20.0 + k / 6, [_walker(1.2 - 0.1 * k, -0.45, steps=6.0)]) is None for k in range(6))     # too far: not within 4 steps


def test_a_person_walking_the_same_way_ahead_in_the_lane_is_said_to_move_away_once_it_has_been_stable():
    p = _policy(CONFIG)
    p.ego_u = None
    got = []
    for k in range(10):
        t = 30.0 + k / 6
        e = p.motion_speech(t, [_walker(0.1, 0.05, steps=4.1)])
        if e:
            got.append((round(t, 2), e["text"], e["role"]))
    assert got == [(31.0, "person moving away at 12 in 4", "danger")]                    # stableS 1.0 s, once
    q = _policy(CONFIG)
    assert all(q.motion_speech(30.0 + k / 6, [_walker(0.1, 0.5, steps=4.1)]) is None for k in range(10))        # still crossing sideways
    q = _policy(CONFIG)
    assert all(q.motion_speech(30.0 + k / 6, [_walker(0.1, 0.05, steps=4.1, close=0.8)]) is None for k in range(10))    # the gap closes
    q = _policy(CONFIG)
    assert all(q.motion_speech(30.0 + k / 6, [_walker(0.1, 0.05, steps=4.1, vf=0.1)]) is None for k in range(10))       # not walking away
    q = _policy(CONFIG)
    assert all(q.motion_speech(30.0 + k / 6, [_walker(1.5, 0.05, steps=4.1)]) is None for k in range(10))       # outside the lane


def test_the_motion_rules_are_off_with_the_switch():
    cfg = copy.deepcopy(CONFIG)
    cfg["motion"]["enabled"] = False
    p = _policy(cfg)
    assert p.motion_speech(1.0, [_walker(0.1, 0.05)]) is None and not p.motion_on


# -- 5. the whole component of every item ------------------------------------------------------------------------------------------------------

def test_every_item_with_a_shape_carries_its_whole_component_when_asked_to():
    fl = np.zeros((20, 20), dtype=np.uint8)
    fl[3:12, 4:10] = 7
    it = _item(1, "none", 10, "building")
    it.full_ref = (fl, (slice(3, 12), slice(4, 10)), 7)
    plain = col._hazard_json(it, 20, 20)
    assert "bboxFull" not in plain and "outlineFull" not in plain                       # v26.2.13: a no-role item had none
    full = col._hazard_json(it, 20, 20, full_all=True)
    assert full["bboxFull"] == [0.2, 0.15, 0.5, 0.6] and len(full["outlineFull"]) >= 4
    assert "outline" not in full                                                        # (its own outline stays for items with a role)
    nofull = _item(2, "none", 10, "building")                                           # a ghost / coasting item has no shape
    assert "bboxFull" not in col._hazard_json(nofull, 20, 20, full_all=True)
