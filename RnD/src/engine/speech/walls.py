"""Walls: the wall-following beep memory, the passing-close predicate and the known-wall phrase memory."""
# ruff: noqa: E501

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.core.types import Item

__all__ = ["WallFollow", "WallsMixin", "followed_wall", "passing_close"]


class WallsMixin:
    """The known-wall methods of ``SpeechPolicy`` (composed with ``TextMixin`` and ``ContextMixin``)."""

    known_on: bool
    known_classes: frozenset[str]
    known_walls: list[dict[str, Any]]
    known_s: float
    known_m: float
    known_rel_s: float
    known_steps: float
    known_quarters: int

    def note_wall(self, t: float, it: Item) -> None:
        """v26.2.13: remember where a wall-family phrase / beep episode was (relative place and world point) for ``_known_wall``."""
        if not self.known_on or it.class_name not in self.known_classes:
            return
        self.known_walls = [w for w in self.known_walls if t - w["t"] <= self.known_s]
        self.known_walls.append(
            {"t": t, "fam": it.family or it.label, "wx": it.wx, "wy": it.wy, "steps": it.steps, "q": it.clock_q}
        )

    def _known_wall(self, t: float, it: Item) -> bool:
        """v26.2.13 (``speech.knownWall``, review 10, 44.66 s: "still a building at same position as before, still known"): a wall phrase is not said
        again when a wall phrase / beep episode of the same family within the last ``windowS`` s was at the same place: the nearest world point
        within ``worldM`` m, or (within ``relativeS`` s) the same RELATIVE place (steps within ``steps``, clock within ``quarters``): a wall that is walked along keeps its
        nearest point at the same distance ahead while its world point slides on with us."""
        if not self.known_on or it.class_name not in self.known_classes:
            return False
        fam = it.family or it.label
        for w in self.known_walls:
            if w["fam"] != fam or t - w["t"] > self.known_s:
                continue
            if (
                math.hypot(it.wx - w["wx"], it.wy - w["wy"]) <= self.known_m
                or t - w.get("sup", -math.inf) <= 1.0
                or (
                    t - w["t"] <= self.known_rel_s
                    and abs(it.steps - w["steps"]) <= self.known_steps
                    and abs(it.clock_q - w["q"]) <= self.known_quarters
                )
            ):
                w["sup"] = (
                    t  # (a suppressed phrase keeps the wall known for the next second: the nearest point flickers)
                )
                return True
        return False


def followed_wall(it: Item, t: float, state: dict[Any, Any], cfg: dict[str, Any]) -> bool:
    """v26.2.12 (``beeps.follow``, review 9, 21.0 s: "previous beeps already identified the building, I use it as a guide with my cane"): True =
    this beep driver is a wall the user is walking along, so it does not start a NEW beep episode. A building / wall / fence face on one side
    (left: clock <= 11:30, right: >= 12:30) that had a beep episode within the last ``quietS`` seconds with the same family on the same side and a
    lateral within ``lateralM`` of that episode's (matched by family + side + lateral, not by track id: the same wall under a new track) is
    followed. A face at the centre (11:45-12:15) or within ``nearSteps`` of us still beeps; a beep running on (<= ``gapS`` since the last real beep
    of that wall) is the same episode and goes on. The memory is the last real beep, so a wall followed for longer than ``followQuietS`` beeps again."""
    if it.class_name not in cfg.get("classes", ()):
        return False
    side = "left" if it.clock_q <= -2 else "right" if it.clock_q >= 2 else None  # type: ignore[operator]  # clock_q is set for items that reach here
    if side is None or it.steps <= float(cfg.get("nearSteps", 1.0)):
        return False
    key = (it.family or it.label, side)
    st = state.get(key)
    if st is not None and t - st["t_real"] <= float(cfg.get("gapS", 1.5)):  # the episode is running: it goes on
        st["t_real"] = st["t"] = t
        return False
    if (
        st is not None
        and t - st["t"] <= float(cfg.get("followQuietS", 6.0))
        and abs(it.lateral_m - st["lat"]) <= float(cfg.get("lateralM", 0.4))
    ):
        return True  # (not refreshed: the memory is the last REAL episode, so a wall hugged for long beeps again)
    state[key] = {"t": t, "t_real": t, "lat": it.lateral_m}
    return False


