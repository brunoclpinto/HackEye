"""engine.egosignals.imu: the IMU / GPS derived signals moved out of sensors.py (v26.3.0 p2-02).

Characterisation: every pinned literal was produced by the legacy ``sensors`` functions (before the move) on the
real sensor stream of the fixture chest0004_review10 (156 s of Chest-center-0004) and on small synthetic arrays.
Arrays are pinned as digests: (shape, sum, abs-sum, first row, last row).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "chest0004_review10.npz"


@cache
def _real_cached() -> dict[str, Any]:
    with np.load(FIXTURE) as z:
        return {k[len("sensors_") :]: np.array(z[k]) for k in z.files if k.startswith("sensors_")}


def _real() -> dict[str, Any]:
    return {k: v.copy() for k, v in _real_cached().items()}


def _syn(seconds: float = 12.0, hz: float = 50.0) -> dict[str, Any]:
    """Synthetic upright camera turning right at 10 deg/s after 3 s, accel with a small bob."""
    t = np.arange(0.0, seconds, 1.0 / hz)
    rate = np.where(t > 3.0, np.radians(10.0), 0.0)
    gyro = np.zeros((len(t), 3))
    gyro[:, 0] = -rate + np.radians(0.4)
    gyro[:, 1] = 0.01 * np.sin(t)
    accl = np.stack(
        [9.81 + 0.5 * np.sin(2 * np.pi * 1.8 * t), 0.7 * np.cos(2 * np.pi * 0.9 * t), 0.3 * np.sin(t)], axis=1
    )
    return {"gyro_t": t, "gyro": gyro, "accl_t": t, "accl": accl}


def _walk(
    n_s: float = 90.0, hz: float = 18.0, speed: float = 1.4, course_deg: float = 45.0, fix: int = 3, dop: float = 1.2
) -> dict[str, Any]:
    """Synthetic GPS: a straight walk on the given compass course."""
    t = np.arange(0.0, n_s, 1.0 / hz)
    lat0, lon0 = 41.0, -8.6
    east = speed * t * np.sin(np.radians(course_deg))
    north = speed * t * np.cos(np.radians(course_deg))
    g = np.zeros((len(t), 5))
    g[:, 0] = lat0 + north / 110540.0
    g[:, 1] = lon0 + east / (111320.0 * np.cos(np.radians(lat0)))
    g[:, 3] = speed
    return {"gps": g, "gps_t": t, "gps_fix": np.full(len(t), fix), "gps_dop": np.full(len(t), dop)}


def _stat_real() -> tuple[npt.NDArray[Any], npt.NDArray[Any]]:
    st = np.arange(0.0, 156.0, 0.1)
    return st, (st < 12.0) | ((st > 40.0) & (st < 46.0))


def _stat_syn() -> tuple[npt.NDArray[Any], npt.NDArray[Any]]:
    st = np.arange(0.0, 3.0, 0.1)
    return st, np.ones(len(st), dtype=bool)


def _step_inputs() -> tuple[npt.NDArray[Any], npt.NDArray[Any], npt.NDArray[Any]]:
    mt = np.arange(0.0, 156.0, 1 / 24)
    cad = 1.75 + 0.25 * np.sin(mt / 7.0)
    return mt, cad, (mt % 40.0) < 5.0


def _digest(x: Any) -> Any:
    if isinstance(x, np.ndarray):
        a = x.astype(np.float64)
        flat = a.reshape(len(a), int(np.prod(a.shape[1:]))) if a.ndim else a.reshape(1, 1)
        first = flat[0].tolist() if len(flat) else None
        last = flat[-1].tolist() if len(flat) else None
        return ("arr", x.shape, float(a.sum()), float(np.abs(a).sum()), first, last)
    if isinstance(x, tuple | list):
        return [_digest(v) for v in x]
    if isinstance(x, dict):
        return {k: _digest(v) for k, v in x.items()}
    if isinstance(x, np.floating | np.integer | np.bool_):
        return x.item()
    return x


def _same(got: Any, exp: Any) -> bool:
    if isinstance(exp, tuple) and exp and exp[0] == "arr":
        return (
            isinstance(got, tuple)
            and got[0] == "arr"
            and tuple(got[1]) == tuple(exp[1])
            and all(_same(g, e) for g, e in zip(got[2:], exp[2:], strict=True))
        )
    if isinstance(exp, dict):
        return isinstance(got, dict) and list(got) == list(exp) and all(_same(got[k], v) for k, v in exp.items())
    if isinstance(exp, list):
        return (
            isinstance(got, list) and len(got) == len(exp) and all(_same(g, e) for g, e in zip(got, exp, strict=True))
        )
    if isinstance(exp, float):
        return isinstance(got, float) and got == pytest.approx(exp, rel=1e-12, abs=1e-12)
    return bool(got == exp) and type(got) is type(exp)


def _chk(got: Any, exp: Any) -> None:
    d = _digest(got)
    assert _same(d, exp), f"{d!r} != {exp!r}"


# ----------------------------------------------------------------------------------------------------------------
# facade identity
# ----------------------------------------------------------------------------------------------------------------


def test_sensors_reexports_the_same_objects() -> None:
    import sensors
    from engine.egosignals import imu

    assert sensors._smooth is imu.smooth
    assert sensors._spans is imu.spans
    assert sensors._wrap is imu.wrap_deg
    for name in (
        "default_imu_cfg",
        "gravity_unit",
        "yaw_rate",
        "estimate_bias",
        "heading_series",
        "gravity_angles",
        "vertical_signals",
        "motion_energy",
        "gps_good",
        "gps_xy",
        "crop",
        "gps_course_offset",
        "gps_step_length",
    ):
        assert getattr(sensors, name) is getattr(imu, name), name


def test_package_reexports_the_public_api() -> None:
    import engine.egosignals as pkg
    from engine.egosignals import imu

    for name in (
        "smooth",
        "default_imu_cfg",
        "gravity_unit",
        "yaw_rate",
        "spans",
        "estimate_bias",
        "heading_series",
        "gravity_angles",
        "vertical_signals",
        "motion_energy",
        "gps_good",
        "gps_xy",
        "crop",
        "wrap_deg",
        "gps_course_offset",
        "gps_step_length",
    ):
        assert getattr(pkg, name) is getattr(imu, name), name
        assert name in pkg.__all__, name


# ----------------------------------------------------------------------------------------------------------------
# smooth, default config
# ----------------------------------------------------------------------------------------------------------------


def test_default_imu_cfg_is_pinned() -> None:
    from engine.egosignals import imu

    assert imu.default_imu_cfg() == {
        "yawSign": -1.0,
        "gravityTauS": 0.5,
        "yawGravityTauS": 1.0,
        "accelUpAxis": 0,
        "accelRightAxis": 1,
        "accelForwardAxis": 2,
        "pitchSign": -1.0,
        "rollSign": -1.0,
        "biasMinStationaryS": 2.0,
        "biasLowFraction": 0.2,
        "timeOffsetS": -0.1,
    }
    assert imu.default_imu_cfg() is not imu.default_imu_cfg()


def test_smooth_on_the_real_accelerometer() -> None:
    from engine.egosignals import imu

    s = _real()
    _chk(
        imu.smooth(s["accl_t"], s["accl"], 0.5),
        (
            "arr",
            (30776, 3),
            326011.9877809796,
            345741.0711039588,
            [11.134801288936627, 1.3377599843765258, 2.4055268040230446],
            [11.899808612440246, -0.3263636363636124, 0.6433971291867056],
        ),
    )
    _chk(
        imu.smooth(s["accl_t"], s["accl"], 1.0),
        (
            "arr",
            (30776, 3),
            326017.5401120671,
            334732.3643976366,
            [9.686261107313738, 0.8566546235719167, 1.7694072844448785],
            [9.939856459330185, -0.05380382775119415, 0.7130622009570289],
        ),
    )


def test_smooth_irregular_synthetic_stamps_and_edges() -> None:
    from engine.egosignals import imu

    t = np.array([0.0, 0.1, 0.15, 0.5, 0.52, 1.3, 2.0, 2.01])
    x = np.stack([np.arange(8.0), np.arange(8.0) ** 2], axis=1)
    _chk(imu.smooth(t, x, 0.4), ("arr", (8, 2), 168.0, 168.0, [1.0, 1.6666666666666667], [6.5, 42.5]))
    _chk(imu.smooth(t, x, 5.0), ("arr", (8, 2), 168.0, 168.0, [3.5, 17.5], [3.5, 17.5]))


def test_smooth_degenerate_inputs_return_a_float_copy() -> None:
    from engine.egosignals import imu

    x = np.arange(6, dtype=np.int64).reshape(3, 2)
    t = np.array([0.0, 1.0, 2.0])
    out = imu.smooth(t, x, 0.0)
    assert out is not x and out.dtype == np.float64 and out.tolist() == [[0.0, 1.0], [2.0, 3.0], [4.0, 5.0]]
    out2 = imu.smooth(t, x, -1.0)
    assert out2.tolist() == out.tolist()
    one = imu.smooth(np.array([0.0]), np.array([[3.0, 4.0]]), 1.0)
    assert one.tolist() == [[3.0, 4.0]]
    out[0, 0] = 99.0
    assert x[0, 0] == 0


# ----------------------------------------------------------------------------------------------------------------
# gravity, yaw rate, spans, bias, heading
# ----------------------------------------------------------------------------------------------------------------


def test_gravity_unit_real_and_synthetic() -> None:
    from engine.egosignals import imu

    _chk(
        imu.gravity_unit(_real(), 0.5),
        (
            "arr",
            (30776, 3),
            32979.68733144418,
            34980.94520199832,
            [0.9707795150344024, 0.11663162683970055, 0.2097240968756221],
            [0.998167292528879, -0.02737569299630468, 0.053968764656413266],
        ),
    )
    _chk(
        imu.gravity_unit(_real(), 1.0),
        (
            "arr",
            (30776, 3),
            33038.7041626535,
            33923.17406381805,
            [0.9800198355493764, 0.08667312536946357, 0.17902204129230195],
            [0.9974222048915441, -0.005398984656043739, 0.07155275084840654],
        ),
    )
    _chk(
        imu.gravity_unit(_syn(), 0.5),
        (
            "arr",
            (600, 3),
            599.0137696504682,
            630.5037663090982,
            [0.9987930870638579, 0.04898906581047551, 0.0035271326124382825],
            [0.9993914709693709, -0.02909549789719622, -0.01923901649750364],
        ),
    )
    g = imu.gravity_unit(_syn(), 1.0)
    assert np.linalg.norm(g, axis=1) == pytest.approx(1.0, rel=1e-12)


def test_gravity_unit_zero_accelerometer_does_not_divide_by_zero() -> None:
    from engine.egosignals import imu

    s = {"accl_t": np.arange(5.0), "accl": np.zeros((5, 3))}
    _chk(imu.gravity_unit(s, 1.0), ("arr", (5, 3), 0.0, 0.0, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]))


def test_yaw_rate_real_and_cfg() -> None:
    from engine.egosignals import imu

    _chk(
        imu.yaw_rate(_real()),
        [
            ("arr", (61552,), 4801105.125859649, 4801105.125859649, [0.0012767857142857142], [155.99920175438598]),
            ("arr", (61552,), -205.42398214737477, 16577.747141584212, [0.05387743158332309], [-0.06203668793155331]),
        ],
    )
    _chk(
        imu.yaw_rate(_real(), {"yawSign": 1.0, "yawGravityTauS": 2.0}),
        [
            ("arr", (61552,), 4801105.125859649, 4801105.125859649, [0.0012767857142857142], [155.99920175438598]),
            ("arr", (61552,), 267.01094556312546, 16538.2186571873, [-0.044023707236818255], [0.07224477592572068]),
        ],
    )
    _chk(
        imu.yaw_rate(_syn(), None),
        [
            ("arr", (600,), 3594.0, 3594.0, [0.0], [11.98]),
            ("arr", (600,), 74.1541010564811, 76.26057571183075, [-0.006980923137340575], [0.16708977624135188]),
        ],
    )
    gt, r = imu.yaw_rate(_syn())
    assert gt is not None and len(r) == len(gt)


def test_spans_on_flags() -> None:
    from engine.egosignals import imu

    t = np.arange(0.0, 10.0, 0.5)
    flag = (t >= 1.0) & (t <= 4.0) | (t >= 6.5)
    _chk(imu.spans(t, flag, 2.0), [[1.0, 4.5], [6.5, 9.5]])
    assert imu.spans(t, flag, 0.0) == [(1.0, 4.5), (6.5, 9.5)]
    assert imu.spans(t, flag, 100.0) == []
    assert imu.spans(t, np.zeros(len(t), dtype=bool), 0.0) == []
    assert imu.spans(np.array([]), np.array([], dtype=bool), 0.0) == []
    one = imu.spans(np.array([5.0]), np.array([True]), 0.0)
    assert one == [(5.0, 5.0)]


def test_estimate_bias_stationary_spans_real() -> None:
    from engine.egosignals import imu

    s = _real()
    gt, rate = imu.yaw_rate(s)
    st, flag = _stat_real()
    _chk(
        imu.estimate_bias(gt, rate, st, flag),
        [
            ("arr", (61552,), 396.79023861045243, 1185.384526865886, [-0.050367157187736725], [0.017044241422049057]),
            "stationary",
        ],
    )
    _chk(
        imu.estimate_bias(gt, rate, st, flag, {"biasMinStationaryS": 5.0}),
        [
            ("arr", (61552,), 396.79023861045243, 1185.384526865886, [-0.050367157187736725], [0.017044241422049057]),
            "stationary",
        ],
    )


def test_estimate_bias_lowest_fraction_and_none() -> None:
    from engine.egosignals import imu

    gt, rate = imu.yaw_rate(_real())
    _chk(
        imu.estimate_bias(gt, rate),
        [
            ("arr", (61552,), 57.7775395172065, 57.7775395172065, [0.0009386785078828715], [0.0009386785078828715]),
            "lowest",
        ],
    )
    _chk(
        imu.estimate_bias(gt, rate, None, None, {"biasLowFraction": 0.5}),
        [
            ("arr", (61552,), 138.85173376990434, 138.85173376990434, [0.002255844387995586], [0.002255844387995586]),
            "lowest",
        ],
    )
    st = np.arange(0.0, 1.0, 0.1)
    _chk(
        imu.estimate_bias(gt, rate, st, np.zeros(len(st), dtype=bool)),
        [
            ("arr", (61552,), 57.7775395172065, 57.7775395172065, [0.0009386785078828715], [0.0009386785078828715]),
            "lowest",
        ],
    )
    short = np.linspace(0.0, 1.0, 60)
    b, src = imu.estimate_bias(short, np.sin(short))
    assert src == "none" and b.tolist() == [0.0] * 60


def test_heading_series_real_stationary_and_lowest() -> None:
    from engine.egosignals import imu

    s = _real()
    st, flag = _stat_real()
    times = np.arange(0.0, 150.0, 0.25)
    _chk(
        imu.heading_series(s, times, st, flag),
        [
            ("arr", (600,), -1185.1823999995831, 21146.65233012197, [0.0], [-81.2689068824124]),
            {"biasDegPerS": 0.9766, "biasSource": "stationary"},
        ],
    )
    _chk(
        imu.heading_series(s, times),
        [
            ("arr", (600,), -10982.242610577268, 12224.553692069529, [0.0], [-37.79891876251691]),
            {"biasDegPerS": 0.0538, "biasSource": "lowest"},
        ],
    )
    _chk(
        imu.heading_series(s, times, st, flag, {"timeOffsetS": -0.10}),
        [
            ("arr", (600,), -1168.181469508172, 21085.812512676028, [0.0], [-77.50438394570503]),
            {"biasDegPerS": 0.9766, "biasSource": "stationary"},
        ],
    )
    _chk(
        imu.heading_series(s, [5.0, 60.0, 120.0], st, flag, {"timeOffsetS": 0.2, "yawSign": 1.0}),
        [
            ("arr", (3,), 36.55959554584371, 73.71396083445956, [0.0], [55.13677819015164]),
            {"biasDegPerS": -0.9766, "biasSource": "stationary"},
        ],
    )


def test_heading_series_synthetic_turn_and_empty_times() -> None:
    from engine.egosignals import imu

    st, flag = _stat_syn()
    _chk(
        imu.heading_series(_syn(), [0.0, 8.0, 11.9], st, flag),
        [
            ("arr", (3,), 138.95096566518262, 138.95096566518262, [0.0], [88.96744062615754]),
            {"biasDegPerS": -0.3992, "biasSource": "stationary"},
        ],
    )
    _chk(
        imu.heading_series(_syn(), [0.0, 8.0, 11.9]),
        [
            ("arr", (3,), 138.9419873357094, 138.9419873357094, [0.0], [88.96207167536699]),
            {"biasDegPerS": -0.3988, "biasSource": "lowest"},
        ],
    )
    _chk(
        imu.heading_series(_syn(), []),
        [("arr", (0,), 0.0, 0.0, None, None), {"biasDegPerS": -0.3988, "biasSource": "lowest"}],
    )


# ----------------------------------------------------------------------------------------------------------------
# gravity angles, vertical signals, motion energy
# ----------------------------------------------------------------------------------------------------------------


def test_gravity_angles_real_and_cfg() -> None:
    from engine.egosignals import imu

    _chk(
        imu.gravity_angles(_real()),
        [
            ("arr", (30776,), 2400591.0954025, 2400591.0954025, [0.0025535714285714285], [155.9983425]),
            ("arr", (30776,), -151248.3543607653, 154616.50950564165, [-12.106184112102698], [-3.093685473813323]),
            ("arr", (30776,), 12318.695781791477, 99726.98802907352, [-6.850807417563804], [1.5709977573266969]),
        ],
    )
    cfg = {
        "pitchSign": 1.0,
        "rollSign": 1.0,
        "gravityTauS": 1.0,
        "accelUpAxis": 1,
        "accelRightAxis": 0,
        "accelForwardAxis": 2,
    }
    _chk(
        imu.gravity_angles(_real(), cfg),
        [
            ("arr", (30776,), 2400591.0954025, 2400591.0954025, [0.0025535714285714285], [155.9983425]),
            ("arr", (30776,), 151606.66410650391, 154176.6012857104, [10.312801666293343], [4.103176966777022]),
            ("arr", (30776,), 2782636.0759587614, 2782636.0759587614, [84.94590103877732], [90.31013547902027]),
        ],
    )
    _chk(
        imu.gravity_angles(_syn()),
        [
            ("arr", (600,), 3594.0, 3594.0, [0.0], [11.98]),
            ("arr", (600,), -14.461535031498642, 681.1771982950347, [-0.20209023149993652], [1.1023824603519707]),
            ("arr", (600,), 41.3408429067665, 1096.841746644936, [-2.8080081215225707], [1.6675932651889418]),
        ],
    )


def test_vertical_signals_real_and_synthetic() -> None:
    from engine.egosignals import imu

    _chk(
        imu.vertical_signals(_real()),
        [
            ("arr", (9360,), 730025.9014285714, 730025.9014285714, [0.0025535714285714285], [155.98588690476188]),
            ("arr", (9360,), 92370.28254006604, 92370.28254006604, [11.805948087509334], [10.412065935148796]),
            ("arr", (9360,), 22.096587930098345, 8456.561840373033, [-1.7361770789811564], [-1.8034209005016606]),
        ],
    )
    _chk(
        imu.vertical_signals(_real(), 30.0),
        [
            ("arr", (4680,), 364973.9507142857, 364973.9507142857, [0.0025535714285714285], [155.96922023809523]),
            ("arr", (4680,), 46192.4899017599, 46192.4899017599, [11.805948087509334], [13.176436165563082]),
            ("arr", (4680,), 6.13827931932707, 4226.381095883246, [-1.7361770789811564], [-1.529562982186798]),
        ],
    )
    _chk(
        imu.vertical_signals(_syn(), 60.0),
        [
            ("arr", (719,), 4302.016666666666, 4302.016666666666, [0.0], [11.966666666666667]),
            ("arr", (719,), 7061.818030540078, 7061.818030540078, [9.814731081007375], [9.674174785606061]),
            ("arr", (719,), 2.526124061306848, 289.61424754969534, [0.6259052334972639], [0.5200655929566771]),
        ],
    )


def test_motion_energy_real_and_synthetic() -> None:
    from engine.egosignals import imu

    _chk(
        imu.motion_energy(_real()),
        [
            ("arr", (30776,), 2400591.0954025, 2400591.0954025, [0.0025535714285714285], [155.9983425]),
            ("arr", (30776,), 83252.63796430477, 83252.63796430477, [2.987425035958033], [4.098313401284714]),
        ],
    )
    _chk(
        imu.motion_energy(_real(), 2.5),
        [
            ("arr", (30776,), 2400591.0954025, 2400591.0954025, [0.0025535714285714285], [155.9983425]),
            ("arr", (30776,), 84849.02021037534, 84849.02021037534, [2.8287379795745937], [3.8971952815407103]),
        ],
    )
    _chk(
        imu.motion_energy(_syn()),
        [
            ("arr", (600,), 3594.0, 3594.0, [0.0], [11.98]),
            ("arr", (600,), 217.16176781344942, 217.16176781344942, [0.3635216812162354], [0.35305181920065987]),
        ],
    )


# ----------------------------------------------------------------------------------------------------------------
# GPS
# ----------------------------------------------------------------------------------------------------------------


def test_gps_good_thresholds() -> None:
    from engine.egosignals import imu

    s = _real()
    for fix, dop in ((3, 2.5), (2, 5.0), (0, 99.99), (4, 1.0)):
        g = imu.gps_good(s, fix, dop)
        assert g.dtype == np.bool_
    _chk(imu.gps_good(s, 3, 2.5), ("arr", (2805,), 345.0, 345.0, [0.0], [0.0]))
    _chk(imu.gps_good(s, 2, 5.0), ("arr", (2805,), 1995.0, 1995.0, [0.0], [0.0]))
    _chk(imu.gps_good(s, 0, 99.99), ("arr", (2805,), 2805.0, 2805.0, [1.0], [1.0]))
    _chk(imu.gps_good(s, 4, 1.0), ("arr", (2805,), 0.0, 0.0, [0.0], [0.0]))


def test_gps_xy_real_and_synthetic() -> None:
    from engine.egosignals import imu

    _chk(
        imu.gps_xy(_real()),
        [
            ("arr", (2805,), -68202.58594260184, 71122.53871427276, [22.05717916371148], [-52.44428545871258]),
            ("arr", (2805,), 205073.5537579519, 206800.63071796158, [-8.13574400003759], [138.77191599978104]),
        ],
    )
    _chk(
        imu.gps_xy(_walk(10.0)),
        [
            ("arr", (180,), 886.0047968265908, 886.0047968265908, [0.0], [9.844497742461295]),
            ("arr", (180,), 886.0047968274007, 886.0047968274007, [0.0], [9.844497742823393]),
        ],
    )
    nofix = _walk(5.0, fix=1)
    _chk(
        imu.gps_xy(nofix),
        [
            ("arr", (90,), 220.26376233948804, 220.26376233948804, [0.0], [4.8947502742705415]),
            ("arr", (90,), 220.26376233931643, 220.26376233931643, [0.0], [4.894750274259394]),
        ],
    )


def test_crop_boundaries_inclusive_and_per_stream() -> None:
    from engine.egosignals import imu

    s = _real()
    out = imu.crop(s, 20.0, 30.0)
    assert list(out) == [
        "gyro",
        "gyro_t",
        "accl",
        "accl_t",
        "gps",
        "gps_t",
        "gps_fix",
        "gps_dop",
        "gps_utc",
        "shut",
        "shut_t",
        "isog",
        "isog_t",
    ]
    _chk(
        out,
        {
            "gyro": (
                "arr",
                (3951, 3),
                39.87802929427431,
                2979.816777629827,
                [-0.010386151797603195, -0.043941411451398134, 0.07456724367509987],
                [-0.6471371504660453, -0.08921438082556592, -0.3203728362183755],
            ),
            "gyro_t": (
                "arr",
                (3951,),
                98770.27041729324,
                98770.27041729324,
                [20.000848214285714],
                [29.998640350877192],
            ),
            "accl": (
                "arr",
                (1975, 3),
                21568.490430622012,
                23915.76315789474,
                [7.954545454545454, 0.13875598086124402, 1.2033492822966507],
                [10.4688995215311, -0.35167464114832536, 3.0023923444976077],
            ),
            "accl_t": ("arr", (1975,), 49372.873185570716, 49372.873185570716, [20.002125], [29.9973040201005]),
            "gps": (
                "arr",
                (181, 5),
                21402.494710699997,
                24573.0088217,
                [41.3630665, -8.7583112, 97.642, 0.548, 0.56],
                [41.3631769, -8.7583244, 76.182, 0.748, 0.87],
            ),
            "gps_t": ("arr", (181,), 4524.547805555556, 4524.547805555556, [20.047805555555556], [29.946583333333333]),
            "gps_fix": ("arr", (181,), 543.0, 543.0, [3.0], [3.0]),
            "gps_dop": ("arr", (181,), 536.4099999999999, 536.4099999999999, [2.53], [2.53]),
            "gps_utc": ("arr", (181,), 324393713309.469, 324393713309.469, [1792230455.794], [1792230464.814]),
            "shut": (
                "arr",
                (300,),
                0.573838404729031,
                0.573838404729031,
                [0.0017593333031982183],
                [0.0017745000077411532],
            ),
            "shut_t": ("arr", (300,), 7497.49, 7497.49, [20.003316666666663], [29.97995]),
            "isog": ("arr", (300,), 424.30940866470337, 424.30940866470337, [1.4143646955490112], [1.4143646955490112]),
            "isog_t": ("arr", (300,), 7497.49, 7497.49, [20.003316666666663], [29.97995]),
        },
    )
    assert out["gyro_t"].min() >= 20.0 and out["gyro_t"].max() <= 30.0
    _chk(
        imu.crop(s, 0.0, 0.0),
        {
            "gyro": ("arr", (0, 3), 0.0, 0.0, None, None),
            "gyro_t": ("arr", (0,), 0.0, 0.0, None, None),
            "accl": ("arr", (0, 3), 0.0, 0.0, None, None),
            "accl_t": ("arr", (0,), 0.0, 0.0, None, None),
            "gps": ("arr", (0, 5), 0.0, 0.0, None, None),
            "gps_t": ("arr", (0,), 0.0, 0.0, None, None),
            "gps_fix": ("arr", (0,), 0.0, 0.0, None, None),
            "gps_dop": ("arr", (0,), 0.0, 0.0, None, None),
            "gps_utc": ("arr", (0,), 0.0, 0.0, None, None),
            "shut": ("arr", (0,), 0.0, 0.0, None, None),
            "shut_t": ("arr", (0,), 0.0, 0.0, None, None),
            "isog": ("arr", (0,), 0.0, 0.0, None, None),
            "isog_t": ("arr", (0,), 0.0, 0.0, None, None),
        },
    )
    _chk(
        imu.crop(s, 200.0, 300.0),
        {
            "gyro": ("arr", (0, 3), 0.0, 0.0, None, None),
            "gyro_t": ("arr", (0,), 0.0, 0.0, None, None),
            "accl": ("arr", (0, 3), 0.0, 0.0, None, None),
            "accl_t": ("arr", (0,), 0.0, 0.0, None, None),
            "gps": ("arr", (0, 5), 0.0, 0.0, None, None),
            "gps_t": ("arr", (0,), 0.0, 0.0, None, None),
            "gps_fix": ("arr", (0,), 0.0, 0.0, None, None),
            "gps_dop": ("arr", (0,), 0.0, 0.0, None, None),
            "gps_utc": ("arr", (0,), 0.0, 0.0, None, None),
            "shut": ("arr", (0,), 0.0, 0.0, None, None),
            "shut_t": ("arr", (0,), 0.0, 0.0, None, None),
            "isog": ("arr", (0,), 0.0, 0.0, None, None),
            "isog_t": ("arr", (0,), 0.0, 0.0, None, None),
        },
    )
    _chk(
        imu.crop(s, -5.0, 1e9),
        {
            "gyro": (
                "arr",
                (61552, 3),
                1446.8660452729694,
                43354.47137150465,
                [-0.00825565912117177, -0.08601864181091877, -0.2141145139813582],
                [0.06231691078561918, 0.4103861517976032, 0.02929427430093209],
            ),
            "gyro_t": (
                "arr",
                (61552,),
                4801105.125859649,
                4801105.125859649,
                [0.0012767857142857142],
                [155.99920175438598],
            ),
            "accl": (
                "arr",
                (30776, 3),
                326050.08851674636,
                369363.6291866029,
                [11.813397129186603, -0.7129186602870813, 1.6220095693779903],
                [9.368421052631579, -2.411483253588517, 4.598086124401914],
            ),
            "accl_t": ("arr", (30776,), 2400591.0954025, 2400591.0954025, [0.0025535714285714285], [155.9983425]),
            "gps": (
                "arr",
                (2805, 5),
                301077.3216293,
                350213.0009791,
                [41.3628997, -8.7580331, 58.243, 0.0, 0.0],
                [41.3642287, -8.7589248, 64.672, 1.069, 1.07],
            ),
            "gps_t": (
                "arr",
                (2805,),
                220630.66025000002,
                220630.66025000002,
                [1.0394999999999999],
                [155.9613611111111],
            ),
            "gps_fix": ("arr", (2805,), 8015.0, 8015.0, [0.0], [3.0]),
            "gps_dop": ("arr", (2805,), 31377.75, 31377.75, [99.99], [21.46]),
            "gps_utc": ("arr", (2805,), 5027206591549.586, 5027206591549.586, [1792230437.094], [1792230590.93]),
            "shut": (
                "arr",
                (4675,),
                7.186231942789163,
                7.186231942789163,
                [0.0015242500230669975],
                [0.0013422499177977443],
            ),
            "shut_t": (
                "arr",
                (4675,),
                364624.6770833334,
                364624.6770833334,
                [0.01668333333333333],
                [155.97248333333334],
            ),
            "isog": (
                "arr",
                (4675,),
                6612.1549516916275,
                6612.1549516916275,
                [1.4143646955490112],
                [1.4143646955490112],
            ),
            "isog_t": (
                "arr",
                (4675,),
                364624.6770833334,
                364624.6770833334,
                [0.01668333333333333],
                [155.97248333333334],
            ),
        },
    )
    exact = {"gyro_t": np.array([1.0, 2.0, 3.0, 4.0]), "gyro": np.arange(8.0).reshape(4, 2)}
    c = imu.crop(exact, 2.0, 3.0)
    assert c["gyro_t"].tolist() == [2.0, 3.0] and c["gyro"].tolist() == [[2.0, 3.0], [4.0, 5.0]]
    assert imu.crop({"foo": np.arange(3)}, 0.0, 1.0) == {}
    assert imu.crop(
        {"gyro": np.zeros((2, 2)), "gyro_t": np.array([0.0, 1.0]), "extra_t": np.array([0.0, 1.0])}, 0.0, 1.0
    ).keys() == {"gyro", "gyro_t"}


def test_wrap_deg_at_plus_minus_180() -> None:
    from engine.egosignals import imu

    assert imu.wrap_deg(180.0) == -180.0
    assert imu.wrap_deg(-180.0) == -180.0
    assert imu.wrap_deg(540.0) == -180.0
    assert imu.wrap_deg(-540.0) == -180.0
    assert imu.wrap_deg(0.0) == 0.0
    assert imu.wrap_deg(179.5) == 179.5
    assert imu.wrap_deg(-179.5) == -179.5
    assert imu.wrap_deg(190.0) == -170.0
    assert imu.wrap_deg(-190.0) == 170.0
    assert imu.wrap_deg(360.0) == 0.0
    got = imu.wrap_deg([180.0, -180.0, 270.0, -270.0, 725.0])
    assert isinstance(got, np.ndarray)
    _chk(got, ("arr", (5,), -355.0, 545.0, [-180.0], [5.0]))


def test_gps_course_offset_real_a() -> None:
    from engine.egosignals import imu

    ht = np.arange(0.0, 150.0, 0.1)
    heading = 20.0 * np.sin(ht / 30.0) + 0.1 * ht
    _chk(
        imu.gps_course_offset(_real(), ht, heading, {}),
        [
            ("arr", (1500,), -2362.918195825082, 2363.845718662584, [0.0], [-2.2342635167425726]),
            {"updates": 7, "meanOffsetDeg": -1.58},
        ],
    )


def test_gps_course_offset_real_b() -> None:
    from engine.egosignals import imu

    ht = np.arange(0.0, 150.0, 0.1)
    heading = 20.0 * np.sin(ht / 30.0) + 0.1 * ht
    _chk(
        imu.gps_course_offset(_real(), ht, heading, {"minFix": 2, "maxDop": 5.0}),
        [
            ("arr", (1500,), -26922.99646797631, 28130.41424823935, [0.0], [-1.1225500605202683]),
            {"updates": 51, "meanOffsetDeg": -17.95},
        ],
    )


def test_gps_course_offset_real_c() -> None:
    from engine.egosignals import imu

    ht = np.arange(0.0, 150.0, 0.1)
    heading = 20.0 * np.sin(ht / 30.0) + 0.1 * ht
    _chk(
        imu.gps_course_offset(
            _real(),
            ht,
            heading,
            {
                "minFix": 2,
                "maxDop": 5.0,
                "courseWindowS": 6.0,
                "courseMinTravelM": 4.0,
                "courseMinSpeedMps": 0.4,
                "courseTauS": 10.0,
            },
        ),
        [
            ("arr", (1500,), -21345.206073704092, 33476.93365489955, [0.0], [12.541113233559713]),
            {"updates": 56, "meanOffsetDeg": -14.23},
        ],
    )


def test_gps_course_offset_synthetic_straight_walk_and_early_outs() -> None:
    from engine.egosignals import imu

    ht = np.arange(0.0, 90.0, 0.1)
    heading = np.zeros(len(ht))
    _chk(
        imu.gps_course_offset(_walk(), ht, heading, {}),
        [
            ("arr", (900,), -5.240755740487657e-07, 5.240755740487657e-07, [0.0], [-9.89388126981794e-10]),
            {"updates": 77, "meanOffsetDeg": -0.0},
        ],
    )
    _chk(
        imu.gps_course_offset(_walk(course_deg=-170.0), ht, heading + 5.0, {"courseTauS": 5.0}),
        [
            ("arr", (900,), -1.849770114858984e-08, 5.285841098157107e-08, [0.0], [-9.202949513564818e-11]),
            {"updates": 77, "meanOffsetDeg": -0.0},
        ],
    )
    _chk(
        imu.gps_course_offset(_walk(), ht, 0.3 * ht, {"courseTauS": 8.0}),
        [
            ("arr", (900,), -7860.242645375591, 7860.242645375591, [0.0], [-21.446985014289822]),
            {"updates": 77, "meanOffsetDeg": -8.73},
        ],
    )
    _chk(
        imu.gps_course_offset(_walk(speed=0.2), ht, heading, {}),
        [("arr", (900,), 0.0, 0.0, [0.0], [0.0]), {"updates": 0, "meanOffsetDeg": 0.0}],
    )
    _chk(
        imu.gps_course_offset(_walk(dop=9.0), ht, heading, {}),
        [("arr", (900,), 0.0, 0.0, [0.0], [0.0]), {"updates": 0, "meanOffsetDeg": 0.0}],
    )
    _chk(
        imu.gps_course_offset({}, ht, heading, {}),
        [("arr", (900,), 0.0, 0.0, [0.0], [0.0]), {"updates": 0, "meanOffsetDeg": 0.0}],
    )
    _chk(
        imu.gps_course_offset(_walk(), np.array([]), np.array([]), {}),
        [("arr", (0,), 0.0, 0.0, None, None), {"updates": 0, "meanOffsetDeg": 0.0}],
    )
    _chk(
        imu.gps_course_offset(_walk(0.5), ht, heading, {}),
        [("arr", (900,), 0.0, 0.0, [0.0], [0.0]), {"updates": 0, "meanOffsetDeg": 0.0}],
    )
    quick_turn = np.where(ht > 40.0, 90.0, 0.0)
    _chk(
        imu.gps_course_offset(_walk(), ht, quick_turn, {"courseMaxTurnDeg": 10.0}),
        [
            ("arr", (900,), -3.888629862558446e-07, 3.888629862558446e-07, [0.0], [-5.901483746129088e-10]),
            {"updates": 28, "meanOffsetDeg": -0.0},
        ],
    )


def test_gps_step_length_real() -> None:
    from engine.egosignals import imu

    s = _real()
    mt, cad, stat = _step_inputs()
    cfg = {"minFix": 2, "maxDop": 5.0, "minS": 10.0}
    _chk(
        imu.gps_step_length(s, mt, cad, stat, cfg),
        {
            "stepM": 0.5,
            "raw": 0.4920106733544822,
            "windowsS": 64.45327777777695,
            "samples": 1159,
            "p10": 0.3427564512676892,
            "p90": 0.7733301990667081,
        },
    )
    _chk(
        imu.gps_step_length(s, mt, cad, None, cfg),
        {
            "stepM": 0.5,
            "raw": 0.4918477871297076,
            "windowsS": 71.84955555555462,
            "samples": 1292,
            "p10": 0.34812935641426346,
            "p90": 0.7637867515570642,
        },
    )
    cfg2 = {"minFix": 2, "maxDop": 5.0, "minS": 10.0, "rangeM": [0.3, 0.6], "minSpeedMps": 0.8, "minCadenceHz": 1.5}
    _chk(
        imu.gps_step_length(s, mt, cad, stat, cfg2),
        {
            "stepM": 0.5517939214558426,
            "raw": 0.5517939214558426,
            "windowsS": 45.76794444444385,
            "samples": 823,
            "p10": 0.43479121752727273,
            "p90": 0.8057981634829267,
        },
    )
    _chk(
        imu.gps_step_length(s, mt, cad, stat, {}),
        {
            "stepM": 0.5595120254493458,
            "raw": 0.5595120254493458,
            "windowsS": 10.288055555555422,
            "samples": 185,
            "p10": 0.42978780077327733,
            "p90": 0.6714156904646588,
        },
    )
    _chk(imu.gps_step_length(s, mt, cad, stat, {"minFix": 2, "maxDop": 5.0, "minS": 1000.0}), None)


def test_gps_step_length_synthetic_clamp_and_none_cases() -> None:
    from engine.egosignals import imu

    mt = np.arange(0.0, 90.0, 1 / 24)
    cad = np.full(len(mt), 1.75)
    nostat = np.zeros(len(mt), dtype=bool)
    cfg = {"minS": 30.0}
    _chk(
        imu.gps_step_length(_walk(), mt, cad, nostat, cfg),
        {
            "stepM": 0.7999999999999999,
            "raw": 0.7999999999999999,
            "windowsS": 90.00000000000256,
            "samples": 1620,
            "p10": 0.7999999999999999,
            "p90": 0.7999999999999999,
        },
    )
    _chk(
        imu.gps_step_length(_walk(speed=3.0), mt, cad, nostat, cfg),
        {
            "stepM": 1.1,
            "raw": 1.7142857142857142,
            "windowsS": 90.00000000000256,
            "samples": 1620,
            "p10": 1.7142857142857142,
            "p90": 1.7142857142857142,
        },
    )
    _chk(
        imu.gps_step_length(_walk(speed=0.6), mt, cad, nostat, cfg),
        {
            "stepM": 0.5,
            "raw": 0.34285714285714286,
            "windowsS": 90.00000000000256,
            "samples": 1620,
            "p10": 0.34285714285714286,
            "p90": 0.34285714285714286,
        },
    )
    assert imu.gps_step_length(_walk(dop=3.3), mt, cad, nostat, cfg) is None
    assert imu.gps_step_length(_walk(fix=2), mt, cad, nostat, cfg) is None
    assert imu.gps_step_length(_walk(speed=0.3), mt, cad, nostat, cfg) is None
    assert imu.gps_step_length(_walk(), mt, np.full(len(mt), np.nan), nostat, cfg) is None
    assert imu.gps_step_length(_walk(), mt, cad, np.ones(len(mt), dtype=bool), cfg) is None
    assert imu.gps_step_length(_walk(n_s=10.0), mt, cad, nostat, cfg) is None
    assert imu.gps_step_length({}, mt, cad, nostat, cfg) is None
    assert imu.gps_step_length(_syn(), mt, cad, nostat, cfg) is None
    assert imu.gps_step_length(_walk(), mt[:1], cad[:1], nostat[:1], cfg) is None
