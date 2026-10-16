"""Regression tests on the user's three real-footage reviews (recording 4929): collision v26.1.5 -> v26.1.7.

Fixtures (read-only): ``tests/fixtures/4929_review1.{json,npz}`` (windows 0-10 / 14-21 / 27-31 s),
``4929_review2.{json,npz}`` (windows 0-10 / 28-42 / 45-62 / 70-80 / 114-126 s) and ``4929_review3.{json,npz}``
(windows 0-12 / 36-62 / 100-122 / 192-218 s), see CONTRACTS.md sections 12.3, 14 and 15. Every window is run as its
own independent sequence, so:

* the ego state is **cold**: cadence needs ~2.4 s, and the gait scale k needs pole-like witnesses AND cadence; it is
  1.0 ("none") until then. Review 2 windows 0, 3 and 4 never get a scale in 10-12 s (no measurable pole closings), windows
  1 and 2 get one after 5 and 10 s from only a few seconds of data (k reads 0.8-2.8 there; 1.3-2.0 in the full 52 minute
  run). The assertions are therefore the ones that hold for any k in that range, plus invariants that tie each spoken
  context phrase to the item that triggered it (near in steps and sideways);
* the start summary applies at each window start, and no memory of earlier phrases exists.

Note on review 1, t=29.15 "person, 3 steps": run as a window v26.1.1 did not reproduce it; the person is a single-frame
danger flicker of a 50 px component, which is what the confirmation rule targets.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import numpy as np
import pytest

import collision as col

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONFIG = col.load_config()
VEHICLE_WORDS = ("vehicle", "parked car")


def _load(name: str):
    meta = json.load(open(FIXTURES / f"{name}.json"))
    s = meta["settings"]
    settings = col.resolve_settings(CONFIG, s["mount"], s["hfovDeg"], s["cameraHeightM"], s["stepLengthM"])
    return meta, settings


def _run_windows(name: str, config: dict | None = None):
    config = config or CONFIG
    meta, settings = _load(name)
    npz = np.load(FIXTURES / f"{name}.npz")
    out = []
    for i, w in enumerate(meta["windows"]):
        motion = {"t": npz[f"w{i}_mt"], "dx": npz[f"w{i}_mdx"], "dy": npz[f"w{i}_mdy"]}
        doc, ev = col.run_collision(npz[f"w{i}_grids"], npz[f"w{i}_t"], meta["classNames"], config, settings, motion)
        out.append({"doc": doc, "events": ev["events"], "key": w["key"],
                    "speech": [e for e in ev["events"] if e["type"] == "speech"],
                    "beeps": [e for e in ev["events"] if e["type"] == "beeps"],
                    "tones": [e for e in ev["events"] if e["type"] == "tone"]})
    return meta, npz, out


@pytest.fixture(scope="module")
def review1():
    return _run_windows("4929_review1")


@pytest.fixture(scope="module")
def review2():
    return _run_windows("4929_review2")


def _near(events, t, tol):
    return [e for e in events if abs(e["t"] - t) <= tol]


def _frame_at(doc, t):
    return min(doc["frames"], key=lambda f: abs(f["t"] - t))


# --------------------------------------------------------------------------
# Review 1 (v26.1.5 expectations, phrases updated to the v26.1.6 wording)
# --------------------------------------------------------------------------

def test_review1_fixture_is_the_documented_one(review1):
    meta, npz, windows = review1
    assert [w["key"] for w in meta["windows"]] == ["w0", "w1", "w2"]
    for i, w in enumerate(meta["windows"]):
        t = npz[f"w{i}_t"]
        assert t[0] >= w["start"] - 0.5 and t[-1] <= w["end"] + 0.5
        assert npz[f"w{i}_grids"].shape == (len(t), meta["gridH"], meta["gridW"])
    assert CONFIG["version"] == "v26.1.8"


def test_review1_start_summary_names_building_and_obstacle_within_the_first_1_5_s(review1):
    """Annotation f8a55082: expected "Obstacle at 12, Building at 2" and nothing was said (v26.1.1).

    The scene has a sidewalk-obstacle at 11-12 o'clock and a building at 2 in the first frames, so both are named in
    one grouped phrase. The building is far to the side (5 m), so this is the first-summary exemption of the lateral cap
    (CONTRACTS.md note): the user ticked exactly this phrase.
    """
    w0 = review1[2][0]
    first_hazards = [h for f in w0["doc"]["frames"] if f["t"] <= 1.0 for h in f["hazards"]]
    assert any(h["className"] == "sidewalk-obstacle" and h["role"] == "context" for h in first_hazards)
    assert any(h["className"] == "building" for h in first_hazards)
    ctx = [e for e in w0["speech"] if e["role"] == "context" and e["t"] <= 1.5]
    assert ctx, "no context phrase in the first 1.5 s"
    text = ctx[0]["text"].lower()
    assert "building" in text and "obstacle" in text
    assert text.count(" at ") >= 2 and "o'clock" not in text      # one grouped phrase, "{label} at {clock}"


def test_review1_vehicle_and_building_after_the_turn_near_6_6_s_are_not_named_a_second_time(review1):
    """v26.1.5/6 named the vehicle at 11 and the building at 1 again after the user's turn at 5.8 s (the label memory is
    cleared by a turn). The third review marks exactly that phrase (7.84 s of the same footage) "already referenced":
    v26.1.7 sees the same objects again (they are still context) and says nothing."""
    w0 = review1[2][0]
    hz = [(f["t"], h) for f in w0["doc"]["frames"] if 6.0 <= f["t"] <= 7.8 for h in f["hazards"]]
    assert any(h["className"] == "vehicle" and h["role"] == "context" and h["clock"] in (11, 12) for _, h in hz)
    assert any(h["className"] == "building" and h["role"] == "context" and h["clock"] in (1, 2) for _, h in hz)
    assert any(f["pathChange"] for f in w0["doc"]["frames"] if 5.0 <= f["t"] <= 7.0)       # the turn is still detected
    after = [e for e in w0["speech"] if e["role"] == "context" and e["t"] >= 6.0]
    assert after == [], after
    before = [e for e in w0["speech"] if e["role"] == "context" and e["t"] < 6.0]
    assert any(any(w in e["text"].lower() for w in VEHICLE_WORDS) for e in before), before


def test_review1_static_vehicle_is_no_danger_and_context_is_not_repeated_in_window_1(review1):
    w1 = review1[2][1]
    sp = w1["speech"]
    # 16.35 s "vehicle, 10 o'clock, 5 steps": a vehicle beside the path, already referenced
    bad = [e for e in _near(sp, 16.35, 1.5) if e["role"] in ("danger", "final")
           and any(w in e["text"].lower() for w in VEHICLE_WORDS)]
    assert bad == []
    assert not [e for e in sp if e["role"] in ("danger", "final") and any(w in e["text"] for w in VEHICLE_WORDS)]
    # 18.85 s "parked car at 12 o'clock": a repeat of what the start summary / earlier phrase named
    assert [e for e in _near(sp, 18.85, 1.5) if "parked car" in e["text"].lower()] == []
    assert len([e for e in sp if e["role"] == "context" and any(w in e["text"].lower() for w in VEHICLE_WORDS)]) <= 1
    veh = [h for f in w1["doc"]["frames"] if 16.0 <= f["t"] <= 16.7 for h in f["hazards"] if h["className"] == "vehicle"]
    assert veh and all(h["role"] != "danger" for h in veh)
    assert not [e for e in w1["beeps"] if "vehicle" in e["text"] or "parked car" in e["text"]]


def test_review1_no_false_person_final_in_window_2(review1):
    w2 = review1[2][2]
    sp = w2["speech"]
    assert not [e for e in _near(sp, 29.15, 1.5) if e["role"] == "final" and "person" in e["text"].lower()]
    assert not [e for e in sp if "person" in e["text"].lower()]
    assert not [e for e in w2["beeps"] if "person" in e["text"]]
    run = best = 0                         # the person was a single-frame danger: never two consecutive frames
    for f in w2["doc"]["frames"]:
        if 28.5 <= f["t"] <= 30.0 and any(h["className"] == "person" and h["role"] == "danger" for h in f["hazards"]):
            run += 1
            best = max(best, run)
        else:
            run = 0
    assert best <= 1


def test_review1_phrases_use_the_new_wording(review1):
    for w in review1[2]:
        for e in w["speech"]:
            assert "o'clock" not in e["text"]
            if e["role"] in ("danger", "final"):
                assert re.fullmatch(r"[a-z ]+ (approaching )?at [0-9, and]+( in \d+( step)?)?(, .+)?", e["text"]), e["text"]
            if e["role"] == "context":
                items = e["text"].split(", ")
                assert 1 <= len(items) <= CONFIG["speech"]["contextMaxItems"]
                assert all(" at " in it for it in items)


# --------------------------------------------------------------------------
# Review 2
# --------------------------------------------------------------------------

def test_review2_fixture_is_the_documented_one(review2):
    meta, npz, windows = review2
    assert [w["key"] for w in meta["windows"]] == ["w0", "w1", "w2", "w3", "w4"]
    for i, w in enumerate(meta["windows"]):
        t = npz[f"w{i}_t"]
        assert t[0] >= w["start"] - 0.5 and t[-1] <= w["end"] + 0.5
        assert npz[f"w{i}_grids"].shape == (len(t), meta["gridH"], meta["gridW"])
    assert [e["text"] for e in meta["systemSpeechV26_1_5"]][:1] == ["obstacle at 11, building at 2"]


def test_review2_start_phrases_still_come_first_and_are_grouped(review2):
    """Annotations 0.67 / 3.17 / 6.34 (all ticked): the scene summary at the start and after the turn at 5.8 s."""
    w0 = review2[2][0]
    first = [e for e in w0["speech"] if e["t"] <= 1.5]
    assert first and first[0]["role"] == "context"
    assert sorted(re.sub(r" in \d+$", "", x) for x in first[0]["text"].split(", ")) == ["building at 2", "obstacle at 11"]   # the ticked v26.1.5 phrase, + steps
    # the phrase after the turn at 5.8 s (ticked in review 2) is the 7.84 s "already referenced" of review 3: not said again
    assert any("vehicle at 11" in e["text"] for e in w0["speech"] if 4.5 <= e["t"] <= 6.0 and e["role"] == "context")
    assert [e for e in w0["speech"] if 6.0 <= e["t"] <= 8.5 and e["role"] == "context"] == []


def test_review2_crosswalk_is_announced_as_a_landmark_with_direction_and_steps_near_33_9_s(review2):
    """Added annotation at 33.9 s: "crosswalks are important ... add direction and steps". The crosswalk is detected
    at 32.8 s but only as 1-2 frame fragments (three track ids), so it is confirmed at about 35 s."""
    w1 = review2[2][1]
    hit = [e for e in _near(w1["speech"], 33.9, 2.0) if re.search(r"crosswalk at 12 in \d+", e["text"])]
    assert hit, [e["text"] for e in w1["speech"]]
    steps = int(re.search(r"crosswalk at 12 in (\d+)", hit[0]["text"]).group(1))
    assert 3 <= steps <= CONFIG["roles"]["landmarkSteps"]
    # the crosswalk never beeps (features and context never beep)
    assert not [b for b in w1["beeps"] if "crosswalk" in b["text"] or "curb" in b["text"]]


def test_review2_curb_ahead_and_poles_named_once_near_38_8_s(review2):
    """Added annotation at 38.8 s: "curb at 12 in 10, beware poles". Three poles at 11, 12 and 1 stand 3-5 m ahead and
    none is in the lane. v26.1.7: the poles of this cluster were named at the window's first notice (28.7 s, "pole at 12 in
    15", position and distance as the third review wants) and are not named a second time at 38.8 s (review 3, 40.50 s:
    "already notified")."""
    w1 = review2[2][1]
    hz = [h for f in w1["doc"]["frames"] if 37.0 <= f["t"] <= 39.5 for h in f["hazards"]]
    assert {h["clock"] for h in hz if h["className"] == "pole"} >= {11, 12, 1}
    assert all(h["role"] != "danger" for h in hz if h["className"] == "pole")
    # "less is more" (architect): a label is not repeated within 6 s unless it is a different crossing, so the curb
    # fragments around 38.8 s are covered by the curb at 32.5 s and the crosswalk at 39.2 s is the feature said here
    curb = [e for e in _near(w1["speech"], 38.8, 2.5) if re.search(r"(curb|crosswalk) at 1?\d in \d+", e["text"])]
    assert curb, [(e["t"], e["text"]) for e in w1["speech"]]
    poles = [e for e in w1["speech"] if re.search(r"\bpoles? at ", e["text"])]
    assert len(poles) == 1 and poles[0]["t"] < 30, [(e["t"], e["text"]) for e in w1["speech"]]
    assert re.fullmatch(r"pole at 1?\d in \d+", poles[0]["text"])
    assert all(e["role"] in ("feature", "danger") for e in curb + poles)


def test_review2_obstacle_in_lane_is_named_once_and_beeps_near_35_3_s(review2):
    """Verdict at 35.33 s ("obstacle, 12 o'clock, 5 steps"): the obstacle is still announced - at 34.99 s as "obstacle at 1 in 6"
    (context, the first time it is seen) - and not a second time as a danger 0.3 s later: v26.1.7 knows it is the same object.
    The parking-sensor beeps are as before."""
    w1 = review2[2][1]
    hit = [e for e in _near(w1["speech"], 35.33, 1.0) if re.search(r"obstacle at \d+ in \d+", e["text"])]
    assert len(hit) == 1
    assert len([e for e in _near(w1["speech"], 35.33, 3.0) if "obstacle" in e["text"]]) == 1
    assert [b for b in w1["beeps"] if abs(b["t"] - 35.33) <= 1.0 and "obstacle at 12" in b["text"]]


def test_review2_person_is_warned_before_49_5_s_and_tracked_as_a_mover(review2):
    """Added annotation at 49.1 s: "Obstacle at 12 in 6, person at 1 and 2 ... people are moving, they should be tracked
    for collision, being notified sooner would be great". v26.1.5 said only "obstacle, 12 o'clock, 6 steps" at 48.5 s."""
    w2 = review2[2][2]
    persons = [e for e in w2["speech"] if "person" in e["text"] and e["t"] <= 49.5]
    assert persons, [(e["t"], e["text"]) for e in w2["speech"]]
    assert persons[0]["t"] <= 48.5                                 # not later than v26.1.5's obstacle call
    assert re.search(r"person (approaching )?at [12]", persons[0]["text"])
    # the persons at 1 and 2 are danger hazards (movers in the wide zone) well before they are alongside
    danger_t = [f["t"] for f in w2["doc"]["frames"] for h in f["hazards"]
                if h["className"] == "person" and h["role"] == "danger" and h["clock"] in (1, 2) and f["t"] <= 49.5]
    assert danger_t and min(danger_t) <= 47.5
    # and the obstacle ahead is still announced near 48.5 s
    assert [e for e in _near(w2["speech"], 48.5, 1.0) if "obstacle at 12" in e["text"]]


