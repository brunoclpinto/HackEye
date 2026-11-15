"""Characterisation tests for engine.worldmap.blocked.BlockedMixin (v26.3.0 p3-07).

The expected dicts were produced by running the legacy ``collision._StaticMap.blocked_ahead`` on today's code
(hackeye-rnd image) through the scenarios of ``tests/test_collision_v26212.py`` (section 9, "blocked ahead"), built
on ``__new__`` instances; the engine module is imported inside each test (it does not exist yet).
"""

from __future__ import annotations

import types
from typing import Any

import numpy as np
import pytest

import collision

BCFG: dict[str, Any] = collision.load_config()["blocked"]

WALL_FREE_LEFT: dict[str, Any] = {
    "kind": "wall",
    "share": 0.92,
    "label": "sidewalk",
    "cfwd": 1.85,
    "cright": -0.0,
    "blockQ": 0,
    "blockClock": "12",
    "wideOk": True,
    "free": True,
    "endClass": "flat sidewalk",
    "clearM": 7.9,
    "bearingDeg": -37.5,
    "clockQ": -5,
    "clock": "10:45",
    "fwd": 6.27,
    "right": -4.81,
}


def _fake_map(solid_cols: tuple[float, float] | None = None, size: int = 200, cell: float = 0.1) -> Any:
    names = ["building", "flat sidewalk", "flat road", "barrier"]
    m = object.__new__(collision._StaticMap)
    rows, cols = np.mgrid[0:size, 0:size]
    m.ob = types.SimpleNamespace(
        fwd=(190 - rows) * cell, right=(cols - 100) * cell, size=size, orow=190, oc=100, cell=cell
    )
    m.classes = np.full((size, size), 2, dtype=np.int64)
    m.conf = np.full((size, size), 255, dtype=np.int64)
    sw = (m.ob.fwd > -1) & (m.ob.right < 1.0)
    m.classes[sw] = 1
    if solid_cols is not None:
        lo, hi = solid_cols
        m.classes[(m.ob.fwd > 1.0) & (m.ob.fwd < 3.5) & (m.ob.right >= lo) & (m.ob.right <= hi)] = 0
    m._names, m.min_conf, m.lane_half = names, 178, 0.6
    return m


