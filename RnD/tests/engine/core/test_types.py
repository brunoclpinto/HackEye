"""Characterisation tests for engine.core.types (v26.3.0 p1-09): Item, Track, Region, constants, trusted_track.

Every literal below was printed by the legacy ``collision`` module (``_Item`` / ``_Track`` / ``Region`` /
``_trusted_track``) in the hackeye-rnd image before the move. The engine module is imported inside each test.
"""

from __future__ import annotations

import dataclasses
import importlib
import math
from typing import Any

import collision
from geometry import Box

ITEM_FIELDS: list[str] = [
    "group",
    "class_name",
    "bbox",
    "contact_y",
    "distance_m",
    "lateral_m",
    "bearing",
    "clock",
    "pan",
    "area_frac",
    "clipped",
    "touches",
    "lane_hit",
    "along_path",
    "lane_cover",
    "contact_y_raw",
    "area_m2",
    "track_id",
    "closing",
    "moving",
    "approaching",
    "steps",
    "label",
    "role",
    "urgency",
    "settled",
    "family",
    "role_run",
    "closing_raw",
    "landmark",
    "receding",
    "ego_known",
    "own_fast",
    "ego_settled",
    "summary_ok",
    "people",
    "fast",
    "speak",
    "thin",
    "collision",
    "prox_run",
    "proximity",
    "present_run",
    "wx",
    "wy",
    "mem_id",
    "mem_named",
    "mem_approach",
    "mem_danger",
    "shape",
    "clock_q",
    "clock_text",
    "depth_m",
    "depth_on",
    "depth_raw",
    "from_depth",
    "lat_vel",
    "cross_mps",
    "depth_cells",
    "lane_part_weak",
    "lane_part",
    "map_source",
    "map_cells",
    "map_world",
    "image_dl",
    "solid_corrected",
    "raw_distance_m",
    "inside_solid",
    "coasting",
    "ghost",
    "map_judged",
    "face_edge",
    "base_row",
    "base_col",
    "dist_source",
    "raw_depth_m",
    "ground_m",
    "srcsel",
    "track_motion",
    "tree",
    "unstable",
    "jumped",
    "full_ref",
    "pred_v",
    "followed",
    "own",
    "own_ok",
    "own_closing",
    "near_pass",
    "from_side",
]

TRACK_FIELDS: list[str] = [
    "id",
    "group",
    "class_name",
    "box",
    "last_t",
    "first_t",
    "last_distance",
    "last_lateral",
    "history",
    "closing",
    "moving",
    "danger_done",
    "final_done",
    "feature_done",
    "thin_done",
    "contact_s",
    "present_run",
    "role",
    "role_run",
    "mem_id",
    "linked_t",
    "under_last",
    "under_fired",
    "dhist",
    "lhist",
    "lp_strong_t",
    "lane_part",
    "along_s",
    "along_t",
    "feature_frames",
    "approach_done",
    "mstate",
    "prox_run",
    "context_seen",
    "ghost_src",
    "ghost_t0",
    "still_t0",
    "d_prev",
    "d_prev_t",
    "df_prev",
    "df_prev_t",
    "jump_t",
    "said",
]

REGION_FIELDS: list[str] = ["group", "label", "mask", "left", "right"]

ITEM_DEFAULTS: dict[str, Any] = {
    "group": "static",
    "class_name": "pole",
    "bbox": [0.4, 0.4, 0.5, 0.6],
    "contact_y": 0.6,
    "distance_m": 8.0,
    "lateral_m": 0.0,
    "bearing": 0.0,
    "clock": 12,
    "pan": 0.0,
    "area_frac": 0.01,
    "clipped": False,
    "touches": True,
    "lane_hit": True,
    "along_path": False,
    "lane_cover": 0.3,
    "contact_y_raw": 0.0,
    "area_m2": 0.0,
    "track_id": 0,
    "closing": None,
    "moving": None,
    "approaching": False,
    "steps": 0.0,
    "label": "",
    "role": "none",
    "urgency": "none",
    "settled": False,
    "family": "",
    "role_run": 0,
    "closing_raw": None,
    "landmark": False,
    "receding": False,
    "ego_known": False,
    "own_fast": False,
    "ego_settled": False,
    "summary_ok": False,
    "people": False,
    "fast": False,
    "speak": True,
    "thin": False,
    "collision": False,
    "prox_run": 0,
    "proximity": False,
    "present_run": 0,
    "wx": 0.0,
    "wy": 0.0,
    "mem_id": None,
    "mem_named": False,
    "mem_approach": False,
    "mem_danger": False,
    "shape": None,
    "clock_q": 0,
    "clock_text": "12",
    "depth_m": None,
    "depth_on": False,
    "depth_raw": None,
    "from_depth": False,
    "lat_vel": None,
    "cross_mps": None,
    "depth_cells": None,
    "lane_part_weak": False,
    "lane_part": False,
    "map_source": "",
    "map_cells": 0,
    "map_world": None,
    "image_dl": None,
    "solid_corrected": False,
    "raw_distance_m": None,
    "inside_solid": False,
    "coasting": False,
    "ghost": False,
    "map_judged": False,
    "face_edge": None,
    "base_row": -1,
    "base_col": -1,
    "dist_source": "",
    "raw_depth_m": None,
    "ground_m": None,
    "srcsel": "",
    "track_motion": None,
    "tree": False,
    "unstable": False,
    "jumped": False,
    "full_ref": None,
    "pred_v": None,
    "followed": False,
    "own": None,
    "own_ok": False,
    "own_closing": None,
    "near_pass": False,
    "from_side": "",
}

