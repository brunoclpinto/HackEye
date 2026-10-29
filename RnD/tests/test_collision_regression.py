"""Regression tests on the user's four real-footage reviews (recording 4929): collision v26.1.5 -> v26.1.11.

Fixtures (read-only): ``tests/fixtures/4929_review1.{json,npz}`` (windows 0-10 / 14-21 / 27-31 s),
``4929_review2.{json,npz}`` (windows 0-10 / 28-42 / 45-62 / 70-80 / 114-126 s) and ``4929_review3.{json,npz}``
(windows 0-12 / 36-62 / 100-122 / 192-218 s) and ``4929_review4.{json,npz}`` (windows 20-50 / 66-105 / 150-205 / 236-270 /
284-345 / 352-410 / 436-470 s, with the DA2 depth maps and the residual flow; v26.1.11), see CONTRACTS.md sections 12.3, 14 and 15. Every window is run as its
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
import re
from pathlib import Path

import numpy as np
import pytest

import collision as col

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONFIG = col.load_config()
# v26.2.2: these fixtures pin the user's ticks and the numbers of v26.1.x, which are the IMAGE rule's. The default config now judges wall-like
# classes on the map, bridges vanished movers (coast) and snaps items inside solid areas, which moves a few events in time (DECISIONS v26.2.2,
# known issues), so they run on the v26.2.0 rules; tests/test_collision_v2622.py and the golden hash pin the new default.
CONFIG["roles"]["staticSource"] = "image"
CONFIG["coast"]["enabled"] = False
# v26.2.3: the default object distance is "ground+depth"; the tests that pin v26.1.x / v26.2.0-2 numbers run on the plain depth distance
# (= v26.2.2), tests/test_collision_v2623.py pins the new default.
CONFIG["distance"]["objectDistance"] = "depth"
VEHICLE_WORDS = ("vehicle", "parked car")


def _load(name: str):
    meta = json.load(open(FIXTURES / f"{name}.json"))
    s = meta["settings"]
    settings = col.resolve_settings(
        CONFIG, s["mount"], s["hfovDeg"], s["cameraHeightM"], s["stepLengthM"], projection=s.get("projection"),
        distance_source=s.get("distanceSource", "ground"), user_height_m=s.get("userHeightM"),
        camera_location=s.get("cameraLocation"), camera_side=s.get("cameraSide"))
    return meta, settings


def _run_windows(name: str, config: dict | None = None):
    """Every window of a fixture as an independent run. Fixtures with ``wN_depth`` (review 4) also feed the depth maps."""
    config = config or CONFIG
    meta, settings = _load(name)
    npz = np.load(FIXTURES / f"{name}.npz")
    out = []
    for i, w in enumerate(meta["windows"]):
        motion = {"t": npz[f"w{i}_mt"], "dx": npz[f"w{i}_mdx"], "dy": npz[f"w{i}_mdy"]}
        if f"w{i}_mresid" in npz.files:
            motion["resid"] = npz[f"w{i}_mresid"]
        depth = None
        if f"w{i}_depth" in npz.files:
            dm = meta["depth"]
            depth = {"t": npz[f"w{i}_t"], "depth": npz[f"w{i}_depth"], "units": dm["units"], "anchor": dm["anchor"]}
        doc, ev = col.run_collision(npz[f"w{i}_grids"], npz[f"w{i}_t"], meta["classNames"], config, settings, motion, depth)
        out.append({"doc": doc, "events": ev["events"], "key": w["key"],
                    "speech": [e for e in ev["events"] if e["type"] == "speech"],
                    # v26.1.13 follow-up: "beeps" / "tones" are the collision (parking) kind; "soft" / "softTones" the proximity kind
                    "beeps": [e for e in ev["events"] if e["type"] == "beeps" and e["kind"].startswith("collision")],
                    "tones": [e for e in ev["events"] if e["type"] == "tone" and e["kind"].startswith("collision")],
                    "soft": [e for e in ev["events"] if e["type"] == "beeps" and e["kind"] == "proximity"],
                    "softTones": [e for e in ev["events"] if e["type"] == "tone" and e["kind"] == "proximity"]})
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
    assert CONFIG["version"] == "v26.2.5"


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
    # v26.1.11: vehicles are never spoken as context (review 4), so the vehicle is not named at all; the obstacle that
    # comes into view at 6.3 s is a different object than the one at 0.7 s (2 steps ahead, 5 s of walking later)
    after = [e for e in w0["speech"] if e["role"] == "context" and e["t"] >= 6.0 and re.search(r"building|vehicle|parked car", e["text"])]
    assert after == [], after
    assert not [e for e in w0["speech"] if e["role"] == "context" and any(w in e["text"].lower() for w in VEHICLE_WORDS)]


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
                assert re.fullmatch(r"[a-z ]+ (approaching )?at [0-9:, and]+( in \d+( step)?)?(, .+)?", e["text"]), e["text"]
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
    # the ticked v26.1.5 phrase, + steps (v26.1.13: the nearest obstacle, 2.9 m to the left, leads: "10:45")
    got = sorted(re.sub(r" in \d+$", "", x) for x in first[0]["text"].split(", "))
    assert got[0] == "building at 2" and got[1] in ("obstacle at 11", "obstacle at 10:45"), got
    # the phrase after the turn at 5.8 s (ticked in review 2) is the 7.84 s "already referenced" of review 3: not said again
    # (v26.1.11: vehicles are never context, so "vehicle at 11" is not said; a new obstacle is, at 6.3 s)
    assert not any("vehicle" in e["text"] for e in w0["speech"] if e["role"] == "context")
    assert [e for e in w0["speech"] if 6.0 <= e["t"] <= 8.5 and e["role"] == "context" and re.search(r"building|vehicle", e["text"])] == []


def test_review2_crosswalk_is_announced_as_a_landmark_with_direction_and_steps_near_33_9_s(review2):
    """Added annotation at 33.9 s: "crosswalks are important ... add direction and steps". The crosswalk is detected
    at 32.8 s but only as 1-2 frame fragments (three track ids), so it is confirmed at about 35 s."""
    w1 = review2[2][1]
    hit = [e for e in _near(w1["speech"], 33.9, 2.0) if re.search(rf"crosswalk at {CLOCK_12} in \d+", e["text"])]
    assert hit, [e["text"] for e in w1["speech"]]
    steps = int(re.search(rf"crosswalk at {CLOCK_12} in (\d+)", hit[0]["text"]).group(1))
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
    # v26.1.11 (review 4, 40.5 / 46.2 s "same curb, no need to repeat"): a curb is said once per crossing and a crosswalk
    # once per 20 steps of walking, so nothing is said here any more: the curb at 32.5 s and the crosswalk at 35.3 s cover it
    curb = [e for e in _near(w1["speech"], 38.8, 2.5) if re.search(r"(curb|crosswalk) at \d+(?::\d\d)? in \d+", e["text"])]
    assert curb == [], [(e["t"], e["text"]) for e in w1["speech"]]
    assert any("curb" in e["text"] for e in w1["speech"] if e["t"] < 36) and any("crosswalk" in e["text"] for e in w1["speech"] if e["t"] < 38)
    poles = [e for e in w1["speech"] if re.search(r"\bpoles? at ", e["text"])]
    assert len(poles) == 1 and poles[0]["t"] < 30, [(e["t"], e["text"]) for e in w1["speech"]]
    # v26.1.15: the cold window's first phrase may carry a person too ("person at 11:45 in 8, pole at 12 in 13", 28.32 s)
    assert re.search(r"(^|, )pole at \d+(?::\d\d)? in \d+$", poles[0]["text"])
    assert all(e["role"] in ("feature", "danger") for e in poles)


def test_review2_obstacle_in_lane_is_named_once_and_beeps_near_35_3_s(review2):
    """Verdict at 35.33 s ("obstacle, 12 o'clock, 5 steps"): the obstacle is announced at 34.99 s as "obstacle at 12:30 in 6" (context, the
    first time it is seen). v26.1.7 muted the danger call 0.3 s later (the same object); v26.1.16 (review 8: collision and danger supersede
    notify-once) says it: "obstacle at 12 in 7" is the verdict's phrase. The parking-sensor beeps are as before."""
    w1 = review2[2][1]
    hit = [e for e in _near(w1["speech"], 35.33, 1.0) if re.search(r"obstacle at \d+(?::\d\d)? in \d+", e["text"])]
    assert [e["role"] for e in hit] == ["context", "danger"]
    assert len([e for e in _near(w1["speech"], 35.33, 3.0) if "obstacle" in e["text"]]) == 2
    # v26.1.12 (review 5): beeps start at 5 steps; the 35.3 s beep was at 7 steps, the phrase carries the warning
    assert not [b for b in w1["beeps"] if abs(b["t"] - 35.33) <= 1.0 and "obstacle at 12" in b["text"]]


