"""Characterisation tests for engine.speech.policy / engine.speech.movers (v26.3.0 p3-13).

Expected literals were produced by running the legacy ``collision.SpeechPolicy`` (hackeye-rnd image)
through the same scenario driver; the engine modules are imported inside each test.

The 40-tick sequence is a reduced scripted driver built from the helpers of the existing policy tests
(``_item`` and ``_tracks`` of ``tests/test_collision.py``, the movers of ``tests/test_collision_v26213.py``
and ``tests/test_collision_v26214.py``), called in the pipeline's order each tick (observe_movers, step,
away_speech, motion_speech). The review-11 fixture window was not driven.
"""

from __future__ import annotations

import copy
import importlib
import math
from typing import Any

import pytest

import collision as col

_tc: Any = importlib.import_module("tests.test_collision")
_item: Any = _tc._item
_tracks: Any = _tc._tracks

DT = 0.25
T0 = 10.0
N_TICKS = 40


def _config() -> dict[str, Any]:
    cfg: dict[str, Any] = copy.deepcopy(col.load_config())
    cfg["personSplit"]["enabled"] = False
    cfg["speech"]["away"]["enabled"] = True
    cfg["speech"]["predictive"]["enabled"] = False
    cfg["motion"]["enabled"] = True
    return cfg


def _building() -> Any:
    it = _item(1, "context", 9, "building", clock=2, dist=6.0)
    it.lateral_m, it.family = 3.0, "building"
    return it


def _pole(k: int) -> Any:
    steps = max(2.0, 14.0 - 0.4 * k)
    it = _item(2, "danger", steps, "pole", clock=12, urgency="final" if steps <= 3 else "danger")
    it.thin, it.family, it.distance_m, it.collision = True, "pole", steps * 0.7, True
    return it


def _leaver(k: int, t: float) -> Any:
    """Track 6: stands in the lane (collision item) for 12 ticks, then walks out sideways (v26.2.13 "away")."""
    lat = 0.3 if k < 12 else 0.3 + 0.12 * (k - 11)
    col_item = abs(lat) <= 0.6
    it = _item(6, "danger" if col_item else "none", 7, "person", group="moving", clock=12, dist=5.0)
    it.class_name, it.people, it.moving, it.collision, it.lateral_m, it.closing = (
        "person",
        True,
        k >= 6,
        col_item,
        lat,
        0.2,
    )
    it.clock_q, it.clock_text, it.receding = 1, col.clock_text(1), False
    it.role = "danger" if col_item else "none"
    return it


def _walker(k: int) -> Any:
    """Track 7: a person walking away ahead in the lane (v26.2.14 "moving away")."""
    it = _item(7, "none", 4.1, "person", group="moving")
    it.people, it.moving, it.own_ok, it.settled = True, True, True, True
    it.lateral_m, it.own, it.own_closing = 0.1, (1.0, 0.05, 0.1), 0.0
    it.distance_m = 4.1 * 0.74
    return it


def _drive(policy_cls: Any) -> tuple[Any, Any, list[tuple[int, float, str | None, str | None]]]:
    cfg = _config()
    world = col._WorldMemory(cfg["memory"])
    policy = policy_cls(cfg)
    policy.world, policy.summary = world, False
    policy.ego_u = None
    tr = _tracks(1, 2, 6, 7)
    out: list[tuple[int, float, str | None, str | None]] = []
    for k in range(N_TICKS):
        t = T0 + k * DT
        world.advance(t, DT, 1.26, 0.0)
        items = [_building(), _pole(k), _leaver(k, t), _walker(k)]
        world.link(items[:2], tr, t)
        for it in items:
            if it.track_id == 6:
                tr[6].lhist.append((t, it.lateral_m, it.distance_m, 0.0, 0.0))
        policy.observe_movers(t, items, tr)
        speech = policy.step(t, items, tr, True)
        if speech is None:
            speech = policy.away_speech(t, items)
        if speech is None:
            speech = policy.motion_speech(t, items)
        if speech is not None:
            out.append((k, t, speech["text"], speech["role"]))
    return policy, world, out


