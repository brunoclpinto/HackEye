"""Characterisation tests for engine.core.groundgeom (v26.3.0 p1-08).

Every expected literal was produced by running the legacy functions (groundfuse.py / collision.py) in the
hackeye-rnd image on the pre-move code, not computed by hand. After the move the legacy names are the engine
objects, so the expected values are pinned literals instead of a legacy-vs-engine comparison.

The engine module is imported inside each test function: it does not exist yet.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import types
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

import collision
import groundfuse
from common_paths import find_common_dir

NAN = float("nan")
HORIZON = 0.45
ROWS = [20.5, 60.0, 67.5, 100.0, 134.0]
COLS = [0.5, 60.5, 120.0, 200.5, 239.5]
FWD = [0.5, 2.0, 5.0, 10.0, 30.0]
RIGHT = [-3.0, -0.5, 0.0, 1.0, 4.0]
REP = {"ref": 1.45}
GH, GW = 135, 240

GEOS: dict[str, tuple[int, int, float, str, float, float]] = {
    "fish": (135, 240, 118.0, "fisheye", 1.3, 0.0),
    "fish_roll": (135, 240, 118.0, "fisheye", 1.3, 0.05),
    "rect": (135, 240, 90.0, "rectilinear", 1.3, 0.0),
    "rect_roll": (135, 240, 90.0, "rectilinear", 1.3, 0.05),
    "fish200": (135, 240, 200.0, "fisheye", 1.3, 0.0),
}
EXP: dict[str, dict[str, Any]] = {
    "fish": {
        "f": (116.53378884016742, 72.10327428330723),
        "pitch": 0.05792311455056182,
        "ray_dir": [
            [-1.8371238574243907, -0.5610031002442215, 0.0, 0.8551623620563468, 2.0826739182149274],
            [-0.7225508058489235, -0.07071467650137245, 0.0, 0.3452518853022518, 1.158977536077763],
        ],
        "ray_dir_s": [-0.5772250503567206, 0.3152909938923264],
        "ground_z": [NAN, NAN, 22.45609943966668, 3.229303373747531, 1.070025273209339],
        "ground_z_s": 3.4885004202254932,
        "ground_z_h": [NAN, NAN, 29.365668498025656, 4.2229351810544635, 1.3992638188122124],
        "ground_point": [
            [NAN, NAN, 22.418438885082924, 3.1593438795978703, 0.9964384252022725],
            [NAN, NAN, 0.0, 2.761578700890468, 2.2285137283438923],
        ],
        "ground_point_s": [4.4709690719035216, -2.633234394036901],
        "ground_pixel": [
            [130.88302599281093, 127.02320400368711, 90.39247362312965, 75.78779162791614, 65.8066096962879],
            [-29.856496687982144, 94.8217964315863, 120.0, 131.52823416942587, 135.43296567672954],
        ],
        "ground_pixel_s": [119.36490879820563, 154.0437802663296],
        "lateral_at": [-0.883103623276203, -1.1193012415340082, 0.0, 8.740988021987556, 67.09437347997235],
        "lateral_at_s": -2.94481392253939,
        "ground_m": [[NAN, NAN, 32.56134418751669, 4.68248989193392, 1.5515366461535414], None],
        "ground_m_sig": [
            [NAN, NAN, 32.56134418751669, 4.68248989193392, 1.5515366461535414],
            [NAN, NAN, 2.914103544064636, 0.07916605432233588, 0.02055002373703959],
        ],
        "ground_m_none": [[NAN, NAN, NAN, NAN, NAN], [NAN, NAN, NAN, NAN, NAN]],
    },
    "fish_roll": {
        "f": (116.53378884016742, 72.10327428330723),
        "pitch": 0.05792311455056182,
        "ray_dir": [
            [-1.7987154419482267, -0.5567677316645162, 0.0, 0.8368382293672088, 2.0221463836784213],
            [-0.8134657297316203, -0.09866477047797281, 0.0, 0.3875607147946043, 1.2616194282436741],
        ],
        "ray_dir_s": [-0.5922616513035371, 0.2860477337510943],
        "ground_z": [NAN, NAN, 22.45609943966668, 2.922652165429354, 0.9867964144075849],
        "ground_z_s": 3.785025231530714,
        "ground_z_h": [NAN, NAN, 29.365668498025656, 3.821929754792232, 1.2904260803791494],
        "ground_point": [
            [NAN, NAN, 22.418438885082924, 2.8521775303892754, 0.9130697509122094],
            [NAN, NAN, 0.0, 2.445787063174139, 1.9954468008211306],
        ],
        "ground_point_s": [4.859383686982841, -2.9314869227294515],
        "ground_pixel": [
            [138.29351692922032, 128.20720119630255, 90.36386399218563, 75.20126247953472, 65.03739918931139],
            [-26.501384104017063, 97.82818291820273, 121.14414681423493, 131.92804381925995, 135.32904424766966],
        ],
        "ground_pixel_s": [117.59861131102438, 156.59339946185952],
        "lateral_at": [-0.8602877109827576, -1.109060734864505, 0.0, 8.57515718118826, 65.56279404155808],
        "lateral_at_s": -3.016315557240544,
        "ground_m": [[NAN, NAN, 32.56134418751669, 4.237845639872563, 1.430854800890998], None],
        "ground_m_sig": [
            [NAN, NAN, 32.56134418751669, 4.237845639872563, 1.430854800890998],
            [NAN, NAN, 2.9104039038710354, 0.06528147650175625, 0.018006775382549373],
        ],
        "ground_m_none": [[NAN, NAN, NAN, NAN, NAN], [NAN, NAN, NAN, NAN, NAN]],
    },
    "rect": {
        "f": (152.78874536821954, 120.00000000000001),
        "pitch": 0.056190786201237096,
        "ray_dir": [
            [-0.9958333333333332, -0.4958333333333333, 0.0, 0.6708333333333333, 0.9958333333333332],
            [-0.3916666666666666, -0.06249999999999999, 0.0, 0.2708333333333333, 0.5541666666666666],
        ],
        "ray_dir_s": [-0.4958333333333333, 0.2708333333333333],
        "ground_z": [NAN, NAN, 23.147644735266773, 3.9808051455554323, 2.1330594124648563],
        "ground_z_s": 3.9808051455554323,
        "ground_z_h": [NAN, NAN, 30.269996961502702, 5.205668267264795, 2.7893853855309656],
        "ground_point": [
            [NAN, NAN, 23.111111111111114, 3.913972929936306, 2.0633063139931744],
            [NAN, NAN, 0.0, 2.6704567851434358, 2.1241716649129194],
        ],
        "ground_point_s": [5.11827229299363, -2.581143849185461],
        "ground_pixel": [
            [333.80316248636865, 136.236810370817, 91.59757299494888, 76.28575417261277, 65.9537689382131],
            [-509.1281682934682, 91.01243441236508, 120.0, 131.93171868886083, 135.98632583979634],
        ],
        "ground_pixel_s": [126.8579648697759, 158.82566325628306],
        "lateral_at": [-0.4879535378966482, -0.9897546690409601, 0.0, 6.822880058056235, 30.884968225613825],
        "lateral_at_s": -2.521499151890348,
        "ground_m": [[NAN, NAN, 33.564084866136824, 5.772167461055377, 3.0929361480740414], None],
        "ground_m_sig": [
            [NAN, NAN, 33.564084866136824, 5.772167461055377, 3.0929361480740414],
            [NAN, NAN, 3.0072350800918715, 0.08825757892735075, 0.025336330494115045],
        ],
        "ground_m_none": [[NAN, NAN, NAN, NAN, NAN], [NAN, NAN, NAN, NAN, NAN]],
    },
    "rect_roll": {
        "f": (152.78874536821954, 120.00000000000001),
        "pitch": 0.056190786201237096,
        "ray_dir": [
            [-0.975013626345638, -0.49208997269975335, 0.0, 0.6564589413374811, 0.9668920113391529],
            [-0.4409481080534123, -0.08720322937139671, 0.0, 0.3040225549093834, 0.6032450253675943],
        ],
        "ray_dir_s": [-0.5087496957899794, 0.245713524093592],
        "ground_z": [NAN, NAN, 23.147644735266773, 3.6140832783841996, 1.9743212098271805],
        "ground_z_s": 4.311961255145475,
        "ground_z_h": [NAN, NAN, 30.269996961502702, 4.726108902502414, 2.5818046590047743],
        "ground_point": [
            [NAN, NAN, 23.111111111111114, 3.5466713555064966, 1.904317180891514],
            [NAN, NAN, 0.0, 2.3724972828335846, 1.9089554055993523],
        ],
        "ground_point_s": [5.552007148184318, -2.8686963542944963],
        "ground_pixel": [
            [364.91365609335475, 137.5996817038222, 91.5674573035919, 75.67843687962248, 65.15671803924616],
            [-495.03231106968633, 94.48407000178304, 121.20437667972708, 132.35591184242284, 135.88906775128675],
        ],
        "ground_pixel_s": [124.84330847427181, 161.7438030610095],
        "lateral_at": [-0.47645966818225166, -0.9809241082215275, 0.0, 6.689363194450168, 30.073069099324098],
        "lateral_at_s": -2.5834768199394795,
        "ground_m": [[NAN, NAN, 33.564084866136824, 5.240420753657089, 2.862765754249412], None],
        "ground_m_sig": [
            [NAN, NAN, 33.564084866136824, 5.240420753657089, 2.862765754249412],
            [NAN, NAN, 3.003417069881932, 0.07265162568349051, 0.021678343866159244],
        ],
        "ground_m_none": [[NAN, NAN, NAN, NAN, NAN], [NAN, NAN, NAN, NAN, NAN]],
    },
    "fish200": {
        "f": (68.75493541569878, -21.159237685015793),
        "pitch": 0.09817477042468105,
        "ray_dir": [
            [NAN, -1.181378846366264, 0.0, 2.913307305556883, NAN],
            [NAN, -0.14891329996213412, 0.0, 1.1761799680819713, NAN],
        ],
        "ray_dir_s": [-1.325824422398978, 0.7241898105540636],
        "ground_z": [NAN, NAN, 13.262986408591825, 1.0248054309201051, NAN],
        "ground_z_s": 1.5878448687053173,
        "ground_z_h": [NAN, NAN, 17.343905303543153, 1.3401301788955222, NAN],
        "ground_point": [
            [NAN, NAN, 13.199121503891519, 0.9017252018049355, NAN],
            [NAN, NAN, 0.0, 2.985573148673912, NAN],
        ],
        "ground_point_s": [1.9190240071715396, -2.752958430805918],
        "ground_pixel": [
            [103.87995947368074, 99.89480538400275, 78.23905943764649, 69.63132553250006, 63.749605543175484],
            [32.31854268331935, 105.24431432591496, 120.0, 126.79699616464352, 129.10967578625187],
        ],
        "ground_pixel_s": [95.41248724110012, 139.96940464314773],
        "lateral_at": [NAN, -2.3398719144789846, 0.0, 33.10956755669963, NAN],
        "lateral_at_s": -7.172808731203731,
        "ground_m": [[NAN, NAN, 19.231330292458146, 1.4859678748341523, NAN], None],
        "ground_m_sig": [
            [NAN, NAN, 19.231330292458146, 1.4859678748341523, NAN],
            [NAN, NAN, 1.7174830537529011, 0.03727368250611423, NAN],
        ],
        "ground_m_none": [[NAN, NAN, NAN, NAN, NAN], [NAN, NAN, NAN, NAN, NAN]],
    },
}

FG: dict[str, dict[str, Any]] = {
    "fish_body": {
        "lat": 0.15,
        "scalars": [135, 240, 72.10327428330723, 0.45, 1.4097600000000001, 118.0, "fisheye", 0.15],
        "lens": [135, 240, 118.0, True, 1.4097600000000001, 0.0],
        "below": [75, [60, 134]],
        "lane": [2378, [88, 138], [109, 125]],
        "lane_region": [2353, [88, 138], [109, 125]],
        "region_dilated": [9779, [18, 181], [58, 181]],
        "floor_below": [9200, [20, 179], [60, 179]],
        "shapes": [[135], [135, 240], [135, 240]],
        "dtypes": ["bool", "bool"],
        "ground_dist": [
            2.590838118333205,
            3.707643152239241,
            4.0260901765969495,
            2.590838118333205,
            1.5092256200709047,
            2.299459919802329,
            2.5295753282414113,
            1.5092256200709047,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        "lateral_of": [
            -8.922596529587492,
            -2.94481392253939,
            0.022436778697789792,
            8.922596529587492,
            -9.954209475631322,
            -3.1402636667977735,
            0.023737407424976823,
            9.954209475631322,
        ],
    },
    "rect_plain": {
        "lat": 0.0,
        "scalars": [135, 240, 120.00000000000001, 0.45, 1.3, 90.0, "rectilinear", 0.0],
        "lens": None,
        "below": [75, [60, 134]],
        "lane": [2576, [92, 147], [111, 128]],
        "lane_region": [0, None, None],
        "region_dilated": [0, None, None],
        "floor_below": [0, None, None],
        "shapes": [[135], [135, 240], [135, 240]],
        "dtypes": ["bool", "bool"],
        "ground_dist": [
            3.974522292993632,
            3.974522292993632,
            3.974522292993632,
            3.974522292993632,
            2.632911392405064,
            2.632911392405064,
            2.632911392405064,
            2.632911392405064,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        "lateral_of": [
            -4.979166666666666,
            -2.4791666666666665,
            0.020833333333333256,
            4.979166666666666,
            -4.979166666666666,
            -2.4791666666666665,
            0.020833333333333256,
            4.979166666666666,
        ],
    },
    "fish_nolens": {
        "lat": -0.15,
        "scalars": [135, 240, 72.10327428330723, 0.45, 1.2816, 118.0, "fisheye", -0.15],
        "lens": None,
        "below": [75, [60, 134]],
        "lane": [2616, [99, 154], [113, 131]],
        "lane_region": [2589, [99, 154], [113, 131]],
        "region_dilated": [9779, [18, 181], [58, 181]],
        "floor_below": [9200, [20, 179], [60, 179]],
        "shapes": [[135], [135, 240], [135, 240]],
        "dtypes": ["bool", "bool"],
        "ground_dist": [
            2.354332645133416,
            2.354332645133416,
            2.354332645133416,
            2.354332645133416,
            1.5596212037381698,
            1.5596212037381698,
            1.5596212037381698,
            1.5596212037381698,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        "lateral_of": [
            -8.286724922536957,
            -4.1260262166606605,
            0.03467248921563568,
            8.286724922536957,
            -8.286724922536957,
            -4.1260262166606605,
            0.03467248921563568,
            8.286724922536957,
        ],
    },
}

BP = (9, 119)
BP2 = (9, 119)
BP3 = (5, 100)
BP4 = (7, 120)
BP5 = (7, 119)
EF = [
    (-2.8301270189221936, 5.098076211353316),
    (2.0, 1.0),
    (-4.801359313118294, -0.09720466209100342),
    (1.0, 6.123233995736766e-17),
]

FIELDS = ["gh", "gw", "f", "horizon", "camera_height_m", "hfov_deg", "projection", "below", "lane", "lane_region",
          "region_dilated", "floor_below", "lateral_offset_m", "lens"]  # fmt: skip
GEO_NAMES = list(GEOS)


def _gg() -> Any:
    return importlib.import_module("engine.core.groundgeom")


def _geo(name: str) -> Any:
    gh, gw, hfov, projection, cam_h, roll = GEOS[name]
    geo = _gg().Geometry(gh, gw, hfov, projection, cam_h)
    geo.roll = roll
    return geo


def _same(actual: Any, expected: Any) -> None:
    """Exact (bit for bit, nan == nan) comparison of a value / nested tuple against a pinned literal."""
    if expected is None:
        assert actual is None
    elif isinstance(actual, tuple):
        assert len(actual) == len(expected)
        for a, e in zip(actual, expected, strict=True):
            _same(a, e)
    else:
        np.testing.assert_array_equal(np.asarray(actual, dtype=np.float64), np.asarray(expected, dtype=np.float64))


def _config() -> dict[str, Any]:
    with open(find_common_dir() / "config" / "collision.json") as fh:
        cfg: dict[str, Any] = json.load(fh)
    return cfg


def _region() -> Any:
    mask: npt.NDArray[np.bool_] = np.zeros((GH, GW), dtype=bool)
    mask[70:135, 60:180] = True
    mask[100:135, 20:60] = True
    left = np.full(GH, np.nan)
    right = np.full(GH, np.nan)
    for r in range(GH):
        c = np.flatnonzero(mask[r])
        if len(c):
            left[r] = c[0] / GW
            right[r] = (c[-1] + 1) / GW
    return collision.Region("walk", "sidewalk", mask, left, right)


FG_CASES: dict[str, dict[str, Any]] = {
    "fish_body": {
        "kw": {"mount": "chest", "hfov_deg": 118.0, "user_height_m": 1.78, "camera_location": "chest",
               "camera_side": "right", "projection": "fisheye", "distance_source": "depth"},
        "region": True, "lens": True, "k": 1.1,
    },
    "rect_plain": {
        "kw": {"mount": "chest", "hfov_deg": 90.0, "projection": "rectilinear"},
        "region": False, "lens": True, "k": 1.0,
    },
    "fish_nolens": {
        "kw": {"mount": "chest", "hfov_deg": 118.0, "user_height_m": 1.78, "camera_location": "chest",
               "camera_side": "left", "projection": "fisheye"},
        "region": True, "lens": False, "k": 1.0,
    },
}  # fmt: skip


def _frame_geo(name: str) -> tuple[Any, Any]:
    """The FrameGeo of one case, built exactly like run_collision builds it (config + resolve_settings + grid size)."""
    gg = _gg()
    case = FG_CASES[name]
    cfg = _config()
    s = collision.resolve_settings(cfg, **case["kw"])
    f = collision.focal_px(GW, s.hfov_deg)
    lat = gg.walking_axis_offset_m(s)
    geo = gg.frame_geometry(
        GH, GW, s.horizon_default, s.camera_height_m * case["k"], f, s.hfov_deg, cfg["geometry"]["laneHalfWidthM"],
        _region() if case["region"] else None, cfg["roles"]["boundaryMarginPx"], s.projection, lat, case["lens"],
    )  # fmt: skip
    return geo, s


def test_facade_identity() -> None:
    gg = _gg()

    for name in ("Geometry", "ray_dir", "ground_z", "ground_point", "ground_pixel", "lateral_at", "ground_m"):
        assert getattr(groundfuse, name) is getattr(gg, name)
    assert groundfuse._pitch is gg.pitch
    assert collision._FrameGeo is gg.FrameGeo
    assert collision._walking_axis_offset_m is gg.walking_axis_offset_m
    assert collision._frame_geometry is gg.frame_geometry
    assert collision._ground_dist is gg.ground_dist
    assert collision._lateral_of is gg.lateral_of
    assert collision._bottom_point is gg.bottom_point
    assert collision._ego_frame is gg.ego_frame


@pytest.mark.parametrize("name", GEO_NAMES)
def test_geometry_fields(name: str) -> None:
    geo = _geo(name)
    gh, gw, hfov, projection, cam_h, roll = GEOS[name]

    got = (geo.gh, geo.gw, geo.hfov, geo.fisheye, geo.cam_h, geo.roll)
    assert got == (gh, gw, hfov, projection == "fisheye", cam_h, roll)
    assert (geo.f_eq, geo.f_pin) == tuple(EXP[name]["f"])
    assert _gg().Geometry(gh, gw, hfov, projection, cam_h).roll == 0.0


@pytest.mark.parametrize("name", GEO_NAMES)
def test_pitch(name: str) -> None:
    assert _gg().pitch(_geo(name), HORIZON) == EXP[name]["pitch"]


@pytest.mark.parametrize("name", GEO_NAMES)
def test_ray_dir(name: str) -> None:
    gg = _gg()
    geo = _geo(name)

    _same(gg.ray_dir(geo, ROWS, COLS), EXP[name]["ray_dir"])
    _same(gg.ray_dir(geo, 100.0, 60.5), EXP[name]["ray_dir_s"])


@pytest.mark.parametrize("name", GEO_NAMES)
def test_ground_z(name: str) -> None:
    gg = _gg()
    geo = _geo(name)

    _same(gg.ground_z(geo, ROWS, COLS, HORIZON), EXP[name]["ground_z"])
    _same(gg.ground_z(geo, 100.0, 60.5, HORIZON), EXP[name]["ground_z_s"])
    _same(gg.ground_z(geo, ROWS, COLS, HORIZON, 1.7), EXP[name]["ground_z_h"])


@pytest.mark.parametrize("name", GEO_NAMES)
def test_ground_point(name: str) -> None:
    gg = _gg()
    geo = _geo(name)

    _same(gg.ground_point(geo, ROWS, COLS, HORIZON), EXP[name]["ground_point"])
    _same(gg.ground_point(geo, 100.0, 60.5, HORIZON, 1.7), EXP[name]["ground_point_s"])


@pytest.mark.parametrize("name", GEO_NAMES)
def test_ground_pixel(name: str) -> None:
    gg = _gg()
    geo = _geo(name)

    _same(gg.ground_pixel(geo, FWD, RIGHT, HORIZON), EXP[name]["ground_pixel"])
    _same(gg.ground_pixel(geo, 3.0, 1.0, HORIZON, 1.7), EXP[name]["ground_pixel_s"])


@pytest.mark.parametrize("name", GEO_NAMES)
def test_lateral_at(name: str) -> None:
    gg = _gg()
    geo = _geo(name)

    _same(gg.lateral_at(geo, ROWS, COLS, FWD, HORIZON), EXP[name]["lateral_at"])
    _same(gg.lateral_at(geo, 100.0, 60.5, 5.0, HORIZON), EXP[name]["lateral_at_s"])


@pytest.mark.parametrize("name", GEO_NAMES)
def test_ground_m(name: str) -> None:
    gg = _gg()
    geo = _geo(name)

    _same(gg.ground_m(geo, ROWS, COLS, HORIZON, REP), EXP[name]["ground_m"])
    _same(gg.ground_m(geo, ROWS, COLS, HORIZON, REP, 0.6), EXP[name]["ground_m_sig"])
    _same(gg.ground_m(geo, ROWS, COLS, HORIZON, None), EXP[name]["ground_m_none"])


def test_rays_above_the_horizon_and_beyond_90_degrees_are_nan() -> None:
    gg = _gg()
    z = gg.ground_z(_geo("fish"), ROWS, COLS, HORIZON)
    xn, _yn = gg.ray_dir(_geo("fish200"), ROWS, COLS)

    assert bool(np.isnan(z[0])) and not bool(np.isnan(z[-1]))
    assert bool(np.isnan(xn[0])) and bool(np.isnan(xn[-1]))  # the 200 deg fisheye's corner rays point backwards


def test_frame_geo_field_order() -> None:
    assert [f.name for f in dataclasses.fields(_gg().FrameGeo)] == FIELDS


@pytest.mark.parametrize("name", list(FG_CASES))
def test_frame_geometry(name: str) -> None:
    gg = _gg()
    geo, s = _frame_geo(name)
    exp = FG[name]

    assert isinstance(geo, gg.FrameGeo)
    assert gg.walking_axis_offset_m(s) == exp["lat"]
    assert [geo.gh, geo.gw, geo.f, geo.horizon, geo.camera_height_m, geo.hfov_deg, geo.projection,
            geo.lateral_offset_m] == exp["scalars"]  # fmt: skip
    if exp["lens"] is None:
        assert geo.lens is None
    else:
        lens = geo.lens
        assert isinstance(lens, groundfuse.Geometry)
        assert [lens.gh, lens.gw, lens.hfov, lens.fisheye, lens.cam_h, lens.roll] == exp["lens"]

    def span(a: npt.NDArray[np.bool_]) -> list[int] | None:
        idx = np.flatnonzero(a)
        return None if not len(idx) else [int(idx[0]), int(idx[-1])]

    assert [int(geo.below.sum()), span(geo.below)] == exp["below"]
    for field in ("lane", "lane_region", "region_dilated", "floor_below"):
        arr = getattr(geo, field)
        assert [int(arr.sum()), span(arr[120]), span(arr[80])] == exp[field]
    assert [list(geo.below.shape), list(geo.lane.shape), list(geo.floor_below.shape)] == exp["shapes"]
    assert [str(geo.below.dtype), str(geo.lane.dtype)] == exp["dtypes"]


@pytest.mark.parametrize("name", list(FG_CASES))
def test_ground_dist_and_lateral_of(name: str) -> None:
    gg = _gg()
    geo, s = _frame_geo(name)
    exp = FG[name]
    ys = [100.0 / GH, 120.0 / GH, s.horizon_default, 0.3]
    cols = [0, 60, 120, 239]

    assert [gg.ground_dist(geo, y, c) for y in ys for c in cols] == exp["ground_dist"]
    assert [gg.lateral_of(geo, y * GH, c, 5.0) for y in ys[:2] for c in cols] == exp["lateral_of"]


def test_walking_axis_offset_m() -> None:
    gg = _gg()

    assert gg.walking_axis_offset_m(types.SimpleNamespace(lateral_offset_m=0.3)) == 0.3
    assert gg.walking_axis_offset_m(types.SimpleNamespace()) == 0.0
    assert gg.walking_axis_offset_m(types.SimpleNamespace(lateral_offset_m=-0.15), 12.0) == -0.15


def test_bottom_point() -> None:
    gg = _gg()
    rows = np.array([5, 9, 9, 9, 9, 3, 9])
    cols = np.array([100, 10, 119, 121, 200, 120, 80])

    assert gg.bottom_point(rows, cols, np.array([1, 1, 1, 1, 1, 1, 0], dtype=bool), 240) == BP
    assert gg.bottom_point(rows, cols, np.array([1, 1, 1, 0, 0, 1, 1], dtype=bool), 240) == BP2
    assert gg.bottom_point(rows, cols, np.array([1, 0, 0, 0, 0, 0, 0], dtype=bool), 240) == BP3
    # tie: columns 119 and 120 are both 0.5 from the centre; the first of them in array order wins
    sel = np.array([1, 1, 1], dtype=bool)
    assert gg.bottom_point(np.array([7, 7, 7]), np.array([120, 119, 50]), sel, 240) == BP4
    assert gg.bottom_point(np.array([7, 7, 7]), np.array([119, 120, 50]), sel, 240) == BP5


def test_ego_frame() -> None:
    gg = _gg()
    got = [
        gg.ego_frame((1.0, 2.0, 30.0), 4.0, -3.0),
        gg.ego_frame((0.0, 0.0, 0.0), 1.0, 2.0),
        gg.ego_frame((-2.5, 7.25, 217.5), 0.5, 11.0),
        gg.ego_frame((0.0, 0.0, 90.0), 1.0, 0.0),
    ]

    assert got == EF
