"""Characterisation tests for engine.depthscale (v26.3.0 p2-08): anchors.py and scale.py.

Every expected literal at the bottom of this file was printed by the legacy ``collision`` functions
(``_DepthAnchor``, ``_InitialAnchor``, ``_ground_anchor``, ``_PlaneFit``, ``_plane_fit``, ``_PlaneAnchor``,
``_DepthScale``, ``_item_depth_m``, ``_ground_depth_distance``) in the hackeye-rnd image on the pre-move code,
by running the same helper functions (``_anchor_run`` ... ``_ground_distance_run``) with the legacy names.
After the move the legacy names are the engine objects, so the literals are pinned.

The inputs come from tests/fixtures/chest0004_review10.npz (window w0: grids and DA2 metric depth maps, read
straight from the npz) and from synthetic data. The collision config is read straight from
common/config/collision.json. The engine modules are imported inside each test function.
"""

from __future__ import annotations

import dataclasses
import functools
import importlib
import json
import math
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

import collision
from common_paths import find_common_dir

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "chest0004_review10"
FRAME_INDICES = list(range(0, 144, 6))
ITEM_FRAMES = [24, 60, 96, 132]

Digest = Any


def _close(got: Digest, exp: Digest, path: str = "") -> None:
    """Deep comparison: floats within 1e-12 (nan equals nan), everything else exactly equal."""
    if isinstance(exp, dict):
        assert isinstance(got, dict), path
        assert list(got) == list(exp), path
        for k in exp:
            _close(got[k], exp[k], f"{path}.{k}")
    elif isinstance(exp, (list, tuple)):
        assert isinstance(got, (list, tuple)), path
        assert len(got) == len(exp), path
        for i, (g, e) in enumerate(zip(got, exp, strict=True)):
            _close(g, e, f"{path}[{i}]")
    elif isinstance(exp, float):
        assert isinstance(got, float), path
        if math.isnan(exp):
            assert math.isnan(got), path
        else:
            assert got == pytest.approx(exp, rel=1e-12, abs=1e-12), path
    else:
        assert got == exp, path


@dataclasses.dataclass
class Frame:
    index: int
    t: float
    grid: npt.NDArray[np.int64]
    dmap: npt.NDArray[np.float16]
    region: Any
    horizon: float


@dataclasses.dataclass
class Setup:
    config: dict[str, Any]
    settings: Any
    ids: Any
    f: float
    gh: int
    gw: int
    anchor_rows: float
    anchor_horizon: float
    frames: list[Frame]
    surf_lut: npt.NDArray[np.bool_]


@functools.cache
def _setup() -> Setup:
    from engine.core.geom import focal_px
    from engine.core.settings import resolve_settings

    config: dict[str, Any] = json.loads((find_common_dir() / "config" / "collision.json").read_text())
    meta = json.loads(FIXTURE.with_suffix(".json").read_text())
    s = meta["settings"]
    settings = resolve_settings(
        config,
        s["mount"],
        s["hfovDeg"],
        s["cameraHeightM"],
        s["stepLengthM"],
        projection=s.get("projection"),
        distance_source=s.get("distanceSource", "ground"),
        user_height_m=s.get("userHeightM"),
        camera_location=s.get("cameraLocation"),
        camera_side=s.get("cameraSide"),
        object_distance=s.get("objectDistance"),
        use_horizon=s.get("useHorizon"),
    )
    ids = collision.resolve_class_ids(config, meta["classNames"])
    z = np.load(FIXTURE.with_suffix(".npz"))
    grids, depth, times = z["w0_grids"], z["w0_depth"], z["w0_t"]
    gh, gw = int(grids.shape[1]), int(grids.shape[2])
    lut = np.zeros(256, dtype=bool)
    for ids_arr in ids.surface_groups.values():
        lut[np.asarray(ids_arr)] = True
    frames = [
        Frame(
            i,
            float(times[i]),
            grids[i],
            depth[i],
            collision.walking_region(grids[i], ids, config),
            settings.horizon_default,
        )
        for i in FRAME_INDICES + ITEM_FRAMES
    ]
    return Setup(
        config,
        settings,
        ids,
        focal_px(gw, settings.hfov_deg),
        gh,
        gw,
        float(config["tracking"]["motionMinRowsBelowHorizon"]),
        float(settings.horizon_default),
        frames,
        lut,
    )


def _frame_items(fr: Frame) -> list[Any]:
    from engine.core.groundgeom import frame_geometry, walking_axis_offset_m

    st = _setup()
    geo = frame_geometry(
        st.gh,
        st.gw,
        fr.horizon,
        st.settings.camera_height_m,
        st.f,
        st.settings.hfov_deg,
        st.config["geometry"]["laneHalfWidthM"],
        fr.region,
        st.config["roles"]["boundaryMarginPx"],
        st.settings.projection,
        walking_axis_offset_m(st.settings),
        False,
    )
    items: list[Any] = collision.detect_items(fr.grid, st.ids, geo, st.config, None)
    return items


def _fit_tuple(fit: Any) -> Digest:
    return None if fit is None else [fit.height_units, fit.pitch_deg, fit.inliers, fit.fraction]


def _anchor_run(m: Any) -> Digest:
    """ground_anchor / plane_fit on the fixture frames, and the three anchor objects fed with them."""
    st = _setup()
    dist = st.config["distance"]
    per_frame = m.DepthAnchor(dist)
    initial = m.InitialAnchor(dist)
    plane = m.PlaneAnchor(dist, st.settings.camera_height_m)
    out: list[Digest] = []
    prev_t = 0.0
    for fr in st.frames[: len(FRAME_INDICES)]:
        dt = max(0.0, fr.t - prev_t)
        prev_t = fr.t
        raw, cells = m.ground_anchor(
            fr.region, fr.dmap, st.anchor_horizon, st.settings.camera_height_m, st.gh, st.gw, st.f, st.anchor_rows
        )
        fit = m.plane_fit(
            fr.region,
            fr.dmap,
            st.anchor_horizon,
            st.gh,
            st.gw,
            st.f,
            st.anchor_rows,
            st.settings.hfov_deg,
            st.settings.projection,
            dist,
        )
        fit_rect = m.plane_fit(
            fr.region,
            fr.dmap,
            st.anchor_horizon,
            st.gh,
            st.gw,
            st.f,
            st.anchor_rows,
            st.settings.hfov_deg,
            "rectilinear",
            dist,
        )
        per_frame.update(fr.t, dt, raw, cells)
        initial.update(fr.t, dt, raw, cells)
        plane.update(fit)
        out.append(
            {
                "i": fr.index,
                "ground": [raw, cells],
                "fit": _fit_tuple(fit),
                "fitRect": _fit_tuple(fit_rect),
                "perFrame": per_frame.value,
                "initial": [initial.value, initial.frozen, len(initial.ratios)],
                "plane": [
                    plane.value,
                    plane.pitch_deg,
                    plane.height_units,
                    plane.frozen,
                    len(plane.scales),
                    _fit_tuple(plane.fit),
                ],
            }
        )
    return out


def _anchor_sequences(m: Any) -> Digest:
    """Synthetic update sequences: hold, expiry, tau 0, too few cells, reset, invalid fits."""
    cfg: dict[str, Any] = {"anchorMinCells": 100, "anchorEmaSeconds": 0.5, "anchorHoldSeconds": 1.0}
    a = m.DepthAnchor(cfg)
    seq = [
        (0.0, 0.1, 2.0, 200),
        (0.1, 0.1, 3.0, 200),
        (0.2, 0.1, None, 0),
        (0.5, 0.3, 4.0, 50),
        (1.5, 1.0, float("nan"), 300),
        (1.7, 0.2, 5.0, 300),
        (3.0, 1.3, 0.0, 300),
        (4.5, 1.5, 1.5, 300),
        (4.6, -1.0, 6.0, 300),
    ]
    per_frame: list[Digest] = []
    for t, dt, raw, cells in seq:
        a.update(t, dt, raw, cells)
        per_frame.append([a.value, a.last_t])
    a0 = m.DepthAnchor({"anchorEmaSeconds": 0.0})
    tau0: list[Digest] = []
    for t, raw in [(0.0, 2.0), (0.2, 3.0), (0.4, 9.0)]:
        a0.update(t, 0.2, raw, 500)
        tau0.append(a0.value)
    d = m.DepthAnchor({})
    defaults = [d.min_cells, d.tau_s, d.hold_s, d.log_a, d.last_t]

    ini = m.InitialAnchor({"anchorMinCells": 100, "initialAnchorFrames": 5, "initialAnchorMinFrames": 2})
    ini_vals: list[Digest] = []
    for raw, cells in [(1.0, 200), (4.0, 50), (2.0, 200), (8.0, 200), (3.0, 200), (5.0, 200), (100.0, 200)]:
        ini.update(0.0, 0.1, raw, cells)
        ini_vals.append([ini.value, ini.frozen, list(ini.ratios)])
    ini.reset()
    after_reset = [ini.value, ini.frozen, list(ini.ratios)]
    ini_clamped = m.InitialAnchor({"initialAnchorFrames": 2, "initialAnchorMinFrames": 9})
    ini_default = m.InitialAnchor({})
    cfgs = [ini_clamped.n_freeze, ini_clamped.n_min, ini_default.n_freeze, ini_default.n_min, ini_default.min_cells]

    pa = m.PlaneAnchor({"initialAnchorFrames": 4, "initialAnchorMinFrames": 2}, 1.3)
    plane_vals: list[Digest] = []
    for fit in [
        m.PlaneFit(0.2, 4.0, 400, 0.9),
        None,
        m.PlaneFit(-1.0, 1.0, 400, 0.9),
        m.PlaneFit(0.25, 6.0, 380, 0.8),
        m.PlaneFit(0.3, 5.0, 390, 0.7),
        m.PlaneFit(0.21, 3.0, 410, 0.95),
        m.PlaneFit(0.5, 9.0, 410, 0.95),
    ]:
        pa.update(fit)
        plane_vals.append([pa.value, pa.pitch_deg, pa.height_units, pa.frozen, list(pa.scales), _fit_tuple(pa.fit)])
    pa.reset()
    plane_reset = [pa.value, pa.pitch_deg, pa.height_units, pa.frozen, pa.scales, pa.pitches, pa.heights, pa.fit]
    pd = m.PlaneAnchor({}, 1.45)
    plane_defaults = [pd.camera_height_m, pd.n_freeze, pd.n_min]
    return {
        "perFrame": per_frame,
        "tau0": tau0,
        "defaults": defaults,
        "initial": ini_vals,
        "afterReset": after_reset,
        "initialCfg": cfgs,
        "plane": plane_vals,
        "planeReset": plane_reset,
        "planeDefaults": plane_defaults,
    }


