"""Inference wrapper: segmentation (letterbox, safety mapping, grid, Ultralytics model).

``model`` (torch / ultralytics at module level) is not imported here: import ``engine.infer.segmentation.model``.
"""

from __future__ import annotations

from engine.infer.segmentation.grid import (
    SegmentationGrid,
    extract_objects,
    grid_from_semantic_mask,
    parse_grid,
)
from engine.infer.segmentation.letterbox import LetterboxMeta, letterbox_params, letterbox_with_meta
from engine.infer.segmentation.mapping import CLASSES, SAFETY_LEVELS, find_mapping, select_mapping

__all__ = [
    "CLASSES",
    "SAFETY_LEVELS",
    "LetterboxMeta",
    "SegmentationGrid",
    "extract_objects",
    "find_mapping",
    "grid_from_semantic_mask",
    "letterbox_params",
    "letterbox_with_meta",
    "parse_grid",
    "select_mapping",
]
