"""Movers: the "moved away", "cutting in front" and "moving away ahead" phrases of a speech policy."""
# ruff: noqa: E501

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from engine.core.clock import clock_text

if TYPE_CHECKING:
    from engine.core.types import Item, Track

__all__ = ["MoversMixin"]


class MoversMixin:
    """The mover methods of ``SpeechPolicy`` (composed with ``TextMixin``, ``ContextMixin`` and ``WallsMixin``)."""

    cfg: dict[str, Any]
    away_on: bool
    away_cfg: dict[str, Any]
    away_state: dict[int, dict[str, Any]]
    motion_on: bool
    cut_cfg: dict[str, Any]
    ahead_cfg: dict[str, Any]
    mover_state: dict[int, dict[str, Any]]
    lane_half: float
    stationary: bool

    if TYPE_CHECKING:

        def _gap_ok(self, t: float, priority: bool = False, danger: bool = False, urgent: bool = False) -> bool: ...
        def _event(self, t: float, role: str, text: str, it: Item | None, urgency: str = "none") -> dict[str, Any]: ...
        def _fmt(self, template: str, **kw: Any) -> str: ...
        def _steps_txt(self, it: Item) -> str | None: ...

    # -- "moved away" (v26.2.13) --------------------------------------------
    def observe_movers(self, t: float, items: list[Item], tracks: dict[int, Track]) -> None:
        """v26.2.13 (``speech.away``, review 10, 30.16 / 40.34 s): per mover track, when it last was a collision item (and where), since when it
        stood still, and since when it has been leaving the lane by its own motion (|lateral| past lane half + ``marginM`` and growing at
        >= ``minLatMps``, or its distance growing while we walk)."""
        if not self.away_on:
            return
        a = self.away_cfg
        lat_w = float(a.get("latWindowS", 0.4))
        seen = set()
        for it in items:
            if it.group != "moving" or it.coasting or it.ghost:
                continue
            tid = it.track_id
            seen.add(tid)
            st = self.away_state.setdefault(
                tid, {"col_t": -math.inf, "dan_q": 0, "still_t0": None, "leave_t0": None, "fired_t": -math.inf}
            )
            if it.moving is False:
                if st["still_t0"] is None:
                    st["still_t0"] = t
            elif it.moving is True:
                st["still_t0"] = None
            if it.role == "danger":
                st["dan_q"] = it.clock_q  # (the clock it is spoken at: where it was last a danger)
            if it.role == "danger" and (it.collision or (self.motion_on and it.own_ok and it.receding)):
                st.update(
                    col_t=t, leave_t0=None
                )  # (v26.2.14: a person walking away ahead is no collision course now, but it still "moves away" when it leaves the lane)
                continue
            if t - st["col_t"] > float(a.get("recentS", 2.0)) + 1e-9:
                st["leave_t0"] = None
                continue
            lh = tracks[tid].lhist
            old = next((h for h in reversed(lh) if t - h[0] >= lat_w - 1e-9), None)
            lat_speed = 0.0 if old is None else (abs(it.lateral_m) - abs(old[1])) / max(t - old[0], 1e-6)
            out = abs(it.lateral_m) > self.lane_half + float(a.get("marginM", 0.2)) and lat_speed >= float(
                a.get("minLatMps", 0.2)
            )
            grows = (
                it.receding
                and it.moving is True
                and old is not None
                and it.distance_m - old[2] >= float(a.get("minGrowM", 0.3))
            )
            # (a mover that closes on us faster than ``maxClosingMps`` passes by, it does not move away)
            beyond = abs(it.lateral_m) > self.lane_half + float(a.get("marginM", 0.2))
            leaving = (out or grows or (st["leave_t0"] is not None and beyond)) and (
                it.closing is None or it.closing <= float(a.get("maxClosingMps", 1.0))
            )  # (once leaving, staying out of the lane goes on)
            if leaving:
                if st["leave_t0"] is None:
                    st["leave_t0"] = t
                    st["static_at_leave"] = (
                        st["still_t0"] is not None and t - st["still_t0"] >= float(a.get("staticS", 1.0)) - 1e-9
                    )
            else:
                st["leave_t0"] = None
        for tid in [k for k in self.away_state if k not in seen and t - self.away_state[k]["col_t"] > 10.0]:
            del self.away_state[tid]

    def away_speech(self, t: float, items: list[Item]) -> dict[str, Any] | None:
        """The "moved away" phrase of a mover that has been leaving the lane for ``confirmS`` (``confirmMovingS`` for one that was moving before:
        a swerve may come back), once per track per ``cooldownS``. Text: "person at 12:30 moved away", or for one that stood still
        (``staticS``) "person at 12:15 started walking away" ("started moving away" for a rider / vehicle)."""
        if not self.away_on:
            return None
        a = self.away_cfg
        for it in items:
            st = self.away_state.get(it.track_id)
            if st is None or st["leave_t0"] is None or it.group != "moving" or it.coasting or it.ghost:
                continue
            static = st.get("static_at_leave", False)
            need = float(a.get("confirmS", 0.0)) if static else float(a.get("confirmMovingS", 0.8))
            if t - st["leave_t0"] < need - 1e-9 or t - st["fired_t"] < float(a.get("cooldownS", 10.0)) - 1e-9:
                continue
            if not self._gap_ok(t, priority=True, danger=True):
                continue
            tpl = a["templates"]["started" if static else "moved"]
            verb = "walking" if it.class_name == "person" else "moving"
            text = tpl.format(label=it.label, clock=clock_text(st["dan_q"]), verb=verb)
            st["fired_t"], st["leave_t0"], st["col_t"] = t, None, -math.inf
            return self._event(t, "danger", text, it, "danger")
        return None

    # -- "cutting in front" / "moving away" ahead (v26.2.14) -------------------------
    def motion_speech(self, t: float, items: list[Item]) -> dict[str, Any] | None:
        """v26.2.14 (``motion.cut`` / ``motion.ahead``, review 11, 141.0 / 149.37 s), from a person's own velocity (``_OwnMotion``).

        * "person cutting in front" (final, once per track per ``cooldownS``): a person within ``maxSteps`` steps whose own lateral motion
          (>= ``minLatMps``, towards our line) takes it into the lane within ``withinS`` s, and who was outside the lane (or at its edge) a moment ago
          (``recentOutS``), for ``confirmFrames`` frames;
        * "person moving away at 12 in 4" (danger): a person in the lane within ``maxSteps`` steps who walks the same way (own speed away from us
          >= ``minAwayMps``, lateral speed <= ``maxLatMps``) and whose gap is steady or growing (closing <= ``maxCloseMps``) for ``stableS`` s: once
          per spell in the lane."""
        if not self.motion_on:
            return None
        cut, ah = self.cut_cfg, self.ahead_cfg
        lane = self.lane_half
        seen = set()
        fire = None
        for it in items:
            if it.group != "moving" or it.class_name != "person" or it.coasting or it.ghost or not it.settled:
                continue
            tid = it.track_id
            seen.add(tid)
            st = self.mover_state.setdefault(
                tid,
                {
                    "out_t": -math.inf,
                    "out_since": None,
                    "cut_run": 0,
                    "cut_fired": -math.inf,
                    "ahead_t0": None,
                    "ahead_done": False,
                    "ahead_fired": -math.inf,
                },
            )
            lat = it.lateral_m
            if abs(lat) > lane + float(cut.get("outMarginM", 0.15)):
                st["out_t"] = t
                st["out_since"] = t if st["out_since"] is None else st["out_since"]
                if t - st["out_since"] >= float(ah.get("rearmOutS", 1.0)) - 1e-9:
                    st["ahead_done"] = False
            else:
                st["out_since"] = None
            vf, vr, _ = it.own if (it.own_ok and it.own) else (None, None, None)
            if vf is None or self.stationary:
                st["cut_run"], st["ahead_t0"] = 0, None
                continue
            rng = max(math.hypot(it.distance_m, lat), 1e-6)
            into = (
                lat * vr < 0
                and abs(vr) >= float(cut.get("minLatMps", 0.3))
                and abs(lat + vr * float(cut.get("withinS", 1.5))) <= lane
                and abs(lat) <= lane + float(cut.get("edgeM", 0.5))
                and t - st["out_t"] <= float(cut.get("recentOutS", 2.5))
                and it.steps <= float(cut.get("maxSteps", 4.0))
            )
            st["cut_run"] = st["cut_run"] + 1 if into else 0
            away = (it.distance_m * vf + lat * vr) / rng
            ahead = (
                abs(lat) <= lane
                and it.steps <= float(ah.get("maxSteps", 5.0))
                and away >= float(ah.get("minAwayMps", 0.4))
                and abs(vr) <= float(ah.get("maxLatMps", 0.3))
                and it.own_closing is not None
                and it.own_closing <= float(ah.get("maxCloseMps", 0.3))
            )
            if ahead:
                st["ahead_t0"] = t if st["ahead_t0"] is None else st["ahead_t0"]
            else:
                st["ahead_t0"] = None
            if fire is not None:
                continue
            if (
                st["cut_run"] >= int(cut.get("confirmFrames", 2))
                and t - st["cut_fired"] >= float(cut.get("cooldownS", 10.0)) - 1e-9
            ):
                fire = ("cut", it, st)
            elif (
                st["ahead_t0"] is not None
                and t - st["ahead_t0"] >= float(ah.get("stableS", 1.0)) - 1e-9
                and not st["ahead_done"]
                and t - st["ahead_fired"] >= float(ah.get("cooldownS", 10.0)) - 1e-9
            ):
                fire = ("ahead", it, st)
        for tid in [
            k
            for k in self.mover_state
            if k not in seen and t - max(self.mover_state[k]["out_t"], self.mover_state[k]["cut_fired"]) > 10.0
        ]:
            del self.mover_state[tid]
        if fire is None or not self._gap_ok(t, priority=True, danger=True):
            return None
        kind, it, st = fire
        if kind == "cut":
            st["cut_fired"], st["cut_run"] = t, 0
            st["ahead_done"] = False  # (what follows the cut-in: the person settles in front)
            return self._event(
                t,
                "final",
                self.cfg["templates"].get("cut", "{label} cutting in front").format(label=it.label),
                it,
                "final",
            )
        st["ahead_fired"], st["ahead_done"] = t, True
        return self._event(
            t,
            "danger",
            self._fmt("receding", label=it.label, clock=it.clock_text, steps=self._steps_txt(it)),
            it,
            "danger",
        )
