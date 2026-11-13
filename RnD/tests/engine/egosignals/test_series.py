"""Characterisation tests for engine.egosignals.series (v26.3.0 p2-04).

Every expected literal in LITS was produced by running the legacy code (collision._motion_series, _sensor_series,
_nearest, _gps_at, _auto_stationary, _sensor_heading) in the hackeye-rnd image on the pre-move code, never by hand.
The scenario functions below are the exact calls that were run against the legacy functions; the tests run them
against the engine functions and compare with the pinned digests. The ego config is read straight from
common/config/collision.json (not through collision.load_config). Real data: tests/fixtures/chest0004_review9.npz
(motion track + device sensors, 150 s) and 4929_review1.npz (motion without sensors, no ``resid``).
Arrays are pinned as digests: float series (n, nan count, sum, abs-sum, first, last, middle), boolean series
(n, true count, first change indices, change count).
"""

from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from common_paths import find_common_dir

FIX = Path(__file__).resolve().parents[2] / "fixtures"
HFOV = 100.0
APPROX: dict[str, Any] = {"rel": 1e-12, "abs": 1e-12, "nan_ok": True}


def _ego() -> dict[str, Any]:
    cfg: dict[str, Any] = json.loads((find_common_dir() / "config" / "collision.json").read_text())
    ego: dict[str, Any] = cfg["ego"]
    return ego


