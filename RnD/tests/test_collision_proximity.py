"""v26.1.13 follow-up: a soft proximity sound for a person measured approaching nearby (the user's choice (c) of the beep question:
"a different, softer sound for 'approaching person nearby' than for a collision course").

Synthetic units for the rule, the sound events and the switch-over, then the review-6 block on ``4929_review6.{json,npz}``."""

from __future__ import annotations

import numpy as np
import pytest

import collision as col
from tests.test_collision import CONFIG, _item, FPS
from tests.test_collision import _rated
from tests.test_collision_regression import _all, _near
from tests.test_collision_v26113 import review6  # noqa: F401  (fixture)

ROLES = CONFIG["roles"]
TONES = CONFIG["tones"]
APPROACH = dict(moving=True, approaching=True, closing=1.5)


def test_the_proximity_numbers():
    assert CONFIG["version"] == "v26.1.16"                    # (the follow-up kept v26.1.13)
    assert ROLES["proximitySteps"] == 5 and ROLES["proximityLateralM"] == 2.6
    p, snd = TONES["proximity"], TONES["sounds"]
    assert snd["proximity"]["pitchHz"] == 440 and snd["collision-center"]["pitchHz"] == 880
    assert p["gain"] == 0.25 and snd["proximity"]["intervalS"] == 1.2          # about half the collision gain (0.5), slow fixed rhythm
    assert p["chirp"]["count"] == 2 and p["chirp"]["attackSeconds"] > 0.005


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cls", ["person", "animal"])
def test_an_approaching_person_nearby_off_the_collision_course_gets_the_soft_sound(cls):
    p = _rated(cls, "moving", 4.0, 2.2, **APPROACH)                      # review 6, 78.2 / 90.5 s (lateral 2.4)
    assert p.proximity and not p.collision and p.role == "none"          # no role: speech and context are untouched
    assert _rated(cls, "moving", ROLES["proximitySteps"], 2.0, **APPROACH).proximity
    assert _rated(cls, "moving", 3.0, ROLES["proximityLateralM"] - 0.05, **APPROACH).proximity
    # spoken (4.5-5 steps) and soft at the same time is fine: the soft sound is a sound, not a phrase
    spoken = _rated(cls, "moving", 4.8, 2.0, **APPROACH)
    assert spoken.proximity and spoken.speak and spoken.role == "danger"


def test_outside_the_zone_or_not_approaching_there_is_no_soft_sound():
    assert not _rated("person", "moving", 5.5, 2.0, **APPROACH).proximity               # farther than 5 steps: speech only
    assert not _rated("person", "moving", 4.0, 2.7, **APPROACH).proximity              # beside the zone (180.7 s, 3.0-3.6 m)
    assert not _rated("person", "moving", 4.0, 2.0, moving=True, receding=True, closing=0.5).proximity
    assert not _rated("person", "moving", 4.0, 2.0, moving=False).proximity             # standing
    assert not _rated("person", "moving", 4.0, 2.0, moving=None).proximity              # unknown motion
    assert not _rated("person", "moving", 4.0, 2.0, moving=True, closing=0.0).proximity # moving sideways, not approaching


@pytest.mark.parametrize("cls", ["rider", "vehicle"])
def test_riders_and_vehicles_never_get_the_soft_sound(cls):
    assert not _rated(cls, "moving", 4.0, 2.0, **APPROACH).proximity


def test_on_a_collision_course_it_is_a_collision_not_a_proximity():
    p = _rated("person", "moving", 4.0, 0.5, **APPROACH)
    assert p.collision and not p.proximity


# --------------------------------------------------------------------------
# The sound events
# --------------------------------------------------------------------------

def _frames(n, steps_of, soft_of, coll_of=None, soft_id=7, coll_id=9):
    times = np.arange(n) / FPS
    soft, coll = [], []
    for i in range(n):
        s = soft_of(i)
        it = None
        if s:
            it = _item(soft_id, "none", steps_of(i), "person", group="moving")
            it.proximity = True
        soft.append((it, {soft_id, coll_id}))
        c = coll_of(i) if coll_of else False
        ct = None
        if c:
            ct = _item(coll_id, "danger", 3.0, "person", group="moving", approaching=True)
        coll.append((ct, {soft_id, coll_id}))
    return times, coll, soft


