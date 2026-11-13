"""Dead-reckoned pose (x, y, heading) with a latched walking speed; owns the pose part of the world memory's advance."""

from __future__ import annotations

import math
from typing import Protocol

__all__ = ["DeadReckoner", "PoseLike"]


class PoseLike(Protocol):
    """Read-only view of a dead-reckoned pose."""

    @property
    def x(self) -> float: ...
    @property
    def y(self) -> float: ...
    @property
    def theta(self) -> float | None: ...
    @property
    def speed(self) -> float | None: ...
    @property
    def speed_t(self) -> float: ...
    @property
    def hold_s(self) -> float: ...


class DeadReckoner:
    def __init__(self, hold_s: float = 5.0) -> None:
        self.hold_s = hold_s
        self.x = 0.0
        self.y = 0.0
        self.theta: float | None = None
        self.speed: float | None = None
        self.speed_t = -math.inf

    def advance(
        self,
        t: float,
        dt: float,
        speed: float | None,
        heading_deg: float | None,
        pose: tuple[float, float, float] | None = None,
    ) -> None:
        """``pose`` (v26.2.11, "one pose"): the online map's corrected (x, y, heading) of this frame; it replaces the
        dead reckoning (the map's own PoseTracker integrates exactly this, plus the alignment found against the
        map)."""
        if heading_deg is None:
            self.theta = None
            return
        if speed is not None:
            self.speed, self.speed_t = speed, t
        if pose is not None:
            self.x, self.y, self.theta = float(pose[0]), float(pose[1]), float(pose[2])
        else:
            v = self.speed if (self.speed is not None and t - self.speed_t <= self.hold_s + 1e-9) else 0.0
            mid = heading_deg if self.theta is None else 0.5 * (self.theta + heading_deg)
            self.x += v * dt * math.sin(math.radians(mid))
            self.y += v * dt * math.cos(math.radians(mid))
            self.theta = heading_deg