def test_review2_person_is_warned_before_49_5_s_and_tracked_as_a_mover(review2):
    """Added annotation at 49.1 s: "Obstacle at 12 in 6, person at 1 and 2 ... people are moving, they should be tracked
    for collision, being notified sooner would be great". v26.1.5 said only "obstacle, 12 o'clock, 6 steps" at 48.5 s."""
    w2 = review2[2][2]
    # v26.1.13 (review 6): people are spoken once at 5-10 steps inside the 2.75 m zone, and under 5 steps they only beep. This
    # person (track 7) stays 3-5 m to the side until it is 4.7 steps away, so it is tracked early but not spoken: the added
    # annotation's "notified sooner" cannot be had without the older 3 m zone at 10 steps that review 6 took back
    assert not [e for e in w2["speech"] if "person" in e["text"] and e["t"] <= 49.5]
    mover_t = [f["t"] for f in w2["doc"]["frames"] for h in f["hazards"]
               if h["className"] == "person" and h["moving"] is True and h["clock"] in (1, 2) and f["t"] <= 49.5]
    assert mover_t and min(mover_t) <= 46.5                           # tracked as a mover well before it is alongside
    # and the obstacle ahead is still announced near 48.5 s
    assert [e for e in _near(w2["speech"], 48.5, 1.0) if re.search(rf"obstacle at {CLOCK_12} ", e["text"])]


