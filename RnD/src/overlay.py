"""Port of the safety-overlay rasterizer.

This is currently duplicated almost verbatim between
Apple/Models/Helpers/SaveMov.swift (~line 333) and
Apple/HackEye-cli/CLIDebugOutput.swift (~line 174) — this single Python
implementation is what both would collapse into in a Stage 2 shared core.
"""

from __future__ import annotations

import numpy as np

from segmentation import CLASSES, SAFETY_LEVELS, SegmentationGrid


def render_safety_overlay(letterboxed_rgb: np.ndarray, grid: SegmentationGrid, alpha: float) -> np.ndarray:
    det_h, det_w = letterboxed_rgb.shape[:2]
    grid_h, grid_w = grid.grid_h, grid.grid_w

    col_idx = (np.arange(det_w) * grid_w) // det_w
    row_idx = (np.arange(det_h) * grid_h) // det_h
    col_idx = np.clip(col_idx, 0, grid_w - 1)
    row_idx = np.clip(row_idx, 0, grid_h - 1)

    sampled = grid.class_ids[np.ix_(row_idx, col_idx)]  # (det_h, det_w)

    rgba = np.zeros((det_h, det_w, 4), dtype=np.uint8)
    alpha_byte = int(round(max(0.0, min(1.0, alpha)) * 255))

    for cls_id in np.unique(sampled):
        info = CLASSES.get(int(cls_id))
        if info is None or info["safetyLevel"] == 0:
            continue
        mask = sampled == cls_id
        color = SAFETY_LEVELS[info["safetyLevel"]]["color"]
        rgba[mask, 0] = color[0]
        rgba[mask, 1] = color[1]
        rgba[mask, 2] = color[2]
        rgba[mask, 3] = alpha_byte

    a = (rgba[..., 3:4].astype(np.float32)) / 255.0
    composited = rgba[..., :3].astype(np.float32) * a + letterboxed_rgb.astype(np.float32) * (1.0 - a)
    return composited.astype(np.uint8)
