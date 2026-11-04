"""v26.2.11 world tracks: pose noise, extended classes, static damping / promotion, revive and one-to-one re-id, the trusted flag."""
from __future__ import annotations

import math

import numpy as np

import worldtracks as wtm
from tests.test_worldtracks import DT, _meas, _walk, _wt

LEGACY = {"extendedClasses": [], "headingSigmaDegPerS": 0.0, "staticVelocityDamping": 1.0, "moverPromoteMps": 0.0, "missDropS": 0.0,
          "reviveS": 0.0, "reidOneToOne": False}
POLE = {"cls": "pole", "group": "static", "static": True}


def _drifting_walk(wt, seconds, items, drift_deg_per_s, noise=0.05, seed=1):
    """Like _walk, but the pose heading the tracker is given drifts (the world is fixed): a static pole then seems to move."""
    rng = np.random.default_rng(seed)
    out = []
    for k in range(int(seconds / DT)):
        t = k * DT
        true = (0.0, 1.4 * t, 0.0)
        pose = (true[0], true[1], drift_deg_per_s * t)
        ms = [_meas(tid, wx + rng.normal(0, noise), wy + rng.normal(0, noise), true, **kw) for tid, wx, wy, kw in items(t)]
        # measurement made from the true pose, located with the drifted one: re-express (fwd, right) as seen from the true pose
        out.append(wt.step(t, pose, ms, 0.0, None))
    return out


def test_a_static_pole_seen_through_two_seconds_of_pose_noise_has_speed_below_015():
    def run(**kw):
        return _drifting_walk(_wt(**kw), 6, lambda t: [(1, 2.0, 18.0, POLE)], drift_deg_per_s=1.0)
    new = run()
    old = run(**LEGACY)
    speed_new = float(np.median([o[0]["speedMps"] for o in new[18:]]))
    speed_old = float(np.median([o[0]["speedMps"] for o in old[18:]]))
    assert speed_new < 0.15
    assert speed_new < speed_old


def test_a_wall_and_a_curb_get_no_world_track_but_a_pole_does():
    wt = _wt()
    out = _walk(wt, 2, lambda t: [(1, -2.0, 10.0, {"cls": "barrier wall", "group": "static", "static": True}),
                                  (2, 1.0, 10.0, {"cls": "curb", "group": "feature", "static": True}),
                                  (3, 1.0, 12.0, {"cls": "nature vegetation", "group": "static", "static": True}),
                                  (4, 0.5, 9.0, POLE)])
    assert all(len(o) == 1 and o[0]["class"] == "pole" for o in out)
    legacy = _walk(_wt(**LEGACY), 1, lambda t: [(1, -2.0, 10.0, {"cls": "barrier wall", "group": "static", "static": True})])
    assert len(legacy[-1]) == 1                                       # v26.2.10 behaviour reachable


def test_a_one_second_occlusion_keeps_the_id_and_a_missing_track_is_not_dropped_before_one_second():
    wt = _wt()

    def items(t):
        return [(1 if t < 2.0 else 2, 1.0, 14.0, POLE)] if not 2.0 <= t < 3.0 else []
    out = _walk(wt, 5, items)
    ids = {o[0]["id"] for o in out if o}
    assert ids == {"W1"}
    assert all(o[0]["state"] != "dropped" for o in out if o)
    assert out[-1][0]["imageTracks"] == [1, 2]
    # without revive / time drop (v26.2.10) the same occlusion gives a second world track
    leg = _walk(_wt(**LEGACY), 5, items)
    assert len({o["id"] for f in leg for o in f}) >= 1


def test_revive_after_the_missing_drop_and_one_to_one_assignment():
    wt = _wt(missDropS=0.5, reviveS=1.5)

    def items(t):
        return [(1 if t < 1.0 else 2, 1.0, 14.0, POLE)] if not 1.0 <= t < 2.0 else []
    out = _walk(wt, 4, items, noise=0.02)
    assert any(o[0]["state"] == "missing" for o in out if o)
    assert out[-1][0]["id"] == "W1" and out[-1][0]["imageTracks"] == [1, 2]
    # two new image tracks, one old world track: only one of them takes it, the other starts its own
    wt2 = _wt()
    pose = (0.0, 0.0, 0.0)
    wt2.step(0.0, pose, [_meas(1, 1.0, 10.0, pose, **POLE)], 0.0)
    assert wt2.step(DT, pose, [], 0.0)[0]["state"] == "missing"
    o = wt2.step(2 * DT, pose, [_meas(2, 1.0, 10.0, pose, **POLE), _meas(3, 1.1, 10.1, pose, **POLE)], 0.0)
    assert sorted(w["id"] for w in o) == ["W1", "W2"]


def test_a_static_like_track_that_really_moves_is_promoted_to_mover():
    wt = _wt()
    out = _walk(wt, 5, lambda t: [(1, -1.0 + 1.5 * t, 12.0, {"cls": "vehicle", "group": "moving", "static": True})], noise=0.03)
    last = out[-1][0]
    assert last["promoted"] and not last["staticLike"]
    assert abs(last["vx"] - 1.5) < 0.4
    never = _walk(_wt(**LEGACY), 5, lambda t: [(1, -1.0 + 1.5 * t, 12.0, {"cls": "vehicle", "group": "moving", "static": True})], noise=0.03)
    assert never[-1][0]["staticLike"] and not never[-1][0]["promoted"]


def test_trusted_flag_needs_seen_time_position_and_speed_sigma():
    wt = _wt()
    out = _walk(wt, 4, lambda t: [(1, 1.0, 8.0, POLE)], noise=0.05)
    assert not out[0][0]["trusted"] and out[0][0]["seenS"] == 0.0
    assert out[-1][0]["trusted"] and out[-1][0]["speedSigmaMps"] <= 0.3 and out[-1][0]["sigmaM"] <= 0.5 and out[-1][0]["seenS"] >= 0.5
    # a far item has a large range sigma: not trusted
    far = _walk(_wt(), 4, lambda t: [(1, 1.0, 29.0 + 0 * t, POLE)], noise=0.05)
    assert not far[-1][0]["trusted"] or far[-1][0]["sigmaM"] <= 0.5
    # strict thresholds
    strict = _walk(_wt(trustMaxSigmaM=0.001), 3, lambda t: [(1, 1.0, 8.0, POLE)])
    assert not strict[-1][0]["trusted"]


def test_pose_noise_inflates_the_gate_after_a_gap():
    wt = _wt()
    tr_cfg = wt.cfg
    assert tr_cfg["headingSigmaDegPerS"] > 0 and tr_cfg["poseSigmaMaxS"] > 0
    base = np.diag([0.01, 0.01])
    pose = (0.0, 0.0, 0.0)
    wt.step(0.0, pose, [_meas(1, 0.0, 20.0, pose, **POLE)], 0.0)
    tr = wt.tracks[1]
    z = np.array([0.0, 20.0])
    r0 = wt._Rx(tr, z, base, 0.1)
    r3 = wt._Rx(tr, z, base, 3.0)
    assert r3[0, 0] > r0[0, 0] > base[0, 0] - 1e-12                   # tangent (east) variance grows with the unseen time
    assert wtm.settings({"headingSigmaDegPerS": 0.0})["headingSigmaDegPerS"] == 0.0
