"""v26.2.13 (W1): walls being followed stay quiet (distance ratio + known-wall memory), "moved away" / "started walking away", soft beeps for a
person passing close (plan ``docs/plans/v26.2.13.md``). The review-10 targets are in ``test_collision_v26213_fixture.py``."""
from __future__ import annotations

import copy

import collision as col
from tests.test_collision import _item, _policy, _tracks

CONFIG = col.load_config()          # conftest: the v26.2.13 defaults for this module (predictive on)
FOLLOW = CONFIG["beeps"]["follow"] | {"enabled": True}


def _pol(config=None):
    p = _policy(config or CONFIG)
    p.ego_u = None                  # no prediction: the spoken numbers are today's
    return p


def _wall(tid, steps, dist, t=None, clock_q=0, role="danger", cls="building"):
    it = _item(tid, role, steps, cls, dist=dist)
    it.class_name, it.family, it.clock_q, it.lateral_m = cls, "building", clock_q, 0.4
    it.collision = role == "danger"
    it.clock_text = col.clock_text(clock_q)
    return it


# -- 1. walls being followed: the distance does not close at the walking speed ------------------------------------------------------------------

def _run(wf, dists, dt=0.2, speed=1.3, tid=1, t0=10.0, **kw):
    out = []
    for k, d in enumerate(dists):
        it = _wall(tid, steps=d / 0.74, dist=d, **kw)
        wf.advance(dt, speed)
        wf.observe(t0 + k * dt, [it])
        out.append(it)
    return out


def _wf(known=True):
    """A follower that has seen track 1 for a long time (``besideS``): only the distance ratio decides."""
    wf = col._WallFollow(FOLLOW)
    if known:
        wf.first[1] = 0.0
    return wf


def test_a_wall_whose_distance_stays_while_we_walk_is_followed_and_one_that_closes_at_the_walking_speed_is_not():
    wf = _wf()
    its = _run(wf, [3.0] * 12)
    assert its[-1].followed and not its[0].followed            # the first frames: no history to decide on (undecided = not followed)
    wf = _wf()
    its = _run(wf, [6.0 - 0.26 * k for k in range(12)])        # 1.3 m/s closing = the walking speed
    assert not any(i.followed for i in its)
    wf = _wf()
    its = _run(wf, [3.0 - 0.1 * k for k in range(12)])         # 0.5 m/s of 1.3 m/s: ratio 0.38 < 0.4, still followed
    assert its[-1].followed
    wf = _wf()
    its = _run(wf, [4.0 - 0.15 * k for k in range(12)])        # 0.75 m/s of 1.3: ratio 0.58, closing again
    assert not its[-1].followed


def test_a_followed_wall_needs_walking_and_is_never_quiet_within_a_step():
    wf = _wf()
    its = _run(wf, [3.0] * 12, speed=0.0)                      # we stand: nothing was walked, nothing is decided
    assert not any(i.followed for i in its)
    wf = _wf()
    its = _run(wf, [0.7] * 12)                                 # <= nearSteps (1): the beeps stay
    assert not any(i.followed for i in its)


def test_a_jump_of_the_distance_away_restarts_the_history_and_a_gap_too():
    wf = _wf()
    its = _run(wf, [1.8] * 8 + [7.0] * 3)                      # the nearest point moved to another face 5 m on: new, undecided
    assert not its[-1].followed
    wf = _wf()
    _run(wf, [3.0] * 8)
    it = _wall(1, 4.0, 3.0)
    wf.advance(1.5, 1.3)
    wf.observe(13.0, [it])                                     # 1.4 s without a sample: restarts
    assert not it.followed


def test_a_wall_that_just_came_up_is_news_unless_a_wall_was_due_a_moment_ago():
    wf = col._WallFollow(FOLLOW)
    its = _run(wf, [3.0] * 12)                                 # a track 2.2 s old (besideS 5): no recent wall event, so not quiet
    assert not its[-1].followed
    wf = col._WallFollow(FOLLOW)
    wf.candidate(9.0, _wall(1, 4.0, 3.0))                      # a wall beep 1 s before (recentS 4.5)
    assert _run(wf, [3.0] * 12)[-1].followed
    wf = col._WallFollow(FOLLOW)
    its = _run(wf, [3.0] * 40)                                 # alongside for 8 s: known
    assert its[-1].followed


def test_a_followed_wall_starts_no_beep_episode_but_a_running_one_goes_on():
    wf = col._WallFollow(FOLLOW)
    it = _wall(1, 4.0, 3.0)
    it.followed = True
    assert wf.quiet(20.0, it, 1.5)
    wf.beeped(19.0, it)                                        # a real beep 1 s ago: the episode runs
    assert not wf.quiet(20.0, it, 1.5)
    assert wf.quiet(21.0, it, 1.5)                             # it ended 2 s ago: a new one would start, quiet
    it.followed = False
    assert not wf.quiet(21.0, it, 1.5)


