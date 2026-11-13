"""Characterisation tests for engine.surface (v26.3.0 p2-06).

Every expected value in ``EXPECTED`` was produced by running the legacy code (``collision.walking_region``,
``_smooth_bounds``, ``estimate_horizon``, ``HorizonGravity``, ``_SurfaceTracker``, ``_CrosswalkTracker``,
``_seed_fraction``) in the hackeye-rnd image on the pre-move code, through the same ``_collect_*`` functions that the
tests below run against the engine modules; nothing was computed by hand. Real inputs come from the fixtures
``chest0004_review7``, ``chest0002_crosswalk`` (grids) and ``chest0004_review9`` (device sensors). The collision config
is read straight from the JSON (key order of ``surfaces.groups`` decides ties in ``walking_region``).

The engine modules are imported with importlib inside each test function: they do not exist yet.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import collision
import sensors
from common_paths import find_common_dir

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

# (fixture, window, the 5 frames used by the walking_region / estimate_horizon pins)
REGION_FRAMES: list[tuple[str, str, list[int]]] = [
    ("chest0004_review7", "w0", [0, 50, 90, 100, 105]),
    ("chest0002_crosswalk", "w0", [0, 20, 50, 75, 105]),
]

_ATTRS_SURFACE = [
    "_evidence",
    "_run",
    "_run_since",
    "_seen",
    "_window",
    "announce_first",
    "lead_s",
    "lookback_s",
    "majority",
    "need_evidence",
    "persist_s",
    "stable",
    "window_s",
]
_ATTRS_CROSSWALK = ["_since", "enter_f", "enter_s", "exit_f", "exit_s", "inside"]
_ATTRS_HORIZON = ["hi", "level", "lo", "n", "prev_t", "rows_per_deg", "tau", "weight"]

EXPECTED: dict[str, Any] = {
    "region": {
        "chest0004_review7": [
            {
                "group": "pedestrian",
                "label": "sidewalk",
                "shape": [135, 240],
                "dtype": "bool",
                "sum": 9713,
                "sha": "342d3da440886625f6bb0d5f4c65cd994369841edee5523c183cd5f2b9a9d8c1",
                "left": ["float64", [135], 51, 10.1375, 0.4, 0.0],
                "right": ["float64", [135], 51, 51.43333333333333, 0.48333333333333334, 0.8166666666666667],
            },
            {
                "group": "pedestrian",
                "label": "sidewalk",
                "shape": [135, 240],
                "dtype": "bool",
                "sum": 9673,
                "sha": "1081f874445e5fa8f89b7ac8ba69c993208d1ec8a2e385ac820ddafb7649885a",
                "left": ["float64", [135], 60, 20.983333333333334, 0.5708333333333333, 0.09583333333333334],
                "right": ["float64", [135], 60, 62.67083333333334, 0.5875, 0.9125],
            },
            {
                "group": "pedestrian",
                "label": "sidewalk",
                "shape": [135, 240],
                "dtype": "bool",
                "sum": 6166,
                "sha": "5f23c85b8ddd49e21b50e6d296fc8c2961ac19c6d28260a9c90f5069041ab1ff",
                "left": ["float64", [135], 73, 12.987500000000006, 0.32083333333333336, 0.20833333333333334],
                "right": ["float64", [135], 73, 40.07916666666668, 0.375, 0.8291666666666667],
            },
            {
                "group": "pedestrian",
                "label": "sidewalk",
                "shape": [135, 240],
                "dtype": "bool",
                "sum": 6430,
                "sha": "e5fa207db8c37db13b901708b4bc992ec1d98f3416c138b487508f367658d774",
                "left": ["float64", [135], 75, 8.3, 0.425, 0.0],
                "right": ["float64", [135], 75, 39.75833333333334, 0.44166666666666665, 0.8541666666666666],
            },
            {
                "group": "pedestrian",
                "label": "sidewalk",
                "shape": [135, 240],
                "dtype": "bool",
                "sum": 3598,
                "sha": "78c67173e28a9e4fdede1de4addf62feeb4158831a40bc93116d1e6f899398c1",
                "left": ["float64", [135], 77, 12.245833333333332, 0.425, 0.07083333333333333],
                "right": ["float64", [135], 77, 27.450000000000006, 0.45416666666666666, 0.4875],
            },
        ],
        "chest0004_review7:reversed": [
            ["pedestrian", 9713],
            ["pedestrian", 9673],
            ["pedestrian", 6166],
            ["pedestrian", 6430],
            ["pedestrian", 3598],
        ],
        "chest0002_crosswalk": [
            None,
            {
                "group": "pedestrian",
                "label": "sidewalk",
                "shape": [135, 240],
                "dtype": "bool",
                "sum": 5492,
                "sha": "40803082358d4f9756e93a89c6b0d6676d0d7f33d197547ba60beb05e11f32f5",
                "left": ["float64", [135], 85, 17.154166666666665, 0.48333333333333334, 0.32916666666666666],
                "right": ["float64", [135], 85, 41.60416666666665, 0.4875, 1.0],
            },
            {
                "group": "road",
                "label": "road",
                "shape": [135, 240],
                "dtype": "bool",
                "sum": 11512,
                "sha": "d5373ad9bac3963abb5427c6bba3696136c02a25fc643cd55971a6e6de9974fe",
                "left": ["float64", [135], 71, 10.779166666666667, 0.5125, 0.0],
                "right": ["float64", [135], 71, 60.579166666666666, 0.5208333333333334, 1.0],
            },
            {
                "group": "road",
                "label": "road",
                "shape": [135, 240],
                "dtype": "bool",
                "sum": 5264,
                "sha": "270bf4a604dff2879dbcb8d6ad5c4a92edcd1d957026decf41fe98bb68d4ca7b",
                "left": ["float64", [135], 85, 8.545833333333334, 0.4166666666666667, 0.0],
                "right": ["float64", [135], 85, 39.37916666666666, 0.4666666666666667, 1.0],
            },
            {
                "group": "road",
                "label": "road",
                "shape": [135, 240],
                "dtype": "bool",
                "sum": 6101,
                "sha": "0d50a79ad40a3cf1bc3894cfbe750f73a7bab420632bcc85d7a525405891d47b",
                "left": ["float64", [135], 75, 6.9625, 0.49583333333333335, 0.0],
                "right": ["float64", [135], 75, 32.650000000000006, 0.5166666666666667, 0.5666666666666667],
            },
        ],
        "chest0002_crosswalk:reversed": [None, ["pedestrian", 5492], ["road", 11512], ["road", 5264], ["road", 6101]],
        "tie": {
            "group": "pedestrian",
            "label": "sidewalk",
            "shape": [20, 20],
            "dtype": "bool",
            "sum": 200,
            "sha": "6ea2ac28e7f91010b3e371d0f190bf214a8995015cb06cc9d73365386893b16d",
            "left": ["float64", [20], 0, 0.0, 0.0, 0.0],
            "right": ["float64", [20], 0, 10.0, 0.5, 0.5],
        },
        "tie_reversed": {
            "group": "road",
            "label": "road",
            "shape": [20, 20],
            "dtype": "bool",
            "sum": 200,
            "sha": "cae7eeb62fd148618b1ca9a34e92c318113f1312d8b9652224b195b4200c4331",
            "left": ["float64", [20], 0, 10.0, 0.5, 0.5],
            "right": ["float64", [20], 0, 20.0, 1.0, 1.0],
        },
        "sum_wins": {
            "group": "pedestrian",
            "label": "sidewalk",
            "shape": [20, 20],
            "dtype": "bool",
            "sum": 198,
            "sha": "97ea59aa2343bcddd18cc137579526a005f7063905a0ee05451cb329a331091b",
            "left": ["float64", [20], 0, 0.0, 0.0, 0.0],
            "right": ["float64", [20], 0, 10.0, 0.5, 0.5],
        },
        "none": None,
        "inside": {
            "group": "pedestrian",
            "label": "sidewalk",
            "shape": [20, 20],
            "dtype": "bool",
            "sum": 140,
            "sha": "2b8ce28de247654cddc31e242c67c67acbe748347b09dc8833ee0a73ce25c6a7",
            "left": ["float64", [20], 5, 4.000000000000001, 0.4, 0.2],
            "right": ["float64", [20], 5, 11.000000000000002, 0.6, 0.8],
        },
        "tiny": {
            "group": "road",
            "label": "road",
            "shape": [3, 3],
            "dtype": "bool",
            "sum": 9,
            "sha": "85c61621ebd04403f66d96fe300cf10b3844de7358184f1276cb08790fd135f1",
            "left": ["float64", [3], 0, 0.0, 0.0, 0.0],
            "right": ["float64", [3], 0, 3.0, 1.0, 1.0],
        },
    },
    "smooth": {
        "none_prev": [[0.3, 0.2, math.nan, 0.9, math.nan, 0.1], False],
        "default": [0.2, 0.2, math.nan, 0.8, math.nan, 0.5],
        "alpha03": [0.15999999999999998, 0.2, math.nan, 0.76, math.nan, 0.66],
        "alpha1": [0.3, 0.2, math.nan, 0.9, math.nan, 0.1],
        "cur_untouched": [0.3, 0.2, math.nan, 0.9, math.nan, 0.1],
        "sequence": [
            ["float64", [135], 51, 10.1375, 0.4, 0.0],
            ["float64", [135], 59, 8.5875, 0.38958333333333334, 0.0],
            ["float64", [135], 60, 14.590625, 0.47812499999999997, 0.04791666666666667],
            ["float64", [135], 66, 10.015104166666665, 0.38802083333333337, 0.023958333333333335],
            ["float64", [135], 75, 7.558333333333333, 0.37421875000000004, 0.011979166666666667],
        ],
    },
    "horizon_fit": {
        "chest0004_review7": [
            [0.33779490603091267, 0.3391748876953411, None],
            [None, None, None],
            [None, None, None],
            [0.5792393901009735, 0.5764209664958274, None],
            [0.4912636837070891, 0.4912636837070891, 0.5389278349837097],
        ],
        "chest0002_crosswalk": [
            None,
            [0.4547198077081585, 0.47134302253695326, None],
            [None, None, None],
            [0.6955483307031246, 0.689602962760173, 0.5972273630098517],
            [0.5604755449409977, 0.5608126944710076, None],
        ],
        "synthetic": 0.44999999999999996,
        "synthetic_bounds": 0.4499999999999999,
        "diverging": None,
        "flat": None,
        "few_rows": None,
        "all_nan": None,
        "clamped": None,
        "clamped_right": None,
        "out_of_range": None,
    },
    "gravity": {
        "fisheye": {
            "init": [0.015065913370998116, 30.0, 0.5, 0.25, 0.75, None, 0, None],
            "seq": [
                [0.46, 0.39973634651600753, 1, 0.0],
                [0.4788323917137477, 0.36207156308851224, 2, 0.2],
                [0.4984431889516635, 0.3628499686126805, 3, 0.2],
                [0.39411958568738226, 0.39343691148775894, 4, 0.5],
                [0.553382297551789, 0.3725913370998117, 5, 1.0],
                [0.6, 0.28505335844318896, 6, 5.0],
                [0.25, 0.45918213613128867, 7, 5.1],
                [0.45334168684422926, 0.42655154694646225, 8, 30.0],
                [0.46263673811018446, 0.42497195468268917, 9, 31.0],
                [0.3, 0.17947269303201507, 10, 90.0],
            ],
            "attrs": ["hi", "level", "lo", "n", "prev_t", "rows_per_deg", "tau", "weight"],
        },
        "rect": {
            "init": [0.015514037795505154, 10.0, 0.25, 0.3, 0.7, None, 0, None],
            "seq": [
                [0.46, 0.3979438488179794, 1, 0.0],
                [0.46969627362219074, 0.3591587543292165, 2, 0.2],
                [0.4991900629925086, 0.35956372283296223, 3, 0.2],
                [0.41619155177120876, 0.39130832047135056, 4, 0.5],
                [0.55598141921393, 0.3698129656678681, 5, 1.0],
                [0.5125, 0.1536631746726384, 6, 5.0],
                [0.3, 0.35040304510944853, 7, 5.1],
                [0.45, 0.4189719244089897, 8, 30.0],
                [0.4568951279091134, 0.4181100334203505, 9, 31.0],
                [0.3, 0.17588769763595874, 10, 90.0],
            ],
            "attrs": ["hi", "level", "lo", "n", "prev_t", "rows_per_deg", "tau", "weight"],
        },
        "notau": {
            "init": [0.015065913370998116, 0.0, 0.5, 0.25, 0.75, None, 0, None],
            "seq": [
                [0.46, 0.39973634651600753, 1, 0.0],
                [0.45999999999999996, 0.32440677966101694, 2, 0.2],
                [0.5, 0.364406779661017, 3, 0.2],
                [0.43999999999999995, 0.4851977401129943, 4, 0.5],
                [0.47, 0.2892090395480226, 5, 1.0],
                [0.45, -0.15263653483992462, 6, 5.0],
                [0.6, 1.503954802259887, 7, 5.1],
                [0.45000000000000007, 0.41986817325800385, 8, 30.0],
                [0.45, 0.4123352165725047, 9, 31.0],
                [0.3, 0.17947269303201507, 10, 90.0],
            ],
            "attrs": ["hi", "level", "lo", "n", "prev_t", "rows_per_deg", "tau", "weight"],
        },
        "defaults": {
            "init": [0.015065913370998116, 30.0, 0.5, 0.25, 0.75, None, 0, None],
            "seq": [
                [0.46, 0.39973634651600753, 1, 0.0],
                [0.4788323917137477, 0.36207156308851224, 2, 0.2],
                [0.4984431889516635, 0.3628499686126805, 3, 0.2],
                [0.39411958568738226, 0.39343691148775894, 4, 0.5],
                [0.553382297551789, 0.3725913370998117, 5, 1.0],
                [0.6, 0.28505335844318896, 6, 5.0],
                [0.25, 0.45918213613128867, 7, 5.1],
                [0.45334168684422926, 0.42655154694646225, 8, 30.0],
                [0.46263673811018446, 0.42497195468268917, 9, 31.0],
                [0.3, 0.17947269303201507, 10, 90.0],
            ],
            "attrs": ["hi", "level", "lo", "n", "prev_t", "rows_per_deg", "tau", "weight"],
        },
        "real_pitch": {
            "n": 181,
            "head": [-12.106184112102698, -11.405720158642326, -10.474625601617682],
            "tail": [-5.558070667135358, -8.300155633246574, -8.862375357238689],
            "sum": -1280.2875880041202,
            "min": -13.014993070307309,
            "max": -1.670534264494357,
        },
        "real_gravity": {
            "series": {
                "n": 181,
                "head": [0.45000000000000007, 0.45823176668778387, 0.4686039875720503],
                "tail": [0.4733158492118079, 0.43207179756517766, 0.4236860995365351],
                "sum": 83.7218797133489,
                "min": 0.36668208562190835,
                "max": 0.5351244964782871,
            },
            "level": 0.5572058789299617,
            "n": 181,
        },
        "real_fused": {
            "series": {
                "n": 181,
                "head": [0.45000000000000007, 0.45707108541050534, 0.4649484185199755],
                "tail": [0.46172867512590327, 0.43814836123361145, 0.4312551592797514],
                "sum": 82.64366489093626,
                "min": 0.40593992683141644,
                "max": 0.4998828636746846,
            },
            "level": 0.5572058789299617,
            "n": 181,
        },
    },
    "seed_fraction": {
        "fixture_20_70": {
            "n": 50,
            "head": [0.0, 0.0, 0.0],
            "tail": [0.9910714285714286, 0.9925595238095238, 0.9449404761904762],
            "sum": 39.45833333333333,
            "min": 0.0,
            "max": 1.0,
        },
        "fixture_55_105": {
            "n": 50,
            "head": [1.0, 1.0, 1.0],
            "tail": [0.0, 0.0, 0.0],
            "sum": 20.029761904761905,
            "min": 0.0,
            "max": 1.0,
        },
        "none_class": 0.0,
        "absent_class": 0.0,
        "partial": 1.0,
        "full_box": 1.0,
        "whole_grid": 0.98,
        "tiny_box": 1.0,
        "odd_grid": 1.0,
    },
    "crosswalk": {
        "init": [{"enter_f": 0.3, "enter_s": 0.5, "exit_f": 0.15, "exit_s": 0.7, "inside": False, "_since": None}],
        "enter_run": {
            "events": [(31, "enter")],
            "states": [(0, (False, None)), (8, (False, 40.8324991658325)), (11, (True, None))],
            "attrs": ["_since", "enter_f", "enter_s", "exit_f", "exit_s", "inside"],
            "final": [True, None],
        },
        "exit_run": {
            "events": [(58, "enter"), (85, "exit")],
            "states": [
                (0, (False, 45.337003670337005)),
                (3, (True, None)),
                (25, (True, 49.507841174507845)),
                (30, (False, None)),
            ],
            "attrs": ["_since", "enter_f", "enter_s", "exit_f", "exit_s", "inside"],
            "final": [False, None],
        },
        "stationary_run": {
            "events": [(31, "enter")],
            "states": [(0, (False, None)), (8, (False, 40.8324991658325)), (11, (True, None))],
            "attrs": ["_since", "enter_f", "enter_s", "exit_f", "exit_s", "inside"],
            "final": [True, None],
        },
        "synthetic": [
            [None, False, 0.0],
            [None, False, 0.0],
            [None, False, None],
            [None, False, 1.0],
            [None, False, 1.0],
            [None, False, None],
            [None, False, 2.5],
            [None, False, 2.5],
            ["enter", True, None],
            [None, True, 4.0],
            [None, True, None],
            [None, True, 5.0],
            [None, True, 5.0],
            ["exit", False, None],
            [None, False, None],
            [None, False, None],
            [None, False, None],
            [None, False, None],
        ],
    },
    "surface": {
        "init": {
            "window_s": 10.0,
            "majority": 0.7,
            "persist_s": 8.0,
            "need_evidence": True,
            "announce_first": False,
            "lookback_s": 3.0,
            "lead_s": 2.0,
            "stable": None,
            "_window": [],
            "_evidence": [],
            "_run": None,
            "_run_since": 0.0,
            "_seen": {},
        },
        "init_empty": {
            "window_s": 10.0,
            "majority": 0.7,
            "persist_s": 8.0,
            "need_evidence": True,
            "announce_first": False,
            "lookback_s": 10.0,
            "lead_s": 1000000000.0,
            "stable": None,
            "_window": [],
            "_evidence": [],
            "_run": None,
            "_run_since": 0.0,
            "_seen": {},
        },
        "review7_default": {
            "states": [
                (0, [None, None, 1, "pedestrian", 0.0]),
                (1, [None, None, 2, "pedestrian", 0.0]),
                (2, [None, None, 3, "pedestrian", 0.0]),
                (3, [None, None, 4, "pedestrian", 0.0]),
                (4, [None, None, 5, "pedestrian", 0.0]),
                (5, [None, None, 6, "pedestrian", 0.0]),
                (6, [None, None, 7, "pedestrian", 0.0]),
                (7, [None, None, 8, "pedestrian", 0.0]),
                (8, [None, None, 9, "pedestrian", 0.0]),
                (9, [None, None, 10, "pedestrian", 0.0]),
                (10, [None, None, 11, "pedestrian", 0.0]),
                (11, [None, None, 12, "pedestrian", 0.0]),
                (12, [None, None, 13, "pedestrian", 0.0]),
                (13, [None, None, 14, "pedestrian", 0.0]),
                (14, [None, None, 15, "pedestrian", 0.0]),
                (15, [None, None, 16, "pedestrian", 0.0]),
                (16, [None, None, 17, "pedestrian", 0.0]),
                (17, [None, None, 18, "pedestrian", 0.0]),
                (18, [None, None, 19, "pedestrian", 0.0]),
                (19, [None, None, 20, "pedestrian", 0.0]),
                (20, [None, None, 21, "pedestrian", 0.0]),
                (21, [None, None, 22, "pedestrian", 0.0]),
                (22, [None, None, 23, "pedestrian", 0.0]),
                (23, [None, None, 24, "pedestrian", 0.0]),
                (24, [None, None, 25, "pedestrian", 0.0]),
                (25, [None, None, 26, "pedestrian", 0.0]),
                (26, [None, None, 27, "pedestrian", 0.0]),
                (27, [None, None, 28, "pedestrian", 0.0]),
                (28, [None, None, 29, "pedestrian", 0.0]),
                (29, [None, None, 30, "pedestrian", 0.0]),
                (30, [None, None, 31, "pedestrian", 0.0]),
                (31, [None, None, 32, "pedestrian", 0.0]),
                (32, [None, None, 33, "pedestrian", 0.0]),
                (33, [None, None, 34, "pedestrian", 0.0]),
                (34, [None, None, 35, "pedestrian", 0.0]),
                (35, [None, None, 36, "pedestrian", 0.0]),
                (36, [None, None, 37, "pedestrian", 0.0]),
                (37, [None, None, 38, "pedestrian", 0.0]),
                (38, [None, None, 39, "pedestrian", 0.0]),
                (39, [None, None, 40, "pedestrian", 0.0]),
                (40, [None, None, 41, "pedestrian", 0.0]),
                (41, [None, None, 42, "pedestrian", 0.0]),
                (42, [None, None, 43, "pedestrian", 0.0]),
                (43, [None, None, 44, "pedestrian", 0.0]),
                (44, [None, None, 45, "pedestrian", 0.0]),
                (45, [None, None, 46, "pedestrian", 0.0]),
                (46, [None, None, 47, "pedestrian", 0.0]),
                (47, [None, None, 48, "pedestrian", 0.0]),
                (48, [[None, "pedestrian", False], "pedestrian", 49, "pedestrian", 0.0]),
                (49, [None, "pedestrian", 50, "pedestrian", 0.0]),
            ],
            "stable": "pedestrian",
            "seen": {"pedestrian": [0.0, 8.174841508174842]},
            "evidence": [],
            "window": [
                [0.0, "pedestrian"],
                [0.16683350016683351, "pedestrian"],
                [0.33366700033366703, "pedestrian"],
                [8.008008008008009, "pedestrian"],
                [8.174841508174842, "pedestrian"],
            ],
        },
        "crosswalk_default": {
            "states": [
                (0, [None, None, 1, "road", 44.502836169502835]),
                (16, [None, None, 2, "pedestrian", 47.172172172172175]),
                (17, [None, None, 3, "road", 47.339005672339006]),
                (18, [None, None, 4, "road", 47.339005672339006]),
                (19, [None, None, 5, "road", 47.339005672339006]),
                (20, [None, None, 6, "road", 47.339005672339006]),
                (21, [None, None, 7, "road", 47.339005672339006]),
                (22, [None, None, 8, "pedestrian", 48.173173173173176]),
                (23, [None, None, 9, "road", 48.34000667334001]),
                (24, [None, None, 10, "road", 48.34000667334001]),
                (25, [None, None, 11, "road", 48.34000667334001]),
                (26, [None, None, 12, "road", 48.34000667334001]),
                (27, [None, None, 13, "road", 48.34000667334001]),
                (28, [None, None, 14, "road", 48.34000667334001]),
                (29, [None, None, 15, "road", 48.34000667334001]),
                (30, [None, None, 16, "road", 48.34000667334001]),
                (31, [None, None, 17, "road", 48.34000667334001]),
                (32, [None, None, 18, "road", 48.34000667334001]),
                (33, [None, None, 19, "pedestrian", 50.008341675008346]),
                (34, [None, None, 20, "pedestrian", 50.008341675008346]),
                (35, [None, None, 21, "pedestrian", 50.008341675008346]),
                (36, [None, None, 22, "pedestrian", 50.008341675008346]),
                (37, [None, None, 23, "pedestrian", 50.008341675008346]),
                (38, [None, None, 24, "pedestrian", 50.008341675008346]),
                (39, [None, None, 25, "pedestrian", 50.008341675008346]),
                (40, [None, None, 26, "pedestrian", 50.008341675008346]),
                (41, [None, None, 27, "pedestrian", 50.008341675008346]),
                (42, [None, None, 28, "pedestrian", 50.008341675008346]),
                (43, [None, None, 29, "pedestrian", 50.008341675008346]),
                (44, [None, None, 30, "pedestrian", 50.008341675008346]),
                (45, [None, None, 31, "pedestrian", 50.008341675008346]),
                (46, [None, None, 32, "pedestrian", 50.008341675008346]),
                (47, [None, None, 33, "pedestrian", 50.008341675008346]),
                (48, [None, None, 34, "pedestrian", 50.008341675008346]),
                (49, [None, None, 35, "pedestrian", 50.008341675008346]),
            ],
            "stable": None,
            "seen": {
                "road": [47.339005672339006, 49.84150817484151],
                "pedestrian": [50.008341675008346, 52.67767767767768],
            },
            "evidence": [46.171171171171174],
            "window": [
                [44.502836169502835, "road"],
                [47.172172172172175, "pedestrian"],
                [47.339005672339006, "road"],
                [52.51084417751085, "pedestrian"],
                [52.67767767767768, "pedestrian"],
            ],
        },
        "crosswalk_short_noevidence": {
            "states": [
                (0, [None, None, 0, None, 0.0]),
                (5, [None, None, 1, "pedestrian", 36.99532866199533]),
                (6, [None, None, 2, "pedestrian", 36.99532866199533]),
                (7, [None, None, 3, "pedestrian", 36.99532866199533]),
                (8, [None, None, 4, "pedestrian", 36.99532866199533]),
                (9, [None, None, 5, "pedestrian", 36.99532866199533]),
                (10, [None, None, 6, "pedestrian", 36.99532866199533]),
                (11, [None, None, 7, "pedestrian", 36.99532866199533]),
                (12, [None, None, 8, "pedestrian", 36.99532866199533]),
                (13, [None, None, 9, "pedestrian", 36.99532866199533]),
                (14, [None, None, 10, "pedestrian", 36.99532866199533]),
                (15, [None, None, 11, "pedestrian", 36.99532866199533]),
                (16, [None, None, 12, "pedestrian", 36.99532866199533]),
                (17, [[None, "pedestrian", True], "pedestrian", 13, "pedestrian", 36.99532866199533]),
                (18, [None, "pedestrian", 14, "pedestrian", 36.99532866199533]),
                (19, [None, "pedestrian", 15, "pedestrian", 36.99532866199533]),
                (20, [None, "pedestrian", 16, "pedestrian", 36.99532866199533]),
                (21, [None, "pedestrian", 17, "pedestrian", 36.99532866199533]),
                (22, [None, "pedestrian", 18, "pedestrian", 36.99532866199533]),
                (23, [None, "pedestrian", 19, "pedestrian", 36.99532866199533]),
                (24, [None, "pedestrian", 20, "pedestrian", 36.99532866199533]),
                (25, [None, "pedestrian", 21, "pedestrian", 36.99532866199533]),
                (26, [None, "pedestrian", 22, "pedestrian", 36.99532866199533]),
                (27, [None, "pedestrian", 23, "pedestrian", 36.99532866199533]),
                (28, [None, "pedestrian", 24, "pedestrian", 36.99532866199533]),
                (31, [None, "pedestrian", 23, "pedestrian", 36.99532866199533]),
                (32, [None, "pedestrian", 22, "pedestrian", 36.99532866199533]),
                (33, [None, "pedestrian", 21, "pedestrian", 36.99532866199533]),
                (34, [None, "pedestrian", 20, "pedestrian", 36.99532866199533]),
                (35, [None, "pedestrian", 19, "pedestrian", 36.99532866199533]),
                (36, [None, "pedestrian", 18, "pedestrian", 36.99532866199533]),
                (37, [None, "pedestrian", 17, "pedestrian", 36.99532866199533]),
                (38, [None, "pedestrian", 16, "pedestrian", 36.99532866199533]),
                (39, [None, "pedestrian", 15, "pedestrian", 36.99532866199533]),
                (40, [None, "pedestrian", 14, "pedestrian", 36.99532866199533]),
                (41, [None, "pedestrian", 13, "pedestrian", 36.99532866199533]),
                (42, [None, "pedestrian", 12, "pedestrian", 36.99532866199533]),
                (43, [None, "pedestrian", 11, "pedestrian", 36.99532866199533]),
                (44, [None, "pedestrian", 10, "pedestrian", 36.99532866199533]),
                (45, [None, "pedestrian", 9, "pedestrian", 36.99532866199533]),
                (46, [None, "pedestrian", 8, "pedestrian", 36.99532866199533]),
                (47, [None, "pedestrian", 7, "pedestrian", 36.99532866199533]),
                (48, [None, "pedestrian", 6, "pedestrian", 36.99532866199533]),
                (49, [None, "pedestrian", 6, "road", 44.336002669336004]),
            ],
            "stable": "pedestrian",
            "seen": {
                "pedestrian": [36.99532866199533, 41.16616616616617],
                "road": [44.336002669336004, 44.336002669336004],
            },
            "evidence": [],
            "window": [
                [40.49883216549883, "pedestrian"],
                [40.66566566566567, "pedestrian"],
                [40.8324991658325, "pedestrian"],
                [41.16616616616617, "pedestrian"],
                [44.336002669336004, "road"],
            ],
        },
        "crosswalk_short_evidence": {
            "states": [
                (0, [None, None, 1, "road", 44.502836169502835]),
                (12, [[None, "road", True], "road", 1, "road", 44.502836169502835]),
                (13, [None, "road", 1, "road", 44.502836169502835]),
                (16, [None, "road", 2, "pedestrian", 47.172172172172175]),
                (17, [None, "road", 3, "road", 47.339005672339006]),
                (18, [None, "road", 4, "road", 47.339005672339006]),
                (19, [None, "road", 5, "road", 47.339005672339006]),
                (20, [None, "road", 6, "road", 47.339005672339006]),
                (21, [None, "road", 7, "road", 47.339005672339006]),
                (22, [None, "road", 8, "pedestrian", 48.173173173173176]),
                (23, [None, "road", 9, "road", 48.34000667334001]),
                (25, [None, "road", 10, "road", 48.34000667334001]),
                (26, [None, "road", 11, "road", 48.34000667334001]),
                (27, [None, "road", 12, "road", 48.34000667334001]),
                (28, [None, "road", 13, "road", 48.34000667334001]),
                (29, [None, "road", 14, "road", 48.34000667334001]),
                (30, [None, "road", 15, "road", 48.34000667334001]),
                (31, [None, "road", 16, "road", 48.34000667334001]),
                (32, [None, "road", 17, "road", 48.34000667334001]),
                (33, [None, "road", 18, "pedestrian", 50.008341675008346]),
                (34, [None, "road", 19, "pedestrian", 50.008341675008346]),
                (35, [None, "road", 20, "pedestrian", 50.008341675008346]),
                (36, [None, "road", 21, "pedestrian", 50.008341675008346]),
                (37, [None, "road", 22, "pedestrian", 50.008341675008346]),
                (38, [None, "road", 23, "pedestrian", 50.008341675008346]),
                (39, [None, "road", 24, "pedestrian", 50.008341675008346]),
                (47, [["road", "pedestrian", True], "pedestrian", 24, "pedestrian", 50.008341675008346]),
                (48, [None, "pedestrian", 24, "pedestrian", 50.008341675008346]),
                (54, [None, "pedestrian", 24, "road", 53.51184517851185]),
            ],
            "stable": "pedestrian",
            "seen": {
                "road": [53.51184517851185, 54.34601267934602],
                "pedestrian": [50.008341675008346, 53.34501167834502],
            },
            "evidence": [52.84451117784452],
            "window": [
                [50.508842175508846, "pedestrian"],
                [50.67567567567568, "pedestrian"],
                [50.84250917584251, "pedestrian"],
                [54.17917917917918, "road"],
                [54.34601267934602, "road"],
            ],
        },
        "crosswalk_short_no_note": {
            "states": [
                (0, [None, None, 1, "road", 44.502836169502835]),
                (12, [[None, "road", True], "road", 1, "road", 44.502836169502835]),
                (13, [None, "road", 1, "road", 44.502836169502835]),
                (16, [None, "road", 2, "pedestrian", 47.172172172172175]),
                (17, [None, "road", 3, "road", 47.339005672339006]),
                (18, [None, "road", 4, "road", 47.339005672339006]),
                (19, [None, "road", 5, "road", 47.339005672339006]),
                (20, [None, "road", 6, "road", 47.339005672339006]),
                (21, [None, "road", 7, "road", 47.339005672339006]),
                (22, [None, "road", 8, "pedestrian", 48.173173173173176]),
                (23, [None, "road", 9, "road", 48.34000667334001]),
                (25, [None, "road", 10, "road", 48.34000667334001]),
                (26, [None, "road", 11, "road", 48.34000667334001]),
                (27, [None, "road", 12, "road", 48.34000667334001]),
                (28, [None, "road", 13, "road", 48.34000667334001]),
                (29, [None, "road", 14, "road", 48.34000667334001]),
                (30, [None, "road", 15, "road", 48.34000667334001]),
                (31, [None, "road", 16, "road", 48.34000667334001]),
                (32, [None, "road", 17, "road", 48.34000667334001]),
                (33, [None, "road", 18, "pedestrian", 50.008341675008346]),
                (34, [None, "road", 19, "pedestrian", 50.008341675008346]),
                (35, [None, "road", 20, "pedestrian", 50.008341675008346]),
                (36, [None, "road", 21, "pedestrian", 50.008341675008346]),
                (37, [None, "road", 22, "pedestrian", 50.008341675008346]),
                (38, [None, "road", 23, "pedestrian", 50.008341675008346]),
                (39, [None, "road", 24, "pedestrian", 50.008341675008346]),
                (54, [None, "road", 24, "road", 53.51184517851185]),
            ],
            "stable": "road",
            "seen": {
                "road": [53.51184517851185, 54.34601267934602],
                "pedestrian": [50.008341675008346, 53.34501167834502],
            },
            "evidence": [],
            "window": [
                [50.508842175508846, "pedestrian"],
                [50.67567567567568, "pedestrian"],
                [50.84250917584251, "pedestrian"],
                [54.17917917917918, "road"],
                [54.34601267934602, "road"],
            ],
        },
        "tie_ab": [
            [None, None, 1, "a", 0.0],
            [None, None, 2, "b", 0.5],
            [[None, "b", False], "b", 3, "b", 0.5],
            [None, "b", 4, "b", 0.5],
            [None, "b", 5, "a", 2.0],
            [["b", "a", True], "a", 6, "a", 2.0],
        ],
        "tie_ba": [
            [None, None, 1, "b", 0.0],
            [None, None, 2, "a", 0.5],
            [[None, "a", False], "a", 3, "a", 0.5],
            [None, "a", 4, "a", 0.5],
            [None, "a", 5, "b", 2.0],
            [["a", "b", True], "b", 6, "b", 2.0],
        ],
        "tie_none": [
            [None, None, 1, "a", 0.0],
            [None, None, 2, "b", 0.5],
            [[None, "b", False], "b", 3, "b", 0.5],
            [None, "b", 3, "b", 0.5],
            [None, "b", 4, "b", 0.5],
            [None, "b", 5, "a", 2.5],
            [["b", "a", True], "a", 6, "a", 2.5],
        ],
        "tie_adopted": [
            [None, None, 1, "x", 0.0, []],
            [[None, "x", False], "x", 2, "x", 0.0, []],
            [None, "x", 3, "x", 0.0, []],
            [None, "x", 4, "b", 3.0, [3.0]],
            [None, "x", 5, "a", 4.0, [3.0]],
            [None, "x", 6, "a", 4.0, [3.0]],
            [None, "x", 7, "b", 6.0, [3.0]],
            [None, "x", 8, "b", 6.0, [3.0]],
            [None, "x", 9, "b", 6.0, [3.0]],
            [["x", "b", True], "b", 10, "b", 6.0, []],
        ],
        "evidence_trim": [59.0, 61.0, 100.0],
    },
}


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


def _config() -> dict[str, Any]:
    with open(find_common_dir() / "config" / "collision.json") as fh:
        cfg: dict[str, Any] = json.load(fh)
    return cfg


def _fixture(name: str) -> tuple[dict[str, Any], Any]:
    with open(FIXTURES / f"{name}.json") as fh:
        meta: dict[str, Any] = json.load(fh)
    return meta, np.load(FIXTURES / f"{name}.npz")


def _legacy_api() -> Any:
    """The legacy callables, used only to generate EXPECTED (see the module docstring)."""
    return SimpleNamespace(
        walking_region=collision.walking_region,
        smooth_bounds=collision._smooth_bounds,
        estimate_horizon=collision.estimate_horizon,
        HorizonGravity=collision.HorizonGravity,
        SurfaceTracker=collision._SurfaceTracker,
        CrosswalkTracker=collision._CrosswalkTracker,
        seed_fraction=collision._seed_fraction,
    )


def _engine_api() -> Any:
    region = importlib.import_module("engine.surface.region")
    horizon = importlib.import_module("engine.surface.horizon")
    trackers = importlib.import_module("engine.surface.trackers")
    return SimpleNamespace(
        walking_region=region.walking_region,
        smooth_bounds=region.smooth_bounds,
        estimate_horizon=horizon.estimate_horizon,
        HorizonGravity=horizon.HorizonGravity,
        SurfaceTracker=trackers.SurfaceTracker,
        CrosswalkTracker=trackers.CrosswalkTracker,
        seed_fraction=trackers.seed_fraction,
    )


def _ids(cfg: dict[str, Any], names: list[str]) -> Any:
    from engine.core.classes import resolve_class_ids

    return resolve_class_ids(cfg, names)


# --------------------------------------------------------------------------
# Digests
# --------------------------------------------------------------------------


def _bound_digest(a: Any) -> list[Any]:
    valid = np.flatnonzero(~np.isnan(a))
    first = float(a[valid[0]]) if valid.size else None
    last = float(a[valid[-1]]) if valid.size else None
    return [
        str(a.dtype),
        list(a.shape),
        int(np.isnan(a).sum()),
        float(np.nansum(a)) if valid.size else 0.0,
        first,
        last,
    ]


def _region_digest(r: Any) -> Any:
    if r is None:
        return None
    return {
        "group": r.group,
        "label": r.label,
        "shape": list(r.mask.shape),
        "dtype": str(r.mask.dtype),
        "sum": int(r.mask.sum()),
        "sha": hashlib.sha256(np.packbits(r.mask).tobytes()).hexdigest(),
        "left": _bound_digest(r.left),
        "right": _bound_digest(r.right),
    }


def _series_digest(values: list[float]) -> dict[str, Any]:
    a = np.array(values, dtype=np.float64)
    return {
        "n": len(values),
        "head": [float(v) for v in a[:3]],
        "tail": [float(v) for v in a[-3:]],
        "sum": float(a.sum()),
        "min": float(a.min()),
        "max": float(a.max()),
    }


def _rle(states: list[Any]) -> list[Any]:
    """[(first frame, state)] where the state differs from the previous frame's."""
    out: list[Any] = []
    for i, s in enumerate(states):
        if not out or out[-1][1] != s:
            out.append((i, s))
    return out