def _synthetic_plane(
    projection: str, outliers: int, seed: int = 7, hfov: float = 118.0
) -> tuple[Any, Any, float, float]:
    """(region, dmap, f, horizon) of a tilted ground plane (c=1.3, a=0.05, b=0.12) seen through ``projection``."""
    gh, gw = 135, 240
    f = gw / math.radians(hfov) if projection == "fisheye" else (gw / 2.0) / math.tan(math.radians(hfov) / 2.0)
    mask = np.zeros((gh, gw), dtype=bool)
    mask[70:, 40:200] = True
    rows, cols = np.mgrid[0:gh, 0:gw]
    px, py = cols + 0.5 - gw / 2.0, rows + 0.5 - gh / 2.0
    if projection == "fisheye":
        r = np.hypot(px, py)
        theta = r / f
        sin_over_r = np.where(r > 0, np.sin(theta) / np.maximum(r, 1e-12), 0.0)
        xn, yn = sin_over_r * px / np.cos(theta), sin_over_r * py / np.cos(theta)
    else:
        xn, yn = px / f, py / f
    a, b, c = 0.05, 0.12, 1.3
    with np.errstate(divide="ignore", invalid="ignore"):
        z = c / (yn - a * xn - b)
    z = np.where(np.isfinite(z) & (z > 0.3) & (z < 60.0), z, 60.0)
    dmap = z.astype(np.float32)
    rng = np.random.RandomState(seed)
    if outliers:
        idx = rng.choice(int(mask.sum()), outliers, replace=False)
        rr, cc = np.nonzero(mask)
        dmap[rr[idx], cc[idx]] = rng.uniform(0.5, 40.0, outliers).astype(np.float32)
    region = collision.Region("road", "road", mask, np.zeros(gh), np.zeros(gh))
    return region, dmap, f, 0.5


def _plane_run(m: Any) -> Digest:
    dist: dict[str, Any] = {"anchorMinCells": 150}
    out: dict[str, Any] = {}
    for proj in ("rectilinear", "fisheye"):
        for outliers in (0, 600, 6000):
            region, dmap, f, hz = _synthetic_plane(proj, outliers)
            fit = m.plane_fit(region, dmap, hz, 135, 240, f, 8.0, 118.0, proj, dist)
            again = m.plane_fit(region, dmap, hz, 135, 240, f, 8.0, 118.0, proj, dist)
            out[f"{proj}-{outliers}"] = [_fit_tuple(fit), _fit_tuple(again)]
    region, dmap, f, hz = _synthetic_plane("rectilinear", 600)
    out["noRegion"] = _fit_tuple(m.plane_fit(None, dmap, hz, 135, 240, f, 8.0, 118.0, "rectilinear", dist))
    out["tooFewCells"] = _fit_tuple(
        m.plane_fit(region, dmap, hz, 135, 240, f, 8.0, 118.0, "rectilinear", {"anchorMinCells": 20000})
    )
    out["minRowsAll"] = _fit_tuple(m.plane_fit(region, dmap, hz, 135, 240, f, 200.0, 118.0, "rectilinear", dist))
    out["strictFraction"] = _fit_tuple(
        m.plane_fit(
            region, dmap, hz, 135, 240, f, 8.0, 118.0, "rectilinear", {**dist, "planeMinInlierFraction": 0.9999}
        )
    )
    out["tightNormal"] = _fit_tuple(
        m.plane_fit(region, dmap, hz, 135, 240, f, 8.0, 118.0, "rectilinear", {**dist, "planeMaxNormalDeg": 1.0})
    )
    out["fewTrials"] = _fit_tuple(
        m.plane_fit(
            region,
            dmap,
            hz,
            135,
            240,
            f,
            8.0,
            118.0,
            "rectilinear",
            {**dist, "planeRansacTrials": 2, "planeRansacTol": 0.005},
        )
    )
    out["nanDepth"] = _fit_tuple(
        m.plane_fit(region, np.full_like(dmap, np.nan), hz, 135, 240, f, 8.0, 118.0, "rectilinear", dist)
    )
    out["groundAnchorSynthetic"] = list(m.ground_anchor(region, dmap, hz, 1.3, 135, 240, f, 8.0))
    out["groundAnchorNoRegion"] = list(m.ground_anchor(None, dmap, hz, 1.3, 135, 240, f, 8.0))
    out["groundAnchorNoRows"] = list(m.ground_anchor(region, dmap, hz, 1.3, 135, 240, f, 500.0))
    out["groundAnchorNan"] = list(m.ground_anchor(region, np.full_like(dmap, np.nan), hz, 1.3, 135, 240, f, 8.0))
    return out


def _scale_run(m: Any) -> Digest:
    ego = {
        "calibrationWindowSeconds": 4.0,
        "calibrationMinSamples": 3,
        "calibrationEmaMinSeconds": 1.0,
        "calibrationEmaSeconds": 6.0,
        "scaleMaxChangePerSecond": 0.25,
    }
    dist = {
        "depthLevelRange": [0.5, 2.0],
        "depthLevelMinSamples": 4,
        "depthWitnessMaxBearingDeg": 30.0,
        "depthWitnessMinEgoSpeed": 0.6,
    }
    s = m.DepthScale(ego, dist)
    attrs = [s.window_s, s.min_samples, s.tau_min_s, s.tau_s, s.max_rate, s.lo, s.hi, s.max_bearing, s.min_speed]
    defaults = m.DepthScale({}, {})
    attrs_default = [
        defaults.window_s,
        defaults.min_samples,
        defaults.tau_min_s,
        defaults.tau_s,
        defaults.max_rate,
        defaults.lo,
        defaults.hi,
        defaults.max_bearing,
        defaults.min_speed,
    ]
    ego_min = m.DepthScale({"calibrationMinSamples": 7}, {})
    samples = [
        s.sample(None, [(0.0, 1.0)]),
        s.sample(0.3, [(0.0, 1.0)]),
        s.sample(1.2, []),
        s.sample(1.2, [(45.0, 1.0), (0.0, -1.0)]),
        s.sample(1.2, [(10.0, 1.0), (-20.0, 2.0), (35.0, 0.1)]),
        s.sample(1.2, [(10.0, 0.5), (-20.0, 0.8), (0.0, 1.5)]),
    ]
    out: list[Digest] = []
    t = 0.0
    for k in range(40):
        t = k * 0.5
        smp: float | None
        if k % 7 == 3:
            smp = None
        elif k % 11 == 5:
            smp = float("nan")
        elif k < 20:
            smp = 0.8 + 0.01 * k
        else:
            smp = 3.0 if k % 5 else 0.1
        s.update(t, smp, 0.5)
        out.append([s.value, s.target, s.age_s, len(s.samples), s.holding])
    frozen = m.DepthScale(ego, dist)
    frozen.freeze = True
    fro: list[Digest] = []
    for k in range(30):
        frozen.update(k * 0.5, 1.2 if k < 12 else 0.6, 0.5, start=1.0)
        fro.append([frozen.value, frozen.target, frozen.age_s, frozen.holding])
    frozen2 = m.DepthScale(ego, dist)
    frozen2.freeze = True
    fro2: list[Digest] = []
    for k in range(20):
        frozen2.update(k * 0.5, 1.5, 0.5, start=None)
        fro2.append([frozen2.value, frozen2.target, frozen2.holding])
    zero_dt = m.DepthScale(ego, dist)
    zdt: list[Digest] = []
    for k in range(8):
        zero_dt.update(k * 0.1, 1.1, 0.0)
        zdt.append([zero_dt.value, zero_dt.target])
    fresh = m.DepthScale(ego, dist)
    return {
        "attrs": attrs,
        "attrsDefault": attrs_default,
        "egoMin": ego_min.min_samples,
        "initial": [fresh.freeze, fresh.age_s, fresh.samples, fresh.target, fresh.applied],
        "samples": samples,
        "continuous": out,
        "freeze": fro,
        "freezeNoStart": fro2,
        "zeroDt": zdt,
    }


