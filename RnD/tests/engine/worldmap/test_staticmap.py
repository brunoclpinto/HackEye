"""Characterisation tests for engine.worldmap.staticmap (v26.3.0 p3-06): StaticMap, set_position, mute_solid.

Every literal below was printed by the legacy ``collision`` objects (``_StaticMap``, ``_set_position``, ``_mute_solid``)
in the hackeye-rnd image before the move, by running the ``_*_snapshot`` builders of this file on them. The scenarios
build the map with ``__new__`` and set only the attributes the methods read (audit 6.4). The engine module is imported
inside each test (it does not exist yet).
"""

from __future__ import annotations

import types
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

import collision
import faceedge as legacy_faceedge
from engine.core.types import Item

if TYPE_CHECKING:
    from numpy.typing import NDArray

METHODS: list[str] = [
    "_apply",
    "_corridor_cells",
    "_footprint",
    "_lut",
    "blocked_ahead",
    "classes_name",
    "corridor",
    "faceedge",
    "ghost",
    "keeps",
    "locate",
    "measure",
    "point_in_solid",
    "recent_obstacle_points",
    "region",
    "snap_solid",
    "solid_border",
    "update",
]

ITEM_FIELDS: list[str] = [
    "distance_m",
    "lateral_m",
    "bearing",
    "clock",
    "clock_q",
    "clock_text",
    "pan",
    "image_dl",
    "map_cells",
    "map_world",
    "map_source",
    "map_judged",
    "inside_solid",
    "solid_corrected",
    "raw_distance_m",
]

MUTE_FIELDS: list[str] = ["role", "urgency", "collision", "summary_ok", "proximity", "speak"]


def _item(group: str = "static", name: str = "pole", dist: float = 5.0, lat: float = 0.5) -> Item:
    it = Item(
        group=group,
        class_name=name,
        bbox=[0.4, 0.5, 0.5, 0.6],
        contact_y=0.6,
        distance_m=dist,
        lateral_m=lat,
        bearing=5.0,
        clock=12,
        pan=0.1,
        area_frac=0.01,
        clipped=False,
        touches=True,
        lane_hit=True,
        along_path=False,
        lane_cover=1.0,
    )
    it.track_id = 7
    return it


def _fields(it: Any, names: list[str]) -> dict[str, Any]:
    return {n: getattr(it, n, "<unset>") for n in names}


def _norm(v: Any) -> Any:
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, tuple | list):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    return v


def _same(got: Any, want: Any) -> None:
    got = _norm(got)
    if isinstance(want, dict):
        assert isinstance(got, dict) and got.keys() == want.keys()
        for k in want:
            _same(got[k], want[k])
    elif isinstance(want, list):
        assert isinstance(got, list) and len(got) == len(want)
        for g, w in zip(got, want, strict=True):
            _same(g, w)
    elif isinstance(want, float):
        assert got == pytest.approx(want, rel=1e-12, abs=1e-12)
    else:
        assert got == want


SET_POSITION: Any = {
    "first": {
        "distance_m": 6.0,
        "lateral_m": 2.0,
        "bearing": 18.43494882292201,
        "clock": 1,
        "clock_q": 2,
        "clock_text": "12:30",
        "pan": 0.31622776601683794,
        "image_dl": [5.0, 0.5, 5.0, 12, 0, "12", 0.1],
        "map_cells": 0,
        "map_world": None,
        "map_source": "",
        "map_judged": False,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
    },
    "second": {
        "distance_m": 3.0,
        "lateral_m": -1.5,
        "bearing": -26.56505117707799,
        "clock": 11,
        "clock_q": -4,
        "clock_text": "11",
        "pan": -0.4472135954999579,
        "image_dl": [5.0, 0.5, 5.0, 12, 0, "12", 0.1],
        "map_cells": 0,
        "map_world": None,
        "map_source": "",
        "map_judged": False,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
    },
}

MUTE: Any = {
    "suppress": {
        "role": "none",
        "urgency": "none",
        "collision": False,
        "summary_ok": False,
        "proximity": False,
        "speak": False,
    },
    "snap": {
        "role": "danger",
        "urgency": "final",
        "collision": True,
        "summary_ok": True,
        "proximity": True,
        "speak": True,
    },
    "not_inside": {
        "role": "danger",
        "urgency": "final",
        "collision": True,
        "summary_ok": True,
        "proximity": True,
        "speak": True,
    },
    "none_map": {
        "role": "danger",
        "urgency": "final",
        "collision": True,
        "summary_ok": True,
        "proximity": True,
        "speak": True,
    },
}