def _recent(m: Any, pts: list[tuple[float, float]], pose: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None:
    """Object-base points (forward m, right m) seen from the origin pose, kept as world points."""
    m.obs_hist = [(0.0, np.array([p[1] for p in pts]), np.array([p[0] for p in pts]))]
    m.pose = pose


def _same(got: dict[str, Any] | None, want: dict[str, Any] | None) -> None:
    if want is None:
        assert got is None
        return
    assert got is not None
    assert list(got) == list(want)
    for k, v in want.items():
        if isinstance(v, float):
            assert got[k] == pytest.approx(v, rel=1e-12, abs=1e-12), k
        else:
            assert got[k] == v, k
            assert type(got[k]) is type(v), k


def _obstacle_pts() -> list[tuple[float, float]]:
    return [(5.0, float(x)) for x in np.arange(-0.55, 0.0, 0.1)]  # 6 of the 12 lane bins at 5 m, nothing in the map


# -- facade identity --


def test_blocked_mixin_is_in_the_mro_and_the_method_is_the_mixins() -> None:
    from engine.worldmap.blocked import BlockedMixin

    assert BlockedMixin in collision._StaticMap.__mro__
    assert collision._StaticMap.blocked_ahead is BlockedMixin.blocked_ahead
    assert "blocked_ahead" in vars(BlockedMixin)
    assert "__init__" not in vars(BlockedMixin)


def test_blocked_module_does_not_import_staticmap() -> None:
    from engine.worldmap import blocked

    assert not hasattr(blocked, "staticmap")
    assert not hasattr(blocked, "StaticMap")


# -- the lazy lookup-table cache --


def test_blk_cache_is_built_lazily_on_the_instance_and_kept() -> None:
    m = _fake_map((-0.6, 0.6))
    assert "_blk" not in m.__dict__
    m.blocked_ahead(BCFG)
    assert "_blk" in m.__dict__
    blk = m._blk
    assert len(blk) == 4
    assert [x.shape for x in blk] == [(256,), (256,), (256,), (256,)]
    assert [int(x.sum()) for x in blk] == [2, 1, 1, 1]  # solid, walkable, wall, obstacle lookup tables
    m.blocked_ahead({})  # a different config does not rebuild it
    assert m._blk is blk


def test_no_classes_returns_none_without_building_the_cache() -> None:
    m = _fake_map((-0.6, 0.6))
    m.classes = None
    assert m.blocked_ahead(BCFG) is None
    assert "_blk" not in m.__dict__


# -- the wall kind --


def test_whole_lane_wall_is_blocked_and_the_sidewalk_continues_to_the_left() -> None:
    _same(_fake_map((-0.6, 0.6)).blocked_ahead(BCFG), WALL_FREE_LEFT)


def test_forty_percent_of_the_lane_or_no_solid_is_not_blocked() -> None:
    assert _fake_map((0.2, 0.6)).blocked_ahead(BCFG) is None
    assert _fake_map(None).blocked_ahead(BCFG) is None


def test_no_walkable_ground_gives_free_none() -> None:
    m = _fake_map((-0.6, 0.6))
    sel = m.ob.fwd > 0.3
    m.classes[sel] = np.where(m.classes[sel] == 1, 2, m.classes[sel])
    want: dict[str, Any] = {
        "kind": "wall",
        "share": 0.92,
        "label": "sidewalk",
        "cfwd": 1.85,
        "cright": -0.0,
        "blockQ": 0,
        "blockClock": "12",
        "wideOk": True,
        "free": None,
    }
    _same(m.blocked_ahead(BCFG), want)


def test_wall_within_3_m_is_a_wall_and_one_starting_at_3_1_m_is_nothing() -> None:
    _same(_fake_map((-0.6, 0.6)).blocked_ahead(BCFG), WALL_FREE_LEFT)
    far = _fake_map((-0.6, 0.6))
    far.classes[(far.ob.fwd <= 3.5) & (far.ob.fwd > 3.0)] = 1
    far.classes[(far.ob.fwd > 1.0) & (far.ob.fwd <= 3.0)] = 1
    far.classes[(far.ob.fwd > 3.05) & (far.ob.fwd < 3.5) & (abs(far.ob.right) <= 0.6)] = 0
    assert far.blocked_ahead(BCFG) is None


def test_a_barrier_at_3_m_is_the_obstacle_kind() -> None:
    bar = _fake_map((-0.6, 0.6))
    bar.classes[bar.classes == 0] = 3
    want = dict(WALL_FREE_LEFT, kind="obstacle")
    _same(bar.blocked_ahead(BCFG), want)


def test_free_direction_is_the_smallest_angle_past_the_blockage() -> None:
    m = _fake_map((-0.6, 0.0))
    m.classes[(m.ob.fwd > 0.9) & (m.ob.fwd < 3.6) & (m.ob.right >= -0.6) & (m.ob.right <= 0.6)] = 1
    m.classes[(m.ob.fwd > 1.0) & (m.ob.fwd < 3.5) & (m.ob.right >= -0.6) & (m.ob.right <= 0.6) & (m.ob.right < 0.0)] = 0
    m.classes[(m.ob.fwd > 1.0) & (m.ob.fwd < 3.5) & (m.ob.right >= 0.0) & (m.ob.right <= 0.6)] = 0
    _same(m.blocked_ahead(BCFG), WALL_FREE_LEFT)


# -- the obstacle kind (recent object bases, dead-reckoned) --


def test_obstacle_with_half_the_lane_at_5_m() -> None:
    m = _fake_map()
    _recent(m, _obstacle_pts())
    want: dict[str, Any] = {
        "kind": "obstacle",
        "share": 0.5,
        "label": "sidewalk",
        "cfwd": 5.0,
        "cright": -0.3,
        "blockQ": 0,
        "blockClock": "12",
        "wideOk": True,
        "free": True,
        "endClass": "flat sidewalk",
        "clearM": 7.2,
        "bearingDeg": 7.5,
        "clockQ": 1,
        "clock": "12:15",
        "fwd": 7.14,
        "right": 0.94,
    }
    _same(m.blocked_ahead(BCFG), want)


def test_obstacle_with_5_of_12_bins_is_not_enough() -> None:
    m = _fake_map()
    _recent(m, _obstacle_pts()[:5])
    assert m.blocked_ahead(BCFG) is None


def test_obstacle_points_are_dead_reckoned_to_the_pose_now() -> None:
    m = _fake_map()
    _recent(m, _obstacle_pts(), pose=(0.0, 4.0, 0.0))  # walked 4 m: the points are 1 m ahead
    want: dict[str, Any] = {
        "kind": "obstacle",
        "share": 0.5,
        "label": "sidewalk",
        "cfwd": 1.0,
        "cright": -0.3,
        "blockQ": -2,
        "blockClock": "11:30",
        "wideOk": True,
        "free": True,
        "endClass": "flat sidewalk",
        "clearM": 3.6,
        "bearingDeg": 15.0,
        "clockQ": 2,
        "clock": "12:30",
        "fwd": 3.48,
        "right": 0.93,
    }
    _same(m.blocked_ahead(BCFG), want)
    passed = _fake_map()
    _recent(passed, _obstacle_pts(), pose=(0.0, 5.5, 0.0))  # passed by 0.5 m: gone
    assert passed.blocked_ahead(BCFG) is None


def test_obstacle_beyond_the_6_5_m_reach_is_nothing() -> None:
    m = _fake_map()
    _recent(m, [(7.0, float(x)) for x in np.arange(-0.6, 0.6, 0.1)])
    assert m.blocked_ahead(BCFG) is None


# -- the engine mixin behaves like the legacy class (runs red until engine.worldmap.blocked exists) --


def test_the_mixin_method_gives_the_pinned_dict_on_a_new_instance() -> None:
    from engine.worldmap.blocked import BlockedMixin

    m = _fake_map((-0.6, 0.6))
    _same(BlockedMixin.blocked_ahead(m, BCFG), WALL_FREE_LEFT)