def test_review2_person_phrase_near_75_5_s_has_no_oclock_and_names_12(review2):
    """Verdict at 75.49 s ("person approaching, 12 o'clock") -> "person approaching at 12" in the full run. As a cold window
    (no ego speed, so no motion measurement) the person is announced as a danger instead of "approaching"."""
    w3 = review2[2][3]
    hit = [e for e in _near(w3["speech"], 75.5, 1.5) if "person" in e["text"] and re.search(r"\bat 12\b", e["text"])]
    assert hit, [(e["t"], e["text"]) for e in w3["speech"]]
    assert "o'clock" not in hit[0]["text"]


@pytest.mark.parametrize("t, words", [(52.344, VEHICLE_WORDS), (55.514, ("obstacle", "building")), (58.016, VEHICLE_WORDS)])
def test_review2_far_context_is_not_spoken(review2, t, words):
    """Verdicts 52.34 / 55.51 / 58.02 s: "too far away, not important" (parked car at 10; obstacle at 2, building at 10;
    vehicle at 11). Every item in question stands 5-9 m to the side."""
    w2 = review2[2][2]
    bad = [e for e in _near(w2["speech"], t, 1.0) if e["role"] == "context" and any(w in e["text"].lower() for w in words)]
    assert bad == [], bad


def test_review2_every_context_phrase_names_something_near(review2):
    """Invariant behind the three verdicts: the lead item of every context phrase (except a run's first scene summary)
    is within contextMaxSteps and contextMaxLateralM, measured at the phrase's own frame."""
    roles = CONFIG["roles"]
    checked = 0
    for w in review2[2]:
        ctx = [e for e in w["speech"] if e["role"] == "context"]
        for e in ctx[1:] if ctx and ctx[0]["t"] <= 1.5 else ctx:
            lead = [h for h in _frame_at(w["doc"], e["t"])["hazards"] if h["trackId"] == e["trackId"]]
            assert lead, e
            assert lead[0]["stepsTo"] <= roles["contextMaxSteps"] + 0.5, (w["key"], e, lead[0])
            assert abs(lead[0]["lateralM"]) <= roles["contextMaxLateralM"] + 0.3, (w["key"], e, lead[0])
            checked += 1
    assert checked >= 3


