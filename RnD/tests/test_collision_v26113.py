"""v26.1.13 (review 6): a phrase window for people, an early warning for riders and vehicles, beeps only on a real collision
course, a stricter lateral limit for context, a robust ego speed for the motion states.

Synthetic units for every rule, then the real-footage block on ``4929_review6.{json,npz}`` (one window 0-452 s of the run from its
start, with the DA2 depth maps: the depth scale and the ego state need the whole history)."""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

import collision as col
from tests.test_collision import CONFIG, _item, _policy, _rated, _tracks, base_grid, hz, place, run
from tests.test_collision_regression import FIXTURES, _all, _load, _near, _produced, _run_windows
from tests.test_collision_v26111 import _mover

ROLES = CONFIG["roles"]


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def test_the_v26113_numbers():
    assert CONFIG["version"] == "v26.2.1"
    assert ROLES["peopleSpeakMinSteps"] == 4.5 and ROLES["movingDangerSteps"] == 10 and ROLES["peopleSpeakLateralM"] == 2.75
    assert ROLES["beepLateralM"] == 0.9 and CONFIG["tones"]["maxSteps"] == 5
    assert ROLES["fastWarnSeconds"] == 6.0 and ROLES["fastWarnMaxM"] == 30.0
    assert ROLES["contextMaxLateralM"] == 2.5 and ROLES["contextNearSteps"] == 3.0 and ROLES["contextNearLateralM"] == 3.0
    assert ROLES["egoMedianSeconds"] == 3.0
    assert set(CONFIG["classes"]["fast"]) == {"rider", "vehicle"}
    tpl = CONFIG["speech"]["templates"]
    assert tpl["approach"] == "{label} approaching at {clock} in {steps}" and tpl["approachFast"] == "{label} approaching at {clock}"
    assert tpl["receding"] == "{label} moving away at {clock} in {steps}"


# --------------------------------------------------------------------------
# 1. People: spoken once at 5-10 steps inside the zone, whatever the direction; under 5 steps beeps only
# --------------------------------------------------------------------------

STATES = [dict(moving=None), dict(moving=False), dict(moving=True, approaching=True, closing=1.5),
          dict(moving=True, receding=True, closing=0.5), dict(moving=True, closing=0.0)]


@pytest.mark.parametrize("kw", STATES)
@pytest.mark.parametrize("cls", ["person", "animal"])
def test_people_are_spoken_at_5_to_10_steps_inside_the_zone_whatever_their_direction(cls, kw):
    p = _rated(cls, "moving", 8, 2.4, **kw)                          # review 6, 111.6 s: "good to know someone is there" (lateral 2.4)
    assert p.role == "danger" and p.speak and not p.collision
    assert _rated(cls, "moving", 8, 3.0, **kw).role == "none"          # review 6, 178-181 s: a static person 3.0 m to the side
    assert _rated(cls, "moving", ROLES["movingDangerSteps"] + 0.6, 1.0, **kw).role == "none"
    assert _rated(cls, "moving", ROLES["movingDangerSteps"], 1.0, **kw).role == "danger"
    assert _rated(cls, "moving", ROLES["peopleSpeakMinSteps"], 1.0, **kw).speak


@pytest.mark.parametrize("kw", [dict(moving=None), dict(moving=False)])
def test_under_5_steps_a_person_only_beeps_and_only_on_a_collision_course(kw):
    near = _rated("person", "moving", 4.0, 0.5, **kw)
    assert near.role == "danger" and near.collision and not near.speak
    assert _rated("person", "moving", 4.0, 1.5, **kw).role == "none"          # review 6: 1.2-3.0 m, "not on a collision course"
    assert _rated("person", "moving", 4.0, 2.2, **kw).role == "none"
    assert _rated("person", "moving", 4.4, 0.5, **kw).speak is False and _rated("person", "moving", 4.6, 0.5, **kw).speak


