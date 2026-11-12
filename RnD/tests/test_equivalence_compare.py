"""Unit tests of the equivalence comparator (tools/equivalence.py): tolerances, perturbed copies, VOLATILE keys."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import equivalence as eq


def _record() -> dict[str, Any]:
    frames = [
        {
            "index": i,
            "t": i / 6,
            "horizonY": 0.4,
            "ego": {"speedMps": 1.2, "headingDeg": 10.0},
            "hazards": [
                {"trackId": 1, "label": "person", "role": "danger", "distanceM": 5.0 - 0.1 * i, "bearingDeg": 3.0},
                {"trackId": 2, "label": "pole", "role": "feature", "distanceM": 9.0, "bearingDeg": -12.0},
            ],
        }
        for i in range(10)
    ]
    events = [
        {"type": "speech", "t": 0.5, "text": "person at 12 in 5", "role": "danger", "label": "person", "trackId": 1},
        {"type": "beeps", "t": 1.0, "tEnd": 1.3, "text": "beeps", "role": "danger", "label": "person"},
    ]
    wm = {
        "idx": np.array([0, 5]),
        "classes": np.zeros((2, 100, 100), np.uint8),
        "conf": np.full((2, 100, 100), 200, np.uint8),
        "pose": np.zeros((10, 3)),
    }
    return {
        "nFrames": 10,
        "dt": 1 / 6,
        "hazards": {"version": "v1", "settings": {"mount": "chest"}, "frames": frames},
        "worldTracks": {"settings": {"enabled": True}, "frames": [[{"id": "W1", "x": 1.0}]] * 10},
        "events": events,
        "tones": [{"type": "tone", "t": 0.5, "frequencyHz": 440.0}],
        "worldmap": wm,
    }


def _run(mutate: Any = None) -> eq.CaseResult:
    old = _record()
    new = copy.deepcopy(old)
    if mutate is not None:
        mutate(new)
    return eq.compare_records("t/w0/default", old, new)


def test_identical_records_have_no_drift() -> None:
    r = _run()
    assert r.status == "ok" and not r.drift and r.n_violations == 0


def test_numbers_use_the_absolute_floor_and_the_relative_tolerance() -> None:
    def ok(n: dict[str, Any]) -> None:
        n["hazards"]["frames"][3]["hazards"][0]["distanceM"] += 0.0009

    def bad(n: dict[str, Any]) -> None:
        n["hazards"]["frames"][3]["hazards"][0]["distanceM"] += 0.01

    r = _run(ok)
    assert r.status == "ok" and "hazards.frames[].hazards[].distanceM" in r.drift
    r = _run(bad)
    assert r.status == "violations" and r.violations[0].path == "hazards.frames[3].hazards[0].distanceM"

    def big(n: dict[str, Any]) -> None:
        n["hazards"]["frames"][0]["ego"]["bigValue"] = 10000.5

    old = _record()
    old["hazards"]["frames"][0]["ego"]["bigValue"] = 10000.0
    new = copy.deepcopy(old)
    big(new)
    assert eq.compare_records("x", old, new).status == "ok"  # 0.5 < 1e-4 * 10000 = 1.0
    new["hazards"]["frames"][0]["ego"]["bigValue"] = 10002.0
    assert eq.compare_records("x", old, new).status == "violations"


def test_a_changed_phrase_role_or_label_fails() -> None:
    for key, value in (("text", "person at 1 in 5"), ("role", "context"), ("label", "pedestrian")):

        def m(n: dict[str, Any], key: str = key, value: str = value) -> None:
            n["events"][0][key] = value

        r = _run(m)
        assert r.status == "violations" and r.violations[0].path == f"events[0].{key}"


def test_event_times_may_move_one_frame_not_two() -> None:
    def one(n: dict[str, Any]) -> None:
        n["events"][0]["t"] += 1 / 6 - 0.001

    def two(n: dict[str, Any]) -> None:
        n["events"][0]["t"] += 2 / 6

    assert _run(one).status == "ok"
    assert _run(two).status == "violations"


def test_event_order_and_counts_are_exact() -> None:
    def swap(n: dict[str, Any]) -> None:
        n["events"].reverse()

    def drop(n: dict[str, Any]) -> None:
        n["events"].pop()

    assert _run(swap).status == "violations"
    r = _run(drop)
    assert r.status == "violations" and any(v.kind == "counts" for v in r.violations)


def test_the_track_set_of_every_frame_must_match() -> None:
    def gone(n: dict[str, Any]) -> None:
        n["hazards"]["frames"][4]["hazards"].pop()

    def relabel(n: dict[str, Any]) -> None:
        n["hazards"]["frames"][4]["hazards"][1]["label"] = "tree"

    for m in (gone, relabel):
        r = _run(m)
        assert r.status == "violations" and r.violations[0].kind == "tracks" and "frames[4]" in r.violations[0].path


def test_volatile_keys_are_ignored_in_records_and_snapshots() -> None:
    def m(n: dict[str, Any]) -> None:
        n["hazards"]["version"] = "v2"

    assert _run(m).status == "ok"
    old: dict[str, Any] = {
        "runs": {
            "status": 200,
            "body": {"id": "c1", "createdAt": "a", "elapsedSeconds": 1.5, "nested": [{"builtAt": 1, "x": 1}]},
        }
    }
    new = copy.deepcopy(old)
    new["runs"]["body"].update(createdAt="b", elapsedSeconds=9.0)
    new["runs"]["body"]["nested"][0]["builtAt"] = 2
    assert eq.compare_snapshots("labapi", old, new).status == "ok"
    new["runs"]["body"]["nested"][0]["x"] = 1.0000001
    r = eq.compare_snapshots("labapi", old, new)
    assert r.status == "violations" and r.violations[0].path == "runs.body.nested[0].x"  # snapshots are exact


def test_worldmap_cells_and_confidence() -> None:
    def few(n: dict[str, Any]) -> None:  # 5 of 10000 cells = 0.05 %
        n["worldmap"]["classes"][1, 0, :5] = 7

    def many(n: dict[str, Any]) -> None:  # 20 cells = 0.2 %
        n["worldmap"]["classes"][1, 0, :20] = 7

    def conf(n: dict[str, Any]) -> None:
        n["worldmap"]["conf"][0, 3, 3] = 201

    r = _run(few)
    assert r.status == "ok" and "worldmap.classes" in r.drift
    assert _run(many).status == "violations"
    assert _run(conf).status == "violations"


def test_canon_rounds_digests_polygons_and_marks_nan() -> None:
    c = eq.canon(
        {
            "outline": [[0, 0], [2, 0], [2, 2], [0, 2]],
            "bbox": [0.123456, 1],
            "v": float("nan"),
            "n": np.float32(0.5),
            "a": np.arange(2),
        }
    )
    assert c["outline"]["_n"] == 4 and c["outline"]["area"] in (4.0, -4.0)
    assert c["bbox"] == [0.123, 1] and c["v"] == "nan" and c["n"] == 0.5 and c["a"] == [0, 1]


def test_plan_covers_every_fixture_and_records_why_cases_are_skipped() -> None:
    cases, skipped = eq.plan()
    assert {c.fixture for c in cases} == set(eq.fixture_names())
    assert all(s["reason"] for s in skipped)
    assert {(c.fixture, c.window) for c in eq.quick_plan(cases)} == set(eq.QUICK_WINDOWS)