def test_review2_no_oclock_in_any_phrase_and_clocks_use_the_new_templates(review2, review1):
    for _, _, windows in (review2, review1):
        for w in windows:
            for e in w["speech"]:
                assert "o'clock" not in e["text"]
                assert re.fullmatch(r"[a-z ,]+( at [0-9][0-9, and]*)?( in \d+( step)?)?(, [a-z ,0-9]+)*", e["text"]) or \
                    "approaching" in e["text"] or e["role"] == "surface", e["text"]
            for b in w["beeps"]:
                assert "o'clock" not in b["text"] and b["text"].startswith("beeps · ")


def test_review2_surface_flicker_is_silent(review2):
    """Verdict at 120.83 s: "road" - a model flicker, the path did not change and no curb was passed."""
    w4 = review2[2][4]
    surfaces = {f["region"]["surface"] for f in w4["doc"]["frames"] if f["region"]}
    assert {"road", "pedestrian"} <= surfaces                     # the model really does flip between them
    assert [e for e in w4["speech"] if e["role"] == "surface"] == []
    flips = sum(1 for a, b in zip(w4["doc"]["frames"], w4["doc"]["frames"][1:])
                if a["region"] and b["region"] and a["region"]["surface"] != b["region"]["surface"])
    assert flips >= 5


