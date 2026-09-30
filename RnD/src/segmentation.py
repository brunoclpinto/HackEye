"""Port of Apple/Models/Domain/SafetySegmentation.swift.

Semantics are kept identical to the Swift original: 4-connected components
per class, a pixel is on the boundary if any 4-neighbor is outside the
component or off-grid, and the polygon is the convex hull of boundary pixels
mapped grid -> detector-input -> original image space.

The *implementation* deliberately diverges from Swift's hand-rolled
union-find: this rig targets native 4K footage by default (see
RnD/src/profiles.py), where the segmentation grid can be ~18x larger than the
512x896 production grid, so connected components uses scipy.ndimage instead
of a pure-Python union-find loop. Convex hull stays hand-rolled (Andrew's
monotone chain, same as Swift) since hull inputs are small.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from common_paths import find_common_dir
from geometry import LetterboxMeta

_CONFIG_PATH = find_common_dir() / "config" / "safety_mapping.json"

_4_CONNECTIVITY = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])


def _load_mapping() -> tuple[dict[int, dict], dict[int, dict]]:
    with open(_CONFIG_PATH) as f:
        data = json.load(f)
    classes = {c["id"]: c for c in data["classes"]}
    levels = {int(k): v for k, v in data["safetyLevels"].items()}
    return classes, levels


CLASSES, SAFETY_LEVELS = _load_mapping()
NUM_CLASSES = len(CLASSES)
SKY_CLASS_ID = next(c["id"] for c in CLASSES.values() if c["name"] == "sky")


@dataclass
class SegmentationGrid:
    grid_w: int
    grid_h: int
    class_ids: np.ndarray  # (gridH, gridW) int
    safety_levels: np.ndarray  # (gridH, gridW) int


def parse_grid(raw: np.ndarray, meta: LetterboxMeta) -> SegmentationGrid:
    """raw: [1, numClasses, gridH, gridW] or [numClasses, gridH, gridW] logits."""
    arr = np.asarray(raw)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.shape[0] != NUM_CLASSES:
        raise ValueError(
            f"Segmentation model produced {arr.shape[0]} classes, expected {NUM_CLASSES} "
            f"(Cityscapes). This model may not be the semantic-segmentation checkpoint "
            f"expected here — see RnD/README.md model verification notes."
        )

    num_classes, grid_h, grid_w = arr.shape
    input_w, input_h = meta.dst_w, meta.dst_h
    scale_x, scale_y = input_w / grid_w, input_h / grid_h

    valid_min_col = int(np.floor(meta.pad_x / scale_x))
    valid_max_col = int(np.ceil((input_w - meta.pad_x) / scale_x)) - 1
    valid_min_row = int(np.floor(meta.pad_y / scale_y))
    valid_max_row = int(np.ceil((input_h - meta.pad_y) / scale_y)) - 1

    class_ids = np.argmax(arr, axis=0).astype(np.int32)

    rows = np.arange(grid_h)[:, None]
    cols = np.arange(grid_w)[None, :]
    valid = (
        (rows >= valid_min_row) & (rows <= valid_max_row)
        & (cols >= valid_min_col) & (cols <= valid_max_col)
    )
    class_ids = np.where(valid, class_ids, SKY_CLASS_ID)

    level_lut = np.zeros(NUM_CLASSES, dtype=np.int32)
    for cid, info in CLASSES.items():
        level_lut[cid] = info["safetyLevel"]
    safety_levels = level_lut[class_ids]

    return SegmentationGrid(grid_w=grid_w, grid_h=grid_h, class_ids=class_ids, safety_levels=safety_levels)


def extract_objects(grid: SegmentationGrid, meta: LetterboxMeta, min_pixel_count: int) -> list[dict]:
    scale_x = meta.dst_w / grid.grid_w
    scale_y = meta.dst_h / grid.grid_h

    objects: list[dict] = []

    for cls_id in np.unique(grid.class_ids):
        info = CLASSES.get(int(cls_id))
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
            points = list(zip(xs.tolist(), ys.tolist()))

            hull = _convex_hull(points)
            polygon = []
            for x, y in hull:
                det_x = (x + 0.5) * scale_x
                det_y = (y + 0.5) * scale_y
                src_x = (det_x - meta.pad_x) / max(meta.scale, 1e-9)
                src_y = (det_y - meta.pad_y) / max(meta.scale, 1e-9)
                polygon.append({
                    "x": max(0, min(int(meta.src_w) - 1, int(round(src_x)))),
                    "y": max(0, min(int(meta.src_h) - 1, int(round(src_y)))),
                })

            objects.append({
                "classId": int(cls_id),
                "className": info["name"],
                "safetyLevel": info["safetyLevel"],
                "safetyLevelName": SAFETY_LEVELS[info["safetyLevel"]]["label"],
                "pixelCount": count,
                "polygon": polygon,
            })

    objects.sort(key=lambda o: -o["pixelCount"])
    return objects


def _convex_hull(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Andrew's monotone chain — direct port of SafetySegmentation.convexHull."""
    if len(points) <= 2:
        return points

    pts = sorted(set(points))

    def cross(o, a, b):
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
