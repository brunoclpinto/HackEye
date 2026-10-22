"""Port of Apple/HackEye-cli/CLIProcessor.swift — orchestrates detect ->
track -> segment -> debug-dump -> JSON per frame, over an image, a folder of
images, or a video.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

import debug_output
from detect import BusDetector, DetectorConfig
from letterbox import letterbox_with_meta
from models import SegmentationModel
from profiles import InputSpec, resolve_seg_min_pixel_count
from segmentation import extract_objects, grid_from_semantic_mask
from track import BusTracker

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


@dataclass
class PipelineConfig:
    input_path: str
    detector: DetectorConfig
    input_spec: InputSpec
    seg_min_pixel_count: int | None
    seg_min_pixel_fraction: float | None
    seg_alpha: float
    debug_destination: Path | None
    verbose: bool
    json_output: bool
    target_fps: float | None = None  # video only; None = every frame
    save_original_png: bool = True


class Pipeline:
    def __init__(self, config: PipelineConfig, detector: BusDetector, seg_model: SegmentationModel | None):
        self.config = config
        self.detector = detector
        self.tracker = BusTracker()
        self.seg_model = seg_model

    def run(self) -> None:
        path = Path(self.config.input_path)
        if not path.exists():
            print(f"Input not found: {path}", file=sys.stderr)
            sys.exit(1)

        if path.is_dir():
            files = sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
            if not files:
                print(f"No image files found in: {path}", file=sys.stderr)
                sys.exit(1)
            for f in files:
                result = self._process_image_file(f)
                if self.config.json_output:
                    _print_json(result)
        elif path.suffix.lower() in IMAGE_EXTENSIONS:
            result = self._process_image_file(path)
            if self.config.json_output:
                _print_json(result)
        else:
            result = self._process_video(path)
            if self.config.json_output:
                _print_json(result)

    def _process_image_file(self, path: Path) -> dict:
        bgr = cv2.imread(str(path))
        if bgr is None:
            print(f"Cannot load image: {path}", file=sys.stderr)
            sys.exit(1)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        out_folder = self._resolve_out_folder(path.stem)
        frame = self._process_frame(rgb, index=0, file_path=str(path), out_folder=out_folder)
        return {"input": str(path), "frames": [frame]}

    def _process_video(self, path: Path) -> dict:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            print(f"No video track in: {path}", file=sys.stderr)
            sys.exit(1)
        fps = cap.get(cv2.CAP_PROP_FPS) or None

        # Sample at target_fps using grab() (decode-free) for skipped frames
        # and retrieve() (actual decode) only for frames we keep — this is
        # what makes striding actually cut runtime, not just disk usage.
        step = 1
        if self.config.target_fps and fps:
            step = max(1, round(fps / self.config.target_fps))
            effective_fps = fps / step
            print(
                f"[pipeline] sampling every {step} frames ({fps:.2f}fps source -> "
                f"~{effective_fps:.2f}fps analyzed)",
                file=sys.stderr,
            )

        out_folder = self._resolve_out_folder(path.stem)
        frames = []
        source_index = 0
        kept_index = 0
        while True:
            ok = cap.grab()
            if not ok:
                break
            if source_index % step == 0:
                ok, bgr = cap.retrieve()
                if not ok:
                    break
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                frames.append(self._process_frame(
                    rgb, index=kept_index, file_path=str(path), out_folder=out_folder, fps=fps
                ))
                kept_index += 1
            source_index += 1
        cap.release()

        print(f"Processed {kept_index} of {source_index} source frames", file=sys.stderr)
        return {"input": str(path), "frames": frames}

    def _resolve_out_folder(self, input_name: str) -> Path | None:
        if self.config.debug_destination is None:
            return None
        return debug_output.resolve_output_folder(self.config.debug_destination, input_name)

    def _process_frame(
        self, rgb: np.ndarray, index: int, file_path: str, out_folder: Path | None, fps: float | None = None
    ) -> dict:
        frame_start = time.perf_counter()
        dst_w, dst_h = self.config.input_spec.dst_w, self.config.input_spec.dst_h

        letterboxed, meta = letterbox_with_meta(rgb, dst_w, dst_h)

        s1_start = time.perf_counter()
        detections = self.detector.detect(letterboxed, meta)
        s1_ms = (time.perf_counter() - s1_start) * 1000

        s2_start = time.perf_counter()
        tracked = self.tracker.update(detections)
        s2_ms = (time.perf_counter() - s2_start) * 1000

        seg_grid = None
        seg_objects: list[dict] = []
        seg_ms = 0.0
        seg_json = None

        if self.seg_model is not None:
            seg_start = time.perf_counter()
            class_ids = self.seg_model.predict_class_grid(letterboxed, dst_w, dst_h)
            seg_grid = grid_from_semantic_mask(class_ids, meta)
            min_px = resolve_seg_min_pixel_count(
                seg_grid.grid_w, seg_grid.grid_h, self.config.input_spec,
                self.config.seg_min_pixel_count, self.config.seg_min_pixel_fraction,
            )
            seg_objects = extract_objects(seg_grid, meta, min_px)
            seg_ms = (time.perf_counter() - seg_start) * 1000
            seg_json = {
                "gridW": seg_grid.grid_w, "gridH": seg_grid.grid_h,
                "objectCount": len(seg_objects), "elapsedMs": seg_ms,
                "objects": seg_objects,
            }

        total_ms = (time.perf_counter() - frame_start) * 1000

        if out_folder is not None:
            debug_output.save_frame(
                folder=out_folder, frame_index=index, original_rgb=rgb, letterboxed_rgb=letterboxed, meta=meta,
                detections=detections, tracked=tracked, seg_grid=seg_grid, seg_objects=seg_objects,
                seg_alpha=self.config.seg_alpha, fps=fps,
                s1_ms=s1_ms, s2_ms=s2_ms, seg_ms=seg_ms, total_ms=total_ms,
                save_original=self.config.save_original_png,
            )

        result = {
            "filePath": file_path,
            "frameNumber": index,
            "BusDetection": {"detected": len(detections) > 0, "count": len(detections)},
            "BusTracking": {"detected": len(tracked) > 0, "count": len(tracked)},
            "SafetySegmentation": seg_json,
        }

        if self.config.verbose:
            parts = [f"[{file_path}] frame {index}", f"detection: {len(detections)} bus(es)",
                     f"tracking: {len(tracked)} tracked"]
            if seg_json is not None:
                parts.append(f"segmentation: {len(seg_objects)} objects")
            parts.append(f"{total_ms:.0f} ms")
            print(" | ".join(parts), file=sys.stderr)

        return result


def _print_json(value: dict) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))
