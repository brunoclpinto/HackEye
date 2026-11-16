"""Sequential frame reader over a recording's chapters (v26.3.0 p5-04), with the ego-motion track (CONTRACTS 5)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

MOTION_W, MOTION_H = 160, 90


class _FrameReader:
    """Sequential reader over a recording's chapters, addressed by recording
    time. Seeks once to the first sampled frame, then decodes forward.

    With `motion_end` set it also builds the ego-motion track (CONTRACTS §5):
    every source frame in [first sampled frame, motion_end) is retrieve()d,
    reduced to 160x90 gray and phase-correlated against its predecessor. The
    track continues across chapter boundaries (the rest of a chapter is
    drained before the next one is opened, and decoding of the next starts at
    its frame 0), so no long-gap seek is used in that mode."""

    MAX_GRAB_GAP = 240  # frames; beyond this a seek is cheaper than decoding through (no-motion mode only)

    def __init__(self, rec: dict[str, Any], motion_end: float | None = None) -> None:
        self.rec = rec
        self.fps = rec["fps"]
        self.chapters = rec["chapters"]
        self.cap: cv2.VideoCapture | None = None
        self.ch = -1
        self.pos = 0
        self.last: tuple[int, int, NDArray[Any]] | None = None  # (chapter, frame, bgr)
        self.seek_seconds = 0.0
        self.motion_end = motion_end
        self.motion_seconds = 0.0  # time spent on gray/resize/phaseCorrelate
        self._m_t: list[float] = []
        self._m_dx: list[float] = []
        self._m_dy: list[float] = []
        self._m_resid: list[float] = []
        import egoflow

        self._m_flow = egoflow.ResidualFlowTrack()
        self._m_prev: NDArray[Any] | None = None
        self._m_win = cv2.createHanningWindow((MOTION_W, MOTION_H), cv2.CV_32F)

    def _locate(self, t: float) -> tuple[int, int]:
        """Recording time -> (chapter index, chapter-local frame index)."""
        for i, ch in enumerate(self.chapters):
            f = round((t - ch["start"]) * self.fps)
            if t < ch["start"] + ch["duration"] and f < ch["frames"]:
                return i, max(0, f)
        return len(self.chapters), 0

    def _motion(self, bgr: NDArray[Any], frame_t: float) -> None:
        if self.motion_end is None or frame_t >= self.motion_end:
            return
        t0 = time.perf_counter()
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        small_u8 = cv2.resize(gray, (MOTION_W, MOTION_H), interpolation=cv2.INTER_AREA)
        small = small_u8.astype(np.float32)
        dx = dy = 0.0
        if self._m_prev is not None:
            (sx, sy), _ = cv2.phaseCorrelate(self._m_prev, small, self._m_win)
            dx, dy = sx / MOTION_W, sy / MOTION_H
        self._m_prev = small
        self._m_t.append(frame_t)
        self._m_dx.append(dx)
        self._m_dy.append(dy)
        self._m_resid.append(self._m_flow.push(small_u8))
        self.motion_seconds += time.perf_counter() - t0

    def _step_skipped(self) -> bool:
        """Decode the frame at self.pos without returning it (motion only)."""
        ch = self.chapters[self.ch]
        frame_t = ch["start"] + self.pos / self.fps
        if self.motion_end is None or frame_t >= self.motion_end:
            return self.cap.grab()  # type: ignore[union-attr]
        if not self.cap.grab():  # type: ignore[union-attr]
            return False
        ok, bgr = self.cap.retrieve()  # type: ignore[union-attr]
        if not ok:
            return False
        self._motion(bgr, frame_t)
        return True

    def read(self, t: float) -> tuple[float, NDArray[Any]] | None:
        """Frame nearest to recording time t as (its exact time, BGR), or None at the end."""
        i, f = self._locate(t)
        if i >= len(self.chapters):
            return None
        ch = self.chapters[i]
        frame_t = ch["start"] + f / self.fps
        if self.last and self.last[:2] == (i, f):
            return frame_t, self.last[2]
        tracking = self.motion_end is not None
        if i != self.ch:
            if tracking and self.cap is not None:  # finish the old chapter's motion frames
                while self.pos < self.chapters[self.ch]["frames"] and self._step_skipped():
                    self.pos += 1
            self._seek(i, f, from_start=tracking and self.ch != -1)
        elif f < self.pos or (not tracking and f - self.pos > self.MAX_GRAB_GAP):
            self._seek(i, f)
        while self.pos < f:
            if not self._step_skipped():
                return None
            self.pos += 1
        ok, bgr = self.cap.read()  # type: ignore[union-attr]
        if not ok:
            return None
        self.pos += 1
        self._motion(bgr, frame_t)
        self.last = (i, f, bgr)
        return frame_t, bgr

    def _seek(self, i: int, f: int, from_start: bool = False) -> None:
        t0 = time.perf_counter()
        if i != self.ch:
            if self.cap is not None:
                self.cap.release()
            self.cap = cv2.VideoCapture(self.chapters[i]["file"])
            if not self.cap.isOpened():
                raise RuntimeError(f"Cannot open {self.chapters[i]['file']}")
            self.ch, self.pos = i, 0
        if f != self.pos and not from_start:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, f)  # type: ignore[union-attr]
            self.pos = f
        self.seek_seconds += time.perf_counter() - t0

    def finish_motion(self) -> None:
        """Process the remaining source frames up to motion_end (after the last sampled frame)."""
        if self.motion_end is None or self.cap is None:
            return
        while True:
            ch = self.chapters[self.ch]
            if self.pos >= ch["frames"]:
                if self.ch + 1 >= len(self.chapters):
                    return
                self._seek(self.ch + 1, 0)
                continue
            if ch["start"] + self.pos / self.fps >= self.motion_end or not self._step_skipped():
                return
            self.pos += 1

    def motion_track(self) -> dict[str, NDArray[Any]]:
        return {
            "t": np.array(self._m_t, np.float64),
            "dx": np.array(self._m_dx, np.float32),
            "dy": np.array(self._m_dy, np.float32),
            "resid": np.array(self._m_resid, np.float32),
        }

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
