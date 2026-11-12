"""Equivalence tests for engine.core.pose.DeadReckoner (v26.3.0 p1-06).

The expected values come from running the legacy ``collision._WorldMemory.advance`` side by side on the same
input sequence; the engine module is imported inside each test (it does not exist yet).
"""

from __future__ import annotations

import importlib
import math
from typing import Any

import numpy as np
import pytest

import collision


def _sequence(seed: int, steps: int = 300) -> list[tuple[float, float, float | None, float | None, Any]]:
    rng = np.random.default_rng(seed)
    out: list[tuple[float, float, float | None, float | None, Any]] = []
    t = 0.0
    heading = 0.0
    for _ in range(steps):
        dt = float(rng.uniform(0.05, 0.4))
        if rng.random() < 0.05:
            dt += float(rng.uniform(6.0, 12.0))  # a gap longer than hold_s: the speed hold expires
        t += dt
        heading += float(rng.normal(0.0, 8.0))
        speed: float | None = None if rng.random() < 0.10 else float(rng.uniform(0.0, 2.0))
        hdg: float | None = None if rng.random() < 0.05 else heading
        pose = None
        if rng.random() < 0.05:
            pose = (float(rng.normal(0, 5)), float(rng.normal(0, 5)), float(rng.uniform(-180, 180)))
        out.append((t, dt, speed, hdg, pose))
    return out


def _same(legacy: Any, new: Any) -> None:
    assert new.x == legacy.x
    assert new.y == legacy.y
    assert new.theta == legacy.theta
    assert new.speed == legacy.speed
    assert new.speed_t == legacy.speed_t


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_equivalence_with_world_memory(seed: int) -> None:
    pose_mod = importlib.import_module("engine.core.pose")
    legacy = collision._WorldMemory({}, True)
    new = pose_mod.DeadReckoner(hold_s=5.0)
    for t, dt, speed, hdg, pose in _sequence(seed):
        legacy.advance(t, dt, speed, hdg, pose)
        new.advance(t, dt, speed, hdg, pose)
        _same(legacy, new)


def test_defaults() -> None:
    pose_mod = importlib.import_module("engine.core.pose")
    d = pose_mod.DeadReckoner()
    assert d.x == 0.0
    assert d.y == 0.0
    assert d.theta is None
    assert d.speed is None
    assert d.speed_t == -math.inf
    assert d.hold_s == 5.0


def test_custom_hold_s() -> None:
    pose_mod = importlib.import_module("engine.core.pose")
    legacy = collision._WorldMemory({"speedHoldSeconds": 1.0})
    new = pose_mod.DeadReckoner(hold_s=1.0)
    assert new.hold_s == legacy.hold_s == 1.0
    for t, dt, speed, hdg, pose in _sequence(7):
        legacy.advance(t, dt, speed, hdg, pose)
        new.advance(t, dt, speed, hdg, pose)
        _same(legacy, new)