def test_a_measured_approach_beeps_only_when_the_predicted_lateral_is_inside_the_body_width():
    kw = dict(moving=True, approaching=True, closing=2.0, lat_vel=None)
    assert _rated("person", "moving", 4.0, 0.8, **kw).collision
    assert not _rated("person", "moving", 4.0, 1.0, **kw).collision
    ap = _rated("person", "moving", 4.0, 2.2, **kw)                            # review 6, 78.2 / 90.5 s (lateral 2.4)
    assert ap.role == "none" and not ap.collision
    assert not _rated("person", "moving", 4.0, 0.3, moving=True, receding=True, closing=0.5).collision


def test_a_silent_person_is_not_spoken_not_even_as_a_final_but_still_holds_the_context_back():
    p = _policy()
    tr = _tracks(1)
    near = _mover(1, "person", 2.5, 12, "unknown")
    near.role, near.collision, near.speak, near.urgency = "danger", True, False, "final"
    assert p.step(0.0, [near], tr) is None and p.step(5.0, [near], tr) is None and not tr[1].final_done
    ctx = _item(2, "context", 4, "obstacle", clock=1)
    assert p.step(6.0, [near, ctx], _tracks(1, 2)) is None                    # a danger is active: context waits
    assert p.step(7.0, [ctx], _tracks(2))["text"] == "obstacle at 1 in 4"


@pytest.mark.parametrize("state,expected", [
    ("approach", "person approaching at 12:15 in 9"),
    ("receding", "person moving away at 12:15 in 9"),
    ("standing", "person standing at 12:15 in 9"),
    ("unknown", "person at 12:15 in 9"),
])
def test_every_person_phrase_carries_the_distance(state, expected):
    it = _mover(1, "person", 9, 12, state)
    it.clock_q, it.clock_text = 1, "12:15"
    p = _policy()
    assert p.step(0.0, [it], _tracks(1))["text"] == expected


# --------------------------------------------------------------------------
# 2. Riders and vehicles approaching on or near the path: as early as possible, no distance
# --------------------------------------------------------------------------

def test_a_cyclist_approaching_near_the_path_is_a_danger_far_out_without_a_step_limit():
    kw = dict(moving=True, approaching=True, lat_vel=None)
    far = _rated("rider", "moving", 40, 0.5, closing=6.0, **kw)               # 28 m, 4.7 s away: step 40
    assert far.role == "danger" and far.collision
    passing = _rated("rider", "moving", 14, 1.9, closing=6.0, **kw)           # review 6, 191.5 s: at 1.9 m, "warn as soon as possible"
    assert passing.role == "danger" and not passing.collision                 # ... and "no need for a beep"
    assert _rated("rider", "moving", 14, 0.5, closing=6.0, **kw).collision
    assert _rated("rider", "moving", 60, 0.5, closing=6.0, **kw).role == "none"       # beyond fastWarnMaxM (30 m)
    assert _rated("rider", "moving", 20, 0.5, closing=1.5, **kw).role == "none"       # 9 s away: not yet
    assert _rated("rider", "moving", 14, 3.5, closing=6.0, **kw).role == "none"       # not near the path
    assert _rated("rider", "moving", 14, 0.5, closing=0.1, **kw).role == "none"


def test_the_predicted_lateral_position_decides_for_a_vehicle_not_the_present_one():
    kw = dict(moving=True, approaching=True)
    crossing = _rated("vehicle", "moving", 30, 7.0, closing=3.0, lat_vel=-6.0, **kw)      # far to the side now: cleared by then
    assert crossing.role == "none"
    coming = _rated("vehicle", "moving", 20, 1.2, closing=5.0, lat_vel=None, **kw)
    assert coming.role == "danger" and not coming.collision
    assert _rated("vehicle", "moving", 20, 0.4, closing=5.0, lat_vel=None, **kw).collision


