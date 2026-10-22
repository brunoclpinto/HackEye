"""Model loading.

Both detection and segmentation use Ultralytics' own `.predict()` pipeline.
Confirmed empirically (ultralytics 8.4.167, 2026-09-30): 'yolo26s-sem' is a
first-class Ultralytics checkpoint with task='semantic', and
Results.semantic_mask gives an
already-argmaxed per-pixel class-id tensor at full input resolution.
This superseded an earlier raw-forward workaround written when semantic
segmentation wasn't assumed to be a supported Ultralytics task — see git
history on this file if that path is ever needed again (e.g. for a
CoreML-export parity check against raw logits).

The safety mapping is chosen from the checkpoint's own class names (see
segmentation.select_mapping): 124-class Mapillary Vistas v2.0 ->
common/config/safety_mapping.json, the 48-class HackEye merge ->
safety_mapping_hackeye48.json.
"""

from __future__ import annotations

import sys

import numpy as np
import torch
from ultralytics import YOLO

import segmentation


def to_ultralytics(rgb: np.ndarray) -> np.ndarray:
    """Ultralytics' predict() treats a numpy image as OpenCV BGR and flips it to
    RGB itself, so our RGB arrays must be handed over as BGR. Passing RGB straight
    in made every model see red and blue swapped (fixed in v26.1.9)."""
    return np.ascontiguousarray(rgb[..., ::-1])


def load_detector(path: str, device: torch.device) -> YOLO:
    model = YOLO(path)
    model.to(device)
    return model


class SegmentationModel:
    def __init__(self, path: str, device: torch.device):
        self.device = device
        self.model = YOLO(path)
        self.model.to(device)
        if self.model.task != "semantic":
            print(
                f"[models] WARNING: {path} has task={self.model.task!r}, expected 'semantic'. "
                f"Results.semantic_mask may not exist — see models/README.md."
            )
        mapping = segmentation.select_mapping(list(self.model.names.values()))
        print(f"[models] safety mapping: {mapping.name} ({segmentation.NUM_CLASSES} classes)", file=sys.stderr)

    def predict_class_grid(self, letterboxed_rgb, dst_w: int, dst_h: int):
        """Returns a (dst_h, dst_w) numpy array of class ids."""
        results = self.model.predict(
            source=to_ultralytics(letterboxed_rgb), imgsz=(dst_h, dst_w), device=self.device, verbose=False,
        )
        return results[0].semantic_mask.data.cpu().numpy()
