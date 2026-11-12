"""Characterisation tests for engine.core.classes (v26.3.0 p1-05).

Every expected literal was produced by running the legacy code (collision.py) in the hackeye-rnd image on the
pre-move code, not computed by hand. The collision config is read straight from common/config/collision.json
(not through collision.load_config, which the test conftest patches).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

import collision
from common_paths import find_common_dir

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "chest0004_review7.json"


def _config() -> dict[str, Any]:
    cfg: dict[str, Any] = json.loads((find_common_dir() / "config" / "collision.json").read_text())
    return cfg


def _fixture_names() -> list[str]:
    names: list[str] = json.loads(FIXTURE.read_text())["classNames"]
    return names


def test_facade_identity() -> None:
    from engine.core import classes

    assert collision.ClassIds is classes.ClassIds
    assert collision.resolve_class_ids is classes.resolve_class_ids
    assert collision.ITEM_GROUPS is classes.ITEM_GROUPS
    assert collision.NO_DATA is classes.NO_DATA
    assert collision._4_CONNECTIVITY is classes.FOUR_CONNECTIVITY


def test_item_groups() -> None:
    from engine.core.classes import ITEM_GROUPS

    assert ITEM_GROUPS == ("static", "moving", "feature")
    assert isinstance(ITEM_GROUPS, tuple)


def test_no_data() -> None:
    from engine.core.classes import NO_DATA

    assert NO_DATA == 255


def test_four_connectivity() -> None:
    from engine.core.classes import FOUR_CONNECTIVITY

    assert FOUR_CONNECTIVITY.tolist() == [[0, 1, 0], [1, 1, 1], [0, 1, 0]]
    assert FOUR_CONNECTIVITY.dtype == np.int64
    assert FOUR_CONNECTIVITY.shape == (3, 3)


def test_resolve_class_ids_fixture_model() -> None:
    from engine.core.classes import resolve_class_ids

    names = _fixture_names()
    assert len(names) == 48
    r = resolve_class_ids(_config(), names)

    assert r.names == names
    assert list(r.surface_groups) == ["pedestrian", "bikeLane", "road", "rail"]
    assert r.surface_groups["pedestrian"].tolist() == [16, 11, 17]
    assert r.surface_groups["bikeLane"].tolist() == [7]
    assert r.surface_groups["road"].tolist() == [13, 14, 15, 9, 10]
    assert r.surface_groups["rail"].tolist() == [12]
    for v in r.surface_groups.values():
        assert v.dtype == np.int64

    assert r.inside.tolist() == [8, 2, 23, 24, 25, 26, 27, 36, 38, 45]
    assert r.inside.dtype == np.int64

    assert list(r.items) == ["static", "moving", "feature"]
    assert r.items["static"] == [37, 34, 39, 40, 41, 35, 1, 3, 4, 5, 6, 32, 19]
    assert r.items["moving"] == [21, 22, 42, 0]
    assert r.items["feature"] == [2, 8, 38]
    for group in r.items.values():
        assert all(type(i) is int for i in group)

    assert r.people == frozenset({"animal", "person", "rider"})
    assert r.fast == frozenset({"rider", "vehicle"})
    assert r.thin == frozenset({"pole", "sign", "traffic-light", "traffic-light pedestrians", "traffic-sign"})
    assert r.landmark == frozenset({"crosswalk"})


def test_resolve_class_ids_hand_list_with_unknown_names() -> None:
    from engine.core.classes import resolve_class_ids

    names = [
        "flat road",
        "person",
        "martian",
        "curb",
        "flat sidewalk",
        "rider",
        "crosswalk",
        "vehicle",
        "no such class",
    ]
    r = resolve_class_ids(_config(), names)

    assert r.names == names
    assert r.surface_groups["pedestrian"].tolist() == [4]
    assert r.surface_groups["bikeLane"].tolist() == []
    assert r.surface_groups["road"].tolist() == [0]
    assert r.surface_groups["rail"].tolist() == []
    assert r.inside.tolist() == [6, 3]
    assert r.items == {"static": [], "moving": [1, 5, 7], "feature": [3, 6]}
    assert r.people == frozenset({"animal", "person", "rider"})
    assert r.fast == frozenset({"rider", "vehicle"})
    assert r.thin == frozenset({"pole", "sign", "traffic-light", "traffic-light pedestrians", "traffic-sign"})
    assert r.landmark == frozenset({"crosswalk"})


def test_resolve_class_ids_minimal_config_defaults() -> None:
    from engine.core.classes import resolve_class_ids

    cfg = {"surfaces": {"groups": {"road": {"label": "road", "classes": ["flat road"]}}, "inside": []}, "classes": {}}
    r = resolve_class_ids(cfg, ["flat road", "person"])

    assert r.names == ["flat road", "person"]
    assert r.surface_groups["road"].tolist() == [0]
    assert r.surface_groups["road"].dtype == np.int64
    assert r.inside.tolist() == []
    assert r.inside.dtype == np.int64
    assert r.items == {"static": [], "moving": [], "feature": []}
    assert r.people == frozenset()
    assert r.fast == frozenset()
    assert r.thin == frozenset()
    assert r.landmark == frozenset()
