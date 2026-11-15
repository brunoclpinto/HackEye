"""Characterisation tests for engine.worldmap.source.map_source (v26.3.0 p3-08): ``source.mode`` "map" (v26.2.11).

The expected literals were produced by running the legacy ``collision._map_source`` on today's code (hackeye-rnd image)
through the same scenario functions (``_scn_*`` take the function under test). The engine module is imported inside each
test (it does not exist yet). Stubs: ``smap`` has ``pose``, ``judged``, ``region`` and ``_apply``; ``wtracks`` has
``on`` and ``lookup`` (spec p3-08).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

import pytest

import collision

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_CFG: dict[str, Any] = {
    "imageNetSteps": 3.0,
    "imageNetFrames": 2,
    "regionPadM": 2.0,
    "regionMinCells": 2,
    "maxTrackJumpM": 3.0,
    "maxTrackJumpFrac": 0.35,
}

_FIELDS = (
    "srcsel",
    "map_source",
    "distance_m",
    "lateral_m",
    "clock_text",
    "closing",
    "pred_v",
    "track_motion",
    "map_cells",
    "image_dl",
)


class _SmapLike(Protocol):
    pose: tuple[float, float, float]
    judged: frozenset[str]

    def region(self, it: Any, pad_m: float, min_cells: int) -> tuple[float, float, int, int, float] | None: ...

    def _apply(self, it: Any, fwd: float, right: float, n: int) -> None: ...


class _WtLike(Protocol):
    on: bool

    def lookup(self, tid: int, t: float) -> dict[str, Any] | None: ...


class _Smap:
    def __init__(self, regions: dict[int, tuple[float, float, int, int, float] | None] | None = None) -> None:
        self.pose: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.judged: frozenset[str] = frozenset({"building"})
        self._regions: dict[int, tuple[float, float, int, int, float] | None] = regions or {}
        self.region_calls: list[tuple[int, float, int]] = []
        self.apply_calls: list[tuple[int, float, float, int]] = []

    def region(self, it: Any, pad_m: float, min_cells: int) -> tuple[float, float, int, int, float] | None:
        self.region_calls.append((it.track_id, pad_m, min_cells))
        return self._regions.get(it.track_id)

    def _apply(self, it: Any, fwd: float, right: float, n: int) -> None:
        self.apply_calls.append((it.track_id, fwd, right, n))


class _Wt:
    def __init__(self, entries: dict[int, dict[str, Any]] | None = None, on: bool = True) -> None:
        self.on: bool = on
        self._entries: dict[int, dict[str, Any]] = entries or {}

    def lookup(self, tid: int, t: float) -> dict[str, Any] | None:
        return self._entries.get(tid)


def _track(x: float = 0.4, y: float = 8.3, trusted: bool = True) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "vx": 0.0,
        "vy": -1.0,
        "trusted": trusted,
        "state": "seen",
        "static": False,
        "promoted": False,
        "seenS": 2.0,
    }


def _item(tid: int, group: str, label: str, dist: float, **flags: Any) -> Any:
    it = collision._Item(
        group=group,
        class_name=label,
        bbox=[0.4, 0.5, 0.5, 0.6],
        contact_y=0.6,
        distance_m=dist,
        lateral_m=0.0,
        bearing=0.0,
        clock=12,
        pan=0.0,
        area_frac=0.01,
        clipped=False,
        touches=True,
        lane_hit=True,
        along_path=False,
        lane_cover=1.0,
    )
    it.track_id = tid
    for k, v in flags.items():
        setattr(it, k, v)
    return it


def _tracks(items: list[Any], runs: dict[int, int] | None = None) -> dict[int, Any]:
    out: dict[int, Any] = {}
    for it in items:
        box = collision.Box(0.4, 0.5, 0.5, 0.6)
        tr = collision._Track(it.track_id, it.group, it.class_name, box, 0.0, 0.0, it.distance_m, 0.0)
        tr.present_run = (runs or {}).get(it.track_id, 5)
        out[it.track_id] = tr
    return out


def _snap(it: Any) -> dict[str, Any]:
    return {f: getattr(it, f, "<unset>") for f in _FIELDS}


def _run(
    fn: Callable[..., None],
    items: list[Any],
    smap: _Smap,
    wt: _WtLike,
    cfg: dict[str, Any] = DEFAULT_CFG,
    u: float | None = 1.2,
    runs: dict[int, int] | None = None,
) -> dict[str, Any]:
    counts = {"map": 0, "track": 0, "image": 0}
    fn(items, _tracks(items, runs), smap, wt, cfg, 10.0, 0.7, u, counts)
    return {
        "items": {it.track_id: _snap(it) for it in items},
        "counts": counts,
        "region_calls": smap.region_calls,
        "apply_calls": smap.apply_calls,
    }


def _scn_static(fn: Callable[..., None]) -> dict[str, Any]:
    items = [
        _item(1, "static", "pole", 9.0),
        _item(2, "static", "building", 9.0),
        _item(3, "static", "building", 9.0, map_judged=True),
        _item(4, "static", "pole", 9.0),
    ]
    items[2].image_dl = (9.0, 0.0, 0.0, 12, 1, "12", 0.0)
    return _run(fn, items, _Smap({1: (7.4, 1.1, 2, 9, 0.3), 4: None}), _Wt())


def _scn_mover(fn: Callable[..., None]) -> dict[str, Any]:
    return _run(fn, [_item(5, "moving", "person", 8.0)], _Smap(), _Wt({5: _track()}))


def _scn_net(fn: Callable[..., None]) -> dict[str, Any]:
    items = [
        _item(1, "moving", "person", 2.0),  # within 3 steps: the image keeps it
        _item(2, "moving", "person", 8.0),  # track not trusted
        _item(3, "moving", "person", 8.0),  # track jumps 6 m from the image
        _item(4, "static", "pole", 2.0),  # static within 3 steps
        _item(5, "static", "pole", 9.0),  # young track (1 frame)
        _item(6, "moving", "person", 8.0),  # young track (1 frame), trusted
    ]
    wt = _Wt({1: _track(y=2.2), 2: _track(trusted=False), 3: _track(y=14.0), 6: _track()})
    return _run(fn, items, _Smap({4: (1.5, 0.0, 1, 4, 0.2), 5: (7.0, 0.0, 1, 4, 0.2)}), wt, runs={5: 1, 6: 1})


def _scn_skip(fn: Callable[..., None]) -> dict[str, Any]:
    items = [
        _item(1, "moving", "person", 8.0, lane_part=True),
        _item(2, "static", "pole", 9.0, ghost=True),
        _item(3, "moving", "person", 8.0, coasting=True),
    ]
    skipped = _run(fn, items, _Smap(), _Wt({1: _track(), 2: _track(), 3: _track()}))
    no_ego = _run(fn, [_item(4, "moving", "person", 8.0)], _Smap(), _Wt({4: _track()}), u=None)
    wt_off = _run(fn, [_item(4, "moving", "person", 8.0)], _Smap(), _Wt({4: _track()}, on=False))
    return {"skipped": skipped, "no_ego_speed": no_ego, "world_tracks_off": wt_off}


def _scn_cfg(fn: Callable[..., None]) -> dict[str, Any]:
    cfg = {
        "imageNetSteps": 1.0,
        "imageNetFrames": 1,
        "regionPadM": 0.5,
        "regionMinCells": 3,
        "maxTrackJumpM": 4.0,
        "maxTrackJumpFrac": 0.35,
    }
    items = [_item(1, "static", "pole", 9.0), _item(2, "moving", "person", 2.0), _item(3, "moving", "person", 8.0)]
    return _run(fn, items, _Smap({1: (7.4, 1.1, 3, 9, 0.3)}), _Wt({2: _track(y=2.2), 3: _track(y=11.0)}), cfg=cfg)


def _assert_close(got: Any, want: Any, path: str = "") -> None:
    if isinstance(want, dict):
        assert isinstance(got, dict) and got.keys() == want.keys(), path
        for k in want:
            _assert_close(got[k], want[k], f"{path}.{k}")
    elif isinstance(want, (list, tuple)):
        assert isinstance(got, (list, tuple)) and len(got) == len(want), path
        for i, (g, w) in enumerate(zip(got, want, strict=True)):
            _assert_close(g, w, f"{path}[{i}]")
    elif isinstance(want, float):
        assert got == pytest.approx(want, rel=1e-12, abs=1e-12), path
    else:
        assert got == want, path


def test_identity_is_the_legacy_map_source_v26_3_0() -> None:
    from engine.worldmap import source

    assert collision._map_source is source.map_source


def test_static_items_take_their_map_region_or_stay_image_v26_3_0() -> None:
    from engine.worldmap import source

    got = _scn_static(source.map_source)
    _assert_close(got, _WANT_STATIC)


def test_a_mover_comes_from_its_trusted_world_track_v26_3_0() -> None:
    from engine.worldmap import source

    got = _scn_mover(source.map_source)
    _assert_close(got, _WANT_MOVER)


def test_the_image_safety_net_v26_3_0() -> None:
    from engine.worldmap import source

    got = _scn_net(source.map_source)
    _assert_close(got, _WANT_NET)


def test_skipped_items_and_the_gates_v26_3_0() -> None:
    from engine.worldmap import source

    got = _scn_skip(source.map_source)
    _assert_close(got, _WANT_SKIP)


def test_config_keys_are_read_v26_3_0() -> None:
    from engine.worldmap import source

    got = _scn_cfg(source.map_source)
    _assert_close(got, _WANT_CFG)


_WANT_STATIC: Any = {
    "items": {
        1: {
            "srcsel": "map",
            "map_source": "map",
            "distance_m": 9.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": None,
        },
        2: {
            "srcsel": "image",
            "map_source": "",
            "distance_m": 9.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": None,
        },
        3: {
            "srcsel": "map",
            "map_source": "",
            "distance_m": 9.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": (9.0, 0.0, 0.0, 12, 1, "12", 0.0),
        },
        4: {
            "srcsel": "image",
            "map_source": "",
            "distance_m": 9.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": None,
        },
    },
    "counts": {"map": 2, "track": 0, "image": 2},
    "region_calls": [(1, 2.0, 2), (4, 2.0, 2)],
    "apply_calls": [(1, 7.4, 1.1, 2)],
}
_WANT_MOVER: Any = {
    "items": {
        5: {
            "srcsel": "track",
            "map_source": "",
            "distance_m": 8.3,
            "lateral_m": 0.4,
            "clock_text": "12",
            "closing": 2.1974496441216576,
            "pred_v": (-1.0, 0.0),
            "track_motion": (0.9988407473280261, 0.0, 0.048136903485688),
            "map_cells": 0,
            "image_dl": (8.0, 0.0, 0.0, 12, 0, "12", 0.0),
        }
    },
    "counts": {"map": 0, "track": 1, "image": 0},
    "region_calls": [],
    "apply_calls": [],
}
_WANT_NET: Any = {
    "items": {
        1: {
            "srcsel": "image",
            "map_source": "",
            "distance_m": 2.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": None,
        },
        2: {
            "srcsel": "image",
            "map_source": "",
            "distance_m": 8.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": None,
        },
        3: {
            "srcsel": "image",
            "map_source": "",
            "distance_m": 8.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": None,
        },
        4: {
            "srcsel": "image",
            "map_source": "",
            "distance_m": 2.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": None,
        },
        5: {
            "srcsel": "image",
            "map_source": "",
            "distance_m": 9.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": None,
        },
        6: {
            "srcsel": "image",
            "map_source": "",
            "distance_m": 8.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": None,
        },
    },
    "counts": {"map": 0, "track": 0, "image": 6},
    "region_calls": [],
    "apply_calls": [],
}
_WANT_SKIP: Any = {
    "skipped": {
        "items": {
            1: {
                "srcsel": "",
                "map_source": "",
                "distance_m": 8.0,
                "lateral_m": 0.0,
                "clock_text": "12",
                "closing": None,
                "pred_v": None,
                "track_motion": None,
                "map_cells": 0,
                "image_dl": None,
            },
            2: {
                "srcsel": "",
                "map_source": "",
                "distance_m": 9.0,
                "lateral_m": 0.0,
                "clock_text": "12",
                "closing": None,
                "pred_v": None,
                "track_motion": None,
                "map_cells": 0,
                "image_dl": None,
            },
            3: {
                "srcsel": "",
                "map_source": "",
                "distance_m": 8.0,
                "lateral_m": 0.0,
                "clock_text": "12",
                "closing": None,
                "pred_v": None,
                "track_motion": None,
                "map_cells": 0,
                "image_dl": None,
            },
        },
        "counts": {"map": 0, "track": 0, "image": 0},
        "region_calls": [],
        "apply_calls": [],
    },
    "no_ego_speed": {
        "items": {
            4: {
                "srcsel": "image",
                "map_source": "",
                "distance_m": 8.0,
                "lateral_m": 0.0,
                "clock_text": "12",
                "closing": None,
                "pred_v": None,
                "track_motion": None,
                "map_cells": 0,
                "image_dl": None,
            }
        },
        "counts": {"map": 0, "track": 0, "image": 1},
        "region_calls": [],
        "apply_calls": [],
    },
    "world_tracks_off": {
        "items": {
            4: {
                "srcsel": "image",
                "map_source": "",
                "distance_m": 8.0,
                "lateral_m": 0.0,
                "clock_text": "12",
                "closing": None,
                "pred_v": None,
                "track_motion": None,
                "map_cells": 0,
                "image_dl": None,
            }
        },
        "counts": {"map": 0, "track": 0, "image": 1},
        "region_calls": [],
        "apply_calls": [],
    },
}
_WANT_CFG: Any = {
    "items": {
        1: {
            "srcsel": "map",
            "map_source": "map",
            "distance_m": 9.0,
            "lateral_m": 0.0,
            "clock_text": "12",
            "closing": None,
            "pred_v": None,
            "track_motion": None,
            "map_cells": 0,
            "image_dl": None,
        },
        2: {
            "srcsel": "track",
            "map_source": "",
            "distance_m": 2.2,
            "lateral_m": 0.4,
            "clock_text": "12:15",
            "closing": 2.1645138022197967,
            "pred_v": (-1.0, 0.0),
            "track_motion": (0.9838699100999075, 0.0, 0.17888543819998318),
            "map_cells": 0,
            "image_dl": (2.0, 0.0, 0.0, 12, 0, "12", 0.0),
        },
        3: {
            "srcsel": "track",
            "map_source": "",
            "distance_m": 11.0,
            "lateral_m": 0.4,
            "clock_text": "12",
            "closing": 2.1985468954821505,
            "pred_v": (-1.0, 0.0),
            "track_motion": (0.9993394979464321, 0.0, 0.036339618107142986),
            "map_cells": 0,
            "image_dl": (8.0, 0.0, 0.0, 12, 0, "12", 0.0),
        },
    },
    "counts": {"map": 1, "track": 2, "image": 0},
    "region_calls": [(1, 0.5, 3)],
    "apply_calls": [(1, 7.4, 1.1, 3)],
}