ATTRS = [
    "after_danger_s",
    "ahead_cfg",
    "away_cfg",
    "away_on",
    "away_state",
    "cfg",
    "coloc_m",
    "confirm",
    "context_speak",
    "cut_cfg",
    "danger_first",
    "danger_label_t",
    "ego_meas",
    "ego_u",
    "feature_gap_s",
    "feature_label_t",
    "feature_new_steps",
    "final_steps",
    "first_summary",
    "forget_s",
    "known_classes",
    "known_m",
    "known_on",
    "known_quarters",
    "known_rel_s",
    "known_s",
    "known_steps",
    "known_walls",
    "landmarks",
    "lane_half",
    "last_beep_t",
    "last_danger_t",
    "last_prio_t",
    "last_say_t",
    "last_t",
    "last_thin_seen",
    "max_entries",
    "max_items",
    "memory",
    "min_voice",
    "mo_again_gap",
    "mo_again_steps",
    "motion_on",
    "motion_wait_s",
    "motion_wait_steps",
    "mover_state",
    "pending_since",
    "pred_clock_hold",
    "pred_latency",
    "pred_max_adv",
    "pred_meas_floor",
    "pred_min_steps",
    "pred_on",
    "pred_passed",
    "pred_stats",
    "pred_wps",
    "quiet_slot",
    "quiet_t",
    "reann_gap_s",
    "reann_on",
    "reann_quarters",
    "reann_steps",
    "speech_rate",
    "stationary",
    "summary",
    "summary_since",
    "surface_pending",
    "thin_armed",
    "thin_range",
    "thin_rearm_s",
    "travel_steps",
    "world",
    "zone_classes",
    "zone_half",
    "zone_on",
]

EXPECTED_SPOKEN = [
    (0, 10.0, "person standing at 12:15 in 7, pole at 12 in 14", "danger"),
    (5, 11.25, "person moving away at 12 in 4", "danger"),
    (20, 15.0, "person at 12:15 moved away", "danger"),
]
MOVERS = ("observe_movers", "away_speech", "motion_speech")
REST = (
    "__init__",
    "_view",
    "_voice",
    "_reannounce",
    "_closing_again",
    "_zone_ok",
    "_compose",
    "_with_prediction",
    "_feature_allowed",
    "_motion_pending",
    "_danger_recent",
    "_gap_ok",
    "_event",
    "step",
)


def test_facade_identity_of_the_class_and_the_movers_methods() -> None:
    from engine.speech import movers, policy

    assert col.SpeechPolicy is policy.SpeechPolicy
    for name in MOVERS:
        assert getattr(col.SpeechPolicy, name) is getattr(movers.MoversMixin, name)
        assert name not in vars(policy.SpeechPolicy)


def test_the_remaining_methods_are_defined_on_the_policy_class() -> None:
    from engine.speech import policy

    for name in REST:
        assert name in vars(policy.SpeechPolicy), name


def test_mro() -> None:
    from engine.speech.policy import SpeechPolicy

    assert [c.__name__ for c in SpeechPolicy.__mro__] == [
        "SpeechPolicy",
        "TextMixin",
        "ContextMixin",
        "WallsMixin",
        "MoversMixin",
        "object",
    ]


def test_instance_attribute_list_after_init() -> None:
    from engine.speech.policy import SpeechPolicy

    assert sorted(vars(SpeechPolicy(_config()))) == ATTRS


def test_forty_tick_sequence_pins_texts_and_times() -> None:
    from engine.speech.policy import SpeechPolicy

    _, _, spoken = _drive(SpeechPolicy)
    assert len(spoken) == len(EXPECTED_SPOKEN)
    for got, want in zip(spoken, EXPECTED_SPOKEN, strict=True):
        assert got[0] == want[0] and got[2:] == want[2:]
        assert got[1] == pytest.approx(want[1], rel=1e-12, abs=1e-12)


def test_forty_tick_sequence_final_state() -> None:
    from engine.speech.policy import SpeechPolicy

    pol, _, _ = _drive(SpeechPolicy)
    assert pol.away_state[6] == {
        "col_t": -math.inf,
        "dan_q": 1,
        "still_t0": None,
        "leave_t0": None,
        "fired_t": 15.0,
        "static_at_leave": False,
    }
    assert pol.away_state[7] == {
        "col_t": -math.inf,
        "dan_q": 0,
        "still_t0": None,
        "leave_t0": None,
        "fired_t": -math.inf,
    }
    assert pol.mover_state[7] == {
        "out_t": -math.inf,
        "out_since": None,
        "cut_run": 0,
        "cut_fired": -math.inf,
        "ahead_t0": 10.25,
        "ahead_done": True,
        "ahead_fired": 11.25,
    }
    assert pol.mover_state[6]["out_t"] == pytest.approx(19.75, rel=1e-12) and pol.mover_state[6][
        "out_since"
    ] == pytest.approx(13.75, rel=1e-12)
    assert pol.last_say_t == pytest.approx(17.0, rel=1e-12) and pol.last_danger_t == pytest.approx(17.0, rel=1e-12)
    assert pol.last_t == pytest.approx(17.0, rel=1e-12)
    assert sorted(pol.danger_first.items()) == [(2, 10.0), (6, 10.0)]
    assert pol.memory == {}
    assert pol.pred_stats == {"phrases": 0, "changed": 0, "dropped": 0}


def test_mark_said_path_stores_steps_and_time_in_the_world_entry() -> None:
    from engine.speech.policy import SpeechPolicy

    _, world, _ = _drive(SpeechPolicy)
    entries = world.entries
    assert list(entries) == [2]
    assert entries[2]["said"] == (14.0, 10.0)
    assert entries[2]["danger"] is True and entries[2]["named"] is True