def _item_depth_run(m: Any) -> Digest:
    st = _setup()
    out: list[Digest] = []
    for fr in st.frames[len(FRAME_INDICES) :]:
        items = _frame_items(fr)
        rows: list[Digest] = []
        for it in items:
            rows.append(
                [
                    it.class_name,
                    it.group,
                    it.base_row,
                    it.base_col,
                    m.item_depth_m(it, fr.dmap, st.gh, st.gw, 0.25),
                    m.item_depth_m(it, fr.dmap, st.gh, st.gw, 1.0),
                    m.item_depth_m(it, fr.dmap, st.gh, st.gw, 0.01),
                    m.item_depth_m(it, np.asarray(fr.dmap, dtype=np.float32)[::2, ::3], st.gh, st.gw, 0.25),
                ]
            )
        out.append([fr.index, rows])
    # explicit cells and edge cases
    fr = st.frames[len(FRAME_INDICES)]
    items = _frame_items(fr)
    edge: dict[str, Digest] = {"nItems": len(items)}
    it0 = items[0]
    cells = (np.array([100, 101, 102, 130]), np.array([10, 11, 12, 239]))
    edge["cells"] = m.item_depth_m(dataclasses.replace(it0, depth_cells=cells), fr.dmap, st.gh, st.gw, 0.5)
    edge["emptyCells"] = m.item_depth_m(
        dataclasses.replace(it0, depth_cells=(np.array([], dtype=int), np.array([], dtype=int))),
        fr.dmap,
        st.gh,
        st.gw,
        0.5,
    )
    mask = np.zeros((4, 5), dtype=bool)
    mask[1:4, 2:5] = True
    shaped = dataclasses.replace(it0, depth_cells=None, shape=(mask, 100, 60))
    edge["shape"] = m.item_depth_m(shaped, fr.dmap, st.gh, st.gw, 0.4)
    edge["noValid"] = m.item_depth_m(shaped, np.zeros((68, 120), dtype=np.float32), st.gh, st.gw, 0.4)
    nanmap = np.full((68, 120), np.nan, dtype=np.float32)
    nanmap[40:, :] = np.arange(120, dtype=np.float32)[None, :] % 7 - 1.0
    edge["nanMap"] = m.item_depth_m(shaped, nanmap, st.gh, st.gw, 1.0)
    edge["emptyMask"] = m.item_depth_m(
        dataclasses.replace(it0, depth_cells=None, shape=(np.zeros((3, 3), dtype=bool), 0, 0)),
        fr.dmap,
        st.gh,
        st.gw,
        0.5,
    )
    return {"frames": out, "edge": edge}


def _ground_distance_run(m: Any) -> Digest:
    from engine.core.distfuse import settings as dist_settings
    from engine.core.groundgeom import Geometry
    from engine.core.types import Track

    st = _setup()
    cfg = dist_settings(st.config["distance"])
    geo = Geometry(st.gh, st.gw, st.settings.hfov_deg, st.settings.projection, st.settings.camera_height_m)
    reps: dict[str, dict[str, Any]] = {
        "flat": {"ref": 1.0, "sigmaRows": 0.5},
        "curve": {"ref": 1.1, "sigmaRows": 1.5, "curve": [[3.0, 1.0], [8.0, 0.95], [12.0, 0.8], [16.0, 0.5]]},
    }
    out: list[Digest] = []
    detail: list[Digest] = []
    for fr in st.frames[len(FRAME_INDICES) :]:
        for rep_name, rep in reps.items():
            for mode in ("depth", "ground-contact", "ground+depth"):
                for contact_s_delta in (None, 0.02):
                    rows: list[Digest] = []
                    for it in _frame_items(fr):
                        d_raw = m.item_depth_m(it, fr.dmap, st.gh, st.gw, 0.25)
                        if d_raw is None:
                            continue
                        w = dataclasses.replace(it, depth_m=d_raw)
                        tr = Track.__new__(Track)
                        tr.contact_s = None if contact_s_delta is None else it.contact_y + contact_s_delta
                        d = m.ground_depth_distance(w, tr, fr.grid, st.surf_lut, fr.horizon, geo, st.gh, rep, cfg, mode)
                        rows.append([it.class_name, d_raw, d, w.raw_depth_m, w.ground_m, w.dist_source])
                        if (
                            fr.index == ITEM_FRAMES[0]
                            and rep_name == "curve"
                            and mode == "ground+depth"
                            and contact_s_delta is None
                        ):
                            detail.append(rows[-1])
                    out.append(
                        [
                            fr.index,
                            rep_name,
                            mode,
                            contact_s_delta,
                            len(rows),
                            sum(r[2] for r in rows),
                            sum(r[3] for r in rows),
                            sum(r[4] is not None for r in rows),
                            ",".join(r[5] for r in rows),
                            rows[0] if rows else None,
                            rows[-1] if rows else None,
                        ]
                    )
    edge: dict[str, Digest] = {}
    fr = st.frames[len(FRAME_INDICES)]
    base = next(i for i in _frame_items(fr) if i.base_row >= 0)
    tr = Track.__new__(Track)
    tr.contact_s = None
    overrides: dict[str, dict[str, Any]] = {
        "clipped": {"clipped": True},
        "noBase": {"base_col": -1},
        "lastRow": {"base_row": st.gh - 1},
        "horizonAbove": {"contact_y": 0.2, "base_row": 20},
    }
    for name, kw in overrides.items():
        w = dataclasses.replace(base, depth_m=6.0, **kw)
        d = m.ground_depth_distance(
            w, tr, fr.grid, st.surf_lut, fr.horizon, geo, st.gh, reps["curve"], cfg, "ground+depth"
        )
        edge[name] = [d, w.raw_depth_m, w.ground_m, w.dist_source]
    return {"digests": out, "detail": detail, "edge": edge}


NAMES = [
    "DepthAnchor",
    "InitialAnchor",
    "ground_anchor",
    "PlaneFit",
    "plane_fit",
    "PlaneAnchor",
    "DepthScale",
    "item_depth_m",
    "ground_depth_distance",
]
LEGACY = {
    "DepthAnchor": "_DepthAnchor",
    "InitialAnchor": "_InitialAnchor",
    "ground_anchor": "_ground_anchor",
    "PlaneFit": "_PlaneFit",
    "plane_fit": "_plane_fit",
    "PlaneAnchor": "_PlaneAnchor",
    "DepthScale": "_DepthScale",
    "item_depth_m": "_item_depth_m",
    "ground_depth_distance": "_ground_depth_distance",
}


def legacy_namespace() -> ModuleType:
    """The legacy names under their engine names (used to print the literals on the pre-move code)."""
    ns = ModuleType("legacy_depthscale")
    for new, old in LEGACY.items():
        setattr(ns, new, getattr(collision, old))
    return ns


def _engine() -> ModuleType:
    return importlib.import_module("engine.depthscale")


def test_facade_identity() -> None:
    from engine.depthscale import anchors, scale

    assert collision._DepthAnchor is anchors.DepthAnchor
    assert collision._InitialAnchor is anchors.InitialAnchor
    assert collision._ground_anchor is anchors.ground_anchor
    assert collision._PlaneFit is anchors.PlaneFit
    assert collision._plane_fit is anchors.plane_fit
    assert collision._PlaneAnchor is anchors.PlaneAnchor
    assert collision._DepthScale is scale.DepthScale
    assert collision._item_depth_m is scale.item_depth_m
    assert collision._ground_depth_distance is scale.ground_depth_distance


def test_package_reexports() -> None:
    from engine.depthscale import anchors, scale

    pkg = _engine()
    for name in NAMES:
        mod = anchors if name in EXP_ANCHOR_NAMES else scale
        assert getattr(pkg, name) is getattr(mod, name), name
        assert name in pkg.__all__, name


def test_plane_fit_fields() -> None:
    from engine.depthscale.anchors import PlaneFit

    assert [f.name for f in dataclasses.fields(PlaneFit)] == ["height_units", "pitch_deg", "inliers", "fraction"]
    fit = PlaneFit(0.25, 5.0, 400, 0.9)
    assert (fit.height_units, fit.pitch_deg, fit.inliers, fit.fraction) == (0.25, 5.0, 400, 0.9)
    assert dataclasses.astuple(fit) == (0.25, 5.0, 400, 0.9)
    assert fit == PlaneFit(0.25, 5.0, 400, 0.9)
    assert fit != PlaneFit(0.25, 5.0, 400, 0.8)


def test_attribute_lists() -> None:
    from engine.depthscale.anchors import DepthAnchor, InitialAnchor, PlaneAnchor
    from engine.depthscale.scale import DepthScale

    dist = _setup().config["distance"]
    ego = _setup().config["ego"]
    assert list(vars(DepthAnchor(dist))) == EXP_ATTRS["DepthAnchor"]
    assert list(vars(InitialAnchor(dist))) == EXP_ATTRS["InitialAnchor"]
    assert list(vars(PlaneAnchor(dist, 1.3))) == EXP_ATTRS["PlaneAnchor"]
    assert list(vars(DepthScale(ego, dist))) == EXP_ATTRS["DepthScale"]
    for cls, props in EXP_PROPERTIES.items():
        owner = {
            "DepthAnchor": DepthAnchor,
            "InitialAnchor": InitialAnchor,
            "PlaneAnchor": PlaneAnchor,
            "DepthScale": DepthScale,
        }[cls]
        assert sorted(k for k, v in vars(owner).items() if isinstance(v, property)) == props, cls


def test_config_values_read_by_constructors() -> None:
    from engine.depthscale.anchors import DepthAnchor, InitialAnchor, PlaneAnchor
    from engine.depthscale.scale import DepthScale

    dist = _setup().config["distance"]
    ego = _setup().config["ego"]
    a = DepthAnchor(dist)
    assert [a.min_cells, a.tau_s, a.hold_s, a.log_a, a.last_t] == EXP_CONFIG["DepthAnchor"]
    i = InitialAnchor(dist)
    assert [i.min_cells, i.n_freeze, i.n_min] == EXP_CONFIG["InitialAnchor"]
    p = PlaneAnchor(dist, 1.3)
    assert [p.camera_height_m, p.n_freeze, p.n_min] == EXP_CONFIG["PlaneAnchor"]
    s = DepthScale(ego, dist)
    assert [
        s.window_s,
        s.min_samples,
        s.tau_min_s,
        s.tau_s,
        s.max_rate,
        s.lo,
        s.hi,
        s.max_bearing,
        s.min_speed,
    ] == EXP_CONFIG["DepthScale"]


