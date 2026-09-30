"""Direct port of Apple/Models/Domain/BusTracker.swift.

Pure logic, zero imports in the Swift original — kept behaviourally identical
here on purpose, since IoU matching and approach-scoring are exactly the kind
of thing that quietly diverges between two implementations. This is the
first module the plan's Stage 2 migration order would move to Rust, and the
first thing to dual-run-diff if that ever happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from geometry import Box


@dataclass
class BusDetection:
    box_detector: Box
    box_original: Box
    score: float
    cls: int


@dataclass
class TrackedBus:
    id: int
    name: str
    last_box_detector: Box
    last_score: float
    approaching_score: float
    is_approaching: bool


@dataclass
class _Track:
    numeric_id: int
    name: str
    last_box_detector: Box
    last_score: float
    last_seen_frame: int
    age_frames: int
    area_history: list[float] = field(default_factory=list)
    approaching_score: float = 0.0
    is_approaching: bool = False


@dataclass
class TrackerConfig:
    iou_match_threshold: float = field(default_factory=lambda: config.TRACKER["iouMatchThreshold"])
    max_missed_frames: int = field(default_factory=lambda: config.TRACKER["maxMissedFrames"])
    approach_window: int = field(default_factory=lambda: config.TRACKER["approachWindow"])
    approach_min_frames: int = field(default_factory=lambda: config.TRACKER["approachMinFrames"])
    approach_ratio_threshold: float = field(default_factory=lambda: config.TRACKER["approachRatioThreshold"])


class BusTracker:
    def __init__(self, config: TrackerConfig | None = None):
        self.config = config or TrackerConfig()
        self._next_id = 1
        self._tracks: dict[int, _Track] = {}
        self._frame_index = 0

    def update(self, detections: list[BusDetection]) -> list[TrackedBus]:
        self._frame_index += 1
        matched_ids = self._match_and_update(detections)
        self._prune_stale()

        out = []
        for tid in sorted(set(matched_ids)):
            t = self._tracks.get(tid)
            if t is None:
                continue
            out.append(TrackedBus(
                id=t.numeric_id, name=t.name,
                last_box_detector=t.last_box_detector, last_score=t.last_score,
                approaching_score=t.approaching_score, is_approaching=t.is_approaching,
            ))
        return out

    def _match_and_update(self, detections: list[BusDetection]) -> list[int]:
        det_boxes = [d.box_detector for d in detections]

        pairs: list[tuple[float, int, int]] = []
        for tid, tr in self._tracks.items():
            for di, db in enumerate(det_boxes):
                v = _iou(tr.last_box_detector, db)
                if v >= self.config.iou_match_threshold:
                    pairs.append((v, tid, di))
        pairs.sort(key=lambda p: -p[0])

        used_tracks: set[int] = set()
        det_assigned = [False] * len(det_boxes)
        matched_ids: list[int] = []

        for v, tid, di in pairs:
            if tid in used_tracks or det_assigned[di]:
                continue
            used_tracks.add(tid)
            det_assigned[di] = True
            matched_ids.append(tid)
            self._update_track(tid, det_boxes[di], detections[di].score)

        for di, assigned in enumerate(det_assigned):
            if assigned:
                continue
            tid = self._next_id
            self._next_id += 1
            box = det_boxes[di]
            tr = _Track(
                numeric_id=tid, name=f"Bus{tid}",
                last_box_detector=box, last_score=detections[di].score,
                last_seen_frame=self._frame_index, age_frames=1,
                area_history=[box.area],
            )
            _compute_approach(tr, self.config)
            self._tracks[tid] = tr
            matched_ids.append(tid)

        return matched_ids

    def _update_track(self, tid: int, box: Box, score: float) -> None:
        tr = self._tracks.get(tid)
        if tr is None:
            return
        tr.last_box_detector = box
        tr.last_score = score
        tr.last_seen_frame = self._frame_index
        tr.age_frames += 1

        tr.area_history.append(box.area)
        if len(tr.area_history) > self.config.approach_window:
            excess = len(tr.area_history) - self.config.approach_window
            tr.area_history = tr.area_history[excess:]

        _compute_approach(tr, self.config)

    def _prune_stale(self) -> None:
        cutoff = self._frame_index - self.config.max_missed_frames
        self._tracks = {k: v for k, v in self._tracks.items() if v.last_seen_frame >= cutoff}


def _compute_approach(tr: _Track, config: TrackerConfig) -> None:
    h = tr.area_history
    if len(h) < config.approach_min_frames:
        tr.approaching_score = 0.0
        tr.is_approaching = False
        return

    first = max(h[0], 1e-6)
    last = max(h[-1], 0.0)
    ratio = (last / first) - 1.0
    tr.approaching_score = ratio

    increases = sum(1 for i in range(1, len(h)) if h[i] >= h[i - 1])
    mostly_increasing = increases >= max(1, (len(h) - 1) * 2 // 3)

    tr.is_approaching = (ratio >= config.approach_ratio_threshold) and mostly_increasing


def _iou(a: Box, b: Box) -> float:
    xa, ya = max(a.x1, b.x1), max(a.y1, b.y1)
    xb, yb = min(a.x2, b.x2), min(a.y2, b.y2)
    inter = max(0.0, xb - xa) * max(0.0, yb - ya)
    union = a.area + b.area - inter
    if union <= 0:
        return 0.0
    return inter / union