TRACK_POSITIONAL: dict[str, Any] = {
    "id": 5,
    "group": "moving",
    "class_name": "person",
    "last_t": 0.0,
    "first_t": 0.0,
    "last_distance": 5.9,
    "last_lateral": -2.4,
    "history": [],
    "closing": None,
    "moving": None,
    "danger_done": False,
    "final_done": False,
    "feature_done": False,
    "thin_done": False,
    "contact_s": None,
    "present_run": 0,
    "role": "none",
    "role_run": 0,
    "mem_id": None,
    "linked_t": 0.0,
    "under_last": None,
    "under_fired": False,
    "dhist": [],
    "lhist": [],
    "lp_strong_t": None,
    "lane_part": False,
    "along_s": None,
    "along_t": 0.0,
    "feature_frames": 0,
    "approach_done": False,
    "mstate": None,
    "prox_run": 0,
    "context_seen": False,
    "ghost_src": None,
    "ghost_t0": None,
    "still_t0": None,
    "d_prev": None,
    "d_prev_t": -math.inf,
    "df_prev": None,
    "df_prev_t": -math.inf,
    "jump_t": -math.inf,
    "said": None,
}


ITEM_REQUIRED = [
    "group", "class_name", "bbox", "contact_y", "distance_m", "lateral_m", "bearing", "clock", "pan", "area_frac",
    "clipped", "touches", "lane_hit", "along_path", "lane_cover",
]  # fmt: skip


def _types() -> Any:
    return importlib.import_module("engine.core.types")


def _kw(**over: Any) -> dict[str, Any]:
    kw: dict[str, Any] = dict(
        group="static", class_name="pole", bbox=[0.4, 0.4, 0.5, 0.6], contact_y=0.6, distance_m=8.0, lateral_m=0.0,
        bearing=0.0, clock=12, pan=0.0, area_frac=0.01, clipped=False, touches=True, lane_hit=True,
        along_path=False, lane_cover=0.3,
    )  # fmt: skip
    kw.update(over)
    return kw


def test_identity_classes_and_functions() -> None:
    types = _types()
    assert collision._Item is types.Item
    assert collision._Track is types.Track
    assert collision.Region is types.Region
    assert collision._trusted_track is types.trusted_track


def test_identity_constants() -> None:
    types = _types()
    assert collision.LANE_PART_ID_BASE is types.LANE_PART_ID_BASE
    assert collision.POINT_ASPECT is types.POINT_ASPECT
    assert types.LANE_PART_ID_BASE == 1000000
    assert types.POINT_ASPECT == 3.0


def test_class_names() -> None:
    types = _types()
    assert types.Item.__name__ in {"Item", "_Item"}
    assert types.Track.__name__ in {"Track", "_Track"}
    assert not hasattr(types.Item, "__slots__")
    assert not hasattr(types.Track, "__slots__")


def test_item_field_order() -> None:
    types = _types()
    names = [f.name for f in dataclasses.fields(types.Item)]
    assert len(names) == 90
    assert names == ITEM_FIELDS


def test_track_field_order() -> None:
    types = _types()
    names = [f.name for f in dataclasses.fields(types.Track)]
    assert len(names) == 43
    assert names == TRACK_FIELDS


def test_region_field_order() -> None:
    types = _types()
    names = [f.name for f in dataclasses.fields(types.Region)]
    assert names == REGION_FIELDS


def test_item_required_fields() -> None:
    types = _types()
    required = [
        f.name
        for f in dataclasses.fields(types.Item)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
    ]
    assert required == ITEM_REQUIRED


