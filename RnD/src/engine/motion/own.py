"""The own ground velocity of a mover, fitted from its own positions on the dead-reckoned world plane."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from engine.core.types import Item

__all__ = ["OwnMotion"]


class OwnMotion:
    """v26.2.14 (``motion``, review 11, 59.16 / 69.34 / 70.84 / 233.5 s): the own ground velocity of a mover (person,
    rider, vehicle, animal) from its OWN positions.

    Every frame the item's position is put on the dead-reckoned world plane (our pose integrated from the ego speed
    and heading, as ``WorldMemory``
    does); the last ``windowS`` s of one mover (a track; a new track that appears where a lost one was a moment ago
    continues its history: fragments of
    one person) are fitted with a line per axis (Theil-Sen: the median of the pairwise slopes, outliers do not
    count), the sigma of the slope from the
    scatter about the line. The velocity is then turned into our frame (forward, right). ``None`` until ``minPoints``
    frames spanning ``minSpanS`` s."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.on = bool(cfg.get("enabled", False))
        self.cfg = cfg
        self.win = float(cfg.get("windowS", 1.2))
        self.min_pts = int(cfg.get("minPoints", 4))
        self.min_span = float(cfg.get("minSpanS", 0.6))
        self.link_m = float(cfg.get("linkM", 1.5))
        self.link_s = float(cfg.get("linkS", 0.7))
        self.floor = float(cfg.get("scatterFloorM", 0.12))
        self.hist: dict[int, list[tuple[float, float, float]]] = {}
        self.last: dict[int, float] = {}
        self.x = self.y = 0.0
        self.theta: float | None = None
        self.known = False
        self.cache: dict[int, tuple[float, float, float] | None] = {}

    def advance(self, t: float, dt: float, speed: float | None, heading: float | None) -> None:
        """Our pose of this frame; ``known`` False when the speed or the heading is not known (nothing is observed
        then)."""
        self.cache.clear()
        if heading is None:
            self.theta, self.known = None, False
            return
        if speed is not None:
            mid = heading if self.theta is None else 0.5 * (self.theta + heading)
            self.x += speed * dt * math.sin(math.radians(mid))
            self.y += speed * dt * math.cos(math.radians(mid))
        self.theta = heading
        self.known = speed is not None

    def _world(self, it: Item) -> tuple[float, float]:
        th = math.radians(self.theta or 0.0)
        return (
            self.x + math.sin(th) * it.distance_m + math.cos(th) * it.lateral_m,
            self.y + math.cos(th) * it.distance_m - math.sin(th) * it.lateral_m,
        )

    def observe(self, it: Item, t: float) -> None:
        if not self.known or (it.clipped and not it.from_depth) or it.jumped:
            return
        tid = it.track_id
        wx, wy = self._world(it)
        h = self.hist.get(tid)
        # a new track: the fragment of a mover lost a moment ago continues its history
        if h is None:
            best, best_d = None, self.link_m
            for oid, oh in self.hist.items():
                if oid != tid and t - self.last.get(oid, -math.inf) <= self.link_s and oh:
                    d = math.hypot(oh[-1][1] - wx, oh[-1][2] - wy)
                    if d <= best_d:
                        best, best_d = oid, d
            h = list(self.hist[best]) if best is not None else []
        h.append((t, wx, wy))
        self.hist[tid] = [p for p in h if p[0] >= t - self.win - 1e-9]
        self.last[tid] = t
        if len(self.hist) > 300:
            for oid in [o for o, lt in self.last.items() if t - lt > 5.0]:
                self.hist.pop(oid, None)
                self.last.pop(oid, None)

    @staticmethod
    def _slope(ts: npt.NDArray[np.float64], xs: npt.NDArray[np.float64]) -> float | None:
        i, j = np.triu_indices(len(ts), 1)
        ok = (ts[j] - ts[i]) >= 0.25
        return float(np.median((xs[j][ok] - xs[i][ok]) / (ts[j][ok] - ts[i][ok]))) if ok.any() else None

    def estimate(self, tid: int, t: float) -> tuple[float, float, float] | None:
        """(forward m/s, right m/s, sigma m/s) in our frame now, or None."""
        h = self.hist.get(tid)
        if (
            not h
            or self.theta is None
            or h[-1][0] != t
            or len(h) < self.min_pts
            or h[-1][0] - h[0][0] < self.min_span - 1e-9
        ):
            return None
        if tid in self.cache:
            return self.cache[tid]
        ts = np.array([p[0] for p in h])
        sxx = float(((ts - ts.mean()) ** 2).sum())
        v, sg = [], 0.0
        for k in (1, 2):
            xs = np.array([p[k] for p in h])
            s_ = self._slope(ts, xs)
            if s_ is None or sxx <= 0:
                self.cache[tid] = None
                return None
            r = xs - (s_ * ts + float(np.median(xs - s_ * ts)))
            scale = max(1.4826 * float(np.median(np.abs(r - np.median(r)))), self.floor)
            v.append(s_)
            sg = max(sg, scale / math.sqrt(sxx))
        th = math.radians(self.theta)
        out = (v[0] * math.sin(th) + v[1] * math.cos(th), v[0] * math.cos(th) - v[1] * math.sin(th), sg)
        self.cache[tid] = out
        return out

    def classify(self, it: Item, t: float, u: float | None, words: bool = True) -> None:
        """Set the item's own velocity and, when it is usable, the motion words (``moving`` / ``approaching`` /
        ``receding``), the side it comes from and
        the near-pass flag. ``u``: our forward speed (None = unknown). Too few frames leave the closing-rate states
        as they were; a NOISY estimate
        (sigma > ``sigmaMaxMps``) leaves them for a person but takes the motion words from a rider / vehicle (their
        distances flicker: the review-11
        parked car read 4 m/s towards us)."""
        c = self.cfg
        est = self.estimate(it.track_id, t)
        if est is None:
            return
        vf, vr, sg = est
        it.own = (round(vf, 3), round(vr, 3), round(sg, 3))
        vehicle = it.class_name == "vehicle"
        if sg > float(c.get("sigmaMaxMps", 0.5)):
            if it.fast and words:
                it.moving, it.approaching, it.receding, it.own_ok = None, False, False, True
            return
        it.own_ok = True
        if u is not None:
            it.own_closing = u - vf
        # our own speed is not settled yet (the start, a hard pan): the velocity is kept, the words are not changed
        if not words:
            return
        mins = c.get("minSpeedMps") or {}
        vmin = float(mins.get("vehicle" if vehicle else "person", 0.8 if vehicle else 0.4))
        speed = math.hypot(vf, vr)
        rng = max(math.hypot(it.distance_m, it.lateral_m), 1e-6)
        toward = -(it.distance_m * vf + it.lateral_m * vr) / rng
        if speed >= vmin and speed >= float(c.get("sigmaK", 1.0)) * sg:
            # a rider / vehicle: the depth distances of a parked car read 2-4 m/s towards us (review 11: 36 / 44 / 51
            # / 67 s), so its own motion can take
            # the motion words away but never give them; it only confirms the closing-rate state
            # (``vehicleApproachingMps``)
            it.moving = True if not it.fast else (True if it.moving is True else it.moving)
            it.approaching = toward >= 0.7 * vmin and (not it.fast or it.approaching)
            it.receding = toward <= -0.7 * vmin and (not it.fast or it.receding)
            if abs(vr) >= float(c.get("sideMps", 0.5)) and vr * it.lateral_m < 0.0:
                it.from_side = "right" if it.lateral_m > 0 else "left"
            if it.approaching and u is not None and (u - vf) >= float(c.get("nearPassMinClosingMps", 0.3)):
                t_pass = it.distance_m / (u - vf)
                it.near_pass = t_pass <= float(c.get("nearPassS", 4.0)) and abs(it.lateral_m + vr * t_pass) <= float(
                    c.get("nearPassM", 1.3)
                )
        else:
            it.approaching = it.receding = False
            if vehicle:
                it.moving = False  # a parked vehicle
            elif speed < float(c.get("standingMps", 0.3)):
                # standing (between standingMps and the minimum speed the closing-rate state stays)
                it.moving = False