def test_review2_person_phrase_near_75_5_s_has_no_oclock_and_names_12(review2):
    """Verdict at 75.49 s ("person approaching, 12 o'clock") -> "person approaching at 12" in the full run. As a cold window
    (no ego speed, so no motion measurement) the person is announced as a danger instead of "approaching"."""
    w3 = review2[2][3]
    hit = [e for e in _near(w3["speech"], 75.5, 1.5) if "person" in e["text"] and re.search(rf"\bat {CLOCK_12}\b", e["text"])]
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
            near = lead[0]["stepsTo"] <= roles["contextNearSteps"] + 0.5          # (v26.1.13: right under us 3.0 m still counts)
            limit = max(roles["contextMaxLateralM"], roles["contextNearLateralM"] if near else 0.0)
            assert abs(lead[0]["lateralM"]) <= limit + 0.3, (w["key"], e, lead[0])
            checked += 1
    assert checked >= 3


def test_review2_no_oclock_in_any_phrase_and_clocks_use_the_new_templates(review2, review1):
    for _, _, windows in (review2, review1):
        for w in windows:
            for e in w["speech"]:
                assert "o'clock" not in e["text"]
                assert re.fullmatch(r"[a-z ,]+( at [0-9][0-9:, and]*)?( in \d+( step)?)?(, [a-z ,0-9:]+)*", e["text"]) or \
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
            frames = [f for f in w["doc"]["frames"] if b["t"] - 0.35 <= f["t"] <= b["tEnd"]]   # (a tone falls up to one interval after its frame)
            tracks = [h for f in frames for h in f["hazards"] if h["trackId"] == b["trackId"]]
            # v26.1.11/12: a mover can drop out of its collision course (role none) between two beeps (its motion state flickers
            # between "approaching" and "unknown"); the episode joins beeps less than 1.5 s apart
            assert tracks and all(h["className"] not in ("curb", "crosswalk", "object pothole") for h in tracks), b
            assert any(h["role"] == "danger" and h["collision"] for h in tracks), b            # (a lost frame may continue for 0.5 s)
        for x in w["tones"]:
            owners = [b for b in w["beeps"] if b["trackId"] == x["trackId"] and b["t"] - 0.05 <= x["t"] <= b["tEnd"] + 0.05]
            assert len(owners) == 1, (w["key"], x)
            assert x["frequencyHz"] == CONFIG["tones"]["sounds"][x["kind"]]["pitchHz"]          # v26.1.16: the pitch of its sector
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
# they reproduce only part of what the full 52 minute run said.

