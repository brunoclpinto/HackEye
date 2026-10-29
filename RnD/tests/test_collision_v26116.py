"""v26.1.16 (review 8, Chest-center-0004, run 180acf11eedb, fixture ``chest0004_review8``): sound kinds and profile, review-8 fixes.

A. Sounds: collision beeps by sector (left 9:00-11:30, center 11:45-12:15, right 12:30-3:00), the Lab-wide sound profile (pitch, duration,
   repeat interval per kind; speech speed) and how it shapes the tone events.
B. Review 8 (0-155 s of Chest-center-0004, one window from the start of the run): danger beats notify-once (6), the 27.3 s person (7),
   the 52.2 s static vehicle (8), no context among dangers (9).
"""

from __future__ import annotations

import copy
import json
import re

import numpy as np
import pytest

import collision as col
from tests.test_collision import CONFIG, FPS, _item, _policy, _rated, _tracks
from tests.test_collision_regression import _run_windows

TONES = CONFIG["tones"]
ROLES = CONFIG["roles"]
SOUNDS = TONES["sounds"]


# ---- config -----------------------------------------------------------------------------------

def test_version_and_the_default_sounds():
    assert CONFIG["version"] == "v26.2.5"
    s = SOUNDS
    assert set(s) == set(col.SOUND_KINDS) == {"collision-left", "collision-center", "collision-right", "crosswalk-in", "crosswalk-out", "proximity"}
    assert (s["collision-center"]["pitchHz"], s["collision-center"]["durationMs"], s["collision-center"]["intervalS"]) == (880, 80, 0.5)
    assert s["collision-left"]["pitchHz"] == 660 and s["collision-right"]["pitchHz"] == 1100
    assert (s["crosswalk-in"]["pitchHz"], s["crosswalk-in"]["durationMs"], s["crosswalk-in"]["intervalS"]) == (330, 600, None)
    assert (s["crosswalk-out"]["pitchHz"], s["crosswalk-out"]["durationMs"], s["crosswalk-out"]["intervalS"]) == (330, 200, 0.12)
    assert (s["proximity"]["pitchHz"], s["proximity"]["durationMs"], s["proximity"]["intervalS"]) == (440, 120, 1.2)
    assert s["collision-center"]["intervalS"] == col._tone_interval(TONES["maxSteps"], TONES["bySteps"])      # the interval at 5 steps
    assert len({s[k]["pitchHz"] for k in ("collision-left", "collision-center", "collision-right", "proximity")}) == 4
    assert TONES["speechRate"] == 1.0 and TONES["soundRanges"]["speechRate"] == [0.5, 2.0] and TONES["soundRanges"]["pitchHz"] == [150, 2000]


def test_the_new_role_numbers():
    assert ROLES["vehicleApproachingMps"] == 2.0 and ROLES["maxWalkingMps"] == 2.0 and ROLES["contextAfterDangerSeconds"] == 2.5
    assert ROLES["panSettleSeconds"] == 1.0
    assert CONFIG["tracking"]["panMatchMinShift"] == 0.06


# ---- A: sectors ---------------------------------------------------------------------------------

@pytest.mark.parametrize("q,kind", [(-12, "left"), (-3, "left"), (-2, "left"), (-1, "center"), (0, "center"), (1, "center"),
                                    (2, "right"), (3, "right"), (12, "right")])
def test_the_sector_of_a_clock_quarter(q, kind):
    """9:00 = -12 ... 11:30 = -2 left; 11:45 = -1, 12 = 0, 12:15 = +1 center (the shared boundaries belong to the center); 12:30 = +2 ... 3:00 right."""
    assert col.collision_kind(q) == f"collision-{kind}"
    assert col.clock_text(-2) == "11:30" and col.clock_text(-1) == "11:45" and col.clock_text(1) == "12:15" and col.clock_text(2) == "12:30"


def _beep_frames(n, quarter_of, steps=3.0, track=9):
    times = np.arange(n) / FPS
    coll = []
    for i in range(n):
        it = _item(track, "danger", steps, "person", group="moving", approaching=True)
        it.clock_q = quarter_of(i)
        it.clock_text = col.clock_text(it.clock_q)
        coll.append((it, {track}))
    return times, coll


