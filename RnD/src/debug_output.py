"""Port of Apple/HackEye-cli/CLIDebugOutput.swift's folder layout, so
output is directly comparable side by side with the macOS CLI's debug dumps.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from geometry import LetterboxMeta
from overlay import render_safety_overlay
from segmentation import SegmentationGrid
from track import BusDetection, TrackedBus


def resolve_output_folder(base_path: Path, input_name: str) -> Path:
    """Finder-style uniqueness: "name", "name 2", "name 3", ..."""
    candidate = base_path / input_name
    if not candidate.exists():
        return candidate
    n = 2
    while (base_path / f"{input_name} {n}").exists():
        n += 1
    return base_path / f"{input_name} {n}"


def _save_png(rgb: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def _save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def save_frame(
    folder: Path,
    frame_index: int,
    original_rgb: np.ndarray,
    letterboxed_rgb: np.ndarray,
    meta: LetterboxMeta,
    detections: list[BusDetection],
    tracked: list[TrackedBus],
    seg_grid: SegmentationGrid | None,
    seg_objects: list[dict],
    seg_alpha: float,
    fps: float | None,
    s1_ms: float, s2_ms: float, seg_ms: float, total_ms: float,
    save_original: bool = True,
) -> None:
    frame_folder = folder / f"frame_{frame_index:04d}"
    frame_folder.mkdir(parents=True, exist_ok=True)

    if save_original:
        _save_png(original_rgb, frame_folder / "original.png")

    info = {
        "frameIndex": frame_index,
        "totalProcessingMs": total_ms,
        "width": original_rgb.shape[1],
        "height": original_rgb.shape[0],
    }
    if fps is not None:
        info["fps"] = fps
    _save_json(info, frame_folder / "info.json")

    # BusDetection/
    _save_png(letterboxed_rgb, frame_folder / "BusDetection" / "work.png")
    _save_json({
        "detected": len(detections) > 0,
        "count": len(detections),
        "elapsedMs": s1_ms,
        "detections": [
            {
                "score": d.score,
                "class": d.cls,
                "boxDetector": {"x1": d.box_detector.x1, "y1": d.box_detector.y1,
                                "x2": d.box_detector.x2, "y2": d.box_detector.y2},
                "boxOriginal": {"x1": d.box_original.x1, "y1": d.box_original.y1,
                                "x2": d.box_original.x2, "y2": d.box_original.y2},
            }
            for d in detections
        ],
    }, frame_folder / "BusDetection" / "result.json")

    # BusTracking/
    _save_json({
        "detected": len(tracked) > 0,
        "count": len(tracked),
        "elapsedMs": s2_ms,
        "buses": [
            {
                "id": t.id, "name": t.name,
                "isApproaching": t.is_approaching,
                "approachingScore": t.approaching_score,
                "score": t.last_score,
            }
            for t in tracked
        ],
    }, frame_folder / "BusTracking" / "result.json")

    # SafetySegmentation/
    if seg_grid is not None:
        overlay = render_safety_overlay(letterboxed_rgb, seg_grid, seg_alpha)
        _save_png(overlay, frame_folder / "SafetySegmentation" / "work.png")
        _save_json({
            "gridW": seg_grid.grid_w,
            "gridH": seg_grid.grid_h,
            "elapsedMs": seg_ms,
            "objectCount": len(seg_objects),
            "objects": seg_objects,
        }, frame_folder / "SafetySegmentation" / "result.json")