def test_riders_and_vehicles_approaching_are_said_without_the_distance_also_as_a_final():
    p = _policy()
    it = _mover(1, "cyclist", 20, 11, "approach")
    assert p.step(0.0, [it], _tracks(1))["text"] == "cyclist approaching at 11"
    fin = _mover(2, "vehicle", 2.5, 10, "approach")
    fin.urgency = "final"
    assert _policy().step(0.0, [fin], _tracks(2))["text"] == "vehicle approaching at 10"
    both = [_mover(1, "cyclist", 20, 11, "approach"), _mover(2, "cyclist", 19, 12, "approach")]
    assert _policy().step(0.0, both, _tracks(1, 2))["text"] == "cyclist approaching at 11 and 12"


def test_a_cyclist_walking_away_or_standing_is_a_person_like_phrase_with_distance():
    p = _rated("rider", "moving", 8, 1.0, moving=True, receding=True, closing=0.5)
    assert p.role == "danger" and not p.collision
    it = _mover(1, "cyclist", 8, 12, "receding")
    assert _policy().step(0.0, [it], _tracks(1))["text"] == "cyclist moving away at 12 in 8"


def test_a_rider_is_placed_at_the_middle_of_its_lowest_row_not_at_the_wheel_nearest_the_image_centre():
    """Review 6, 445.3 s ("position is wrong"): the column nearest the image centre on the lowest row of a bicycle + rider is its inner
    edge, up to one clock quarter off the body."""
    frames = []
    for cls in ("rider", "person"):
        fr = []
        for _ in range(6):
            g = base_grid(half_w_m=3.0)
            place(g, cls, 8.0, -1.5, 1.4, 1.7)                                   # a wide mask: 1.4 m
            fr.append(g)
        doc, _ = run(fr)
        got = hz(doc, cls)
        assert got, cls
        frames.append(got[-1][1]["lateralM"])
    assert frames[0] < frames[1] - 0.3, frames                                     # rider: the middle (more to the left)


# --------------------------------------------------------------------------
# 3. Context beside the path
# --------------------------------------------------------------------------

def test_context_beside_the_path_uses_2_5_m_and_3_m_only_right_under_us():
    assert _rated("building", "static", 5, 2.4).role == "context"                  # review 6, 0.7 s / 383.3 s ticks (2.4 / 2.3 m)
    assert _rated("building", "static", 7.8, 2.9).role != "context"                # review 6, 132.3 s ⊘ (2.9 m, 7.8 steps)
    assert _rated("building", "static", 3.7, 2.86).role != "context"               # review 6, 179.5 s ⊘ (2.86 m, 3.7 steps)
    assert _rated("building", "static", 2.6, 2.93).role == "context"               # review 6, 59.2 s ✓ (2.93 m, 2.6 steps)
    assert _rated("building", "static", 2.6, 3.2).role != "context"


# --------------------------------------------------------------------------
# 4. Robust ego speed for the motion states
# --------------------------------------------------------------------------

def test_the_motion_speed_is_the_median_of_the_last_three_seconds():
    hist: list = []
    speeds = [1.1] * 12 + [2.07] + [1.1] * 2                  # a one-frame spike (review 6, 374.0 s: 2.07 against 1.1)
    out = [col._robust_speed(hist, 0.17 * i, s, 3.0) for i, s in enumerate(speeds)]
    assert max(out) == pytest.approx(1.1)
    assert col._robust_speed([], 0.0, 2.0, 0.0) == 2.0           # window 0: the speed itself
    hist = []
    for i in range(40):                                           # old values leave the window
        v = col._robust_speed(hist, 0.17 * i, 1.0 if i < 20 else 2.0, 3.0)
    assert v == pytest.approx(2.0)


def test_a_spike_of_the_ego_speed_does_not_make_a_closing_person_stand():
    """closing 1.69 against the spike 2.07: along = -0.38 (not "approaching"); against the median 1.1: +0.59."""
    tr = _tracks(1)[1]
    hist: list = []
    for i in range(18):
        med = col._robust_speed(hist, 0.17 * i, 2.07 if i == 17 else 1.1, 3.0)
    assert med == pytest.approx(1.1)
    states = [col._motion_state(tr, 0.17 * i, 1.69 - med, 0.0, None, ROLES) for i in range(3)]
    assert states[-1] == "approach"


