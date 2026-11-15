"""Characterisation tests for engine.output (v26.3.0 p3-15): outline and hazards.

Every literal below was printed by the legacy ``collision`` functions (``trace_outline``, ``simplify_polygon``,
``_dp_open``, ``item_outline``, ``item_full``, ``_hazard_dict``, ``_hazard_json``, ``_lane_polygon``, ``_region_rows``)
in the hackeye-rnd image before the move, on the inputs built by the helpers of this file. The engine modules are
imported inside each test (they do not exist yet).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

import collision

BoolMask = npt.NDArray[np.bool_]

IDENTITY: list[tuple[str, str, str]] = [
    ("engine.output.outline", "OUTLINE_EPS_PX", "OUTLINE_EPS_PX"),
    ("engine.output.outline", "OUTLINE_MAX_POINTS", "OUTLINE_MAX_POINTS"),
    ("engine.output.outline", "DIRS", "_DIRS"),
    ("engine.output.outline", "trace_outline", "trace_outline"),
    ("engine.output.outline", "dp_open", "_dp_open"),
    ("engine.output.outline", "simplify_polygon", "simplify_polygon"),
    ("engine.output.outline", "item_outline", "item_outline"),
    ("engine.output.outline", "item_full", "item_full"),
    ("engine.output.hazards", "lane_polygon", "_lane_polygon"),
    ("engine.output.hazards", "region_rows", "_region_rows"),
    ("engine.output.hazards", "hazard_json", "_hazard_json"),
    ("engine.output.hazards", "hazard_dict", "_hazard_dict"),
]


def _masks() -> dict[str, BoolMask]:
    sq = np.zeros((6, 7), bool)
    sq[1:4, 2:5] = True
    ell = np.zeros((6, 6), bool)
    ell[1:5, 1:3] = True
    ell[3:5, 1:5] = True
    ring = np.zeros((7, 7), bool)
    ring[1:6, 1:6] = True
    ring[3, 3] = True
    one = np.zeros((3, 3), bool)
    one[1, 1] = True
    yy, xx = np.mgrid[0:45, 0:45]
    disc: BoolMask = (yy - 22) ** 2 + (xx - 22) ** 2 <= 20**2
    return {"square": sq, "L": ell, "ring": ring, "single": one, "disc": disc}


def _mk(**kw: Any) -> Any:
    group = kw.pop("group", "static")
    cn = kw.pop("cn", "wall")
    it = collision._Item(
        group=group,
        class_name=cn,
        bbox=[0.12345678, 0.2, 0.5, 0.6],
        contact_y=0.6123456,
        distance_m=7.456,
        lateral_m=-0.123,
        bearing=-3.456,
        clock=11,
        pan=-0.12345,
        area_frac=0.0123456,
        clipped=False,
        touches=True,
        lane_hit=True,
        along_path=False,
        lane_cover=1.0,
    )
    for k, v in kw.items():
        setattr(it, k, v)
    return it


def _items() -> dict[str, Any]:
    masks = _masks()
    minimal = _mk()
    full = _mk(
        group="moving", cn="person", track_id=7, label="person", role="danger", moving=True, clock_q=3,
        clock_text="11:45", steps=10.04, closing=1.2345, urgency="danger", collision=True, lat_vel=0.456,
        cross_mps=-0.789, depth_on=True, depth_m=7.8, lane_part=True, image_dl=(8.1234, 0.5678, 1, 2, 3, "x", 0.1),
        ghost=True, coasting=True, inside_solid=True, solid_corrected=True, raw_distance_m=9.876, face_edge={"a": 1},
        own=(1.0, 2.0), from_side="left", near_pass=True, dist_source="fused", raw_depth_m=7.7777, ground_m=7.123,
        srcsel="depth",
    )  # fmt: skip
    static = _mk(
        track_id=3,
        label="wall",
        role="danger",
        map_source="map",
        map_cells=12,
        shape=(masks["L"], 4, 5),
        clock_text="11",
    )
    fl = np.zeros((10, 12), int)
    fl[2:6, 3:8] = 5
    fl[3:5, 4:7] = 0
    fsl = (slice(1, 8), slice(2, 10))
    fr = _mk(track_id=4, label="b", role="none", shape=(masks["square"], 1, 1), full_ref=(fl, fsl, 5))
    return {"minimal": minimal, "full": full, "static": static, "fr": fr}


BASE_KEYS = [
    "trackId", "className", "group", "label", "role", "moving", "bbox", "contactY", "bearingDeg", "clock",
    "clockText", "pan", "distanceM", "lateralM", "stepsTo", "closingMps", "urgency", "areaFrac", "collision",
    "latVelMps", "crossMps",
]  # fmt: skip
FULL_KEYS = [
    *BASE_KEYS,
    "depthM", "lanePart", "source", "imageDistanceM", "imageLateralM", "ghost", "coasting", "insideSolid",
    "solidCorrected", "rawDistanceM", "faceEdge", "ownMps", "fromSide", "nearPass", "distanceSource", "rawDepthM",
    "groundM",
]  # fmt: skip

TRACE: dict[str, list[tuple[int, int]]] = {
    "square": [(2, 1), (5, 1), (5, 4), (2, 4)],
    "L": [(1, 1), (3, 1), (3, 3), (5, 3), (5, 5), (1, 5)],
    "ring": [(1, 1), (6, 1), (6, 6), (1, 6)],
    "single": [(1, 1), (2, 1), (2, 2), (1, 2)],
}
SIMP: dict[str, list[tuple[float, float]]] = {
    "square": [(2.0, 1.0), (5.0, 1.0), (5.0, 4.0), (2.0, 4.0)],
    "L": [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (5.0, 3.0), (5.0, 5.0), (1.0, 5.0)],
    "ring": [(1.0, 1.0), (6.0, 1.0), (6.0, 6.0), (1.0, 6.0)],
    "single": [(1.0, 1.0), (2.0, 2.0)],
}
SIMP_EPS3_6: dict[str, list[tuple[float, float]]] = {
    "square": [(2.0, 1.0), (5.0, 4.0)],
    "L": [(1.0, 1.0), (5.0, 5.0)],
    "ring": [(1.0, 1.0), (6.0, 1.0), (6.0, 6.0), (1.0, 6.0)],
    "single": [(1.0, 1.0), (2.0, 2.0)],
    "disc": [(22.0, 2.0), (43.0, 22.0), (23.0, 43.0), (2.0, 23.0)],
}
DISC_SIMP: list[tuple[float, float]] = [
    (22.0, 2.0), (29.0, 3.0), (35.0, 6.0), (39.0, 10.0), (42.0, 16.0), (42.0, 22.0), (43.0, 22.0), (42.0, 29.0),
    (39.0, 35.0), (35.0, 39.0), (29.0, 42.0), (23.0, 42.0), (23.0, 43.0), (16.0, 42.0), (10.0, 39.0), (6.0, 35.0),
    (3.0, 29.0), (3.0, 23.0), (2.0, 23.0), (3.0, 16.0), (6.0, 10.0), (10.0, 6.0), (16.0, 3.0), (22.0, 3.0),
]  # fmt: skip


@pytest.mark.parametrize(("module", "new", "old"), IDENTITY)
def test_facade_identity(module: str, new: str, old: str) -> None:
    import importlib

    mod = importlib.import_module(module)
    assert getattr(collision, old) is getattr(mod, new)


def test_package_reexports() -> None:
    import engine.output as out

    assert out.trace_outline is collision.trace_outline
    assert out.simplify_polygon is collision.simplify_polygon
    assert out.item_outline is collision.item_outline
    assert out.item_full is collision.item_full
    assert out.hazard_dict is collision._hazard_dict
    assert out.hazard_json is collision._hazard_json
    assert out.lane_polygon is collision._lane_polygon
    assert out.region_rows is collision._region_rows
    for name in ("trace_outline", "simplify_polygon", "item_outline", "item_full", "hazard_dict", "hazard_json",
                 "lane_polygon", "region_rows"):  # fmt: skip
        assert name in out.__all__


def test_constants() -> None:
    from engine.output import outline

    assert outline.OUTLINE_EPS_PX == 0.75
    assert outline.OUTLINE_MAX_POINTS == 32
    assert outline.DIRS == ((1, 0), (0, 1), (-1, 0), (0, -1))


@pytest.mark.parametrize("name", ["square", "L", "ring", "single"])
def test_trace_outline(name: str) -> None:
    from engine.output.outline import trace_outline

    assert trace_outline(_masks()[name]) == TRACE[name]


def test_trace_outline_disc() -> None:
    from engine.output.outline import trace_outline

    t = trace_outline(_masks()["disc"])
    assert len(t) == 100
    assert t[:3] == [(22, 2), (23, 2), (23, 3)]
    assert t[-3:] == [(16, 4), (16, 3), (22, 3)]


@pytest.mark.parametrize("name", ["square", "L", "ring", "single"])
def test_simplify_polygon(name: str) -> None:
    from engine.output.outline import simplify_polygon, trace_outline

    pts = [(float(x), float(y)) for x, y in trace_outline(_masks()[name])]
    assert simplify_polygon(pts) == SIMP[name]


@pytest.mark.parametrize("name", ["square", "L", "ring", "single", "disc"])
def test_simplify_polygon_raised_eps_and_cap(name: str) -> None:
    from engine.output.outline import simplify_polygon, trace_outline

    pts = [(float(x), float(y)) for x, y in trace_outline(_masks()[name])]
    assert simplify_polygon(pts, 3.0, 6) == SIMP_EPS3_6[name]


def test_simplify_polygon_disc_default() -> None:
    from engine.output.outline import simplify_polygon, trace_outline

    pts = [(float(x), float(y)) for x, y in trace_outline(_masks()["disc"])]
    out = simplify_polygon(pts)
    assert len(out) == 24
    assert out == DISC_SIMP


def test_dp_open() -> None:
    from engine.output.outline import dp_open

    pts = np.array([(0, 0), (1, 0.2), (2, -0.1), (3, 5), (4, 6), (5, 6.1), (6, 6)], float)
    assert dp_open(pts, 0.75) == [0, 2, 3, 6]
    assert dp_open(pts, 10.0) == [0, 6]
    assert dp_open(pts[:2], 0.1) == [0, 1]


def test_item_outline_and_full() -> None:
    from engine.output.outline import item_full, item_outline

    items = _items()
    assert item_outline(items["minimal"], 20, 30) is None
    assert item_full(items["minimal"], 20, 30) is None
    assert item_outline(items["static"], 20, 30) == [
        [0.1667, 0.3], [0.2333, 0.3], [0.2333, 0.4], [0.3, 0.4], [0.3, 0.5], [0.1667, 0.5],
    ]  # fmt: skip
    assert item_full(items["static"], 20, 30) is None
    assert item_outline(items["fr"], 20, 30) == [[0.1, 0.1], [0.2, 0.1], [0.2, 0.25], [0.1, 0.25]]
    assert item_full(items["fr"], 20, 30) == (
        [0.0667, 0.05, 0.3333, 0.4],
        [[0.1, 0.1], [0.2667, 0.1], [0.2667, 0.3], [0.1, 0.3]],
    )


def test_hazard_dict_minimal() -> None:
    from engine.output.hazards import hazard_dict

    d = hazard_dict(_items()["minimal"])
    assert list(d.keys()) == BASE_KEYS
    assert d == {
        "trackId": 0, "className": "wall", "group": "static", "label": "", "role": "none", "moving": False,
        "bbox": [0.1235, 0.2, 0.5, 0.6], "contactY": 0.6123, "bearingDeg": -3.46, "clock": 11, "clockText": "11",
        "pan": -0.1235, "distanceM": 7.46, "lateralM": -0.12, "stepsTo": 0.0, "closingMps": None, "urgency": "none",
        "areaFrac": 0.01235, "collision": False, "latVelMps": None, "crossMps": None,
    }  # fmt: skip


def test_hazard_dict_full() -> None:
    from engine.output.hazards import hazard_dict

    d = hazard_dict(_items()["full"])
    assert list(d.keys()) == FULL_KEYS
    assert d == {
        "trackId": 7, "className": "person", "group": "moving", "label": "person", "role": "danger", "moving": True,
        "bbox": [0.1235, 0.2, 0.5, 0.6], "contactY": 0.6123, "bearingDeg": -3.46, "clock": 11, "clockText": "11:45",
        "pan": -0.1235, "distanceM": 7.46, "lateralM": -0.12, "stepsTo": 10.0, "closingMps": 1.23, "urgency": "danger",
        "areaFrac": 0.01235, "collision": True, "latVelMps": 0.46, "crossMps": -0.79, "depthM": 7.8, "lanePart": True,
        "source": "depth", "imageDistanceM": 8.12, "imageLateralM": 0.57, "ghost": True, "coasting": True,
        "insideSolid": True, "solidCorrected": True, "rawDistanceM": 9.88, "faceEdge": {"a": 1}, "ownMps": [1.0, 2.0],
        "fromSide": "left", "nearPass": True, "distanceSource": "fused", "rawDepthM": 7.78, "groundM": 7.12,
    }  # fmt: skip


def test_hazard_dict_static_map() -> None:
    from engine.output.hazards import hazard_dict

    d = hazard_dict(_items()["static"])
    assert list(d.keys()) == [*BASE_KEYS, "source", "mapCells"]
    assert d["trackId"] == 3
    assert d["label"] == "wall"
    assert d["role"] == "danger"
    assert d["source"] == "map"
    assert d["mapCells"] == 12


def test_hazard_json() -> None:
    from engine.output.hazards import hazard_json

    items = _items()
    for name, keys in (("minimal", BASE_KEYS), ("full", FULL_KEYS)):
        for gh, gw, fa in ((0, 0, False), (20, 30, False), (20, 30, True)):
            j = hazard_json(items[name], gh, gw, fa)
            assert list(j.keys()) == keys
    # default arguments
    assert list(hazard_json(items["static"]).keys()) == [*BASE_KEYS, "source", "mapCells"]
    assert list(hazard_json(items["static"], 0, 0, True).keys()) == [*BASE_KEYS, "source", "mapCells"]
    # a role with a shape: the outline is added; no full_ref: no bboxFull
    for fa in (False, True):
        j = hazard_json(items["static"], 20, 30, fa)
        assert list(j.keys()) == [*BASE_KEYS, "source", "mapCells", "outline"]
        assert j["outline"] == [[0.1667, 0.3], [0.2333, 0.3], [0.2333, 0.4], [0.3, 0.4], [0.3, 0.5], [0.1667, 0.5]]
    # no role: nothing unless full_all
    assert list(hazard_json(items["fr"], 20, 30, False).keys()) == BASE_KEYS
    assert list(hazard_json(items["fr"], 0, 0, True).keys()) == BASE_KEYS
    j = hazard_json(items["fr"], 20, 30, True)
    assert list(j.keys()) == [*BASE_KEYS, "bboxFull", "outlineFull"]
    assert j["bboxFull"] == [0.0667, 0.05, 0.3333, 0.4]
    assert j["outlineFull"] == [[0.1, 0.1], [0.2667, 0.1], [0.2667, 0.3], [0.1, 0.3]]
    assert "outline" not in j


def _geo(offset: float) -> Any:
    f = collision.focal_px(240, 118.0)
    return collision._frame_geometry(135, 240, 0.45, 1.3, f, 118.0, 0.6, None, 0, "rectilinear", offset)


def test_lane_polygon() -> None:
    from engine.output.hazards import lane_polygon

    geo = _geo(0.0)
    assert lane_polygon(geo, 0.6, 15.0) == [[0.3572, 1.0], [0.6428, 1.0], [0.512, 0.4963], [0.488, 0.4963]]
    assert lane_polygon(geo, 0.9, 3.0) == [[0.2858, 1.0], [0.7142, 1.0], [0.5901, 0.6814], [0.4099, 0.6814]]
    assert lane_polygon(geo, 0.6, 500.0) == [[0.3572, 1.0], [0.6428, 1.0], [0.5004, 0.4514], [0.4996, 0.4514]]
    assert lane_polygon(_geo(0.25), 0.6, 15.0) == [[0.2977, 1.0], [0.5833, 1.0], [0.507, 0.4963], [0.483, 0.4963]]


def test_region_rows() -> None:
    from engine.core.types import Region
    from engine.output.hazards import region_rows

    left = np.array([np.nan, 0.1, 0.2234, 0.3, 0.4, np.nan, 0.25, 0.31, 0.33, 0.4])
    reg = Region("g", "road", np.zeros((10, 10), bool), left, left + 0.31234)
    assert region_rows(reg) == [[0.95, 0.4, 0.712], [0.15, 0.1, 0.412]]
    assert region_rows(reg, 1) == [
        [0.95, 0.4, 0.712], [0.85, 0.33, 0.642], [0.75, 0.31, 0.622], [0.65, 0.25, 0.562],
        [0.45, 0.4, 0.712], [0.35, 0.3, 0.612], [0.25, 0.223, 0.536], [0.15, 0.1, 0.412],
    ]  # fmt: skip
    assert region_rows(reg, 3) == [[0.95, 0.4, 0.712], [0.65, 0.25, 0.562], [0.35, 0.3, 0.612]]
    assert region_rows(None) == []
