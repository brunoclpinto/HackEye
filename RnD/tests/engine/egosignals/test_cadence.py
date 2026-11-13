"""Characterisation tests for engine.egosignals.cadence (v26.3.0 p2-01).

Every expected literal was produced by running the legacy code (collision.py) in the hackeye-rnd image on the
pre-move code, not computed by hand. The collision config is read straight from common/config/collision.json
(not through collision.load_config, which the test conftest patches). The real-data case replays the vertical
acceleration of the device sensors in tests/fixtures/chest0004_review9.npz the way collision._sensor_series does.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

import collision
import sensors as sensor_lib
from common_paths import find_common_dir

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "chest0004_review9.npz"
APPROX: dict[str, Any] = {"rel": 1e-12, "abs": 1e-12, "nan_ok": True}
FLOATS = npt.NDArray[np.float64]
BAND = (0.8, 3.5)
LOBE = 10


def _ego() -> dict[str, Any]:
    cfg: dict[str, Any] = json.loads((find_common_dir() / "config" / "collision.json").read_text())
    ego: dict[str, Any] = cfg["ego"]
    return ego


def _arr(prefix: str, a: FLOATS) -> dict[str, float]:
    """Compact digest of a float array: size, nan count, sum, extremes, first/last valid, three quartile samples."""
    a = np.asarray(a, dtype=float)
    n = len(a)
    ok = a[~np.isnan(a)]
    out: dict[str, float] = {
        f"{prefix}_n": n,
        f"{prefix}_nan": int(np.isnan(a).sum()),
        f"{prefix}_sum": float(np.nansum(a)),
    }
    out[f"{prefix}_min"] = float(ok.min()) if len(ok) else math.nan
    out[f"{prefix}_max"] = float(ok.max()) if len(ok) else math.nan
    out[f"{prefix}_first"] = float(ok[0]) if len(ok) else math.nan
    out[f"{prefix}_last"] = float(ok[-1]) if len(ok) else math.nan
    for name, i in (("q1", n // 4), ("q2", n // 2), ("q3", 3 * n // 4)):
        out[f"{prefix}_{name}"] = float(a[i]) if n else math.nan
    return out


def _edges(prefix: str, a: npt.NDArray[np.bool_]) -> dict[str, float]:
    """Digest of a boolean series: size, true count and the indices where it changes."""
    idx = np.flatnonzero(np.diff(a.astype(int)) != 0)
    out: dict[str, float] = {f"{prefix}_n": len(a), f"{prefix}_true": int(a.sum()), f"{prefix}_edges": len(idx)}
    for j, i in enumerate(idx):
        out[f"{prefix}_e{j}"] = int(i)
    return out


def _sine(f: float, fs: float, seconds: float = 8.0, noise: float = 0.1, seed: int = 0) -> tuple[FLOATS, float]:
    t = np.arange(0, seconds, 1 / fs)
    rng = np.random.default_rng(seed)
    return np.sin(2 * math.pi * f * t) + noise * rng.standard_normal(len(t)), 1 / fs


def _walk_stand_walk() -> tuple[FLOATS, FLOATS, FLOATS, FLOATS]:
    """60 s at 24 fps: walking 1.8 Hz (0-20 s), standing (20-40 s), walking 2.0 Hz (40-60 s); (t, dy, dx, resid)."""
    t = np.arange(0, 60, 1 / 24)
    rng = np.random.default_rng(0)
    walk1 = t < 20
    walk2 = t >= 40
    dy = 0.003 * rng.standard_normal(len(t))
    dx = 0.002 * rng.standard_normal(len(t))
    dy = (
        dy
        + np.where(walk1, 0.01 * np.sin(2 * math.pi * 1.8 * t), 0.0)
        + np.where(walk2, 0.01 * np.sin(2 * math.pi * 2.0 * t), 0.0)
    )
    dx = (
        dx
        + np.where(walk1, 0.006 * np.sin(math.pi * 1.8 * t), 0.0)
        + np.where(walk2, 0.006 * np.sin(math.pi * 2.0 * t), 0.0)
    )
    resid = np.where(walk1 | walk2, 2.7, 0.12) + 0.05 * np.abs(rng.standard_normal(len(t)))
    return np.asarray(t, dtype=np.float64), dy, dx, resid


def _stride_signal() -> tuple[FLOATS, FLOATS, FLOATS]:
    """30 s at 24 fps: stride 1.05 Hz with a 2.1 Hz second harmonic; (t, signal, dx swaying at the stride)."""
    t = np.arange(0, 30, 1 / 24)
    rng = np.random.default_rng(1)
    sig = np.sin(2 * math.pi * 1.05 * t) + 0.4 * np.sin(2 * math.pi * 2.1 * t) + 0.15 * rng.standard_normal(len(t))
    dx = np.sin(2 * math.pi * 1.05 * t + 1.0) + 0.1 * rng.standard_normal(len(t))
    return np.asarray(t, dtype=np.float64), sig, dx


def _fixture_vertical() -> tuple[FLOATS, FLOATS, FLOATS]:
    """(t, vertical, side) acceleration at 60 Hz over the first 60 s of the fixture, as _sensor_series builds them."""
    z = np.load(FIXTURE)
    sens = {k[len("sensors_") :]: z[k] for k in z.files if k.startswith("sensors_")}
    mt = np.asarray(z["w0_mt"], dtype=float)
    s = sensor_lib.crop(sens, float(mt[0]) - 6.0, float(mt[0]) + 60.0)
    vt, vert, side = sensor_lib.vertical_signals(s, float(_ego()["imu"]["cadenceRateHz"]))
    return vt, vert, side


def _cad(m: Any, t: FLOATS, dy: FLOATS, dx: FLOATS | None = None) -> FLOATS:
    e = _ego()
    out: FLOATS = m.estimate_cadence(
        t,
        dy,
        e["cadenceWindowSeconds"],
        e["cadenceBandHz"],
        e["cadenceMinPeakRatio"],
        dx=dx,
        min_step_hz=e["minStepHz"],
        harmonic_ratio=e["harmonicMinRatio"],
    )
    return out


# --- cases (shared by the scratch generator, which feeds the legacy names through the same functions) ---


def case_spectrum(m: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for f in (1.6, 1.9, 2.2):
        for fs in (30, 60):
            seg, dt = _sine(f, fs)
            freqs, power = m.spectrum(seg, dt)
            k = int(np.argmax(power))
            tag = f"s{f}_{fs}"
            out.update(
                {
                    f"{tag}_nf": len(freqs),
                    f"{tag}_df": float(freqs[1]),
                    f"{tag}_fmax": float(freqs[-1]),
                    f"{tag}_k": k,
                    f"{tag}_pmax": float(power[k]),
                    f"{tag}_psum": float(power.sum()),
                    f"{tag}_p0": float(power[0]),
                }
            )
            f2, p2 = m.spectrum(seg, dt, 2)
            out.update(
                {f"{tag}_pad2_nf": len(f2), f"{tag}_pad2_k": int(np.argmax(p2)), f"{tag}_pad2_pmax": float(p2.max())}
            )
    return out


def case_peak_refine(m: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for f in (1.6, 1.9, 2.2):
        for fs in (30, 60):
            seg, dt = _sine(f, fs)
            freqs, power = m.spectrum(seg, dt)
            tag = f"s{f}_{fs}"
            found = m.peak(freqs, power, BAND[0], BAND[1], LOBE)
            assert found is not None
            k, ratio = found
            out.update(
                {
                    f"{tag}_k": k,
                    f"{tag}_ratio": ratio,
                    f"{tag}_ref": m.refine(freqs, power, k),
                    f"{tag}_ref_band": m.refine(freqs, power, k, BAND[0], BAND[1]),
                }
            )
            # narrow band that excludes the sinusoid: another (weaker) peak or none
            other = m.peak(freqs, power, 3.0, 3.5, LOBE)
            out[f"{tag}_other_none"] = float(other is None)
            if other is not None:
                out[f"{tag}_other_k"] = other[0]
                out[f"{tag}_other_ratio"] = other[1]
    return out


def case_refine_edges(m: Any) -> dict[str, float]:
    freqs = np.arange(0, 6.0, 0.1)
    out: dict[str, float] = {}
    power = np.zeros_like(freqs)
    power[34], power[35], power[36] = 10.0, 5.01, 0.0  # far extrapolation at the band edge
    out["reject_none"] = m.refine(freqs, power, 35)
    out["reject_band"] = m.refine(freqs, power, 35, 0.8, 3.5)
    power = np.zeros_like(freqs)
    power[19], power[20], power[21] = 1.0, 4.0, 3.0
    out["ordinary"] = m.refine(freqs, power, 20, 0.8, 3.5)
    out["ordinary_noband"] = m.refine(freqs, power, 20)
    power[:] = 0.0
    power[19], power[20], power[21] = 3.0, 4.0, 1.0
    out["ordinary_left"] = m.refine(freqs, power, 20, 0.8, 3.5)
    out["edge_k0"] = m.refine(freqs, power, 0)
    out["edge_klast"] = m.refine(freqs, power, len(freqs) - 1)
    power[:] = 1.0  # denom == 0: no refine
    out["flat"] = m.refine(freqs, power, 20)
    power[:] = 0.0
    power[19], power[20], power[21] = 1.0, 0.0, 1.0  # denom > 0: a valley, no refine
    out["valley"] = m.refine(freqs, power, 20)
    power[:] = 0.0
    power[7], power[8], power[9] = 3.0, 4.0, 1.0  # candidate 0.8 - eps stays inside lo - df
    out["near_lo"] = m.refine(freqs, power, 8, 0.8, 3.5)
    power[:] = 0.0
    power[3], power[4], power[5] = 3.4, 4.0, 0.2  # interpolated shift leaves lo by more than a bin
    out["below_lo"] = m.refine(freqs, power, 4, 1.0, 3.5)
    out["type_is_float"] = float(type(m.refine(freqs, power, 4)) is float)
    return out


def case_peak_edges(m: Any) -> dict[str, float]:
    freqs = np.arange(0, 6.0, 0.1)
    out: dict[str, float] = {}
    power = np.ones_like(freqs)
    power[20] = 50.0
    r = m.peak(freqs, power, 0.8, 3.5, 3)
    out["basic_k"], out["basic_ratio"] = r
    out["empty_band_none"] = float(m.peak(freqs, power, 7.0, 8.0, 3) is None)
    few = np.arange(0, 0.5, 0.1)  # fewer than 4 bins at >= 0.25 Hz outside the lobe
    out["few_rest_none"] = float(m.peak(few, np.ones_like(few), 0.0, 0.5, 1) is None)
    zero = np.zeros_like(freqs)
    zero[20] = 5.0
    out["zero_rest_none"] = float(m.peak(freqs, zero, 0.8, 3.5, 3) is None)
    tie = np.ones_like(freqs)
    tie[15] = tie[25] = 9.0
    out["tie_k"] = m.peak(freqs, tie, 0.8, 3.5, 3)[0]  # first of equal maxima
    low = np.ones_like(freqs)
    low[1] = 100.0  # below 0.25 Hz: not part of the rest
    low[30] = 4.0
    out["lowfreq_k"], out["lowfreq_ratio"] = m.peak(freqs, low, 0.8, 3.5, 3)
    out["lobe0_ratio"] = m.peak(freqs, power, 0.8, 3.5, 0)[1]
    return out


def case_window_cadence(m: Any) -> dict[str, float]:
    e = _ego()
    ratio = float(e["cadenceMinPeakRatio"])
    out: dict[str, float] = {}
    for f in (1.6, 1.9, 2.2):
        for fs in (30, 60):
            seg, dt = _sine(f, fs)
            tag = f"s{f}_{fs}"
            out[tag] = m.window_cadence(seg, dt, BAND, ratio)
            out[f"{tag}_strict"] = m.window_cadence(seg, dt, BAND, 1e6)
            out[f"{tag}_noisy"] = m.window_cadence(_sine(f, fs, noise=2.0)[0], dt, BAND, ratio)
            dx, _ = _sine(f / 2, fs, seed=5)
            out[f"{tag}_dx_half"] = m.window_cadence(seg, dt, BAND, ratio, dx)
            out[f"{tag}_dx_same"] = m.window_cadence(seg, dt, BAND, ratio, _sine(f, fs, seed=6)[0])
            out[f"{tag}_dx_len"] = m.window_cadence(seg, dt, BAND, ratio, dx[:-1])
    _t, sig, dx = _stride_signal()
    seg, sdx = sig[:96], dx[:96]  # a 4 s window
    for name, kwargs in (
        ("plain", {}),
        ("dx", {"seg_dx": sdx}),
        ("minstep", {"min_step_hz": 1.0}),
        ("harm", {"harmonic_ratio": 0.9}),
        ("harm_dx", {"seg_dx": sdx, "harmonic_ratio": 0.9}),
        ("harm_lo", {"harmonic_ratio": 0.001}),
    ):
        out[f"stride_{name}"] = m.window_cadence(seg, 1 / 24, BAND, 3.0, **kwargs)
    out["stride_weak_dx"] = m.window_cadence(seg, 1 / 24, BAND, 8.0, sdx)
    out["stride_weak_nodx"] = m.window_cadence(seg, 1 / 24, BAND, 8.0)
    out["stride_hi_band"] = m.window_cadence(seg, 1 / 24, (0.8, 2.0), 3.0)
    out["stride_nopeak"] = m.window_cadence(np.zeros(96), 1 / 24, BAND, 3.0)
    out["stride_empty_band"] = m.window_cadence(seg, 1 / 24, (50.0, 60.0), 3.0)
    return out


def case_corroborated(m: Any) -> dict[str, float]:
    return {"frac": m.CORROBORATED_RATIO_FRAC}


def case_estimate_cadence(m: Any) -> dict[str, float]:
    t, dy, dx, _ = _walk_stand_walk()
    out: dict[str, float] = {}
    out.update(_arr("dy", _cad(m, t, dy)))
    out.update(_arr("dydx", _cad(m, t, dy, dx)))
    first = _cad(m, t, dy, dx)
    out["walk1_median"] = float(np.nanmedian(first[(t > 6) & (t < 20)]))
    out["stand_nan"] = float(np.isnan(first[(t > 28) & (t < 40)]).mean())
    out["walk2_median"] = float(np.nanmedian(first[t > 46]))
    s, sig, sdx = _stride_signal()
    out.update(_arr("stride", _cad(m, s, sig)))
    out.update(_arr("stride_dx", _cad(m, s, sig, sdx)))
    e = _ego()
    win2 = m.estimate_cadence(t, dy, 2.0, (0.8, 3.5), 3.0, dx=dx, min_step_hz=1.0, harmonic_ratio=0.5)
    out.update(_arr("win2", np.asarray(win2)))
    listed = m.estimate_cadence(list(t), list(dy), e["cadenceWindowSeconds"], e["cadenceBandHz"], 3.0)
    out.update(_arr("list_in", np.asarray(listed)))
    # degenerate inputs
    out.update(_arr("short", m.estimate_cadence(t[:7], dy[:7], 4.0, BAND, 3.0)))
    out.update(_arr("flat_t", m.estimate_cadence(np.zeros(50), dy[:50], 4.0, BAND, 3.0)))
    out.update(_arr("back_t", m.estimate_cadence(t[:50][::-1], dy[:50], 4.0, BAND, 3.0)))
    out.update(_arr("tiny_window", m.estimate_cadence(t[:100], dy[:100], 0.1, BAND, 3.0)))
    out.update(_arr("nonuniform", m.estimate_cadence(t[::2] + 0.001 * np.sin(t[::2]), dy[::2], 4.0, BAND, 3.0)))
    return out


def case_estimate_cadence_fixture(m: Any) -> dict[str, float]:
    vt, vert, side = _fixture_vertical()
    out: dict[str, float] = {"nvt": len(vt)}
    out.update(_arr("vert", vert))
    out.update(_arr("side", side))
    out.update(_arr("cad", _cad(m, vt, vert, side)))
    out.update(_arr("cad_nodx", _cad(m, vt, vert)))
    return out


def case_hold_last(m: Any) -> dict[str, float]:
    nan = math.nan
    t = np.arange(10, dtype=float)
    out: dict[str, float] = {}

    def run(name: str, series: list[float], hold: float, tt: FLOATS = t) -> None:
        series_a = np.array(series, dtype=float)
        before = series_a.copy()
        res: FLOATS = m.hold_last(tt[: len(series_a)], series_a, hold)
        out[f"{name}_len"] = len(res)
        for i, v in enumerate(res):
            out[f"{name}_{i}"] = float(v)
        out[f"{name}_input_unchanged"] = float(np.array_equal(before, series_a, equal_nan=True))
        out[f"{name}_is_copy"] = float(res is not series_a)

    run("expire", [1, nan, nan, nan, nan, 2, nan], 2.0)
    run("exact", [5, nan, nan, nan], 2.0)  # t - last_t == hold_s is still held
    run("lead_nan", [nan, nan, 3, nan, nan, nan], 1.0)  # nothing to hold before the first value
    run("all_nan", [nan, nan, nan], 5.0)
    run("no_nan", [1, 2, 3, 4], 5.0)
    run("zero_hold", [1, nan, 2, nan], 0.0)
    run("neg_hold", [1, nan, 2, nan], -1.0)
    run("empty", [], 1.0)
    run("single", [7], 1.0)
    run("irregular", [1, nan, nan, nan, 4, nan], 1.5, np.array([0.0, 0.5, 1.4, 1.6, 3.0, 4.4, 9.0]))
    return out


def case_estimate_stationary(m: Any) -> dict[str, float]:
    e = _ego()
    t, _, _, resid = _walk_stand_walk()
    out: dict[str, float] = {}
    out.update(_edges("cfg", m.estimate_stationary(t, resid, e["stationary"])))
    out.update(
        _edges(
            "imu",
            m.estimate_stationary(
                t,
                resid,
                {"medianSeconds": 0.3, "enterPx": 0.5, "leavePx": 0.8, "enterSeconds": 1.5, "leaveSeconds": 1.0},
            ),
        )
    )
    out.update(_edges("empty_cfg", m.estimate_stationary(t, resid, {})))
    out.update(_edges("list_in", m.estimate_stationary(list(t), list(resid), e["stationary"])))
    out.update(_edges("slow", m.estimate_stationary(t, resid, {"enterSeconds": 6.0, "leaveSeconds": 4.0})))
    out.update(_edges("high_enter", m.estimate_stationary(t, resid, {"enterPx": 5.0, "leavePx": 6.0})))
    rn = resid.copy()
    # texture-less frames: never enter, count as walking when leaving
    rn[(t > 25) & (t < 31)] = math.nan
    out.update(_edges("nan_standing", m.estimate_stationary(t, rn, e["stationary"])))
    rn2 = resid.copy()
    rn2[(t > 8) & (t < 12)] = math.nan
    out.update(_edges("nan_walking", m.estimate_stationary(t, rn2, e["stationary"])))
    out.update(_edges("all_nan", m.estimate_stationary(t, np.full(len(t), math.nan), e["stationary"])))
    out.update(_edges("short", m.estimate_stationary(t[:1], resid[:1], e["stationary"])))
    out.update(_edges("empty", m.estimate_stationary(t[:0], resid[:0], e["stationary"])))
    out.update(_edges("flat_t", m.estimate_stationary(np.zeros(30), resid[:30], e["stationary"])))
    out.update(_edges("quiet", m.estimate_stationary(t, np.full(len(t), 0.1), e["stationary"])))
    return out


def case_stationary_fixture(m: Any) -> dict[str, float]:
    """Stationary flag from the fixture's accelerometer + gyro activity on a 10 Hz grid over 60-150 s
    (a standing stretch included), as _sensor_series does."""
    z = np.load(FIXTURE)
    sens = {k[len("sensors_") :]: z[k] for k in z.files if k.startswith("sensors_")}
    mt = np.asarray(z["w0_mt"], dtype=float)
    s = sensor_lib.crop(sens, float(mt[0]) + 54.0, float(mt[0]) + 156.0)
    icfg = _ego()["imu"]
    et, en = sensor_lib.motion_energy(s, float(icfg["activityWindowS"]))
    tu = np.arange(mt[0] + 60.0, mt[0] + 150.0, 0.1)
    out: dict[str, float] = {}
    out.update(_arr("energy", np.interp(tu, et, en)))
    out.update(_edges("stat", m.estimate_stationary(tu, np.interp(tu, et, en), icfg["stationary"])))
    return out


# --- tests ---


def test_facade_identity() -> None:
    from engine.egosignals import cadence

    assert collision._spectrum is cadence.spectrum
    assert collision._refine is cadence.refine
    assert collision._peak is cadence.peak
    assert collision.CORROBORATED_RATIO_FRAC is cadence.CORROBORATED_RATIO_FRAC
    assert collision._window_cadence is cadence.window_cadence
    assert collision.estimate_cadence is cadence.estimate_cadence
    assert collision._hold_last is cadence.hold_last
    assert collision.estimate_stationary is cadence.estimate_stationary


def test_package_reexports_public_api() -> None:
    import engine.egosignals as pkg
    from engine.egosignals import cadence

    names = (
        "spectrum",
        "refine",
        "peak",
        "CORROBORATED_RATIO_FRAC",
        "window_cadence",
        "estimate_cadence",
        "hold_last",
        "estimate_stationary",
    )
    for name in names:
        if name in pkg.__all__:
            assert getattr(pkg, name) is getattr(cadence, name)
    assert "estimate_cadence" in pkg.__all__
    assert "estimate_stationary" in pkg.__all__


def test_corroborated_ratio_frac() -> None:
    from engine.egosignals import cadence

    assert case_corroborated(cadence) == pytest.approx({"frac": 0.7}, **APPROX)


def test_spectrum_on_sinusoids() -> None:
    from engine.egosignals import cadence

    assert case_spectrum(cadence) == pytest.approx(
        {
            "s1.6_30_nf": 481,
            "s1.6_30_df": 0.03125,
            "s1.6_30_fmax": 15.0,
            "s1.6_30_k": 51,
            "s1.6_30_pmax": 3680.0664117363035,
            "s1.6_30_psum": 22878.214927727615,
            "s1.6_30_p0": 0.7402271292646074,
            "s1.6_30_pad2_nf": 241,
            "s1.6_30_pad2_k": 26,
            "s1.6_30_pad2_pmax": 3532.9903520833286,
            "s1.6_60_nf": 961,
            "s1.6_60_df": 0.03125,
            "s1.6_60_fmax": 30.0,
            "s1.6_60_k": 51,
            "s1.6_60_pmax": 13958.164340500825,
            "s1.6_60_psum": 85629.16705002556,
            "s1.6_60_p0": 12.399993969452163,
            "s1.6_60_pad2_nf": 481,
            "s1.6_60_pad2_k": 26,
            "s1.6_60_pad2_pmax": 13307.094469020576,
            "s1.9_30_nf": 481,
            "s1.9_30_df": 0.03125,
            "s1.9_30_fmax": 15.0,
            "s1.9_30_k": 61,
            "s1.9_30_pmax": 3497.125441256767,
            "s1.9_30_psum": 21555.35593847502,
            "s1.9_30_p0": 0.046383534900757244,
            "s1.9_30_pad2_nf": 241,
            "s1.9_30_pad2_k": 30,
            "s1.9_30_pad2_pmax": 3349.925393387877,
            "s1.9_60_nf": 961,
            "s1.9_60_df": 0.03125,
            "s1.9_60_fmax": 30.0,
            "s1.9_60_k": 61,
            "s1.9_60_pmax": 14230.018970565856,
            "s1.9_60_psum": 87571.05590364536,
            "s1.9_60_p0": 7.348926801961428,
            "s1.9_60_pad2_nf": 481,
            "s1.9_60_pad2_k": 30,
            "s1.9_60_pad2_pmax": 13520.271684188723,
            "s2.2_30_nf": 481,
            "s2.2_30_df": 0.03125,
            "s2.2_30_fmax": 15.0,
            "s2.2_30_k": 70,
            "s2.2_30_pmax": 3425.356239961283,
            "s2.2_30_psum": 21201.318261995777,
            "s2.2_30_p0": 2.79094516287624,
            "s2.2_30_pad2_nf": 241,
            "s2.2_30_pad2_k": 35,
            "s2.2_30_pad2_pmax": 3425.356239961283,
            "s2.2_60_nf": 961,
            "s2.2_60_df": 0.03125,
            "s2.2_60_fmax": 30.0,
            "s2.2_60_k": 70,
            "s2.2_60_pmax": 14383.415355593208,
            "s2.2_60_psum": 89686.30766225341,
            "s2.2_60_p0": 27.83905156137245,
            "s2.2_60_pad2_nf": 481,
            "s2.2_60_pad2_k": 35,
            "s2.2_60_pad2_pmax": 14383.415355593212,
        },
        **APPROX,
    )


def test_peak_and_refine_on_sinusoids() -> None:
    from engine.egosignals import cadence

    assert case_peak_refine(cadence) == pytest.approx(
        {
            "s1.6_30_k": 51,
            "s1.6_30_ratio": 66.56790486283367,
            "s1.6_30_ref": 1.601127617524891,
            "s1.6_30_ref_band": 1.601127617524891,
            "s1.6_30_other_none": 0.0,
            "s1.6_30_other_k": 100,
            "s1.6_30_other_ratio": 0.06886925109594165,
            "s1.6_60_k": 51,
            "s1.6_60_ratio": 83.55800208835446,
            "s1.6_60_ref": 1.6000119903588865,
            "s1.6_60_ref_band": 1.6000119903588865,
            "s1.6_60_other_none": 0.0,
            "s1.6_60_other_k": 106,
            "s1.6_60_other_ratio": 0.20435831551323833,
            "s1.9_30_k": 61,
            "s1.9_30_ratio": 64.88801694726239,
            "s1.9_30_ref": 1.8991845220747738,
            "s1.9_30_ref_band": 1.8991845220747738,
            "s1.9_30_other_none": 0.0,
            "s1.9_30_other_k": 100,
            "s1.9_30_other_ratio": 0.07075353593093506,
            "s1.9_60_k": 61,
            "s1.9_60_ratio": 83.82361237228457,
            "s1.9_60_ref": 1.9007087588356646,
            "s1.9_60_ref_band": 1.9007087588356646,
            "s1.9_60_other_none": 0.0,
            "s1.9_60_other_k": 105,
            "s1.9_60_other_ratio": 0.20311364659706138,
            "s2.2_30_k": 70,
            "s2.2_30_ratio": 63.215749554408795,
            "s2.2_30_ref": 2.200454714170602,
            "s2.2_30_ref_band": 2.200454714170602,
            "s2.2_30_other_none": 0.0,
            "s2.2_30_other_k": 100,
            "s2.2_30_other_ratio": 0.07732919509995373,
            "s2.2_60_k": 70,
            "s2.2_60_ratio": 84.75885195866599,
            "s2.2_60_ref": 2.199675378279839,
            "s2.2_60_ref_band": 2.199675378279839,
            "s2.2_60_other_none": 0.0,
            "s2.2_60_other_k": 106,
            "s2.2_60_other_ratio": 0.20036050112145662,
        },
        **APPROX,
    )


def test_refine_edge_cases() -> None:
    from engine.egosignals import cadence

    assert case_refine_edges(cadence) == pytest.approx(
        {
            "reject_none": 3.5,
            "reject_band": 3.5,
            "ordinary": 2.025,
            "ordinary_noband": 2.025,
            "ordinary_left": 1.975,
            "edge_k0": 0.0,
            "edge_klast": 5.9,
            "flat": 2.0,
            "valley": 2.0,
            "near_lo": 0.775,
            "below_lo": 0.4,
            "type_is_float": 0.0,
        },
        **APPROX,
    )


def test_peak_edge_cases() -> None:
    from engine.egosignals import cadence

    assert case_peak_edges(cadence) == pytest.approx(
        {
            "basic_k": 20,
            "basic_ratio": 7.0710678118654755,
            "empty_band_none": 1.0,
            "few_rest_none": 1.0,
            "zero_rest_none": 1.0,
            "tie_k": 15,
            "lowfreq_k": 30,
            "lowfreq_ratio": 2.0,
            "lobe0_ratio": 7.0710678118654755,
        },
        **APPROX,
    )


def test_window_cadence() -> None:
    from engine.egosignals import cadence

    assert case_window_cadence(cadence) == pytest.approx(
        {
            "s1.6_30": 1.601127617524891,
            "s1.6_30_strict": math.nan,
            "s1.6_30_noisy": 1.6229048101535495,
            "s1.6_30_dx_half": 1.601127617524891,
            "s1.6_30_dx_same": 3.1216140762087314,
            "s1.6_30_dx_len": 1.601127617524891,
            "s1.6_60": 1.6000119903588865,
            "s1.6_60_strict": math.nan,
            "s1.6_60_noisy": 1.6037922404001252,
            "s1.6_60_dx_half": 1.6000119903588865,
            "s1.6_60_dx_same": 3.296964454193343,
            "s1.6_60_dx_len": 1.6000119903588865,
            "s1.9_30": 1.8991845220747738,
            "s1.9_30_strict": math.nan,
            "s1.9_30_noisy": 1.8702484901940708,
            "s1.9_30_dx_half": 1.8991845220747738,
            "s1.9_30_dx_same": 1.8991845220747738,
            "s1.9_30_dx_len": 1.8991845220747738,
            "s1.9_60": 1.9007087588356646,
            "s1.9_60_strict": math.nan,
            "s1.9_60_noisy": 1.910187994481456,
            "s1.9_60_dx_half": 1.9007087588356646,
            "s1.9_60_dx_same": 1.9007087588356646,
            "s1.9_60_dx_len": 1.9007087588356646,
            "s2.2_30": 2.200454714170602,
            "s2.2_30_strict": math.nan,
            "s2.2_30_noisy": math.nan,
            "s2.2_30_dx_half": 2.200454714170602,
            "s2.2_30_dx_same": 2.200454714170602,
            "s2.2_30_dx_len": 2.200454714170602,
            "s2.2_60": 2.199675378279839,
            "s2.2_60_strict": math.nan,
            "s2.2_60_noisy": 2.202993119883024,
            "s2.2_60_dx_half": 2.199675378279839,
            "s2.2_60_dx_same": 2.199675378279839,
            "s2.2_60_dx_len": 2.199675378279839,
            "stride_plain": 2.089874961496335,
            "stride_dx": 2.089874961496335,
            "stride_minstep": 1.0574312691003567,
            "stride_harm": 2.089874961496335,
            "stride_harm_dx": 2.089874961496335,
            "stride_harm_lo": 2.089874961496335,
            "stride_weak_dx": 2.089874961496335,
            "stride_weak_nodx": 2.089874961496335,
            "stride_hi_band": 1.0574312691003567,
            "stride_nopeak": math.nan,
            "stride_empty_band": math.nan,
        },
        **APPROX,
    )


def test_estimate_cadence_walk_stand_walk() -> None:
    from engine.egosignals import cadence

    assert case_estimate_cadence(cadence) == pytest.approx(
        {
            "dy_n": 1440,
            "dy_nan": 290,
            "dy_sum": 2131.052354578689,
            "dy_min": 1.5438071577792443,
            "dy_max": 3.0625000000000435,
            "dy_first": 1.8256678953403778,
            "dy_last": 2.0082503266454124,
            "dy_q1": 1.796666638036569,
            "dy_q2": 1.5438071577792443,
            "dy_q3": 1.9875834128675756,
            "dydx_n": 1440,
            "dydx_nan": 280,
            "dydx_sum": 2292.0918327974728,
            "dydx_min": 1.5438071577792443,
            "dydx_max": 3.0625000000000435,
            "dydx_first": 1.8256678953403778,
            "dydx_last": 2.0082503266454124,
            "dydx_q1": 1.796666638036569,
            "dydx_q2": 1.5438071577792443,
            "dydx_q3": 1.9875834128675756,
            "walk1_median": 1.7992633906040703,
            "stand_nan": 0.6062717770034843,
            "walk2_median": 2.0033400967098847,
            "stride_n": 720,
            "stride_nan": 56,
            "stride_sum": 1393.7791710717715,
            "stride_min": 2.0689654680329177,
            "stride_max": 2.1237084225732348,
            "stride_first": 2.117065335170472,
            "stride_last": 2.0937682294501587,
            "stride_q1": 2.081568333417088,
            "stride_q2": 2.1040792032090723,
            "stride_q3": 2.1085187734833966,
            "stride_dx_n": 720,
            "stride_dx_nan": 56,
            "stride_dx_sum": 1393.7791710717715,
            "stride_dx_min": 2.0689654680329177,
            "stride_dx_max": 2.1237084225732348,
            "stride_dx_first": 2.117065335170472,
            "stride_dx_last": 2.0937682294501587,
            "stride_dx_q1": 2.081568333417088,
            "stride_dx_q2": 2.1040792032090723,
            "stride_dx_q3": 2.1085187734833966,
            "win2_n": 1440,
            "win2_nan": 391,
            "win2_sum": 2020.890194241495,
            "win2_min": 1.3593606223346564,
            "win2_max": 3.1250000000000444,
            "win2_first": 1.6637860765704657,
            "win2_last": 1.9578005472187523,
            "win2_q1": 1.807803464479916,
            "win2_q2": math.nan,
            "win2_q3": 2.0381375272142273,
            "list_in_n": 1440,
            "list_in_nan": 290,
            "list_in_sum": 2131.052354578689,
            "list_in_min": 1.5438071577792443,
            "list_in_max": 3.0625000000000435,
            "list_in_first": 1.8256678953403778,
            "list_in_last": 2.0082503266454124,
            "list_in_q1": 1.796666638036569,
            "list_in_q2": 1.5438071577792443,
            "list_in_q3": 1.9875834128675756,
            "short_n": 7,
            "short_nan": 7,
            "short_sum": 0.0,
            "short_min": math.nan,
            "short_max": math.nan,
            "short_first": math.nan,
            "short_last": math.nan,
            "short_q1": math.nan,
            "short_q2": math.nan,
            "short_q3": math.nan,
            "flat_t_n": 50,
            "flat_t_nan": 50,
            "flat_t_sum": 0.0,
            "flat_t_min": math.nan,
            "flat_t_max": math.nan,
            "flat_t_first": math.nan,
            "flat_t_last": math.nan,
            "flat_t_q1": math.nan,
            "flat_t_q2": math.nan,
            "flat_t_q3": math.nan,
            "back_t_n": 50,
            "back_t_nan": 50,
            "back_t_sum": 0.0,
            "back_t_min": math.nan,
            "back_t_max": math.nan,
            "back_t_first": math.nan,
            "back_t_last": math.nan,
            "back_t_q1": math.nan,
            "back_t_q2": math.nan,
            "back_t_q3": math.nan,
            "tiny_window_n": 100,
            "tiny_window_nan": 47,
            "tiny_window_sum": 156.0272762260834,
            "tiny_window_min": 1.5136381130416212,
            "tiny_window_max": 3.0000000000000027,
            "tiny_window_first": 3.0000000000000027,
            "tiny_window_last": 3.0000000000000027,
            "tiny_window_q1": math.nan,
            "tiny_window_q2": 3.0000000000000027,
            "tiny_window_q3": 3.0000000000000027,
            "nonuniform_n": 720,
            "nonuniform_nan": 220,
            "nonuniform_sum": 943.6997938394766,
            "nonuniform_min": 1.7675122656436537,
            "nonuniform_max": 2.1763833437852096,
            "nonuniform_first": 1.8161602799053376,
            "nonuniform_last": 2.0039417697059374,
            "nonuniform_q1": 1.7953196423348237,
            "nonuniform_q2": math.nan,
            "nonuniform_q3": 2.002434059103621,
        },
        **APPROX,
    )


def test_estimate_cadence_on_fixture_vertical_acceleration() -> None:
    from engine.egosignals import cadence

    assert case_estimate_cadence_fixture(cadence) == pytest.approx(
        {
            "nvt": 3600,
            "vert_n": 3600,
            "vert_nan": 0,
            "vert_sum": 35586.245472809045,
            "vert_min": 4.179583414203523,
            "vert_max": 18.884179694086935,
            "vert_first": 11.805948087509334,
            "vert_last": 5.913647581472133,
            "vert_q1": 12.246409062816625,
            "vert_q2": 10.631895059313427,
            "vert_q3": 7.4444604806976775,
            "side_n": 3600,
            "side_nan": 0,
            "side_sum": 4.36621894623037,
            "side_min": -5.240027003370628,
            "side_max": 6.447514037533731,
            "side_first": -1.7361770789811564,
            "side_last": -0.21446125956539797,
            "side_q1": 0.8963693196874275,
            "side_q2": 0.04442450065412333,
            "side_q3": -1.2777593129512184,
            "cad_n": 3600,
            "cad_nan": 143,
            "cad_sum": 5970.90699907777,
            "cad_min": 1.4860446388749995,
            "cad_max": 1.9154814316736215,
            "cad_first": 1.7730307085347718,
            "cad_last": 1.9142790526766769,
            "cad_q1": 1.7910533667449209,
            "cad_q2": 1.8073714811893622,
            "cad_q3": 1.8104368871182082,
            "cad_nodx_n": 3600,
            "cad_nodx_nan": 143,
            "cad_nodx_sum": 5970.90699907777,
            "cad_nodx_min": 1.4860446388749995,
            "cad_nodx_max": 1.9154814316736215,
            "cad_nodx_first": 1.7730307085347718,
            "cad_nodx_last": 1.9142790526766769,
            "cad_nodx_q1": 1.7910533667449209,
            "cad_nodx_q2": 1.8073714811893622,
            "cad_nodx_q3": 1.8104368871182082,
        },
        **APPROX,
    )


def test_hold_last_edge_cases() -> None:
    from engine.egosignals import cadence

    assert case_hold_last(cadence) == pytest.approx(
        {
            "expire_len": 7,
            "expire_0": 1.0,
            "expire_1": 1.0,
            "expire_2": 1.0,
            "expire_3": math.nan,
            "expire_4": math.nan,
            "expire_5": 2.0,
            "expire_6": 2.0,
            "expire_input_unchanged": 1.0,
            "expire_is_copy": 1.0,
            "exact_len": 4,
            "exact_0": 5.0,
            "exact_1": 5.0,
            "exact_2": 5.0,
            "exact_3": math.nan,
            "exact_input_unchanged": 1.0,
            "exact_is_copy": 1.0,
            "lead_nan_len": 6,
            "lead_nan_0": math.nan,
            "lead_nan_1": math.nan,
            "lead_nan_2": 3.0,
            "lead_nan_3": 3.0,
            "lead_nan_4": math.nan,
            "lead_nan_5": math.nan,
            "lead_nan_input_unchanged": 1.0,
            "lead_nan_is_copy": 1.0,
            "all_nan_len": 3,
            "all_nan_0": math.nan,
            "all_nan_1": math.nan,
            "all_nan_2": math.nan,
            "all_nan_input_unchanged": 1.0,
            "all_nan_is_copy": 1.0,
            "no_nan_len": 4,
            "no_nan_0": 1.0,
            "no_nan_1": 2.0,
            "no_nan_2": 3.0,
            "no_nan_3": 4.0,
            "no_nan_input_unchanged": 1.0,
            "no_nan_is_copy": 1.0,
            "zero_hold_len": 4,
            "zero_hold_0": 1.0,
            "zero_hold_1": math.nan,
            "zero_hold_2": 2.0,
            "zero_hold_3": math.nan,
            "zero_hold_input_unchanged": 1.0,
            "zero_hold_is_copy": 1.0,
            "neg_hold_len": 4,
            "neg_hold_0": 1.0,
            "neg_hold_1": math.nan,
            "neg_hold_2": 2.0,
            "neg_hold_3": math.nan,
            "neg_hold_input_unchanged": 1.0,
            "neg_hold_is_copy": 1.0,
            "empty_len": 0,
            "empty_input_unchanged": 1.0,
            "empty_is_copy": 1.0,
            "single_len": 1,
            "single_0": 7.0,
            "single_input_unchanged": 1.0,
            "single_is_copy": 1.0,
            "irregular_len": 6,
            "irregular_0": 1.0,
            "irregular_1": 1.0,
            "irregular_2": 1.0,
            "irregular_3": math.nan,
            "irregular_4": 4.0,
            "irregular_5": 4.0,
            "irregular_input_unchanged": 1.0,
            "irregular_is_copy": 1.0,
        },
        **APPROX,
    )


def test_estimate_stationary_walk_stand_walk() -> None:
    from engine.egosignals import cadence

    assert case_estimate_stationary(cadence) == pytest.approx(
        {
            "cfg_n": 1440,
            "cfg_true": 467,
            "cfg_edges": 2,
            "cfg_e0": 527,
            "cfg_e1": 994,
            "imu_n": 1440,
            "imu_true": 468,
            "imu_edges": 2,
            "imu_e0": 518,
            "imu_e1": 986,
            "empty_cfg_n": 1440,
            "empty_cfg_true": 467,
            "empty_cfg_edges": 2,
            "empty_cfg_e0": 527,
            "empty_cfg_e1": 994,
            "list_in_n": 1440,
            "list_in_true": 467,
            "list_in_edges": 2,
            "list_in_e0": 527,
            "list_in_e1": 994,
            "slow_n": 1440,
            "slow_true": 431,
            "slow_edges": 2,
            "slow_e0": 635,
            "slow_e1": 1066,
            "high_enter_n": 1440,
            "high_enter_true": 1393,
            "high_enter_edges": 1,
            "high_enter_e0": 46,
            "nan_standing_n": 1440,
            "nan_standing_true": 313,
            "nan_standing_edges": 4,
            "nan_standing_e0": 527,
            "nan_standing_e1": 636,
            "nan_standing_e2": 790,
            "nan_standing_e3": 994,
            "nan_walking_n": 1440,
            "nan_walking_true": 467,
            "nan_walking_edges": 2,
            "nan_walking_e0": 527,
            "nan_walking_e1": 994,
            "all_nan_n": 1440,
            "all_nan_true": 0,
            "all_nan_edges": 0,
            "short_n": 1,
            "short_true": 0,
            "short_edges": 0,
            "empty_n": 0,
            "empty_true": 0,
            "empty_edges": 0,
            "flat_t_n": 30,
            "flat_t_true": 0,
            "flat_t_edges": 0,
            "quiet_n": 1440,
            "quiet_true": 1393,
            "quiet_edges": 1,
            "quiet_e0": 46,
        },
        **APPROX,
    )


def test_estimate_stationary_on_fixture_sensor_energy() -> None:
    from engine.egosignals import cadence

    assert case_stationary_fixture(cadence) == pytest.approx(
        {
            "energy_n": 900,
            "energy_nan": 0,
            "energy_sum": 2261.9384505258886,
            "energy_min": 0.0642979440932091,
            "energy_max": 4.8289057222932685,
            "energy_first": 3.913289046382444,
            "energy_last": 2.843748864242748,
            "energy_q1": 3.3597730029693196,
            "energy_q2": 2.8200318428022015,
            "energy_q3": 0.09625284342802345,
            "stat_n": 900,
            "stat_true": 195,
            "stat_edges": 2,
            "stat_e0": 571,
            "stat_e1": 766,
        },
        **APPROX,
    )
