"""The pixel-resize half of ImageLetterboxer.swift's letterboxWithMeta —
split from geometry.py because this part genuinely needs cv2/numpy, unlike
the pure coordinate math.
"""

from __future__ import annotations

import cv2
import numpy as np

from geometry import LetterboxMeta, letterbox_params


def letterbox_with_meta(src_rgb: np.ndarray, dst_w: int, dst_h: int) -> tuple[np.ndarray, LetterboxMeta]:
    """CPU reference letterbox: centered resize onto a black canvas.

    Apple's production path does this on GPU via CoreImage+Metal for the live
    camera frame (see the plan's letterbox carve-out) — this CPU version is
    the shared reference implementation any platform can fall back to, and
    the only one this R&D rig uses.

    Resampling kernel is bilinear (cv2.INTER_LINEAR), matching the Swift
    letterbox in spirit. This is a correctness contract, not a quality
    preference — a different kernel changes detections.
    """
    src_h, src_w = src_rgb.shape[:2]
    meta = letterbox_params(src_w, src_h, dst_w, dst_h)

    resized_w = max(1, round(src_w * meta.scale))
    resized_h = max(1, round(src_h * meta.scale))
    resized = cv2.resize(src_rgb, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)

    canvas = np.zeros((dst_h, dst_w, 3), dtype=src_rgb.dtype)
    ox, oy = round(meta.pad_x), round(meta.pad_y)
    canvas[oy : oy + resized_h, ox : ox + resized_w] = resized

    return canvas, meta