WARM_PRIOR = 1.25     # a scale prior stands in for the calibration the full run has at 36 s (its k is 1.16-1.5 there)
CLOCK_12 = r"(?:11:30|11:45|12|12:15|12:30)"      # a reviewed "12" within half an hour
THIN_PHRASE = re.compile(r"\b(poles?|traffic lights?|pedestrian lights?|signs?|traffic signs?) at ")
_CLK = r"\d+(?::\d\d)?(?:, \d+(?::\d\d)?)*(?: and \d+(?::\d\d)?)?"
# v26.1.11: "approaching" and "moving away" carry no distance (review 4); "standing"/"stopped" do
ENTRY_RE = rf"[a-z ]+? (?:(?:approaching|moving away) at {_CLK}|(?:(?:standing|stopped) )?at {_CLK} in \d+(?: steps?)?)"


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


def _q_of(clock: str) -> int:
    """Quarter index of a spoken clock ("12" -> 0, "1" -> 4, "11:45" -> -1)."""
    h, _, m = clock.partition(":")
    mins = (int(h) % 12) * 60 + (int(m) if m else 0)
    return round((mins - 720 if mins > 360 else mins) / 15)


def _norm(text: str) -> tuple:
    """Entries of a phrase as (label part, clock quarter indices), without steps and "approaching"."""
    text = re.sub(r" in \d+( steps?)?", "", text)
    for word in (" approaching", " standing", " stopped", " moving away"):      # v26.1.11 motion words are allowed on a kept phrase
        text = text.replace(word, "")
    out = []
    for x in text.split(", "):
        m = re.match(r"(.+?) at (\d+(?::\d\d)?(?:(?:,| and) \d+(?::\d\d)?)*)$", x.strip())
        if m:
            out.append((m.group(1), tuple(sorted(_q_of(c) for c in re.findall(r"\d+(?::\d\d)?", m.group(2))))))
        else:
            out.append((x.strip(), ()))
    return tuple(sorted(out))


QUARTER_TOL = 2     # v26.1.10: a reviewed whole hour matches a quarter text within half an hour (the lens model moves bearings too)


def _entry_match(a: tuple, b: tuple) -> bool:
    (la, qa), (lb, qb) = a, b
    near = lambda q, qs: any(abs(q - r) <= QUARTER_TOL for r in qs)    # noqa: E731
    return la == lb and all(near(q, qb) for q in qa) and all(near(q, qa) for q in qb)


def _same_norm(a: tuple, b: tuple) -> bool:
    """Equal entry lists (label and clocks within QUARTER_TOL quarters)."""
    return len(a) == len(b) and all(_entry_match(x, y) for x, y in zip(a, b))


def _sub_norm(a: tuple, b: tuple) -> bool:
    """Every entry of ``a`` has a matching entry in ``b``."""
    return all(any(_entry_match(x, y) for y in b) for x in a)


def _is_the_annotated_event(ann: dict, e: dict) -> bool:
    """Same label / type pattern as the annotated v26.1.6 event; the phrasing may differ by CONTRACTS.md 15 rule 3
    (" in N" added, "beware poles" -> "poles at 11 and 1 in 8")."""
    a = ann["event"]
    if a["type"] == "beeps":
        strip = lambda t: re.sub(r"^(beeps|soft) · (left · |center · |right · )?", "", re.sub(r" · [\d→ ]+ steps?", "", t))          # noqa: E731
        return e["type"] == "beeps" and strip(e["text"]) == strip(a["text"])
    if e["type"] != "speech":
        return False
    if a["text"] == "beware poles":
        return any(THIN_PHRASE.match(x.strip()) for x in e["text"].split(", "))
    if a["role"] == "surface":
        return e["role"] == "surface" and e["text"] == a["text"]
    return _same_norm(_norm(a["text"]), _norm(e["text"])) or (a["role"] == "context" and _sub_norm(_norm(a["text"]), _norm(e["text"])))


def _produced(meta, windows, ann, tol=1.5):
    evs = _all(windows) + _all(windows, "beeps") + _all(windows, "soft")      # a soft proximity sound stands in for a beep (v26.1.13 follow-up)
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
    assert CONFIG["version"] == "v26.2.5"


