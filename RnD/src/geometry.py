"""Port of Box + LetterboxMeta from Apple/Models/Domain/ImageLetterboxer.swift.

Pure logic, zero image-library imports — deliberately, mirroring Box.swift /
the coordinate-math half of ImageLetterboxer.swift. This is exactly the math
a shared `common/core` would carry in Stage 2, and it's the piece most likely
to silently drift (see the plan's cross-implementation parity note). The
actual pixel resize lives in letterbox.py, which does need cv2/numpy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Box:
    """Top-left origin box, matching Box.swift."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def w(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def h(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.w * self.h


def iou(a: Box, b: Box) -> float:
    """Intersection-over-union of two boxes; 0 when both are degenerate."""
    xa, ya = max(a.x1, b.x1), max(a.y1, b.y1)
    xb, yb = min(a.x2, b.x2), min(a.y2, b.y2)
    inter = max(0.0, xb - xa) * max(0.0, yb - ya)
    union = a.area + b.area - inter
    if union <= 0:
        return 0.0
    return inter / union


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
        src_w=float(src_w), src_h=float(src_h),
        dst_w=float(dst_w), dst_h=float(dst_h),
        scale=scale, pad_x=pad_x, pad_y=pad_y,
    )


def expand_box(b: Box, src_w: float, src_h: float, margin: float) -> Box:
    """Mirrors BusDetector.expandBox / clampBox."""
    if margin <= 0:
        return _clamp_box(b, src_w, src_h)
    mx, my = b.w * margin, b.h * margin
    return _clamp_box(Box(b.x1 - mx, b.y1 - my, b.x2 + mx, b.y2 + my), src_w, src_h)


def _clamp_box(b: Box, src_w: float, src_h: float) -> Box:
    x1 = max(0.0, min(src_w, b.x1))
    x2 = max(0.0, min(src_w, b.x2))
    y1 = max(0.0, min(src_h, b.y1))
    y2 = max(0.0, min(src_h, b.y2))
    return Box(x1=min(x1, x2), y1=min(y1, y2), x2=max(x1, x2), y2=max(y1, y2))
