"""Characterisation tests for engine.gait.scale (v26.3.0 p2-05).

Every expected literal was produced by running the legacy classes (collision._Scale, collision.GpsSpeedScale) in the
hackeye-rnd image on the pre-move code, not computed by hand. The input sequences come from np.random.default_rng(1)
(gaps, standing still, cadence and speed outliers); the same generator produced the literals.

The engine module is imported with importlib inside each test function: it does not exist yet, and a static
``from engine.gait import scale`` would fail mypy now and make a ``# type: ignore`` unused later.
"""

from __future__ import annotations

import importlib
import itertools
import math

import numpy as np
import pytest

import collision

_SCALE_ATTRS: list[str] = [
    "age_s",
    "applied",
    "from_gait",
    "hi",
    "k",
    "lo",
    "max_rate",
    "min_raw",
    "min_samples",
    "prior_step_m",
    "samples",
    "tau_min_s",
    "tau_s",
    "window_s",
]

_SCALE_INIT: dict[str, object] = {
    "window_s": 20.0,
    "min_samples": 18,
    "tau_min_s": 3.0,
    "tau_s": 40.0,
    "age_s": 0.0,
    "lo": 0.5,
    "hi": 4.0,
    "min_raw": 0.2,
    "prior_step_m": 0.7,
    "samples": [],
    "k": None,
    "applied": 1.0,
    "max_rate": 0.25,
    "from_gait": False,
}

_SCALE_INIT_PRIOR: dict[str, object] = {
    "window_s": 20.0,
    "min_samples": 18,
    "tau_min_s": 3.0,
    "tau_s": 40.0,
    "age_s": 30.0,
    "lo": 0.5,
    "hi": 4.0,
    "min_raw": 0.2,
    "prior_step_m": 0.7,
    "samples": [],
    "k": 1.3,
    "applied": 1.3,
    "max_rate": 0.25,
    "from_gait": False,
}

_DEFAULT_VALUES: list[float] = [
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.1331484530668263,
    1.161834242728283,
    1.191246216612358,
    1.2523227161918644,
    1.2840254166877416,
    1.3165306748676218,
    1.3840306459807517,
    1.9538362729346883,
    1.9538113612793493,
    1.9536902003857204,
    1.9531223340738078,
    1.9528028412388427,
    1.9525242883296556,
    1.9481217767519845,
    1.9473343626753323,
    1.9453706076418475,
    1.9453577837280496,
    1.9449693579893885,
    1.9447961791902186,
    1.943547874918081,
    1.9428603871796637,
    1.9394744903313186,
    1.9393156538968868,
    1.9392149861612957,
    1.9392516658990375,
    1.9392743892671318,
    1.93938183743698,
    1.9395214839707744,
    1.9395413025409685,
    1.9395331863793537,
    1.9393244650591897,
]

_PRIOR_VALUES: list[float] = [
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.3,
    1.308707079342853,
    1.310406805026375,
    1.3120998668700685,
    1.3154251107525528,
    1.3170816041801432,
    1.3187420953557056,
    1.3220449797401617,
    1.3523524906471243,
    1.3538393180153594,
    1.355312780187628,
    1.3582100549358693,
    1.3596463858141459,
    1.361077345760898,
    1.3874042081584208,
    1.3937490693009769,
    1.4172841754958037,
    1.4184470796570159,
    1.4241029042851605,
    1.4252091565511698,
    1.430562825381682,
    1.4358946449145915,
    1.4564440218725292,
    1.4584906214403117,
    1.478872044319322,
    1.4798828304081308,
    1.4808881818699986,
    1.4858875247455003,
    1.4869152214250496,
    1.487907737782233,
    1.488890560675426,
    1.4937269432096159,
]

_COLD_VALUES: list[float] = [
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0253151205244289,
    1.0512710963760241,
    1.0778841508846315,
    1.1051709180756475,
    1.133148453066826,
    1.1618342427282828,
    1.1912462166123579,
    1.2214027581601696,
    1.2523227161918642,
    1.2840254166877414,
    1.3165306748676215,
    1.349858807576003,
    1.3840306459807512,
    1.4190675485932571,
    1.4549914146182013,
    1.4918246976412703,
    1.5295904196633787,
    1.568312185490169,
    1.608014197485783,
    1.6487212707001282,
    1.6904588483790914,
    1.7332530178673953,
    1.7771305269140385,
]

_HOLD_K: float = 2.0

_HOLD_VALUE: float = 2.0

_CLAMP_HI: float = 4.0

_CLAMP_LO: float = 0.5

_GPS_ATTRS: list[str] = [
    "hi",
    "k",
    "lo",
    "min_s",
    "prev_t",
    "samples",
    "tau",
    "win_s",
]

_GPS_INIT: dict[str, object] = {
    "min_s": 20.0,
    "win_s": 60.0,
    "tau": 5.0,
    "lo": 0.5,
    "hi": 1.6,
    "k": 1.0,
    "samples": [],
    "prev_t": None,
}