# --------------------------------------------------------------------------
# Review 6 (v26.1.12, 4929 0-452 s; fixtures 4929_review6)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def review6():
    return _run_windows("4929_review6")


def _ann6(meta, t, kind=None, verdict=None):
    return [a for a in meta["annotations"] if abs(a["t"] - t) < 0.02 and (kind is None or a["kind"] == kind)
            and (verdict is None or a.get("verdict") == verdict)]


def test_review6_fixture_is_the_documented_one():
    meta, settings = _load("4929_review6")
    npz = np.load(FIXTURES / "4929_review6.npz")
    assert [(w["start"], w["end"]) for w in meta["windows"]] == [(0.0, 452.0)]
    t = npz["w0_t"]
    assert t[0] < 0.2 and 451.5 <= t[-1] <= 452.0
    assert npz["w0_grids"].shape == (len(t), meta["gridH"], meta["gridW"])
    assert npz["w0_depth"].shape == (len(t), *meta["depth"]["shape"]) and npz["w0_depth"].dtype == np.float16
    assert len(npz["w0_mt"]) == len(npz["w0_mdx"]) == len(npz["w0_mresid"]) > 10000
    ann = meta["annotations"]
    assert len(ann) == 48 and meta["summary"] == {"correct": 36, "incorrect": 0, "remove": 10, "added": 2}
    assert (sum(a.get("verdict") == "correct" for a in ann), sum(a.get("verdict") == "remove" for a in ann),
            sum(a["kind"] == "added" for a in ann)) == (36, 10, 2)
    assert all(a["runId"] == "36d9d120d801" and a["collisionVersion"] == "v26.1.12" for a in ann)
    assert max(a["t"] for a in ann) < 452.0 and settings.distance_source == "depth" and settings.user_height_m == 1.78
    old = [e["text"] for e in meta["systemEventsV26_1_12"] if e["type"] in ("speech", "beeps")]
    assert len(old) == 46 and "person approaching at 1" in old and "cyclist approaching at 11" in old
    added = {a["t"]: a for a in ann if a["kind"] == "added"}
    assert set(added) == {76.6, 111.6} and added[76.6]["role"] == "danger" and "incomming" in added[76.6]["note"]


def test_review6_none_of_the_ten_entries_marked_should_not_be_said_is_produced_any_more(review6):
    meta, _, windows = review6
    entries = [a for a in meta["annotations"] if a.get("verdict") == "remove"]
    assert len(entries) == 10
    for a in entries:
        got = _produced(meta, windows, a)
        if a["t"] == 203.8288 and a["event"]["type"] == "speech":
            continue                                    # the same person, announced earlier and with the distance (next test)
        assert not got, (a["t"], a["event"]["text"], [(e["t"], e["text"]) for e in got])
    assert not [b for b in _all(windows, "beeps") if b["label"] == "person"]           # no person parking beeps at all in 0-452 s


def test_review6_203_8_the_person_is_announced_earlier_and_with_the_distance(review6):
    _, _, windows = review6
    sp = [e for e in _all(windows) if 200.0 <= e["t"] <= 205.0 and e["text"].startswith("person")]
    assert [(e["t"], e["text"]) for e in sp] == [(202.661, "person approaching at 12:30 in 8")]
    assert not [b for b in _all(windows, "beeps") if 200.0 <= b["t"] <= 206.0]


