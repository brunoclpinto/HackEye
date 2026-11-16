"""The GPU model cache (v26.3.0 p5-04): one segmentation and one depth model, loaded on first use, released when idle.

The model classes are imported lazily by their flat names (`models`, `depth`, `segmentation`), so a test that replaces
`sys.modules["models"]` is seen.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from lab.store import requests as store_requests
from lab.store import runs, util


class _ModelCache:
    def __init__(self) -> None:
        self.path: str | None = None
        self.device: str | None = None  # "gpu" | "cpu" the segmentation model was built for
        self.model = None
        self.class_names: list[str] = []
        self.depth_model = None
        self.depth_variant: str | None = None
        self.depth_device: str | None = None
        self.last_used = 0.0

    @staticmethod
    def _torch_device(device: str) -> Any:
        """GPU asserts CUDA (no fallback, exits like before); CPU is only used when the run asks for it."""
        if device == "cpu":
            import torch

            torch.set_num_threads(store_requests._cpu_threads())
            return torch.device("cpu")
        import gpu_guard

        return gpu_guard.assert_torch_cuda()

    def get(self, path: str, device: str = "gpu") -> Any:
        if self.path != path or self.device != device:
            self.release()
            (runs.LAB_DIR / ".ultralytics").mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("YOLO_CONFIG_DIR", str(runs.LAB_DIR / ".ultralytics"))
            import segmentation
            from models import SegmentationModel

            t0 = time.perf_counter()
            self.model = SegmentationModel(path, self._torch_device(device))
            self.path, self.device = path, device
            self.class_names = [segmentation.CLASSES[i]["name"] for i in sorted(segmentation.CLASSES)]
            util._log(f"model loaded: {Path(path).name} on {device} ({time.perf_counter() - t0:.1f}s)")
        self.last_used = time.monotonic()
        return self.model

    def get_depth(self, variant: str = "da3-small", device: str = "gpu") -> Any:
        """The depth model of `variant` on `device`, loaded on first use (only runs that ask for depth pay for it)."""
        if self.depth_model is not None and (self.depth_variant, self.depth_device) != (variant, device):
            self.depth_model = None
            import gc

            gc.collect()
        if self.depth_model is None:
            from depth import DepthModel

            t0 = time.perf_counter()
            self.depth_model = DepthModel(self._torch_device(device), variant)
            self.depth_variant, self.depth_device = variant, device
            util._log(f"depth model {variant} loaded ({time.perf_counter() - t0:.1f}s)")
        self.last_used = time.monotonic()
        return self.depth_model

    def release(self) -> None:
        if self.model is None and self.depth_model is None:
            return
        import torch

        name = Path(self.path).name if self.path else None
        had_depth = self.depth_model is not None
        self.model, self.path, self.device, self.depth_model = None, None, None, None
        import gc

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        util._log(f"model released: {name}{' + depth' if had_depth else ''}")