def test_review3_no_repeat_at_7_84_40_50_59_85_and_118_66(review3, review3_warm, review3_no_memory):
    """The four repeats of the same real object. The memory-less run (v26.1.6 behaviour) reproduces three of them in these cold
    windows (59.85 s needs the 52 s history of the full run), so these assertions are not vacuous."""
    for windows in (review3[2], review3_warm[2]):
        sp = _all(windows)
        assert [e for e in _near(sp, 7.84, 1.5) if "building" in e["text"]] == []
        # (v26.1.16: the pole named earlier is still called a danger at 3 steps, 40.83 s: collision and danger supersede notify-once)
        assert [e for e in _near(sp, 40.50, 1.5) if THIN_PHRASE.search(e["text"]) and e["role"] != "danger"] == []
        assert [e for e in _near(sp, 59.85, 1.5) if "crosswalk" in e["text"]] == []
        # v26.1.12: the cold window has not named this person before (v26.1.11 only beeped, at 7 steps); "approaching" is the state
        # change that is announced again, a plain repeat is still not
        assert [e for e in _near(sp, 118.66, 1.5) if "person" in e["text"] and "approaching" not in e["text"]] == []
        w0 = [e for e in windows[0]["speech"] if re.search(r"vehicle|parked car", e["text"])]
        assert w0 == [], w0                                      # v26.1.11: vehicles are never spoken as context (was: once, 5.34 s)
    cold = _all(review3[2])
    assert [e for e in _near(cold, 7.84, 1.5) if re.search(r"building|vehicle|parked car", e["text"])] == []
    old = _all(review3_no_memory[2])
    # (v26.1.11: without the vehicle phrase of 5.3 s the memory-less repeat of the building comes 1.5 s earlier, at 6.34 s)
    assert [e for e in _near(old, 7.1, 1.3) if re.search(r"building|vehicle|parked car", e["text"])]
    assert [e for e in _near(old, 40.50, 1.5) if THIN_PHRASE.search(e["text"])]
    # (v26.1.13: the person is 13 steps away: people are spoken at 5-10 steps only, so even the memory-less run is silent)
    assert [e for e in _near(old, 118.66, 1.5) if "person" in e["text"]] == []


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
            assert re.fullmatch(r"beeps · (left|center|right) · [a-z ]+ at \d+(?::\d\d)? · [\d→]+ steps?", b["text"]), b["text"]
    assert n >= 25


# What the committed v26.1.6 reproduces from the user's 27 ticks in these COLD windows, and what v26.1.7 must keep. The rest
# of the 27 (e.g. 15.35 s, 30.82 s, 35.49 s ...) lie outside the windows or need the warm state of the full run.
# v26.1.11 deviations: 5.3387 "vehicle at 11" (vehicles are never context, review 4 decision 3) and 49.6747 "curb at 12 in 3"
# (one curb per crossing: the curb of 40-41 s is 9 s and < 24 steps earlier, decision 4) are no longer produced.
# 201.3263 "person approaching at 12": in this cold window (192-218 s) the depth gait level is not measured yet, so the person's
# closing speed is not on the gait scale and the approach is not recognised; the warm 0-500 s run says it at 200.8 s.
COLD_TICKS = [0.6673, 47.5058, 48.5068, 48.5068, 196.3213, 212.3373]
WARM_TICKS = [41.1662, 47.5058, 48.5068, 48.5068, 56.1812, 106.982, 196.3213, 212.3373]


# v26.1.12 ticks that moved on purpose: 48.5068 beeps "obstacle at 12" (a person 2 steps away at 1:45 now takes the beeps from 47.8 s,
# as an unknown-motion person within 5 steps), 106.982 "person approaching at 12" (13 steps away) and 196.3213 "person at 12 in 14", both
# beyond the 10-step reach of movers
# v26.1.13: 47.5058 "person at 1 in 4" is under 5 steps (people only beep there, and only on a collision course)
MOVED_TICKS = {(48.5068, "beeps"), (106.982, "speech"), (196.3213, "speech"), (47.5058, "speech")}


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
    assert len(anns) == 6
    for a in anns:
        if (a["t"], a["event"]["type"]) in MOVED_TICKS:
            continue
        assert _produced(meta, windows, a), (a["t"], a["event"]["text"])


