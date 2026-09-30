"""Bus detection.

Two things live here:

1. `parse_detections` / `detection_to_top_left` — a faithful port of
   YOLOModel.swift's raw-tensor decode (handles normalized/pixel coords,
   cx/cy/w/h vs x1y1x2y2, float16/32/64). This is NOT used on the hot path
   below — it's kept for the future parity check described in the plan
   ("dump the raw output tensor from the Apple CLI, feed it to the Python
   post-processing"), and for inspecting a raw ONNX/CoreML export directly.

2. `BusDetector` — what the pipeline actually runs today. It uses
   Ultralytics' own `.predict()`, which does decode + NMS internally. We do
   NOT know that the CoreML export's raw output format (whatever coremltools
   step produced Apple/Models/YOLO/yolo26sINT8512x896.mlpackage) matches the
   .pt checkpoint's native head output — that's exactly the kind of
   assumption the plan calls out as unverified. Trusting Ultralytics' own
   decode is the pragmatic choice for getting real detections today.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import config
from geometry import Box, LetterboxMeta, expand_box


@dataclass
class YOLODetection:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    cls: int


@dataclass
class BusDetection:
    box_detector: Box
    box_original: Box
    score: float
    cls: int


@dataclass
class DetectorConfig:
    # detector_w/h are normally overridden per-run by the resolved input
    # spec (see profiles.py) — these defaults only apply if unset.
    detector_w: int = field(default_factory=lambda: config.DETECTOR["width"])
    detector_h: int = field(default_factory=lambda: config.DETECTOR["height"])
    bus_class: int = field(default_factory=lambda: config.DETECTOR["busClass"])
    confidence: float = field(default_factory=lambda: config.DETECTOR["confidence"])
    crop_margin: float = field(default_factory=lambda: config.DETECTOR["cropMargin"])


# --- Raw-tensor path (parity / inspection use only — see module docstring) ---

def parse_detections(arr: np.ndarray, input_w: float, input_h: float) -> list[YOLODetection]:
    """Port of YOLOModel.parseDetections. Expects a [1,N,6] / [N,6] / flat
    array of (x, y, w_or_x2, h_or_y2, score, cls) rows."""
    a = np.asarray(arr, dtype=np.float64)
    shape = a.shape

    if a.ndim == 3 and shape[2] == 6:
        rows = a[0]
    elif a.ndim == 2 and shape[1] == 6:
        rows = a
    else:
        flat = a.reshape(-1)
        n = flat.shape[0] // 6
        rows = flat[: n * 6].reshape(n, 6)

    out = []
    for x, y, w_or_x2, h_or_y2, score, cls_f in rows:
        x1, y1, x2, y2 = float(x), float(y), float(w_or_x2), float(h_or_y2)
        cls = int(round(float(cls_f)))
        score = float(score)

        max_coord = max(abs(x1), abs(y1), abs(x2), abs(y2))
        if max_coord <= 2.0:
            x1 *= input_w; x2 *= input_w
            y1 *= input_h; y2 *= input_h

        if x2 <= x1 or y2 <= y1:
            cx, cy, w, h = x1, y1, x2, y2
            x1 = cx - w / 2.0
            y1 = cy - h / 2.0
            x2 = cx + w / 2.0
            y2 = cy + h / 2.0

        out.append(YOLODetection(
            x1=min(x1, x2), x2=max(x1, x2),
            y1=min(y1, y2), y2=max(y1, y2),
            score=score, cls=cls,
        ))
    return out


def detection_to_top_left(d: YOLODetection, origin: str, input_h: float) -> YOLODetection:
    """origin is 'topLeft' or 'bottomLeft', matching YOLOModel.BoxOrigin."""
    if origin != "bottomLeft":
        return d
    return YOLODetection(x1=d.x1, y1=input_h - d.y2, x2=d.x2, y2=input_h - d.y1, score=d.score, cls=d.cls)


# --- Ultralytics path (what the pipeline actually runs) ---

class BusDetector:
    def __init__(self, model, config: DetectorConfig, device):
        self.model = model
        self.config = config
        self.device = device

    def detect(self, letterboxed_rgb: np.ndarray, meta: LetterboxMeta) -> list[BusDetection]:
        cfg = self.config
        results = self.model.predict(
            source=letterboxed_rgb,
            imgsz=(cfg.detector_h, cfg.detector_w),
            conf=cfg.confidence,
            classes=[cfg.bus_class],
            device=self.device,
            verbose=False,
        )
        r = results[0]
        detections: list[BusDetection] = []
        if r.boxes is None or len(r.boxes) == 0:
            return detections

        xyxy = r.boxes.xyxy.detach().cpu().numpy()
        scores = r.boxes.conf.detach().cpu().numpy()
        classes = r.boxes.cls.detach().cpu().numpy()

        order = np.argsort(-scores)
        for i in order:
            x1, y1, x2, y2 = (float(v) for v in xyxy[i])
            det_box = Box(x1, y1, x2, y2)
            orig_box = meta.dst_to_src(det_box)
            orig_box = meta.clamp_to_src(orig_box)
            orig_box = expand_box(orig_box, meta.src_w, meta.src_h, cfg.crop_margin)
            detections.append(BusDetection(
                box_detector=det_box, box_original=orig_box,
                score=float(scores[i]), cls=int(classes[i]),
            ))
        return detections