def test_the_soft_sound_is_a_slow_fixed_double_chirp_lower_and_softer_than_the_beeps():
    times, coll, soft = _frames(60, lambda i: 4.0 - i * 0.03, lambda i: True)
    tn, eps = col._tone_events(coll, times, TONES, soft)
    assert tn and all(e["kind"] == "proximity" for e in tn)
    p, snd = TONES["proximity"], TONES["sounds"]["proximity"]
    assert {e["frequencyHz"] for e in tn} == {float(snd["pitchHz"])} and all(e["gain"] == p["gain"] for e in tn)
    assert all(e["chirp"] == {"count": 2, "gapSeconds": p["chirp"]["gapSeconds"], "attackSeconds": p["chirp"]["attackSeconds"]} for e in tn)
    assert np.diff([e["t"] for e in tn]) == pytest.approx([snd["intervalS"]] * (len(tn) - 1), abs=1 / FPS)   # the rate does not encode distance
    assert len(eps) == 1 and eps[0]["kind"] == "proximity" and eps[0]["type"] == "beeps"
    assert eps[0]["text"].startswith("soft · person at 12 · ") and eps[0]["text"].endswith("steps")


def test_collision_beeps_are_unchanged_and_carry_their_kind():
    times = np.arange(30) / FPS
    coll = [(_item(9, "danger", 4.0 - i * 0.05, "pole"), {9}) for i in range(30)]
    for it, _ in coll:
        it.collision = True
    tn, eps = col._tone_events(coll, times, TONES, [(None, {9})] * 30)
    assert tn and all(e["kind"] == "collision-center" and e["frequencyHz"] == 880.0 and "gain" not in e and "chirp" not in e for e in tn)
    assert len(eps) == 1 and eps[0]["kind"] == "collision-center" and eps[0]["text"].startswith("beeps · center · pole at 12")


def test_the_two_sounds_never_play_at_once_the_collision_beeps_win_and_the_soft_one_resumes_after():
    # the soft item is there the whole time; a collision track beeps from 1.0 to 3.0 s
    times, coll, soft = _frames(80, lambda i: 4.0, lambda i: True, lambda i: 10 <= i < 30)
    tn, eps = col._tone_events(coll, times, TONES, soft)
    beeps = [e for e in tn if e["kind"].startswith("collision")]
    softs = [e for e in tn if e["kind"] == "proximity"]
    assert beeps and softs
    lo, hi = min(e["t"] for e in beeps), max(e["t"] for e in beeps)
    assert not [e for e in softs if lo - 1e-6 <= e["t"] <= hi + 0.3]
    assert [e for e in softs if e["t"] < lo] and [e for e in softs if e["t"] > hi]
    assert {e["kind"] for e in eps} == {"collision-center", "proximity"}


def test_a_track_that_turns_into_a_collision_course_switches_from_soft_to_beeps():
    """The item is soft first, then (same track) a collision: the soft stream stops where the beeps start."""
    n = 60
    times = np.arange(n) / FPS
    soft, coll = [], []
    for i in range(n):
        if i < 30:
            it = _item(7, "none", 4.0, "person", group="moving")
            it.proximity = True
            soft.append((it, {7})); coll.append((None, {7}))
        else:
            c = _item(7, "danger", 3.0, "person", group="moving", approaching=True)
            soft.append((None, {7})); coll.append((c, {7}))
    tn, eps = col._tone_events(coll, times, TONES, soft)
    kinds = [e["kind"] for e in sorted(tn, key=lambda e: e["t"])]
    assert kinds[0] == "proximity" and kinds[-1].startswith("collision")
    assert kinds == sorted(kinds, key=lambda k: k.startswith("collision"))             # soft ... then beeps, never interleaved
    assert max(e["t"] for e in tn if e["kind"] == "proximity") < min(e["t"] for e in tn if e["kind"].startswith("collision"))


