"""Opt-in real-model smoke test: HACKEYE_GPU_TESTS=1 (needs the GPU and /base-models weights)."""
import os
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("HACKEYE_GPU_TESTS") != "1", reason="set HACKEYE_GPU_TESTS=1")

VIDEO = Path("/media/GOPR4929.MP4")


@pytest.mark.parametrize("variant", ["da3-small", "da3-base"])
def test_da3_relative_on_gopr4929(variant):
    import depth
    import gpu_guard

    cap = cv2.VideoCapture(str(VIDEO))
    cap.set(cv2.CAP_PROP_POS_MSEC, 100_000)
    ok, bgr = cap.read()
    assert ok
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    model = depth.DepthModel(gpu_guard.assert_torch_cuda(), variant)
    model.predict_relative(rgb)  # warm-up
    t0 = time.perf_counter()
    n = 10
    for _ in range(n):
        d = model.predict_relative(rgb)
    ms = (time.perf_counter() - t0) * 1000 / n
    h, w = d.shape
    ground = float(np.median(d[int(0.8 * h):, int(0.4 * w):int(0.6 * w)]))      # bottom centre: near the walker
    ahead = float(np.median(d[int(0.3 * h):int(0.5 * h), int(0.4 * w):int(0.6 * w)]))  # centre-top: farther
    print(f"\n{variant}: {ms:.1f} ms/frame, map {d.shape}, range {d.min():.3f}-{d.max():.3f}, "
          f"ground {ground:.3f} < ahead {ahead:.3f}")
    assert np.isfinite(d).all() and (d > 0).all()
    assert ground < ahead   # relative depth: larger = farther


@pytest.mark.parametrize("variant", ["da2-metric-outdoor-small", "unidepth-v2-s"])
def test_metric_on_gopr4929(variant):
    import depth
    import gpu_guard

    cap = cv2.VideoCapture(str(VIDEO))
    cap.set(cv2.CAP_PROP_POS_MSEC, 100_000)
    ok, bgr = cap.read()
    assert ok
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    model = depth.DepthModel(gpu_guard.assert_torch_cuda(), variant)
    model.predict(rgb)  # warm-up
    t0 = time.perf_counter()
    n = 10
    for _ in range(n):
        d, units = model.predict(rgb)
    ms = (time.perf_counter() - t0) * 1000 / n
    h, w = d.shape
    ground = float(np.median(d[int(0.8 * h):, int(0.4 * w):int(0.6 * w)]))
    ahead = float(np.median(d[int(0.3 * h):int(0.5 * h), int(0.4 * w):int(0.6 * w)]))
    med = float(np.median(d))
    print(f"\n{variant}: {ms:.1f} ms/frame, map {d.shape}, median {med:.2f} m, "
          f"ground {ground:.2f} m < ahead {ahead:.2f} m")
    assert units == "metric" and np.isfinite(d).all()
    assert 1.0 < med < 80.0
    assert ground < ahead
