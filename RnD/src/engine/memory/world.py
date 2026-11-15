"""World memory: object permanence by dead reckoning (moved from collision._WorldMemory)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from engine.core.pose import DeadReckoner

if TYPE_CHECKING:
    from engine.core.types import Item, Track

__all__ = ["WorldMemory"]


class WorldMemory:
    """Object permanence by dead reckoning (CONTRACTS.md 15 design 1).

    The user's ground position is integrated from the calibrated ego speed (cadence x step length, the
    witness speed as a fallback, the last speed held ``speedHoldSeconds``) along the camera heading of the
    motion track (x east / y north in an arbitrary frame; heading 0 = the initial direction, positive =
    right turn). Every announced item is stored as ``(label family, world x, y)``. A candidate of the same
    family within ``matchRadiusM`` + ``matchRangeFraction`` x its distance (per-family override in
    ``radiusOverrides``) of a stored object is that object. Objects are forgotten when behind the user
    (``ahead < behindM``) or farther than ``maxRangeM``.

    Inactive (``active`` False) without motion data: the policy then keeps the track / label rules of
    v26.1.6. Dead reckoning drifts (heading integration, step length), which is why the match radius grows
    with the item's distance and why a matched track keeps refreshing its object's position, so a drift
    only matters between two sightings separated by a gap.
    """

    def __init__(self, cfg: dict[str, Any], enabled: bool = True) -> None:
        self.enabled = enabled and bool(cfg.get("enabled", True))
        self.radius = float(cfg.get("matchRadiusM", 2.5))
        self.range_frac = float(cfg.get("matchRangeFraction", 0.10))
        self.max_range = float(cfg.get("maxRangeM", 30.0))
        self.behind = float(cfg.get("behindM", -1.0))
        self._pose = DeadReckoner(float(cfg.get("speedHoldSeconds", 5.0)))
        self.seen_hold_s = float(cfg.get("seenHoldSeconds", 1.0))
        self.takeover_s = float(cfg.get("moverTakeoverSeconds", 1.0))
        self.adopt_s = float(cfg.get("ownerAdoptSeconds", 3.0))
        self.overrides = dict(cfg.get("radiusOverrides", {}))
        self.entries: dict[int, dict[str, Any]] = {}
        self._next = 1

    # The pose lives in a composed DeadReckoner; tests assign these attributes (and build instances with __new__),
    # so the reckoner is created on first use.
    @property
    def _reckoner(self) -> DeadReckoner:
        r: DeadReckoner | None = self.__dict__.get("_pose")
        if r is None:
            r = self.__dict__["_pose"] = DeadReckoner()
        return r

    @property
    def x(self) -> float:
        return self._reckoner.x

    @x.setter
    def x(self, v: float) -> None:
        self._reckoner.x = v

    @property
    def y(self) -> float:
        return self._reckoner.y

    @y.setter
    def y(self, v: float) -> None:
        self._reckoner.y = v

    @property
    def theta(self) -> float | None:
        return self._reckoner.theta

    @theta.setter
    def theta(self, v: float | None) -> None:
        self._reckoner.theta = v

    @property
    def speed(self) -> float | None:
        return self._reckoner.speed

    @speed.setter
    def speed(self, v: float | None) -> None:
        self._reckoner.speed = v

    @property
    def speed_t(self) -> float:
        return self._reckoner.speed_t

    @speed_t.setter
    def speed_t(self, v: float) -> None:
        self._reckoner.speed_t = v

    @property
    def hold_s(self) -> float:
        return self._reckoner.hold_s

    @hold_s.setter
    def hold_s(self, v: float) -> None:
        self._reckoner.hold_s = v

    @property
    def active(self) -> bool:
        return self.enabled and self.theta is not None

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
        self._reckoner.advance(t, dt, speed, heading_deg, pose)
        if heading_deg is None:
            return
        assert self.theta is not None
        fx, fy = math.sin(math.radians(self.theta)), math.cos(math.radians(self.theta))
        for eid in list(self.entries):
            e = self.entries[eid]
            dx, dy = e["x"] - self.x, e["y"] - self.y
            if t - e["seen"] <= self.seen_hold_s:
                continue  # in view right now: the camera outranks the dead reckoning
            if dx * fx + dy * fy < self.behind or math.hypot(dx, dy) > self.max_range:
                del self.entries[eid]  # passed (behind us) or too far to matter

    def locate(self, it: Item) -> tuple[float, float]:
        th = math.radians(self.theta or 0.0)
        return (
            self.x + math.sin(th) * it.distance_m + math.cos(th) * it.lateral_m,
            self.y + math.cos(th) * it.distance_m - math.sin(th) * it.lateral_m,
        )

    def match(self, it: Item, t: float = 0.0) -> int | None:
        best, best_d = None, math.inf
        mover = it.people or it.moving is True
        fam = it.family or it.label
        reach = self.overrides.get(fam, self.radius) + self.range_frac * it.distance_m
        for eid, e in self.entries.items():
            if e["family"] != fam:
                continue
            if mover and t - e["fresh"] > self.takeover_s:
                continue  # a person walks on: only a hand-off within a second is the same person
            d = math.hypot(e["x"] - it.wx, e["y"] - it.wy)
            if d <= reach and d < best_d:
                best, best_d = eid, d
        return best

    def refresh(self, eid: int, it: Item, t: float) -> None:
        e = self.entries[eid]
        e["x"], e["y"], e["seen"], e["fresh"], e["owner"] = it.wx, it.wy, t, t, it.track_id

    def add(self, it: Item, t: float, named: bool = True) -> int:
        eid, self._next = self._next, self._next + 1
        self.entries[eid] = {
            "family": it.family or it.label,
            "x": it.wx,
            "y": it.wy,
            "named": named,
            "approach": False,
            "danger": False,
            "seen": t,
            "fresh": t,
            "owner": it.track_id,
        }
        return eid

    def link(self, items: list[Item], tracks: dict[int, Track], t: float) -> None:
        """Locate every item and connect it to a remembered object (via its track, else by position)."""
        for it in items:
            it.mem_id = None
            if not self.active:
                continue
            it.wx, it.wy = self.locate(it)
            tr = tracks[it.track_id]
            if tr.mem_id is None or tr.mem_id not in self.entries:
                tr.mem_id = self.match(it, t)
                tr.linked_t = t
            if tr.mem_id is not None:
                it.mem_id = tr.mem_id
                it.mem_named = self.entries[tr.mem_id]["named"]
                it.mem_approach = self.entries[tr.mem_id]["approach"]
                it.mem_danger = self.entries[tr.mem_id]["danger"]
                e = self.entries[tr.mem_id]
                if e["owner"] != it.track_id and t - tr.linked_t >= self.adopt_s:
                    # a track that has shown it for seconds is as good an owner as the first one
                    e["owner"] = it.track_id
                if e["owner"] == it.track_id:
                    # its own track still sees it: in view, however the dead reckoning drifts
                    e["seen"] = t
                # a standing object stays where it was first put (a refresh would let a long curb or wall drag its
                # entry along as we walk, so that it is never "passed"); a mover is followed by whichever track
                # currently shows it, so that a fragmented person is still the same person
                if (it.people or it.moving is True) and (
                    e["owner"] == it.track_id or t - e["fresh"] <= self.takeover_s
                ):
                    self.refresh(tr.mem_id, it, t)

    def mark_said(self, mem_id: int, steps: float, t: float) -> None:
        """Record that the object was spoken at ``steps`` away at time ``t`` (the ``said`` entry the speech reads)."""
        self.entries[mem_id]["said"] = (steps, t)

    def said_at(self, mem_id: int) -> tuple[float, float] | None:
        return self.entries[mem_id].get("said")
