"""Characterisation tests for lab.features (v26.3.0 p5-05): reviews, notes, issues, sounds, display, compare.

Every literal below was printed by the legacy ``lab.collisions`` compare functions (``match_events``, ``_same``, ``_flatten``,
``_settings_diff``) and ``lab.issues`` in the hackeye-rnd image before the move. The ``lab.features`` modules are imported inside each
test (they do not exist yet). The flat modules stay as facades: every moved name is the same object, and a patched module global
(``issues.CATALOGUE``, ``reviews.LAB_DIR``) is seen by the moved functions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from lab import collisions, display, issues, notes, recordings, reviews, sounds

if TYPE_CHECKING:
    from pathlib import Path


def _sp(t: float, text: str) -> dict[str, Any]:
    return {"t": t, "type": "speech", "text": text}


def _bp(t: float, kind: str, clock: int, text: str) -> dict[str, Any]:
    return {"t": t, "type": "beeps", "kind": kind, "clock": clock, "text": text}


# ---- identity through the facades -------------------------------------------------------------------------------------------

REVIEWS_NAMES: list[str] = [
    "KINDS", "MAX_NOTE", "MAX_TEXT", "NEARBY_SECONDS", "ROLES", "TYPES", "VERDICTS", "_EVENT_KEYS",
    "ReviewError", "_RunData",
    "_auto_correct", "_bad", "_check_note", "_check_role", "_check_run", "_check_t", "_check_t_end", "_check_text",
    "_check_type", "_check_verdict", "_load", "_lock", "_log", "_now", "_path", "_run_notifications", "_save", "_sorted",
    "count_for_collision", "create", "delete", "export", "list_annotations", "match_key", "recordings_with_reviews", "update",
]  # fmt: skip
NOTES_NAMES: list[str] = ["MAX_CHARS", "NotesError", "_lock", "_path", "_read", "get", "put"]
ISSUES_NAMES: list[str] = [
    "IssuesError", "MAX_NOTE", "_catalogue", "_item", "_items", "_lock", "_state", "_state_path",
    "export_items", "list_issues", "reset", "update",
]  # fmt: skip
SOUNDS_NAMES: list[str] = [
    "FIELDS", "SoundsError", "_col", "_is_num", "_lock", "_overrides", "_path", "_read", "_view", "get", "profile", "put", "reset",
]  # fmt: skip
DISPLAY_NAMES: list[str] = [
    "DisplayError", "_clean_classes", "_clean_levels", "_dir", "_is_num", "_lock", "_mapping", "_read", "_write",
    "default_opacity", "get", "put", "reset",
]  # fmt: skip
COMPARE_NAMES: list[str] = ["_flatten", "_settings_diff", "_events", "_same", "match_events", "compare"]


def test_reviews_names_are_the_features_objects() -> None:
    from lab.features import reviews as home

    for name in REVIEWS_NAMES:
        assert getattr(reviews, name) is getattr(home, name), name


def test_notes_names_are_the_features_objects() -> None:
    from lab.features import notes as home

    for name in NOTES_NAMES:
        assert getattr(notes, name) is getattr(home, name), name


def test_issues_names_are_the_features_objects() -> None:
    from lab.features import issues as home

    for name in ISSUES_NAMES:
        assert getattr(issues, name) is getattr(home, name), name
    assert issues.CATALOGUE is home.CATALOGUE
    assert issues.CATALOGUE.name == "issues.json"
    assert issues.CATALOGUE.exists()


def test_sounds_names_are_the_features_objects() -> None:
    from lab.features import sounds as home

    for name in SOUNDS_NAMES:
        assert getattr(sounds, name) is getattr(home, name), name


def test_display_names_are_the_features_objects() -> None:
    from lab.features import display as home

    for name in DISPLAY_NAMES:
        assert getattr(display, name) is getattr(home, name), name


def test_compare_names_leave_collisions_as_the_same_objects() -> None:
    from lab.features import compare as home

    for name in COMPARE_NAMES:
        assert getattr(collisions, name) is getattr(home, name), name


# ---- patched module globals are seen by the moved functions ---------------------------------------------------------------

CAT: dict[str, Any] = {
    "updatedAt": "2026-10-27",
    "groups": [{"id": "open", "title": "Open issues"}, {"id": "debt", "title": "Debt"}],
    "items": [
        {"id": "O1", "group": "open", "title": "one", "details": ["a `b`"]},
        {"id": "D1", "group": "debt", "title": "debt one", "details": []},
    ],
}


def test_issues_catalogue_patch_is_seen_by_the_issues_functions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lab.features import issues as home

    cat = tmp_path / "cat.json"
    cat.write_text(json.dumps(CAT))
    monkeypatch.setattr(issues, "CATALOGUE", cat)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path / "lab")
    assert home.CATALOGUE is cat
    assert issues._catalogue() == CAT
    assert issues.list_issues() == {
        "updatedAt": "2026-10-27",
        "groups": [
            {
                "id": "open",
                "title": "Open issues",
                "items": [
                    {
                        "id": "O1", "group": "open", "title": "one", "details": ["a `b`"], "status": "open",
                        "closedAt": None, "note": "", "noteUpdatedAt": None, "userChanged": False,
                    }
                ],
                "openCount": 1,
            },
            {
                "id": "debt",
                "title": "Debt",
                "items": [
                    {
                        "id": "D1", "group": "debt", "title": "debt one", "details": [], "status": "open",
                        "closedAt": None, "note": "", "noteUpdatedAt": None, "userChanged": False,
                    }
                ],
                "openCount": 1,
            },
        ],
    }  # fmt: skip
    assert issues.export_items() == []


def test_issues_state_follows_the_recordings_lab_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path / "lab")
    assert issues._state_path() == tmp_path / "lab" / "issues-state.json"


def test_reviews_lab_dir_is_its_own_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lab.features import reviews as home

    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path / "lab")
    monkeypatch.setattr(reviews, "LAB_DIR", tmp_path / "rv")
    assert home.LAB_DIR == tmp_path / "rv"
    assert reviews._path("rec1") == tmp_path / "rv" / "reviews" / "rec1.json"
    assert recordings.LAB_DIR == tmp_path / "lab"
    assert reviews.list_annotations("rec1") == {"recording": "rec1", "annotations": []}
    assert reviews.recordings_with_reviews() == []


# ---- compare / match --------------------------------------------------------------------------------------------------------


def test_match_events_compare_fixture_inputs() -> None:
    from lab.features.compare import match_events

    ea = [_sp(1.0, "pole 12"), _sp(5.0, "car 3"), _sp(9.0, "bench"), _bp(2.0, "collision-left", 11, "beeps a"), _sp(20.0, "gone")]
    eb = [_sp(1.4, "pole 12"), _sp(5.5, "car 2"), _sp(9.0, "bench"), _bp(2.5, "collision-left", 11, "beeps b"), _sp(30.0, "new")]
    assert match_events(ea, eb) == {
        "same": 3,
        "changed": [
            {
                "t": 5.0,
                "type": "speech",
                "a": {"t": 5.0, "type": "speech", "text": "car 3"},
                "b": {"t": 5.5, "type": "speech", "text": "car 2"},
            }
        ],
        "onlyA": [{"t": 20.0, "type": "speech", "text": "gone"}],
        "onlyB": [{"t": 30.0, "type": "speech", "text": "new"}],
    }


def test_match_events_greedy_nearest_first_uses_each_once() -> None:
    from lab.features.compare import match_events

    assert match_events([_sp(1.0, "x"), _sp(1.9, "x")], [_sp(1.6, "x")]) == {
        "same": 1,
        "changed": [],
        "onlyA": [{"t": 1.0, "type": "speech", "text": "x"}],
        "onlyB": [],
    }


def test_match_events_beyond_one_second_is_not_a_match() -> None:
    from lab.features.compare import match_events

    assert match_events([_sp(0.0, "x")], [_sp(1.01, "x")]) == {
        "same": 0,
        "changed": [],
        "onlyA": [{"t": 0.0, "type": "speech", "text": "x"}],
        "onlyB": [{"t": 1.01, "type": "speech", "text": "x"}],
    }


def test_match_events_beeps_with_another_clock_are_changed() -> None:
    from lab.features.compare import match_events

    got = match_events([_bp(2.0, "collision-left", 11, "a")], [_bp(2.2, "collision-left", 12, "b")])
    assert got == {
        "same": 0,
        "changed": [
            {
                "t": 2.0,
                "type": "beeps",
                "a": {"t": 2.0, "type": "beeps", "kind": "collision-left", "clock": 11, "text": "a"},
                "b": {"t": 2.2, "type": "beeps", "kind": "collision-left", "clock": 12, "text": "b"},
            }
        ],
        "onlyA": [],
        "onlyB": [],
    }


def test_match_events_empty_sides() -> None:
    from lab.features.compare import match_events

    assert match_events([], [_sp(1.0, "x")]) == {"same": 0, "changed": [], "onlyA": [], "onlyB": [{"t": 1.0, "type": "speech", "text": "x"}]}
    assert match_events([], []) == {"same": 0, "changed": [], "onlyA": [], "onlyB": []}


def test_same_compares_text_for_speech_and_kind_clock_for_beeps() -> None:
    from lab.features.compare import _same

    assert _same(_sp(0, "a"), _sp(5, "a")) is True
    assert _same(_sp(0, "a"), _sp(0, "b")) is False
    assert _same(_bp(0, "k", 1, "a"), _bp(0, "k", 1, "zz")) is True
    assert _same(_bp(0, "k", 1, "a"), _bp(0, "k", 2, "a")) is False


def test_flatten_keeps_empty_dicts_and_lists_as_leaves() -> None:
    from lab.features.compare import _flatten

    out: dict[str, Any] = {}
    _flatten("", {"a": {"b": 1, "c": {}}, "d": [1, 2], "e": None}, out)
    assert out == {"a.b": 1, "a.c": {}, "d": [1, 2], "e": None}
    out2: dict[str, Any] = {}
    _flatten("p", 3, out2)
    assert out2 == {"p": 3}


def test_settings_diff_rows_are_sorted_and_cover_the_three_sections() -> None:
    from lab.features.compare import _settings_diff

    a = {"settings": {"x": 1, "y": {"z": 2}}, "resolved": {"r": 1}}
    b = {"settings": {"x": 1, "y": {"z": 3}, "w": 0}, "overrides": {"o": {"p": True}}}
    assert _settings_diff(a, b) == [
        {"key": "overrides", "a": {}, "b": None},
        {"key": "overrides.o.p", "a": None, "b": True},
        {"key": "resolved", "a": None, "b": {}},
        {"key": "resolved.r", "a": 1, "b": None},
        {"key": "settings.w", "a": None, "b": 0},
        {"key": "settings.y.z", "a": 2, "b": 3},
    ]
    assert _settings_diff({}, {}) == []