def test_a_lost_track_keeps_the_soft_sound_only_for_the_hold_time():
    n = 40
    times = np.arange(n) / FPS
    soft = [(None, set())] * n
    it = _item(7, "none", 4.0, "person", group="moving")
    it.proximity = True
    soft[0] = (it, {7})
    tn, _ = col._tone_events([(None, set())] * n, times, TONES, soft)
    assert all(e["t"] <= TONES["holdSeconds"] + 1e-6 for e in tn)


def test_without_a_proximity_stream_the_old_call_still_works():
    times = np.arange(5) / FPS
    tn, eps = col._tone_events([(None, set())] * 5, times, TONES)
    assert tn == [] and eps == []


# --------------------------------------------------------------------------
# Review 6 (4929 0-452 s): what each beep entry now produces
# --------------------------------------------------------------------------

def _beep_entries(meta):
    return [a for a in meta["annotations"] if a["kind"] == "verdict" and a["event"]["type"] == "beeps"]


def test_review6_the_person_beeps_come_back_as_soft_sounds_where_the_person_was_measured_approaching(review6):  # noqa: F811
    meta, _, windows = review6
    soft = _all(windows, "soft")
    got = {t: [(round(b["t"], 1), b["clockText"]) for b in _near(soft, t, 1.5)] for t in (78.1615, 90.5072, 91.0816, 92.0651)}
    assert all(got.values()), got                                                    # four of the six ticked person beeps are back
    assert got[78.1615] == [(78.2, "1")] and (90.7, "1:15") in got[90.5072] and (92.0, "1:15") in got[92.0651]
    assert (90.7, "1:15") in got[91.0816]                                              # ticked at 1:30; the clock reads 1:15 (two tracks, 2050 at 92.0 s)
    assert [b["t"] for b in _near(soft, 366.4915, 2.5)] == [] and [b["t"] for b in _near(soft, 48.8405, 2.5)] == []


def test_review6_the_removed_beeps_180_7_and_191_5_stay_silent_203_8_and_376_0_come_back_soft(review6):  # noqa: F811
    meta, _, windows = review6
    soft, beeps = _all(windows, "soft"), _all(windows, "beeps")
    assert not _near(soft, 180.6807, 2.5) and not _near(beeps, 180.6807, 2.5)       # 3.0-3.6 m: outside the zone
    assert not _near(soft, 191.4831, 2.5) and not _near(beeps, 191.4831, 2.5)       # a cyclist: spoken early, no soft sound
    assert [b["clockText"] for b in _near(soft, 203.8288, 1.0)] == ["12:45"]    # accepted by choosing (c) (the id was 4984; ids shift)
    assert [b["clockText"] for b in _near(soft, 376.001, 1.0)] == ["1"]
    assert not _near(beeps, 203.8288, 2.5) and not _near(beeps, 376.001, 2.5)


def test_review6_the_collision_beeps_are_the_cyclist_at_445_7_only_and_the_soft_sounds_are_person_only(review6):  # noqa: F811
    _, _, windows = review6
    assert [(round(b["t"], 1), b["text"]) for b in _all(windows, "beeps")] == [(445.7, "beeps · center · cyclist at 11:45 · 4 steps")]
    soft = _all(windows, "soft")
    assert soft and all(b["label"] == "person" and b["minSteps"] <= ROLES["proximitySteps"] + 0.5 for b in soft)
    assert len(windows[0]["tones"]) == 2                                            # the collision tones: as in v26.1.13
    assert [round(b["t"], 1) for b in soft] == [78.2, 90.7, 92.0, 203.8, 376.0]


def test_review6_every_soft_sound_has_a_measured_approaching_person_inside_the_zone(review6):  # noqa: F811
    _, _, windows = review6
    frames = {f["t"]: {h["trackId"]: h for h in f["hazards"]} for f in windows[0]["doc"]["frames"]}
    for tone in windows[0]["softTones"]:
        t0 = max(t for t in frames if t <= tone["t"] + 1e-9)
        h = frames[t0].get(tone["trackId"])
        assert h is None or (h["className"] == "person" and h["moving"] is True and abs(h["lateralM"]) <= ROLES["proximityLateralM"] + 0.2
                             and h["stepsTo"] <= ROLES["proximitySteps"] + 0.5 and not h["collision"]), (tone, h)