def test_anchors_on_fixture_frames() -> None:
    got = _anchor_run(_engine())
    _close(got, EXP_ANCHOR_RUN)


def test_anchor_update_sequences() -> None:
    _close(_anchor_sequences(_engine()), EXP_ANCHOR_SEQUENCES)


def test_plane_fit_synthetic_and_deterministic() -> None:
    got = _plane_run(_engine())
    _close(got, EXP_PLANE_RUN)
    # the synthetic planes were fitted twice (`fit`, `again`): RANSAC is seeded per call, so both runs are equal
    twice = [k for k in got if k.startswith(("fisheye-", "rectilinear-"))]
    assert twice
    for key in twice:
        first, second = got[key]
        assert first == second, key


def test_depth_scale_sequences() -> None:
    _close(_scale_run(_engine()), EXP_SCALE_RUN)


def test_item_depth_m_on_fixture_items() -> None:
    got = _item_depth_run(_engine())
    _close(got, EXP_ITEM_DEPTH)


def test_ground_depth_distance_fields_written() -> None:
    got = _ground_distance_run(_engine())
    assert len(got["digests"]) == 48
    _close(got, EXP_GROUND_DISTANCE)


# --- characterisation literals (printed by the legacy code) ---

EXP_ANCHOR_RUN: Any = [
    {
        "i": 0,
        "ground": [0.25589907855891736, 9067],
        "fit": [4.370260125409288, 13.567524301573847, 6244, 0.6886511525311569],
        "fitRect": [6.11799568501513, 16.88039284022404, 8180, 0.9021727142384471],
        "perFrame": 0.2558990785589174,
        "initial": [None, None, 1],
        "plane": [None, None, None, False, 1, [4.370260125409288, 13.567524301573847, 6244, 0.6886511525311569]],
    },
    {
        "i": 6,
        "ground": [0.24315903295182378, 8686],
        "fit": None,
        "fitRect": [6.012461200843521, 12.320467791776894, 8320, 0.9578632281832834],
        "perFrame": 0.24417790559648297,
        "initial": [None, None, 2],
        "plane": [None, None, None, False, 1, None],
    },
    {
        "i": 12,
        "ground": [0.24856989136044338, 8733],
        "fit": [4.214045200046906, 9.586592191770105, 5286, 0.6052902782548952],
        "fitRect": [5.96790584460578, 11.834116181195595, 8217, 0.9409137753349365],
        "perFrame": 0.2482073260080864,
        "initial": [0.24856989136044338, None, 3],
        "plane": [None, None, None, False, 2, [4.214045200046906, 9.586592191770105, 5286, 0.6052902782548952]],
    },
    {
        "i": 18,
        "ground": [0.24459776941382624, 8533],
        "fit": [4.352055505743518, 9.26268074746626, 5570, 0.6527598734325559],
        "fitRect": [6.04878598268536, 10.560879579887185, 8006, 0.9382397749912106],
        "perFrame": 0.2448913358378116,
        "initial": [0.24658383038713483, None, 4],
        "plane": [
            0.2944815382774048,
            9.586592191770105,
            4.352055505743518,
            False,
            3,
            [4.352055505743518, 9.26268074746626, 5570, 0.6527598734325559],
        ],
    },
    {
        "i": 24,
        "ground": [0.243910539406271, 8585],
        "fit": None,
        "fitRect": [6.053955247287804, 11.210978781707505, 8217, 0.9571345369831101],
        "perFrame": 0.2439906989959215,
        "initial": [0.24459776941382624, None, 5],
        "plane": [0.2944815382774048, 9.586592191770105, 4.352055505743518, False, 3, None],
    },
    {
        "i": 30,
        "ground": [0.23598812313286918, 8189],
        "fit": None,
        "fitRect": [6.025099497206981, 10.802774363769213, 7659, 0.9352790328489438],
        "perFrame": 0.2366333882055749,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [0.2944815382774048, 9.586592191770105, 4.352055505743518, False, 3, None],
    },
    {
        "i": 36,
        "ground": [0.22602169244726514, 7316],
        "fit": [4.28288066602543, 7.524126760503605, 4632, 0.6331328594860579],
        "fitRect": [6.101908975999171, 9.223236536186109, 6936, 0.9480590486604702],
        "perFrame": 0.22687239305037968,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.29685969386925554,
            9.424636469618182,
            4.3174680858844745,
            False,
            4,
            [4.28288066602543, 7.524126760503605, 4632, 0.6331328594860579],
        ],
    },
    {
        "i": 42,
        "ground": [0.23111086119037175, 8518],
        "fit": None,
        "fitRect": [5.9839896808916775, 9.3062911727439, 8012, 0.9405963841277295],
        "perFrame": 0.23076085962635895,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [0.29685969386925554, 9.424636469618182, 4.3174680858844745, False, 4, None],
    },
    {
        "i": 48,
        "ground": [0.2474220807520094, 9376],
        "fit": [4.098333102326978, 8.56349184215824, 5787, 0.6172141638225256],
        "fitRect": [5.86820512944933, 11.231192050629174, 8875, 0.9465656996587031],
        "perFrame": 0.2460137810326661,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.29923784946110626,
            9.26268074746626,
            4.28288066602543,
            False,
            5,
            [4.098333102326978, 8.56349184215824, 5787, 0.6172141638225256],
        ],
    },
    {
        "i": 54,
        "ground": [0.24496439821995908, 10147],
        "fit": [4.145906595604613, 8.32523153545891, 6236, 0.6145658815413423],
        "fitRect": [5.852942166911579, 10.567820006920329, 9833, 0.9690548930718439],
        "perFrame": 0.24505380600090682,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.145906595604613, 8.32523153545891, 6236, 0.6145658815413423],
        ],
    },
    {
        "i": 60,
        "ground": [0.23967917343769563, 10227],
        "fit": None,
        "fitRect": [5.927529372149634, 9.83310236244614, 10033, 0.9810306052605847],
        "perFrame": 0.24011478122335878,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [0.3016818404280087, 8.91308629481225, 4.248462933036167, True, 6, None],
    },
    {
        "i": 66,
        "ground": [0.22495028568454115, 8810],
        "fit": [4.277559432593093, 6.956944801843076, 5464, 0.6202043132803632],
        "fitRect": [5.990675254107446, 7.802295594276492, 8628, 0.9793416572077185],
        "perFrame": 0.22615510576070966,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.277559432593093, 6.956944801843076, 5464, 0.6202043132803632],
        ],
    },
    {
        "i": 72,
        "ground": [0.23740137102271577, 8885],
        "fit": [4.23676262866254, 8.56902743476611, 5511, 0.6202588632526731],
        "fitRect": [5.935763677912736, 10.182827747311999, 8571, 0.9646595385481148],
        "perFrame": 0.23645987499753457,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.23676262866254, 8.56902743476611, 5511, 0.6202588632526731],
        ],
    },
    {
        "i": 78,
        "ground": [0.22352829184536327, 8298],
        "fit": None,
        "fitRect": [6.067551426560783, 8.696968589543939, 8126, 0.9792721137623523],
        "perFrame": 0.22456000577787713,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [0.3016818404280087, 8.91308629481225, 4.248462933036167, True, 6, None],
    },
    {
        "i": 84,
        "ground": [0.21026637950497315, 7610],
        "fit": [4.351580341884391, 6.173062027660287, 4914, 0.6457293035479632],
        "fitRect": [6.067541242137693, 6.288744974808387, 7364, 0.9676741130091985],
        "perFrame": 0.2114017293741197,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.351580341884391, 6.173062027660287, 4914, 0.6457293035479632],
        ],
    },
    {
        "i": 90,
        "ground": [0.20861149056253192, 6166],
        "fit": [4.3583624321912, 5.732079008836464, 4308, 0.6986701265001621],
        "fitRect": [6.081882117017103, 5.543814735515337, 5798, 0.9403178722024003],
        "perFrame": 0.20883856395885797,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.3583624321912, 5.732079008836464, 4308, 0.6986701265001621],
        ],
    },
    {
        "i": 96,
        "ground": [0.2091292467687624, 7115],
        "fit": [4.45671142924679, 6.606676112894239, 4478, 0.6293745607870695],
        "fitRect": [6.082773074234251, 6.0169691462602675, 6738, 0.947013352073085],
        "perFrame": 0.20910543050706049,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.45671142924679, 6.606676112894239, 4478, 0.6293745607870695],
        ],
    },
    {
        "i": 102,
        "ground": [0.21024348758140807, 5597],
        "fit": None,
        "fitRect": [6.050876661696704, 5.595484936474145, 5085, 0.9085224227264606],
        "perFrame": 0.21015007129462573,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [0.3016818404280087, 8.91308629481225, 4.248462933036167, True, 6, None],
    },
    {
        "i": 108,
        "ground": [0.22294292488207745, 4520],
        "fit": [4.426870942272377, 8.225688657788238, 2773, 0.613495575221239],
        "fitRect": [5.8896596306234255, 5.595701064603765, 4240, 0.9380530973451328],
        "perFrame": 0.22186679913129936,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.426870942272377, 8.225688657788238, 2773, 0.613495575221239],
        ],
    },
    {
        "i": 114,
        "ground": [0.2425320581336753, 6576],
        "fit": [4.280894945540088, 10.210388679345852, 3953, 0.6011253041362531],
        "fitRect": [5.9167502768861615, 10.97563966955651, 6105, 0.9283759124087592],
        "perFrame": 0.24076995927700048,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.280894945540088, 10.210388679345852, 3953, 0.6011253041362531],
        ],
    },
    {
        "i": 120,
        "ground": [0.2525767074343429, 6499],
        "fit": [4.266671067455074, 11.240695264880738, 4361, 0.6710263117402677],
        "fitRect": [6.007169133014304, 14.313843638140577, 6130, 0.9432220341591014],
        "perFrame": 0.251588585827282,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.266671067455074, 11.240695264880738, 4361, 0.6710263117402677],
        ],
    },
    {
        "i": 126,
        "ground": [0.20895929845840422, 5118],
        "fit": [4.4608012402555905, 6.907521452755832, 3699, 0.7227432590855803],
        "fitRect": [6.248369571081567, 7.193779850339114, 4719, 0.9220398593200468],
        "perFrame": 0.2121600504453321,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.4608012402555905, 6.907521452755832, 3699, 0.7227432590855803],
        ],
    },
    {
        "i": 132,
        "ground": [0.22822128563966182, 5741],
        "fit": [4.354469887529783, 8.871232375637014, 3959, 0.6896011147883644],
        "fitRect": [6.140779603998789, 10.54717189817991, 5389, 0.9386866399581955],
        "perFrame": 0.22686169245658655,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.354469887529783, 8.871232375637014, 3959, 0.6896011147883644],
        ],
    },
    {
        "i": 138,
        "ground": [0.20896137498312656, 5746],
        "fit": [4.4122166995556675, 5.50471991483338, 4181, 0.7276366167768883],
        "fitRect": [6.114566259397211, 5.3420050102004115, 5327, 0.9270797076226941],
        "perFrame": 0.21037238491548166,
        "initial": [0.2442541544100486, 0.2442541544100486, 6],
        "plane": [
            0.3016818404280087,
            8.91308629481225,
            4.248462933036167,
            True,
            6,
            [4.4122166995556675, 5.50471991483338, 4181, 0.7276366167768883],
        ],
    },
]

