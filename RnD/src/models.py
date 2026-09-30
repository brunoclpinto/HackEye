"""Model loading.

Detection uses Ultralytics' full predict() pipeline (see detect.py docstring
for why). Segmentation cannot: a 19-class Cityscapes *semantic* segmentation
head is not a task Ultralytics' high-level API knows about (its "segment"
task is *instance* segmentation with a different output format), so we load
the checkpoint via Ultralytics (for convenience) but call the underlying
torch module directly to get raw [1, 19, gridH, gridW] logits.
"""

from __future__ import annotations

import sys

import torch
from ultralytics import YOLO


def load_detector(path: str, device: torch.device) -> YOLO:
    model = YOLO(path)
    model.to(device)
    return model


class SegmentationModel:
    """Wraps a YOLO checkpoint's underlying nn.Module for raw-logit forward
    passes. Validates output shape on first use — see segmentation.parse_grid
    for the actual channel-count check.
    """

    def __init__(self, path: str, device: torch.device):
        self.device = device
        self._yolo = YOLO(path)
        self._yolo.to(device)
        self.net = self._yolo.model
        self.net.eval()

    @torch.no_grad()
    def forward(self, letterboxed_rgb) -> "torch.Tensor":
        tensor = torch.from_numpy(
            (letterboxed_rgb.astype("float32") / 255.0)
        ).permute(2, 0, 1).unsqueeze(0).to(self.device)

        raw = self.net(tensor)
        if isinstance(raw, (tuple, list)):
            raw = raw[0]
        if not isinstance(raw, torch.Tensor):
            print(
                f"[models] segmentation model forward() returned {type(raw)}, "
                "expected a raw tensor. The checkpoint's forward pass may include "
                "its own postprocessing — inspect RnD/src/models.py:SegmentationModel.",
                file=sys.stderr,
            )
            sys.exit(1)
        return raw.detach().float().cpu().numpy()
