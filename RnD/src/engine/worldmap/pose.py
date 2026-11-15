"""Worldmap pose: the user's dead-reckoned pose frame by frame, and its integration over a whole run."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from engine.core.pose import DeadReckoner

__all__ = ["PoseTracker", "integrate_pose"]


class PoseTracker:
    """The user's pose, frame by frame: exactly what the collision pass's world memory integrates (speed x dt along the
    mean heading; stationary = 0). The offline ``build`` and the collision pass feed it the same (rounded) ego
    values."""

    def __init__(self, coll_cfg: dict[str, Any]) -> None:
        self.wm = DeadReckoner(float(coll_cfg.get("memory", {}).get("speedHoldSeconds", 5.0)))
        self.prev_t: float | None = None
        self.last_heading = 0.0

    def advance(self, t: float, ego: dict[str, Any]) -> tuple[float, float, float]:
        dt = 0.0 if self.prev_t is None else float(t - self.prev_t)
        self.prev_t = float(t)
        h = ego.get("headingDeg")
        h = self.last_heading if h is None else float(h)
        self.last_heading = h
        speed = 0.0 if ego.get("stationary") else ego.get("speedMps")
        self.wm.advance(float(t), dt, speed, h)
        return (self.wm.x, self.wm.y, h)


def integrate_pose(
    times: npt.NDArray[np.float64], egos: list[dict[str, Any]], coll_cfg: dict[str, Any]
) -> npt.NDArray[np.float64]:
    """(N, 3) x east, y north (m), heading deg (0 = initial direction, + = right turn) over a whole run."""
    pt = PoseTracker(coll_cfg)
    out = np.zeros((len(times), 3))
    for i, (t, e) in enumerate(zip(times, egos)):  # noqa: B905
        out[i] = pt.advance(float(t), e)
    return out
