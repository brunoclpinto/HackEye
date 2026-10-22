"""Monocular depth for the Lab, several interchangeable variants.

  da3-small / da3-base        Depth Anything 3 (Apache-2.0): *relative* depth, positive, larger = farther,
                              correct only up to an unknown global scale (collision.py calibrates it by gait).
  da2-metric-outdoor-small    Depth Anything V2 Metric Outdoor Small (Apache-2.0, transformers): metres.
  unidepth-v2-s               UniDepth v2 ViT-S (CC-BY-NC-4.0, official package): metres, camera intrinsics
                              are estimated by the model itself (none are passed: production cameras are unknown).

Weights live on the host under ~/models and are mounted read-only at /base-models (compose.yaml);
see README "Depth model". Every variant imports its package lazily, so a missing optional
package only breaks that variant.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import torch

DEFAULT_MODEL_ROOT = "/base-models"
# variant -> (units, weights dir relative to the model root, file that must exist there)
VARIANTS = {
    "da3-small": ("relative", "depth-anything/DA3-SMALL", "model.safetensors"),
    "da3-base": ("relative", "depth-anything/DA3-BASE", "model.safetensors"),
    "da2-metric-outdoor-small": ("metric", "depth-anything/DA2-METRIC-OUTDOOR-SMALL-hf", "model.safetensors"),
    "unidepth-v2-s": ("metric", "unidepth/unidepth-v2-vits14", "model.safetensors"),
}
VARIANT_DIRS = {v: d for v, (_, d, _) in VARIANTS.items()}
PROCESS_RES = 504  # DA3's default: longest side is resized to 504 (rounded to a multiple of 14)


class DepthModel:
    def __init__(self, device: torch.device, variant: str = "da3-small"):
        if variant not in VARIANTS:
            raise ValueError(f"unknown depth variant {variant!r}; one of {list(VARIANTS)}")
        self.device, self.variant = device, variant
        self.units, rel_dir, probe = VARIANTS[variant]
        root = os.environ.get("HACKEYE_DEPTH_MODEL_ROOT", DEFAULT_MODEL_ROOT)
        path = Path(root) / rel_dir
        if not (path / probe).is_file():
            raise FileNotFoundError(f"Depth model weights not found in {path} (see README 'Depth model')")
        self._intrinsics_logged = False
        getattr(self, "_load_" + variant.replace("-", "_"))(path)
        print(f"[depth] loaded {variant} from {path}", file=sys.stderr)

    # -- loaders ---------------------------------------------------------------------------
    def _load_da3_small(self, path: Path):
        os.environ.setdefault("DA3_LOG_LEVEL", "WARN")  # it logs 3 INFO lines per frame otherwise
        from depth_anything_3.api import DepthAnything3

        # DA3's own forward() autocasts to bf16/fp16, so weights stay fp32.
        self.model = DepthAnything3.from_pretrained(str(path)).to(device=self.device).eval()

    _load_da3_base = _load_da3_small

    def _load_da2_metric_outdoor_small(self, path: Path):
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        self.processor = AutoImageProcessor.from_pretrained(str(path), local_files_only=True)
        self.model = AutoModelForDepthEstimation.from_pretrained(str(path), local_files_only=True).to(self.device).eval()

    def _load_unidepth_v2_s(self, path: Path):
        import warnings

        from unidepth.models import UniDepthV2

        # No resolution_level set: the model's default pixel bounds apply (it only warns about that).
        warnings.filterwarnings("ignore", message=".*resolution_level not set.*")
        self.model = UniDepthV2.from_pretrained(str(path)).to(self.device).eval()

    # -- inference -------------------------------------------------------------------------
    @torch.inference_mode()
    def predict(self, rgb: np.ndarray) -> tuple[np.ndarray, str]:
        """Depth for one RGB (H, W, 3 uint8) frame -> (float32 (h, w) map, units) with units "relative"
        (larger = farther, unknown scale) or "metric" (metres). Map size is the model's own (DA3: 504 long side),
        not necessarily the source size."""
        rgb = np.ascontiguousarray(rgb)
        if self.variant.startswith("da3-"):
            pred = self.model.inference([rgb], process_res=PROCESS_RES)
            return pred.depth[0].astype(np.float32), "relative"
        if self.variant == "da2-metric-outdoor-small":
            inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)
            out = self.model(**inputs)
            h, w = rgb.shape[:2]
            if hasattr(self.processor, "post_process_depth_estimation"):
                d = self.processor.post_process_depth_estimation(out, target_sizes=[(h, w)])[0]["predicted_depth"]
            else:
                d = torch.nn.functional.interpolate(out.predicted_depth[:, None], size=(h, w), mode="bicubic",
                                                    align_corners=False)[0, 0]
            return d.float().cpu().numpy(), "metric"
        # unidepth-v2-s: no camera passed, the model predicts its own intrinsics
        t = torch.from_numpy(rgb).permute(2, 0, 1).contiguous().to(self.device)  # uint8 CxHxW; infer() normalises
        pred = self.model.infer(t)
        if not self._intrinsics_logged:
            self._intrinsics_logged = True
            k = pred["intrinsics"][0].float().cpu().numpy()
            print(f"[depth] unidepth estimated intrinsics for {rgb.shape[1]}x{rgb.shape[0]}: "
                  f"fx={k[0, 0]:.1f} fy={k[1, 1]:.1f} cx={k[0, 2]:.1f} cy={k[1, 2]:.1f}", file=sys.stderr)
        return pred["depth"][0, 0].float().cpu().numpy(), "metric"

    def predict_relative(self, rgb: np.ndarray) -> np.ndarray:
        """Relative depth map (kept for DA3 callers); only valid for the relative variants."""
        d, units = self.predict(rgb)
        if units != "relative":
            raise ValueError(f"{self.variant} is a metric model; use predict()")
        return d
