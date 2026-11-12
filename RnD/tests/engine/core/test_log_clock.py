"""p1-01: engine.core.log and engine.core.clock characterisation tests.

Every expected value below was produced by the legacy functions in ``collision.py`` inside the hackeye-rnd image
(``docker compose run --rm -T --entrypoint python rnd -c ...`` from RnD/). Do not hand-edit them.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest

import collision as col

if TYPE_CHECKING:
    from types import ModuleType

# bearing_deg: (x_norm, hfov_deg, projection, legacy value)
BEARING_CASES: list[tuple[float, float, str, float]] = [
    (0.0, 100.0, "rectilinear", -50.0),
    (0.0, 100.0, "fisheye", -50.0),
    (0.0, 140.0, "rectilinear", -70.0),
    (0.0, 140.0, "fisheye", -70.0),
    (0.25, 100.0, "rectilinear", -30.78973302883215),
    (0.25, 100.0, "fisheye", -25.0),
    (0.25, 140.0, "rectilinear", -53.94761126761209),
    (0.25, 140.0, "fisheye", -35.0),
    (0.5, 100.0, "rectilinear", 0.0),
    (0.5, 100.0, "fisheye", 0.0),
    (0.5, 140.0, "rectilinear", 0.0),
    (0.5, 140.0, "fisheye", 0.0),
    (0.9, 100.0, "rectilinear", 43.633506451993895),
    (0.9, 100.0, "fisheye", 40.0),
    (0.9, 140.0, "rectilinear", 65.5362310860197),
    (0.9, 140.0, "fisheye", 56.0),
    (1.0, 100.0, "rectilinear", 50.0),
    (1.0, 100.0, "fisheye", 50.0),
    (1.0, 140.0, "rectilinear", 70.0),
    (1.0, 140.0, "fisheye", 70.0),
]

# (bearing, clock_from_bearing, clock_quarter)
CLOCK_CASES: list[tuple[float, int, int]] = [
    (-180, 9, -12),
    (-95, 9, -12),
    (-60, 10, -8),
    (-15, 12, -2),
    (0, 12, 0),
    (7.4, 12, 1),
    (7.6, 12, 1),
    (15, 1, 2),
    (44.9, 1, 6),
    (45, 2, 6),
    (90, 3, 12),
    (179.9, 3, 12),
]

# clock_text(q) for q in -12..48 (clock_quarter returns -12..12; legacy values, Opus added -12..0)
TEXT_CASES: list[tuple[int, str]] = [
    (-12, "9"),
    (-11, "9:15"),
    (-10, "9:30"),
    (-9, "9:45"),
    (-8, "10"),
    (-7, "10:15"),
    (-6, "10:30"),
    (-5, "10:45"),
    (-4, "11"),
    (-3, "11:15"),
    (-2, "11:30"),
    (-1, "11:45"),
    (0, "12"),
    (1, "12:15"),
    (2, "12:30"),
    (3, "12:45"),
    (4, "1"),
    (5, "1:15"),
    (6, "1:30"),
    (7, "1:45"),
    (8, "2"),
    (9, "2:15"),
    (10, "2:30"),
    (11, "2:45"),
    (12, "3"),
    (13, "3:15"),
    (14, "3:30"),
    (15, "3:45"),
    (16, "4"),
    (17, "4:15"),
    (18, "4:30"),
    (19, "4:45"),
    (20, "5"),
    (21, "5:15"),
    (22, "5:30"),
    (23, "5:45"),
    (24, "6"),
    (25, "6:15"),
    (26, "6:30"),
    (27, "6:45"),
    (28, "7"),
    (29, "7:15"),
    (30, "7:30"),
    (31, "7:45"),
    (32, "8"),
    (33, "8:15"),
    (34, "8:30"),
    (35, "8:45"),
    (36, "9"),
    (37, "9:15"),
    (38, "9:30"),
    (39, "9:45"),
    (40, "10"),
    (41, "10:15"),
    (42, "10:30"),
    (43, "10:45"),
    (44, "11"),
    (45, "11:15"),
    (46, "11:30"),
    (47, "11:45"),
    (48, "12"),
]

# quarter_of_hour(c) for c in 1..12
QUARTER_OF_HOUR_CASES: list[tuple[int, int]] = [
    (1, 4),
    (2, 8),
    (3, 12),
    (4, -32),
    (5, -28),
    (6, -24),
    (7, -20),
    (8, -16),
    (9, -12),
    (10, -8),
    (11, -4),
    (12, 0),
]

# pan_from_bearing: (bearing, legacy value)
PAN_CASES: list[tuple[float, float]] = [
    (-120, -0.8660254037844387),
    (-30, -0.49999999999999994),
    (0, 0.0),
    (30, 0.49999999999999994),
    (120, 0.8660254037844387),
]


def _engine(name: str) -> ModuleType:
    # importlib keeps the engine import inside the test body and stays mypy-clean before and after the module exists.
    return importlib.import_module(name)


def test_log_writes_prefixed_line_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    log = _engine("engine.core.log").log

    log("p1-01 probe")
    captured = capsys.readouterr()
    assert captured.err == "[collision] p1-01 probe\n"
    assert captured.out == ""


def test_warn_once_prints_once_and_records_message(capsys: pytest.CaptureFixture[str]) -> None:
    log_mod = _engine("engine.core.log")
    WARNED = log_mod.WARNED
    warn_once = log_mod.warn_once

    msg = "p1-01 warn-once probe"
    WARNED.discard(msg)
    try:
        warn_once(msg)
        assert capsys.readouterr().err == "[collision] p1-01 warn-once probe\n"
        assert msg in WARNED

        warn_once(msg)
        assert capsys.readouterr().err == ""
    finally:
        WARNED.discard(msg)


def test_facade_identity_log_and_clock() -> None:
    log_mod = _engine("engine.core.log")
    clock_mod = _engine("engine.core.clock")

    assert col._WARNED is log_mod.WARNED
    assert col._log is log_mod.log
    assert col._warn_once is log_mod.warn_once
    assert col.bearing_deg is clock_mod.bearing_deg
    assert col.clock_from_bearing is clock_mod.clock_from_bearing
    assert col.clock_quarter is clock_mod.clock_quarter
    assert col.clock_text is clock_mod.clock_text
    assert col._quarter_of_hour is clock_mod.quarter_of_hour
    assert col._pan_from_bearing is clock_mod.pan_from_bearing


def test_bearing_deg_matches_legacy() -> None:
    bearing_deg = _engine("engine.core.clock").bearing_deg

    for x_norm, hfov, projection, expected in BEARING_CASES:
        assert bearing_deg(x_norm, hfov, projection) == pytest.approx(expected, rel=1e-12, abs=1e-12), (
            x_norm,
            hfov,
            projection,
        )


def test_clock_from_bearing_and_quarter_match_legacy() -> None:
    clock_mod = _engine("engine.core.clock")

    for bearing, expected_clock, expected_quarter in CLOCK_CASES:
        assert clock_mod.clock_from_bearing(bearing) == expected_clock, bearing
        assert clock_mod.clock_quarter(bearing) == expected_quarter, bearing


def test_clock_text_matches_legacy() -> None:
    clock_text = _engine("engine.core.clock").clock_text

    for q, expected in TEXT_CASES:
        assert clock_text(q) == expected, q


def test_quarter_of_hour_matches_legacy() -> None:
    quarter_of_hour = _engine("engine.core.clock").quarter_of_hour

    for clock, expected in QUARTER_OF_HOUR_CASES:
        assert quarter_of_hour(clock) == expected, clock


def test_pan_from_bearing_matches_legacy() -> None:
    pan_from_bearing = _engine("engine.core.clock").pan_from_bearing

    for bearing, expected in PAN_CASES:
        assert pan_from_bearing(bearing) == pytest.approx(expected, rel=1e-12, abs=1e-12), bearing
