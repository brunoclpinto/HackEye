"""Characterisation tests for engine.motion (v26.3.0 p3-10): ``robust_speed``, ``motion_state`` and ``OwnMotion``.

Every expected literal was printed by the legacy ``collision._robust_speed`` / ``_motion_state`` / ``_OwnMotion`` in the
hackeye-rnd image, fed by the ``_*_cases`` / ``_run_*`` helpers of this file (the inputs follow
``tests/test_collision_v26113.py``, ``test_collision_v26112.py``, ``test_collision_v26116.py`` and
``test_collision_v26214.py``). The engine modules are imported inside each test (they do not exist yet).
"""

from __future__ import annotations

import types
from typing import Any

import pytest

import collision

ROLES: dict[str, Any] = {
    "approachingMps": 0.4,
    "motionLeaveMps": 0.3,
    "standingMps": 0.3,
    "standingHoldSeconds": 1.0,
    "standingMaxCrossMps": 0.6,
    "vehicleApproachingMps": 2.0,
}

MO: dict[str, Any] = {
    "enabled": True,
    "windowS": 1.2,
    "minPoints": 4,
    "minSpanS": 0.6,
    "linkM": 1.5,
    "linkS": 0.7,
    "scatterFloorM": 0.12,
    "minSpeedMps": {"person": 0.4, "vehicle": 0.8},
    "sigmaK": 1.0,
    "sigmaMaxMps": 0.5,
    "sideMps": 0.5,
    "standingMps": 0.3,
    "nearPassS": 4.0,
    "nearPassM": 1.3,
    "nearPassMinClosingMps": 0.3,
}

OWN_ATTRS: list[str] = [
    "on",
    "cfg",
    "win",
    "min_pts",
    "min_span",
    "link_m",
    "link_s",
    "floor",
    "hist",
    "last",
    "x",
    "y",
    "theta",
    "known",
    "cache",
]
U = 1.3


def _eq(got: Any, exp: Any) -> None:
    """Deep compare: floats with ``approx(rel=1e-12, abs=1e-12)``, everything else exactly (tuples and lists alike)."""
    if isinstance(exp, float):
        assert isinstance(got, float)
        assert got == pytest.approx(exp, rel=1e-12, abs=1e-12)
    elif isinstance(exp, (list, tuple)):
        assert isinstance(got, (list, tuple))
        assert len(got) == len(exp)
        for g, e in zip(got, exp, strict=True):
            _eq(g, e)
    else:
        assert got == exp
        assert type(got) is type(exp)


# ---- robust_speed -------------------------------------------------------------------------------------------------


def _robust_cases() -> list[tuple[float, list[tuple[float, float]]]]:
    spike = [1.1] * 12 + [2.07] + [1.1] * 2
    step = [1.0 if i < 20 else 2.0 for i in range(40)]
    return [
        (3.0, [(0.17 * i, s) for i, s in enumerate(spike)]),
        (1.0, [(0.17 * i, s) for i, s in enumerate(step)]),
        (0.0, [(0.5 * i, 1.0 + i) for i in range(4)]),
        (-5.0, [(0.5 * i, 1.0 + i) for i in range(3)]),
    ]


def _run_robust(
    fn: Any, window: float, steps: list[tuple[float, float]]
) -> tuple[list[float], list[list[tuple[float, float]]], bool]:
    hist: list[tuple[float, float]] = []
    out: list[float] = []
    snaps: list[list[tuple[float, float]]] = []
    same = True
    for t, s in steps:
        before = id(hist)
        out.append(fn(hist, t, s, window))
        same = same and id(hist) == before
        snaps.append(list(hist))
    return out, snaps, same