def _vars(obj: Any) -> list[str]:
    return sorted(vars(obj))


# --------------------------------------------------------------------------
# Collectors (run on the legacy code for EXPECTED, on the engine in the tests)
# --------------------------------------------------------------------------


def _collect_region(api: Any) -> dict[str, Any]:
    cfg = _config()
    out: dict[str, Any] = {}
    for name, win, frames in REGION_FRAMES:
        meta, z = _fixture(name)
        ids = _ids(cfg, meta["classNames"])
        grids = z[f"{win}_grids"]
        rows = []
        for i in frames:
            r = api.walking_region(grids[i], ids, cfg)
            rows.append(_region_digest(r))
        out[name] = rows
        # the same frames with the group order reversed: key order is behaviour
        rcfg = dict(cfg)
        rcfg["surfaces"] = {**cfg["surfaces"], "groups": dict(reversed(list(cfg["surfaces"]["groups"].items())))}
        rids = _ids(rcfg, meta["classNames"])
        rev = []
        for i in frames:
            r = api.walking_region(grids[i], rids, rcfg)
            rev.append(None if r is None else [r.group, int(r.mask.sum())])
        out[name + ":reversed"] = rev
    # tie: half the seed box sidewalk, half road, same pixel counts -> the first group of the config wins
    names = _fixture("chest0004_review7")[0]["classNames"]
    grid = np.full((20, 20), names.index("flat sidewalk"), dtype=np.uint8)
    grid[:, 10:] = names.index("flat road")
    ids = _ids(cfg, names)
    r = api.walking_region(grid, ids, cfg)
    out["tie"] = _region_digest(r)
    rcfg = dict(cfg)
    rcfg["surfaces"] = {**cfg["surfaces"], "groups": dict(reversed(list(cfg["surfaces"]["groups"].items())))}
    out["tie_reversed"] = _region_digest(api.walking_region(grid, _ids(rcfg, names), rcfg))
    # a tie on max but more group pixels elsewhere in the seed box: the larger sum wins
    grid2 = grid.copy()
    grid2[18:, 10:13] = names.index("flat road")
    grid2[18:, 8:10] = names.index("flat sidewalk")
    grid2[19, 6:8] = names.index("flat bike-lane")
    out["sum_wins"] = _region_digest(api.walking_region(grid2, ids, cfg))
    # no surface class at all, and a class id beyond the bincount (grid.max() small): None
    out["none"] = _region_digest(api.walking_region(np.zeros((20, 20), dtype=np.uint8), ids, cfg))
    # a surface that is connected only through "inside" classes, and one that is not
    grid3 = np.full((20, 20), names.index("animal"), dtype=np.uint8)
    grid3[10:, 4:16] = names.index("flat sidewalk")
    grid3[5:10, 8:12] = names.index("crosswalk")
    grid3[2:4, 8:12] = names.index("flat sidewalk")
    out["inside"] = _region_digest(api.walking_region(grid3, ids, cfg))
    # tiny grid: the seed box rows / columns are at least one cell
    grid4 = np.full((3, 3), names.index("flat road"), dtype=np.uint8)
    out["tiny"] = _region_digest(api.walking_region(grid4, ids, cfg))
    return out


