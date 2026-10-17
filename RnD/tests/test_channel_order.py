"""v26.1.9: the models must see true RGB. Ultralytics' predict() assumes a numpy
image is OpenCV BGR, so SegmentationModel / BusDetector convert at that boundary.
The reference is Ultralytics' own file loader (cv2.imread -> BGR -> RGB)."""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pytest

import models

MODEL = Path("/hackeye-models/Yolo26m-sem-HackEye20261012-544.pt")


def test_to_ultralytics_reverses_channels_contiguously():
    rgb = np.zeros((2, 3, 3), np.uint8)
    rgb[..., 0] = 10  # R
    rgb[..., 2] = 30  # B
    bgr = models.to_ultralytics(rgb)
    assert bgr.flags["C_CONTIGUOUS"]
    assert (bgr[..., 0] == 30).all() and (bgr[..., 2] == 10).all()


@pytest.mark.skipif(not MODEL.exists() or os.environ.get("HACKEYE_GPU_TESTS") != "1",
                    reason="needs the segmentation release and a GPU: set HACKEYE_GPU_TESTS=1 in the lab container")
def test_segmentation_matches_ultralytics_file_loader(tmp_path):
    import torch
    seg = models.SegmentationModel(str(MODEL), torch.device("cuda"))
    rng = np.random.default_rng(0)
    # A colour-asymmetric scene: swapping R and B must change the prediction.
    rgb = np.zeros((544, 960, 3), np.uint8)
    rgb[:272] = (90, 140, 220)    # sky-blue top
    rgb[272:] = (120, 110, 100)   # grey-brown ground
    rgb = np.clip(rgb.astype(int) + rng.integers(-20, 20, rgb.shape), 0, 255).astype(np.uint8)
    p = tmp_path / "frame.png"
    cv2.imwrite(str(p), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    ref = seg.model.predict(source=str(p), imgsz=(544, 960), verbose=False)[0].semantic_mask.data.cpu().numpy()
    assert (seg.predict_class_grid(rgb, 960, 544) == ref).all()