ROBUST_EXPECTED: list[Any] = [
    (
        [1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1],
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
        [
            (0.0, 1.1),
            (0.17, 1.1),
            (0.34, 1.1),
            (0.51, 1.1),
            (0.68, 1.1),
            (0.8500000000000001, 1.1),
            (1.02, 1.1),
            (1.1900000000000002, 1.1),
            (1.36, 1.1),
            (1.53, 1.1),
            (1.7000000000000002, 1.1),
            (1.87, 1.1),
            (2.04, 2.07),
            (2.21, 1.1),
            (2.3800000000000003, 1.1),
        ],
    ),
    (
        [
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.5,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
        ],
        [
            1,
            2,
            3,
            4,
            5,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
            6,
        ],
        [(5.78, 2.0), (5.95, 2.0), (6.12, 2.0), (6.29, 2.0), (6.460000000000001, 2.0), (6.630000000000001, 2.0)],
    ),
    ([1.0, 2.0, 3.0, 4.0], [1, 1, 1, 1], [(1.5, 4.0)]),
    ([1.0, 2.0, 3.0], [1, 1, 1], [(1.0, 3.0)]),
]


# ---- motion_state -------------------------------------------------------------------------------------------------


def _track() -> Any:
    return types.SimpleNamespace(mstate=None, still_t0=None)


# (name, vehicle, [(t, along, side, cross)])
def _state_cases() -> list[tuple[bool, list[Any]]]:
    return [
        (False, [(0.17 * i, 0.1, 0.0, None) for i in range(8)] + [(1.5, 0.35, 0.0, None), (1.7, 0.45, 0.0, None)]),
        (False, [(0.17 * i, 0.35, 0.0, None) for i in range(10)]),
        (
            False,
            [(0.17 * i, 0.05, 0.0, None) for i in range(5)]
            + [(0.9, 0.36, 0.0, None)]
            + [(1.0 + 0.17 * i, 0.05, 0.0, None) for i in range(7)],
        ),
        (False, [(0.17 * i, -0.6, 0.0, None) for i in range(10)] + [(2.0, -0.32, 0.0, None), (2.2, -0.2, 0.0, None)]),
        (False, [(0.17 * i, -0.1, 0.0, -0.7) for i in range(10)]),
        (False, [(0.17 * i, -0.1, 0.0, -0.3) for i in range(8)] + [(3.0, 0.0, -3.0, None), (3.2, 0.0, 0.0, None)]),
        (False, [(0.17 * i, 0.58, 0.0, None) for i in range(3)]),
        (
            True,
            [
                (10.0, 0.6, 0.0, None),
                (10.1, 1.5, 0.0, None),
                (10.2, 2.4, 0.0, None),
                (10.3, 7.0, 0.0, None),
                (10.4, 1.5, 0.0, None),
                (10.5, 1.2, 0.0, None),
            ],
        ),
        (True, [(10.0, -1.5, 0.0, None), (10.1, -2.4, 0.0, None), (10.2, -1.5, 0.0, None), (10.3, -1.3, 0.0, None)]),
    ]


def _run_states(
    fn: Any, vehicle: bool, steps: list[tuple[float, float, float, float | None]]
) -> list[tuple[str | None, float | None]]:
    tr = _track()
    out: list[tuple[str | None, float | None]] = []
    for t, along, side, cross in steps:
        tr.mstate = fn(tr, t, along, side, cross, ROLES, vehicle)
        out.append((tr.mstate, tr.still_t0))
    return out


def _vehicle_prev_cases() -> list[tuple[float, bool, str | None]]:
    return [
        (0.6, False, None),
        (1.5, True, None),
        (2.4, True, None),
        (7.0, True, None),
        (1.5, True, "approach"),
        (1.2, True, "approach"),
    ]


def _run_vehicle_prev(fn: Any) -> list[tuple[str | None, float | None]]:
    out: list[tuple[str | None, float | None]] = []
    for along, vehicle, prev in _vehicle_prev_cases():
        tr = _track()
        tr.mstate = prev
        out.append((fn(tr, 10.0, along, 0.0, None, ROLES, vehicle), tr.still_t0))
    return out