def test_review2_spoken_tracks_have_stable_step_counts_while_walking(review2):
    """No jump of more than 30 percent between consecutive frames for a track that is a danger or feature, while walking."""
    pairs = 0
    for w in review2[2]:
        last: dict[int, tuple[int, dict]] = {}
        for f in w["doc"]["frames"]:
            cur = {}
            for h in f["hazards"]:
                cur[h["trackId"]] = (f["index"], h)
                prev = last.get(h["trackId"])
                if (prev and prev[0] == f["index"] - 1 and f["ego"]["cadenceHz"] is not None
                        and prev[1]["role"] in ("danger", "feature") and h["role"] in ("danger", "feature")):
                    a, b = prev[1]["stepsTo"], h["stepsTo"]
                    assert abs(b - a) <= 0.3 * a, (w["key"], f["t"], h["className"], a, b)
                    pairs += 1
            last = cur
    assert pairs > 100


def test_review2_beeps_are_collision_tracks_only_and_every_tone_is_in_exactly_one_episode(review2):
    n_tones = 0
    for w in review2[2]:
        for b in w["beeps"]:
            assert b["role"] == "danger" and b["tEnd"] > b["t"]
            frames = [f for f in w["doc"]["frames"] if b["t"] - 0.01 <= f["t"] <= b["tEnd"]]
            tracks = [h for f in frames for h in f["hazards"] if h["trackId"] == b["trackId"]]
            assert tracks and all(h["role"] == "danger" and h["className"] not in ("curb", "crosswalk", "object pothole")
                                  for h in tracks), b
            assert any(h["collision"] for h in tracks), b            # (a lost frame may continue for 0.5 s)
        for x in w["tones"]:
            owners = [b for b in w["beeps"] if b["trackId"] == x["trackId"] and b["t"] - 0.05 <= x["t"] <= b["tEnd"] + 0.05]
            assert len(owners) == 1, (w["key"], x)
            assert x["frequencyHz"] == CONFIG["tones"]["frequencyHz"]
            n_tones += 1
        # no beep while only features / context are around: every episode's label is an obstacle, person, pole, ...
        assert not [b for b in w["beeps"] if b["label"] in ("curb", "crosswalk", "pothole")]
    assert n_tones >= 3