APPLY: Any = {
    "distance_m": 4.0,
    "lateral_m": -1.0,
    "bearing": -14.036243467926479,
    "clock": 12,
    "clock_q": -2,
    "clock_text": "11:30",
    "pan": -0.24253562503633297,
    "image_dl": [5.0, 0.5, 5.0, 12, 0, "12", 0.1],
    "map_cells": 9,
    "map_world": [2.133974596215561, 5.964101615137755],
    "map_source": "",
    "map_judged": False,
    "inside_solid": False,
    "solid_corrected": False,
    "raw_distance_m": None,
}

SNAP: Any = {
    "snap": {
        "distance_m": 3.0,
        "lateral_m": 0.4,
        "bearing": 7.594643368591445,
        "clock": 12,
        "clock_q": 1,
        "clock_text": "12:15",
        "pan": 0.13216372009101796,
        "image_dl": None,
        "map_cells": 0,
        "map_world": None,
        "map_source": "",
        "map_judged": False,
        "inside_solid": True,
        "solid_corrected": True,
        "raw_distance_m": 5.0,
    },
    "suppress": {
        "distance_m": 5.0,
        "lateral_m": 0.5,
        "bearing": 5.0,
        "clock": 12,
        "clock_q": 0,
        "clock_text": "12",
        "pan": 0.1,
        "image_dl": None,
        "map_cells": 0,
        "map_world": None,
        "map_source": "",
        "map_judged": False,
        "inside_solid": True,
        "solid_corrected": False,
        "raw_distance_m": None,
    },
    "judged": {
        "distance_m": 5.0,
        "lateral_m": 0.5,
        "bearing": 5.0,
        "clock": 12,
        "clock_q": 0,
        "clock_text": "12",
        "pan": 0.1,
        "image_dl": None,
        "map_cells": 0,
        "map_world": None,
        "map_source": "",
        "map_judged": False,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
    },
    "ghost": {
        "distance_m": 5.0,
        "lateral_m": 0.5,
        "bearing": 5.0,
        "clock": 12,
        "clock_q": 0,
        "clock_text": "12",
        "pan": 0.1,
        "image_dl": None,
        "map_cells": 0,
        "map_world": None,
        "map_source": "",
        "map_judged": False,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
    },
    "outside": {
        "distance_m": 5.0,
        "lateral_m": 0.5,
        "bearing": 5.0,
        "clock": 12,
        "clock_q": 0,
        "clock_text": "12",
        "pan": 0.1,
        "image_dl": None,
        "map_cells": 0,
        "map_world": None,
        "map_source": "",
        "map_judged": False,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
    },
    "off": {
        "distance_m": 5.0,
        "lateral_m": 0.5,
        "bearing": 5.0,
        "clock": 12,
        "clock_q": 0,
        "clock_text": "12",
        "pan": 0.1,
        "image_dl": None,
        "map_cells": 0,
        "map_world": None,
        "map_source": "",
        "map_judged": False,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
    },
}

FOOTPRINT: Any = {
    "shape": [5, 14],
    "count": 58,
    "r0": 80,
    "c0": 93,
    "rows": [0, 4],
    "cols": [0, 13],
    "none_lut": None,
    "no_shape": None,
    "lut_known": True,
    "lut_unknown": True,
}

CORRIDOR: Any = {"hit": [6.1000000000000005, 0.0, 100, 100], "miss": [None, None, 0, 0]}

MEASURE: Any = {
    "building": {
        "distance_m": 6.6,
        "lateral_m": 0.0,
        "bearing": 0.0,
        "clock": 12,
        "clock_q": 0,
        "clock_text": "12",
        "pan": 0.0,
        "image_dl": [5.0, 0.5, 5.0, 12, 0, "12", 0.1],
        "map_cells": 50,
        "map_world": [4.299999999999999, 7.715767664977295],
        "map_source": "map",
        "map_judged": True,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
        "fe_keys": [
            "cells",
            "edge",
            "face",
            "faceCells",
            "imageAlongPath",
            "imageLaneHit",
            "lines",
            "maxCrossAngleDeg",
            "maxProtrusionAllM",
            "maxProtrusionM",
            "minLineDistM",
            "nearestFaceM",
            "nearestFaceRightM",
            "none",
            "reasons",
            "stationary",
            "verdict",
        ],
        "verdict": "face",
        "face": 50,
        "nearestFaceM": 6.6,
        "fe_res_keys": [7],
        "cache": 1,
    },
    "pole": {
        "distance_m": 5.0,
        "lateral_m": 0.5,
        "bearing": 5.0,
        "clock": 12,
        "clock_q": 0,
        "clock_text": "12",
        "pan": 0.1,
        "image_dl": None,
        "map_cells": 0,
        "map_world": None,
        "map_source": "image",
        "map_judged": False,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
        "face_edge": None,
    },
    "moving": {
        "distance_m": 5.0,
        "lateral_m": 0.5,
        "bearing": 5.0,
        "clock": 12,
        "clock_q": 0,
        "clock_text": "12",
        "pan": 0.1,
        "image_dl": None,
        "map_cells": 0,
        "map_world": None,
        "map_source": "",
        "map_judged": False,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
        "face_edge": None,
    },
    "no_fe": {
        "distance_m": 5.0,
        "lateral_m": 0.5,
        "bearing": 5.0,
        "clock": 12,
        "clock_q": 0,
        "clock_text": "12",
        "pan": 0.1,
        "image_dl": None,
        "map_cells": 0,
        "map_world": None,
        "map_source": "image",
        "map_judged": False,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
    },
    "stationary": {
        "distance_m": 5.0,
        "lateral_m": 0.5,
        "bearing": 5.0,
        "clock": 12,
        "clock_q": 0,
        "clock_text": "12",
        "pan": 0.1,
        "image_dl": None,
        "map_cells": 0,
        "map_world": None,
        "map_source": "map",
        "map_judged": True,
        "inside_solid": False,
        "solid_corrected": False,
        "raw_distance_m": None,
    },
}


