"""Pinhole camera helpers, the top-left-origin ``Box`` with ``iou``, and small numeric helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["Box", "focal_px", "ground_distance_m", "iou", "lateral_m", "round_opt", "steps_to"]


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


def focal_px(grid_w: float, hfov_deg: float) -> float:
    """Focal length in grid pixels: (W / 2) / tan(hfov / 2)."""
    return (grid_w / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)


def ground_distance_m(
    y_norm: float, horizon_y: float, camera_height_m: float, grid_h: float, f_px: float
) -> float | None:
    """Distance to a ground point seen at ``y_norm``: H * f / ((y - horizon) * grid_h)."""
    if y_norm <= horizon_y:
        return None
    return camera_height_m * f_px / ((y_norm - horizon_y) * grid_h)


def lateral_m(x_norm: float, distance_m: float, grid_w: float, f_px: float) -> float:
    """Sideways offset in metres (+ = right): (x - 0.5) * W * d / f."""
    return (x_norm - 0.5) * grid_w * distance_m / f_px


def steps_to(distance_m: float, step_length_m: float) -> float:
    """Steps until we reach the item: ``distance / step length`` (v26.1.6).

    The distance is gait calibrated (see ``_Scale``) and the step length is the prior or the
    per-recording value, so the number is stable: it no longer divides by a noisy instantaneous ego
    speed (v26.1.5 steps swung 25.9 -> 12.7 in 0.2 s).
    """
    return distance_m / step_length_m


def round_opt(v: float | None, nd: int) -> float | None:
    return None if v is None else round(float(v), nd)
