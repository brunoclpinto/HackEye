"""Depth model wrapper: relative prediction and variant handling (no GPU)."""
import types

import numpy as np
import pytest

import depth


def test_predict_relative_returns_processed_resolution_float32():
    net = np.full((1, 4, 6), 3.0, np.float16)
    seen = {}
    model = depth.DepthModel.__new__(depth.DepthModel)
    model.model = types.SimpleNamespace(
        inference=lambda imgs, process_res: seen.update(n=len(imgs), res=process_res) or types.SimpleNamespace(depth=net))
    out = model.predict_relative(np.zeros((10, 12, 3), np.uint8))
    assert out.shape == (4, 6) and out.dtype == np.float32 and np.allclose(out, 3.0)
    assert seen == {"n": 1, "res": depth.PROCESS_RES}


def test_variant_dirs_and_unknown_variant():
    assert depth.VARIANT_DIRS == {"da3-small": "DA3-SMALL", "da3-base": "DA3-BASE"}
    with pytest.raises(ValueError, match="unknown depth variant"):
        depth.DepthModel(None, "da3-metric-large")


def test_missing_weights_raise(monkeypatch, tmp_path):
    pytest.importorskip("depth_anything_3")
    monkeypatch.setenv("HACKEYE_DEPTH_MODEL_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="DA3-BASE"):
        depth.DepthModel(None, "da3-base")