STATE_EXPECTED: list[Any] = [
    [
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        ("still", 0.0),
        ("still", 0.0),
        ("still", 0.0),
        ("approach", None),
    ],
    [
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
    ],
    [
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        (None, None),
        (None, 1.0),
        (None, 1.0),
        (None, 1.0),
        (None, 1.0),
        (None, 1.0),
        (None, 1.0),
        ("still", 1.0),
    ],
    [
        ("recede", None),
        ("recede", None),
        ("recede", None),
        ("recede", None),
        ("recede", None),
        ("recede", None),
        ("recede", None),
        ("recede", None),
        ("recede", None),
        ("recede", None),
        ("recede", None),
        (None, 2.2),
    ],
    [
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
    ],
    [
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        (None, 0.0),
        ("still", 0.0),
        ("still", 0.0),
        ("side", None),
        (None, 3.2),
    ],
    [("approach", None), ("approach", None), ("approach", None)],
    [(None, None), (None, None), ("approach", None), ("approach", None), ("approach", None), (None, None)],
    [(None, None), ("recede", None), ("recede", None), (None, None)],
]
VEHICLE_PREV_EXPECTED: list[Any] = [
    ("approach", None),
    (None, None),
    ("approach", None),
    ("approach", None),
    ("approach", None),
    (None, None),
]


# ---- OwnMotion ----------------------------------------------------------------------------------------------------


def _mover(track_id: int = 1, cls: str = "person", fast: bool = False) -> Any:
    return types.SimpleNamespace(
        track_id=track_id,
        class_name=cls,
        fast=fast,
        moving=None,
        approaching=False,
        receding=False,
        own=None,
        own_ok=False,
        own_closing=None,
        near_pass=False,
        from_side="",
        distance_m=0.0,
        lateral_m=0.0,
        clipped=False,
        from_depth=False,
        jumped=False,
    )


def _fields(it: Any) -> tuple[Any, ...]:
    return (it.own, it.own_ok, it.own_closing, it.near_pass, it.from_side, it.moving, it.approaching, it.receding)


# (path, cls, fast, n, jitter, preset moving/approaching)
def _own_scenarios() -> list[tuple[str, Any, str, bool, int, list[float] | None, bool]]:
    return [
        ("toward-1.0L", lambda s: (-1.0, 9.0 - 1.0 * s), "person", False, 8, None, False),
        ("toward-2.5L", lambda s: (-2.5, 9.0 - 1.0 * s), "person", False, 8, None, False),
        ("toward-far", lambda s: (-1.0, 20.0 - 1.0 * s), "person", False, 8, None, False),
        ("stands", lambda s: (0.0, 6.0), "person", False, 8, None, True),
        ("walks-away", lambda s: (0.0, 6.0 + 1.5 * s), "person", False, 8, None, False),
        ("parked-vehicle", lambda s: (-1.5, 8.0), "vehicle", True, 8, None, True),
        ("jitter-vehicle", lambda s: (-1.5, 8.0), "vehicle", True, 8, [0.0, 2.5, -2.0, 3.0, -2.5, 1.5], True),
        ("vehicle-fast-no-preset", lambda s: (-1.5, 15.0 - 4.0 * s), "vehicle", True, 8, None, False),
        ("vehicle-fast-preset", lambda s: (-1.5, 15.0 - 4.0 * s), "vehicle", True, 8, None, True),
        ("from-right", lambda s: (1.5 - 0.9 * s, 9.0 - 0.8 * s), "person", False, 8, None, False),
        ("from-left", lambda s: (-1.5 + 0.9 * s, 9.0 - 0.8 * s), "person", False, 8, None, False),
        ("away-sideways", lambda s: (-1.5 - 0.9 * s, 9.0 - 0.8 * s), "person", False, 8, None, False),
    ]


