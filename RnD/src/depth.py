"""Monocular relative depth (Depth Anything 3 Small / Base, Apache-2.0, "Any-view" series).

Weights live on the host in ~/models/depth-anything/DA3-SMALL and DA3-BASE and are
mounted read-only at /base-models (compose.yaml); see README "Depth model".

Single-image output is *relative* depth: positive, larger = farther, correct only up to
an unknown global scale (no metres). Consumers calibrate the scale themselves
(collision.py uses the walker's gait).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import torch

DEFAULT_MODEL_ROOT = "/base-models/depth-anything"
VARIANT_DIRS = {"da3-small": "DA3-SMALL", "da3-base": "DA3-BASE"}
PROCESS_RES = 504  # DA3's default: longest side is resized to 504 (rounded to a multiple of 14)


class DepthModel:
    def __init__(self, device: torch.device, variant: str = "da3-small"):
        if variant not in VARIANT_DIRS:
            raise ValueError(f"unknown depth variant {variant!r}; one of {list(VARIANT_DIRS)}")
        os.environ.setdefault("DA3_LOG_LEVEL", "WARN")  # it logs 3 INFO lines per frame otherwise
        from depth_anything_3.api import DepthAnything3

        self.device, self.variant = device, variant
        root = os.environ.get("HACKEYE_DEPTH_MODEL_ROOT", DEFAULT_MODEL_ROOT)
        path = Path(root) / VARIANT_DIRS[variant]
        if not (path / "model.safetensors").is_file():
            raise FileNotFoundError(f"Depth model weights not found in {path} (see README 'Depth model')")
        self.model = DepthAnything3.from_pretrained(str(path)).to(device=device).eval()
        # DA3's own forward() autocasts to bf16/fp16, so weights stay fp32.
        print(f"[depth] loaded {variant} from {path}", file=sys.stderr)

    @torch.inference_mode()
    def predict_relative(self, rgb: np.ndarray) -> np.ndarray:
        """Relative depth (larger = farther, unknown scale) for one RGB (H, W, 3 uint8) frame, as a
        float32 (h, w) map at the resolution DA3 processed at (not the source size)."""
        pred = self.model.inference([np.ascontiguousarray(rgb)], process_res=PROCESS_RES)
        return pred.depth[0].astype(np.float32)
