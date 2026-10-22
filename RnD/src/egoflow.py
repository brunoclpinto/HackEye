"""Residual image flow: is the camera moving through the scene? (v26.1.11, review 4: stationary user)

Walking forward expands the picture and every bob and sway adds parallax, so two frames a fraction of a second apart
differ by more than a pure shift. Standing still (however much the body fidgets: a chest camera bobs at 1-2 Hz even
then, which the cadence detector reads as steps) leaves the scene rigid: a shift explains the two frames.

``residual_flow`` = median, over the textured pixels, of the dense (Farneback) flow magnitude after subtracting the
median flow (the global shift = pan / tilt / bob), in pixels of the 160x90 gray frame. On recording 4929 (review 4):
standing 308-346 s median 0.12 px (5-95 percent 0.05-0.47), walking 0-280 s and 360-470 s median 2.7 px (5-95
percent 0.9-4.7). NaN when the frame is too bland (sky, plain wall, glare): no evidence either way.

Needs OpenCV, so it lives next to the analysis (``lab/analysis.py``) and not in the pure collision module; the
collision logic only reads the per-frame series (``motion["resid"]``).
"""

from __future__ import annotations

import cv2
import numpy as np

LAG_FRAMES = 6          # compare with the frame 6 source frames (0.25 s at 24 fps) earlier
GRAD_MIN = 40.0         # Sobel magnitude (0-255 gray) of a textured pixel
MIN_TEXTURED = 300      # of 14400 pixels; fewer = no verdict


def residual_flow(prev: np.ndarray, cur: np.ndarray) -> float:
    """``prev``, ``cur``: uint8 gray frames (90 x 160). Returns the residual flow in px, or nan without texture."""
    gx = cv2.Sobel(prev, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(prev, cv2.CV_32F, 0, 1, ksize=3)
    tex = np.hypot(gx, gy) > GRAD_MIN
    if int(tex.sum()) < MIN_TEXTURED:
        return float("nan")
    flow = cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    u, v = flow[..., 0][tex], flow[..., 1][tex]
    return float(np.median(np.hypot(u - np.median(u), v - np.median(v))))


class ResidualFlowTrack:
    """Streaming wrapper: ``push(gray_u8)`` per source frame -> residual flow against the frame ``LAG_FRAMES`` earlier
    (nan for the first frames)."""

    def __init__(self, lag: int = LAG_FRAMES):
        self.lag = lag
        self._ring: list[np.ndarray] = []

    def push(self, gray_u8: np.ndarray) -> float:
        out = float("nan")
        if len(self._ring) >= self.lag:
            out = residual_flow(self._ring[-self.lag], gray_u8)
        self._ring.append(gray_u8)
        if len(self._ring) > self.lag:
            self._ring.pop(0)
        return out
