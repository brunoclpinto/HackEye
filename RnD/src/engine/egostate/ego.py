"""Ego state: the smoothed walking speed and the sustained path-change (heading) detector."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = ["Ego"]


@dataclass
class Ego:
    speed: float | None = None
    speed_t: float = -math.inf
    cadence: float | None = None
    heading: float | None = None
    ref_heading: float | None = None
    exceed_since: float | None = None

    def update_speed(self, closings: list[float], t: float, cfg: dict[str, Any]) -> None:
        if len(closings) >= cfg["speedMinTracks"]:
            v = float(np.median(closings))
            self.speed = v if self.speed is None else (1 - cfg["speedEma"]) * self.speed + cfg["speedEma"] * v
            self.speed_t = t
        elif self.speed is not None and t - self.speed_t > 5.0:
            self.speed = None  # stale: do not judge parked-vs-moving on it

    def update_heading(self, heading: float | None, t: float, cfg: dict[str, Any], dt: float) -> bool:
        """True when the heading has stayed more than headingDeg off the slow reference for sustainSeconds."""
        self.heading = heading
        if heading is None:
            return False
        if self.ref_heading is None:
            self.ref_heading = heading
        self.ref_heading += (heading - self.ref_heading) * min(1.0, dt / cfg["referenceTauSeconds"])
        if abs(heading - self.ref_heading) <= cfg["headingDeg"]:
            self.exceed_since = None
            return False
        if self.exceed_since is None:
            self.exceed_since = t
        if t - self.exceed_since >= cfg["sustainSeconds"]:
            self.ref_heading, self.exceed_since = heading, None
            return True
        return False
