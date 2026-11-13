"""Coast: a mover that left the image keeps its last world velocity for a bounded time (v26.2.2)."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import numpy as np

from engine.core.clock import clock_from_bearing, clock_quarter, clock_text, pan_from_bearing
from engine.core.geom import steps_to

if TYPE_CHECKING:
    from collections.abc import Callable

    from engine.core.pose import PoseLike
    from engine.core.types import Item, Track

__all__ = ["Coast"]


class Coast:
    """A mover (person, rider, animal, vehicle) that disappears (out of frame, occluded, a segmentation dropout)
    keeps its last world
    velocity for a bounded time: its position is predicted linearly in world coordinates (dead-reckoned pose) and it
    stays an item
    of the collision logic (collision course, beeps, proximity) but is never spoken (``speak`` False). It stops when
    the object is matched
    again (the same track, or a new item of its class near the prediction), when it is passed, out of range or the
    time is up.

    The velocity is the least-squares line through the last ``histSeconds`` of its measured world positions (at least
    ``minPoints`` over
    ``minSpanSeconds``); a mover without such a measurement is not coasted."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.on = bool(cfg.get("enabled", False))
        self.seconds = float(cfg.get("seconds", 2.0))
        self.vehicle_seconds = float(cfg.get("vehicleSeconds", self.seconds))
        self.hist_s = float(cfg.get("histSeconds", 1.0))
        self.min_points = int(cfg.get("minPoints", 3))
        self.min_span = float(cfg.get("minSpanSeconds", 0.5))
        self.max_speed = float(cfg.get("maxSpeedMps", 15.0))
        self.max_range = float(cfg.get("maxRangeM", 30.0))
        self.rematch = float(cfg.get("rematchRadiusM", 2.0))
        self.hist: dict[int, list[tuple[float, float, float]]] = {}
        self.last: dict[int, tuple[Item, float]] = {}  # track -> (last measured item, its time)
        self.active: dict[int, dict[str, Any]] = {}  # track -> the running coasting episode
        self.episodes: list[dict[str, Any]] = []

    def observe(self, it: Item, t: float, world: PoseLike) -> None:
        if not self.on or it.group != "moving" or it.coasting or it.clipped or world.theta is None:
            return
        th = math.radians(world.theta)
        s_, c_ = math.sin(th), math.cos(th)
        h = self.hist.setdefault(it.track_id, [])
        h.append(
            (t, world.x + s_ * it.distance_m + c_ * it.lateral_m, world.y + c_ * it.distance_m - s_ * it.lateral_m)
        )
        self.hist[it.track_id] = [p for p in h if p[0] >= t - self.hist_s - 1e-9]
        self.last[it.track_id] = (it, t)

    def _velocity(self, tid: int) -> tuple[float, float] | None:
        h = self.hist.get(tid, [])
        if len(h) < self.min_points or h[-1][0] - h[0][0] < self.min_span - 1e-9:
            return None
        a = np.asarray(h)
        tt = a[:, 0] - a[:, 0].mean()
        den = float((tt * tt).sum())
        if den <= 1e-9:
            return None
        vx, vy = (
            float((tt * (a[:, 1] - a[:, 1].mean())).sum() / den),
            float((tt * (a[:, 2] - a[:, 2].mean())).sum() / den),
        )
        if math.hypot(vx, vy) > self.max_speed:
            return None
        return vx, vy

    def _end(self, tid: int, t: float, why: str) -> None:
        ep = self.active.pop(tid, None)
        if ep is not None:
            ep["t1"], ep["end"] = round(t, 2), why
            self.episodes.append(ep)

    def items(
        self,
        t: float,
        seen: dict[int, Item],
        world: PoseLike,
        tracks: dict[int, Track],
        step_len: float,
        blocked: Callable[[float, float], bool] | None = None,
        ext: Callable[[int], dict[str, Any] | None] | None = None,
    ) -> list[Item]:
        """The coasting items of this frame (``seen``: the real items by track id). ``ext`` (v26.2.11, source.mode
        "map"): image track id ->
        its trusted world track {x, y, vx, vy} (predicted to ``t``) or None; a coasting mover follows that instead of
        its own line fit."""
        out: list[Item] = []
        if not self.on or world.theta is None:
            return out
        th = math.radians(world.theta)
        s_, c_ = math.sin(th), math.cos(th)
        for tid in list(self.last):
            it0, t_last = self.last[tid]
            if tid in seen:
                self._end(tid, t, "rematch")
                continue
            if tid not in tracks:
                self._end(tid, t, "lost")
                self.last.pop(tid, None)
                self.hist.pop(tid, None)
                continue
            e = ext(tid) if ext is not None else None
            v = (e["vx"], e["vy"]) if e is not None else self._velocity(tid)
            horizon_s = self.vehicle_seconds if it0.class_name == "vehicle" else self.seconds
            if v is None or t - t_last > horizon_s + 1e-9 or t - t_last <= 0:
                if t - t_last > horizon_s + 1e-9:
                    self._end(tid, t, "expired")
                    self.last.pop(tid, None)
                    self.hist.pop(tid, None)
                continue
            if e is not None:
                wx, wy = e["x"], e["y"]
            else:
                _, wx0, wy0 = self.hist[tid][-1]
                wx, wy = wx0 + v[0] * (t - self.hist[tid][-1][0]), wy0 + v[1] * (t - self.hist[tid][-1][0])
            dx, dy = wx - world.x, wy - world.y
            fwd, right = dx * s_ + dy * c_, dx * c_ - dy * s_
            if fwd <= 0.0:
                self._end(tid, t, "passed")
                self.last.pop(tid, None)
                self.hist.pop(tid, None)
                continue
            rng = math.hypot(fwd, right)
            if blocked is not None and blocked(fwd, right):
                self._end(tid, t, "solid")
                self.last.pop(tid, None)
                self.hist.pop(tid, None)
                continue
            if rng > self.max_range:
                self._end(tid, t, "range")
                self.last.pop(tid, None)
                self.hist.pop(tid, None)
                continue
            if any(
                o.class_name == it0.class_name
                and not o.coasting
                and math.hypot(o.distance_m - fwd, o.lateral_m - right) <= self.rematch + 0.1 * rng
                for o in seen.values()
            ):
                self._end(tid, t, "rematch")  # the same object came back under another track
                self.last.pop(tid, None)
                self.hist.pop(tid, None)
                continue
            ev = (world.speed or 0.0) if world.speed is not None and t - world.speed_t <= world.hold_s + 1e-9 else 0.0
            vrel = (v[0] - ev * s_, v[1] - ev * c_)  # relative to us, world axes
            closing = -((dx * vrel[0] + dy * vrel[1]) / max(rng, 1e-6))
            bearing = math.degrees(math.atan2(right, fwd))
            g = replace(
                it0,
                coasting=True,
                shape=None,
                full_ref=None,
                clipped=True,
                speak=False,
                distance_m=fwd,
                lateral_m=right,
                bearing=bearing,
                clock=clock_from_bearing(bearing),
                clock_q=clock_quarter(bearing),
                clock_text=clock_text(clock_quarter(bearing)),
                pan=pan_from_bearing(bearing),
                closing=closing,
                closing_raw=closing,
                map_cells=0,
                map_world=None,
                image_dl=None,
                srcsel="track" if e is not None else it0.srcsel,
            )
            if tid not in self.active:
                self.active[tid] = {
                    "track": tid,
                    "class": it0.class_name,
                    "t0": round(t, 2),
                    "steps0": round(steps_to(fwd, step_len), 1),
                    "speedMps": round(math.hypot(*v), 2),
                    "moving": it0.moving,
                }
            tr = tracks[tid]
            tr.last_t, tr.last_distance, tr.last_lateral = t, fwd, right
            tr.present_run += 1
            g.present_run = tr.present_run
            out.append(g)
        return out