def _collect_smooth(api: Any) -> dict[str, Any]:
    nan = math.nan
    prev = np.array([0.1, nan, 0.5, 0.7, nan, 0.9])
    cur = np.array([0.3, 0.2, nan, 0.9, nan, 0.1])
    out: dict[str, Any] = {}
    r1 = api.smooth_bounds(None, cur)
    out["none_prev"] = [r1.tolist(), r1 is cur]
    r2 = api.smooth_bounds(prev, cur)
    out["default"] = r2.tolist()
    r3 = api.smooth_bounds(prev, cur, 0.3)
    out["alpha03"] = r3.tolist()
    r4 = api.smooth_bounds(prev, cur, 1.0)
    out["alpha1"] = r4.tolist()
    out["cur_untouched"] = cur.tolist()
    # a run over the frames of a fixture
    cfg = _config()
    meta, z = _fixture("chest0004_review7")
    ids = _ids(cfg, meta["classNames"])
    prev_left = None
    seq = []
    for i in (0, 25, 50, 75, 100):
        r = api.walking_region(z["w0_grids"][i], ids, cfg)
        prev_left = api.smooth_bounds(prev_left, r.left)
        seq.append(_bound_digest(prev_left))
    out["sequence"] = seq
    return out


def _synthetic_bounds() -> tuple[Any, Any]:
    gh = 100
    y = (np.arange(gh) + 0.5) / gh
    left = np.where(y > 0.45, 0.5 - 0.8 * (y - 0.45), np.nan)
    right = np.where(y > 0.45, 0.5 + 0.8 * (y - 0.45), np.nan)
    return left, right


