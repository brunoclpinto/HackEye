"""Characterisation tests for engine.worldmap config, pose and helpers (v26.3.0 p3-01).

Every literal below was printed by the legacy ``worldmap`` functions (``load_config``, ``class_kinds``,
``integrate_pose``, ``frames_from_hazards``, ``first_depth_scale``, ``settings_from_hazards``, ``PoseTracker``) in the
hackeye-rnd image on today's code, fed with the inputs built by the helpers of this file. The engine modules are
imported inside each test (they do not exist yet).
"""

from __future__ import annotations

import importlib
import json
import lzma
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

import collision
import groundfuse
import worldmap
from common_paths import find_common_dir

if TYPE_CHECKING:
    import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
EQ_CASE = FIXTURES / "equivalence" / "cases" / "4929_review4__w0__default.json.xz"
N_FRAMES = 8


def _chest_names() -> list[str]:
    names: list[str] = json.loads((FIXTURES / "chest0004_review10.json").read_text())["classNames"]
    return names


def _coll_cfg() -> dict[str, Any]:
    cfg: dict[str, Any] = json.loads((find_common_dir() / "config" / "collision.json").read_text())
    return cfg


def _egos() -> tuple[np.ndarray[Any, Any], list[dict[str, Any]]]:
    """20 synthetic ego frames at 5 Hz: a stationary frame (7), a None heading (12), a sharp turn (15)."""
    times = np.arange(20, dtype=float) * 0.2
    egos: list[dict[str, Any]] = []
    for i in range(20):
        ego: dict[str, Any] = {"speedMps": 1.0 + 0.1 * i, "headingDeg": 3.0 * i - 10.0, "stationary": i == 7}
        if i == 12:
            ego["headingDeg"] = None
        if i == 15:
            ego["headingDeg"] = 120.0
        egos.append(ego)
    return times, egos


def _hazards() -> dict[str, Any]:
    """The first N_FRAMES frames (and the settings) of a real chest run from the equivalence fixtures."""
    with lzma.open(EQ_CASE) as fh:
        h: dict[str, Any] = json.loads(fh.read())["hazards"]
    out = dict(h)
    out["frames"] = h["frames"][:N_FRAMES]
    return out


EXPECTED_KIND_LEN = 256
EXPECTED_KINDS = {
    0: 3,
    1: 2,
    2: 1,
    3: 2,
    4: 2,
    5: 2,
    6: 2,
    7: 1,
    8: 1,
    9: 1,
    10: 1,
    11: 1,
    12: 1,
    13: 1,
    14: 1,
    15: 1,
    16: 1,
    17: 1,
    18: 2,
    19: 2,
    20: 2,
    21: 3,
    22: 3,
    23: 1,
    24: 1,
    25: 1,
    26: 1,
    27: 1,
    29: 1,
    31: 1,
    32: 2,
    33: 1,
    34: 2,
    35: 2,
    36: 1,
    37: 2,
    38: 1,
    39: 2,
    40: 2,
    41: 2,
    42: 3,
    45: 1,
}
EXPECTED_CFG_KEYS = [
    "alignDeg",
    "alignMinCells",
    "alignMinGain",
    "alignMinVotes",
    "alignMoveDeg",
    "alignShiftM",
    "alignShiftStepM",
    "alignStepDeg",
    "alignStride",
    "alignWindow",
    "cellM",
    "classes",
    "confFullWeight",
    "conflictFactor",
    "decay",
    "faceClasses",
    "faceDepthRows",
    "faceGroundContact",
    "faceJoinCols",
    "faceJoinFrac",
    "faceOutlierFrac",
    "faceRatioClamp",
    "faceRatioMinBases",
    "faceScaleOccluded",
    "faceSmoothCols",
    "faceThicknessM",
    "gapCloseM",
    "groundScale",
    "halfLifeSeconds",
    "hiddenBinDeg",
    "hiddenThicknessM",
    "lateralModel",
    "maxRangeM",
    "minForwardM",
    "objectClearBottomM",
    "objectClearFactor",
    "objectClearMarginM",
    "objectClearRays",
    "objectVoteGain",
    "objectWinShare",
    "occluderClasses",
    "poseAlign",
    "rangeWeightM",
    "snapshot",
    "surfaceHiddenFactor",
    "version",
    "voteCap",
    "weightFloor",
    "windowM",
]
EXPECTED_VERSION = "v26.2.11"
EXPECTED_POSE = [
    [0.0, 0.0, -10.0],
    [-0.03251807044851434, 0.21758348993962173, -7.0],
    [-0.05552105105336809, 0.4564785775477447, -4.0],
    [-0.06686209176835545, 0.7162311151590278, -1.0],
    [-0.06441866182881074, 0.9962204536169956, 2.0],
    [-0.046104099968353685, 1.2956608931435556, 5.0],
    [-0.0098790715626235, 1.613603886960064, 8.0],
    [-0.0098790715626235, 1.613603886960064, 11.0],
    [0.06803918945509352, 1.9650704495232398, 14.0],
    [0.16958977236483108, 2.3312500217425165, 17.0],
    [0.29651163492686794, 2.710579483824996, 20.0],
    [0.4504421501510729, 3.101354862377447, 23.0],
    [0.6223638466863536, 3.5063769978965214, 23.0],
    [0.8240145742093289, 3.9198222591941376, 29.0],
    [1.0676329884304672, 4.33340425620607, 32.0],
    [1.5527808515684647, 4.454365204005904, 120.0],
    [2.0632269869612503, 4.553585881601707, 38.0],
    [2.4067092259112433, 4.970263156631076, 41.0],
    [2.7850397421760125, 5.383138465244745, 44.0],
    [3.198725002685438, 5.789665838538658, 47.0],
]
EXPECTED_TRACKER_ATTRS = ["last_heading", "prev_t", "wm"]
EXPECTED_HOLD_S = 5.0
EXPECTED_FRAMES = [
    (0.254, 1.0, None, None, -0.4, None),
    (0.335, 1.0, 0.292, None, -1.5, None),
    (0.362, 1.0, 0.291, None, -2.4, None),
    (0.408, 1.0, None, None, -2.0, None),
    (0.439, 1.0, None, None, -1.3, None),
    (0.427, 1.0, 0.291, None, -1.6, None),
    (0.421, 1.0, 0.29, None, -3.8, 1.25),
    (0.424, 1.0, 0.291, None, -6.5, 1.25),
]
EXPECTED_FRAME_KEYS = ["dcorr", "depthScale", "ego", "horizon", "scale"]
EXPECTED_FDS = 0.292
EXPECTED_SETTINGS = {
    "hfovDeg": 118.0,
    "cameraHeightM": 1.282,
    "lateralOffsetM": 0.0,
    "projection": "fisheye",
    "distanceSource": "depth",
    "objectDistance": "depth",
    "useHorizon": True,
}
EXPECTED_CONSTS = (255, 0, 1, 2, 3)