def test_review3_every_tick_the_warm_windows_reproduced_is_still_produced(review3_warm):
    meta, _, windows = review3_warm
    anns = _ticks(meta, WARM_TICKS)
    assert len(anns) == 8
    for a in anns:
        if (a["t"], a["event"]["type"]) in MOVED_TICKS:
            continue
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
        assert _sub_norm(_norm(e["text"]), _norm(same[0]["text"])), (e["text"], same[0]["text"])


# --------------------------------------------------------------------------
# Review 4 (v26.1.10, first review on the fixed model; fixtures 4929_review4)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def review4():
    return _run_windows("4929_review4")


def test_review4_fixture_is_the_documented_one():
    meta, settings = _load("4929_review4")
    npz = np.load(FIXTURES / "4929_review4.npz")
    assert [(w["start"], w["end"]) for w in meta["windows"]] == [
        (20.0, 50.0), (66.0, 105.0), (150.0, 205.0), (236.0, 270.0), (284.0, 345.0), (352.0, 410.0), (436.0, 470.0)]
    for i, w in enumerate(meta["windows"]):
        t = npz[f"w{i}_t"]
        assert t[0] >= w["start"] - 0.5 and t[-1] <= w["end"] + 0.5
        assert npz[f"w{i}_grids"].shape == (len(t), meta["gridH"], meta["gridW"])
        assert npz[f"w{i}_depth"].shape == (len(t), *meta["depth"]["shape"])
    ann = meta["annotations"]
    assert len(ann) == 63
    assert (sum(a["verdict"] == "correct" for a in ann), sum(a["verdict"] == "incorrect" for a in ann),
            sum(a["verdict"] == "remove" for a in ann)) == (52, 2, 9)
    assert settings.distance_source == "depth" and settings.user_height_m == 1.78
    assert len(meta["systemEventsV26_1_10"]) > 0

# What review 4 (v26.1.10) marked wrong or "should not be said", and what v26.1.11 does with it. The windows are cold (each starts
# its own sequence), so everything below holds without the warm state of the full run; the same checks hold on 0-500 s of the run.
# v26.1.12: movers are spoken within 10 steps and beeps start at 5, so these review-4 entries leave on purpose (all are movers
# named at 11-15 steps, and one beep at 5.5 steps); ``test_review4_the_entries_that_left_are_beyond_the_new_reach`` pins the numbers
R4_BEYOND_REACH = [28.0, 74.5, 200.3, 467.2]
R4_WALKS_INTO_REACH = [28.0]      # v26.1.15: said one second later at 10 steps ("person standing at 11:45 in 10", 28.99 s), still within the 10 steps
# v26.1.13: 190.5 / 462.2 (cyclist / person at 11-14 steps): the cyclist is announced early now (no step limit), the person at 462
# stays out of reach; 371.5 is the 374.0 s person ("approaching", see ``test_review4_the_person_at_374_s_is_approaching``);
# 48.5 "person at 12:45 in 5" (lateral 2.6-2.8 m, flickering around the 2.75 m people zone, 5.0 steps) is not reproduced
# 366.5 "person at 1:15 in 3" is under 5 steps: people only beep there (and only on a collision course, v26.1.13)
R4_KEPT = [37.3, 300.3, 354.3, 381.5, 384.0, 445.2]       # (445.3 "cyclist approaching at 12 in 7": two seconds earlier, see below)
R4_GONE = [39.0, 46.2, 159.8, 244.0, 321.7, 334.2, 380.7, 399.1]       # (40.5: see the curb test; 302.8: the user is not yet "stationary")


def _r4_ann(meta, t, verdicts):
    return [a for a in meta["annotations"] if abs(a["t"] - t) < 0.06 and a["verdict"] in verdicts]


def test_review4_the_checked_phrases_are_kept_with_a_motion_word_where_measured(review4):
    meta, _, windows = review4
    for t in R4_KEPT:
        anns = _r4_ann(meta, t, ("correct",))
        assert anns, t
        for a in anns:
            # v26.1.15: the cold window of 352 s no longer holds the beeps back for its first 1.5 s: the person at 2 steps beeps at 352.35 s
            # (2 s before the user's 354.3 s, where the real run had the person already in view)
            assert _produced(meta, windows, a, tol=2.5 if t == 354.3 else 1.5), (a["t"], a["event"]["text"])


