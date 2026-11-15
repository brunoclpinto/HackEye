"""Characterisation tests for engine.pipeline.glue (v26.3.0 p4-01): the helpers moved out of ``collision``.

Every literal below was printed by the legacy ``collision`` functions (``_bottom_distance``, ``_hidden_fn``,
``_predict_velocities``) in the hackeye-rnd image before the move, fed the inputs built by the helpers of this file.
The engine module is imported inside each test (it does not exist yet).
"""

from __future__ import annotations

import types
from typing import Any

import numpy as np
import pytest

import collision

GH = 40
GW = 64
HFOV_DEG = 118.0
CAM_H = 1.4


def _focal() -> float:
    from engine.core.geom import focal_px

    return focal_px(GW, HFOV_DEG)


def _observer(geo: Any, geometry: bool = True, cam_h: float = CAM_H) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        geometry=geometry, geo=geo, gh=GH, gw=GW, cam_h=cam_h, ray_hidden=None, orow=0, oc=0, cell=0.5
    )


def test_glue_names_are_the_legacy_objects() -> None:
    from engine.pipeline import glue

    assert collision._bottom_distance is glue.bottom_distance
    assert collision._hidden_fn is glue.hidden_fn
    assert collision._predict_velocities is glue.predict_velocities
    assert collision.LAST_WORLD_TRACKS_MS is glue.LAST_WORLD_TRACKS_MS


def test_bottom_distance_fisheye_geometry() -> None:
    from engine.core.groundgeom import Geometry
    from engine.pipeline.glue import bottom_distance

    geo = Geometry(GH, GW, HFOV_DEG, "fisheye", CAM_H)
    f = _focal()
    # the ground under the bottom row, through the lens; the camera height of the observer is used (not the argument)
    assert bottom_distance(_observer(geo), 0.40, 1.6, GH, f) == pytest.approx(1.437140199684077, rel=1e-12, abs=1e-12)
    assert bottom_distance(_observer(geo), 0.45, 1.6, GH, f) == pytest.approx(1.635573275886913, rel=1e-12, abs=1e-12)
    assert bottom_distance(_observer(geo), 0.50, 1.6, GH, f) == pytest.approx(1.866320391027446, rel=1e-12, abs=1e-12)


def test_bottom_distance_rectilinear_geometry() -> None:
    from engine.core.groundgeom import Geometry
    from engine.pipeline.glue import bottom_distance

    geo = Geometry(GH, GW, 70.0, "rectilinear", CAM_H)
    got = bottom_distance(_observer(geo), 0.50, 1.6, GH, _focal())
    assert got == pytest.approx(3.1990515351023365, rel=1e-12, abs=1e-12)


def test_bottom_distance_flat_formula_without_geometry() -> None:
    from engine.core.groundgeom import Geometry
    from engine.pipeline.glue import bottom_distance

    geo = Geometry(GH, GW, HFOV_DEG, "fisheye", CAM_H)
    f = _focal()
    # no geometry flag, or no observer: cam_h * f / ((1 - horizon) * gh), the argument camera height
    assert bottom_distance(_observer(geo, geometry=False), 0.45, 1.6, GH, f) == pytest.approx(
        1.3983665315550495, rel=1e-12, abs=1e-12
    )
    assert bottom_distance(None, 0.45, 1.6, GH, f) == pytest.approx(1.3983665315550495, rel=1e-12, abs=1e-12)


def test_bottom_distance_errors_and_non_finite_return_zero() -> None:
    from engine.pipeline.glue import bottom_distance

    f = _focal()
    # a geometry observer without a lens raises inside the try: 0.0
    assert bottom_distance(_observer(None), 0.45, 1.6, GH, f) == 0.0
    # the horizon at 1.5 puts the bottom row above the horizon: not finite, 0.0
    from engine.core.groundgeom import Geometry

    geo = Geometry(GH, GW, HFOV_DEG, "fisheye", CAM_H)
    assert bottom_distance(_observer(geo), 1.5, 1.6, GH, f) == 0.0


def _hidden_observer() -> types.SimpleNamespace:
    rh = np.zeros((12, 16), dtype=bool)
    rh[5, 7] = True
    rh[3, 4] = True
    rh[10, 15] = True
    return types.SimpleNamespace(ray_hidden=rh, orow=8, oc=6, cell=0.5)


def test_hidden_fn_reads_the_map_cell_of_a_point() -> None:
    from engine.pipeline.glue import hidden_fn

    hidden = hidden_fn(_hidden_observer())
    assert hidden is not None
    cases: list[tuple[tuple[float, float], bool]] = [
        ((0.0, 0.0), False),
        ((1.5, 0.5), True),
        ((1.5, -0.5), False),
        ((1.0, 0.5), False),
        ((-5.0, 0.0), False),
        ((0.0, 5.0), False),
        ((8.0, 0.0), False),
        ((6.0, 0.0), False),
        ((1.0, 0.0), False),
    ]
    for (fwd, right), expected in cases:
        assert hidden(fwd, right) is expected, (fwd, right)


def test_hidden_fn_none_without_a_map() -> None:
    from engine.pipeline.glue import hidden_fn

    assert hidden_fn(None) is None
    assert hidden_fn(types.SimpleNamespace(ray_hidden=None)) is None


class _WorldTracks:
    """Stub of the world-track store: ``lookup(track_id, t)`` returns the entry or None."""

    def __init__(self, table: dict[int, dict[str, Any]]) -> None:
        self._table = table

    def lookup(self, tid: int, t: float) -> dict[str, Any] | None:
        return self._table.get(tid)


def _item(group: str, track_id: int) -> Any:
    from engine.core.types import Item

    return Item(
        group=group,
        class_name="person",
        bbox=[0.4, 0.4, 0.5, 0.9],
        contact_y=0.9,
        distance_m=5.0,
        lateral_m=0.5,
        bearing=10.0,
        clock=12,
        pan=0.0,
        area_frac=0.01,
        clipped=False,
        touches=False,
        lane_hit=True,
        along_path=False,
        lane_cover=0.5,
        track_id=track_id,
    )


def test_predict_velocities_sets_pred_v_only_for_trusted_moving_tracks() -> None:
    from engine.pipeline.glue import predict_velocities

    wt = _WorldTracks(
        {
            7: {"trusted": True, "static": False, "vx": 1.0, "vy": -2.0},
            8: {"trusted": False, "static": False, "vx": 0.5, "vy": 0.5},
            10: {"trusted": True, "static": False, "vx": 0.3, "vy": 0.3},
        }
    )
    items = [_item("moving", 7), _item("moving", 8), _item("moving", 9), _item("static", 10)]
    predict_velocities(items, wt, 3.0, 0.2, {"maxMoverMps": 12.0})
    # 7: trusted mover, rotated into our frame (theta 0.2 rad)
    assert items[0].pred_v == pytest.approx((-1.761463824887422, 1.377405239431364), rel=1e-12, abs=1e-12)
    # 8: untrusted track, 9: no track entry, 10: not a mover (group static, no lookup)
    assert items[1].pred_v is None
    assert items[2].pred_v is None
    assert items[3].pred_v is None
