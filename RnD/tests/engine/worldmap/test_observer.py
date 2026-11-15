"""Characterisation tests for engine.worldmap.observer.Observer (v26.3.0 p3-02).

The expected literals were produced by running the legacy ``worldmap.Observer`` on today's code (hackeye-rnd image)
through the same scenario functions, with the map settings pytest uses (the conftest's v26.2.9 overrides).
The engine module is imported inside each test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

import groundfuse
import worldmap

if TYPE_CHECKING:
    from numpy.typing import NDArray

NAMES = ["flat sidewalk", "building", "pole", "person", "nature sky"]
SW, BLD, POLE, PERSON, SKY = range(5)
GH, GW, HFOV, CAM_H, HORIZON = 135, 240, 118.0, 1.28, 0.45
REL = 1e-12


def _settings() -> dict[str, Any]:
    return {
        "hfovDeg": HFOV,
        "cameraHeightM": CAM_H,
        "lateralOffsetM": 0.0,
        "projection": "fisheye",
        "distanceSource": "depth",
        "objectDistance": "depth",
    }


def _make(**over: Any) -> Any:
    cfg = {**worldmap.load_config(), **over}
    kind = worldmap.class_kinds(cfg, NAMES)
    return worldmap.Observer(cfg, _settings(), kind, GH, GW, None, NAMES)


def _scene(wall_m: float = 8.0) -> tuple[NDArray[Any], NDArray[Any], dict[str, Any]]:
    """Sidewalk up to a facade, plus a pole and a person standing on the sidewalk (lens-rendered, perfect z-depth)."""
    geo = groundfuse.Geometry(GH, GW, HFOV, "fisheye", CAM_H)
    rows, cols = np.mgrid[0:GH, 0:GW]
    fwd, _ = groundfuse.ground_point(geo, rows + 0.5, cols + 0.5, HORIZON)
    z = groundfuse.ground_z(geo, rows + 0.5, cols + 0.5, HORIZON)
    grid = np.full((GH, GW), SKY, np.uint8)
    below = np.isfinite(fwd)
    grid[below & (fwd < wall_m)] = SW
    grid[below & (fwd >= wall_m)] = BLD
    depth = np.where(np.isfinite(z), z, 30.0).astype(np.float32)
    for c in range(GW):
        b = np.flatnonzero(grid[:, c] == BLD)
        if b.size:
            grid[20 : b.min(), c] = BLD
            depth[20 : b.max() + 1, c] = float(z[b.max(), c])
    for cols_, cls, top, base in ((range(40, 44), POLE, 50, 100), (range(170, 180), PERSON, 60, 104)):
        for c in cols_:
            grid[top : base + 1, c] = cls
            depth[top : base + 1, c] = float(z[base, c])
    frame = {"horizon": HORIZON, "scale": 1.0, "depthScale": 1.0, "ego": {}, "dcorr": None}
    return grid, depth, frame


def _arr(a: NDArray[Any]) -> dict[str, Any]:
    return {"shape": tuple(a.shape), "dtype": str(a.dtype)}


def _digest(ob: Any) -> dict[str, Any]:
    grid, depth, frame = _scene()
    obs, w = ob.observe(grid, frame, depth)
    counts = {int(k): int(v) for k, v in enumerate(np.bincount(obs.ravel(), minlength=256)) if v}
    rr, cc, dist, lat = ob.object_bases(grid, frame, depth)
    v, g = ob.face_contact_samples(grid, depth, 1.0, HORIZON)
    return {
        "obs": _arr(obs),
        "w": _arr(w),
        "counts": counts,
        "w_sum": float(w.sum(dtype=np.float64)),
        "w_nonzero": int(np.count_nonzero(w)),
        "seen": int(ob.seen.sum()),
        "bases_n": int(rr.size),
        "bases_first": (int(rr[0]), int(cc[0]), float(dist[0]), float(lat[0])),
        "bases_last": (int(rr[-1]), int(cc[-1]), float(dist[-1]), float(lat[-1])),
        "dist_sum": float(dist.sum(dtype=np.float64)),
        "lat_sum": float(lat.sum(dtype=np.float64)),
        "contact_n": int(v.size),
        "contact_first": (float(v[0]), float(g[0])) if v.size else None,
        "contact_last": (float(v[-1]), float(g[-1])) if v.size else None,
    }


def _check(got: dict[str, Any], want: dict[str, Any]) -> None:
    assert got.keys() == want.keys()
    for k, wv in want.items():
        gv = got[k]
        if isinstance(wv, float) or (isinstance(wv, tuple) and any(isinstance(x, float) for x in wv)):
            assert gv == pytest.approx(wv, rel=REL, abs=REL), k
        else:
            assert gv == wv, k


ATTRS_AFTER_INIT: list[str] = [
    "cam_h",
    "cell",
    "cell_bin",
    "cell_range",
    "cfg",
    "depth_rows",
    "depth_source",
    "f_px",
    "face_ground",
    "face_lut",
    "face_scale_occ",
    "face_thick_m",
    "fisheye",
    "fwd",
    "gap_k",
    "gap_tab",
    "gd",
    "geo",
    "geometry",
    "gh",
    "gw",
    "hfov",
    "hid_bin_deg",
    "hid_nb",
    "hidden_factor",
    "join_cols",
    "join_frac",
    "kind",
    "lat_off",
    "lens",
    "max_range",
    "min_fwd",
    "object_mode",
    "oc",
    "occ_lut",
    "orow",
    "outlier_frac",
    "range_w",
    "ratio_clamp",
    "ratio_min",
    "ray_hidden",
    "right",
    "size",
    "sky_id",
    "smooth_cols",
    "thick_m",
    "use_horizon",
    "weight",
]

GEOMETRY_DIGEST: dict[str, Any] = {
    "obs": {"shape": (200, 200), "dtype": "uint8"},
    "w": {"shape": (200, 200), "dtype": "float32"},
    "counts": {0: 9308, 1: 775, 2: 3, 255: 29914},
    "w_sum": 7296.043032795191,
    "w_nonzero": 10086,
    "seen": 10086,
    "bases_n": 244,
    "bases_first": (49, 40, 8.16793681700556, -6.640724844906912),
    "bases_last": (100, 43, 3.19059157371521, -2.6030914553895577),
    "dist_sum": 1936.642524310183,
    "lat_sum": -10.8681583285816,
    "contact_n": 226,
    "contact_first": (8.285069465637207, 7.929149737229531),
    "contact_last": (8.072607040405273, 7.844641263420814),
}

COLLISION_DIGEST: dict[str, Any] = {
    "obs": {"shape": (200, 200), "dtype": "uint8"},
    "w": {"shape": (200, 200), "dtype": "float32"},
    "counts": {0: 4430, 1: 750, 2: 2, 255: 34818},
    "w_sum": 4301.873222947121,
    "w_nonzero": 5182,
    "seen": 5182,
    "bases_n": 244,
    "bases_first": (49, 40, 8.511061668395996, -9.38417026637207),
    "bases_last": (100, 43, 3.19059157371521, -3.3851480090928554),
    "dist_sum": 2014.6979112625122,
    "lat_sum": -13.716751167408447,
    "contact_n": 226,
    "contact_first": (8.285069465637207, 7.929149737229531),
    "contact_last": (8.072607040405273, 7.844641263420814),
}


def test_observer_is_the_legacy_object() -> None:
    from engine.worldmap import observer

    assert worldmap.Observer is observer.Observer


def test_attributes_after_init() -> None:
    ob = _make()
    assert sorted(vars(ob)) == ATTRS_AFTER_INIT
    assert ob.geo.__class__ is groundfuse.Geometry
    assert (ob.gh, ob.gw, ob.size, ob.cell) == (135, 240, 200, 0.1)


def test_observe_objects_and_face_samples_on_the_lens_geometry() -> None:
    from engine.worldmap import observer

    base = worldmap.load_config()
    cfg = {**base, "lateralModel": "geometry"}
    ob = observer.Observer(cfg, _settings(), worldmap.class_kinds(base, NAMES), GH, GW, None, NAMES)
    assert ob.geometry
    _check(_digest(ob), GEOMETRY_DIGEST)


def test_observe_objects_and_face_samples_on_the_pinhole_formulas() -> None:
    from engine.worldmap import observer

    cfg = {**worldmap.load_config(), "lateralModel": "collision", "faceGroundContact": False}
    ob = observer.Observer(cfg, _settings(), worldmap.class_kinds(cfg, NAMES), GH, GW, None, NAMES)
    assert not ob.geometry
    _check(_digest(ob), COLLISION_DIGEST)


def test_face_contact_samples_guards() -> None:
    from engine.worldmap import observer

    cfg = worldmap.load_config()
    ob = observer.Observer(cfg, _settings(), worldmap.class_kinds(cfg, NAMES), GH, GW, None, NAMES)
    grid, depth, _ = _scene()
    assert ob.face_contact_samples(grid, None, 1.0, HORIZON)[0].size == 0
    assert ob.face_contact_samples(grid, depth, None, HORIZON)[0].size == 0
    direct = ob.face_contact_samples(grid, depth, 1.0, HORIZON)[0].size
    assert worldmap.face_contact_samples(ob, grid, depth, 1.0, HORIZON)[0].size == direct
