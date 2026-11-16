"""Characterisation tests for engine.infer.depth.model and engine.infer.egoflow.flow (v26.3.0 p5-01).

Literals were printed by the legacy ``depth`` / ``egoflow`` modules in the hackeye-rnd image before the move. No GPU or
weights: ``DepthModel`` is built with ``__new__`` and fake inference objects; flow frames are synthetic (seeded). The
engine modules are imported inside each test (they do not exist yet).
"""

from __future__ import annotations

import types
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
import pytest

import depth
import egoflow

if TYPE_CHECKING:
    from numpy.typing import NDArray

VARIANTS = {
    "da3-small": ("relative", "depth-anything/DA3-SMALL", "model.safetensors"),
    "da3-base": ("relative", "depth-anything/DA3-BASE", "model.safetensors"),
    "da2-metric-outdoor-small": ("metric", "depth-anything/DA2-METRIC-OUTDOOR-SMALL-hf", "model.safetensors"),
    "unidepth-v2-s": ("metric", "unidepth/unidepth-v2-vits14", "model.safetensors"),
}


cv: Any = cv2


def _frames() -> tuple[NDArray[Any], NDArray[Any], NDArray[Any]]:
    rs = np.random.RandomState(1)
    a = rs.randint(0, 256, (90, 160)).astype(np.uint8)
    blurred = cv2.GaussianBlur(a, (0, 0), 2.0)
    base = cv.normalize(blurred, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    shifted = np.roll(base, 3, axis=1)
    zoom = cv2.warpAffine(base, cv2.getRotationMatrix2D((80, 45), 0, 1.15), (160, 90))
    return base, shifted, zoom


def test_frames_are_the_probed_ones() -> None:
    base, _, zoom = _frames()
    assert int(base.sum()) == 1789367
    assert int(zoom.sum()) == 1760970


def test_depth_facade_identity() -> None:
    from engine.infer.depth import model

    assert depth.DepthModel is model.DepthModel
    assert depth.VARIANTS is model.VARIANTS
    assert depth.VARIANT_DIRS is model.VARIANT_DIRS
    assert depth.PROCESS_RES is model.PROCESS_RES
    assert depth.DEFAULT_MODEL_ROOT is model.DEFAULT_MODEL_ROOT


def test_depth_constants() -> None:
    from engine.infer.depth import model

    assert model.PROCESS_RES == 504
    assert model.DEFAULT_MODEL_ROOT == "/base-models"
    assert model.VARIANTS == VARIANTS
    assert {v: d for v, (_, d, _) in VARIANTS.items()} == model.VARIANT_DIRS


def test_depth_model_attributes() -> None:
    from engine.infer.depth.model import DepthModel

    names = sorted(n for n in vars(DepthModel) if not n.startswith("__"))
    assert names == [
        "_load_da2_metric_outdoor_small",
        "_load_da3_base",
        "_load_da3_small",
        "_load_unidepth_v2_s",
        "predict",
        "predict_relative",
    ]
    assert DepthModel._load_da3_base is DepthModel._load_da3_small


def test_depth_unknown_variant() -> None:
    from engine.infer.depth.model import DepthModel

    with pytest.raises(ValueError, match="unknown depth variant"):
        DepthModel(None, "da3-metric-large")


def test_depth_missing_weights(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from engine.infer.depth.model import DepthModel

    monkeypatch.setenv("HACKEYE_DEPTH_MODEL_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="DA3-BASE"):
        DepthModel(None, "da3-base")


def test_depth_predict_relative_new() -> None:
    from engine.infer.depth.model import PROCESS_RES, DepthModel

    seen: dict[str, Any] = {}

    def inference(imgs: list[NDArray[Any]], process_res: int) -> Any:
        seen.update(n=len(imgs), res=process_res)
        return types.SimpleNamespace(depth=np.full((1, 4, 6), 3.0, np.float16))

    model = DepthModel.__new__(DepthModel)
    model.variant = "da3-small"
    model.model = types.SimpleNamespace(inference=inference)
    out = model.predict_relative(np.zeros((10, 12, 3), np.uint8))
    assert out.shape == (4, 6)
    assert out.dtype == np.float32
    assert np.all(out == 3.0)
    assert seen == {"n": 1, "res": PROCESS_RES}


def test_depth_predict_dispatch_da3() -> None:
    from engine.infer.depth.model import DepthModel

    model = DepthModel.__new__(DepthModel)
    model.variant = "da3-base"
    ones = types.SimpleNamespace(depth=np.ones((1, 3, 3)))
    model.model = types.SimpleNamespace(inference=lambda imgs, process_res: ones)
    d, units = model.predict(np.zeros((6, 6, 3), np.uint8))
    assert units == "relative"
    assert d.dtype == np.float32
    assert d.shape == (3, 3)


def test_depth_predict_relative_refuses_metric() -> None:
    from engine.infer.depth.model import DepthModel

    model = DepthModel.__new__(DepthModel)
    model.variant = "unidepth-v2-s"
    model.predict = lambda rgb: (np.ones((2, 2), np.float32), "metric")
    with pytest.raises(ValueError, match="unidepth-v2-s is a metric model; use predict"):
        model.predict_relative(np.zeros((4, 4, 3), np.uint8))


def test_egoflow_facade_identity() -> None:
    from engine.infer.egoflow import flow

    assert egoflow.residual_flow is flow.residual_flow
    assert egoflow.ResidualFlowTrack is flow.ResidualFlowTrack
    assert egoflow.LAG_FRAMES is flow.LAG_FRAMES
    assert egoflow.GRAD_MIN is flow.GRAD_MIN
    assert egoflow.MIN_TEXTURED is flow.MIN_TEXTURED


def test_egoflow_constants() -> None:
    from engine.infer.egoflow import flow

    assert (flow.LAG_FRAMES, flow.GRAD_MIN, flow.MIN_TEXTURED) == (6, 40.0, 300)


def test_residual_flow_values() -> None:
    from engine.infer.egoflow.flow import residual_flow

    base, shifted, zoom = _frames()
    # A rigid shift or an identical frame leaves (numerically) no residual; the legacy values are ~1e-6..1e-4 and depend
    # on SIMD rounding in Farneback, so only their order of magnitude is pinned.
    assert residual_flow(base, base) < 1e-3
    assert residual_flow(base, shifted) < 1e-3
    assert residual_flow(base, zoom) == pytest.approx(5.136363983154297, rel=1e-12, abs=1e-12)


def test_residual_flow_bland_frame_is_nan() -> None:
    from engine.infer.egoflow.flow import residual_flow

    bland = np.full((90, 160), 128, np.uint8)
    assert np.isnan(residual_flow(bland, bland))


def test_residual_flow_track_default_lag() -> None:
    from engine.infer.egoflow.flow import ResidualFlowTrack

    base, _, zoom = _frames()
    track = ResidualFlowTrack()
    assert track.lag == 6
    assert track._ring == []
    outs = [track.push(base if i % 2 == 0 else zoom) for i in range(9)]
    assert all(np.isnan(o) for o in outs[:6])
    assert all(o < 1e-3 for o in outs[6:])
    assert len(track._ring) == 6


def test_residual_flow_track_lag2() -> None:
    from engine.infer.egoflow.flow import ResidualFlowTrack

    base, shifted, zoom = _frames()
    track = ResidualFlowTrack(lag=2)
    outs = [track.push(f) for f in [base, shifted, zoom, base, shifted, zoom, base, zoom]]
    assert np.isnan(outs[0]) and np.isnan(outs[1])
    assert outs[2] == pytest.approx(5.136363983154297, rel=1e-12, abs=1e-12)
    assert outs[3] < 1e-3
    assert outs[4] == pytest.approx(4.624785423278809, rel=1e-12, abs=1e-12)
    assert outs[5] == pytest.approx(5.136363983154297, rel=1e-12, abs=1e-12)
    assert outs[6] < 1e-3
    assert outs[7] < 1e-3
    assert len(track._ring) == 2
