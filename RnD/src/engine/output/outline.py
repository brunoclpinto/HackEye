"""Item outlines: the outer contour of an item's own connected component, simplified for hazards.json."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from engine.core.types import Item

__all__ = [
    "DIRS",
    "OUTLINE_EPS_PX",
    "OUTLINE_MAX_POINTS",
    "dp_open",
    "item_full",
    "item_outline",
    "simplify_polygon",
    "trace_outline",
]

OUTLINE_EPS_PX = 0.75  # Douglas-Peucker tolerance in grid pixels
OUTLINE_MAX_POINTS = 32  # epsilon is raised until the outline fits

DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))  # east, south, west, north (x right, y down)


def trace_outline(mask: npt.NDArray[np.bool_]) -> list[tuple[int, int]]:
    """Outer boundary of the 4-connected component ``mask`` (bool, True = member) as pixel-corner vertices.

    Walks the pixel borders with the component on the right-hand side (square tracing on the corner lattice),
    starting at the top-left corner of the first pixel in row-major order. The result is a closed polygon in
    (x, y) = (column, row) corner coordinates, collinear vertices dropped; holes are ignored. Corner
    coordinates make the extent equal ``bbox`` exactly (``[min col, min row, max col + 1, max row + 1]``), and
    diagonal-only contacts are not crossed (the walk turns right there: 4-connectivity, as in detect_items).
    """
    m = np.pad(np.asarray(mask, dtype=bool), 1)  # padded: pixel (c, r) is m[r + 1, c + 1]
    r0, c0 = np.argwhere(m)[0]
    x0, y0 = int(c0) - 1, int(r0) - 1

    def inside(c: int, r: int) -> bool:
        return bool(m[r + 1, c + 1])

    # pixels ahead of vertex (x, y) when moving in direction d: (left, right)
    ahead = (
        lambda x, y: ((x, y - 1), (x, y)),  # east
        lambda x, y: ((x, y), (x - 1, y)),  # south
        lambda x, y: ((x - 1, y), (x - 1, y - 1)),  # west
        lambda x, y: ((x - 1, y - 1), (x, y - 1)),
    )  # north
    x, y, d = x0, y0, 3  # arrive at the start corner heading north
    pts: list[tuple[int, int]] = []
    limit = 4 * m.size + 8
    for _ in range(limit):
        (lc, lr), (rc, rr_) = ahead[d](x, y)
        if not inside(rc, rr_):
            nd = (d + 1) % 4  # right: the wall ends
        elif inside(lc, lr):
            nd = (d + 3) % 4  # left: blocked
        else:
            nd = d
        if nd != d:
            pts.append((x, y))
        d = nd
        x, y = x + DIRS[d][0], y + DIRS[d][1]
        if (x, y, d) == (x0, y0, 3):
            break
    return pts


def dp_open(pts: npt.NDArray[np.float64], eps: float) -> list[int]:
    """Douglas-Peucker on an open polyline: indices of the kept points (both ends always kept)."""
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = pts[b] - pts[a]
        n = float(np.hypot(*seg))
        rel = pts[a + 1 : b] - pts[a]
        dist = np.hypot(rel[:, 0], rel[:, 1]) if n == 0 else np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / n
        i = int(np.argmax(dist))
        if dist[i] > eps:
            k = a + 1 + i
            keep.add(k)
            stack += [(a, k), (k, b)]
    return sorted(keep)


def simplify_polygon(
    pts: list[tuple[float, float]], eps: float = OUTLINE_EPS_PX, max_points: int = OUTLINE_MAX_POINTS
) -> list[tuple[float, float]]:
    """Douglas-Peucker for a closed polygon; ``eps`` grows (x1.25) until at most ``max_points`` remain.

    The ring is split at vertex 0 and the vertex farthest from it, so both anchors survive. Concavities
    deeper than ``eps`` are kept (no convex hull). Polygons already within the cap and below 4 points pass through.
    """
    a = np.asarray(pts, dtype=float)
    if len(a) <= 3:
        return [(float(x), float(y)) for x, y in a]
    far = int(np.argmax(np.hypot(*(a - a[0]).T)))
    h1, h2 = a[: far + 1], np.vstack([a[far:], a[:1]])
    while True:
        k1, k2 = dp_open(h1, eps), dp_open(h2, eps)
        out = [(float(h1[i][0]), float(h1[i][1])) for i in k1] + [(float(h2[i][0]), float(h2[i][1])) for i in k2[1:-1]]
        if len(out) <= max_points:
            return out
        eps *= 1.25


def item_outline(it: Item, gh: int, gw: int) -> list[list[float]] | None:
    """Normalised, simplified outline ``[[x, y], ...]`` of the item's component (4 decimals), or None."""
    if it.shape is None:
        return None
    mask, c0, r0 = it.shape
    poly = simplify_polygon([(x + c0, y + r0) for x, y in trace_outline(mask)])
    return [[round(x / gw, 4), round(y / gh, 4)] for x, y in poly]


def item_full(it: Item, gh: int, gw: int) -> tuple[list[float], list[list[float]] | None] | None:
    """v26.2.12: (bboxFull, outlineFull) of the item's whole connected component, the rows above the horizon included
    (the item itself is judged below it); None without a shape (ghost / coasting items)."""
    if it.full_ref is None:
        return None
    fl, fsl, fid = it.full_ref
    mask = fl[fsl] == fid
    r0, c0 = fsl[0].start, fsl[1].start
    bbox = [
        round(c0 / gw, 4),
        round(r0 / gh, 4),
        round((c0 + mask.shape[1]) / gw, 4),
        round((r0 + mask.shape[0]) / gh, 4),
    ]
    poly = simplify_polygon([(x + c0, y + r0) for x, y in trace_outline(mask)])
    return bbox, [[round(x / gw, 4), round(y / gh, 4)] for x, y in poly]