def test_moved_names_are_the_engine_objects() -> None:
    config = importlib.import_module("engine.worldmap.config")
    helpers = importlib.import_module("engine.worldmap.helpers")
    pose = importlib.import_module("engine.worldmap.pose")

    owners: list[tuple[str, Any]] = [
        ("load_config", config),
        ("class_kinds", config),
        ("UNKNOWN", config),
        ("KIND_IGNORE", config),
        ("KIND_SURFACE", config),
        ("KIND_OBJECT", config),
        ("KIND_MOVER", config),
        ("PoseTracker", pose),
        ("integrate_pose", pose),
        ("face_contact_samples", helpers),
        ("frames_from_hazards", helpers),
        ("first_depth_scale", helpers),
        ("settings_from_hazards", helpers),
    ]
    for name, mod in owners:
        assert getattr(worldmap, name) is getattr(mod, name), name
    assert worldmap.collision is collision
    assert worldmap.groundfuse is groundfuse


def test_constants() -> None:
    config = importlib.import_module("engine.worldmap.config")

    got = (config.UNKNOWN, config.KIND_IGNORE, config.KIND_SURFACE, config.KIND_OBJECT, config.KIND_MOVER)
    assert got == EXPECTED_CONSTS


def test_load_config_keys_and_version() -> None:
    config = importlib.import_module("engine.worldmap.config")

    cfg = config.load_config()
    assert sorted(cfg.keys()) == EXPECTED_CFG_KEYS
    assert cfg["version"] == EXPECTED_VERSION


def test_default_config_loader_sees_facade_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    config = importlib.import_module("engine.worldmap.config")

    sentinel: dict[str, Any] = {"patched": True}
    monkeypatch.setattr(worldmap, "load_config", lambda path=None: sentinel)
    assert config.default_config_loader() is sentinel


def test_class_kinds_on_chest_names() -> None:
    config = importlib.import_module("engine.worldmap.config")

    kind = config.class_kinds(config.load_config(), _chest_names())
    assert kind.dtype == np.uint8
    assert len(kind) == EXPECTED_KIND_LEN
    got = {i: int(v) for i, v in enumerate(kind) if v}
    assert got == EXPECTED_KINDS


def test_pose_tracker_attributes() -> None:
    pose = importlib.import_module("engine.worldmap.pose")

    tr = pose.PoseTracker(_coll_cfg())
    assert sorted(vars(tr).keys()) == EXPECTED_TRACKER_ATTRS
    assert tr.wm.hold_s == EXPECTED_HOLD_S
    assert tr.prev_t is None
    assert tr.last_heading == 0.0


def test_integrate_pose_matches_legacy() -> None:
    pose = importlib.import_module("engine.worldmap.pose")

    times, egos = _egos()
    got = pose.integrate_pose(times, egos, _coll_cfg())
    assert got.shape == (20, 3)
    assert got.tolist() == EXPECTED_POSE


def test_frames_from_hazards_on_real_run() -> None:
    helpers = importlib.import_module("engine.worldmap.helpers")

    frames = helpers.frames_from_hazards(_hazards())
    assert len(frames) == N_FRAMES
    assert sorted(frames[0].keys()) == EXPECTED_FRAME_KEYS
    got = [
        (f["horizon"], f["scale"], f["depthScale"], f["dcorr"], f["ego"].get("headingDeg"), f["ego"].get("speedMps"))
        for f in frames
    ]
    assert got == EXPECTED_FRAMES


def test_first_depth_scale() -> None:
    helpers = importlib.import_module("engine.worldmap.helpers")

    frames = helpers.frames_from_hazards(_hazards())
    assert helpers.first_depth_scale(frames) == EXPECTED_FDS
    assert helpers.first_depth_scale(None) is None
    assert helpers.first_depth_scale([]) is None
    synthetic: list[dict[str, Any]] = [
        {"depthScale": None},
        {"depthScale": 0.0},
        {"depthScale": 0.92},
        {"depthScale": 1.1},
    ]
    assert helpers.first_depth_scale(synthetic) == 0.92


def test_settings_from_hazards() -> None:
    helpers = importlib.import_module("engine.worldmap.helpers")

    assert helpers.settings_from_hazards(_hazards()) == EXPECTED_SETTINGS
