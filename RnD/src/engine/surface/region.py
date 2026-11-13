"""Walking region: the surface group under the seed box and its per-row bounds."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from engine.core.classes import FOUR_CONNECTIVITY, ClassIds
from engine.core.types import Region


def walking_region(grid: npt.NDArray[np.integer[Any]], ids: ClassIds, config: dict[str, Any]) -> Region | None:
    """Region of the surface group under the seed box, or None without surface pixels."""
    gh, gw = grid.shape
    x0, y0, x1, y1 = config["surfaces"]["seedBox"]
    box = grid[
        int(y0 * gh) : max(int(math.ceil(y1 * gh)), int(y0 * gh) + 1),  # noqa: RUF046
        int(x0 * gw) : max(int(math.ceil(x1 * gw)), int(x0 * gw) + 1),  # noqa: RUF046
    ]
    counts = np.bincount(box.ravel(), minlength=int(grid.max()) + 1)
    best: tuple[int, int, str] | None = None
    for group, cls in ids.surface_groups.items():
        if cls.size == 0:
            continue
        per_class = counts[cls[cls < len(counts)]]
        if per_class.size == 0 or per_class.max() == 0:
            continue
        key = (int(per_class.max()), int(per_class.sum()), group)  # ties: more group pixels
        if best is None or key[:2] > best[:2]:
            best = key
    if best is None:
        return None
    group = best[2]
    group_ids = ids.surface_groups[group]
    seed = np.isin(grid, group_ids)
    seed_box = np.zeros_like(seed)
    seed_box[
        int(y0 * gh) : max(int(math.ceil(y1 * gh)), int(y0 * gh) + 1),  # noqa: RUF046
        int(x0 * gw) : max(int(math.ceil(x1 * gw)), int(x0 * gw) + 1),  # noqa: RUF046
    ] = True
    allowed = seed | np.isin(grid, ids.inside)
    labels, _ = ndimage.label(allowed, structure=FOUR_CONNECTIVITY)
    keep = np.unique(labels[seed & seed_box])
    keep = keep[keep > 0]
    mask = np.isin(labels, keep)
    left = np.full(gh, np.nan)
    right = np.full(gh, np.nan)
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size:
        first = mask[rows].argmax(axis=1)
        last = gw - 1 - mask[rows][:, ::-1].argmax(axis=1)
        left[rows] = first / gw
        right[rows] = (last + 1) / gw
    return Region(group, config["surfaces"]["groups"][group]["label"], mask, left, right)


def smooth_bounds(
    prev: npt.NDArray[np.float64] | None, cur: npt.NDArray[np.float64], alpha: float = 0.5
) -> npt.NDArray[np.float64]:
    """Per-row EMA; a row that is invalid now stays invalid, a new row starts at its value."""
    if prev is None:
        return cur.copy()
    out = cur.copy()
    both = ~np.isnan(prev) & ~np.isnan(cur)
    out[both] = (1 - alpha) * prev[both] + alpha * cur[both]
    return out