def _collect_horizon_fit(api: Any) -> dict[str, Any]:
    cfg = _config()
    out: dict[str, Any] = {}
    for name, win, frames in REGION_FRAMES:
        meta, z = _fixture(name)
        ids = _ids(cfg, meta["classNames"])
        rows: list[Any] = []
        for i in frames:
            r = api.walking_region(z[f"{win}_grids"][i], ids, cfg)
            if r is None:
                rows.append(None)
                continue
            rows.append(
                [
                    api.estimate_horizon(r.left, r.right, cfg),
                    api.estimate_horizon(r.left, r.right, cfg, (0.05, 0.95)),
                    api.estimate_horizon(r.left, r.right, cfg, (0.3, 0.6)),
                ]
            )
        out[name] = rows
    left, right = _synthetic_bounds()
    out["synthetic"] = api.estimate_horizon(left, right, cfg)
    out["synthetic_bounds"] = api.estimate_horizon(left, right, cfg, (0.2, 0.8))
    out["diverging"] = api.estimate_horizon(right, left, cfg)
    out["flat"] = api.estimate_horizon(
        np.where(np.isnan(left), np.nan, 0.3), np.where(np.isnan(right), np.nan, 0.7), cfg
    )
    out["few_rows"] = api.estimate_horizon(left[:60], right[:60], cfg)
    out["all_nan"] = api.estimate_horizon(np.full(100, np.nan), np.full(100, np.nan), cfg)
    # clamped rows are dropped: a left bound at the border for every row leaves no edge rows
    out["clamped"] = api.estimate_horizon(np.zeros(100), right, cfg)
    out["clamped_right"] = api.estimate_horizon(left, np.ones(100), cfg)
    # intersection outside horizonValidRange
    far_l = np.where(np.isnan(left), np.nan, 0.5 - 0.8 * ((np.arange(100) + 0.5) / 100 - 0.05))
    far_r = np.where(np.isnan(right), np.nan, 0.5 + 0.8 * ((np.arange(100) + 0.5) / 100 - 0.05))
    out["out_of_range"] = api.estimate_horizon(far_l, far_r, cfg)
    return out