@pytest.mark.parametrize("q,kind,hz", [(-5, "collision-left", 660.0), (0, "collision-center", 880.0), (3, "collision-right", 1100.0)])
def test_beeps_take_the_kind_and_pitch_of_their_sector(q, kind, hz):
    times, coll = _beep_frames(30, lambda i: q)
    tn, eps = col._tone_events(coll, times, TONES, None, None)
    assert tn and {e["kind"] for e in tn} == {kind} and {e["frequencyHz"] for e in tn} == {hz}
    assert len(eps) == 1 and eps[0]["kind"] == kind
    side = kind.split("-")[1]
    assert eps[0]["text"].startswith(f"beeps · {side} · person at ")


def test_an_episode_whose_item_changes_sector_switches_kind_per_tone_and_splits():
    times, coll = _beep_frames(60, lambda i: -3 if i < 20 else 0 if i < 40 else 2)
    tn, eps = col._tone_events(coll, times, TONES, None, None)
    by_t = sorted(tn, key=lambda e: e["t"])
    kinds = [e["kind"] for e in by_t]
    assert kinds[0] == "collision-left" and kinds[-1] == "collision-right" and "collision-center" in kinds
    assert kinds == sorted(kinds, key=["collision-left", "collision-center", "collision-right"].index)
    assert [e["kind"] for e in eps] == ["collision-left", "collision-center", "collision-right"]
    for e in tn:                                              # still every tone in exactly one episode
        assert len([x for x in eps if x["kind"] == e["kind"] and x["t"] - 0.05 <= e["t"] <= x["tEnd"] + 0.05]) == 1


def test_a_continuous_chunk_is_marked_and_keeps_its_length():
    times, coll = _beep_frames(20, lambda i: 0, steps=1.0)
    tn, _ = col._tone_events(coll, times, TONES, None, None)
    assert tn and all(e.get("continuous") and e["durationSeconds"] == TONES["continuousChunkSeconds"] for e in tn)
    times, coll = _beep_frames(20, lambda i: 0, steps=4.0)
    tn, _ = col._tone_events(coll, times, TONES, None, None)
    assert tn and not any("continuous" in e for e in tn)


# ---- A: the profile -----------------------------------------------------------------------------

def test_resolve_sounds_clamps_and_ignores_what_it_does_not_know():
    r = col.resolve_sounds(TONES, {"kinds": {"collision-left": {"pitchHz": 99999, "durationMs": "x", "intervalS": 0.0001},
                                              "crosswalk-in": {"intervalS": 3.0}, "bogus": {"pitchHz": 1}}, "speechRate": 7})
    left = r["kinds"]["collision-left"]
    assert left["pitchHz"] == 2000 and left["durationMs"] == 80 and left["intervalS"] == 0.05
    assert r["kinds"]["crosswalk-in"]["intervalS"] is None and "bogus" not in r["kinds"]      # unused field stays unused
    assert r["speechRate"] == 2.0
    assert col.resolve_sounds(TONES, None) == col.resolve_sounds(TONES, {}) and col.resolve_sounds(TONES)["speechRate"] == 1.0
    assert col.resolve_sounds(TONES, {"speechRate": 0.1})["speechRate"] == 0.5


def test_pitch_and_duration_of_a_profile_are_in_the_events():
    prof = {"kinds": {"collision-right": {"pitchHz": 1500, "durationMs": 120}}}
    times, coll = _beep_frames(30, lambda i: 3)
    tn, eps = col._tone_events(coll, times, TONES, None, None, col.resolve_sounds(TONES, prof))
    assert {e["frequencyHz"] for e in tn} == {1500.0} and {e["durationSeconds"] for e in tn} == {0.12}
    assert abs(max(e["t"] + e["durationSeconds"] for e in tn) - eps[0]["tEnd"]) < 1e-3


