"""Depth model helpers: focal length formulas and the metric conversion (no GPU)."""
import math
import types

import numpy as np
import pytest

import depth


def test_focal_rectilinear():
    assert depth.focal_px(1920, 90, "rectilinear") == pytest.approx(960.0)
    assert depth.focal_px(1000, 60, "rectilinear") == pytest.approx(500 / math.tan(math.radians(30)))


def test_focal_fisheye_equidistant():
    assert depth.focal_px(1920, 180, "fisheye") == pytest.approx(960 / (math.pi / 2))
    assert depth.focal_px(1000, 120, "fisheye") == pytest.approx(500 / math.radians(60))


def test_focal_auto_follows_hfov():
    assert depth.focal_px(1000, 118, "auto") == pytest.approx(depth.focal_px(1000, 118, "fisheye"))
    assert depth.focal_px(1000, 80, "auto") == pytest.approx(depth.focal_px(1000, 80, "rectilinear"))
    assert depth.resolve_projection(None, 100) == "fisheye"
    assert depth.resolve_projection("rectilinear", 160) == "rectilinear"


def test_predict_metric_scales_focal_to_processed_width(monkeypatch):
    """metric = focal_at_processed_res * net / 300 (DA3 README, DA3METRIC-LARGE)."""
    net = np.full((1, 4, 6), 3.0, np.float32)
    pred = types.SimpleNamespace(depth=net)
    model = depth.DepthModel.__new__(depth.DepthModel)
    model.model = types.SimpleNamespace(inference=lambda imgs, process_res: pred)
    rgb = np.zeros((10, 12, 3), np.uint8)             # source width 12, processed width 6
    out = model.predict_metric(rgb, focal_px=600.0)   # focal at width 6 = 300
    assert out.shape == (4, 6)
    assert np.allclose(out, 3.0 * 300.0 / 300.0)
