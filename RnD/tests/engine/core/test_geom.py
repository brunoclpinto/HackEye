"""Characterisation tests for engine.core.geom (v26.3.0 p1-02).

Every expected literal was produced by running the legacy functions in the hackeye-rnd image
(collision.py / geometry.py) on the pre-move code, not computed by hand.

The engine module is imported with importlib inside each test function: it does not exist yet, and a
static ``from engine.core import geom`` would fail mypy now and make a ``# type: ignore`` unused later.
"""

from __future__ import annotations

import importlib

import pytest

import collision
import geometry


def test_facade_identity() -> None:
    geom = importlib.import_module("engine.core.geom")

    assert geometry.Box is geom.Box
    assert collision.Box is geom.Box
    assert geometry.iou is geom.iou
    assert collision.iou is geom.iou
    assert collision.focal_px is geom.focal_px
    assert collision.ground_distance_m is geom.ground_distance_m
    assert collision.lateral_m is geom.lateral_m
    assert collision.steps_to is geom.steps_to
    assert collision._r is geom.round_opt


def test_focal_px() -> None:
    geom = importlib.import_module("engine.core.geom")

    assert geom.focal_px(160.0, 100.0) == pytest.approx(67.12797049418239, rel=1e-12, abs=1e-12)
    assert geom.focal_px(160.0, 140.0) == pytest.approx(29.117618741296194, rel=1e-12, abs=1e-12)
    assert geom.focal_px(320.0, 60.0) == pytest.approx(277.1281292110204, rel=1e-12, abs=1e-12)


def test_ground_distance_m() -> None:
    geom = importlib.import_module("engine.core.geom")

    # normal case: y below the horizon line
    assert geom.ground_distance_m(0.8, 0.5, 1.78, 64.0, 67.12797049418239) == pytest.approx(
        6.223322264564826, rel=1e-12, abs=1e-12
    )
    # horizon exactly at the row: no ground distance
    assert geom.ground_distance_m(0.5, 0.5, 1.78, 64.0, 67.12797049418239) is None
    # horizon below the row (row above the horizon): no ground distance
    assert geom.ground_distance_m(0.4, 0.5, 1.78, 64.0, 67.12797049418239) is None
    # second normal case with other camera height, grid and focal length
    assert geom.ground_distance_m(0.9, 0.6, 1.5, 48.0, 277.1281292110204) == pytest.approx(
        28.867513459481284, rel=1e-12, abs=1e-12
    )


def test_lateral_m() -> None:
    geom = importlib.import_module("engine.core.geom")

    assert geom.lateral_m(0.25, 3.0, 160.0, 67.12797049418239) == pytest.approx(
        -1.7876303888913152, rel=1e-12, abs=1e-12
    )
    assert geom.lateral_m(0.5, 5.0, 160.0, 29.117618741296194) == pytest.approx(0.0, rel=1e-12, abs=1e-12)
    assert geom.lateral_m(0.9, 1.7, 320.0, 277.1281292110204) == pytest.approx(0.7851963660978909, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize(
    ("distance", "step", "expected"),
    [
        (0.0, 0.7, 0.0),
        (0.0, 0.75, 0.0),
        (0.7, 0.7, 1.0),
        (0.7, 0.75, 0.9333333333333332),
        (5.0, 0.7, 7.142857142857143),
        (5.0, 0.75, 6.666666666666667),
    ],
)
def test_steps_to(distance: float, step: float, expected: float) -> None:
    geom = importlib.import_module("engine.core.geom")

    assert geom.steps_to(distance, step) == pytest.approx(expected, rel=1e-12, abs=1e-12)


def test_box_construction_and_properties() -> None:
    geom = importlib.import_module("engine.core.geom")

    b = geom.Box(1.0, 2.0, 4.0, 7.0)
    assert (b.x1, b.y1, b.x2, b.y2) == (1.0, 2.0, 4.0, 7.0)
    assert b.w == 3.0
    assert b.h == 5.0
    assert b.area == 15.0

    # degenerate (inverted) box: w, h and area clamp to 0
    d = geom.Box(5.0, 5.0, 3.0, 1.0)
    assert d.w == 0.0
    assert d.h == 0.0
    assert d.area == 0.0


def test_box_equality_and_hash() -> None:
    geom = importlib.import_module("engine.core.geom")

    assert geom.Box(1, 2, 3, 4) == geom.Box(1.0, 2.0, 3.0, 4.0)
    assert geom.Box(1, 2, 3, 4) != geom.Box(1, 2, 3, 5)
    # not frozen: a dataclass with eq and no frozen flag is unhashable
    with pytest.raises(TypeError):
        hash(geom.Box(1, 2, 3, 4))


def test_iou() -> None:
    geom = importlib.import_module("engine.core.geom")
    Box = geom.Box

    a = Box(0.0, 0.0, 10.0, 10.0)
    # identical boxes
    assert geom.iou(a, Box(0.0, 0.0, 10.0, 10.0)) == pytest.approx(1.0, rel=1e-12, abs=1e-12)
    # disjoint boxes
    assert geom.iou(a, Box(20.0, 20.0, 30.0, 30.0)) == 0.0
    # touching edges only (zero-area intersection)
    assert geom.iou(a, Box(10.0, 0.0, 20.0, 10.0)) == 0.0
    # partial overlap
    assert geom.iou(a, Box(5.0, 5.0, 15.0, 15.0)) == pytest.approx(0.14285714285714285, rel=1e-12, abs=1e-12)
    # contained box
    assert geom.iou(a, Box(2.0, 2.0, 4.0, 4.0)) == pytest.approx(0.04, rel=1e-12, abs=1e-12)
    assert geom.iou(Box(2.0, 2.0, 4.0, 4.0), a) == pytest.approx(0.04, rel=1e-12, abs=1e-12)
    # both degenerate: 0 rather than a division by zero
    assert geom.iou(Box(1.0, 1.0, 1.0, 1.0), Box(1.0, 1.0, 1.0, 1.0)) == 0.0


def test_round_opt() -> None:
    geom = importlib.import_module("engine.core.geom")

    assert geom.round_opt(None, 2) is None
    assert geom.round_opt(1.23456, 2) == pytest.approx(1.23, rel=1e-12, abs=1e-12)
    assert geom.round_opt(-0.0049, 2) == pytest.approx(-0.0, rel=1e-12, abs=1e-12)