def test_review6_the_person_at_76_6_s_is_announced_at_9_steps_and_the_one_at_88_8_s_before_the_beeps_he_had(review6):
    _, _, windows = review6
    sp = _all(windows)
    assert [e for e in sp if e["text"] == "person approaching at 12:15 in 9" and abs(e["t"] - 76.6) <= 0.2]       # the added entry
    first = [e for e in sp if 86.0 <= e["t"] <= 92.0 and e["text"].startswith("person")]
    assert first and first[0]["t"] < 90.0 and re.search(r"approaching at \d+(:\d\d)? in [6-9]$", first[0]["text"]), first       # 78.2 / 90.5 s entries
    assert not [e for e in sp if 77.5 <= e["t"] <= 80.0]                                                       # (the 78.2 s phrase)


def test_review6_111_6_s_someone_moving_away_is_still_there_to_hear_about_3_s_earlier(review6):
    """The added 111.6 s "person moving away at 12:30 in 8" (track 2481, lateral 2.4-2.7 m, unknown motion): by the time it has two
    confirming frames inside the zone it is at 3.0 m, and the label gap (5 s) holds it behind the "person moving away at 12:15 in 9"
    of 108.5 s (track 2137). That one is spoken: someone is there, at the same place."""
    _, _, windows = review6
    sp = [e for e in _all(windows) if 106.0 <= e["t"] <= 114.0 and e["text"].startswith("person")]
    assert [e["text"] for e in sp] == ["person moving away at 12:15 in 9"] and 108.0 <= sp[0]["t"] <= 109.0


def test_review6_191_5_s_the_cyclist_is_announced_earlier_without_distance_and_without_beeps(review6):
    _, _, windows = review6
    sp = [e for e in _all(windows) if 188.0 <= e["t"] <= 192.0 and e["text"].startswith("cyclist")]
    assert len(sp) == 1 and sp[0]["text"] == "cyclist approaching at 11:45" and sp[0]["t"] < 191.4831 - 1.0      # 1.2 s earlier, 9.5 m
    assert not [b for b in _all(windows, "beeps") if 188.0 <= b["t"] <= 193.0]                                    # lateral 1.9 m: passing
    f = min(windows[0]["doc"]["frames"], key=lambda f: abs(f["t"] - 191.48))
    h = [h for h in f["hazards"] if h["trackId"] == sp[0]["trackId"]][0]
    assert abs(h["lateralM"]) > 1.5 and h["closingMps"] > 5.0


def test_review6_374_0_s_the_person_is_no_longer_standing(review6):
    _, _, windows = review6
    assert not [e for e in _all(windows) if "standing" in e["text"] and 365.0 <= e["t"] <= 380.0]
    frames = windows[0]["doc"]["frames"]
    tid = [b for b in _all(windows, "soft") if abs(b["t"] - 376.001) <= 1.0][0]["trackId"]                     # (11195 before v26.1.16: ids shift)
    states = [(f["t"], h["moving"]) for f in frames for h in f["hazards"] if h["trackId"] == tid and 373.0 <= f["t"] <= 377.0]
    assert states and all(m is not False for _, m in states)                  # never "standing"; "approaching" once the median has caught up
    assert [m for t, m in states if t >= 375.6] and all(m is True for t, m in states if t >= 375.6)
    assert not [b for b in _all(windows, "beeps") if 374.0 <= b["t"] <= 378.0]                # 376.0 s: not on a collision course


def test_review6_445_3_s_the_cyclist_comes_earlier_and_at_its_real_clock_position(review6):
    meta, _, windows = review6
    sp = [e for e in _all(windows) if 440.0 <= e["t"] <= 447.0 and e["text"].startswith("cyclist")]
    assert [e["text"] for e in sp] == ["cyclist approaching at 12"] and sp[0]["t"] <= 445.3203 - 1.5            # 13358: 13.6 m, 18 steps
    bp = [b for b in _all(windows, "beeps") if 445.0 <= b["t"] <= 446.5]
    assert len(bp) == 1 and bp[0]["label"] == "cyclist" and bp[0]["clockText"] == "11:45"       # ticked 445.65 s: kept (lateral -0.6 m)
    f = min(windows[0]["doc"]["frames"], key=lambda f: abs(f["t"] - 445.32))
    h = [h for h in f["hazards"] if h["trackId"] == bp[0]["trackId"]][0]                       # (13381 in the run; ids shift with the 0.3 % depth rounding)
    assert h["clockText"] == "11:45" and h["lateralM"] == pytest.approx(-0.57, abs=0.1)         # was "12": the wheel's inner edge, not the body (x 0.45)