def test_a_wall_phrase_is_not_said_for_a_followed_wall_but_the_slot_is_spent():
    p = _pol()
    tr = _tracks(1, 2)
    w = _wall(1, 6.0, 4.4)
    w.followed = True
    p2 = _item(2, "danger", 8, "person", group="moving", clock=12)
    assert p.step(10.0, [w], tr) is None and p.quiet_t == 10.0
    assert p.last_danger_t == 10.0                              # the slot is consumed as the spoken phrase would have: the next danger waits
    assert p.step(10.4, [p2], tr) is None
    assert p.step(11.1, [p2], tr)["text"] == "person at 12 in 8"
    assert p.step(11.2, [w], tr) is None                        # (once per track: the next frames do not consume again)
    w.followed = False
    q = _pol()
    assert q.step(10.0, [_wall(1, 6.0, 4.4)], _tracks(1))["text"] == "building at 12 in 6"


# -- 2. a wall phrase for a known place ---------------------------------------------------------------------------------------------------------

def test_a_wall_at_the_same_relative_place_as_a_recent_phrase_is_known_and_a_new_place_or_an_old_phrase_is_not():
    p = _pol()
    tr = _tracks(1, 2, 3)
    a = _wall(1, 6.0, 4.4, clock_q=1)
    a.wx, a.wy = 0.0, 40.0
    assert p.step(10.0, [a], tr)["text"] == "building at 12:15 in 6"
    b = _wall(2, 6.0, 4.4, clock_q=1)                           # 10 s later 11 m on: the same relative place (a wall walked along)
    b.wx, b.wy = -1.0, 52.0
    assert p.step(20.0, [b], tr) is None
    c = _wall(3, 9.0, 6.7, clock_q=1)                           # 4 steps further ahead: another place
    c.wx, c.wy = -1.0, 55.0
    assert p.step(25.0, [c], tr)["text"] == "building at 12:15 in 9"
    # 13 s later at the same relative place (relativeS 12): said again
    q = _pol()
    q.step(10.0, [a], _tracks(1))
    d = _wall(2, 6.0, 4.4, clock_q=1)
    d.wx, d.wy = 0.0, 60.0
    assert q.step(23.0, [d], _tracks(2))["text"] == "building at 12:15 in 6"
    # the same world point (within 2 m) is known for 30 s whatever the relative place
    r = _pol()
    r.step(10.0, [a], _tracks(1))
    e = _wall(2, 11.0, 8.1, clock_q=0)
    e.wx, e.wy = 0.5, 40.5
    assert r.step(30.0, [e], _tracks(2)) is None
    assert _pol().known_on and not _pol(_off(("speech", "knownWall", "enabled"), False)).known_on


def _off(path, v):
    c = copy.deepcopy(CONFIG)
    d = c
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = v
    return c


def test_a_wall_beep_run_is_remembered_by_its_start_only():
    p = _pol()
    w = _wall(1, 6.0, 4.4, clock_q=1)
    p.note_wall(10.0, w)
    assert len(p.known_walls) == 1 and p.known_walls[0]["fam"] == "building"
    p.note_wall(45.0, w)                                        # entries older than windowS leave
    assert len(p.known_walls) == 1
    pole = _wall(2, 4.0, 3.0, cls="pole")
    p.note_wall(46.0, pole)                                     # not a wall family
    assert len(p.known_walls) == 1


# -- 3. "moved away" ----------------------------------------------------------------------------------------------------------------------------

def _mover(tid, lat, t, dist=3.0, moving=False, role="danger", collision=True, closing=0.5, clock_q=1, receding=False, hist=()):
    it = _item(tid, role, 4, "person", group="moving", clock=12, dist=dist)
    it.class_name, it.people, it.moving, it.collision, it.lateral_m, it.closing = "person", True, moving, collision, lat, closing
    it.clock_q, it.clock_text, it.receding = clock_q, col.clock_text(clock_q), receding
    it.role = role
    return it


def _walk_away(p, tr, lats, t0=10.0, dt=0.17, **kw):
    """Feed lateral positions of one mover; returns the phrases."""
    said = []
    for k, lat in enumerate(lats):
        t = t0 + k * dt
        collision = abs(lat) <= 0.6
        it = _mover(1, lat, t, collision=collision, role="danger" if collision else "none", **kw)
        tr[1].lhist.append((t, lat, it.distance_m, 0.0, 0.0))
        p.observe_movers(t, [it], tr)
        s = p.away_speech(t, [it])
        if s:
            said.append((round(t, 2), s["text"]))
    return said


