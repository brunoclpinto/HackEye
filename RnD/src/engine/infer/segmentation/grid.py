"""Segmentation grid: padding mask, safety levels, connected-component objects (port of SafetySegmentation.swift).

Semantics are kept identical to the Swift original: 4-connected components per class, a pixel is on the boundary if any
4-neighbor is outside the component or off-grid, and the polygon is the convex hull of boundary pixels mapped
grid -> detector-input -> original image space. Connected components use scipy.ndimage (native 4K grids are large);
the convex hull stays hand-rolled (Andrew's monotone chain).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from engine.infer.segmentation import mapping

if TYPE_CHECKING:
    from engine.infer.segmentation.letterbox import LetterboxMeta

_4_CONNECTIVITY = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])


@dataclass
class SegmentationGrid:
    grid_w: int
    grid_h: int
    class_ids: npt.NDArray[Any]  # (gridH, gridW) int
    safety_levels: npt.NDArray[Any]  # (gridH, gridW) int


def _mask_padding_and_finish(
    class_ids: npt.NDArray[Any], grid_w: int, grid_h: int, meta: LetterboxMeta
) -> SegmentationGrid:
    """Shared tail of both parse paths below: blank out the letterbox padding
    region (the model doesn't know it's padding, not scene) and attach safety
    levels.
    """
    input_w, input_h = meta.dst_w, meta.dst_h
    scale_x, scale_y = input_w / grid_w, input_h / grid_h

    valid_min_col = int(np.floor(meta.pad_x / scale_x))
    valid_max_col = int(np.ceil((input_w - meta.pad_x) / scale_x)) - 1
    valid_min_row = int(np.floor(meta.pad_y / scale_y))
    valid_max_row = int(np.ceil((input_h - meta.pad_y) / scale_y)) - 1

    rows = np.arange(grid_h)[:, None]
    cols = np.arange(grid_w)[None, :]
    valid = (rows >= valid_min_row) & (rows <= valid_max_row) & (cols >= valid_min_col) & (cols <= valid_max_col)
    class_ids = np.where(valid, class_ids, mapping.SKY_CLASS_ID).astype(np.int32)

    level_lut = np.zeros(mapping.NUM_CLASSES, dtype=np.int32)
    for cid, info in mapping.CLASSES.items():
        level_lut[cid] = info["safetyLevel"]
    safety_levels = level_lut[class_ids]

    return SegmentationGrid(grid_w=grid_w, grid_h=grid_h, class_ids=class_ids, safety_levels=safety_levels)


def parse_grid(raw: npt.NDArray[Any], meta: LetterboxMeta) -> SegmentationGrid:
    """raw: [1, numClasses, gridH, gridW] or [numClasses, gridH, gridW] logits.

    For the raw-tensor / parity-testing path only (see models.py). The
    pipeline's normal path is grid_from_semantic_mask below.
    """
    arr = np.asarray(raw)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.shape[0] != mapping.NUM_CLASSES:
        raise ValueError(
            f"Segmentation model produced {arr.shape[0]} classes, expected {mapping.NUM_CLASSES} "
            f"(per the selected safety mapping). This model may not be the semantic-segmentation "
            f"checkpoint expected here — see RnD/README.md model verification notes."
        )
    _, grid_h, grid_w = arr.shape
    class_ids = np.argmax(arr, axis=0)
    return _mask_padding_and_finish(class_ids, grid_w, grid_h, meta)


def grid_from_semantic_mask(class_ids: npt.NDArray[Any], meta: LetterboxMeta) -> SegmentationGrid:
    """class_ids: (H, W) array of already-argmaxed class ids, as returned by
    Ultralytics' Results.semantic_mask.data for a 'semantic' task model
    (confirmed as of ultralytics 8.4.167 — see RnD/src/models.py). Already at
    full detector-input resolution, not a downsampled grid, so grid_w/grid_h
    equal meta.dst_w/dst_h.
    """
    grid_h, grid_w = class_ids.shape
    return _mask_padding_and_finish(class_ids, grid_w, grid_h, meta)


def extract_objects(grid: SegmentationGrid, meta: LetterboxMeta, min_pixel_count: int) -> list[dict[str, Any]]:
    scale_x = meta.dst_w / grid.grid_w
    scale_y = meta.dst_h / grid.grid_h

    objects: list[dict[str, Any]] = []

    for cls_id in np.unique(grid.class_ids):
        info = mapping.CLASSES.get(int(cls_id))
        if info is None or info["safetyLevel"] == 0:  # ignored
            continue

        mask = grid.class_ids == cls_id
        labeled, n_components = ndimage.label(mask, structure=_4_CONNECTIVITY)
        if n_components == 0:
            continue

        for comp_id in range(1, n_components + 1):
            comp_mask = labeled == comp_id
            count = int(comp_mask.sum())
            if count < min_pixel_count:
                continue

            eroded = ndimage.binary_erosion(comp_mask, structure=_4_CONNECTIVITY, border_value=0)
            boundary = comp_mask & ~eroded
            ys, xs = np.nonzero(boundary)
            points = list(zip(xs.tolist(), ys.tolist()))  # noqa: B905

            hull = _convex_hull(points)
            polygon = []
            for x, y in hull:
                det_x = (x + 0.5) * scale_x
                det_y = (y + 0.5) * scale_y
                src_x = (det_x - meta.pad_x) / max(meta.scale, 1e-9)
                src_y = (det_y - meta.pad_y) / max(meta.scale, 1e-9)
                polygon.append(
                    {
                        "x": max(0, min(int(meta.src_w) - 1, int(round(src_x)))),  # noqa: RUF046
                        "y": max(0, min(int(meta.src_h) - 1, int(round(src_y)))),  # noqa: RUF046
                    }
                )

            objects.append(
                {
                    "classId": int(cls_id),
                    "className": info["name"],
                    "safetyLevel": info["safetyLevel"],
                    "safetyLevelName": mapping.SAFETY_LEVELS[info["safetyLevel"]]["label"],
                    "pixelCount": count,
                    "polygon": polygon,
                }
            )

    objects.sort(key=lambda o: -o["pixelCount"])
    return objects


def _convex_hull(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Andrew's monotone chain — direct port of SafetySegmentation.convexHull."""
    if len(points) <= 2:
        return points

    pts = sorted(set(points))

    def cross(o: tuple[int, int], a: tuple[int, int], b: tuple[int, int]) -> int:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    hull: list[tuple[int, int]] = []
    for p in pts:
        while len(hull) >= 2 and cross(hull[-2], hull[-1], p) <= 0:
            hull.pop()
        hull.append(p)

    lower = len(hull) + 1
    for p in reversed(pts):
        while len(hull) >= lower and cross(hull[-2], hull[-1], p) <= 0:
            hull.pop()
        hull.append(p)
    hull.pop()
    return hull