def test_the_collision_interval_scales_the_whole_parking_table_but_not_the_continuous_chunk():
    base_gaps = {}
    for steps in (4.0, 2.5):
        for iv in (0.5, 1.0):
            prof = {"kinds": {"collision-center": {"intervalS": iv}}}
            times, coll = _beep_frames(90, lambda i: 0, steps=steps)
            tn, _ = col._tone_events(coll, times, TONES, None, None, col.resolve_sounds(TONES, prof))
            base_gaps[(steps, iv)] = float(np.median(np.diff([e["t"] for e in tn])))
    for steps in (4.0, 2.5):
        assert base_gaps[(steps, 1.0)] == pytest.approx(2 * base_gaps[(steps, 0.5)], rel=0.2)
    assert base_gaps[(4.0, 0.5)] == pytest.approx(col._tone_interval(4.0, TONES["bySteps"]), abs=1 / FPS)
    times, coll = _beep_frames(40, lambda i: 0, steps=1.0)
    tn, _ = col._tone_events(coll, times, TONES, None, None, col.resolve_sounds(TONES, {"kinds": {"collision-center": {"intervalS": 2.0}}}))
    assert np.diff([e["t"] for e in tn]) == pytest.approx([TONES["continuousChunkSeconds"]] * (len(tn) - 1), abs=1e-3)


def test_the_intervals_of_proximity_and_crosswalk_out():
    prof = col.resolve_sounds(TONES, {"kinds": {"proximity": {"intervalS": 2.4, "pitchHz": 500}, "crosswalk-out": {"intervalS": 0.3, "durationMs": 100},
                                               "crosswalk-in": {"pitchHz": 400, "durationMs": 900}}})
    n = 80
    times = np.arange(n) / FPS
    soft = []
    for i in range(n):
        it = _item(7, "none", 4.0, "person", group="moving")
        it.proximity = True
        soft.append((it, {7}))
    tn, _ = col._tone_events([(None, {7})] * n, times, TONES, soft, [(2.0, "enter"), (8.0, "exit")], prof)
    sf = [e for e in tn if e["kind"] == "proximity"]
    assert {e["frequencyHz"] for e in sf} == {500.0} and np.diff([e["t"] for e in sf]) == pytest.approx([2.4] * (len(sf) - 1), abs=1 / FPS)
    cin = next(e for e in tn if e["kind"] == "crosswalk-in")
    cout = next(e for e in tn if e["kind"] == "crosswalk-out")
    assert (cin["frequencyHz"], cin["durationSeconds"]) == (400.0, 0.9)
    assert (cout["durationSeconds"], cout["chirp"]["gapSeconds"], cout["chirp"]["count"]) == (0.1, 0.3, 2)


# ---- B6: danger beats notify-once -----------------------------------------------------------------

def _mem_policy():
    world = col._WorldMemory(CONFIG["memory"])
    policy = _policy()
    policy.world = world
    return policy, world


def _linked(world, tracks, t, it):
    world.advance(t, 0.0, 1.2, 0.0)
    it.family = it.family or it.label
    world.link([it], tracks, t)


def test_a_danger_for_something_named_as_context_or_feature_is_spoken():
    policy, world = _mem_policy()
    tr = _tracks(1)
    ctx = _item(1, "context", 3.0, "building")
    ctx.distance_m = 2.0
    _linked(world, tr, 0.0, ctx)
    policy._register(0.0, ctx, tr)                            # "building at 1 in 2" (context)
    assert world.entries[ctx.mem_id]["named"] and not world.entries[ctx.mem_id]["danger"]
    d = _item(1, "danger", 6.0, "building")
    d.distance_m = 2.0
    _linked(world, tr, 0.5, d)
    assert d.mem_id == ctx.mem_id and d.mem_named and not d.mem_danger
    assert not policy._seen_before(d, danger=True) and policy._seen_before(d)        # context / feature phrases are muted, the danger is not
    ev = policy.step(0.5, [d], tr)
    assert ev and ev["role"] == "danger" and ev["text"].startswith("building at 12 in 6")
    assert world.entries[d.mem_id]["danger"]


def test_only_a_danger_call_mutes_the_next_danger_or_final_for_the_same_object():
    policy, world = _mem_policy()
    tr = _tracks(1, 2)
    a = _item(1, "danger", 6.0, "pole")
    a.distance_m = 4.2
    _linked(world, tr, 0.0, a)
    assert policy.step(0.0, [a], tr)["role"] == "danger"
    b = _item(2, "danger", 2.0, "pole")                       # the same pole under a new track, now a final
    b.distance_m, b.collision = 4.2, True
    _linked(world, tr, 3.0, b)
    assert b.mem_id == a.mem_id and b.mem_danger
    assert policy.step(3.0, [b], tr) is None                  # muted: the beeps carry it