EXP_ANCHOR_SEQUENCES: Any = {
    "perFrame": [
        [2.0, 0.0],
        [2.152533531992535, 0.1],
        [2.152533531992535, 0.1],
        [2.152533531992535, 0.1],
        [None, 0.1],
        [4.999999999999999, 1.7],
        [None, 1.7],
        [1.5, 4.5],
        [1.5, 4.6],
    ],
    "tau0": [2.0, 3.0000000000000004, 9.000000000000002],
    "defaults": [150, 0.5, 2.0, None, -math.inf],
    "initial": [
        [None, None, [1.0]],
        [None, None, [1.0]],
        [1.5, None, [1.0, 2.0]],
        [2.0, None, [1.0, 2.0, 8.0]],
        [2.5, None, [1.0, 2.0, 8.0, 3.0]],
        [3.0, 3.0, [1.0, 2.0, 8.0, 3.0, 5.0]],
        [3.0, 3.0, [1.0, 2.0, 8.0, 3.0, 5.0]],
    ],
    "afterReset": [None, None, []],
    "initialCfg": [2, 2, 6, 3, 150],
    "plane": [
        [None, None, None, False, [6.5], [0.2, 4.0, 400, 0.9]],
        [None, None, None, False, [6.5], None],
        [None, None, None, False, [6.5], [-1.0, 1.0, 400, 0.9]],
        [5.85, 5.0, 0.225, False, [6.5, 5.2], [0.25, 6.0, 380, 0.8]],
        [5.2, 5.0, 0.25, False, [6.5, 5.2, 4.333333333333334], [0.3, 5.0, 390, 0.7]],
        [
            5.695238095238095,
            4.5,
            0.22999999999999998,
            True,
            [6.5, 5.2, 4.333333333333334, 6.190476190476191],
            [0.21, 3.0, 410, 0.95],
        ],
        [
            5.695238095238095,
            4.5,
            0.22999999999999998,
            True,
            [6.5, 5.2, 4.333333333333334, 6.190476190476191],
            [0.5, 9.0, 410, 0.95],
        ],
    ],
    "planeReset": [None, None, None, False, [], [], [], None],
    "planeDefaults": [1.45, 6, 3],
}

EXP_PLANE_RUN: Any = {
    "rectilinear-0": [
        [1.2891565959068434, -6.834219054016239, 9159, 0.9540625],
        [1.2891565959068434, -6.834219054016239, 9159, 0.9540625],
    ],
    "rectilinear-600": [
        [1.2891576216278147, -6.834194420429211, 8625, 0.8984375],
        [1.2891576216278147, -6.834194420429211, 8625, 0.8984375],
    ],
    "rectilinear-6000": [None, None],
    "fisheye-0": [
        [1.2891656554939825, -6.834102694874043, 8341, 0.8688541666666667],
        [1.2891656554939825, -6.834102694874043, 8341, 0.8688541666666667],
    ],
    "fisheye-600": [
        [1.2891642761085778, -6.834119763602333, 7841, 0.8167708333333333],
        [1.2891642761085778, -6.834119763602333, 7841, 0.8167708333333333],
    ],
    "fisheye-6000": [None, None],
    "noRegion": None,
    "tooFewCells": None,
    "minRowsAll": None,
    "strictFraction": None,
    "tightNormal": None,
    "fewTrials": None,
    "nanDepth": None,
    "groundAnchorSynthetic": [0.7593957637491848, 9600],
    "groundAnchorNoRegion": [None, 0],
    "groundAnchorNoRows": [None, 0],
    "groundAnchorNan": [None, 0],
}

EXP_SCALE_RUN: Any = {
    "attrs": [4.0, 4, 1.0, 6.0, 0.25, 0.5, 2.0, 30.0, 0.6],
    "attrsDefault": [20.0, 12, 3.0, 40.0, 0.25, 0.3, 5.0, 40.0, 0.5],
    "egoMin": 7,
    "initial": [False, 0.0, [], None, None],
    "samples": [None, None, None, None, 0.8999999999999999, 1.4999999999999998],
    "continuous": [
        [None, None, 0.0, 1, False],
        [None, None, 0.0, 2, False],
        [None, None, 0.0, 3, False],
        [None, None, 0.0, 3, False],
        [0.8150000000000001, 0.8150000000000001, 0.0, 4, False],
        [0.8150000000000001, 0.8150000000000001, 0.5, 4, False],
        [0.8169636983841199, 0.8169636983841199, 1.0, 5, False],
        [0.8206381465841144, 0.8206381465841144, 1.5, 6, False],
        [0.8248821670394623, 0.8248821670394623, 2.0, 7, False],
        [0.831139787666362, 0.831139787666362, 2.5, 7, False],
        [0.8362505034324887, 0.8362505034324887, 3.0, 6, False],
        [0.8413082060857441, 0.8413082060857441, 3.5, 6, False],
        [0.8457649286730592, 0.8457649286730592, 4.0, 7, False],
        [0.8503113282359177, 0.8503113282359177, 4.5, 7, False],
        [0.8549192709209956, 0.8549192709209956, 5.0, 8, False],
        [0.8599798725489307, 0.8599798725489307, 5.5, 8, False],
        [0.8646312914041527, 0.8646312914041527, 6.0, 7, False],
        [0.8693096680847, 0.8693096680847, 6.5, 6, False],
        [0.8743877661616959, 0.8743877661616959, 7.0, 6, False],
        [0.8794609881550653, 0.8794609881550653, 7.5, 7, False],
        [0.884154572525925, 0.884154572525925, 8.0, 7, False],
        [0.8892470730661972, 0.8892470730661972, 8.5, 7, False],
        [0.8961833282285627, 0.8961833282285627, 9.0, 7, False],
        [0.9033457522780778, 0.9033457522780778, 9.5, 7, False],
        [0.9624226507565584, 0.9624226507565584, 10.0, 6, False],
        [0.9645990712089916, 0.9645990712089916, 10.5, 7, False],
        [1.0223050524600745, 1.0223050524600745, 11.0, 8, False],
        [1.0786573860749236, 1.0786573860749236, 11.5, 7, False],
        [1.1332437431950086, 1.1332437431950086, 12.0, 7, False],
        [1.1859022848464555, 1.1859022848464555, 12.5, 7, False],
        [1.2365090853271705, 1.2365090853271705, 13.0, 7, False],
        [1.2849749199010299, 1.2849749199010299, 13.5, 6, False],
        [1.3312417983366245, 1.3312417983366245, 14.0, 6, False],
        [1.3752794001051316, 1.3752794001051316, 14.5, 7, False],
        [1.4170815345392718, 1.4170815345392718, 15.0, 7, False],
        [1.4566627197026287, 1.4566627197026287, 15.5, 7, False],
        [1.4940549478130776, 1.4940549478130776, 16.0, 8, False],
        [1.5293046830641137, 1.5293046830641137, 16.5, 8, False],
        [1.5624701195481896, 1.5624701195481896, 17.0, 7, False],
        [1.5936187124610803, 1.5936187124610803, 17.5, 7, False],
    ],
    "freeze": [
        [None, None, 0.0, False],
        [None, None, 0.0, False],
        [None, None, 0.0, False],
        [1.1331484530668263, 1.2, 0.0, False],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
        [1.2, 1.2, 0.0, True],
    ],
    "freezeNoStart": [
        [None, None, False],
        [None, None, False],
        [None, None, False],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
        [1.5, 1.5, True],
    ],
    "zeroDt": [[None, None], [None, None], [None, None], [1.1, 1.1], [1.1, 1.1], [1.1, 1.1], [1.1, 1.1], [1.1, 1.1]],
}