class WallFollow:
    """v26.2.13 (``beeps.follow.windowS``, review 10, 11.66 / 50.5 / 57.3 ... 69.1 s: "still following the same wall, no need to re-notify"): a wall
    the user walks ALONG keeps its nearest point at the same distance ahead (the point slides forward with us), a wall really ahead closes at
    about the walking speed (15.5-18.1 s: 5 -> 1 steps). Per wall track the (distance, distance walked) samples of the last ``windowS`` s are kept;
    the wall is *followed* when, from the nearest value of the older half of the window, its distance closed by less than ``minCloseRatio`` x the
    distance walked since (needs ``minWalkM`` walked and ``minSpanS`` of history; undecided = not followed). A gap of more than ``gapMaxS`` or a
    jump of the distance AWAY of ``jumpM`` or more (the nearest point moved to another face) restarts the history; a jump nearer is a wall that is
    there. A wall is only *quiet* when its track has been seen for ``besideS`` s or a wall phrase / beep was due within ``recentS`` s (a building
    that just came up in the lane is news, one that is known is not); A beep episode that is running goes on (``quiet``)."""

    def __init__(self, cfg: dict[str, Any]):
        self.window = float(cfg.get("windowS", 0.0)) if cfg.get("enabled", True) else 0.0
        self.on = self.window > 0
        self.min_ratio = float(cfg.get("minCloseRatio", 0.4))
        self.min_walk = float(cfg.get("minWalkM", 0.5))
        self.min_span = float(cfg.get("minSpanS", 0.5 * self.window))
        self.gap = float(cfg.get("gapMaxS", 0.7))
        self.jump = float(cfg.get("jumpM", 3.0))
        self.beside_s = float(cfg.get("besideS", 5.0))
        self.recent_s = float(cfg.get("recentS", 4.5))
        self.near_steps = float(cfg.get("nearSteps", 1.0))
        self.classes = frozenset(cfg.get("classes", ()))
        self.walked = 0.0
        self.hist: dict[int, list[tuple[float, float, float]]] = {}
        self.first: dict[int, float] = {}  # track -> first frame seen
        self.last_followed: dict[str, float] = {}  # family -> last frame a wall of it was followed
        self.cand_last: dict[str, float] = {}  # family -> last frame a wall of it was due a beep (real or quiet)
        self.prev_end: dict[
            str, float
        ] = {}  # ... and the last frame of the run before the current one (a run: frames < ``gapS`` apart)
        self.run_gap = float(cfg.get("gapS", 1.5))
        self.last_real: dict[
            str, float
        ] = {}  # family -> last frame a wall of it really beeped (an episode running goes on)

    def advance(self, dt: float, speed: float | None) -> None:
        if speed is not None and speed > 0:
            self.walked += speed * dt

    def observe(self, t: float, items: list[Item]) -> None:
        for it in items:
            if it.class_name not in self.classes or it.coasting or it.ghost:
                it.followed = False
                continue
            tid, fam = it.track_id, it.family or it.label
            h = self.hist.setdefault(tid, [])
            self.first.setdefault(tid, t)
            if h and (t - h[-1][0] > self.gap or it.distance_m - h[-1][1] >= self.jump):
                h.clear()
            h.append((t, it.distance_m, self.walked))
            while h and t - h[0][0] > self.window + 1e-9:
                h.pop(0)
            it.followed = it.steps > self.near_steps and self._ratio(t, it.distance_m, h)
            if it.followed:
                self.last_followed[fam] = t
            if (
                it.followed
                and t - self.first[tid] < self.beside_s - 1e-9
                and t - self._last_event(t, fam) > self.recent_s
            ):
                it.followed = False  # a wall that just came up and was not announced lately is news
        for tid in [k for k, h in self.hist.items() if t - h[-1][0] > 2.0]:
            del self.hist[tid]
            self.first.pop(tid, None)

    def _ratio(self, t: float, d_now: float, h: list[tuple[float, float, float]]) -> bool:
        if t - h[0][0] < self.min_span - 1e-9:
            return False
        half = [x for x in h if x[0] <= h[0][0] + 0.5 * (t - h[0][0]) + 1e-9]
        _t0, d0, w0 = min(half, key=lambda x: x[1])
        walked = self.walked - w0
        return walked >= self.min_walk - 1e-9 and (d0 - d_now) < self.min_ratio * walked

    def quiet(self, t: float, it: Item, gap_s: float) -> bool:
        """True = this beep driver starts no episode (a followed wall; one whose episode is running goes on)."""
        fam = it.family or it.label
        return it.followed and t - self.last_real.get(fam, -math.inf) > gap_s

    def _last_event(self, t: float, fam: str) -> float:
        """The last wall event BEFORE the run of beep frames it may be in (a run does not make itself a recent event)."""
        last = self.cand_last.get(fam, -math.inf)
        return self.prev_end.get(fam, -math.inf) if t - last <= self.run_gap else last

    def candidate(self, t: float, it: Item) -> bool:
        """A wall due a beep this frame; True = it starts a new run (episode) of its family."""
        fam = it.family or it.label
        last = self.cand_last.get(fam, -math.inf)
        start = t - last > self.run_gap
        if start:
            self.prev_end[fam] = last
        self.cand_last[fam] = t
        return start

    def beeped(self, t: float, it: Item) -> None:
        self.last_real[it.family or it.label] = t


def passing_close(it: Item, cfg: dict[str, Any]) -> bool:
    """v26.2.13 (``beeps.passing``, review 10, 59.16 s: "don't forget the beeps for this person when passing close to me"): a moving person / rider /
    vehicle that is closing in (>= ``minClosingMps``), within ``lateralM`` m sideways and ``maxSteps`` steps, outside the beeping lane, gets the soft
    sound (``proximity``) until it has passed (its distance stops closing). Static items outside the lane never do."""
    return (
        it.group == "moving"
        and not it.coasting
        and not it.ghost
        and it.moving is True
        and not it.receding
        and not it.collision
        and it.closing is not None
        and it.closing >= float(cfg.get("minClosingMps", 0.8))
        and abs(it.lateral_m) <= float(cfg.get("lateralM", 1.5))
        and it.steps <= float(cfg.get("maxSteps", 4.0))
    )