_GPS_INIT_DEFAULT: dict[str, object] = {
    "min_s": 20.0,
    "win_s": 60.0,
    "tau": 40.0,
    "lo": 0.5,
    "hi": 1.6,
    "k": 1.0,
    "samples": [],
    "prev_t": None,
}

_GPS_PINNED: list[tuple[int, float]] = [
    (0, 1.0),
    (10, 1.0),
    (20, 1.0),
    (30, 1.0),
    (40, 1.0),
    (50, 1.0),
    (60, 1.0),
    (70, 1.0),
    (80, 1.0),
    (90, 1.0),
    (100, 1.0052280747796902),
    (110, 1.0474618105222475),
    (120, 1.075771930209456),
    (130, 1.09474877094146),
    (140, 1.1074693276945475),
    (150, 1.1159961718828764),
    (160, 1.1217118864717357),
    (170, 1.1255432445380664),
    (180, 1.1281114806534682),
    (190, 1.129833020804575),
    (200, 1.1309870036779166),
    (210, 1.1317605415306995),
    (220, 1.1322790594597871),
    (230, 1.1326266324218837),
    (240, 1.1328596175458372),
    (250, 1.133015792144851),
    (260, 1.1331204791092515),
    (270, 1.133190652880048),
    (280, 1.1332376917653184),
    (290, 1.1332692228730585),
    (299, 1.1332886049829463),
]

_GPS_TAU0_K: float = 1.1333333333333333

_GPS_CLIP_HI: float = 1.5997987224232586

_GPS_CLIP_LO: float = 0.5001677313139511


def _steps() -> list[tuple[float, float | None, float | None, float]]:
    rng = np.random.default_rng(1)
    out: list[tuple[float, float | None, float | None, float]] = []
    t = 0.0
    for _ in range(50):
        dt = float(rng.choice([0.1, 0.1, 0.1, 0.2, 0.5, 2.0]))
        t += dt
        r = float(rng.random())
        if r < 0.1:
            cad: float | None = None
        elif r < 0.15:
            cad = 6.0
        else:
            cad = float(1.9 + 0.1 * rng.standard_normal())
        r2 = float(rng.random())
        if r2 < 0.1:
            raw: float | None = 0.1
        elif r2 < 0.15:
            raw = 3.0
        else:
            raw = float(0.7 + 0.05 * rng.standard_normal())
        out.append((t, cad, raw, dt))
    return out


def test_facade_identity() -> None:
    scale = importlib.import_module("engine.gait.scale")

    assert collision._Scale is scale.Scale
    assert collision.GpsSpeedScale is scale.GpsSpeedScale


def test_scale_attributes_after_init() -> None:
    scale = importlib.import_module("engine.gait.scale")

    sc = scale.Scale({}, 0.7)
    assert sorted(vars(sc)) == _SCALE_ATTRS
    assert vars(sc) == _SCALE_INIT
    warm = scale.Scale({"scalePrior": 1.3}, 0.7)
    assert vars(warm) == _SCALE_INIT_PRIOR


def test_scale_update_sequence_from_default_rng() -> None:
    scale = importlib.import_module("engine.gait.scale")

    sc = scale.Scale({}, 0.7)
    values = []
    for t, cad, raw, dt in _steps():
        sc.update(t, cad, raw, dt)
        values.append(sc.value)
    assert values == pytest.approx(_DEFAULT_VALUES, rel=1e-12, abs=1e-12)


def test_scale_update_sequence_warm_start() -> None:
    scale = importlib.import_module("engine.gait.scale")

    sc = scale.Scale({"scalePrior": 1.3}, 0.7)
    values = []
    for t, cad, raw, dt in _steps():
        sc.update(t, cad, raw, dt)
        values.append(sc.value)
    assert values == pytest.approx(_PRIOR_VALUES, rel=1e-12, abs=1e-12)


def test_scale_cold_start_slews_in_log_space() -> None:
    scale = importlib.import_module("engine.gait.scale")

    sc = scale.Scale({}, 0.7)
    values = []
    t = 0.0
    for _ in range(40):
        t += 0.1
        sc.update(t, 2.0, 0.7, 0.1)
        values.append(sc.value)
    assert values == pytest.approx(_COLD_VALUES, rel=1e-12, abs=1e-12)
    assert sc.k == 2.0 and sc.from_gait is True
    # the applied scale moves towards k at most scaleMaxChangePerSecond (25 %/s) per step; here it saturates
    for a, b in itertools.pairwise(values):
        assert abs(math.log(b) - math.log(a)) <= 0.25 * 0.1 + 1e-12


