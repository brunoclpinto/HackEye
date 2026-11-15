"""Characterisation tests for engine.worldmap.map (v26.3.0 p3-04): ``WorldMap`` and ``build``.

The expected literals were produced by running the legacy ``worldmap.WorldMap`` / ``worldmap.build`` on today's code
(hackeye-rnd image) through the same scenario; the engine module is imported inside each test (it does not exist yet).
``ms`` (timing) is never pinned.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

import collision
import worldmap

if TYPE_CHECKING:
    from numpy.typing import NDArray

NAMES = ["flat sidewalk", "building", "pole", "person", "nature sky"]
SW, BLD, POLE, PERSON, SKY = range(5)
GH, GW, HFOV, CAM_H, HORIZON = 135, 240, 118.0, 1.3, 0.45
FPS = 6.0
N_FRAMES = 4


def _render(x: float, y: float) -> NDArray[Any]:
    f = collision.focal_px(GW, HFOV)
    grid = np.full((GH, GW), SKY, dtype=np.uint8)
    rows, cols = np.mgrid[0:GH, 0:GW]
    yb = (rows + 1.0) / GH
    below = yb > HORIZON + 1e-9
    d = np.where(below, CAM_H * f / (np.maximum(yb - HORIZON, 1e-9) * GH), 1.0)
    lat = (((cols + 0.5) / GW) - 0.5) * GW * d / f
    wx = x + lat
    wy = y + d
    cls = np.full(wx.shape, SW, dtype=np.uint8)
    cls[(np.abs(wx - 2.5) <= 0.15) & (wy >= 0)] = BLD
    cls[(np.abs(wy - 9.0) <= 0.15) & (wx >= -0.5) & (wx <= 2.5)] = BLD
    grid[below] = cls[below]
    for c in range(GW):
        col = grid[:, c]
        objs = np.flatnonzero(np.isin(col, (BLD, POLE)))
        if objs.size:
            lowest = objs.max()
            col[:lowest] = col[lowest]
    return grid


def _scene() -> tuple[NDArray[Any], NDArray[Any], dict[str, Any]]:
    times = np.arange(N_FRAMES) / FPS
    grids = np.stack([_render(0.0, 1.2 * float(t)) for t in times])
    ego = {"speedMps": 1.2, "headingDeg": 0.0, "stationary": False}
    doc: dict[str, Any] = {
        "frames": [{"horizonY": HORIZON, "ego": dict(ego)} for _ in times],
        "settings": {"hfovDeg": HFOV, "cameraHeightM": CAM_H, "lateralOffsetM": 0.0},
        "projection": "rectilinear",
        "distanceSource": "ground",
    }
    return grids, times, doc


def _digest(a: NDArray[Any]) -> list[Any]:
    arr = np.asarray(a)
    f = arr.astype(float)
    return [str(arr.dtype), list(arr.shape), float(np.nansum(f)), float(np.nansum(f**2))]


def test_facade_identity() -> None:
    from engine.worldmap import map as wmap

    assert worldmap.WorldMap is wmap.WorldMap
    assert worldmap.build is wmap.build


def test_cfg_none_uses_the_patched_load_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.worldmap import map as wmap

    real = worldmap.load_config()
    monkeypatch.setattr(worldmap, "load_config", lambda path=None: {**real, "marker": 1})
    grids, times, doc = _scene()
    frames = worldmap.frames_from_hazards(doc)
    settings = worldmap.settings_from_hazards(doc)
    coll_cfg = collision.load_config()
    wm = worldmap.WorldMap(grids, times, NAMES, frames, settings, coll_cfg, None)
    assert wm.cfg["marker"] == 1
    wm2 = wmap.WorldMap(grids, times, NAMES, frames, settings, coll_cfg, None)
    assert wm2.cfg["marker"] == 1


def test_build_keys_and_digests() -> None:
    from engine.worldmap import map as wmap

    grids, times, doc = _scene()
    seen: list[int] = []

    def hook(i: int, _wm: Any, _obs: Any, _cl: Any) -> None:
        seen.append(i)

    out = wmap.build(grids, times, NAMES, doc, collision.load_config(), worldmap.load_config(), None, hook)
    assert seen == list(range(N_FRAMES))
    assert sorted(out) == KEYS
    got = {k: _digest(out[k]) for k in KEYS if k != "ms"}
    assert got == pytest.approx(DIGESTS, rel=1e-12, abs=1e-12)
    assert out["ms"].shape == (N_FRAMES,)
    assert float(out["cellM"]) == pytest.approx(CELL_M, rel=1e-12, abs=1e-12)
    assert out["origin"].tolist() == ORIGIN


def test_build_frame_count_mismatch() -> None:
    from engine.worldmap import map as wmap

    grids, times, doc = _scene()
    with pytest.raises(ValueError, match=r"hazards\.json has 4 frames, grids\.npz 3"):
        wmap.build(grids[:3], times[:3], NAMES, doc, collision.load_config(), worldmap.load_config())


def test_build_equals_legacy_facade_arrays() -> None:
    from engine.worldmap import map as wmap

    grids, times, doc = _scene()
    a = wmap.build(grids, times, NAMES, doc, collision.load_config(), worldmap.load_config())
    b = worldmap.build(grids, times, NAMES, doc, collision.load_config(), worldmap.load_config())
    for k in KEYS:
        if k != "ms":
            assert np.array_equal(a[k], b[k], equal_nan=True), k


def test_step_shape_and_attrs() -> None:
    from engine.worldmap import map as wmap

    grids, times, doc = _scene()
    frames = worldmap.frames_from_hazards(doc)
    settings = worldmap.settings_from_hazards(doc)
    wm = wmap.WorldMap(grids, times, NAMES, frames, settings, collision.load_config(), worldmap.load_config())
    assert (wm.n, wm.gh, wm.gw) == (N_FRAMES, GH, GW)
    assert sorted(vars(wm)) == ATTRS
    _obs, classes, conf, ms = wm.step(0)
    assert _digest(classes) == STEP_CLASSES
    assert _digest(conf) == STEP_CONF
    assert isinstance(ms, float) and not math.isnan(ms)


KEYS: list[str] = [
    "agree",
    "agreePrior",
    "alignDeg",
    "alignM",
    "cellM",
    "classes",
    "conf",
    "ms",
    "object",
    "origin",
    "pose",
    "surface",
    "t",
]
DIGESTS: dict[str, list[Any]] = {
    "agree": ["float64", [4], 3.520889703855851, 3.1554068873758996],
    "agreePrior": ["float64", [4], 2.0, 2.0],
    "alignDeg": ["float64", [4], 0.0, 0.0],
    "alignM": ["float64", [4], 0.0, 0.0],
    "cellM": ["float32", [], 0.10000000149011612, 0.010000000298023226],
    "classes": ["uint8", [4, 200, 200], 22223003.0, 5666410343.0],
    "conf": ["uint8", [4, 200, 200], 6619498.0, 886149588.0],
    "object": ["uint8", [4, 200, 200], 40344578.0, 10287411968.0],
    "origin": ["int32", [2], 300.0, 50000.0],
    "pose": ["float64", [4, 3], 1.2, 0.5599999999999999],
    "surface": ["uint8", [4, 200, 200], 22566735.0, 5754517425.0],
    "t": ["float64", [4], 1.0, 0.3888888888888889],
}
CELL_M = 0.10000000149011612
ORIGIN: list[int] = [100, 200]
ATTRS: list[str] = [
    "agree",
    "agree_prior",
    "align_deg",
    "align_m",
    "align_on",
    "align_th",
    "cfg",
    "depth",
    "depth_t",
    "first_ds",
    "frames",
    "fusion",
    "gh",
    "grids",
    "gw",
    "kind",
    "last_ds",
    "n",
    "observer",
    "pos_c",
    "pose",
    "pose_tracker",
    "props",
    "raw_prev",
    "times",
]
STEP_CLASSES: list[Any] = ["uint8", [200, 200], 6976638.0, 1778954298.0]
STEP_CONF: list[Any] = ["uint8", [200, 200], 595531.0, 33203869.0]