def test_review6_the_context_entries_beside_the_path(review6):
    meta, _, windows = review6
    for t in (132.3407, 179.5128):
        assert not _produced(meta, windows, _ann6(meta, t, verdict="remove")[0]), t
    assert _produced(meta, windows, _ann6(meta, 59.1842, verdict="correct")[0])           # 2.9 m but 2.6 steps away
    assert not _produced(meta, windows, _ann6(meta, 448.9907, verdict="correct")[0])      # 2.9 m at 3.8 steps: the price of the rule


def test_review6_no_person_phrase_under_5_steps_and_every_phrase_of_a_person_has_the_distance(review6):
    _, _, windows = review6
    for e in _all(windows):
        if re.match(r"(person|animal)\b", e["text"]):
            m = re.search(r" in (\d+)$", e["text"])
            assert m and 5 <= int(m.group(1)) <= 10, e
        if re.match(r"(cyclist|vehicle) approaching", e["text"]):
            assert not re.search(r" in \d", e["text"]), e


def test_review6_beeps_only_on_a_real_collision_course(review6):
    _, _, windows = review6
    frames = {f["t"]: {h["trackId"]: h for h in f["hazards"]} for f in windows[0]["doc"]["frames"]}
    for tone in windows[0]["tones"]:
        t0 = max(t for t in frames if t <= tone["t"] + 1e-9)
        h = frames[t0].get(tone["trackId"])
        assert h is None or (abs(h["lateralM"]) <= ROLES["beepLateralM"] + 0.2 and h["stepsTo"] <= 5.5), (tone, h)


def test_review6_ticks_that_stay_and_ticks_that_moved_on_purpose(review6):
    meta, _, windows = review6
    ticks = [a for a in meta["annotations"] if a.get("verdict") == "correct"]
    assert len(ticks) == 36
    produced = [a for a in ticks if _produced(meta, windows, a)]
    lost = sorted((round(a["t"], 1), a["event"]["text"]) for a in ticks if not _produced(meta, windows, a))
    assert len(produced) >= 22, lost
    # lost on purpose: the beeps at 1.7-2.6 m (decision 3), phrases under 5 steps (decision 1), the two cyclists (earlier, other
    # clock), 48.5 "person at 12:45 in 5" (lateral 2.6-2.8 m around the zone limit), 292.7 (moved to 291.0 "moving away"), the
    # 2.9 m obstacle (decision 4) and the thin notice of 357 s in the crowd
    # (v26.1.13 follow-up: the soft proximity sound brings back the 90.5 and 92.1 s person beeps with the same clock; 78.2 and
    # 91.1 s are produced at another clock (1 / 1:15 against the ticked 1:30), see ``tests/test_collision_proximity.py``)
    assert lost == [(48.5, "person at 12:45 in 5"), (48.8, "beeps \u00b7 person at 12:30 \u00b7 5\u21924 steps"),
                    (78.2, "beeps \u00b7 person at 1:30 \u00b7 4\u21922 steps"),
                    (91.1, "beeps \u00b7 person at 1:30 \u00b7 4\u21922 steps"),
                    (191.5, "cyclist approaching at 11"), (292.7, "person standing at 12:15 in 8"),
                    (352.7, "person moving away at 12"),
                    (366.5, "beeps \u00b7 person at 1:45 \u00b7 3\u21922 steps"),
                    (366.5, "person at 1:15 in 3"), (445.3, "cyclist approaching at 12"),
                    (449.0, "obstacle at 1:15 in 4")], lost
    # (v26.1.16: the pole of 357 s - named as a feature, then called a danger - is produced again)
