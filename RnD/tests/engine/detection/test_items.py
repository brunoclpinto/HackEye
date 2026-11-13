"""engine.detection.items: characterisation of detect_items, split_people, tree_trunk and lane_part_item.

Every expected literal was produced by running the legacy ``collision.detect_items`` / ``_split_people`` /
``_tree_trunk`` / ``_lane_part_item`` in the hackeye-rnd image on the pre-move code (same arguments as
``run_collision`` builds: the real ``collision.json``, ``resolve_settings`` from the fixture's settings,
``walking_region``, ``frame_geometry`` with the preset horizon), not computed by hand. The engine module is
imported inside each test: it does not exist yet. Fixtures are read from the npz directly.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt
import pytest

import collision
from common_paths import find_common_dir

if TYPE_CHECKING:
    from collections.abc import Callable

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

_CFG: dict[str, Any] = json.loads((find_common_dir() / "config" / "collision.json").read_text())
_IMAGE_CFG: dict[str, Any] = copy.deepcopy(_CFG)
_IMAGE_CFG["roles"]["staticSource"] = "image"  # the lane part is the image rule (the map replaces it by default)

# (key, fixture, frame, depth map given, staticSource image)
SCENARIOS: list[tuple[str, str, int, bool, bool]] = (
    [(f"c4_{i}", "chest0004_review7", i, False, False) for i in (10, 40, 50, 70, 90, 110)]
    + [(f"a4_{i}", "4929_review4", i, False, False) for i in (15, 45, 75, 105, 135, 165)]
    + [(f"cw_{i}", "chest0002_crosswalk", i, False, False) for i in (15, 45, 90, 120, 135, 165)]
    + [
        ("c4_9_dm", "chest0004_review7", 9, True, False),
        ("a4_150_dm", "4929_review4", 150, True, False),
        ("cw_48_dm", "chest0002_crosswalk", 48, True, False),
    ]
    + [(f"c4_{i}_img", "chest0004_review7", i, False, True) for i in (1, 21, 60, 70)]
    + [(f"a4_{i}_img", "4929_review4", i, False, True) for i in (0, 5)]
)

_CACHE: dict[str, tuple[dict[str, Any], Any, Any]] = {}


def _setup(name: str) -> tuple[dict[str, Any], Any, Any]:
    if name not in _CACHE:
        meta = json.loads((FIXTURES / f"{name}.json").read_text())
        npz = np.load(FIXTURES / f"{name}.npz")
        s = meta["settings"]
        settings = collision.resolve_settings(
            _CFG,
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
        grids = np.asarray(npz["w0_grids"])
        depth = np.asarray(npz["w0_depth"])
        _CACHE[name] = (meta, settings, (grids, depth))
    return _CACHE[name]


def _frame(name: str, i: int, cfg: dict[str, Any], with_depth: bool) -> tuple[npt.NDArray[np.int64], Any, Any, Any]:
    """(grid, ids, geo, dmap) as run_collision builds them for frame ``i`` (preset horizon)."""
    meta, settings, (grids, depth) = _setup(name)
    grid = grids[i]
    gh, gw = grid.shape
    ids = collision.resolve_class_ids(cfg, meta["classNames"])
    f = collision.focal_px(gw, settings.hfov_deg)
    region = collision.walking_region(grid, ids, cfg)
    geo = collision._frame_geometry(
        gh,
        gw,
        settings.horizon_default,
        settings.camera_height_m,
        f,
        settings.hfov_deg,
        cfg["geometry"]["laneHalfWidthM"],
        region,
        cfg["roles"]["boundaryMarginPx"],
        getattr(settings, "projection", "rectilinear"),
        collision._walking_axis_offset_m(settings),
        False,
    )
    dmap = np.asarray(depth[i]).astype(np.float32) if with_depth else None
    return grid, ids, geo, dmap


def _runs(labels: list[str]) -> str:
    out: list[str] = []
    for lab in labels:
        if out and out[-1].split("*")[0] == lab:
            base, _, n = out[-1].partition("*")
            out[-1] = f"{base}*{int(n or 1) + 1}"
        else:
            out.append(lab)
    return ",".join(out)


def _sha(obj: object) -> str:
    return hashlib.sha1(repr(obj).encode()).hexdigest()


def _digest(items: list[Any]) -> dict[str, Any]:
    """Digest of an ordered item list: order, exact fields, float sums, first and last item."""
    labels = [f"{i.group}:{i.class_name}" for i in items]
    marks = {
        "L": [k for k, i in enumerate(items) if i.lane_part],
        "T": [k for k, i in enumerate(items) if i.tree],
        "h": [k for k, i in enumerate(items) if i.thin],
        "l": [k for k, i in enumerate(items) if i.lane_hit],
        "a": [k for k, i in enumerate(items) if i.along_path],
        "c": [k for k, i in enumerate(items) if i.clipped],
    }
    flags = ";".join(f"{m}:{','.join(map(str, v))}" for m, v in marks.items() if v)
    exact = [
        (i.bbox, i.clock, i.clock_text, i.base_row, i.base_col, i.touches, i.people, i.fast, i.landmark) for i in items
    ]
    out: dict[str, Any] = {"n": len(items), "order": _runs(labels), "flags": flags, "exact": _sha(exact)}
    if items:
        d = [i.distance_m for i in items]
        la = [i.lateral_m for i in items]
        b = [i.bearing for i in items]
        out["dist_sum"] = float(sum(d))
        out["lat_sum"] = float(sum(la))
        out["bearing_sum"] = float(sum(b))
        out["area_sum"] = float(sum(i.area_frac for i in items))
        out["area_m2_sum"] = float(sum(i.area_m2 for i in items))
        out["first"] = (d[0], la[0], b[0])
        out["last"] = (d[-1], la[-1], b[-1])
        out["shape_px"] = int(sum(int(i.shape[0].sum()) for i in items))
    return out


def _check(got: dict[str, Any], exp: dict[str, Any]) -> None:
    assert set(got) == set(exp)
    for k, v in exp.items():
        if isinstance(v, (float, tuple)):
            assert got[k] == pytest.approx(v, rel=1e-12, abs=1e-12), k
        else:
            assert got[k] == v, k


def _scenario(key: str, detect: Callable[..., list[Any]]) -> dict[str, Any]:
    _, name, i, with_depth, image = next(s for s in SCENARIOS if s[0] == key)
    cfg = _IMAGE_CFG if image else _CFG
    grid, ids, geo, dmap = _frame(name, i, cfg, with_depth)
    return _digest(detect(grid, ids, geo, cfg, dmap))


EXP: dict[str, dict[str, Any]] = {
    "c4_10": {
        "n": 13,
        "order": "static:pole,static:nature vegetation*3,static:building,moving:person*2,feature:curb*6",
        "flags": "T:0;l:5;a:3,4,5,11;c:4",
        "exact": "8cafcf99e2c4802019d29bed8a2550e8cab2e38f",
        "dist_sum": 102.96404844440806,
        "lat_sum": -68.73210833566978,
        "bearing_sum": -317.37083333333334,
        "area_sum": 0.21506172839506169,
        "area_m2_sum": 9.603658660849197,
        "first": (5.136123647578051, -1.5315068493150692, -10.570833333333335),
        "last": (2.1672660478219514, -3.531791907514451, -57.77083333333333),
        "shape_px": 6968,
    },
    "c4_40": {
        "n": 15,
        "order": "static:pole,static:sign*2,static:nature "
        "vegetation*3,static:building*4,moving:person,moving:vehicle,feature:curb*3",
        "flags": "h:0,1,2;a:0,2,10;c:9",
        "exact": "7573d36d163b10180a5d4ec8c2d0f88a357162cc",
        "dist_sum": 137.11260274642734,
        "lat_sum": -58.3596190887452,
        "bearing_sum": -237.22916666666663,
        "area_sum": 0.22910493827160494,
        "area_m2_sum": 27.741593477686326,
        "first": (10.13343314251886, 0.9135135135135146, 3.195833333333335),
        "last": (1.7939570635081226, -2.9483253588516747, -58.2625),
        "shape_px": 7423,
    },
    "c4_50": {
        "n": 22,
        "order": "static:pole*2,static:sign,static:nature "
        "vegetation*5,static:building*5,moving:person*3,moving:vehicle*2,feature:curb*4",
        "flags": "h:0,1,2;l:7;a:11,12,13;c:3,13,14,21",
        "exact": "e4c12fb060d3e73e1ef4403a4f0677786309cd1c",
        "dist_sum": 207.21114313809358,
        "lat_sum": -45.17642890651868,
        "bearing_sum": -192.73333333333335,
        "area_sum": 0.17015432098765434,
        "area_m2_sum": 33.51739733009725,
        "first": (11.361728068884785, 3.072727272727277, 9.587500000000006),
        "last": (1.2624142298760863, -2.0572390572390575, -57.77083333333333),
        "shape_px": 5513,
    },
    "c4_70": {
        "n": 19,
        "order": "static:pole*3,static:sign,static:sidewalk-obstacle,static:barrier,static:nature "
        "vegetation*2,static:building*4,moving:vehicle*3,feature:curb*4",
        "flags": "T:1;h:0,2,3;l:4;a:2,11;c:11",
        "exact": "712c626523a4fdd8dc7eaaaa6463eaf515e2e9ae",
        "dist_sum": 161.51269981150685,
        "lat_sum": -126.35362982412799,
        "bearing_sum": -612.3708333333333,
        "area_sum": 0.2532716049382716,
        "area_m2_sum": 19.72464120529513,
        "first": (7.074283514588634, -10.056603773584907, -50.39583333333333),
        "last": (1.7939570635081226, -2.923444976076555, -57.77083333333333),
        "shape_px": 8206,
    },
    "c4_90": {
        "n": 21,
        "order": "static:pole*5,static:sign*2,static:sidewalk-obstacle*2,static:barrier fence,static:nature "
        "vegetation*2,static:building*4,moving:vehicle*2,feature:curb*3",
        "flags": "T:2;h:0,1,3,4,5,6;a:14;c:0,4,7,8",
        "exact": "605bfeb83bd70b8a317f8645910c0b3f945e7aed",
        "dist_sum": 137.98207808015792,
        "lat_sum": -59.6704271708618,
        "bearing_sum": -223.46249999999998,
        "area_sum": 0.2660802469135803,
        "area_m2_sum": 30.268225388161895,
        "first": (1.2624142298760863, 1.3919191919191922, 39.087500000000006),
        "last": (1.6372795907126532, -2.71353711790393, -58.75416666666667),
        "shape_px": 8621,
    },
    "c4_110": {
        "n": 17,
        "order": "static:pole*4,static:sign*2,static:traffic-sign,static:barrier fence,static:nature "
        "vegetation*2,static:building*4,moving:vehicle,feature:curb*2",
        "flags": "T:1;h:0,2,3,4,5,6;l:1;a:15;c:3,13,15",
        "exact": "3f2728be3c3450095e0496027677b5e229a19f38",
        "dist_sum": 82.77200703128975,
        "lat_sum": -8.392841507726867,
        "bearing_sum": -123.16250000000001,
        "area_sum": 0.30095679012345683,
        "area_m2_sum": 17.378842903535787,
        "first": (11.361728068884785, 14.260606060606072, 44.49583333333333),
        "last": (2.999496210185581, -4.888000000000001, -57.77083333333333),
        "shape_px": 9751,
    },
    "a4_15": {
        "n": 11,
        "order": "static:pole*3,static:barrier wall,static:building*2,moving:vehicle,feature:curb*4",
        "flags": "h:0,1,2;l:1,3,8,9;a:5,6;c:5",
        "exact": "77838bb7b980628377a1783068dadd98737a1c2e",
        "dist_sum": 32.947318470805634,
        "lat_sum": -20.68687580390497,
        "bearing_sum": -214.1208333333333,
        "area_sum": 0.3455246913580247,
        "area_m2_sum": 6.794067906081418,
        "first": (5.6866188505530175, -0.6703753846153843, -4.179166666666665),
        "last": (1.508694797085495, -2.437655510204082, -57.27916666666667),
        "shape_px": 11195,
    },
    "a4_45": {
        "n": 14,
        "order": "static:pole*3,static:traffic-sign,static:barrier fence,static:barrier "
        "wall*5,static:building,moving:person,moving:vehicle,feature:curb",
        "flags": "h:0,1,2,3;l:2,4;a:6,10,12;c:10,12",
        "exact": "5f26fe44cbe9ddf2a7ff19064f86947757ef79e7",
        "dist_sum": 62.61564488452516,
        "lat_sum": -18.69645278249287,
        "bearing_sum": 51.133333333333326,
        "area_sum": 0.34030864197530863,
        "area_m2_sum": 5.109916173482917,
        "first": (6.059511889933543, -6.6811278688524585, -39.0875),
        "last": (1.508694797085495, -0.9311216326530614, -21.879166666666666),
        "shape_px": 11026,
    },
    "a4_75": {
        "n": 33,
        "order": "static:pole*7,static:traffic-sign,static:sidewalk-obstacle*2,static:barrier,static:barrier "
        "fence*2,static:barrier wall*6,static:building,moving:person*2,moving:vehicle*4,feature:curb*7",
        "flags": "h:0,1,2,3,4,5,6,7;l:2,23,24,31;a:31;c:25,31",
        "exact": "7c0f96d7e46e265ebe675141605fe9d0acf1d9ab",
        "dist_sum": 198.86368034495592,
        "lat_sum": -16.195263820726883,
        "bearing_sum": -463.3958333333335,
        "area_sum": 0.18324074074074073,
        "area_m2_sum": 13.64630872573787,
        "first": (5.356959786752846, -8.209669565217396, -54.32916666666667),
        "last": (2.295839908608362, -2.2447900621118015, -34.6625),
        "shape_px": 5937,
    },
    "a4_105": {
        "n": 22,
        "order": "static:pole*3,static:sidewalk-obstacle,static:barrier wall*4,static:nature "
        "vegetation*3,moving:person,moving:vehicle*4,feature:curb*4,feature:crosswalk*2",
        "flags": "T:1;h:0,2;l:1,6,7,20,21",
        "exact": "a337c50b922131ab1df743ac5b5115b30d49b9e7",
        "dist_sum": 91.33210004845094,
        "lat_sum": 5.647005868367908,
        "bearing_sum": 31.958333333333325,
        "area_sum": 0.12787037037037036,
        "area_m2_sum": 8.276595033804071,
        "first": (2.95704180228757, -1.2918527999999998, -15.487499999999997),
        "last": (3.0547952502970763, -0.021183471074380095, -0.24583333333333246),
        "shape_px": 4143,
    },
    "a4_135": {
        "n": 13,
        "order": "static:pole*2,static:barrier wall*3,static:nature "
        "vegetation,moving:person,feature:curb*4,feature:crosswalk*2",
        "flags": "h:0,1;l:7,8,11,12;c:0,1,12",
        "exact": "b8380579e564f4f38e24721cb455293c4354e372",
        "dist_sum": 34.852666539111034,
        "lat_sum": 8.235013111441324,
        "bearing_sum": 81.86250000000003,
        "area_sum": 0.22469135802469137,
        "area_m2_sum": 4.914305333406807,
        "first": (1.244546213083994, 1.9072969696969697, 54.32916666666667),
        "last": (1.244546213083994, -0.008630303030303, -0.24583333333333246),
        "shape_px": 7280,
    },
    "a4_165": {
        "n": 12,
        "order": "static:barrier,static:barrier wall*3,static:nature "
        "vegetation,moving:person*2,feature:curb*4,feature:crosswalk",
        "flags": "l:8,9,11;a:11;c:10,11",
        "exact": "b10215037c82ac516247bced52ca86f413f4c260",
        "dist_sum": 28.7071206689513,
        "lat_sum": 9.780056697885323,
        "bearing_sum": 97.84166666666665,
        "area_sum": 0.2621913580246914,
        "area_m2_sum": 5.65075709067159,
        "first": (2.2401831835511894, -1.6311272727272732, -25.8125),
        "last": (1.244546213083994, -0.008630303030303, -0.24583333333333246),
        "shape_px": 8495,
    },
    "cw_15": {
        "n": 22,
        "order": "static:pole*3,static:sidewalk-obstacle,static:barrier fence,static:barrier "
        "wall*4,static:building,moving:person*2,moving:vehicle*2,feature:curb*8",
        "flags": "h:0,1,2;l:1,16,17;c:21",
        "exact": "3c3561048f4c64b0d66e693755bc8928bf82f4f4",
        "dist_sum": 68.35273651932522,
        "lat_sum": 6.562024470329463,
        "bearing_sum": -35.89166666666665,
        "area_sum": 0.13589506172839502,
        "area_m2_sum": 5.25516317927764,
        "first": (2.0883063575477188, -0.7675118644067798, -13.029166666666667),
        "last": (1.244546213083994, 1.9418181818181817, 55.3125),
        "shape_px": 4403,
    },
    "cw_45": {
        "n": 11,
        "order": "static:barrier wall*2,static:nature "
        "vegetation,moving:person,moving:vehicle,feature:curb*4,feature:crosswalk*2",
        "flags": "l:5,9,10;c:10",
        "exact": "ae8dcd9bdfe9dd4ec73456bf1bb4b65878c7a959",
        "dist_sum": 38.48819781630101,
        "lat_sum": -8.286793542841528,
        "bearing_sum": -111.36250000000001,
        "area_sum": 0.2374074074074074,
        "area_m2_sum": 6.445030595878049,
        "first": (4.348590885717015, 1.8394729411764712, 14.995833333333332),
        "last": (1.244546213083994, -0.008630303030303, -0.24583333333333246),
        "shape_px": 7692,
    },
    "cw_90": {
        "n": 13,
        "order": "static:pole,static:barrier fence,static:barrier wall*2,static:nature "
        "vegetation*3,moving:person*3,feature:curb*2,feature:crosswalk",
        "flags": "h:0;c:8",
        "exact": "4427d303958f073578f9ccc1b343ac5e7ade11e3",
        "dist_sum": 35.897777893581505,
        "lat_sum": 12.318501371994245,
        "bearing_sum": 31.220833333333324,
        "area_sum": 0.17518518518518517,
        "area_m2_sum": 3.999798572720215,
        "first": (2.6214909594747957, -3.2539914893617023, -44.00416666666667),
        "last": (2.2401831835511894, -3.4642036363636373, -54.82083333333333),
        "shape_px": 5676,
    },
    "cw_120": {
        "n": 33,
        "order": "static:pole*7,static:sign*4,static:barrier fence*2,static:barrier wall,static:nature "
        "vegetation*8,static:building*4,moving:person,moving:vehicle*2,feature:curb*3,feature:crosswalk",
        "flags": "h:0,1,2,3,4,5,6,7,8,9,10;l:26,29,32;a:13,29;c:13,29",
        "exact": "ad1a342f7f0d7ae67804d9e47303fb51f95099d7",
        "dist_sum": 176.97875146619347,
        "lat_sum": -74.13692835829525,
        "bearing_sum": -244.60416666666663,
        "area_sum": 0.15290123456790122,
        "area_m2_sum": 16.854246610933977,
        "first": (3.520287859866154, -4.61376, -46.4625),
        "last": (3.159232694751678, -0.24098461538461521, -2.7041666666666635),
        "shape_px": 4954,
    },
    "cw_135": {
        "n": 36,
        "order": "static:pole*10,static:sign*4,static:traffic-sign*2,static:barrier fence,static:barrier "
        "wall*2,static:nature "
        "vegetation*4,static:building*5,moving:person,moving:vehicle*2,feature:curb*4,feature:crosswalk",
        "flags": "h:0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15;l:28,31,35;a:18,31;c:31,34",
        "exact": "ced33ca086dd8f75954d2c485c93eccc30aa3c66",
        "dist_sum": 148.35118056559165,
        "lat_sum": -91.28343056685432,
        "bearing_sum": -686.8583333333331,
        "area_sum": 0.18623456790123458,
        "area_m2_sum": 12.090424602766475,
        "first": (3.2710639405835957, -2.1549026548672576, -23.354166666666668),
        "last": (2.0883063575477188, -0.4778847457627117, -8.112499999999997),
        "shape_px": 6034,
    },
    "cw_165": {
        "n": 32,
        "order": "static:pole*6,static:sign*3,static:traffic-sign,static:sidewalk-obstacle,static:barrier "
        "wall*3,static:nature "
        "vegetation*3,static:building*4,moving:person,moving:vehicle*5,feature:curb*4,feature:crosswalk",
        "flags": "h:0,1,2,3,4,5,6,7,8,9;l:21,27,31;a:27;c:27,31",
        "exact": "10b54eb48fe147068956b417e5ffd7dad3b60179",
        "dist_sum": 135.32725064675728,
        "lat_sum": -93.81917395434542,
        "bearing_sum": -568.3666666666667,
        "area_sum": 0.211358024691358,
        "area_m2_sum": 16.120783908672603,
        "first": (3.520287859866154, -3.0026057142857137, -30.237499999999997),
        "last": (1.244546213083994, -0.11219393939393947, -3.195833333333335),
        "shape_px": 6848,
    },
    "c4_9_dm": {
        "n": 12,
        "order": "static:nature vegetation*3,static:building*2,moving:person*3,feature:curb*4",
        "flags": "l:6,7;a:4,5,6,7,9;c:4",
        "exact": "d72ecd6bdc68864b046c3e7ea080100c13b4ceb2",
        "dist_sum": 78.2482245933679,
        "lat_sum": -43.039798101657055,
        "bearing_sum": -293.03333333333325,
        "area_sum": 0.22962962962962963,
        "area_m2_sum": 9.46060579052168,
        "first": (1.983793789805278, -2.5174603174603174, -44.9875),
        "last": (1.7602677289821484, -2.868544600938967, -57.77083333333333),
        "shape_px": 7440,
    },
    "a4_150_dm": {
        "n": 15,
        "order": "static:pole,static:barrier fence,static:barrier wall*4,static:nature "
        "vegetation,moving:person*2,feature:curb*5,feature:crosswalk",
        "flags": "h:0;l:11,13,14;c:14",
        "exact": "4eb1665381731ed095af0cbc08487511428d4ef9",
        "dist_sum": 77.07661919991442,
        "lat_sum": -13.879182326371133,
        "bearing_sum": -40.07083333333336,
        "area_sum": 0.29237654320987655,
        "area_m2_sum": 15.202662094442942,
        "first": (6.484740794490284, -9.848084210526315, -53.8375),
        "last": (1.244546213083994, -0.008630303030303, -0.24583333333333246),
        "shape_px": 9473,
    },
    "cw_48_dm": {
        "n": 18,
        "order": "static:pole,static:barrier fence*2,static:barrier wall*4,static:nature "
        "vegetation,moving:person*4,feature:curb*4,feature:crosswalk*2",
        "flags": "h:0;l:12,14,15,16,17;c:16",
        "exact": "dee7edc8fbaf6664303ab57fa1d75aa4b08f09d4",
        "dist_sum": 67.11779199428975,
        "lat_sum": 15.267082946544926,
        "bearing_sum": -144.05833333333337,
        "area_sum": 0.2372530864197531,
        "area_m2_sum": 8.555971656925927,
        "first": (2.4158838253983417, -3.367341176470589, -49.4125),
        "last": (2.5491739674892835, 0.053031724137930836, 0.7374999999999974),
        "shape_px": 7687,
    },
    "c4_1_img": {
        "n": 15,
        "order": "static:pole,static:sidewalk-obstacle,static:barrier wall,static:nature "
        "vegetation*3,static:building*4,moving:person,feature:curb*4",
        "flags": "L:9;h:0;l:9;a:0,8,10,13;c:8",
        "exact": "3a2d2294836dd24bd64e5286a3c82a2128fa78a0",
        "dist_sum": 123.98257628311417,
        "lat_sum": -92.25339072289654,
        "bearing_sum": -435.37083333333334,
        "area_sum": 0.4255555555555556,
        "area_m2_sum": 11.605800612268322,
        "first": (8.33193391718217, -3.1777777777777776, -13.52083333333333),
        "last": (1.828961103771696, -3.0058536585365863, -58.2625),
        "shape_px": 13788,
    },
    "c4_21_img": {
        "n": 18,
        "order": "static:sign,static:nature "
        "vegetation*4,static:building*4,moving:person*3,moving:vehicle*2,feature:curb*4",
        "flags": "L:8;h:0;l:8,10,11;a:4,7,9,10;c:7",
        "exact": "95f29d924337a444318b058205b2ab2d1fd8d647",
        "dist_sum": 183.53623953917878,
        "lat_sum": -110.90999494184955,
        "bearing_sum": -381.0416666666667,
        "area_sum": 0.4812654320987656,
        "area_m2_sum": 26.9536765007494,
        "first": (17.854144108247517, 20.67619047619049, 41.05416666666667),
        "last": (1.828961103771696, -3.0312195121951224, -58.75416666666667),
        "shape_px": 15593,
    },
    "c4_60_img": {
        "n": 12,
        "order": "static:pole,static:sign,static:barrier,static:nature vegetation*3,static:building*4,feature:curb*2",
        "flags": "L:8;h:0,1;l:8;a:0,9;c:9",
        "exact": "d86a96468120f8031ab97ddb3692c810c95cad81",
        "dist_sum": 98.02176871530824,
        "lat_sum": -62.413784730894506,
        "bearing_sum": -180.93333333333328,
        "area_sum": 0.17425925925925925,
        "area_m2_sum": 14.280075954399269,
        "first": (6.577842566196448, -0.8666666666666673, -4.670833333333336),
        "last": (2.516355881028171, -3.367785234899328, -47.44583333333333),
        "shape_px": 5646,
    },
    "c4_70_img": {
        "n": 20,
        "order": "static:pole*3,static:sign,static:sidewalk-obstacle,static:barrier,static:nature "
        "vegetation*2,static:building*5,moving:vehicle*3,feature:curb*4",
        "flags": "L:12;T:1;h:0,2,3;l:4,12;a:2,11;c:11",
        "exact": "25cf01ecdfec2f8293b084ebbdefc1e5acf11798",
        "dist_sum": 168.09054237770331,
        "lat_sum": -126.12555964868939,
        "bearing_sum": -611.1416666666667,
        "area_sum": 0.4611728395061729,
        "area_m2_sum": 21.7895261943552,
        "first": (7.074283514588634, -10.056603773584907, -50.39583333333333),
        "last": (1.7939570635081226, -2.923444976076555, -57.77083333333333),
        "shape_px": 14942,
    },
    "a4_0_img": {
        "n": 13,
        "order": "static:pole*2,static:sidewalk-obstacle*2,static:building*4,moving:vehicle*3,feature:curb*2",
        "flags": "L:7;h:0,1;l:1,7;a:6,8,11;c:3,9,11",
        "exact": "6f11e1f4de51c47c46124ea81a2aff96babc8a10",
        "dist_sum": 51.122572882618435,
        "lat_sum": -33.09994841453834,
        "bearing_sum": -250.99583333333334,
        "area_sum": 0.39487654320987653,
        "area_m2_sum": 11.413841374861889,
        "first": (6.974155194074457, -9.430641509433963, -47.9375),
        "last": (1.768565671224623, -2.489615311004785, -49.90416666666667),
        "shape_px": 12794,
    },
    "a4_5_img": {
        "n": 13,
        "order": "static:pole*4,static:sidewalk-obstacle,static:building*3,moving:vehicle*2,feature:curb*3",
        "flags": "L:7;h:0,1,2,3;l:2,7;a:6,8;c:4,6,11",
        "exact": "f6458dac4d5449a6a35216f62f64c1ab612941c4",
        "dist_sum": 43.22176679901504,
        "lat_sum": -22.686135596780126,
        "bearing_sum": -251.4875,
        "area_sum": 0.4720679012345679,
        "area_m2_sum": 7.397600199548579,
        "first": (5.063427743643101, -4.03791780821918, -28.270833333333332),
        "last": (1.2615366050714891, -2.0558088737201374, -57.77083333333333),
        "shape_px": 15295,
    },
}


def test_facade_identity() -> None:
    import engine.detection as pkg
    from engine.detection import items

    assert collision.detect_items is items.detect_items
    assert collision._split_people is items.split_people
    assert collision._tree_trunk is items.tree_trunk
    assert collision._lane_part_item is items.lane_part_item
    assert pkg.detect_items is items.detect_items
    assert pkg.split_people is items.split_people
    assert pkg.tree_trunk is items.tree_trunk
    assert pkg.lane_part_item is items.lane_part_item
    assert set(pkg.__all__) >= {"detect_items", "split_people", "tree_trunk", "lane_part_item"}


@pytest.mark.parametrize("key", [s[0] for s in SCENARIOS])
def test_detect_items_digest(key: str) -> None:
    from engine.detection.items import detect_items

    _check(_scenario(key, detect_items), EXP[key])


def test_detect_items_without_depth_map_equals_none() -> None:
    from engine.detection.items import detect_items

    grid, ids, geo, _ = _frame("chest0004_review7", 40, _CFG, False)
    a = detect_items(grid, ids, geo, _CFG)
    b = detect_items(grid, ids, geo, _CFG, None)
    assert _digest(a) == _digest(b)


def test_detect_items_is_repeatable_and_leaves_the_grid_alone() -> None:
    from engine.detection.items import detect_items

    grid, ids, geo, _ = _frame("4929_review4", 75, _CFG, False)
    before = grid.copy()
    a = _digest(detect_items(grid, ids, geo, _CFG))
    b = _digest(detect_items(grid, ids, geo, _CFG))
    assert a == b
    assert np.array_equal(grid, before)


def _components(
    grid: npt.NDArray[np.int64], ids: Any, geo: Any, cls: str
) -> list[tuple[npt.NDArray[np.bool_], int, int, Any]]:
    """The components detect_items cuts for ``cls``: (comp, r0, c0, full)."""
    from scipy import ndimage

    from engine.core.classes import FOUR_CONNECTIVITY

    cid = ids.names.index(cls)
    mask = (grid == cid) & geo.below[:, None]
    labels, _ = ndimage.label(mask, structure=FOUR_CONNECTIVITY)
    fl, _ = ndimage.label(grid == cid, structure=FOUR_CONNECTIVITY)
    fobj = ndimage.find_objects(fl)
    out = []
    for k, sl in enumerate(ndimage.find_objects(labels), start=1):
        comp = labels[sl] == k
        rr, cc = np.nonzero(comp)
        fid = int(fl[rr[0] + sl[0].start, cc[0] + sl[1].start])
        fsl = fobj[fid - 1]
        out.append((comp, sl[0].start, sl[1].start, (fl[fsl] == fid, fsl[1].start, fsl[0].start)))
    return out


def _split_digest(res: list[Any] | None) -> Any:
    if res is None:
        return None
    return [(int(r.size), int(r.sum()), int(c.sum()), int(m.sum()), c0, r0) for r, c, m, c0, r0 in res]


def _split_all(frame_key: str, split: Callable[..., Any], with_depth: bool, with_full: bool) -> list[Any]:
    _, name, i, _, _ = next(s for s in SCENARIOS if s[0] == frame_key)
    grid, ids, geo, dmap = _frame(name, i, _CFG, True)
    min_pixels = _CFG["minComponentFraction"] * geo.gw * geo.gh
    out = []
    for comp, r0, c0, full in _components(grid, ids, geo, "person"):
        res = split(
            comp,
            r0,
            c0,
            geo,
            _CFG["personSplit"],
            dmap if with_depth else None,
            min_pixels,
            full if with_full else None,
        )
        out.append(_split_digest(res))
    return out


SPLIT_EXP: dict[tuple[str, bool], Any] = {
    ("c4_9_dm", False): [None, None],
    ("c4_9_dm", True): [[(42, 2747, 4598, 42, 107, 60), (38, 2425, 4377, 38, 107, 60)], None],
    ("a4_150_dm", False): [None],
    ("a4_150_dm", True): [[(76, 5229, 14241, 76, 184, 60), (86, 5871, 16509, 86, 184, 60)]],
    ("cw_48_dm", False): [None, None],
    ("cw_48_dm", True): [
        [(25, 1625, 4859, 25, 192, 60), (86, 5739, 17069, 86, 192, 60), (33, 2229, 6709, 33, 192, 60)],
        None,
    ],
}


@pytest.mark.parametrize("frame_key", ["c4_9_dm", "a4_150_dm", "cw_48_dm"])
@pytest.mark.parametrize("with_depth", [False, True])
def test_split_people_with_full(frame_key: str, with_depth: bool) -> None:
    from engine.detection.items import split_people

    assert _split_all(frame_key, split_people, with_depth, True) == SPLIT_EXP[(frame_key, with_depth)]


def test_split_people_latent_nameerror_without_full() -> None:
    """latent defect, audit 5.8: ``hgt`` is only assigned when ``full`` is given, so a wide one without it raises."""
    from engine.detection.items import split_people

    _, name, i, _, _ = next(s for s in SCENARIOS if s[0] == SPLIT_NAMEERROR[0])
    grid, ids, geo, dmap = _frame(name, i, _CFG, True)
    min_pixels = _CFG["minComponentFraction"] * geo.gw * geo.gh
    comp, r0, c0, _ = _components(grid, ids, geo, "person")[SPLIT_NAMEERROR[1]]
    with pytest.raises(NameError):
        split_people(comp, r0, c0, geo, _CFG["personSplit"], dmap, min_pixels, None)


SPLIT_NAMEERROR: tuple[str, int] = ("c4_9_dm", 0)


def _tree_case(step: int, tree_trunk: Callable[..., bool]) -> bool:
    from scipy import ndimage

    grid = np.zeros((30, 40), dtype=np.int64)
    grid[3:9, 10:20] = 3
    grid[10:25, 14:16] = 4
    fl, _ = ndimage.label(grid == 4)
    fsl = ndimage.find_objects(fl)[0]
    cfg = _CFG["tree"]
    if step >= 1:
        grid[3:9, 10:20] = 0
    if step >= 2:
        grid[3:9, 30:38] = 3
    if step >= 3:
        grid[3:6, 10:20] = 3
    return tree_trunk(grid, 3, (fl, fsl, 1), cfg)


def test_tree_trunk_old_cases() -> None:
    from engine.detection.items import tree_trunk

    assert [_tree_case(s, tree_trunk) for s in range(4)] == TREE_EXP
    assert all(isinstance(_tree_case(s, tree_trunk), bool) for s in range(4))


TREE_EXP: list[bool] = [True, False, False, False]


def test_tree_trunk_config_defaults_and_empty_component() -> None:
    from scipy import ndimage

    from engine.detection.items import tree_trunk

    grid = np.zeros((30, 40), dtype=np.int64)
    grid[3:9, 10:20] = 3
    grid[10:25, 14:16] = 4
    fl, _ = ndimage.label(grid == 4)
    fsl = ndimage.find_objects(fl)[0]
    assert tree_trunk(grid, 3, (fl, fsl, 1), {}) is TREE_EXP_DEFAULTS[0]
    assert tree_trunk(grid, 3, (fl, fsl, 2), {}) is TREE_EXP_DEFAULTS[1]
    assert tree_trunk(grid, 3, (fl, fsl, 1), {"gapRows": 0, "minOverlap": 1.0}) is TREE_EXP_DEFAULTS[2]


TREE_EXP_DEFAULTS: list[bool] = [True, False, False]


def _lane_pair(key: str) -> list[tuple[Any, Any, Any, Any, Any]]:
    """(geo, main, part-from-detect, rr, cc) for every lane part detect_items produced on the scenario frame."""
    from engine.detection.items import detect_items

    _, name, i, with_depth, image = next(s for s in SCENARIOS if s[0] == key)
    cfg = _IMAGE_CFG if image else _CFG
    grid, ids, geo, dmap = _frame(name, i, cfg, with_depth)
    items = detect_items(grid, ids, geo, cfg, dmap)
    out = []
    for j, it in enumerate(items):
        if it.lane_part:
            main = items[j - 1]
            assert main.shape is not None
            mask, c0, r0 = main.shape
            rr, cc = np.nonzero(mask)
            out.append((geo, main, it, rr + r0, cc + c0))
    return out


LANE_EXP: dict[str, Any] = {
    "c4_1_img": {
        "count": 1,
        "parts": [(True, 64, 121, 3, 0.25, 22.055119192541063, 0.4588235294117637, 0.7374999999999974, 12, False)],
    },
    "c4_21_img": {
        "count": 1,
        "parts": [(True, 77, 127, 3, 0.0625, 5.4338699459883735, 0.5652173913043481, 3.6875, 12, False)],
    },
    "c4_60_img": {
        "count": 1,
        "parts": [(True, 68, 123, 2, 0.125, 11.361728068884785, 0.55151515151515, 1.7208333333333272, 12, False)],
    },
    "c4_70_img": {
        "count": 1,
        "parts": [
            (
                True,
                74,
                122,
                7,
                0.07142857142857142,
                6.577842566196448,
                0.22807017543859565,
                1.2291666666666623,
                12,
                False,
            )
        ],
    },
    "a4_0_img": {
        "count": 1,
        "parts": [(False, 76, 127, 8, 0.0625, 5.6866188505530175, 0.5915076923076923, 3.6875, 12, False)],
    },
    "a4_5_img": {
        "count": 1,
        "parts": [
            (
                True,
                75,
                124,
                3,
                0.21428571428571427,
                6.059511889933543,
                0.37817704918032874,
                2.2125000000000052,
                12,
                False,
            )
        ],
    },
}


@pytest.mark.parametrize("key", ["c4_1_img", "c4_21_img", "c4_60_img", "c4_70_img", "a4_0_img", "a4_5_img"])
def test_lane_part_item_follows_its_main_item_and_shares_arrays(key: str) -> None:
    from engine.detection.items import lane_part_item

    pairs = _lane_pair(key)
    assert len(pairs) == LANE_EXP[key]["count"]
    got = []
    for geo, main, part, rr, cc in pairs:
        again = lane_part_item(main, rr, cc, geo, _IMAGE_CFG)
        assert again is not None
        assert _digest([again]) == _digest([part])
        assert again.lane_part is True and main.lane_part is False
        # replace(): a shallow copy, the arrays are shared with the main item
        assert again.shape is main.shape and again.bbox is main.bbox and again.full_ref is main.full_ref
        assert again.depth_cells is not None and main.depth_cells is None
        assert again.base_row == part.base_row and again.base_col == part.base_col
        got.append(
            (
                again.lane_part_weak,
                again.base_row,
                again.base_col,
                int(again.depth_cells[0].size),
                again.lane_cover,
                again.distance_m,
                again.lateral_m,
                again.bearing,
                again.clock,
                again.clipped,
            )
        )
    assert len(got) == len(LANE_EXP[key]["parts"])
    for g, e in zip(got, LANE_EXP[key]["parts"], strict=False):
        assert [g[0], g[1], g[2], g[3], g[8], g[9]] == [e[0], e[1], e[2], e[3], e[8], e[9]]
        assert list(g[4:8]) == pytest.approx(list(e[4:8]), rel=1e-12, abs=1e-12)


def test_lane_part_item_none_cases() -> None:
    from engine.detection.items import lane_part_item

    geo, main, _, rr, cc = _lane_pair("c4_60_img")[0]
    wide = copy.deepcopy(_IMAGE_CFG)
    wide["roles"]["laneBaseMinColumns"] = 10_000
    assert lane_part_item(main, rr, cc, geo, wide) is None
    short = copy.deepcopy(_IMAGE_CFG)
    short["geometry"]["maxRangeM"] = 0.01
    assert lane_part_item(main, rr, cc, geo, short) is None
    assert (lane_part_item(main, rr[:0], cc[:0], geo, _IMAGE_CFG) is None) is True


def test_no_lane_parts_with_the_default_map_source() -> None:
    from engine.detection.items import detect_items

    grid, ids, geo, _ = _frame("chest0004_review7", 60, _CFG, False)
    assert _CFG["roles"]["staticSource"] == "map"
    assert not [i for i in detect_items(grid, ids, geo, _CFG) if i.lane_part]
    grid, ids, geo, _ = _frame("chest0004_review7", 60, _IMAGE_CFG, False)
    assert [i for i in detect_items(grid, ids, geo, _IMAGE_CFG) if i.lane_part]