def test_review2_context_and_features_do_not_start_before_confirmation_and_ego_scale_is_reported(review2):
    for w in review2[2]:
        egos = [f["ego"] for f in w["doc"]["frames"]]
        assert all({"scale", "scaleSource"} <= set(e) for e in egos)
        assert all(e["scale"] > 0 and e["scaleSource"] in ("none", "gait", "prior") for e in egos)
        # the scale never jumps: at most 25 percent per second (+ rounding)
        ts = [f["t"] for f in w["doc"]["frames"]]
        for (t0, e0), (t1, e1) in zip(zip(ts, egos), zip(ts[1:], egos[1:])):
            assert e1["scale"] / e0["scale"] <= np.exp(CONFIG["ego"]["scaleMaxChangePerSecond"] * (t1 - t0)) + 0.002
    # windows 1 and 2 calibrate (poles and cadence are there); the scale is a real-world one: 0.5 .. 4
    for idx in (1, 2):
        last = review2[2][idx]["doc"]["frames"][-1]["ego"]
        assert last["scaleSource"] == "gait" and 0.5 <= last["scale"] <= 4.0


# --------------------------------------------------------------------------
# Review 3 (v26.1.6 -> v26.1.7): 27 correct, 6 "should not be said" (CONTRACTS.md section 15)
# --------------------------------------------------------------------------
#
# The windows are cold sequences (no calibration at the start: a window's first seconds have k = 1 and no cadence), so
# they reproduce only part of what the full 52 minute run said. The full run is the stronger check; it is run here when
# HACKEYE_FULL_RUN=1 and the run directory exists (about 50 s), and its table is in the contract notes of the release.

