"""Opt-in real-model smoke test: HACKEYE_GPU_TESTS=1 (needs the GPU and /base-models weights)."""
import os
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("HACKEYE_GPU_TESTS") != "1", reason="set HACKEYE_GPU_TESTS=1")

VIDEO = Path("/media/GOPR4929.MP4")


def test_da3_metric_on_gopr4929():
    import depth
    import gpu_guard

    cap = cv2.VideoCapture(str(VIDEO))
    cap.set(cv2.CAP_PROP_POS_MSEC, 100_000)
    ok, bgr = cap.read()
    assert ok
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    model = depth.DepthModel(gpu_guard.assert_torch_cuda())
    focal = depth.focal_px(rgb.shape[1], 120.0, "auto")
    model.predict_metric(rgb, focal)  # warm-up
    t0 = time.perf_counter()
    n = 10
    for _ in range(n):
        d = model.predict_metric(rgb, focal)
    ms = (time.perf_counter() - t0) * 1000 / n
    print(f"\nDA3 metric: {ms:.1f} ms/frame, map {d.shape}, median {np.median(d):.2f} m, "
          f"p5 {np.percentile(d, 5):.2f} p95 {np.percentile(d, 95):.2f}")
    assert np.isfinite(d).all()
    assert 1.0 < float(np.median(d)) < 60.0