def _run_own(
    cls_: Any, scen: tuple[str, Any, str, bool, int, list[float] | None, bool]
) -> tuple[list[tuple[Any, ...]], Any, tuple[float, float, float | None, bool]]:
    _, path, cls, fast, n, jitter, preset = scen
    om = cls_(MO)
    dt = 1 / 6
    rows: list[tuple[Any, ...]] = []
    est: Any = None
    for k in range(n):
        t = 10.0 + k * dt
        om.advance(t, dt, U, 0.0)
        wx, wy = path(t - 10.0)
        it = _mover(1, cls, fast)
        it.distance_m = wy - om.y + (0.0 if jitter is None else jitter[k % len(jitter)])
        it.lateral_m = wx - om.x
        om.observe(it, t)
        if preset:
            it.moving, it.approaching = True, True
        om.classify(it, t, U)
        rows.append(_fields(it))
        est = om.estimate(1, t)
    return rows, est, (om.x, om.y, om.theta, om.known)


def _run_fragment(cls_: Any) -> tuple[Any, Any, int]:
    om = cls_(MO)
    t = 10.0
    for k in range(10):
        t = 10.0 + k / 6
        om.advance(t, 1 / 6, U, 0.0)
        it = _mover(1 if k < 5 else 2)
        it.distance_m, it.lateral_m = 9.0 - 1.0 * (k / 6) - om.y, -1.0
        om.observe(it, t)
    return om.estimate(2, t), om.estimate(1, t), len(om.hist[2])


def _run_edges(cls_: Any) -> tuple[Any, ...]:
    om = cls_({})
    cfg_defaults = (om.on, om.win, om.min_pts, om.min_span, om.link_m, om.link_s, om.floor)
    om.advance(0.0, 0.1, 1.0, None)  # heading unknown
    st1 = (om.theta, om.known, om.x, om.y)
    om.advance(0.1, 0.1, None, 90.0)  # speed unknown
    st2 = (om.theta, om.known, om.x, om.y)
    om.advance(0.2, 0.1, 2.0, 90.0)
    st3 = (om.theta, om.known, round(om.x, 12), round(om.y, 12))
    it = _mover()
    it.jumped = True
    om.observe(it, 0.2)
    skipped = dict(om.hist)
    om2 = cls_(MO)
    est_none = om2.estimate(1, 0.0)
    return cfg_defaults, st1, st2, st3, skipped, est_none