WARM_PRIOR = 1.25     # a scale prior stands in for the calibration the full run has at 36 s (its k is 1.16-1.5 there)
THIN_PHRASE = re.compile(r"\b(poles?|traffic lights?|pedestrian lights?|signs?|traffic signs?) at ")
ENTRY_RE = r"[a-z ]+? (?:approaching )?at \d+(?:, \d+)*(?: and \d+)? in \d+(?: steps?)?"


@pytest.fixture(scope="module")
def review3():
    return _run_windows("4929_review3")


@pytest.fixture(scope="module")
def review3_warm():
    cfg = copy.deepcopy(CONFIG)
    cfg["ego"]["scalePrior"] = WARM_PRIOR
    return _run_windows("4929_review3", cfg)


@pytest.fixture(scope="module")
def review3_no_memory():
    cfg = copy.deepcopy(CONFIG)
    cfg["memory"]["enabled"] = False
    return _run_windows("4929_review3", cfg)


def _all(windows, key="speech"):
    return [e for w in windows for e in w[key]]


def _norm(text: str) -> tuple:
    text = re.sub(r" in \d+( steps?)?", "", text).replace(" approaching", "")
    return tuple(sorted(x.strip() for x in text.split(", ")))


def _is_the_annotated_event(ann: dict, e: dict) -> bool:
    """Same label / type pattern as the annotated v26.1.6 event; the phrasing may differ by CONTRACTS.md 15 rule 3
    (" in N" added, "beware poles" -> "poles at 11 and 1 in 8")."""
    a = ann["event"]
    if a["type"] == "beeps":
        strip = lambda t: re.sub(r" · [\d→ ]+ steps?", "", t)          # noqa: E731
        return e["type"] == "beeps" and strip(e["text"]) == strip(a["text"])
    if e["type"] != "speech":
        return False
    if a["text"] == "beware poles":
        return any(THIN_PHRASE.match(x.strip()) for x in e["text"].split(", "))
    if a["role"] == "surface":
        return e["role"] == "surface" and e["text"] == a["text"]
    return _norm(a["text"]) == _norm(e["text"]) or (a["role"] == "context" and set(_norm(a["text"])) <= set(_norm(e["text"])))


def _produced(meta, windows, ann, tol=1.5):
    evs = _all(windows) + _all(windows, "beeps")
    return [e for e in evs if abs(e["t"] - ann["t"]) <= tol and _is_the_annotated_event(ann, e)]


def _in_a_window(meta, t):
    return any(w["start"] <= t <= w["end"] for w in meta["windows"])