def test_a_person_who_stood_in_the_lane_and_walks_away_sideways_is_told_once():
    p = _pol()
    tr = _tracks(1)
    # still (moving False) in the lane for 1.5 s, then out of it by 0.4 m/s
    lats = [0.3] * 10 + [0.3 + 0.07 * k for k in range(1, 14)]
    said = _walk_away(p, tr, lats)
    assert len(said) == 1 and said[0][1] == "person at 12:15 started walking away"
    assert 12.7 <= said[0][0] <= 13.1                          # when |lateral| passes lane half + 0.2 m (0.8)
    # once per track per cooldownS: it does not repeat
    assert _walk_away(p, tr, [1.2] * 5, t0=14.0) == []


def test_a_mover_that_swerves_out_of_the_lane_is_told_moved_away_after_confirmMovingS_and_not_when_it_comes_back():
    p = _pol()
    tr = _tracks(1)
    said = _walk_away(p, tr, [0.3] * 8 + [0.5, 0.8, 1.1, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2], moving=True, clock_q=2)
    assert len(said) == 1 and said[0][1] == "person at 12:30 moved away"
    q = _pol()
    tr = _tracks(1)
    assert _walk_away(q, tr, [0.3] * 8 + [0.5, 0.8, 1.1, 0.9, 0.5, 0.3, 0.3], moving=True) == []       # back in the lane within the confirmation
    # a mover that closes on us faster than maxClosingMps passes by, it does not move away
    r = _pol()
    tr = _tracks(1)
    assert _walk_away(r, tr, [0.3] * 8 + [0.5, 0.8, 1.1, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2], moving=True, closing=2.5) == []


def test_moved_away_needs_a_recent_collision_and_the_gap_of_a_danger_phrase():
    p = _pol()
    tr = _tracks(1)
    # never a collision item: nothing is told
    said = []
    for k in range(14):
        t = 10.0 + 0.17 * k
        it = _mover(1, 1.5 + 0.1 * k, t, collision=False, role="none")
        tr[1].lhist.append((t, it.lateral_m, 3.0, 0.0, 0.0))
        p.observe_movers(t, [it], tr)
        said.append(p.away_speech(t, [it]))
    assert not any(said)
    # a danger phrase 0.5 s ago holds it back until priorityMinGapSeconds have passed
    q = _pol()
    tr = _tracks(1)
    q._event(11.5, "danger", "pole at 12 in 8", None, "danger")
    out = _walk_away(q, tr, [0.3] * 8 + [0.3 + 0.07 * k for k in range(1, 14)])
    assert out and out[0][0] >= 12.5 - 1e-6
    # off
    o = _pol(_off(("speech", "away", "enabled"), False))
    assert _walk_away(o, _tracks(1), [0.3] * 10 + [0.3 + 0.07 * k for k in range(1, 14)]) == []


# -- 4. soft beeps for a person passing close ---------------------------------------------------------------------------------------------------

def test_a_person_passing_close_and_closing_in_gets_the_soft_sound_and_static_items_do_not():
    cfg = CONFIG["beeps"]["passing"]
    p = _mover(1, -1.1, 0.0, dist=2.0, moving=True, role="none", collision=False, closing=2.0)
    p.steps = 2.7
    assert col._passing_close(p, cfg)
    assert not col._passing_close(_mover(1, -1.8, 0.0, moving=True, role="none", collision=False, closing=2.0), cfg)        # > 1.5 m aside
    far = _mover(1, -1.1, 0.0, moving=True, role="none", collision=False, closing=2.0)
    far.steps = 6.0
    assert not col._passing_close(far, cfg)                                                                             # > 4 steps
    slow = _mover(1, -1.1, 0.0, moving=True, role="none", collision=False, closing=0.5)
    slow.steps = 2.0
    assert not col._passing_close(slow, cfg)                                                                            # not closing
    gone = _mover(1, -1.1, 0.0, moving=True, role="none", collision=False, closing=-1.0, receding=True)
    gone.steps = 2.0
    assert not col._passing_close(gone, cfg)                                                                            # passed
    stat = _wall(1, 2.0, 1.5, cls="sign")
    stat.group, stat.moving, stat.closing, stat.collision = "static", False, 2.0, False
    assert not col._passing_close(stat, cfg)                                                                            # a static item outside the lane
    still = _mover(1, -1.1, 0.0, moving=False, role="none", collision=False, closing=2.0)
    still.steps = 2.0
    assert not col._passing_close(still, cfg)                                                                           # not a mover
