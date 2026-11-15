"""Characterisation tests for engine.worldmap.faceedge (v26.3.0 p3-05): the face / edge test on the ego-centric map.

Every literal below was printed by the legacy ``faceedge`` module in the hackeye-rnd image before the move, by feeding
it the synthetic grids of ``_scenario_*`` (a 200 x 200 map at 0.1 m per cell, ego frame: ``fwd`` ahead, ``right`` to
the right). The engine module is imported inside each test (it does not exist yet).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

import faceedge as legacy

if TYPE_CHECKING:
    from numpy.typing import NDArray

CELL: float = 0.1

DEFAULTS_LITERAL: dict[str, Any] = {
    "enabled": False,
    "maxAheadM": 12.0,
    "lineAheadM": 8.0,
    "lineMaxSideM": 4.0,
    "lineMinCells": 15,
    "lineMinSpanM": 2.0,
    "lineTrials": 80,
    "maxLineAngleDeg": 25.0,
    "edgeBandM": 0.25,
    "edgeBlurPerM": 0.02,
    "faceProtrusionM": 0.3,
    "crossRadiusM": 0.5,
    "crossAngleDeg": 45.0,
    "crossElongation": 2.0,
    "crossMinCells": 6,
    "minFaceCells": 3,
    "crossSideEdge": True,
    "seed": 7,
}


def _check(got: float, exp: float) -> None:
    assert got == pytest.approx(exp, rel=1e-12, abs=1e-12)


def _grid() -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    n = 200
    rows, cols = np.mgrid[0:n, 0:n]
    fwd = ((n - rows) * CELL).astype(np.float64)
    right = ((cols - 100) * CELL).astype(np.float64)
    return fwd, right


def _scenario_a(fwd: NDArray[np.float64], right: NDArray[np.float64]) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    """A wall beside the path at 0.5 m to the right; the candidate is its blur inside the corridor (all EDGE)."""
    wall = (np.abs(right - 0.5) <= 0.1) & (fwd > 0.5) & (fwd < 8.0)
    cand = wall & (fwd > 3.0) & (fwd < 4.0)
    return wall, cand


def _scenario_b(fwd: NDArray[np.float64], right: NDArray[np.float64]) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    """The wall of A plus a section sticking out across the path at 5 m (FACE candidates mixed with edge and none)."""
    wall = (np.abs(right - 0.5) <= 0.1) & (fwd > 0.5) & (fwd < 8.0)
    across = wall | ((np.abs(fwd - 5.0) <= 0.1) & (np.abs(right) <= 0.4))
    cand = across & (np.abs(fwd - 5.0) <= 0.1) & (np.abs(right) <= 0.4)
    return across, cand


def _scenario_c(fwd: NDArray[np.float64], right: NDArray[np.float64]) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    """Two walls (left -1.0 m, right +1.0 m) and a block protruding from the left wall at 6-7 m (FACE by protrusion)."""
    walls = ((np.abs(right + 1.0) <= 0.1) | (np.abs(right - 1.0) <= 0.1)) & (fwd > 0.5) & (fwd < 12.0)
    block = (fwd >= 6.0) & (fwd <= 7.0) & (right >= -0.6) & (right <= -0.4)
    return walls | block, block


# ---- identity --------------------------------------------------------------------------------------------------


def test_facade_identity() -> None:
    from engine.worldmap import faceedge as fe

    assert legacy.EDGE == fe.EDGE == 0
    assert legacy.FACE == fe.FACE == 1
    assert legacy.NONE == fe.NONE == 2
    assert legacy.VERDICT_NAMES is fe.VERDICT_NAMES
    assert legacy.DEFAULTS is fe.DEFAULTS
    assert legacy.settings is fe.settings
    assert legacy.fit_line is fe.fit_line
    assert legacy.fit_wall_lines is fe.fit_wall_lines
    assert legacy.local_orientation is fe.local_orientation
    assert legacy.classify is fe.classify
    assert legacy.summarize is fe.summarize
    assert legacy.lines_json is fe.lines_json


def test_package_exports_the_submodule_not_its_functions() -> None:
    import engine.worldmap as pkg
    from engine.worldmap import faceedge

    assert not hasattr(pkg, "settings")
    assert not hasattr(pkg, "classify")
    assert faceedge.classify is legacy.classify


# ---- settings and defaults --------------------------------------------------------------------------------------


def test_defaults_are_the_legacy_literals() -> None:
    from engine.worldmap import faceedge as fe

    assert fe.DEFAULTS == DEFAULTS_LITERAL
    assert fe.VERDICT_NAMES == ("edge", "face", "none")


def test_settings_overlays_the_config_on_the_defaults() -> None:
    from engine.worldmap import faceedge as fe

    assert fe.settings(None) == DEFAULTS_LITERAL
    assert fe.settings({}) == DEFAULTS_LITERAL
    out = fe.settings({"enabled": True, "minFaceCells": 5})
    assert out["enabled"] is True and out["minFaceCells"] == 5
    assert {k: v for k, v in out.items() if k not in ("enabled", "minFaceCells")} == {
        k: v for k, v in DEFAULTS_LITERAL.items() if k not in ("enabled", "minFaceCells")
    }
    assert fe.DEFAULTS["enabled"] is False  # the overlay never writes into DEFAULTS


# ---- wall lines ------------------------------------------------------------------------------------------------


def test_fit_wall_lines_scenario_a_right_wall_only() -> None:
    from engine.worldmap import faceedge as fe

    fwd, right = _grid()
    fam, _ = _scenario_a(fwd, right)
    lines = fe.fit_wall_lines(fam, fwd, right, fe.settings({}))
    assert fe.lines_json(lines) == {
        "left": None,
        "right": {"a": 0.45, "b": 0.0, "angleDeg": 0.0, "n": 148, "spanM": 7.3, "rms": 0.05},
    }


def test_fit_wall_lines_scenario_b_right_wall_with_a_section_across() -> None:
    from engine.worldmap import faceedge as fe

    fwd, right = _grid()
    fam, _ = _scenario_b(fwd, right)
    lines = fe.fit_wall_lines(fam, fwd, right, fe.settings({}))
    assert fe.lines_json(lines) == {
        "left": None,
        "right": {"a": 0.447, "b": -0.0015, "angleDeg": -0.1, "n": 154, "spanM": 7.3, "rms": 0.071},
    }


def test_fit_wall_lines_scenario_c_both_walls() -> None:
    from engine.worldmap import faceedge as fe

    fwd, right = _grid()
    fam, _ = _scenario_c(fwd, right)
    lines = fe.fit_wall_lines(fam, fwd, right, fe.settings({}))
    assert fe.lines_json(lines) == {
        "left": {"a": -0.971, "b": 0.0086, "angleDeg": 0.5, "n": 150, "spanM": 7.4, "rms": 0.056},
        "right": {"a": 0.95, "b": 0.0, "angleDeg": 0.0, "n": 150, "spanM": 7.4, "rms": 0.05},
    }


def test_lines_json_rounds_and_keeps_missing_sides() -> None:
    from engine.worldmap import faceedge as fe

    assert fe.lines_json({"left": None, "right": None}) == {"left": None, "right": None}
    raw = {"a": 0.123456, "b": 0.00012345, "angleDeg": 0.0070, "n": 9, "spanM": 2.345, "rms": 0.0123456}
    assert fe.lines_json({"left": raw, "right": None}) == {
        "left": {"a": 0.123, "b": 0.0001, "angleDeg": 0.0, "n": 9, "spanM": 2.3, "rms": 0.012},
        "right": None,
    }


# ---- classify and summarize ------------------------------------------------------------------------------------


def test_classify_scenario_a_is_all_edge() -> None:
    from engine.worldmap import faceedge as fe

    fwd, right = _grid()
    fam, cand = _scenario_a(fwd, right)
    cfg = fe.settings({})
    res = fe.classify(cand, fam, fwd, right, CELL, cfg)
    v = res["verdict"]
    assert v.size == 18
    assert [int((v == k).sum()) for k in (fe.EDGE, fe.FACE, fe.NONE)] == [18, 0, 0]
    assert [str(x) for x in res["reason"]].count("edge") == 18
    assert (int(res["rows"][0]), int(res["cols"][0]), int(v[0])) == (161, 104, 0)
    assert (int(res["rows"][-1]), int(res["cols"][-1]), int(v[-1])) == (169, 105, 0)
    _check(float(np.nansum(res["protrusionM"])), 4.440892098500626e-16)
    _check(float(np.nansum(res["lineDistM"])), 0.8999999999999999)
    _check(float(np.sum(res["angleDeg"])), 2.2380666213787804e-09)
    assert fe.summarize(res, cfg) == {
        "verdict": "edge",
        "cells": 18,
        "face": 0,
        "edge": 18,
        "none": 0,
        "minLineDistM": 0.05,
        "maxProtrusionAllM": 0.05,
    }


def test_classify_scenario_b_mixed_face_edge_none() -> None:
    from engine.worldmap import faceedge as fe

    fwd, right = _grid()
    fam, cand = _scenario_b(fwd, right)
    cfg = fe.settings({})
    res = fe.classify(cand, fam, fwd, right, CELL, cfg)
    v = res["verdict"]
    assert v.size == 18
    assert [int((v == k).sum()) for k in (fe.EDGE, fe.FACE, fe.NONE)] == [8, 8, 2]
    reasons = [str(x) for x in res["reason"]]
    counts = sorted((r, reasons.count(r)) for r in set(reasons))
    assert counts == [("", 2), ("cross", 6), ("edge", 8), ("protrusion", 2)]
    assert (int(res["rows"][0]), int(res["cols"][0]), int(v[0])) == (150, 96, 1)
    assert (int(res["rows"][-1]), int(res["cols"][-1]), int(v[-1])) == (151, 104, 0)
    assert int(np.isfinite(res["protrusionM"]).sum()) == 10
    _check(float(np.nansum(res["protrusionM"])), 2.3925863049531846)
    _check(float(np.nansum(res["lineDistM"])), 7.906655348915734)
    _check(float(np.sum(res["angleDeg"])), 527.9999999997259)
    assert fe.summarize(res, cfg) == {
        "verdict": "face",
        "cells": 18,
        "face": 8,
        "edge": 8,
        "none": 2,
        "nearestFaceM": 4.9,
        "nearestFaceRightM": 0.0,
        "maxProtrusionM": 0.44,
        "maxCrossAngleDeg": 90.0,
        "reasons": ["cross", "protrusion"],
        "minLineDistM": 0.04,
        "maxProtrusionAllM": 0.44,
    }


def test_classify_scenario_c_protruding_block_is_face() -> None:
    from engine.worldmap import faceedge as fe

    fwd, right = _grid()
    fam, cand = _scenario_c(fwd, right)
    cfg = fe.settings({})
    res = fe.classify(cand, fam, fwd, right, CELL, cfg)
    v = res["verdict"]
    assert v.size == 22
    assert [int((v == k).sum()) for k in (fe.EDGE, fe.FACE, fe.NONE)] == [0, 22, 0]
    assert sorted({str(x) for x in res["reason"]}) == ["protrusion"]
    assert [str(x) for x in res["reason"]].count("protrusion") == 22
    assert (int(res["rows"][0]), int(res["cols"][0]), int(v[0])) == (130, 95, 1)
    assert (int(res["rows"][-1]), int(res["cols"][-1]), int(v[-1])) == (140, 96, 1)
    assert int(np.isfinite(res["protrusionM"]).sum()) == 22
    _check(float(np.nansum(res["protrusionM"])), 10.219848771759256)
    _check(float(np.nansum(res["lineDistM"])), 10.219848771759256)
    _check(float(np.sum(res["angleDeg"])), -22.0)
    assert fe.summarize(res, cfg) == {
        "verdict": "face",
        "cells": 22,
        "face": 22,
        "edge": 0,
        "none": 0,
        "nearestFaceM": 6.0,
        "nearestFaceRightM": -0.4,
        "maxProtrusionM": 0.52,
        "maxCrossAngleDeg": None,
        "reasons": ["protrusion"],
        "minLineDistM": 0.41,
        "maxProtrusionAllM": 0.52,
    }


def test_summarize_reads_the_config_minimum_face_cells() -> None:
    from engine.worldmap import faceedge as fe

    fwd, right = _grid()
    fam, cand = _scenario_b(fwd, right)
    res = fe.classify(cand, fam, fwd, right, CELL, fe.settings({}))
    # scenario B has 8 face cells: above that count the verdict drops to "unsure" (edge only needs zero face cells)
    assert fe.summarize(res, fe.settings({"minFaceCells": 9}))["verdict"] == "unsure"
    assert fe.summarize(res, fe.settings({"minFaceCells": 8}))["verdict"] == "face"


def test_classify_edge_only_scenario_matches_the_legacy_verdict_names() -> None:
    from engine.worldmap import faceedge as fe

    fwd, right = _grid()
    fam, cand = _scenario_a(fwd, right)
    cfg = fe.settings({})
    got = fe.summarize(fe.classify(cand, fam, fwd, right, CELL, cfg), cfg)["verdict"]
    assert got == legacy.summarize(legacy.classify(cand, fam, fwd, right, CELL, cfg), cfg)["verdict"] == "edge"