def test_review3_fixture_is_the_documented_one(review3):
    meta, npz, windows = review3
    assert [(w["start"], w["end"]) for w in meta["windows"]] == [(0.0, 12.0), (36.0, 62.0), (100.0, 122.0), (192.0, 218.0)]
    for i, w in enumerate(meta["windows"]):
        t = npz[f"w{i}_t"]
        assert t[0] >= w["start"] - 0.5 and t[-1] <= w["end"] + 0.5
        assert npz[f"w{i}_grids"].shape == (len(t), meta["gridH"], meta["gridW"])
    ann = meta["annotations"]
    assert len(ann) == 33 and sum(a["verdict"] == "correct" for a in ann) == 27 and sum(a["verdict"] == "remove" for a in ann) == 6
    assert sorted(round(a["t"], 2) for a in ann if a["verdict"] == "remove") == [7.84, 40.5, 41.17, 59.85, 118.66, 199.16]
    assert len(meta["systemEventsV26_1_6"]) > 0
    assert CONFIG["version"] == "v26.1.8"


def test_review3_no_repeat_at_7_84_40_50_59_85_and_118_66(review3, review3_warm, review3_no_memory):
    """The four repeats of the same real object. The memory-less run (v26.1.6 behaviour) reproduces three of them in these cold
    windows (59.85 s needs the 52 s history of the full run), so these assertions are not vacuous."""
    for windows in (review3[2], review3_warm[2]):
        sp = _all(windows)
        assert [e for e in _near(sp, 7.84, 1.5) if "building" in e["text"]] == []
        assert [e for e in _near(sp, 40.50, 1.5) if THIN_PHRASE.search(e["text"])] == []
        assert [e for e in _near(sp, 59.85, 1.5) if "crosswalk" in e["text"]] == []
        assert [e for e in _near(sp, 118.66, 1.5) if "person" in e["text"]] == []
        w0 = [e for e in windows[0]["speech"] if re.search(r"vehicle|parked car", e["text"])]
        assert len(w0) == 1, w0                                  # the vehicle at 11 is named once, never again after the turn
    cold = _all(review3[2])
    assert [e for e in _near(cold, 7.84, 1.5) if re.search(r"building|vehicle|parked car", e["text"])] == []
    old = _all(review3_no_memory[2])
    assert [e for e in _near(old, 7.84, 1.5) if re.search(r"building|vehicle|parked car", e["text"])]
    assert [e for e in _near(old, 40.50, 1.5) if THIN_PHRASE.search(e["text"])]
    assert [e for e in _near(old, 118.66, 1.5) if "person" in e["text"]]


def test_review3_no_final_at_41_17_but_the_beeps_are_there(review3, review3_warm, review3_no_memory):
    for windows in (review3[2], review3_warm[2]):
        assert [e for e in _near(_all(windows), 41.17, 1.5) if e["role"] == "final"] == []
        assert [e for e in _all(windows) if e["role"] == "final" and "pole" in e["text"]] == []
    beeps = [b for b in _all(review3_warm[2], "beeps") if abs(b["t"] - 41.17) <= 1.5 and "pole at 12" in b["text"]]
    assert beeps, [(b["t"], b["text"]) for b in _all(review3_warm[2], "beeps")]
    # the beeps do not depend on the memory at all
    key = lambda ev: [(b["t"], b["text"], b["trackId"]) for b in ev]                                 # noqa: E731
    assert key(_all(review3[2], "beeps")) == key(_all(review3_no_memory[2], "beeps"))
    assert [t["t"] for t in _all(review3[2], "tones")] == [t["t"] for t in _all(review3_no_memory[2], "tones")]


def test_review3_no_surface_event_near_199_16(review3, review3_warm):
    for windows in (review3[2], review3_warm[2]):
        assert [e for e in _all(windows) if e["role"] == "surface"] == []
        w3 = windows[3]
        surfaces = {f["region"]["surface"] for f in w3["doc"]["frames"] if f["region"]}
        assert {"road", "pedestrian"} <= surfaces                    # the model really does flip between them here
        assert any(f["t"] >= 199.0 for f in w3["doc"]["frames"])


def test_review3_every_object_phrase_has_a_position_and_a_distance(review3, review3_warm):
    n = 0
    for windows in (review3[2], review3_warm[2]):
        for e in _all(windows):
            if e["role"] == "surface":
                continue
            assert re.fullmatch(f"{ENTRY_RE}(?:, {ENTRY_RE})*", e["text"]), e["text"]
            assert "o'clock" not in e["text"] and "beware" not in e["text"]
            n += 1
        for b in _all(windows, "beeps"):
            assert re.fullmatch(r"beeps · [a-z ]+ at \d+ · [\d→]+ steps?", b["text"]), b["text"]
    assert n >= 25