# ---- B7: the pan-compensated person match ------------------------------------------------------------

def test_a_person_that_jumps_a_box_width_because_the_camera_panned_keeps_its_track():
    trk = CONFIG["tracking"]
    people = frozenset({"person", "rider", "animal"})
    old = col._Track(5, "moving", "person", col.Box(0.3125, 0.45, 0.3833, 0.63), 0.0, 0.0, 5.9, -2.4)

    def item(x0, x1):
        it = _item(0, "none", 8.0, "person", group="moving")
        it.bbox, it.distance_m, it.lateral_m = [x0, 0.45, x1, 0.62], 5.7, -0.9
        return it
    new = item(0.3875, 0.4542)                               # no overlap with the old box
    assert col._match({5: old}, [new], 0.17, trk, 0.0, people) == {}
    assert col._match({5: old}, [new], 0.17, trk, 0.077, people) == {0: 5}               # a 9 degree pan to the left moves the scene 0.077 right
    assert col._match({5: old}, [new], 0.17, trk, 0.02, people) == {}                    # a gentle pan: unchanged behaviour
    pole = col._Track(6, "static", "pole", col.Box(0.3125, 0.45, 0.3833, 0.63), 0.0, 0.0, 5.9, -2.4)
    pnew = item(0.3875, 0.4542)
    pnew.group, pnew.class_name = "static", "pole"
    assert col._match({6: pole}, [pnew], 0.17, trk, 0.077, people) == {}                 # only people get the pan compensation


# ---- B8: the static vehicle -----------------------------------------------------------------------------

def _state(along, vehicle, prev=None):
    tr = col._Track(1, "moving", "vehicle" if vehicle else "person", col.Box(0, 0, 1, 1), 0.0, 0.0, 5.0, 0.0)
    tr.mstate = prev
    return col._motion_state(tr, 10.0, along, 0.0, None, ROLES, vehicle)


def test_a_vehicle_needs_a_clear_own_speed_to_be_approaching():
    assert _state(0.6, False) == "approach"                   # a person (or a cyclist) at 0.6 m/s: approaching, as before
    assert _state(1.5, True) is None                          # a parked car read 1-3 m/s off at 52.2 s: no state, so no "approaching"
    assert _state(2.4, True) == "approach" and _state(7.0, True) == "approach"
    assert _state(1.5, True, prev="approach") == "approach"   # hysteresis (0.7 x 2.0)
    assert _state(1.2, True, prev="approach") is None


def test_an_unsettled_ego_speed_allows_approaching_only_for_a_vehicle_faster_than_a_walker():
    def veh(closing):
        v = _rated("vehicle", "moving", 12, 0.1, ego_known=True, moving=True, approaching=True, closing=closing, urgency="danger")
        v.ego_settled = False
        v.own_fast = closing - ROLES["maxWalkingMps"] >= ROLES["approachingMps"]          # what the driver sets
        return v
    assert col.SpeechPolicy._kind(veh(1.9), "danger") == "danger"                          # a walker's speed: the plain phrase
    assert col.SpeechPolicy._kind(veh(2.5), "danger") == "approach" and col.SpeechPolicy._kind(veh(5.0), "danger") == "approach"


# ---- B9: no context among dangers ----------------------------------------------------------------------------

def _ctx_item(track, steps=3.0):
    it = _item(track, "context", steps, "building")
    it.distance_m = steps * 0.7
    return it


def test_no_context_phrase_for_2_5_seconds_after_a_danger_phrase_or_a_beep_stream():
    p = _policy()
    tr = _tracks(1, 2, 3)
    p.last_danger_t = 10.0
    c = _ctx_item(1)
    assert p.step(11.0, [c], tr) is None and p.step(12.4, [c], tr) is None               # still among dangers
    ev = None
    for t in np.arange(12.5, 16.0, 0.17):
        ev = ev or p.step(float(t), [c], tr)
    assert ev and ev["role"] == "context" and ev["text"].startswith("building")            # afterwards, as usual
    q = _policy()
    q.last_beep_t = 20.0
    assert q.step(21.0, [_ctx_item(2)], tr) is None
    r = _policy()
    r.last_danger_t = None
    ev = None
    for t in np.arange(0.0, 1.0, 0.17):
        ev = ev or r.step(float(t), [_ctx_item(3)], tr)
    assert ev and ev["role"] == "context"