def _dig(a: npt.ArrayLike) -> dict[str, Any]:
    arr = np.asarray(a)
    if arr.dtype == bool:
        idx = np.flatnonzero(np.diff(arr.astype(int)) != 0)
        return {"n": len(arr), "true": int(arr.sum()), "edges": [int(i) for i in idx[:6]], "nedges": len(idx)}
    f = arr.astype(float)
    ok = f[~np.isnan(f)]
    return {
        "n": len(f),
        "nan": int(np.isnan(f).sum()),
        "sum": float(ok.sum()),
        "abs": float(np.abs(ok).sum()),
        "first": float(f[0]) if len(f) else None,
        "last": float(f[-1]) if len(f) else None,
        "mid": float(f[len(f) // 2]) if len(f) else None,
    }


@cache
def _load_cached(name: str) -> tuple[dict[str, Any], npt.NDArray[np.float64], dict[str, Any]]:
    with np.load(FIX / f"{name}.npz") as z:
        m: dict[str, Any] = {"t": np.array(z["w0_mt"]), "dx": np.array(z["w0_mdx"]), "dy": np.array(z["w0_mdy"])}
        if "w0_mresid" in z.files:
            m["resid"] = np.array(z["w0_mresid"])
        s: dict[str, Any] = {k[len("sensors_") :]: np.array(z[k]) for k in z.files if k.startswith("sensors_")}
        return m, np.array(z["w0_t"]), s


def _load(name: str) -> tuple[dict[str, Any], npt.NDArray[np.float64], dict[str, Any]]:
    m, t, s = _load_cached(name)
    return {k: v.copy() for k, v in m.items()}, t.copy(), {k: v.copy() for k, v in s.items()}


def _ms(r: Any) -> dict[str, Any] | None:
    if r is None:
        return None
    return {"mt": _dig(r[0]), "cad": _dig(r[1]), "head": _dig(r[2]), "stat": None if r[3] is None else _dig(r[3])}


def _ss(r: Any) -> dict[str, Any] | None:
    if r is None:
        return None
    out: dict[str, Any] = {k: _dig(v) for k, v in r.items() if isinstance(v, np.ndarray)}
    out["keys"] = list(r.keys())
    return out


def sc_motion(f: Any) -> dict[str, Any]:
    ego = _ego()
    m9, _, _ = _load("chest0004_review9")
    m49, _, _ = _load("4929_review1")
    return {
        "chest9": _ms(f.motion_series(m9, HFOV, ego)),
        "no_resid": _ms(f.motion_series(m49, HFOV, ego)),
        "none": f.motion_series(None, HFOV, ego),
        "short": f.motion_series({"t": [1.0], "dx": [0.0], "dy": [0.0]}, HFOV, ego),
    }


def sc_sensor(f: Any) -> dict[str, Any]:
    ego = _ego()
    m9, t9, s9 = _load("chest0004_review9")
    m49, t49, _ = _load("4929_review1")
    mr = f.motion_series(m9, HFOV, ego)
    r = f.sensor_series(s9, mr, t9, ego, HFOV)
    assert r is not None
    return {
        "full": _ss(r),
        "full_slen": {k: len(v) for k, v in r["s"].items()},
        "times_only": _ss(f.sensor_series(s9, None, t9, ego, HFOV)),
        "other_motion": _ss(f.sensor_series(s9, f.motion_series(m49, HFOV, ego), t49, ego, HFOV)),
        "no_sensors": [
            f.sensor_series(None, mr, t9, ego, HFOV),
            f.sensor_series({}, mr, t9, ego, HFOV),
            f.sensor_series({k: v for k, v in s9.items() if k != "gyro"}, mr, t9, ego, HFOV),
        ],
        "short_mt": f.sensor_series(s9, None, t9[:1], ego, HFOV),
        "short_gyro": f.sensor_series(
            {**s9, "gyro_t": s9["gyro_t"][:100], "gyro": s9["gyro"][:100]}, mr, t9, ego, HFOV
        ),
    }


def sc_nearest(f: Any) -> dict[str, Any]:
    tu = np.array([0.0, 1.0, 2.0, 5.0])
    q = np.array([-1.0, 0.0, 0.5, 1.0, 1.9999999999, 2.0, 4.9, 5.0, 9.0])
    return {
        "grid": f.nearest(tu, q).tolist(),
        "single": f.nearest(np.array([3.0]), np.array([0.0, 3.0, 4.0])).tolist(),
    }


def sc_gps(f: Any) -> dict[str, Any]:
    _, _, g = _load("chest0004_review9")
    gcfg = _ego().get("gps") or {}
    gt = g["gps_t"]
    times = [0.0, float(gt[0]), float(gt[1000]), float(gt[1000]) + 1.0, float(gt[-1]), float(gt[-1]) + 1.4]
    times += [float(gt[-1]) + 1.6, -5.0]
    real = [f.gps_at(g, t, gcfg) for t in times]
    k = float(gt[1000])
    syn = {
        "gps_t": np.array([0.0, 1.0, 2.0]),
        "gps_fix": np.array([0, 2, 3]),
        "gps_dop": np.array([9.0, 3.0, 1.0]),
        "gps": np.array(
            [
                [41.1234567891, -8.1234567891, 0, 1.234, 0],
                [41.5, -8.5, 0, 0.0, 0],
                [41.123456789, -8.987654321, 0, 1.2349, 0],
            ]
        ),
    }
    return {
        "real": real,
        "real_cfg": [
            f.gps_at(g, k, {"maxDop": 0.0}),
            f.gps_at(g, k, {"enabled": False}),
            f.gps_at(g, k, {"minFix": 9}),
        ],
        "empty": [f.gps_at({}, 1.0, {}), f.gps_at({"gps_t": np.zeros(0)}, 1.0, {})],
        "syn": [f.gps_at(syn, t, {}) for t in (0.0, 1.0, 1.5, 2.0, 2.7, 3.6, -1.4, -1.6)],
        "syn_loose": f.gps_at(syn, 1.0, {"minFix": 2, "maxDop": 3.0}),
    }


def sc_auto(f: Any) -> dict[str, Any]:
    a = np.array([True, False, True])
    b = np.array([False, False, True])
    r = f.auto_stationary(a, b)
    return {"is_imu": r[0] is b, "name": r[1], "len": len(r)}


def _hd(sser: dict[str, Any]) -> dict[str, Any]:
    return {
        "keys": list(sser.keys()),
        "imu": _dig(sser["heading_imu"]),
        "gps": _dig(sser["heading_gps"]),
        "info": sser["info"],
        "same": sser["heading_gps"] is sser["heading_imu"],
    }


def sc_heading(f: Any) -> dict[str, Any]:
    ego = _ego()
    m9, t9, s9 = _load("chest0004_review9")
    mr = f.motion_series(m9, HFOV, ego)
    base = f.sensor_series(s9, mr, t9, ego, HFOV)
    out: dict[str, Any] = {"keys_before": list(base.keys())}
    cases = [
        ("nostat", None, ego),
        ("flowstat", mr[3], ego),
        ("imustat", base["stat_imu"], ego),
        ("gpsoff", base["stat_imu"], {**ego, "gps": {"enabled": False}}),
    ]
    for name, stat, cfg in cases:
        sd = f.sensor_series(s9, mr, t9, ego, HFOV)
        out[name + "_ret"] = f.sensor_heading(sd, stat, cfg)
        out[name] = _hd(sd)
    sd = f.sensor_series({k: v for k, v in s9.items() if not k.startswith("gps")}, mr, t9, ego, HFOV)
    f.sensor_heading(sd, base["stat_imu"], ego)
    out["nogps"] = _hd(sd)
    return out


def check(got: Any, exp: Any, path: str = "") -> None:
    if isinstance(exp, dict):
        assert isinstance(got, dict), path
        assert list(got.keys()) == list(exp.keys()), path
        for k in exp:
            check(got[k], exp[k], f"{path}/{k}")
    elif isinstance(exp, (list, tuple)):
        assert isinstance(got, (list, tuple)), path
        assert len(got) == len(exp), path
        for i, (g, e) in enumerate(zip(got, exp, strict=True)):
            check(g, e, f"{path}[{i}]")
    elif isinstance(exp, float):
        assert got == pytest.approx(exp, **APPROX), path
    else:
        assert got == exp, path


nan = math.nan
LITS: dict[str, Any] = {
    "imu_default": {
        "medianSeconds": 0.3,
        "enterPx": 0.5,
        "leavePx": 0.8,
        "enterSeconds": 1.5,
        "leaveSeconds": 1.0,
    },
    "motion": {
        "chest9": {
            "mt": {
                "n": 8992,
                "nan": 0,
                "sum": 674400.0,
                "abs": 674400.0,
                "first": 0.0,
                "last": 150.0,
                "mid": 75.00834167500834,
            },
            "cad": {
                "n": 8992,
                "nan": 143,
                "sum": 16577.45876195953,
                "abs": 16577.45876195953,
                "first": nan,
                "last": 1.6262005947549456,
                "mid": 1.8906690762929568,
            },
            "head": {
                "n": 8992,
                "nan": 0,
                "sum": 329997.7197931427,
                "abs": 357381.5602171275,
                "first": -0.0,
                "last": 90.08293341276712,
                "mid": 36.31608996424234,
            },
            "stat": {
                "n": 8992,
                "true": 1240,
                "edges": [7021, 8261],
                "nedges": 2,
            },
        },
        "no_resid": {
            "mt": {
                "n": 240,
                "nan": 0,
                "sum": 1196.1961961961963,
                "abs": 1196.1961961961963,
                "first": 0.0,
                "last": 9.968301634968302,
                "mid": 5.005005005005005,
            },
            "cad": {
                "n": 240,
                "nan": 56,
                "sum": 352.17237313378854,
                "abs": 352.17237313378854,
                "first": nan,
                "last": 1.9722283034723245,
                "mid": 1.9778595846519267,
            },
            "head": {
                "n": 240,
                "nan": 0,
                "sum": 5726.315574688488,
                "abs": 5726.315574688488,
                "first": -0.0,
                "last": 35.552149490467855,
                "mid": 27.955747453597724,
            },
            "stat": None,
        },
        "none": None,
        "short": None,
    },
    "sensor": {
        "full": {
            "mt": {
                "n": 8992,
                "nan": 0,
                "sum": 674400.0,
                "abs": 674400.0,
                "first": 0.0,
                "last": 150.0,
                "mid": 75.00834167500834,
            },
            "stat_imu": {
                "n": 8992,
                "true": 1169,
                "edges": [7024, 8193],
                "nedges": 2,
            },
            "cad": {
                "n": 8992,
                "nan": 144,
                "sum": 17085.30892426291,
                "abs": 17085.30892426291,
                "first": nan,
                "last": 1.6410614924806513,
                "mid": 1.8731353428985376,
            },
            "pitch": {
                "n": 8992,
                "nan": 0,
                "sum": -44558.84672773707,
                "abs": 45560.71733128229,
                "first": -12.106184112102698,
                "last": -4.260600131180673,
                "mid": -5.489469912554881,
            },
            "roll": {
                "n": 8992,
                "nan": 0,
                "sum": 3599.872716090512,
                "abs": 29136.76234689085,
                "first": -6.850807417563804,
                "last": 1.6589176773106167,
                "mid": -2.716762180793743,
            },
            "keys": ["mt", "s", "stat_imu", "cad", "pitch", "roll"],
        },
        "full_slen": {
            "gyro": 61552,
            "gyro_t": 61552,
            "accl": 30776,
            "accl_t": 30776,
            "gps": 2805,
            "gps_t": 2805,
            "gps_fix": 2805,
            "gps_dop": 2805,
            "gps_utc": 2805,
            "shut": 4675,
            "shut_t": 4675,
            "isog": 4675,
            "isog_t": 4675,
        },
        "times_only": {
            "mt": {
                "n": 181,
                "nan": 0,
                "sum": 2715.031698365032,
                "abs": 2715.031698365032,
                "first": 0.0,
                "last": 29.996663329996665,
                "mid": 14.998331664998332,
            },
            "stat_imu": {
                "n": 181,
                "true": 0,
                "edges": [],
                "nedges": 0,
            },
            "cad": {
                "n": 181,
                "nan": 15,
                "sum": 284.84243091701626,
                "abs": 284.84243091701626,
                "first": nan,
                "last": 1.8073714811893622,
                "mid": 1.7910533667449209,
            },
            "pitch": {
                "n": 181,
                "nan": 0,
                "sum": -1279.8362953418086,
                "abs": 1279.8362953418086,
                "first": -12.106184112102698,
                "last": -8.826792454463696,
                "mid": -8.141140689901114,
            },
            "roll": {
                "n": 181,
                "nan": 0,
                "sum": -72.94763360564528,
                "abs": 631.328272532128,
                "first": -6.850807417563804,
                "last": 1.9225350835618287,
                "mid": -3.304083425409096,
            },
            "keys": ["mt", "s", "stat_imu", "cad", "pitch", "roll"],
        },
        "other_motion": {
            "mt": {
                "n": 240,
                "nan": 0,
                "sum": 1196.1961961961963,
                "abs": 1196.1961961961963,
                "first": 0.0,
                "last": 9.968301634968302,
                "mid": 5.005005005005005,
            },
            "stat_imu": {
                "n": 240,
                "true": 0,
                "edges": [],
                "nedges": 0,
            },
            "cad": {
                "n": 240,
                "nan": 58,
                "sum": 315.17859667001323,
                "abs": 315.17859667001323,
                "first": nan,
                "last": 1.7102039150027448,
                "mid": 1.8076802866992823,
            },
            "pitch": {
                "n": 240,
                "nan": 0,
                "sum": -1895.0752796202892,
                "abs": 1895.0752796202892,
                "first": -12.106184112102698,
                "last": -7.705125127712044,
                "mid": -5.264420670878505,
            },
            "roll": {
                "n": 240,
                "nan": 0,
                "sum": -140.71062796305392,
                "abs": 830.4378112169481,
                "first": -6.850807417563804,
                "last": 2.438973844043415,
                "mid": -1.419045138241387,
            },
            "keys": ["mt", "s", "stat_imu", "cad", "pitch", "roll"],
        },
        "no_sensors": [None, None, None],
        "short_mt": None,
        "short_gyro": None,
    },
    "nearest": {
        "grid": [0, 0, 0, 1, 2, 2, 2, 3, 3],
        "single": [0, 0, 0],
    },
    "gps": {
        "real": [
            {
                "lat": None,
                "lon": None,
                "speedMps": 0.0,
                "dop": 99.99,
                "fix": 0,
                "good": False,
            },
            {
                "lat": None,
                "lon": None,
                "speedMps": 0.0,
                "dop": 99.99,
                "fix": 0,
                "good": False,
            },
            {
                "lat": 41.3634829,
                "lon": -8.7583105,
                "speedMps": 1.08,
                "dop": 20.93,
                "fix": 3,
                "good": False,
            },
            {
                "lat": 41.3634933,
                "lon": -8.7583072,
                "speedMps": 1.21,
                "dop": 20.93,
                "fix": 3,
                "good": False,
            },
            {
                "lat": 41.3642287,
                "lon": -8.7589248,
                "speedMps": 1.07,
                "dop": 21.46,
                "fix": 3,
                "good": False,
            },
            {
                "lat": 41.3642287,
                "lon": -8.7589248,
                "speedMps": 1.07,
                "dop": 21.46,
                "fix": 3,
                "good": False,
            },
            None,
            None,
        ],
        "real_cfg": [
            {
                "lat": 41.3634829,
                "lon": -8.7583105,
                "speedMps": 1.08,
                "dop": 20.93,
                "fix": 3,
                "good": False,
            },
            {
                "lat": 41.3634829,
                "lon": -8.7583105,
                "speedMps": 1.08,
                "dop": 20.93,
                "fix": 3,
                "good": False,
            },
            {
                "lat": 41.3634829,
                "lon": -8.7583105,
                "speedMps": 1.08,
                "dop": 20.93,
                "fix": 3,
                "good": False,
            },
        ],
        "empty": [None, None],
        "syn": [
            {
                "lat": None,
                "lon": None,
                "speedMps": 1.23,
                "dop": 9.0,
                "fix": 0,
                "good": False,
            },
            {
                "lat": 41.5,
                "lon": -8.5,
                "speedMps": 0.0,
                "dop": 3.0,
                "fix": 2,
                "good": False,
            },
            {
                "lat": 41.5,
                "lon": -8.5,
                "speedMps": 0.0,
                "dop": 3.0,
                "fix": 2,
                "good": False,
            },
            {
                "lat": 41.1234568,
                "lon": -8.9876543,
                "speedMps": 1.23,
                "dop": 1.0,
                "fix": 3,
                "good": True,
            },
            {
                "lat": 41.1234568,
                "lon": -8.9876543,
                "speedMps": 1.23,
                "dop": 1.0,
                "fix": 3,
                "good": True,
            },
            None,
            {
                "lat": None,
                "lon": None,
                "speedMps": 1.23,
                "dop": 9.0,
                "fix": 0,
                "good": False,
            },
            None,
        ],
        "syn_loose": {
            "lat": 41.5,
            "lon": -8.5,
            "speedMps": 0.0,
            "dop": 3.0,
            "fix": 2,
            "good": True,
        },
    },
    "auto": {
        "is_imu": True,
        "name": "imu",
        "len": 2,
    },
    "heading": {
        "keys_before": ["mt", "s", "stat_imu", "cad", "pitch", "roll"],
        "nostat_ret": None,
        "nostat": {
            "keys": ["mt", "s", "stat_imu", "cad", "pitch", "roll", "heading_imu", "info", "heading_gps"],
            "imu": {
                "n": 8992,
                "nan": 0,
                "sum": -164747.51997784342,
                "abs": 183242.1771051314,
                "first": 0.0,
                "last": -42.29178998263208,
                "mid": -16.398119017752894,
            },
            "gps": {
                "n": 8992,
                "nan": 0,
                "sum": -171183.77105980951,
                "abs": 189064.01847170322,
                "first": 0.0,
                "last": -43.30091486012972,
                "mid": -17.407243895250534,
            },
            "info": {
                "biasDegPerS": 0.0538,
                "biasSource": "lowest",
                "gpsUpdates": 7,
            },
            "same": False,
        },
        "flowstat_ret": None,
        "flowstat": {
            "keys": ["mt", "s", "stat_imu", "cad", "pitch", "roll", "heading_imu", "info", "heading_gps"],
            "imu": {
                "n": 8992,
                "nan": 0,
                "sum": -206117.91965477774,
                "abs": 219699.34302078784,
                "first": 0.0,
                "last": -51.49960755652413,
                "mid": -20.999429647399197,
            },
            "gps": {
                "n": 8992,
                "nan": 0,
                "sum": -212054.25176200832,
                "abs": 225129.69762387604,
                "first": 0.0,
                "last": -52.43032802879413,
                "mid": -21.930150119669193,
            },
            "info": {
                "biasDegPerS": 0.1152,
                "biasSource": "stationary",
                "gpsUpdates": 7,
            },
            "same": False,
        },
        "imustat_ret": None,
        "imustat": {
            "keys": ["mt", "s", "stat_imu", "cad", "pitch", "roll", "heading_imu", "info", "heading_gps"],
            "imu": {
                "n": 8992,
                "nan": 0,
                "sum": -212624.57834033185,
                "abs": 225487.45118833997,
                "first": 0.0,
                "last": -52.94779579400819,
                "mid": -21.723115132845866,
            },
            "gps": {
                "n": 8992,
                "nan": 0,
                "sum": -218482.28413105514,
                "abs": 230853.74262655718,
                "first": 0.0,
                "last": -53.86618496882292,
                "mid": -22.6415043076606,
            },
            "info": {
                "biasDegPerS": 0.1249,
                "biasSource": "stationary",
                "gpsUpdates": 7,
            },
            "same": False,
        },
        "gpsoff_ret": None,
        "gpsoff": {
            "keys": ["mt", "s", "stat_imu", "cad", "pitch", "roll", "heading_imu", "info", "heading_gps"],
            "imu": {
                "n": 8992,
                "nan": 0,
                "sum": -212624.57834033185,
                "abs": 225487.45118833997,
                "first": 0.0,
                "last": -52.94779579400819,
                "mid": -21.723115132845866,
            },
            "gps": {
                "n": 8992,
                "nan": 0,
                "sum": -212624.57834033185,
                "abs": 225487.45118833997,
                "first": 0.0,
                "last": -52.94779579400819,
                "mid": -21.723115132845866,
            },
            "info": {
                "biasDegPerS": 0.1249,
                "biasSource": "stationary",
            },
            "same": True,
        },
        "nogps": {
            "keys": ["mt", "s", "stat_imu", "cad", "pitch", "roll", "heading_imu", "info", "heading_gps"],
            "imu": {
                "n": 8992,
                "nan": 0,
                "sum": -212624.57834033185,
                "abs": 225487.45118833997,
                "first": 0.0,
                "last": -52.94779579400819,
                "mid": -21.723115132845866,
            },
            "gps": {
                "n": 8992,
                "nan": 0,
                "sum": -212624.57834033185,
                "abs": 225487.45118833997,
                "first": 0.0,
                "last": -52.94779579400819,
                "mid": -21.723115132845866,
            },
            "info": {
                "biasDegPerS": 0.1249,
                "biasSource": "stationary",
            },
            "same": True,
        },
    },
}


def _ser() -> Any:
    from engine.egosignals import series

    return series


def test_identity() -> None:
    import collision

    ser = _ser()
    assert collision._motion_series is ser.motion_series
    assert collision._nearest is ser.nearest
    assert collision._sensor_series is ser.sensor_series
    assert collision._gps_at is ser.gps_at
    assert collision._auto_stationary is ser.auto_stationary
    assert collision._sensor_heading is ser.sensor_heading
    assert collision.IMU_STATIONARY_DEFAULT is ser.IMU_STATIONARY_DEFAULT


def test_imu_stationary_default() -> None:
    assert LITS["imu_default"] == _ser().IMU_STATIONARY_DEFAULT


def test_motion_series() -> None:
    check(sc_motion(_ser()), LITS["motion"])


def test_sensor_series() -> None:
    check(sc_sensor(_ser()), LITS["sensor"])


def test_nearest() -> None:
    check(sc_nearest(_ser()), LITS["nearest"])


def test_gps_at() -> None:
    check(sc_gps(_ser()), LITS["gps"])


def test_auto_stationary() -> None:
    check(sc_auto(_ser()), LITS["auto"])


def test_sensor_heading_mutation() -> None:
    check(sc_heading(_ser()), LITS["heading"])