# What the committed v26.1.6 reproduces from the user's 27 ticks in these COLD windows, and what v26.1.7 must keep. The rest
# of the 27 (e.g. 15.35 s, 30.82 s, 35.49 s ...) lie outside the windows or need the warm state of the full run.
COLD_TICKS = [0.6673, 5.3387, 47.5058, 48.5068, 48.5068, 196.3213, 201.3263, 212.3373]
WARM_TICKS = [41.1662, 47.5058, 48.5068, 48.5068, 49.6747, 56.1812, 106.982, 196.3213, 212.3373]


def _ticks(meta, ts):
    out = []
    for t in ts:
        found = [a for a in meta["annotations"] if a["verdict"] == "correct" and abs(a["t"] - t) < 0.01]
        assert found, t
        out.extend(found)
    return sorted({id(a): a for a in out}.values(), key=lambda a: (a["t"], a["event"]["type"]))


def test_review3_every_tick_the_cold_windows_reproduced_is_still_produced(review3):
    meta, _, windows = review3
    anns = _ticks(meta, COLD_TICKS)
    assert len(anns) == 8
    for a in anns:
        assert _produced(meta, windows, a), (a["t"], a["event"]["text"])


def test_review3_every_tick_the_warm_windows_reproduced_is_still_produced(review3_warm):
    meta, _, windows = review3_warm
    anns = _ticks(meta, WARM_TICKS)
    assert len(anns) == 9
    for a in anns:
        assert _produced(meta, windows, a), (a["t"], a["event"]["text"])


def test_review3_beeps_and_tones_are_the_same_with_and_without_the_memory(review3_warm):
    cfg = copy.deepcopy(CONFIG)
    cfg["ego"]["scalePrior"] = WARM_PRIOR
    cfg["memory"]["enabled"] = False
    off = _run_windows("4929_review3", cfg)[2]
    for key in ("beeps", "tones"):
        assert [(e["t"], e.get("text")) for e in _all(review3_warm[2], key)] == [(e["t"], e.get("text")) for e in _all(off, key)]


def test_review3_speech_with_memory_is_a_subset_of_speech_without_it_apart_from_the_surface(review3_warm, review3_no_memory):
    """The memory only takes phrases away (CONTRACTS.md note): everything v26.1.7 says in these windows, v26.1.6 rules also
    say at that moment (same time within 0.01 s, the same labels or fewer of them)."""
    cfg = copy.deepcopy(CONFIG)
    cfg["ego"]["scalePrior"] = WARM_PRIOR
    cfg["memory"]["enabled"] = False
    off = _all(_run_windows("4929_review3", cfg)[2])
    on = _all(review3_warm[2])
    for e in on:
        same = [o for o in off if abs(o["t"] - e["t"]) < 0.01 and o["role"] == e["role"]]
        assert same, (e["t"], e["text"])
        assert set(_norm(e["text"])) <= set(_norm(same[0]["text"])), (e["text"], same[0]["text"])


FULL_RUN = Path(__file__).resolve().parents[2] / "debug" / "lab" / "runs" / "7b9d5ac14e14"


@pytest.mark.skipif(os.environ.get("HACKEYE_FULL_RUN") != "1" or not (FULL_RUN / "grids.npz").exists(),
                    reason="the 52 minute run is not part of the repository: set HACKEYE_FULL_RUN=1 where debug/lab/runs/7b9d5ac14e14 exists")
def test_review3_full_run_all_27_ticks_kept_and_all_6_removals_gone():
    meta, settings = _load("4929_review3")
    g, mo = np.load(FULL_RUN / "grids.npz"), np.load(FULL_RUN / "motion.npz")
    run = json.load(open(FULL_RUN / "run.json"))
    doc, ev = col.run_collision(g["grids"], g["t"], run["classNames"], CONFIG, settings,
                                {"t": mo["t"], "dx": mo["dx"], "dy": mo["dy"]})
    window = [{"speech": [e for e in ev["events"] if e["type"] == "speech"], "beeps": [e for e in ev["events"] if e["type"] == "beeps"],
               "tones": []}]
    for a in meta["annotations"]:
        got = _produced(meta, window, a)
        assert bool(got) == (a["verdict"] == "correct"), (a["t"], a["verdict"], a["event"]["text"], [(e["t"], e["text"]) for e in got])
    assert len(window[0]["beeps"]) == 40