def test_surfaces_and_features_are_not_held_back_by_a_recent_danger():
    p = _policy()
    p.last_danger_t = 10.0
    p.surface_pending = ("road", "road")
    ev = p.step(11.5, [], _tracks(1))
    assert ev and ev["role"] == "surface"


def test_a_never_named_context_thing_reached_among_dangers_gets_no_final_phrase_but_a_named_one_does():
    def final(named, recent):
        policy, world = _mem_policy()
        tr = _tracks(1)
        tr[1].context_seen = True
        it = _item(1, "danger", 2.0, "building")
        it.distance_m, it.collision = 1.4, True
        _linked(world, tr, 5.0, it)
        if named:
            eid = world.add(it, 5.0, named=True)
            world.link([it], tr, 5.1)
            assert it.mem_id == eid and it.mem_named
        if recent:
            policy.last_danger_t = 4.0
        return policy.step(5.1 if named else 5.0, [it], tr)
    assert final(False, False)["role"] == "final"            # on its own: spoken
    assert final(False, True) is None                         # in the middle of dangers: the beeps are enough
    assert final(True, True)["role"] == "final"               # named as context before: collision and danger supersede notify-once


# ---- review 8 -----------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def review8():
    return _run_windows("chest0004_review8")


def test_review8_fixture_is_the_documented_one(review8):
    meta, npz, windows = review8
    assert [(w["start"], w["end"]) for w in meta["windows"]] == [(0.0, 155.0)]
    t = npz["w0_t"]
    assert t[0] < 0.05 and t[-1] >= 154.5 and npz["w0_grids"].shape == (len(t), meta["gridH"], meta["gridW"])
    ann = meta["annotations"]
    assert [a["kind"] for a in ann].count("added") == 2
    assert sum(a.get("verdict") == "correct" for a in ann) == 41
    assert sorted(a["t"] for a in ann if a.get("verdict") == "remove") == [28.4952, 107.007]
    assert [a["t"] for a in ann if a.get("verdict") == "incorrect"] == [52.1688]
    assert len(meta["systemEventsV26_1_15"]) == 87


def _norm(text: str) -> str:
    return re.sub(r" in \d+| in 1 step", "", text)


def _produced(ev, a):
    """Does the new run produce what ✓ entry ``a`` ticked? Speech: the same phrase (steps may differ) within 1.5 s. Beeps: an episode of the same label there."""
    e = a["event"]
    if e["type"] == "speech":
        return any(x["type"] == "speech" and abs(x["t"] - e["t"]) <= 1.5 and _norm(x["text"]) == _norm(e["text"]) for x in ev)
    return any(x["type"] == "beeps" and x.get("label") == e.get("label") and x["t"] - 0.5 <= e["t"] <= x["tEnd"] + 0.5 for x in ev)


def test_review8_the_old_run_is_reproduced_by_the_fixture_where_nothing_changed(review8):
    """The v26.1.15 run (87 system events, 32 phrases) minus the changes: most of it is still there."""
    meta, _, windows = review8
    old = {(round(e["t"], 1), e["text"]) for e in meta["systemEventsV26_1_15"] if e["type"] == "speech"}
    new = {(round(e["t"], 1), e["text"]) for e in windows[0]["events"] if e["type"] == "speech"}
    assert len(old & new) >= 24, sorted(old - new)


def test_review8_most_ticked_entries_are_still_produced(review8):
    meta, _, windows = review8
    ev = windows[0]["events"]
    ticks = [a for a in meta["annotations"] if a["kind"] == "verdict" and a["verdict"] == "correct"]
    lost = [(a["t"], a["event"]["text"]) for a in ticks if not _produced(ev, a)]
    assert len(ticks) - len(lost) >= 40, lost
    # the one tick that moves: 54.7 s "building at 1:30 in 2, obstacle at 1 in 2" is said at the same time as "building at 1:15 in 2, ..." (the
    # clock of the nearest cell changed with the tracking; the same two objects)
    assert [round(t, 1) for t, _ in lost] == [54.7], lost


