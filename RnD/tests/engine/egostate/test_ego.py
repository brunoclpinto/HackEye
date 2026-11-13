"""Characterisation tests for engine.egostate.ego.Ego (v26.3.0 p2-11).

Every expected literal was produced by running the legacy ``collision._Ego`` in the hackeye-rnd image on the
pre-move code (update sequence printed step by step), not computed by hand.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

import collision

SPEED_CFG: dict[str, Any] = {"speedMinTracks": 2, "speedEma": 0.3}
HEADING_CFG: dict[str, Any] = {"headingDeg": 20.0, "sustainSeconds": 2.0, "referenceTauSeconds": 4.0}
CFG: dict[str, Any] = {**SPEED_CFG, **HEADING_CFG}


def _same(actual: float | None, expected: float | None) -> None:
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)


def test_facade_identity() -> None:
    from engine.egostate.ego import Ego

    assert collision._Ego is Ego


def test_attribute_list_and_defaults() -> None:
    from engine.egostate.ego import Ego

    fields = [(f.name, f.default) for f in dataclasses.fields(Ego)]
    assert fields == [
        ("speed", None),
        ("speed_t", -math.inf),
        ("cadence", None),
        ("heading", None),
        ("ref_heading", None),
        ("exceed_since", None),
    ]
    fresh = Ego()
    assert sorted(vars(fresh)) == sorted(f.name for f in dataclasses.fields(Ego))
    assert fresh.speed is None
    assert fresh.speed_t == -math.inf
    assert fresh.cadence is None
    assert fresh.heading is None
    assert fresh.ref_heading is None
    assert fresh.exceed_since is None


def test_update_speed_sequence_pins_state_per_step() -> None:
    from engine.egostate.ego import Ego

    ego = Ego()
    # (closings, t, expected speed, expected speed_t)
    steps: list[tuple[list[float], float, float | None, float]] = [
        ([1.0], 0.0, None, -math.inf),  # below speedMinTracks: nothing learned
        ([1.0, 1.4, 1.2], 1.0, 1.2, 1.0),  # first estimate = median
        ([2.0, 2.2], 2.0, 1.47, 2.0),  # EMA: 0.7 * 1.2 + 0.3 * 2.1
        ([], 5.0, 1.47, 2.0),  # 3 s without tracks: not stale yet
        ([], 7.5, None, 2.0),  # 5.5 s without tracks: stale, speed dropped
        ([], 9.0, None, 2.0),  # already None: nothing to drop
        ([3.0, 3.5, 2.5, 3.0], 9.5, 3.0, 9.5),  # fresh start after a stale drop
    ]
    for closings, t, expected_speed, expected_t in steps:
        ego.update_speed(closings, t, CFG)
        _same(ego.speed, expected_speed)
        assert ego.speed_t == expected_t
        assert ego.heading is None
        assert ego.ref_heading is None
        assert ego.exceed_since is None


def test_update_heading_sequence_pins_state_per_step() -> None:
    from engine.egostate.ego import Ego

    ego = Ego()
    # (heading, t, dt, expected return, heading, ref_heading, exceed_since)
    steps: list[tuple[float | None, float, float, bool, float | None, float | None, float | None]] = [
        (None, 0.0, 0.1, False, None, None, None),  # no heading: nothing learned
        (90.0, 0.1, 0.1, False, 90.0, 90.0, None),  # first heading seeds the reference
        (100.0, 0.2, 0.1, False, 100.0, 90.25, None),  # within headingDeg
        (130.0, 1.0, 0.5, False, 130.0, 95.21875, 1.0),  # off by more than 20 deg: timer starts
        (131.0, 2.0, 1.0, False, 131.0, 104.1640625, 1.0),  # still off, 1 s < sustainSeconds
        (90.0, 2.5, 0.5, False, 90.0, 102.3935546875, None),  # back within: timer cleared
        (150.0, 3.0, 0.1, False, 150.0, 103.5837158203125, 3.0),  # off again: timer restarts
        (150.0, 4.0, 0.1, False, 150.0, 104.7441229248047, 3.0),  # 1 s < sustainSeconds
        (150.0, 5.0, 0.1, True, 150.0, 150.0, None),  # 2 s sustained: fires, reference jumps
        (150.0, 5.1, 0.1, False, 150.0, 150.0, None),  # agrees with the new reference
        (None, 5.2, 0.1, False, None, 150.0, None),  # no heading: reference and timer held
        (60.0, 6.0, 0.2, False, 60.0, 145.5, 6.0),  # off again: timer starts from 6.0
    ]
    for heading, t, dt, expected_ret, exp_heading, exp_ref, exp_exceed in steps:
        assert ego.update_heading(heading, t, CFG, dt) is expected_ret
        assert ego.heading == exp_heading
        _same(ego.ref_heading, exp_ref)
        _same(ego.exceed_since, exp_exceed)
        assert ego.speed is None
        assert ego.speed_t == -math.inf
