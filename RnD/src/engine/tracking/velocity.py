"""Track velocities: closing speed, sideways ground velocity, bearing-rate cross velocity."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = ["closing_mps", "cross_velocity", "depth_closing", "lateral_velocity"]


def closing_mps(
    history: list[tuple[float, float]],
    horizon: float,
    camera_height_m: float,
    gh: int,
    f: float,
    min_rows: float,
    min_span_s: float,
    min_points: int = 3,
) -> float | None:
    """-slope of distance over time, with every history row re-projected through the CURRENT horizon.

    A track stores contact rows, not distances: the per-frame horizon wobbles
    (up to +-0.03 near the vanishing point), and distances computed with a
    different horizon each frame would turn a parked car at a fixed row into
    something "approaching at 6 m/s". Rows close to the horizon (< ``min_rows``
    grid rows) are too coarse to differentiate: such points are left out, and the answer is None
    while the latest point is one of them or too few remain.
    """
    t = np.array([h[0] for h in history])
    y = np.array([h[1] for h in history])
    keep = (y - horizon) * gh >= min_rows  # older points nearer the horizon are simply left out
    t, y = t[keep], y[keep]
    if len(t) < min_points or t[-1] - t[0] < min_span_s or t[-1] != history[-1][0]:
        return None
    d = camera_height_m * f / ((y - horizon) * gh)
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    if denom <= 0:
        return None
    return -float((tc * (d - d.mean())).sum() / denom)


def depth_closing(
    history: list[tuple[float, float]], t_now: float, min_span_s: float, min_points: int = 3
) -> float | None:
    """-slope of the metric depth history; needs >= 3 points, >= ``min_span_s`` of history, latest point = now."""
    if len(history) < min_points or history[-1][0] != t_now or history[-1][0] - history[0][0] < min_span_s:
        return None
    t = np.array([h[0] for h in history])
    d = np.array([h[1] for h in history])
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    return None if denom <= 0 else -float((tc * (d - d.mean())).sum() / denom)


def lateral_velocity(hist: list[tuple[Any, ...]], min_span_s: float, min_points: int = 3) -> float | None:
    """Sideways ground velocity (m/s, + = right) of a track in the camera frame of its newest sample, from its
    (t, lateral m, distance m, heading deg) history; None without >= 3 points over >= ``min_span_s`` s or a heading.

    Our own turn moves everything sideways in the picture (a pole at 6 m turns by 1 m/s while we turn 10 deg/s), so
    every
    point is first re-expressed in the newest heading: ``lat - (heading_now - heading_then) * distance`` (heading + = a
    right turn, which shifts the scene left). Forward walking does not change a static object's lateral position, so
    for a static item the result is ~0 plus noise (see ``_sideways_mps``: 0.5 m/s median, 1.4-2.4 at p90 on 4929) and
    for a mover it is its own sideways speed (v26.1.11). The correction is first order: the old samples are rotated
    but not shifted by our own forward step, which leaves ~1.4 m/s x sin(turn) over a 2 s window."""
    if len(hist) < min_points or hist[-1][0] - hist[0][0] < min_span_s or any(h[3] is None for h in hist):
        return None
    t = np.array([h[0] for h in hist])
    th_now = hist[-1][3]
    lat = np.array([h[1] - math.radians(th_now - h[3]) * h[2] for h in hist])
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    return None if denom <= 0 else float((tc * (lat - lat.mean())).sum() / denom)


def cross_velocity(hist: list[tuple[Any, ...]], speed: float | None, window_s: float) -> float | None:
    """Velocity across the line of sight (m/s, + = right) from the bearing rate of the track (v26.1.12, review 5).

    ``hist`` = (t, lateral m, distance m, heading deg, bearing deg of the bbox centre). The heading (the camera's
    yaw, from the
    motion series) is added back to the bearings, so our own turn cancels. A STATIC point at bearing theta and range
    R seen
    by someone walking at ``speed`` drifts outwards at ``speed * sin(theta) / R`` rad/s; what is left over after
    ``R * rate - speed * sin(theta)`` is the item's own sideways speed. Needs >= 4 points over >= 0.7 of ``window_s``
    and a
    heading; None otherwise. Unlike the lateral-offset derivative this never differentiates the noisy distance, but
    it is
    still weak (numbers: see DECISIONS v26.1.12), so it is used only as a veto for "standing"
    (``standingMaxCrossMps``)."""
    pts = [h for h in hist if h[0] >= hist[-1][0] - window_s - 1e-9] if hist else []
    if speed is None or len(pts) < 4 or pts[-1][0] - pts[0][0] < 0.7 * window_s or any(h[3] is None for h in pts):
        return None
    t = np.array([h[0] for h in pts])
    th = np.radians(np.array([h[4] for h in pts]) + np.array([h[3] for h in pts]))
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    if denom <= 0:
        return None
    rate = float((tc * (th - th.mean())).sum() / denom)  # rad/s
    # range and bearing at the middle of the window, where the fitted rate belongs (distance_m is the forward distance)
    rng = float(np.mean([math.hypot(h[2], h[1]) for h in pts]))
    return rng * rate - speed * math.sin(math.radians(float(np.mean([h[4] for h in pts]))))