def test_review8_the_person_at_27_3_s_is_announced_at_its_first_eligible_frame(review8):
    _, _, windows = review8
    sp = [e for e in windows[0]["speech"] if 26.5 <= e["t"] <= 29.0]
    assert sp and sp[0]["t"] <= 27.5 and sp[0]["text"] == "person at 11:45 in 8", [(e["t"], e["text"]) for e in sp]       # the user's added entry
    assert not [e for e in sp if "person" in e["text"] and e["t"] > 27.5], [(e["t"], e["text"]) for e in sp]     # and not again 1.2 s later


def test_review8_the_vehicle_at_52_s_is_no_longer_approaching(review8):
    _, _, windows = review8
    assert not [e for e in windows[0]["speech"] if "vehicle" in e["text"] and 51.0 <= e["t"] <= 54.0]


def test_review8_no_context_phrase_in_the_middle_of_dangers(review8):
    _, _, windows = review8
    ev = windows[0]["events"]
    gap = ROLES["contextAfterDangerSeconds"]
    dangers = [e["t"] for e in ev if e["type"] == "speech" and e["role"] in ("danger", "final")]
    ctx = [e for e in ev if e["type"] == "speech" and e["role"] == "context"]
    assert ctx
    for c in ctx:
        assert not [d for d in dangers if 0 <= c["t"] - d < gap - 1e-6], (c["t"], c["text"])
    assert not [e for e in ev if e["type"] == "speech" and e["role"] == "final" and "vegetation" in e["text"]]      # 107.0 s


def test_review8_a_pole_already_named_gets_its_danger_call(review8):
    """Rule 6 on the footage: the pole at 11:45 named as a feature at 97.0 s is called a final at 108.7 s (2 steps) - the beeps alone are not enough."""
    _, _, windows = review8
    assert [e for e in windows[0]["speech"] if e["role"] == "final" and e["text"].startswith("pole at 11:45") and 108 <= e["t"] <= 109.5]


def test_review8_collision_beeps_are_split_by_sector(review8):
    _, _, windows = review8
    eps = [e for e in windows[0]["events"] if e["type"] == "beeps" and e["kind"].startswith("collision")]
    assert {e["kind"] for e in eps} == {"collision-center", "collision-right"}, [(e["t"], e["kind"]) for e in eps]
    for e in eps:                                             # the kind is the sector of the clock position of the episode
        q = {"11:45": -1, "12": 0, "12:15": 1, "12:30": 2}[e["clockText"]]
        assert e["kind"] == col.collision_kind(q)
        assert e["text"].startswith("beeps · " + e["kind"].split("-")[1] + " · ")
    tones = [e for e in windows[0]["events"] if e["type"] == "tone" and e["kind"].startswith("collision")]
    assert {e["frequencyHz"] for e in tones if e["kind"] == "collision-right"} == {1100.0}
    assert {e["frequencyHz"] for e in tones if e["kind"] == "collision-center"} == {880.0}


# ---- the lane versus the 11:45-12:15 band (review 8, 10.9 s: "anything in that range has a fair chance of collision") ----------

LANE = ROLES and CONFIG["geometry"]["laneHalfWidthM"]


def test_lane_angle_versus_the_center_band():
    import math
    half_angle = lambda d: math.degrees(math.atan(LANE / d))        # noqa: E731
    assert half_angle(2.0) == pytest.approx(16.7, abs=0.1) and half_angle(4.0) == pytest.approx(8.5, abs=0.1)
    assert half_angle(7.4) == pytest.approx(4.6, abs=0.1)                                # 10 steps: the lane is inside the band
    cross = LANE / math.tan(math.radians(7.5))                                             # where the lane is as wide as 11:45-12:15 (+-7.5 deg)
    assert cross == pytest.approx(4.56, abs=0.01) and cross / 0.7 == pytest.approx(6.5, abs=0.05)
    assert 7.0 * math.tan(math.radians(7.5)) == pytest.approx(0.92, abs=0.01)             # at 10 steps the band reaches 0.92 m sideways, the lane 0.6 m