# -- set_position ---------------------------------------------------------------------------------------
def _set_position_snapshot(fn: Any) -> dict[str, Any]:
    it = _item()
    fn(it, 6.0, 2.0)
    first = _fields(it, ITEM_FIELDS)
    fn(it, 3.0, -1.5)
    return {"first": first, "second": _fields(it, ITEM_FIELDS)}


# -- mute_solid -----------------------------------------------------------------------------------------
def _mute_snapshot(fn: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tag, mode, inside, smap in (
        ("suppress", "suppress", True, True),
        ("snap", "snap", True, True),
        ("not_inside", "suppress", False, True),
        ("none_map", "suppress", True, False),
    ):
        it = _item()
        it.role, it.urgency, it.collision, it.summary_ok, it.proximity, it.speak = (
            "danger",
            "final",
            True,
            True,
            True,
            True,
        )
        it.inside_solid = inside
        sm = types.SimpleNamespace(solid_mode=mode) if smap else None
        fn(it, sm)
        out[tag] = _fields(it, MUTE_FIELDS)
    return out


# -- map scenarios --------------------------------------------------------------------------------------
N = 200


def _grid() -> tuple[NDArray[Any], NDArray[Any]]:
    fwd = np.repeat(((150 - np.arange(N))[:, None] * 0.1), N, axis=1)
    right = np.repeat(((np.arange(N) - 100)[None, :] * 0.1), N, axis=0)
    return fwd, right


def _map(cls: Any) -> Any:
    sm = cls.__new__(cls)
    fwd, right = _grid()
    sm.ob = types.SimpleNamespace(size=N, fwd=fwd, right=right)
    sm.cell = 0.1
    sm.rad = 2
    yy, xx = np.mgrid[-2:3, -2:3]
    sm.disk = (yy * yy + xx * xx) <= 2 * 2 + 0.5
    sm.solid = np.zeros((N, N), dtype=bool)
    sm.solid[80:90, 95:105] = True
    sm.classes = np.zeros((N, N), dtype=np.int64)
    sm.classes[80:90, 95:105] = 1
    sm.corr_full = (fwd > 0) & (np.abs(right) <= 0.6)
    sm.fam = {"building": np.array([False, True] + [False] * 254)}
    sm.labels = {}
    sm.judged = frozenset({"building"})
    sm.fe_cfg = legacy_faceedge.settings({"enabled": True})
    sm.fe_res = {}
    sm._fe_cache = {}
    sm.fe_lines = None
    sm.stationary = False
    sm.image_fallback = True
    sm.pose = (1.0, 2.0, 30.0)
    sm.b_rr = np.full(10, 20, dtype=np.int64)
    sm.b_cc = np.arange(10, dtype=np.int64) + 30
    sm.b_row = np.full(10, 82, dtype=np.int64)
    sm.b_col = np.arange(10, dtype=np.int64) + 95
    return sm


def _shaped(name: str, group: str = "static") -> Item:
    it = _item(group=group, name=name)
    it.shape = (np.ones((5, 12), dtype=bool), 28, 18)
    return it


def _apply_snapshot(cls: Any) -> dict[str, Any]:
    sm = _map(cls)
    it = _item()
    sm._apply(it, 4.0, -1.0, 9)
    return _fields(it, ITEM_FIELDS)


def _snap_snapshot(cls: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tag, mode, name, ghost, border in (
        ("snap", "snap", "pole", False, (3.0, 0.4)),
        ("suppress", "suppress", "pole", False, (3.0, 0.4)),
        ("judged", "snap", "building", False, (3.0, 0.4)),
        ("ghost", "snap", "pole", True, (3.0, 0.4)),
        ("outside", "snap", "pole", False, None),
    ):
        sm = _map(cls)
        sm.solid_on, sm.solid_mode = True, mode
        sm.solid_border = lambda fwd, right, b=border: b
        it = _item(name=name)
        it.ghost = ghost
        sm.snap_solid(it)
        out[tag] = _fields(it, ITEM_FIELDS)
    sm = _map(cls)
    sm.solid_on, sm.solid_mode = False, "off"
    it = _item()
    sm.snap_solid(it)
    out["off"] = _fields(it, ITEM_FIELDS)
    return out


def _footprint_snapshot(cls: Any) -> dict[str, Any]:
    sm = _map(cls)
    fp = sm._footprint(_shaped("building"), sm._lut(_shaped("building")))
    assert fp is not None
    mask, r0, c0 = fp
    none_lut = sm._footprint(_shaped("building"), None)
    no_shape = sm._footprint(_item(name="building"), sm._lut(_item(name="building")))
    return {
        "shape": list(mask.shape),
        "count": int(mask.sum()),
        "r0": r0,
        "c0": c0,
        "rows": [int(r) for r in np.flatnonzero(mask.any(axis=1))[[0, -1]]],
        "cols": [int(c) for c in np.flatnonzero(mask.any(axis=0))[[0, -1]]],
        "none_lut": none_lut,
        "no_shape": no_shape,
        "lut_known": bool(sm._lut(_item(name="building")).any()),
        "lut_unknown": sm._lut(_item(name="pole")) is None,
    }


def _measure_snapshot(cls: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    sm = _map(cls)
    it = _shaped("building")
    sm.measure(it)
    fe = it.face_edge
    out["building"] = {
        **_fields(it, ITEM_FIELDS),
        "fe_keys": sorted(fe) if fe else None,
        "verdict": fe["verdict"] if fe else None,
        "face": fe["face"] if fe else None,
        "nearestFaceM": fe["nearestFaceM"] if fe else None,
        "fe_res_keys": sorted(sm.fe_res),
        "cache": len(sm._fe_cache),
    }
    pole = _shaped("pole")
    sm.measure(pole)
    out["pole"] = _fields(pole, ITEM_FIELDS) | {"face_edge": pole.face_edge}
    mover = _shaped("person", group="moving")
    sm.measure(mover)
    out["moving"] = _fields(mover, ITEM_FIELDS) | {"face_edge": getattr(mover, "face_edge", "<unset>")}
    sm2 = _map(cls)
    sm2.fe_cfg = None
    nofe = _shaped("building")
    sm2.measure(nofe)
    out["no_fe"] = _fields(nofe, ITEM_FIELDS)
    sm3 = _map(cls)
    sm3.stationary = True
    st = _shaped("building")
    sm3.measure(st)
    out["stationary"] = _fields(st, ITEM_FIELDS)
    return out


def _corridor_snapshot(cls: Any) -> dict[str, Any]:
    sm = _map(cls)
    lut = sm.fam["building"]
    patch = np.ones((20, 20), dtype=bool)
    hit = sm._corridor_cells(patch, lut, 75, 90)
    miss = sm._corridor_cells(patch, lut, 10, 10)
    return {"hit": list(hit), "miss": list(miss)}


# -- tests ----------------------------------------------------------------------------------------------
def test_identity_with_the_legacy_names() -> None:
    from engine.worldmap import staticmap

    assert collision._StaticMap is staticmap.StaticMap
    assert collision._set_position is staticmap.set_position
    assert collision._mute_solid is staticmap.mute_solid


def test_method_list() -> None:
    from engine.worldmap.staticmap import StaticMap

    reachable = sorted(n for n in dir(StaticMap) if callable(getattr(StaticMap, n)) and (n in METHODS))
    assert reachable == METHODS


def test_set_position() -> None:
    from engine.worldmap.staticmap import set_position

    _same(_set_position_snapshot(set_position), SET_POSITION)


def test_mute_solid() -> None:
    from engine.worldmap.staticmap import mute_solid

    _same(_mute_snapshot(mute_solid), MUTE)


def test_apply() -> None:
    from engine.worldmap.staticmap import StaticMap

    _same(_apply_snapshot(StaticMap), APPLY)


def test_snap_solid() -> None:
    from engine.worldmap.staticmap import StaticMap

    _same(_snap_snapshot(StaticMap), SNAP)


def test_footprint_and_lut() -> None:
    from engine.worldmap.staticmap import StaticMap

    _same(_footprint_snapshot(StaticMap), FOOTPRINT)


def test_corridor_cells() -> None:
    from engine.worldmap.staticmap import StaticMap

    _same(_corridor_snapshot(StaticMap), CORRIDOR)


def test_measure() -> None:
    from engine.worldmap.staticmap import StaticMap

    _same(_measure_snapshot(StaticMap), MEASURE)