EXP_ITEM_DEPTH: Any = {
    "frames": [
        [
            24,
            [
                ["pole", "static", 103, 80, 8.7265625, 8.8046875, 8.59375, 8.765625],
                ["sign", "static", 81, 238, 5.21484375, 5.98828125, 4.84765625, 5.30078125],
                ["nature vegetation", "static", 81, 64, 15.9609375, 16.21875, 15.203125, 16.546875],
                ["nature vegetation", "static", 96, 79, 9.234375, 9.9296875, 8.890625, 9.4453125],
                ["nature vegetation", "static", 67, 92, 32.625, 34.875, 29.53125, 37.3125],
                ["building", "static", 65, 8, 35.09375, 36.484375, 34.71875, 34.9375],
                ["building", "static", 134, 176, 5.24609375, 6.07421875, 5.00390625, 5.3203125],
                ["person", "moving", 82, 115, 16.046875, 17.3125, 15.3359375, 16.1875],
                ["person", "moving", 81, 131, 17.5625, 19.171875, 15.43359375, 17.6875],
                ["person", "moving", 81, 133, 16.984375, 17.796875, 15.453125, 17.6875],
                ["curb", "feature", 74, 0, 23.046875, 26.109375, 20.78125, 23.046875],
                ["curb", "feature", 81, 50, 16.140625, 16.171875, 15.01171875, 16.1875],
                ["curb", "feature", 100, 3, 9.49609375, 10.5078125, 9.14453125, 9.984375],
            ],
        ],
        [
            60,
            [
                ["pole", "static", 74, 110, 22.859375, 30.640625, 22.8359375, 24.625],
                ["sign", "static", 77, 140, 20.953125, 22.921875, 19.2109375, 21.140625],
                ["barrier", "static", 68, 115, 31.765625, 31.765625, 31.765625, 31.765625],
                ["nature vegetation", "static", 67, 20, 31.0, 34.65625, 30.828125, 30.828125],
                ["nature vegetation", "static", 84, 64, 14.453125, 14.8359375, 14.1328125, 14.765625],
                ["nature vegetation", "static", 69, 91, 31.609375, 32.28125, 28.5625, 31.8125],
                ["building", "static", 65, 10, 37.34375, 37.09375, 37.09375, 37.5],
                ["building", "static", 72, 138, 26.8359375, 32.546875, 24.03125, 29.25],
                ["building", "static", 134, 230, 6.0, 7.84765625, 5.55859375, 6.125],
                ["curb", "feature", 73, 2, 24.09375, 27.28125, 21.25, 24.09375],
                ["curb", "feature", 97, 23, 10.6953125, 12.734375, 9.6875, 11.296875],
            ],
        ],
        [
            96,
            [
                ["sign", "static", 67, 97, 11.671875, 10.40625, 12.15234375, 12.1171875],
                ["sign", "static", 94, 200, 7.12890625, 7.390625, 6.70703125, 7.28125],
                ["sign", "static", 104, 180, 8.5625, 8.59375, 8.46875, 8.65625],
                ["sidewalk-obstacle", "static", 101, 113, 10.3515625, 10.36328125, 10.3203125, 10.34375],
                ["barrier fence", "static", 69, 66, 62.84375, 65.3125, 54.609375, 51.21875],
                ["nature vegetation", "static", 114, 27, 8.9765625, 9.1484375, 8.7578125, 8.984375],
                ["nature vegetation", "static", 78, 80, 26.53125, 32.5, 25.234375, 28.1875],
                ["nature vegetation", "static", 83, 2, 23.2890625, 23.0625, 23.0625, 23.046875],
                ["building", "static", 80, 5, 32.65625, 38.34375, 29.828125, 36.34375],
                ["building", "static", 72, 22, 43.3125, 48.8125, 38.40625, 9.109375],
                ["building", "static", 134, 201, 5.5234375, 6.5859375, 5.203125, 5.609375],
                ["vehicle", "moving", 78, 33, 32.5625, 37.21875, 31.9375, 32.875],
                ["curb", "feature", 83, 67, 21.765625, 23.828125, 19.953125, 24.609375],
                ["curb", "feature", 88, 2, 19.765625, 21.421875, 19.953125, 19.953125],
                ["curb", "feature", 91, 53, 15.47265625, 17.078125, 14.9609375, 16.1484375],
                ["curb", "feature", 101, 35, 12.015625, 12.6640625, 11.421875, 12.015625],
                ["curb", "feature", 120, 1, 8.171875, 8.828125, 7.94140625, 8.609375],
            ],
        ],
        [
            132,
            [
                ["pole", "static", 82, 127, 16.828125, 19.84375, 16.03125, 16.828125],
                ["sign", "static", 83, 102, 16.25, 17.0, 15.75, 16.3125],
                ["barrier wall", "static", 66, 95, 18.375, 19.890625, 17.890625, 18.828125],
                ["nature vegetation", "static", 120, 59, 7.7890625, 11.1796875, 7.25, 7.921875],
                ["building", "static", 67, 4, 30.578125, 35.0, 22.46875, 34.8125],
                ["building", "static", 66, 21, 35.953125, 35.96875, 33.0625, 36.40625],
                ["building", "static", 134, 173, 4.921875, 5.15625, 4.71484375, 4.9453125],
                ["person", "moving", 65, 132, 36.96875, 39.53125, 37.078125, 36.96875],
                ["vehicle", "moving", 67, 71, 39.9375, 46.8125, 35.5625, 17.734375],
                ["vehicle", "moving", 85, 1, 20.25, 22.6875, 18.96875, 20.25],
                ["vehicle", "moving", 76, 44, 27.265625, 25.671875, 27.25, 27.265625],
                ["vehicle", "moving", 75, 61, 25.5625, 27.3125, 25.78125, 25.296875],
                ["curb", "feature", 77, 35, 25.78125, 26.0, 25.78125, 27.15625],
                ["curb", "feature", 97, 64, 11.984375, 12.8828125, 11.15625, 8.7109375],
                ["curb", "feature", 134, 24, 6.37890625, 7.23828125, 6.04296875, 6.56640625],
            ],
        ],
    ],
    "edge": {
        "nItems": 13,
        "cells": 4.28125,
        "emptyCells": None,
        "shape": 50.0625,
        "noValid": None,
        "nanMap": None,
        "emptyMask": None,
    },
}

