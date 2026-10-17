"""Monocular metric depth (Depth Anything 3 Metric Large, Apache-2.0).

Weights live on the host in ~/models/depth-anything/DA3METRIC-LARGE and are
mounted read-only at /base-models (compose.yaml); see README "Depth model".

Metric conversion (Depth-Anything-3 README, "Monocular Metric Depth"):
    metric_depth = focal * net_output / 300.
with `focal` the focal length in pixels *of the image the network saw*. We
therefore compute the focal at the processed width, not the source width.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import torch

from collision import resolve_projection

DEFAULT_MODEL_DIR = "/base-models/depth-anything/DA3METRIC-LARGE"
METRIC_DIVISOR = 300.0
PROCESS_RES = 504  # DA3's default: longest side is resized to 504 (rounded to a multiple of 14)


def focal_px(width: float, hfov_deg: float, projection: str = "rectilinear") -> float:
    """Focal length in pixels for an image `width` px wide with horizontal FOV `hfov_deg`.

    rectilinear: (W/2) / tan(HFOV/2).  fisheye (equidistant, r = f*theta): (W/2) / (HFOV/2 in rad)."""
    half = math.radians(hfov_deg) / 2
    if resolve_projection(projection, hfov_deg) == "fisheye":
        return (width / 2) / half
    return (width / 2) / math.tan(half)


class DepthModel:
    def __init__(self, device: torch.device, model_dir: str | None = None):
        os.environ.setdefault("DA3_LOG_LEVEL", "WARN")  # it logs 3 INFO lines per frame otherwise
        from depth_anything_3.api import DepthAnything3

        self.device = device
        path = model_dir or os.environ.get("HACKEYE_DEPTH_MODEL_DIR", DEFAULT_MODEL_DIR)
        if not (Path(path) / "model.safetensors").is_file():
            raise FileNotFoundError(f"Depth model weights not found in {path} (see README 'Depth model')")
        self.model = DepthAnything3.from_pretrained(path).to(device=device).eval()
        # DA3's own forward() autocasts to bf16/fp16 (bf16 on this GPU), so weights stay fp32.
        print(f"[depth] loaded DA3 metric from {path}", file=sys.stderr)

    @torch.inference_mode()
    def predict_metric(self, rgb: np.ndarray, focal_px: float) -> np.ndarray:
        """Metric depth in metres for one RGB (H, W, 3 uint8) frame.

        `focal_px` is the focal length in pixels of `rgb`. Returns a float32 (h, w) map at the
        resolution DA3 processed at (not the source size)."""
        pred = self.model.inference([np.ascontiguousarray(rgb)], process_res=PROCESS_RES)
        net = pred.depth[0].astype(np.float32)
        focal_proc = focal_px * net.shape[1] / rgb.shape[1]
        return net * (focal_proc / METRIC_DIVISOR)
