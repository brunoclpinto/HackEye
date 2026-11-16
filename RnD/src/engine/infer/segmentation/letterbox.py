"""Letterbox geometry and the CPU reference letterbox (ImageLetterboxer.swift's letterboxWithMeta).

``LetterboxMeta`` / ``letterbox_params`` are the pure coordinate math (port of
Apple/Models/Domain/ImageLetterboxer.swift, zero image-library imports); ``letterbox_with_meta`` is the
pixel-resize half and needs cv2/numpy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt

from engine.core.geom import Box


@dataclass
class LetterboxMeta:
    """Mirrors LetterboxMeta.swift — maps boxes between original <-> detector
    coordinate spaces (top-left origin)."""

    src_w: float
    src_h: float
    dst_w: float
    dst_h: float
    scale: float
    pad_x: float
    pad_y: float

    def dst_to_src(self, b: Box) -> Box:
        inv = 1.0 / max(self.scale, 1e-9)
        return Box(
            x1=(b.x1 - self.pad_x) * inv,
            y1=(b.y1 - self.pad_y) * inv,
            x2=(b.x2 - self.pad_x) * inv,
            y2=(b.y2 - self.pad_y) * inv,
        )

    def clamp_to_src(self, b: Box) -> Box:
        x1 = max(0.0, min(self.src_w, b.x1))
        x2 = max(0.0, min(self.src_w, b.x2))
        y1 = max(0.0, min(self.src_h, b.y1))
        y2 = max(0.0, min(self.src_h, b.y2))
        return Box(x1=min(x1, x2), y1=min(y1, y2), x2=max(x1, x2), y2=max(y1, y2))


def letterbox_params(src_w: float, src_h: float, dst_w: float, dst_h: float) -> LetterboxMeta:
    """Compute letterbox scale/padding without touching any pixels."""
    scale = min(dst_w / max(src_w, 1e-9), dst_h / max(src_h, 1e-9))
    resized_w = max(1, round(src_w * scale))
    resized_h = max(1, round(src_h * scale))
    pad_x = (dst_w - resized_w) / 2.0
    pad_y = (dst_h - resized_h) / 2.0
    return LetterboxMeta(
        src_w=float(src_w),
        src_h=float(src_h),
        dst_w=float(dst_w),
        dst_h=float(dst_h),
        scale=scale,
        pad_x=pad_x,
        pad_y=pad_y,
    )


def letterbox_with_meta(src_rgb: npt.NDArray[Any], dst_w: int, dst_h: int) -> tuple[npt.NDArray[Any], LetterboxMeta]:
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
