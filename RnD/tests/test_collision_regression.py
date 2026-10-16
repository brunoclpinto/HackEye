"""Regression tests on the user's two real-footage reviews (recording 4929): collision v26.1.5 -> v26.1.6.

Fixtures (read-only): ``tests/fixtures/4929_review1.{json,npz}`` (windows 0-10 / 14-21 / 27-31 s) and
``4929_review2.{json,npz}`` (windows 0-10 / 28-42 / 45-62 / 70-80 / 114-126 s), see CONTRACTS.md sections
12.3 and 14. Every window is run as its own independent sequence, so:

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

import json
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


def _run_windows(name: str):
    meta, settings = _load(name)
    npz = np.load(FIXTURES / f"{name}.npz")
    out = []
    for i, w in enumerate(meta["windows"]):
        motion = {"t": npz[f"w{i}_mt"], "dx": npz[f"w{i}_mdx"], "dy": npz[f"w{i}_mdy"]}
        doc, ev = col.run_collision(npz[f"w{i}_grids"], npz[f"w{i}_t"], meta["classNames"], CONFIG, settings, motion)
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
    assert CONFIG["version"] == "v26.1.6"


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


def test_review1_vehicle_and_building_context_after_the_turn_near_6_6_s(review1):
    """The user turned at 5.8 s, which clears the memory: the vehicle at 11 and the building at 1 are named again."""
    w0 = review1[2][0]
    hz = [(f["t"], h) for f in w0["doc"]["frames"] if 6.0 <= f["t"] <= 7.8 for h in f["hazards"]]
    assert any(h["className"] == "vehicle" and h["role"] == "context" and h["clock"] in (11, 12) for _, h in hz)
    assert any(h["className"] == "building" and h["role"] == "context" and h["clock"] in (1, 2) for _, h in hz)
    near = [e for e in _near(w0["speech"], 6.6, 2.0) if e["role"] == "context"]
    assert any(any(w in e["text"].lower() for w in VEHICLE_WORDS) for e in near), near
    assert any("building" in e["text"].lower() for e in near), near


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
    assert sorted(first[0]["text"].split(", ")) == ["building at 2", "obstacle at 11"]       # as the ticked v26.1.5 phrase
    after_turn = [e for e in w0["speech"] if 6.0 <= e["t"] <= 8.5 and e["role"] == "context"]
    assert after_turn and any("building" in e["text"] or "vehicle" in e["text"] for e in after_turn)


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


def test_review2_curb_ahead_and_beware_poles_near_38_8_s(review2):
    """Added annotation at 38.8 s: "curb at 12 in 10, beware poles". Three poles at 11, 12 and 1 stand 3-5 m ahead and
    none is in the lane."""
    w1 = review2[2][1]
    hz = [h for f in w1["doc"]["frames"] if 37.0 <= f["t"] <= 39.5 for h in f["hazards"]]
    assert {h["clock"] for h in hz if h["className"] == "pole"} >= {11, 12, 1}
    assert all(h["role"] != "danger" for h in hz if h["className"] == "pole")
    # "less is more" (architect): a label is not repeated within 6 s unless it is a different crossing, so the curb
    # fragments around 38.8 s are covered by the curb at 32.5 s and the crosswalk at 39.2 s is the feature said here
    curb = [e for e in _near(w1["speech"], 38.8, 2.5) if re.search(r"(curb|crosswalk) at 1?\d in \d+", e["text"])]
    poles = [e for e in _near(w1["speech"], 38.8, 2.0) if "beware poles" in e["text"]]
    assert curb, [(e["t"], e["text"]) for e in w1["speech"]]
    assert poles, [(e["t"], e["text"]) for e in w1["speech"]]
    assert all(e["role"] in ("feature", "danger") for e in curb + poles)


def test_review2_obstacle_in_lane_is_spoken_and_beeps_near_35_3_s(review2):
    """Verdict at 35.33 s ("obstacle, 12 o'clock, 5 steps"): still announced, now as "obstacle at 12 in N" with beeps."""
    w1 = review2[2][1]
    hit = [e for e in _near(w1["speech"], 35.33, 1.0) if re.search(r"obstacle at 12 in \d+", e["text"])]
    assert hit and hit[0]["role"] == "danger"
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
