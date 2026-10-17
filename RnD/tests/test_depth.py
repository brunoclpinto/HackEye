"""Depth model wrapper: relative prediction and variant handling (no GPU)."""
import types

import numpy as np
import pytest

import depth


def test_predict_relative_returns_processed_resolution_float32():
    net = np.full((1, 4, 6), 3.0, np.float16)
    seen = {}
    model = depth.DepthModel.__new__(depth.DepthModel)
    model.variant = "da3-small"
    model.model = types.SimpleNamespace(
        inference=lambda imgs, process_res: seen.update(n=len(imgs), res=process_res) or types.SimpleNamespace(depth=net))
    out = model.predict_relative(np.zeros((10, 12, 3), np.uint8))
    assert out.shape == (4, 6) and out.dtype == np.float32 and np.allclose(out, 3.0)
    assert seen == {"n": 1, "res": depth.PROCESS_RES}


def test_variant_dirs_and_unknown_variant():
    assert depth.VARIANT_DIRS == {
        "da3-small": "depth-anything/DA3-SMALL", "da3-base": "depth-anything/DA3-BASE",
        "da2-metric-outdoor-small": "depth-anything/DA2-METRIC-OUTDOOR-SMALL-hf",
        "unidepth-v2-s": "unidepth/unidepth-v2-vits14"}
    assert {v: u for v, (u, _, _) in depth.VARIANTS.items()} == {
        "da3-small": "relative", "da3-base": "relative", "da2-metric-outdoor-small": "metric", "unidepth-v2-s": "metric"}
    with pytest.raises(ValueError, match="unknown depth variant"):
        depth.DepthModel(None, "da3-metric-large")


def test_missing_weights_raise(monkeypatch, tmp_path):
    pytest.importorskip("depth_anything_3")
    monkeypatch.setenv("HACKEYE_DEPTH_MODEL_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="DA3-BASE"):
        depth.DepthModel(None, "da3-base")


@pytest.mark.parametrize("variant", ["da2-metric-outdoor-small", "unidepth-v2-s"])
def test_new_variants_validate_and_report_missing_weights(monkeypatch, tmp_path, variant):
    monkeypatch.setenv("HACKEYE_DEPTH_MODEL_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError, match=depth.VARIANT_DIRS[variant].split("/")[1]):
        depth.DepthModel(None, variant)


def test_predict_relative_refuses_metric_variants():
    model = depth.DepthModel.__new__(depth.DepthModel)
    model.variant = "unidepth-v2-s"
    model.predict = lambda rgb: (np.ones((2, 2), np.float32), "metric")
    with pytest.raises(ValueError, match="metric"):
        model.predict_relative(np.zeros((4, 4, 3), np.uint8))


def test_dispatch_da3_predict_returns_relative():
    model = depth.DepthModel.__new__(depth.DepthModel)
    model.variant = "da3-base"
    model.model = types.SimpleNamespace(inference=lambda imgs, process_res: types.SimpleNamespace(depth=np.ones((1, 3, 3))))
    d, units = model.predict(np.zeros((6, 6, 3), np.uint8))
    assert units == "relative" and d.dtype == np.float32