def test_scale_is_held_without_cadence() -> None:
    scale = importlib.import_module("engine.gait.scale")

    sc = scale.Scale({}, 0.7)
    t = 0.0
    for _ in range(80):  # 8 s of walking at cadence 2 Hz, raw speed 0.7
        t += 0.1
        sc.update(t, 2.0, 0.7, 0.1)
    assert sc.k == _HOLD_K
    k0 = sc.k
    for _ in range(100):  # standing still: no cadence, nothing learnt, k held
        t += 0.1
        sc.update(t, None, 0.7, 0.1)
    assert sc.k == k0
    assert sc.value == pytest.approx(_HOLD_VALUE, rel=1e-12, abs=1e-12)


def test_scale_below_min_raw_speed_never_estimates() -> None:
    scale = importlib.import_module("engine.gait.scale")

    sc = scale.Scale({}, 0.7)
    t = 0.0
    for _ in range(40):
        t += 0.1
        sc.update(t, 2.0, 0.1, 0.1)
    assert sc.k is None
    assert sc.value == 1.0
    assert sc.from_gait is False
    assert len(sc.samples) == 40


def test_scale_clamps_to_scale_range() -> None:
    scale = importlib.import_module("engine.gait.scale")

    high = scale.Scale({}, 0.7)
    low = scale.Scale({}, 0.7)
    t = 0.0
    for _ in range(200):
        t += 0.1
        high.update(t, 4.0, 0.2, 0.1)  # raw k = 4 * 0.7 / 0.2 = 14, clipped to scaleRange hi
        low.update(t, 0.2, 2.0, 0.1)  # raw k = 0.2 * 0.7 / 2 = 0.07, clipped to scaleRange lo
    assert high.k == 4.0
    assert high.value == pytest.approx(_CLAMP_HI, rel=1e-12, abs=1e-12)
    assert low.k == 0.5
    assert low.value == pytest.approx(_CLAMP_LO, rel=1e-12, abs=1e-12)


def test_gps_speed_scale_attributes_after_init() -> None:
    scale = importlib.import_module("engine.gait.scale")

    g = scale.GpsSpeedScale({"speedMinS": 20.0, "speedTauS": 5.0})
    assert sorted(vars(g)) == _GPS_ATTRS
    assert vars(g) == _GPS_INIT
    assert vars(scale.GpsSpeedScale({})) == _GPS_INIT_DEFAULT


def test_gps_speed_scale_follows_gps_after_enough_good_moving_frames() -> None:
    scale = importlib.import_module("engine.gait.scale")

    g = scale.GpsSpeedScale({"speedMinS": 20.0, "speedTauS": 5.0})
    ks = [g.update(0.2 * i, 1.7, 1.5) for i in range(300)]
    for i, k in _GPS_PINNED:
        assert ks[i] == pytest.approx(k, rel=1e-12, abs=1e-12)
    assert ks[50] == 1.0  # < 20 s of samples: no change yet
    assert abs(ks[-1] - 1.7 / 1.5) < 0.02
    assert len(g.samples) == 300
    assert g.prev_t == pytest.approx(59.8, rel=1e-12)


def test_gps_speed_scale_without_good_fix_never_learns() -> None:
    scale = importlib.import_module("engine.gait.scale")

    g = scale.GpsSpeedScale({"speedMinS": 20.0, "speedTauS": 5.0})
    assert all(g.update(0.2 * i, None, 1.5) == 1.0 for i in range(300))
    assert g.k == 1.0
    assert g.samples == []
    slow = scale.GpsSpeedScale({"speedMinS": 20.0, "speedTauS": 5.0})
    assert all(slow.update(0.2 * i, 0.2, 1.5) == 1.0 for i in range(150))  # GPS speed <= 0.3 m/s is not a sample
    assert slow.samples == []


def test_gps_speed_scale_zero_tau_jumps_to_target() -> None:
    scale = importlib.import_module("engine.gait.scale")

    g = scale.GpsSpeedScale({"speedMinS": 20.0, "speedTauS": 0.0})
    ks = [g.update(0.2 * i, 1.7, 1.5) for i in range(300)]
    assert ks[99] == 1.0  # the span is 19.8 s: not enough yet
    assert ks[100] == pytest.approx(_GPS_TAU0_K, rel=1e-12, abs=1e-12)
    assert ks[-1] == pytest.approx(ks[100], rel=1e-12, abs=1e-12)


def test_gps_speed_scale_clips_to_speed_range() -> None:
    scale = importlib.import_module("engine.gait.scale")

    high = scale.GpsSpeedScale({"speedMinS": 20.0, "speedTauS": 5.0})
    low = scale.GpsSpeedScale({"speedMinS": 20.0, "speedTauS": 5.0})
    kh = [high.update(0.2 * i, 5.0, 1.0) for i in range(300)]
    kl = [low.update(0.2 * i, 0.5, 2.0) for i in range(300)]
    # target 5.0 is clipped to speedMaxScale 1.6; target 0.25 to speedMinScale 0.5
    assert kh[-1] == pytest.approx(_GPS_CLIP_HI, rel=1e-12, abs=1e-12)
    assert kl[-1] == pytest.approx(_GPS_CLIP_LO, rel=1e-12, abs=1e-12)
