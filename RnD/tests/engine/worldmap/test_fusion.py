"""Characterisation tests for engine.worldmap.fusion.Fusion (v26.3.0 p3-03).

The expected literals were printed by running the legacy ``worldmap.Fusion`` on today's code (hackeye-rnd image) through
the same scenario functions (``_scenario_none``, ``_scenario_time_align``, ``_gap_digest``, ``_recentre_digest``). The
scenario cfg sets every fusion key the conftest overrides explicitly, so the literals do not depend on it. The engine
module is imported inside each test.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

import collision
import worldmap

NAMES = ["flat sidewalk", "building", "pole", "person", "nature sky", "flat road"]
SW, BLD, POLE, PERSON, SKY, ROAD = range(6)
GH, GW, HFOV, CAM_H, HORIZON = 135, 240, 118.0, 1.3, 0.45
FPS = 6.0
N_FRAMES = 10
_Pose = tuple[float, float, float]
SETTINGS: dict[str, Any] = {
    "hfovDeg": HFOV,
    "cameraHeightM": CAM_H,
    "lateralOffsetM": 0.0,
    "projection": "rectilinear",
    "distanceSource": "ground",
}

ATTRS_AFTER_INIT = sorted(
    [
        "cfg",
        "cell",
        "n",
        "decay_mode",
        "lam",
        "conflict",
        "vote_cap",
        "confront",
        "floor",
        "full",
        "classes",
        "is_surface",
        "lut",
        "surf_layers",
        "obj_layers",
        "layer_pos",
        "votes",
        "count",
        "x0",
        "y0",
        "t_base",
    ]
)

FUSION_NONE = [
    [{0: 11366, 1: 352, 255: 28282}, 28282, 540314, 11366, 352, 17053, 7395.58642578125],
    [{0: 17682, 1: 497, 255: 21821}, 21821, 1257091, 17795, 497, 36305, 15238.4716796875],
    [{0: 19235, 1: 427, 255: 20338}, 20338, 1931355, 19325, 427, 55545, 23115.49609375],
    [{0: 17340, 1: 558, 255: 22102}, 22102, 2390023, 17470, 558, 72495, 29751.37890625],
    [{0: 17472, 1: 536, 255: 21992}, 21992, 2813687, 17582, 569, 89449, 36909.35546875],
    [{0: 19097, 1: 551, 255: 20352}, 20352, 3178745, 19187, 638, 108693, 44653.2890625],
    [{0: 17776, 1: 615, 255: 21609}, 21609, 3377907, 17895, 627, 125296, 51204.05078125],
    [{0: 17766, 1: 607, 255: 21627}, 21627, 3596048, 17874, 633, 141879, 58245.859375],
    [{0: 19307, 1: 598, 255: 20095}, 20095, 3797857, 19448, 658, 161120, 65946.3828125],
    [{0: 18004, 1: 611, 255: 21385}, 21385, 3900244, 18101, 648, 177641, 72607.984375],
]
FUSION_TIME = [
    [
        [{0: 11366, 1: 348, 5: 928, 255: 27358}, 27358, 595531, 12294, 348, 18072, 8117.71142578125],
        [{0: 17518, 1: 516, 5: 1541, 255: 20425}, 20425, 1357125, 19251, 516, 39883, 17194.115234375],
        [{0: 19113, 1: 581, 5: 2376, 255: 17930}, 17930, 2071295, 21708, 584, 61697, 26490.470703125],
        [{0: 17468, 1: 707, 5: 980, 255: 20845}, 20845, 2492454, 18739, 713, 79707, 33812.1796875],
        [{0: 17628, 1: 689, 5: 962, 255: 20721}, 20721, 2901037, 18839, 811, 97721, 42136.77734375],
        [{0: 19048, 1: 636, 5: 1875, 255: 18441}, 18441, 3272195, 21156, 838, 119532, 51766.25390625],
        [{0: 17933, 1: 800, 5: 926, 255: 20341}, 20341, 3448386, 19151, 829, 137106, 59647.12109375],
        [{0: 18066, 1: 774, 5: 936, 255: 20224}, 20224, 3645314, 19282, 842, 154681, 68350.0859375],
        [{0: 19415, 1: 711, 5: 1849, 255: 18025}, 18025, 3862917, 21546, 870, 176492, 78474.640625],
        [{0: 18313, 1: 831, 5: 910, 255: 19946}, 19946, 3924959, 19493, 913, 193892, 86574.78125],
    ],
    [
        [0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0017453070996747868, 0.19999238461283425, 1.0],
        [0.0, 0.0, 0.0069806967612494174, 0.3999238496079457, 2.0],
        [-0.5, 0.0, 0.015704574234316617, 0.5997334939243173, 2.5],
        [-0.5, 0.0017453237138986243, 0.026171765482905382, 0.799459400875232, 3.5],
        [-1.0, 0.0034905145146391483, 0.04012306023173045, 0.998972210927197, 4.0],
        [-1.5, 0.006980713371737014, 0.05581487937729944, 1.1983556776738227, 4.5],
        [-2.0, 0.10043301604235748, 0.06714117397334539, 1.2977811374499852, 5.0],
        [-2.5, 0.2003251540434164, 0.07933467710297763, 1.3971039720974383, 5.5],
        [-3.0, 0.2504995718831145, 0.0963174149701161, 1.5461624844844364, 6.0],
    ],
]
GAP = [[158, 3128121, [1], 31600.0], [None]]
RECENTRE = [177641, 72607.984375, [-32.0, -32.0, 177641], -2.0, -52.0, 29722, 20700.849609375]
SURFACE_NONE = [{0: 218, 255: 207}, "|u1", 425]
SURFACE_TIME = [{0: 221, 5: 36, 255: 168}, "|u1", 425]


def _scene(wx: np.ndarray[Any, Any], wy: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    out = np.full(wx.shape, SW, dtype=np.uint8)
    out[(wx > 0.4) & (wx < 1.6)] = ROAD
    out[(np.abs(wx - 2.5) <= 0.15) & (wy >= 0)] = BLD
    out[(np.abs(wy - 9.0) <= 0.15) & (wx >= -0.5) & (wx <= 2.5)] = BLD
    return out


def _render(x: float, y: float, heading_deg: float) -> np.ndarray[Any, Any]:
    f = collision.focal_px(GW, HFOV)
    th = math.radians(heading_deg)
    grid = np.full((GH, GW), SKY, dtype=np.uint8)
    rows, cols = np.mgrid[0:GH, 0:GW]
    yb = (rows + 1.0) / GH
    below = yb > HORIZON + 1e-9
    d = np.where(below, CAM_H * f / (np.maximum(yb - HORIZON, 1e-9) * GH), 1.0)
    lat = (((cols + 0.5) / GW) - 0.5) * GW * d / f
    wx = x + math.sin(th) * d + math.cos(th) * lat
    wy = y + math.cos(th) * d - math.sin(th) * lat
    cls = _scene(wx, wy)
    grid[below] = cls[below]
    for c in range(GW):
        col = grid[:, c]
        objs = np.flatnonzero(np.isin(col, (BLD, POLE)))
        if objs.size:
            lowest = objs.max()
            col[:lowest] = col[lowest]
    return grid


def _grids() -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    times = np.arange(N_FRAMES) / FPS
    return np.stack([_render(0.0, 1.2 * float(t), 0.0) for t in times]), times


def _frame(i: int = 0, drift: float = 0.0) -> dict[str, Any]:
    ego = {"speedMps": 1.2, "headingDeg": drift * i, "stationary": False}
    return {"horizon": HORIZON, "scale": 1.0, "depthScale": None, "ego": ego}


def _cfg(**over: Any) -> dict[str, Any]:
    base = {
        **worldmap.load_config(),
        "decay": "time",
        "conflictFactor": 1.0,
        "voteCap": 0.0,
        "poseAlign": False,
        "gapCloseM": 0.5,
        "faceThicknessM": 0.3,
    }
    return {**base, **over}


def _digest(fu: Any, ob: Any, t: float, pose: _Pose) -> list[Any]:
    classes, conf, surf, objs = fu.snapshot(t, pose, ob, True)
    u, c = np.unique(classes, return_counts=True)
    return [
        {int(k): int(v) for k, v in zip(u, c, strict=True)},
        int((classes == worldmap.UNKNOWN).sum()),
        int(conf.astype(np.int64).sum()),
        int((surf != worldmap.UNKNOWN).sum()),
        int((objs != worldmap.UNKNOWN).sum()),
        int(fu.count.astype(np.int64).sum()),
        float(fu.votes.sum()),
    ]


def _scenario_none(cls: Any) -> tuple[list[list[Any]], Any, Any, _Pose, float]:
    cfg = _cfg(decay="none")
    kind = worldmap.class_kinds(cfg, NAMES)
    ob = worldmap.Observer(cfg, SETTINGS, kind, GH, GW, None, NAMES)
    grids, times = _grids()
    fu = cls(cfg, kind, np.array([SW, BLD]), (0.0, 0.0))
    out: list[list[Any]] = []
    pose = (0.0, 0.0, 0.0)
    t = 0.0
    for i in range(N_FRAMES):
        t = float(times[i])
        pose = (0.0, 1.2 * t, 0.0)
        obs, w = ob.observe(grids[i], _frame(), None)
        fu.update(t, pose, obs, w, ob)
        out.append(_digest(fu, ob, t, pose))
    return out, fu, ob, pose, t


def _scenario_time_align(cls: Any) -> tuple[list[list[Any]], list[list[float]], Any, Any, _Pose, float]:
    cfg = _cfg(decay="time", poseAlign=True)
    grids, times = _grids()
    frames = [_frame(i, 1.0) for i in range(N_FRAMES)]
    wm = worldmap.WorldMap(grids, times, NAMES, frames, SETTINGS, collision.load_config(), cfg)
    present = np.flatnonzero(np.bincount(np.asarray(wm.grids).ravel(), minlength=256))
    wm.fusion = cls(wm.cfg, wm.kind, present, (0.0, 0.0))
    out: list[list[Any]] = []
    offs: list[list[float]] = []
    for i in range(N_FRAMES):
        wm.step(i)
        pose = (float(wm.pose[i][0]), float(wm.pose[i][1]), float(wm.pose[i][2]))
        out.append(_digest(wm.fusion, wm.observer, float(wm.times[i]), pose))
        offs.append([float(wm.align_deg[i]), float(wm.align_m[i]), pose[0], pose[1], pose[2]])
    return out, offs, wm.fusion, wm.observer, pose, float(wm.times[-1])


def _surface_digest(fu: Any, pose: _Pose, t: float) -> list[Any]:
    fwd, right = np.meshgrid(np.linspace(0.0, 12.0, 25), np.linspace(-4.0, 4.0, 17))
    cls = fu.surface_at(pose, fwd.ravel(), right.ravel(), t, 1.0)
    u, c = np.unique(cls, return_counts=True)
    return [{int(k): int(v) for k, v in zip(u, c, strict=True)}, cls.dtype.str, cls.shape[0]]


def _gap_digest(cls: Any, fu: Any, ob: Any) -> list[Any]:
    classes = np.full((ob.size, ob.size), worldmap.UNKNOWN, np.uint8)
    conf = np.zeros((ob.size, ob.size), np.float64)
    classes[100:180, 60:140] = SW
    classes[90:98, 60:140] = BLD
    conf[100:180, 60:140] = 100.0
    conf[90:98, 60:140] = 200.0
    return [_gap_summary(cls.close_gaps(classes, conf, ob)), _gap_summary(_snap_gap(cls, fu, ob))]


def _snap_gap(cls: Any, fu: Any, ob: Any) -> Any:
    snap, snap_conf = fu.snapshot(0.0, (0.0, 0.0, 0.0), ob)
    return cls.close_gaps(snap, snap_conf, ob)


def _gap_summary(res: Any) -> list[Any]:
    if res is None:
        return [None]
    return [
        int(res[0].size),
        int(res[0].astype(np.int64).sum()),
        [int(x) for x in np.unique(res[1])],
        float(np.asarray(res[2]).sum()),
    ]


def _recentre_digest(fu: Any) -> list[Any]:
    cnt0 = int(fu.count.astype(np.int64).sum())
    v0 = float(fu.votes.sum())
    fu._recentre(0.0, 0.0)
    same = [fu.x0, fu.y0, int(fu.count.astype(np.int64).sum())]
    fu._recentre(30.0, -20.0)
    return [cnt0, v0, same, fu.x0, fu.y0, int(fu.count.astype(np.int64).sum()), float(fu.votes.sum())]


def _eq(actual: Any, expected: Any) -> None:
    if isinstance(expected, dict):
        assert actual == expected
    elif isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple)) and len(actual) == len(expected)
        for a, e in zip(actual, expected, strict=True):
            _eq(a, e)
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)
    else:
        assert actual == expected


def test_fusion_is_the_facade_object() -> None:
    from engine.worldmap import fusion as fusion_mod

    assert worldmap.Fusion is fusion_mod.Fusion


def test_fusion_attribute_list() -> None:
    from engine.worldmap.fusion import Fusion

    cfg = _cfg()
    kind = worldmap.class_kinds(cfg, NAMES)
    fu = Fusion(cfg, kind, np.array([SW, BLD]), (0.0, 0.0))
    assert sorted(vars(fu)) == ATTRS_AFTER_INIT
    assert fu.votes.shape == (2, fu.n, fu.n) and fu.votes.dtype == np.float32 and fu.count.dtype == np.uint16


def test_ten_frame_sequence_decay_none() -> None:
    from engine.worldmap.fusion import Fusion

    out, _fu, _ob, _pose, _t = _scenario_none(Fusion)
    _eq(out, FUSION_NONE)


def test_ten_frame_sequence_decay_time_pose_align() -> None:
    from engine.worldmap.fusion import Fusion

    out, offs, _fu, _ob, _pose, _t = _scenario_time_align(Fusion)
    _eq(out, FUSION_TIME[0])
    _eq(offs, FUSION_TIME[1])


def test_close_gaps_and_surface_at_on_the_final_state() -> None:
    from engine.worldmap.fusion import Fusion

    _out, fu, ob, pose, t = _scenario_none(Fusion)
    _eq(_gap_digest(Fusion, fu, ob), GAP)
    _eq(_surface_digest(fu, pose, t), SURFACE_NONE)
    _out2, _offs, fu2, _ob2, pose2, t2 = _scenario_time_align(Fusion)
    _eq(_surface_digest(fu2, pose2, t2), SURFACE_TIME)


def test_recentre_moves_the_window() -> None:
    from engine.worldmap.fusion import Fusion

    _out, fu, _ob, _pose, _t = _scenario_none(Fusion)
    _eq(_recentre_digest(fu), RECENTRE)