def _nearest(t: Any, mt: Any) -> Any:
    return np.array([int(np.argmin(np.abs(t - m))) for m in mt])


def _collect_gravity(api: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tag, (gh, gw, hfov, proj, cfg) in {
        "fisheye": (135, 240, 118.0, "fisheye", {"levelTauS": 30.0, "gravityWeight": 0.5}),
        "rect": (
            108,
            192,
            90.0,
            "rectilinear",
            {"levelTauS": 10.0, "gravityWeight": 0.25, "horizonValidRange": [0.3, 0.7]},
        ),
        "notau": (135, 240, 118.0, "fisheye", {"levelTauS": 0.0}),
        "defaults": (135, 240, 118.0, "fisheye", {}),
    }.items():
        hg = api.HorizonGravity(cfg, gh, gw, hfov, proj)
        init = [hg.rows_per_deg, hg.tau, hg.weight, hg.lo, hg.hi, hg.level, hg.n, hg.prev_t]
        ts = [0.0, 0.2, 0.2, 0.5, 1.0, 5.0, 5.1, 30.0, 31.0, 90.0]
        pitches = [4.0, 9.0, 9.0, -3.0, 12.0, 40.0, -60.0, 2.0, 2.5, 8.0]
        himg = [0.46, 0.46, 0.5, 0.44, 0.47, 0.45, 0.6, 0.45, 0.45, 0.3]
        seq = []
        for k, (t, p, h) in enumerate(zip(ts, pitches, himg, strict=True)):
            src = "gravity" if k % 2 == 0 else "fused"
            seq.append([hg.update(t, p, h, src), hg.level, hg.n, hg.prev_t])
        out[tag] = {"init": init, "seq": seq, "attrs": _vars(hg)}
    # the real sensor series (chest0004_review9, the window the run uses: crop +-6 s, gravity tau 0.5)
    z = _fixture("chest0004_review9")[1]
    s = {k[len("sensors_") :]: z[k] for k in z.files if k.startswith("sensors_")}
    mt = z["w0_t"]
    c = sensors.crop(s, float(mt[0]) - 6.0, float(mt[-1]) + 6.0)
    pt, pitch, _roll = sensors.gravity_angles(c, {"gravityTauS": 0.5})
    pitch_f = pitch[_nearest(pt, mt)]
    out["real_pitch"] = _series_digest([float(v) for v in pitch_f])
    for src in ("gravity", "fused"):
        hg = api.HorizonGravity(
            {"levelTauS": 30.0, "gravityWeight": 0.5, "horizonValidRange": [0.25, 0.75]}, 135, 240, 118.0, "fisheye"
        )
        vals = [
            hg.update(float(t), float(p), 0.45 + 0.02 * math.sin(0.3 * i), src)
            for i, (t, p) in enumerate(zip(mt, pitch_f, strict=True))
        ]
        out["real_" + src] = {"series": _series_digest(vals), "level": hg.level, "n": hg.n}
    return out


def _fractions(api: Any, name: str, frames: range) -> list[float]:
    cfg = _config()
    meta, z = _fixture(name)
    cw = meta["classNames"].index("crosswalk")
    return [api.seed_fraction(z["w0_grids"][i], cw, cfg["surfaces"]["seedBox"]) for i in frames]


def _collect_seed_fraction(api: Any) -> dict[str, Any]:
    cfg = _config()
    box = cfg["surfaces"]["seedBox"]
    out: dict[str, Any] = {}
    out["fixture_20_70"] = _series_digest(_fractions(api, "chest0002_crosswalk", range(20, 70)))
    out["fixture_55_105"] = _series_digest(_fractions(api, "chest0002_crosswalk", range(55, 105)))
    g = np.zeros((10, 10), dtype=np.uint8)
    g[9, 4:6] = 3
    out["none_class"] = api.seed_fraction(g, None, box)
    out["absent_class"] = api.seed_fraction(g, 7, box)
    out["partial"] = api.seed_fraction(g, 3, box)
    out["full_box"] = api.seed_fraction(g, 3, [0.4, 0.9, 0.6, 1.0])
    out["whole_grid"] = api.seed_fraction(g, 0, [0.0, 0.0, 1.0, 1.0])
    out["tiny_box"] = api.seed_fraction(g, 3, [0.45, 0.95, 0.46, 0.96])
    out["odd_grid"] = api.seed_fraction(np.full((7, 13), 2, dtype=np.uint8), 2, [0.37, 0.81, 0.63, 0.99])
    return out


def _crosswalk_run(api: Any, name: str, frames: range, stationary_from: int | None) -> dict[str, Any]:
    cfg = _config()
    meta, z = _fixture(name)
    cw = meta["classNames"].index("crosswalk")
    tr = api.CrosswalkTracker(cfg["crosswalk"])
    t = z["w0_t"]
    states = []
    events = []
    for i in frames:
        stat = stationary_from is not None and i >= stationary_from
        res = tr.update(float(t[i]), api.seed_fraction(z["w0_grids"][i], cw, cfg["surfaces"]["seedBox"]), stat)
        if res:
            events.append((i, res))
        states.append((tr.inside, tr._since))
    return {"events": events, "states": _rle(states), "attrs": _vars(tr), "final": [tr.inside, tr._since]}


def _collect_crosswalk(api: Any) -> dict[str, Any]:
    cfg = _config()
    out: dict[str, Any] = {}
    out["init"] = [vars(api.CrosswalkTracker(cfg["crosswalk"]))]
    out["enter_run"] = _crosswalk_run(api, "chest0002_crosswalk", range(20, 70), None)
    out["exit_run"] = _crosswalk_run(api, "chest0002_crosswalk", range(55, 105), None)
    out["stationary_run"] = _crosswalk_run(api, "chest0002_crosswalk", range(20, 70), 35)
    # synthetic: a break resets the enter run, stationary blocks entering, a blip resets the exit run
    tr = api.CrosswalkTracker({"enterFraction": 0.3, "enterSeconds": 1.0, "exitFraction": 0.15, "exitSeconds": 1.0})
    seq = [
        (0.0, 0.5, False),
        (0.5, 0.5, False),
        (0.9, 0.1, False),
        (1.0, 0.5, False),
        (1.4, 0.5, False),
        (2.0, 0.5, True),
        (2.5, 0.5, False),
        (3.4, 0.5, False),
        (3.5, 0.5, False),
        (4.0, 0.1, False),
        (4.5, 0.2, False),
        (5.0, 0.1, False),
        (5.5, 0.1, False),
        (6.0, 0.15, False),
        (6.9, 0.1, False),
        (7.0, 0.0, False),
        (7.9, 0.0, False),
        (8.0, 0.0, False),
    ]
    rows = []
    for t, f, st in seq:
        rows.append([tr.update(t, f, st), tr.inside, tr._since])
    out["synthetic"] = rows
    return out


def _surface_state(tr: Any, res: Any) -> Any:
    return [None if res is None else list(res), tr.stable, len(tr._window), tr._run, tr._run_since]


def _surface_run(api: Any, name: str, frames: range, scfg: dict[str, Any], evidence_at: list[int]) -> dict[str, Any]:
    cfg = _config()
    meta, z = _fixture(name)
    ids = _ids(cfg, meta["classNames"])
    tr = api.SurfaceTracker(scfg)
    t = z["w0_t"]
    states = []
    for i in frames:
        r = api.walking_region(z["w0_grids"][i], ids, cfg)
        if i in evidence_at:
            tr.note_evidence(float(t[i]))
        res = tr.update(float(t[i]), None if r is None else r.group)
        states.append(_surface_state(tr, res))
    return {
        "states": _rle(states),
        "stable": tr.stable,
        "seen": {k: list(v) for k, v in tr._seen.items()},
        "evidence": list(tr._evidence),
        "window": [[a, b] for a, b in tr._window][:3] + [[a, b] for a, b in tr._window][-2:],
    }


SHORT_CFG: dict[str, Any] = {
    "windowSeconds": 4.0,
    "majority": 0.6,
    "minPersistSeconds": 2.0,
    "requireCrossingEvidence": True,
    "announceFirstSurface": True,
    "evidenceLookbackSeconds": 3.0,
    "evidenceLeadSeconds": 2.0,
}


def _collect_surface(api: Any) -> dict[str, Any]:
    cfg = _config()
    out: dict[str, Any] = {}
    out["init"] = vars(api.SurfaceTracker(cfg["surfaces"]))
    out["init_empty"] = vars(api.SurfaceTracker({}))
    out["review7_default"] = _surface_run(api, "chest0004_review7", range(0, 50), cfg["surfaces"], [])
    out["crosswalk_default"] = _surface_run(api, "chest0002_crosswalk", range(50, 100), cfg["surfaces"], [60])
    out["crosswalk_short_noevidence"] = _surface_run(
        api, "chest0002_crosswalk", range(0, 50), {**SHORT_CFG, "requireCrossingEvidence": False}, []
    )
    out["crosswalk_short_evidence"] = _surface_run(
        api, "chest0002_crosswalk", range(50, 110), SHORT_CFG, [66, 72, 74, 100]
    )
    out["crosswalk_short_no_note"] = _surface_run(api, "chest0002_crosswalk", range(50, 110), SHORT_CFG, [])
    # ties: the group that entered the window first leads
    tie_cfg = {
        "windowSeconds": 100.0,
        "majority": 0.5,
        "minPersistSeconds": 0.5,
        "requireCrossingEvidence": False,
        "announceFirstSurface": False,
    }
    for tag, seq in (
        ("tie_ab", ["a", "b", "b", "b", "a", "a"]),
        ("tie_ba", ["b", "a", "a", "a", "b", "b"]),
        ("tie_none", ["a", "b", "b", None, "b", "a", "a"]),
    ):
        tr = api.SurfaceTracker(tie_cfg)
        rows = []
        for k, g in enumerate(seq):
            res = tr.update(k * 0.5, g)
            rows.append(_surface_state(tr, res))
        out[tag] = rows
    # a tie against an adopted surface needs evidence; evidence older than 60 s is dropped
    tr = api.SurfaceTracker(
        {**tie_cfg, "requireCrossingEvidence": True, "evidenceLookbackSeconds": 3.0, "evidenceLeadSeconds": 2.0}
    )
    rows = []
    for k, g in enumerate(["x", "x", "x", "b", "a", "a", "b", "b", "b", "b"]):
        if k == 3:
            tr.note_evidence(3.0)
        res = tr.update(float(k), g)
        rows.append([*_surface_state(tr, res), list(tr._evidence)])
    out["tie_adopted"] = rows
    tr = api.SurfaceTracker(tie_cfg)
    for e in (0.0, 30.0, 59.0, 61.0, 100.0):
        tr.note_evidence(e)
    out["evidence_trim"] = list(tr._evidence)
    return out


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


def _same(actual: Any, expected: Any, where: str = "") -> None:
    if isinstance(expected, float):
        assert isinstance(actual, float), where
        if math.isnan(expected):
            assert math.isnan(actual), where
        else:
            assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12), where
    elif isinstance(expected, dict):
        assert isinstance(actual, dict), where
        assert list(actual) == list(expected), where
        for k in expected:
            _same(actual[k], expected[k], f"{where}/{k}")
    elif isinstance(expected, list | tuple):
        assert isinstance(actual, list | tuple), where
        assert len(actual) == len(expected), where
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            _same(a, e, f"{where}[{i}]")
    else:
        assert actual == expected, where
        assert type(actual) is type(expected), where


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_facade_identity() -> None:
    region = importlib.import_module("engine.surface.region")
    horizon = importlib.import_module("engine.surface.horizon")
    trackers = importlib.import_module("engine.surface.trackers")
    assert collision.walking_region is region.walking_region
    assert collision._smooth_bounds is region.smooth_bounds
    assert collision.estimate_horizon is horizon.estimate_horizon
    assert collision.HorizonGravity is horizon.HorizonGravity
    assert collision._SurfaceTracker is trackers.SurfaceTracker
    assert collision._CrosswalkTracker is trackers.CrosswalkTracker
    assert collision._seed_fraction is trackers.seed_fraction