EXP_GROUND_DISTANCE: Any = {
    "digests": [
        [
            24,
            "flat",
            "depth",
            None,
            13,
            211.37890625,
            211.37890625,
            10,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 8.7265625, 8.7265625, 8.7265625, 3.245792792855303, "depth"],
            ["curb", 9.49609375, 9.49609375, 9.49609375, 2.426622514862711, "depth"],
        ],
        [
            24,
            "flat",
            "depth",
            0.02,
            13,
            211.37890625,
            211.37890625,
            10,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 8.7265625, 8.7265625, 8.7265625, 3.038389050071617, "depth"],
            ["curb", 9.49609375, 9.49609375, 9.49609375, 2.2461011021934922, "depth"],
        ],
        [
            24,
            "flat",
            "ground-contact",
            None,
            13,
            132.41369791494876,
            211.37890625,
            10,
            "ground,ground,ground,depth,depth,ground,depth,ground,ground,ground,ground,ground,ground",
            ["pole", 8.7265625, 3.245792792855303, 8.7265625, 3.245792792855303, "ground"],
            ["curb", 9.49609375, 2.426622514862711, 9.49609375, 2.426622514862711, "ground"],
        ],
        [
            24,
            "flat",
            "ground-contact",
            0.02,
            13,
            110.5387279109197,
            211.37890625,
            10,
            "ground,ground,ground,depth,depth,ground,depth,ground,ground,ground,ground,ground,ground",
            ["pole", 8.7265625, 3.038389050071617, 8.7265625, 3.038389050071617, "ground"],
            ["curb", 9.49609375, 2.2461011021934922, 9.49609375, 2.2461011021934922, "ground"],
        ],
        [
            24,
            "flat",
            "ground+depth",
            None,
            13,
            134.31659658049793,
            211.37890625,
            10,
            "fused,fused,fused,depth,depth,fused,depth,fused,fused,fused,fused,fused,fused",
            ["pole", 8.7265625, 3.254060106329128, 8.7265625, 3.245792792855303, "fused"],
            ["curb", 9.49609375, 2.433539202030124, 9.49609375, 2.426622514862711, "fused"],
        ],
        [
            24,
            "flat",
            "ground+depth",
            0.02,
            13,
            112.9591973116341,
            211.37890625,
            10,
            "fused,fused,fused,depth,depth,fused,depth,fused,fused,fused,fused,fused,fused",
            ["pole", 8.7265625, 3.045200536650353, 8.7265625, 3.038389050071617, "fused"],
            ["curb", 9.49609375, 2.251586933712869, 9.49609375, 2.2461011021934922, "fused"],
        ],
        [
            24,
            "curve",
            "depth",
            None,
            13,
            211.37890625,
            211.37890625,
            10,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 8.7265625, 8.7265625, 8.7265625, 3.5703720721408336, "depth"],
            ["curb", 9.49609375, 9.49609375, 9.49609375, 2.6692847663489827, "depth"],
        ],
        [
            24,
            "curve",
            "depth",
            0.02,
            13,
            211.37890625,
            211.37890625,
            10,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 8.7265625, 8.7265625, 8.7265625, 3.342227955078779, "depth"],
            ["curb", 9.49609375, 9.49609375, 9.49609375, 2.4707112124128416, "depth"],
        ],
        [
            24,
            "curve",
            "ground-contact",
            None,
            13,
            140.94452083144364,
            211.37890625,
            10,
            "ground,ground,ground,depth,depth,ground,depth,ground,ground,ground,ground,ground,ground",
            ["pole", 8.7265625, 3.5703720721408336, 8.7265625, 3.5703720721408336, "ground"],
            ["curb", 9.49609375, 2.6692847663489827, 9.49609375, 2.6692847663489827, "ground"],
        ],
        [
            24,
            "curve",
            "ground-contact",
            0.02,
            13,
            116.88205382701167,
            211.37890625,
            10,
            "ground,ground,ground,depth,depth,ground,depth,ground,ground,ground,ground,ground,ground",
            ["pole", 8.7265625, 3.342227955078779, 8.7265625, 3.342227955078779, "ground"],
            ["curb", 9.49609375, 2.4707112124128416, 9.49609375, 2.4707112124128416, "ground"],
        ],
        [
            24,
            "curve",
            "ground+depth",
            None,
            13,
            160.76711314018516,
            211.37890625,
            10,
            "fused,fused,fused,depth,depth,fused,depth,fused,fused,fused,fused,fused,fused",
            ["pole", 8.7265625, 3.6390334507476845, 8.7265625, 3.5703720721408336, "fused"],
            ["curb", 9.49609375, 2.7220633732188553, 9.49609375, 2.6692847663489827, "fused"],
        ],
        [
            24,
            "curve",
            "ground+depth",
            0.02,
            13,
            133.243649353876,
            211.37890625,
            10,
            "fused,fused,fused,depth,depth,fused,depth,fused,fused,fused,fused,fused,fused",
            ["pole", 8.7265625, 3.3989340539659807, 8.7265625, 3.342227955078779, "fused"],
            ["curb", 9.49609375, 2.512575211274951, 9.49609375, 2.4707112124128416, "fused"],
        ],
        [
            60,
            "flat",
            "depth",
            None,
            11,
            257.609375,
            257.609375,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 22.859375, 22.859375, 22.859375, 10.472825154230266, "depth"],
            ["curb", 10.6953125, 10.6953125, 10.6953125, 3.1001451487799723, "depth"],
        ],
        [
            60,
            "flat",
            "depth",
            0.02,
            11,
            257.609375,
            257.609375,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 22.859375, 22.859375, 22.859375, 8.79668053375506, "depth"],
            ["curb", 10.6953125, 10.6953125, 10.6953125, 2.864789646089632, "depth"],
        ],
        [
            60,
            "flat",
            "ground-contact",
            None,
            11,
            165.90790746262203,
            257.609375,
            8,
            "ground,ground,ground,ground,depth,ground,ground,ground,depth,depth,ground",
            ["pole", 22.859375, 10.472825154230266, 22.859375, 10.472825154230266, "ground"],
            ["curb", 10.6953125, 3.1001451487799723, 10.6953125, 3.1001451487799723, "ground"],
        ],
        [
            60,
            "flat",
            "ground-contact",
            0.02,
            11,
            130.7403572837309,
            257.609375,
            8,
            "ground,ground,ground,ground,depth,ground,ground,ground,depth,depth,ground",
            ["pole", 22.859375, 8.79668053375506, 22.859375, 8.79668053375506, "ground"],
            ["curb", 10.6953125, 2.864789646089632, 10.6953125, 2.864789646089632, "ground"],
        ],
        [
            60,
            "flat",
            "ground+depth",
            None,
            11,
            173.3065191392837,
            257.609375,
            8,
            "fused,fused,fused,fused,depth,fused,fused,fused,depth,depth,fused",
            ["pole", 22.859375, 10.693416981915755, 22.859375, 10.472825154230266, "fused"],
            ["curb", 10.6953125, 3.110202962885752, 10.6953125, 3.1001451487799723, "fused"],
        ],
        [
            60,
            "flat",
            "ground+depth",
            0.02,
            11,
            134.82058154738178,
            257.609375,
            8,
            "fused,fused,fused,fused,depth,fused,fused,fused,depth,depth,fused",
            ["pole", 22.859375, 8.923259675808469, 22.859375, 8.79668053375506, "fused"],
            ["curb", 10.6953125, 2.872644931552028, 10.6953125, 2.864789646089632, "fused"],
        ],
        [
            60,
            "curve",
            "depth",
            None,
            11,
            257.609375,
            257.609375,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 22.859375, 22.859375, 22.859375, 11.520107669653294, "depth"],
            ["curb", 10.6953125, 10.6953125, 10.6953125, 3.4101596636579696, "depth"],
        ],
        [
            60,
            "curve",
            "depth",
            0.02,
            11,
            257.609375,
            257.609375,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 22.859375, 22.859375, 22.859375, 9.676348587130567, "depth"],
            ["curb", 10.6953125, 10.6953125, 10.6953125, 3.1512686106985957, "depth"],
        ],
        [
            60,
            "curve",
            "ground-contact",
            None,
            11,
            178.04401070888423,
            257.609375,
            8,
            "ground,ground,ground,ground,depth,ground,ground,ground,depth,depth,ground",
            ["pole", 22.859375, 11.520107669653294, 22.859375, 11.520107669653294, "ground"],
            ["curb", 10.6953125, 3.4101596636579696, 10.6953125, 3.4101596636579696, "ground"],
        ],
        [
            60,
            "curve",
            "ground-contact",
            0.02,
            11,
            139.35970551210397,
            257.609375,
            8,
            "ground,ground,ground,ground,depth,ground,ground,ground,depth,depth,ground",
            ["pole", 22.859375, 9.676348587130567, 22.859375, 9.676348587130567, "ground"],
            ["curb", 10.6953125, 3.1512686106985957, 10.6953125, 3.1512686106985957, "ground"],
        ],
        [
            60,
            "curve",
            "ground+depth",
            None,
            11,
            219.29652959002928,
            257.609375,
            8,
            "fused,fused,fused,fused,depth,fused,fused,fused,depth,depth,fused",
            ["pole", 22.859375, 11.683106636507237, 22.859375, 11.520107669653294, "fused"],
            ["curb", 10.6953125, 3.4774374993737025, 10.6953125, 3.4101596636579696, "fused"],
        ],
        [
            60,
            "curve",
            "ground+depth",
            0.02,
            11,
            173.82956067833234,
            257.609375,
            8,
            "fused,fused,fused,fused,depth,fused,fused,fused,depth,depth,fused",
            ["pole", 22.859375, 9.762203280600158, 22.859375, 9.676348587130567, "fused"],
            ["curb", 10.6953125, 3.203708600328111, 10.6953125, 3.1512686106985957, "fused"],
        ],
        [
            96,
            "flat",
            "depth",
            None,
            17,
            350.6015625,
            350.6015625,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["sign", 11.671875, 11.671875, 11.671875, None, "depth"],
            ["curb", 8.171875, 8.171875, 8.171875, 1.428192182284309, "depth"],
        ],
        [
            96,
            "flat",
            "depth",
            0.02,
            17,
            350.6015625,
            350.6015625,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["sign", 11.671875, 11.671875, 11.671875, None, "depth"],
            ["curb", 8.171875, 8.171875, 8.171875, 1.343276016341699, "depth"],
        ],
        [
            96,
            "flat",
            "ground-contact",
            None,
            17,
            250.83568836920506,
            350.6015625,
            8,
            "depth,depth,depth,ground,depth,ground,depth,depth,ground,depth,depth,depth,ground,ground,ground,ground,ground",
            ["sign", 11.671875, 11.671875, 11.671875, None, "depth"],
            ["curb", 8.171875, 1.428192182284309, 8.171875, 1.428192182284309, "ground"],
        ],
        [
            96,
            "flat",
            "ground-contact",
            0.02,
            17,
            248.0904586178756,
            350.6015625,
            8,
            "depth,depth,depth,ground,depth,ground,depth,depth,ground,depth,depth,depth,ground,ground,ground,ground,ground",
            ["sign", 11.671875, 11.671875, 11.671875, None, "depth"],
            ["curb", 8.171875, 1.343276016341699, 8.171875, 1.343276016341699, "ground"],
        ],
        [
            96,
            "flat",
            "ground+depth",
            None,
            17,
            250.97419181383438,
            350.6015625,
            8,
            "depth,depth,depth,fused,depth,fused,depth,depth,fused,depth,depth,depth,fused,fused,fused,fused,fused",
            ["sign", 11.671875, 11.671875, 11.671875, None, "depth"],
            ["curb", 8.171875, 1.43006587489499, 8.171875, 1.428192182284309, "fused"],
        ],
        [
            96,
            "flat",
            "ground+depth",
            0.02,
            17,
            248.18478151420453,
            350.6015625,
            8,
            "depth,depth,depth,fused,depth,fused,depth,depth,fused,depth,depth,depth,fused,fused,fused,fused,fused",
            ["sign", 11.671875, 11.671875, 11.671875, None, "depth"],
            ["curb", 8.171875, 1.344901750333748, 8.171875, 1.343276016341699, "fused"],
        ],
        [
            96,
            "curve",
            "depth",
            None,
            17,
            350.6015625,
            350.6015625,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["sign", 11.671875, 11.671875, 11.671875, None, "depth"],
            ["curb", 8.171875, 8.171875, 8.171875, 1.5710114005127402, "depth"],
        ],
        [
            96,
            "curve",
            "depth",
            0.02,
            17,
            350.6015625,
            350.6015625,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["sign", 11.671875, 11.671875, 11.671875, None, "depth"],
            ["curb", 8.171875, 8.171875, 8.171875, 1.4776036179758691, "depth"],
        ],
        [
            96,
            "curve",
            "ground-contact",
            None,
            17,
            253.7766790811255,
            350.6015625,
            8,
            "depth,depth,depth,ground,depth,ground,depth,depth,ground,depth,depth,depth,ground,ground,ground,ground,ground",
            ["sign", 11.671875, 11.671875, 11.671875, None, "depth"],
            ["curb", 8.171875, 1.5710114005127402, 8.171875, 1.5710114005127402, "ground"],
        ],
        [
            96,
            "curve",
            "ground-contact",
            0.02,
            17,
            250.75692635466316,
            350.6015625,
            8,
            "depth,depth,depth,ground,depth,ground,depth,depth,ground,depth,depth,depth,ground,ground,ground,ground,ground",
            ["sign", 11.671875, 11.671875, 11.671875, None, "depth"],
            ["curb", 8.171875, 1.4776036179758691, 8.171875, 1.4776036179758691, "ground"],
        ],
        [
            96,
            "curve",
            "ground+depth",
            None,
            17,
            312.2635202618449,
            350.6015625,
            8,
            "depth,depth,depth,fused,depth,fused,depth,depth,fused,depth,depth,depth,fused,fused,fused,fused,fused",
            ["sign", 11.671875, 14.405159302395347, 11.671875, None, "depth"],
            ["curb", 8.171875, 1.587925412897663, 8.171875, 1.5710114005127402, "fused"],
        ],
        [
            96,
            "curve",
            "ground+depth",
            0.02,
            17,
            309.18344803024553,
            350.6015625,
            8,
            "depth,depth,depth,fused,depth,fused,depth,depth,fused,depth,depth,depth,fused,fused,fused,fused,fused",
            ["sign", 11.671875, 14.405159302395347, 11.671875, None, "depth"],
            ["curb", 8.171875, 1.4922902963715128, 8.171875, 1.4776036179758691, "fused"],
        ],
        [
            132,
            "flat",
            "depth",
            None,
            15,
            324.82421875,
            324.82421875,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 16.828125, 16.828125, 16.828125, 6.6871483398729765, "depth"],
            ["curb", 6.37890625, 6.37890625, 6.37890625, None, "depth"],
        ],
        [
            132,
            "flat",
            "depth",
            0.02,
            15,
            324.82421875,
            324.82421875,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 16.828125, 16.828125, 16.828125, 5.952437361860584, "depth"],
            ["curb", 6.37890625, 6.37890625, 6.37890625, None, "depth"],
        ],
        [
            132,
            "flat",
            "ground-contact",
            None,
            15,
            217.278664299777,
            324.82421875,
            8,
            "ground,ground,depth,depth,depth,depth,depth,ground,ground,ground,ground,ground,depth,ground,depth",
            ["pole", 16.828125, 6.6871483398729765, 16.828125, 6.6871483398729765, "ground"],
            ["curb", 6.37890625, 6.37890625, 6.37890625, None, "depth"],
        ],
        [
            132,
            "flat",
            "ground-contact",
            0.02,
            15,
            196.93841927544406,
            324.82421875,
            8,
            "ground,ground,depth,depth,depth,depth,depth,ground,ground,ground,ground,ground,depth,ground,depth",
            ["pole", 16.828125, 5.952437361860584, 16.828125, 5.952437361860584, "ground"],
            ["curb", 6.37890625, 6.37890625, 6.37890625, None, "depth"],
        ],
        [
            132,
            "flat",
            "ground+depth",
            None,
            15,
            221.8199553967722,
            324.82421875,
            8,
            "fused,fused,depth,depth,depth,depth,depth,fused,fused,fused,fused,fused,depth,fused,depth",
            ["pole", 16.828125, 6.74459857168947, 16.828125, 6.6871483398729765, "fused"],
            ["curb", 6.37890625, 6.37890625, 6.37890625, None, "depth"],
        ],
        [
            132,
            "flat",
            "ground+depth",
            0.02,
            15,
            199.06689529023757,
            324.82421875,
            8,
            "fused,fused,depth,depth,depth,depth,depth,fused,fused,fused,fused,fused,depth,fused,depth",
            ["pole", 16.828125, 5.991716558257915, 16.828125, 5.952437361860584, "fused"],
            ["curb", 6.37890625, 6.37890625, 6.37890625, None, "depth"],
        ],
        [
            132,
            "curve",
            "depth",
            None,
            15,
            324.82421875,
            324.82421875,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 16.828125, 16.828125, 16.828125, 7.355863173860275, "depth"],
            ["curb", 6.37890625, 6.37890625, 6.37890625, None, "depth"],
        ],
        [
            132,
            "curve",
            "depth",
            0.02,
            15,
            324.82421875,
            324.82421875,
            8,
            "depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth,depth",
            ["pole", 16.828125, 16.828125, 16.828125, 6.547681098046643, "depth"],
            ["curb", 6.37890625, 6.37890625, 6.37890625, None, "depth"],
        ],
        [
            132,
            "curve",
            "ground-contact",
            None,
            15,
            226.02879635475475,
            324.82421875,
            8,
            "ground,ground,depth,depth,depth,depth,depth,ground,ground,ground,ground,ground,depth,ground,depth",
            ["pole", 16.828125, 7.355863173860275, 16.828125, 7.355863173860275, "ground"],
            ["curb", 6.37890625, 6.37890625, 6.37890625, None, "depth"],
        ],
        [
            132,
            "curve",
            "ground-contact",
            0.02,
            15,
            203.65452682798843,
            324.82421875,
            8,
            "ground,ground,depth,depth,depth,depth,depth,ground,ground,ground,ground,ground,depth,ground,depth",
            ["pole", 16.828125, 6.547681098046643, 16.828125, 6.547681098046643, "ground"],
            ["curb", 6.37890625, 6.37890625, 6.37890625, None, "depth"],
        ],
        [
            132,
            "curve",
            "ground+depth",
            None,
            15,
            301.57255792472483,
            324.82421875,
            8,
            "fused,fused,depth,depth,depth,depth,depth,fused,fused,fused,fused,fused,depth,fused,depth",
            ["pole", 16.828125, 7.410480127774444, 16.828125, 7.355863173860275, "fused"],
            ["curb", 6.37890625, 6.63402744101091, 6.37890625, None, "depth"],
        ],
        [
            132,
            "curve",
            "ground+depth",
            0.02,
            15,
            275.85695548666143,
            324.82421875,
            8,
            "fused,fused,depth,depth,depth,depth,depth,fused,fused,fused,fused,fused,depth,fused,depth",
            ["pole", 16.828125, 6.583193266962799, 16.828125, 6.547681098046643, "fused"],
            ["curb", 6.37890625, 6.63402744101091, 6.37890625, None, "depth"],
        ],
    ],
    "detail": [
        ["pole", 8.7265625, 3.6390334507476845, 8.7265625, 3.5703720721408336, "fused"],
        ["sign", 5.21484375, 5.4434149391698945, 5.21484375, 5.479174328319368, "fused"],
        ["nature vegetation", 15.9609375, 7.418423380179148, 15.9609375, 7.296121095898106, "fused"],
        ["nature vegetation", 9.234375, 10.295696560251011, 9.234375, None, "depth"],
        ["nature vegetation", 32.625, 45.0, 32.625, None, "depth"],
        ["building", 35.09375, 41.870341561501746, 35.09375, 36.3008004070139, "fused"],
        ["building", 5.24609375, 5.399936553658836, 5.24609375, None, "depth"],
        ["person", 16.046875, 7.463042503822052, 16.046875, 7.360444346098771, "fused"],
        ["person", 17.5625, 7.734522407682792, 17.5625, 7.696691085560833, "fused"],
        ["person", 16.984375, 7.746393594376068, 16.984375, 7.690149525201572, "fused"],
        ["curb", 23.046875, 8.885749984744026, 23.046875, 8.732967291841177, "fused"],
        ["curb", 16.140625, 7.148494830833076, 16.140625, 7.043047163020075, "fused"],
        ["curb", 9.49609375, 2.7220633732188553, 9.49609375, 2.6692847663489827, "fused"],
    ],
    "edge": {
        "clipped": [6.219774182144074, 6.0, None, "depth"],
        "noBase": [6.219774182144074, 6.0, None, "depth"],
        "lastRow": [6.219774182144074, 6.0, None, "depth"],
        "horizonAbove": [6.219774182144074, 6.0, None, "depth"],
    },
}