def test_item_defaults() -> None:
    types = _types()
    item = types.Item(**_kw())
    assert dataclasses.asdict(item) == ITEM_DEFAULTS


def test_item_post_init_fills_clock_fields() -> None:
    types = _types()
    expected = {1: (4, "1"), 3: (12, "3"), 12: (0, "12"), 6: (-24, "6")}
    for clock, (q, text) in expected.items():
        item = types.Item(**_kw(clock=clock))
        assert (item.clock_q, item.clock_text) == (q, text)


def test_item_post_init_does_not_overwrite() -> None:
    types = _types()
    item = types.Item(**_kw(clock_q=5))
    assert (item.clock_q, item.clock_text) == (5, "1:15")
    item = types.Item(**_kw(clock_text="x"))
    assert (item.clock_q, item.clock_text) == (0, "x")
    item = types.Item(**_kw(clock_q=5, clock_text="x"))
    assert (item.clock_q, item.clock_text) == (5, "x")


def test_replace_reruns_post_init_but_keeps_filled_values() -> None:
    types = _types()
    item = types.Item(**_kw(clock=3))
    assert (item.clock_q, item.clock_text) == (12, "3")
    same = dataclasses.replace(item, distance_m=2.5)
    assert same is not item
    assert (same.distance_m, same.clock_q, same.clock_text) == (2.5, 12, "3")
    # clock_q / clock_text are copied, so a new clock is NOT re-derived
    moved = dataclasses.replace(item, clock=9)
    assert (moved.clock, moved.clock_q, moved.clock_text) == (9, 12, "3")


def test_replace_refills_blank_clock_fields() -> None:
    types = _types()
    item = types.Item(**_kw(clock=3))
    item.clock_q = None
    item.clock_text = ""
    copy = dataclasses.replace(item, distance_m=2.5)
    assert (copy.clock_q, copy.clock_text) == (12, "3")


def test_item_new_then_attribute_assignment() -> None:
    types = _types()
    item = types.Item.__new__(types.Item)
    item.group = "g"
    item.distance_m = 3.0
    assert (item.group, item.distance_m) == ("g", 3.0)
    assert hasattr(item, "clock_q")  # class-level default
    assert not hasattr(item, "bbox")  # required field, never set


def test_track_positional_construction() -> None:
    types = _types()
    box = Box(0.1, 0.2, 0.3, 0.4)
    track = types.Track(5, "moving", "person", box, 0.0, 0.0, 5.9, -2.4)
    got = {k: v for k, v in dataclasses.asdict(track).items() if k != "box"}
    assert got == TRACK_POSITIONAL
    assert track.box is box


def test_track_positional_with_history() -> None:
    types = _types()
    box = Box(0.1, 0.2, 0.3, 0.4)
    track = types.Track(1, "static", "x", box, 0.0, 0.0, 0.0, 5.0, [(0.0, 1.0)])
    assert track.history == [(0.0, 1.0)]
    assert (track.closing, track.role) == (None, "none")
    # the 9th positional lands in ``history`` (tests/test_collision.py passes 0.0 there)
    odd = types.Track(1, "static", "x", box, 0.0, 0.0, 0.0, 5.0, 0.0)
    assert odd.history == 0.0


def test_track_history_lists_not_shared() -> None:
    types = _types()
    box = Box(0.1, 0.2, 0.3, 0.4)
    a = types.Track(1, "static", "x", box, 0.0, 0.0, 0.0, 5.0)
    b = types.Track(2, "static", "x", box, 0.0, 0.0, 0.0, 5.0)
    a.history.append((1.0, 2.0))
    assert b.history == []
    assert a.dhist is not b.dhist
    assert a.lhist is not b.lhist
    assert math.isinf(a.d_prev_t) and a.d_prev_t < 0


class _Lookup:
    def __init__(self, result: dict[str, Any] | None) -> None:
        self.result = result
        self.calls: list[tuple[int, float]] = []

    def lookup(self, tid: int, t: float) -> dict[str, Any] | None:
        self.calls.append((tid, t))
        return self.result


def test_trusted_track_none_and_untrusted() -> None:
    types = _types()
    for result in (None, {"trusted": False}):
        stub = _Lookup(result)
        assert types.trusted_track(stub, 7, 1.5) is None
        assert stub.calls == [(7, 1.5)]


def test_trusted_track_trusted_returns_same_entry() -> None:
    types = _types()
    entry = {"trusted": True, "k": 1}
    stub = _Lookup(entry)
    out = types.trusted_track(stub, 7, 1.5)
    assert out is entry
    assert out == {"trusted": True, "k": 1}
    assert stub.calls == [(7, 1.5)]