def test_review4_the_entries_that_left_are_beyond_the_new_reach(review4):
    meta, _, windows = review4
    for t in R4_BEYOND_REACH:
        for a in _r4_ann(meta, t, ("correct",)):
            if a["event"]["type"] != "speech":
                continue
            steps = int(re.search(r" in (\d+)$", a["event"]["text"]).group(1))
            assert steps > CONFIG["roles"]["movingDangerSteps"], (t, a["event"]["text"])
            made = _produced(meta, windows, a)
            if t in R4_WALKS_INTO_REACH:
                assert all(int(re.search(r" in (\d+)$", e["text"]).group(1)) <= CONFIG["roles"]["movingDangerSteps"] for e in made), (t, made)
            else:
                assert not made, (t, a["event"]["text"])
    # the beeps at 5.5 steps (48.7 s): the same obstacle is now beeped only from 5 steps
    assert [a for a in _r4_ann(meta, 48.6737, ("correct",)) if a["event"]["type"] == "beeps"]
    assert not [b for b in _all(windows, "beeps") if b["t"] < 48.8 and "obstacle" in b["text"] and 48.0 <= b["t"] <= 48.8]


def test_review4_the_cyclists_at_190_5_and_462_s_are_announced_without_distance_and_earlier(review4):
    _, _, windows = review4
    sp = _all(windows)
    c190 = [e for e in sp if e["text"].startswith("cyclist approaching") and 188.0 <= e["t"] <= 191.5]
    assert c190 and c190[0]["t"] < 190.5 and not re.search(r" in \d", c190[0]["text"])
    c445 = [e for e in sp if e["text"].startswith("cyclist approaching") and 441.0 <= e["t"] <= 446.0]     # the pair of cyclists, 2 s before 445.3
    assert c445 and c445[0]["t"] <= 443.5 and c445[0]["text"] == "cyclist approaching at 11:45 and 12"
    c462 = [e for e in sp if e["text"].startswith("cyclist approaching") and 460.0 <= e["t"] <= 463.5]
    assert c462 and not re.search(r" in \d", c462[0]["text"])


def test_review4_the_person_at_374_s_is_approaching_not_standing(review4):
    _, _, windows = review4
    sp = [e for e in _all(windows) if 372.0 <= e["t"] <= 376.0 and "person" in e["text"]]
    assert sp and all("standing" not in e["text"] for e in sp), sp


def test_review4_the_wrong_and_unwanted_phrases_are_gone(review4):
    meta, _, windows = review4
    for t in R4_GONE:
        anns = _r4_ann(meta, t, ("incorrect", "remove"))
        assert anns, t
        for a in anns:
            assert not _produced(meta, windows, a), (a["t"], a["event"]["text"], [(e["t"], e["text"]) for e in _all(windows) + _all(windows, "beeps") if abs(e["t"] - a["t"]) < 2])


def test_review4_the_vehicle_crossing_the_crosswalk_at_39_s_is_neither_said_nor_beeped(review4):
    """39.0 s (both ✗): "vehicle is passing over the crosswalk in a non-collision direction ... should notify about poles and curb"."""
    w0 = review4[2][0]
    assert [e for e in w0["speech"] + w0["beeps"] if 36.0 <= e["t"] <= 42.0 and re.search(r"vehicle|parked car", e["text"])] == []
    slot = [e for e in w0["speech"] if 38.5 <= e["t"] <= 41.5]
    assert slot and all("curb" in e["text"] for e in slot), [(e["t"], e["text"]) for e in w0["speech"]]


def test_review4_a_curb_is_said_once_per_crossing(review4):
    """40.5 / 46.2 s (⊘): "cane will pick it up + previous curb and pole notification would be enough", "same curb, no need to repeat"."""
    w0 = review4[2][0]
    curbs = [e for e in w0["speech"] if 36.0 <= e["t"] <= 50.0 and "curb" in e["text"]]
    assert len(curbs) == 1 and curbs[0]["t"] < 41.0, [(e["t"], e["text"]) for e in w0["speech"]]


def test_review4_vehicles_are_never_spoken_as_context_nor_as_a_standing_danger(review4):
    _, _, windows = review4
    assert [e for e in _all(windows) if re.search(r"vehicle|parked car", e["text"]) and e["role"] == "context"] == []
    assert [e for e in _all(windows) if re.search(r"parked car|vehicle at|vehicle standing", e["text"])] == []
    assert [b for b in _all(windows, "beeps") if "vehicle" in b["text"]] == []