OWN_EXPECTED: list[Any] = [
    (
        [
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            ((-1.0, 0.0, 0.228), True, 2.3, True, "", True, True, False),
            ((-1.0, 0.0, 0.172), True, 2.3, True, "", True, True, False),
            ((-1.0, 0.0, 0.136), True, 2.3, True, "", True, True, False),
            ((-1.0, 0.0, 0.111), True, 2.3, True, "", True, True, False),
        ],
        (-1.0, 0.0, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            ((-1.0, 0.0, 0.228), True, 2.3, False, "", True, True, False),
            ((-1.0, 0.0, 0.172), True, 2.3, False, "", True, True, False),
            ((-1.0, 0.0, 0.136), True, 2.3, False, "", True, True, False),
            ((-1.0, 0.0, 0.111), True, 2.3, False, "", True, True, False),
        ],
        (-1.0, 0.0, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            ((-1.0, 0.0, 0.228), True, 2.3, False, "", True, True, False),
            ((-1.0, 0.0, 0.172), True, 2.300000000000001, False, "", True, True, False),
            ((-1.0, 0.0, 0.136), True, 2.3, False, "", True, True, False),
            ((-1.0, 0.0, 0.111), True, 2.3, False, "", True, True, False),
        ],
        (-1.0, 0.0, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            ((0.0, 0.0, 0.228), True, 1.3, False, "", False, False, False),
            ((0.0, 0.0, 0.172), True, 1.3, False, "", False, False, False),
            ((0.0, 0.0, 0.136), True, 1.3, False, "", False, False, False),
            ((0.0, 0.0, 0.111), True, 1.3, False, "", False, False, False),
        ],
        (0.0, 0.0, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            ((1.5, 0.0, 0.228), True, -0.20000000000000062, False, "", True, False, True),
            ((1.5, 0.0, 0.172), True, -0.2000000000000013, False, "", True, False, True),
            ((1.5, 0.0, 0.136), True, -0.19999999999999996, False, "", True, False, True),
            ((1.5, 0.0, 0.111), True, -0.20000000000000062, False, "", True, False, True),
        ],
        (1.5000000000000007, 0.0, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            ((0.0, 0.0, 0.228), True, 1.3, False, "", False, False, False),
            ((0.0, 0.0, 0.172), True, 1.3, False, "", False, False, False),
            ((0.0, 0.0, 0.136), True, 1.3, False, "", False, False, False),
            ((0.0, 0.0, 0.111), True, 1.3, False, "", False, False, False),
        ],
        (0.0, 0.0, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            ((-2.625, 0.0, 3.165), True, None, False, "", None, False, False),
            ((-1.5, 0.0, 3.987), True, None, False, "", None, False, False),
            ((-1.5, 0.0, 2.522), True, None, False, "", None, False, False),
            ((0.0, 0.0, 2.402), True, None, False, "", None, False, False),
        ],
        (0.0, 0.0, 2.4020865398648734),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            ((-4.0, 0.0, 0.228), True, 5.3, False, "", None, False, False),
            ((-4.0, 0.0, 0.172), True, 5.3, False, "", None, False, False),
            ((-4.0, 0.0, 0.136), True, 5.3, False, "", None, False, False),
            ((-4.0, 0.0, 0.111), True, 5.3, False, "", None, False, False),
        ],
        (-4.0, 0.0, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            (None, False, None, False, "", True, True, False),
            ((-4.0, 0.0, 0.228), True, 5.3, False, "", True, True, False),
            ((-4.0, 0.0, 0.172), True, 5.3, False, "", True, True, False),
            ((-4.0, 0.0, 0.136), True, 5.3, False, "", True, True, False),
            ((-4.0, 0.0, 0.111), True, 5.3, False, "", True, True, False),
        ],
        (-4.0, 0.0, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            ((-0.8, -0.9, 0.228), True, 2.1000000000000005, False, "right", True, True, False),
            ((-0.8, -0.9, 0.172), True, 2.1000000000000005, False, "right", True, True, False),
            ((-0.8, -0.9, 0.136), True, 2.1000000000000005, False, "right", True, True, False),
            ((-0.8, -0.9, 0.111), True, 2.1000000000000005, False, "right", True, True, False),
        ],
        (-0.8000000000000007, -0.9000000000000001, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            ((-0.8, 0.9, 0.228), True, 2.1000000000000005, False, "left", True, True, False),
            ((-0.8, 0.9, 0.172), True, 2.1000000000000005, False, "left", True, True, False),
            ((-0.8, 0.9, 0.136), True, 2.1000000000000005, False, "left", True, True, False),
            ((-0.8, 0.9, 0.111), True, 2.1000000000000005, False, "left", True, True, False),
        ],
        (-0.8000000000000007, 0.9000000000000001, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
    (
        [
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            (None, False, None, False, "", None, False, False),
            ((-0.8, -0.9, 0.228), True, 2.1000000000000005, False, "", True, True, False),
            ((-0.8, -0.9, 0.172), True, 2.1000000000000005, False, "", True, True, False),
            ((-0.8, -0.9, 0.136), True, 2.1000000000000005, False, "", True, True, False),
            ((-0.8, -0.9, 0.111), True, 2.1000000000000005, False, "", True, True, False),
        ],
        (-0.8000000000000007, -0.8999999999999999, 0.11109841197270619),
        (0.0, 1.7333333333333338, 0.0, True),
    ),
]
FRAGMENT_EXPECTED: Any = ((-1.0, 0.0, 0.11109841197270619), None, 8)
EDGES_EXPECTED: Any = (
    (False, 1.2, 4, 0.6, 1.5, 0.7, 0.12),
    (None, False, 0.0, 0.0),
    (90.0, False, 0.0, 0.0),
    (90.0, True, 0.2, 0.0),
    {},
    None,
)


# ---- tests --------------------------------------------------------------------------------------------------------


def test_facade_identity() -> None:
    from engine.motion import own, state

    assert collision._robust_speed is state.robust_speed
    assert collision._motion_state is state.motion_state
    assert collision._OwnMotion is own.OwnMotion


def test_package_reexports() -> None:
    import engine.motion as pkg
    from engine.motion import own, state

    assert pkg.robust_speed is state.robust_speed
    assert pkg.motion_state is state.motion_state
    assert pkg.OwnMotion is own.OwnMotion
    for name in ("robust_speed", "motion_state", "OwnMotion"):
        assert name in pkg.__all__
    assert isinstance(pkg.own, types.ModuleType)
    assert isinstance(pkg.state, types.ModuleType)


def test_own_motion_attribute_list() -> None:
    from engine.motion.own import OwnMotion

    om = OwnMotion(MO)
    assert list(vars(om)) == OWN_ATTRS
    assert om.on is True and om.cfg is MO and om.win == 1.2 and om.min_pts == 4 and om.min_span == 0.6
    assert om.hist == {} and om.last == {} and om.cache == {}
    assert om.x == 0.0 and om.y == 0.0 and om.theta is None and om.known is False
    off = OwnMotion({})
    assert off.on is False and (off.win, off.min_pts, off.min_span, off.link_m, off.link_s, off.floor) == (
        1.2,
        4,
        0.6,
        1.5,
        0.7,
        0.12,
    )


@pytest.mark.parametrize("idx", range(4))
def test_robust_speed_trims_hist_in_place(idx: int) -> None:
    from engine.motion.state import robust_speed

    window, steps = _robust_cases()[idx]
    out, snaps, same = _run_robust(robust_speed, window, steps)
    exp_out, exp_snaps, exp_final = ROBUST_EXPECTED[idx]
    assert same is True
    _eq(out, exp_out)
    _eq(snaps[-1], exp_final)
    _eq([len(s) for s in snaps], exp_snaps)


def test_robust_speed_returns_the_speed_itself_without_window() -> None:
    from engine.motion.state import robust_speed

    assert robust_speed([], 0.0, 2.0, 0.0) == 2.0


@pytest.mark.parametrize("idx", range(9))
def test_motion_state_sequences(idx: int) -> None:
    from engine.motion.state import motion_state

    vehicle, steps = _state_cases()[idx]
    _eq(_run_states(motion_state, vehicle, steps), STATE_EXPECTED[idx])


def test_motion_state_vehicle_levels_and_hysteresis() -> None:
    from engine.motion.state import motion_state

    _eq(_run_vehicle_prev(motion_state), VEHICLE_PREV_EXPECTED)


@pytest.mark.parametrize("idx", range(12))
def test_own_motion_classify_per_step(idx: int) -> None:
    from engine.motion.own import OwnMotion

    rows, est, pose = _run_own(OwnMotion, _own_scenarios()[idx])
    exp_rows, exp_est, exp_pose = OWN_EXPECTED[idx]
    _eq(rows, exp_rows)
    _eq(est, exp_est)
    _eq(pose, exp_pose)


def test_own_motion_fragment_links_history() -> None:
    from engine.motion.own import OwnMotion

    _eq(_run_fragment(OwnMotion), FRAGMENT_EXPECTED)


def test_own_motion_advance_observe_edges() -> None:
    from engine.motion.own import OwnMotion

    _eq(_run_edges(OwnMotion), EDGES_EXPECTED)
