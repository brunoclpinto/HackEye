"""Port of Box + LetterboxMeta from Apple/Models/Domain/ImageLetterboxer.swift.

Pure logic, zero image-library imports — deliberately, mirroring Box.swift /
the coordinate-math half of ImageLetterboxer.swift. This is exactly the math
a shared `common/core` would carry in Stage 2, and it's the piece most likely
to silently drift (see the plan's cross-implementation parity note). The
letterbox math moved to engine.infer.segmentation.letterbox (re-exported here); the pixel resize is in letterbox.py.
"""

from __future__ import annotations

from engine.core.geom import Box, iou  # noqa: F401
from engine.infer.segmentation.letterbox import LetterboxMeta, letterbox_params  # noqa: F401


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