def test_package_reexports_the_public_api() -> None:
    pkg = importlib.import_module("engine.surface")
    region = importlib.import_module("engine.surface.region")
    horizon = importlib.import_module("engine.surface.horizon")
    trackers = importlib.import_module("engine.surface.trackers")
    expected = {
        "walking_region": region.walking_region,
        "smooth_bounds": region.smooth_bounds,
        "estimate_horizon": horizon.estimate_horizon,
        "HorizonGravity": horizon.HorizonGravity,
        "SurfaceTracker": trackers.SurfaceTracker,
        "CrosswalkTracker": trackers.CrosswalkTracker,
        "seed_fraction": trackers.seed_fraction,
    }
    for name, obj in expected.items():
        assert name in pkg.__all__, name
        assert getattr(pkg, name) is obj, name


def test_instance_attribute_lists() -> None:
    api = _engine_api()
    cfg = _config()
    assert _vars(api.SurfaceTracker(cfg["surfaces"])) == _ATTRS_SURFACE
    assert _vars(api.CrosswalkTracker(cfg["crosswalk"])) == _ATTRS_CROSSWALK
    assert _vars(api.HorizonGravity({}, 135, 240, 118.0, "fisheye")) == _ATTRS_HORIZON


def test_walking_region_on_fixture_frames_ties_and_edges() -> None:
    _same(_collect_region(_engine_api()), EXPECTED["region"])


def test_smooth_bounds() -> None:
    _same(_collect_smooth(_engine_api()), EXPECTED["smooth"])


def test_estimate_horizon() -> None:
    _same(_collect_horizon_fit(_engine_api()), EXPECTED["horizon_fit"])


def test_horizon_gravity_synthetic_and_real_sensor_series() -> None:
    _same(_collect_gravity(_engine_api()), EXPECTED["gravity"])


def test_seed_fraction() -> None:
    _same(_collect_seed_fraction(_engine_api()), EXPECTED["seed_fraction"])


def test_crosswalk_tracker_sequences() -> None:
    _same(_collect_crosswalk(_engine_api()), EXPECTED["crosswalk"])


def test_surface_tracker_sequences_and_ties() -> None:
    _same(_collect_surface(_engine_api()), EXPECTED["surface"])