EXP_ATTRS: Any = {
    "DepthAnchor": ["min_cells", "tau_s", "hold_s", "log_a", "last_t"],
    "InitialAnchor": ["min_cells", "n_freeze", "n_min", "ratios", "frozen", "_run"],
    "PlaneAnchor": ["camera_height_m", "n_freeze", "n_min", "scales", "pitches", "heights", "frozen", "fit"],
    "DepthScale": [
        "window_s",
        "min_samples",
        "tau_min_s",
        "tau_s",
        "max_rate",
        "lo",
        "hi",
        "max_bearing",
        "min_speed",
        "freeze",
        "age_s",
        "samples",
        "target",
        "applied",
    ],
}

EXP_PROPERTIES: Any = {
    "DepthAnchor": ["value"],
    "InitialAnchor": ["value"],
    "PlaneAnchor": ["height_units", "pitch_deg", "value"],
    "DepthScale": ["holding", "value"],
}

EXP_CONFIG: Any = {
    "DepthAnchor": [150, 0.4, 2.0, None, -math.inf],
    "InitialAnchor": [150, 6, 3],
    "PlaneAnchor": [1.3, 6, 3],
    "DepthScale": [20.0, 30, 3.0, 40.0, 0.25, 0.3, 5.0, 40.0, 0.5],
}

EXP_ANCHOR_NAMES: list[str] = ["DepthAnchor", "InitialAnchor", "ground_anchor", "PlaneFit", "plane_fit", "PlaneAnchor"]