def test_review4_no_surface_event_at_159_8_or_244_0(review4):
    """The wrong "road" (a crosswalk at the left edge of the lane, 5 s after the change began and 7 s before it) and the
    "sidewalk" that flipped it back: no surface announcement at all in these windows."""
    assert [e for e in _all(review4[2]) if e["role"] == "surface"] == []


def test_review4_stationary_user_is_detected_in_286_345_and_never_while_walking(review4):
    meta, npz, windows = review4
    for i, w in enumerate(windows):
        flags = [(f["t"], f["ego"]["stationary"]) for f in w["doc"]["frames"]]
        if i != 4:
            assert not any(s for _, s in flags), (meta["windows"][i], [t for t, s in flags if s][:3])
    w4 = windows[4]
    still = [f for f in w4["doc"]["frames"] if 312.0 <= f["t"] <= 344.0]
    assert len(still) > 150 and sum(f["ego"]["stationary"] for f in still) >= 0.97 * len(still)
    assert all(f["ego"]["speedMps"] == 0.0 for f in still if f["ego"]["stationary"])
    # the numbers the choice rests on: the median residual flow over 1 s, standing against walking (egoflow.py)
    resid = {k: npz[f"w{i}_mresid"] for i, k in enumerate(["w0", "w1", "w2", "w3", "w4", "w5", "w6"])}
    mt4 = npz["w4_mt"]
    standing = resid["w4"][(mt4 >= 312) & (mt4 <= 344)]
    walking = np.concatenate([resid[k] for k in ("w0", "w1", "w2", "w3", "w5", "w6")])
    assert np.nanpercentile(standing, 95) < CONFIG["ego"]["stationary"]["enterPx"] < np.nanpercentile(walking, 5)


def test_review4_nothing_is_said_or_beeped_while_standing(review4):
    """302.8 (obstacle) is still said: the user stops and turns at ~300-305 s and is "stationary" only from ~307 s on (the
    picture still rotates). 321.7 (person) and 334.2 (obstacle) are the ⊘ the user marked "I'm static, no need to notify"."""
    w4 = review4[2][4]
    standing = [f["t"] for f in w4["doc"]["frames"] if f["ego"]["stationary"] and f["t"] > 305]
    assert standing and standing[-1] - standing[0] > 30
    said = [e for e in w4["speech"] + w4["beeps"] if standing[0] <= e["t"] <= standing[-1]]
    assert said == [], said
    assert [e for e in w4["speech"] if 321.0 <= e["t"] <= 336.0] == []


def test_review4_people_phrases_say_what_was_measured(review4):
    meta, _, windows = review4
    checked = 0
    for w in windows:
        for e in w["speech"]:
            if e["trackId"] is None or e["role"] not in ("danger", "final"):
                continue
            f = min(w["doc"]["frames"], key=lambda f: abs(f["t"] - e["t"]))
            hz = next((h for h in f["hazards"] if h["trackId"] == e["trackId"]), None)
            if hz is None or hz["className"] not in ("person", "rider"):
                continue
            entry = e["text"].split(", ")[0]
            if hz["moving"] is None:
                assert not re.search(r"standing|stopped|approaching|moving away", entry), (e["t"], e["text"])
            elif hz["moving"] is False:
                assert re.search(r"standing|stopped", entry), (e["t"], e["text"], hz)
            elif hz["collision"]:
                assert "approaching" in entry, (e["t"], e["text"], hz)
            checked += 1
    assert checked >= 10


def test_review4_people_carry_the_distance_riders_and_vehicles_do_not(review4):
    """v26.1.13: "person approaching at 12:15 in 9" / "person moving away at 12 in 8" (5-10 steps); "cyclist approaching at 11" has none."""
    texts = [e["text"] for e in _all(review4[2])]
    movers = [t for t in texts if re.search(r"approaching|moving away", t)]
    assert len(movers) >= 5 and any("cyclist approaching" in t for t in movers)
    assert all(re.search(r" in \d+$", t) for t in movers if t.startswith("person"))
    assert not [t for t in movers if re.match(r"(cyclist|vehicle)", t) and re.search(r" in \d", t)], movers
