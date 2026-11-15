"""The speech policy: state, priorities, one phrase per frame (``step``) and the predictive-speech helpers."""
# ruff: noqa: E501

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from engine.core.clock import clock_from_bearing, clock_quarter, clock_text
from engine.core.settings import WARMUP_S
from engine.speech.context import ContextMixin
from engine.speech.movers import MoversMixin
from engine.speech.text import TextMixin
from engine.speech.walls import WallsMixin

if TYPE_CHECKING:
    from collections.abc import Callable

    from engine.core.types import Item, ObjectMemory, Track

__all__ = ["SpeechPolicy"]


class SpeechPolicy(TextMixin, ContextMixin, WallsMixin, MoversMixin):
    """At most one phrase per frame; see the module docstring ("Less is more").

    Priority: final > danger > feature > surface > context. Only the highest
    priority class that has candidates is considered in a frame, so a danger
    that waits for the global gap is never overtaken by lower priorities.
    """

    LABEL_COOLDOWN_S = 5.0  # same label again (a fragmented track) stays quiet this long

    def __init__(self, config: dict[str, Any]):
        self.cfg = config["speech"]
        self.forget_s = config["contextMemory"]["forgetAfterSeconds"]
        self.final_steps = config["roles"]["finalSteps"]
        self.confirm = int(config["roles"].get("confirmFrames", 1))
        self.max_items = int(self.cfg.get("contextMaxItems", 1))
        self.max_entries = int(self.cfg.get("maxEntries", 3))
        self.thin_rearm_s = float(self.cfg.get("thinRearmSeconds", 8.0))
        self.feature_gap_s = float(self.cfg.get("featureLabelGapSeconds", 6.0))
        self.feature_new_steps = float(self.cfg.get("featureNewCrossingSteps", 5.0))
        self.travel_steps = 0.0  # our own walking, in steps (set by the driver)
        self.landmarks = frozenset(config["classes"].get("landmark", []))
        self.thin_armed = True
        self.last_thin_seen = -math.inf
        self.thin_range = (
            float(config["roles"].get("thinNoticeSteps", 15)),
            float(config["roles"].get("thinNoticeLateralM", 2.5)),
        )
        self.danger_first: dict[int, float] = {}  # track id -> when it first was a confirmed danger
        self.motion_wait_s = float(self.cfg.get("peopleMotionWaitSeconds", 1.5))
        self.motion_wait_steps = float(self.cfg.get("peopleMotionWaitSteps", 6))
        self.last_t: float | None = None
        self.last_prio_t: float | None = None
        self.last_danger_t: float | None = None  # last danger / final phrase (v26.1.15)
        self.last_say_t: float | None = None  # last phrase that was really spoken (v26.2.14)
        self.last_beep_t: float | None = None  # last frame with a collision beep driver (v26.1.16, set by the driver)
        self.after_danger_s = float(config["roles"].get("contextAfterDangerSeconds", 0.0))
        self.memory: dict[str, float] = {}  # context label (family) -> last seen
        self.pending_since: dict[str, float] = {}  # context waiting for the gap
        self.feature_label_t: dict[str, tuple[float, float]] = {}  # label -> (time, position in steps along our walk)
        self.danger_label_t: dict[str, float] = {}
        self.surface_pending: tuple[str, str] | None = None  # (group, label) waiting to be spoken
        self.context_speak = set(config.get("contextSpeak", []))
        # start summary: the first context phrase of a run (and after a path change) needs only
        # ``confirmFrames`` frames, no track age and no adopted surface, so it comes within ~1 s
        self.summary = True
        self.first_summary = True  # the run's first summary: not limited to near-lateral items
        self.summary_since: float | None = None
        self.world: ObjectMemory | None = (
            None  # object permanence (v26.1.7); set by the driver, None = track/label rules
        )
        self.stationary = False  # the user stands still (v26.1.11); set by the driver each frame
        pr = self.cfg.get("predictive") or {}  # v26.2.11: say the position the item has when the phrase ends
        self.pred_on = bool(pr.get("enabled", False))
        self.pred_latency = float(pr.get("startLatencyS", 0.2))
        self.pred_wps = float(pr.get("wordsPerSecond", 2.8))
        self.pred_min_steps = float(pr.get("minSteps", 1))
        self.pred_passed = float(pr.get("passedM", 0.3))
        self.pred_max_adv = float(
            pr.get("maxAdvanceM", 0.0)
        )  # v26.2.12: the most a phrase may advance an item (0 = no cap)
        self.pred_clock_hold = int(
            pr.get("clockHoldQuarters", 0)
        )  # ... the spoken clock stays the current one when the predicted differs by more (0 = off)
        self.pred_meas_floor = float(
            pr.get("measuredFloor", 0.0)
        )  # ... the advance speed = the measured ego speed, at least this share of the cadence speed (0 = cadence only)
        self.ego_meas: float | None = (
            None  # measured ego speed (m/s) from the static witnesses' closing speed, set by the driver
        )
        self.lane_half = float(config["geometry"]["laneHalfWidthM"])
        self.min_voice = float(
            self.cfg.get("minVoiceSteps", 0)
        )  # v26.2.12: a beeping item this close to us is not spoken (the beeps say it)
        zo = self.cfg.get("zoneOnly") or {}  # v26.2.12: thin statics are spoken only inside the collision zone
        self.zone_on = bool(zo.get("enabled", False))
        self.zone_classes = frozenset(zo.get("classes", ()))
        self.zone_half = float(
            zo.get("halfWidthM", 0.0)
        )  # (0 = only a collision item counts as inside; else also |lateral| <= this)
        ra = self.cfg.get("reannounce") or {}  # v26.2.12: a static announced before whose place changed a lot
        self.reann_on = bool(ra.get("enabled", False))
        self.reann_quarters = int(ra.get("clockQuarters", 4))
        self.reann_steps = float(ra.get("growSteps", 3.0))
        self.reann_gap_s = float(ra.get("minGapS", 1.0))
        self.coloc_m = float(
            self.cfg.get("colocatedM", 0.0)
        )  # v26.2.12: co-located collision items are said once, the closest one's numbers
        kw = self.cfg.get("knownWall") or {}  # v26.2.13: a wall phrase is not said again for the same place
        self.known_on = bool(kw.get("enabled", False))
        self.known_s = float(kw.get("windowS", 30.0))
        self.known_rel_s = float(kw.get("relativeS", 12.0))
        self.known_m = float(kw.get("worldM", 2.0))
        self.known_steps = float(kw.get("steps", 1.5))
        self.known_quarters = int(kw.get("quarters", 1))
        self.known_classes = frozenset((config.get("beeps") or {}).get("follow", {}).get("classes", ()))
        self.quiet_t = -math.inf  # the last frame a wall phrase was held back (followed / known)
        self.quiet_slot: set[int] = (
            set()
        )  # wall tracks whose phrase was held back once (the slot was consumed silently)
        self.known_walls: list[
            dict[str, Any]
        ] = []  # recent wall phrases / beeps: {"t", "fam", "wx", "wy", "steps", "q"}
        aw = self.cfg.get("away") or {}  # v26.2.13: "moved away" / "started walking away"
        self.away_on = bool(aw.get("enabled", False))
        self.away_cfg = aw
        self.away_state: dict[
            int, dict[str, Any]
        ] = {}  # track id -> {"col_t", "dan_q", "still_t0", "leave_t0", "fired_t", "static_at_leave"}
        self.speech_rate = 1.0  # the sound profile's speechRate (set by the driver)
        self.ego_u: float | None = (
            None  # our ground speed (m/s), None = unknown (no prediction); set by the driver each frame
        )
        self.pred_stats = {"phrases": 0, "changed": 0, "dropped": 0}
        mo = config.get("motion") or {}  # v26.2.14: movers by their own motion (see _OwnMotion)
        self.motion_on = bool(mo.get("enabled", False))
        self.mo_again_steps = float(
            mo.get("againSteps", 2.0)
        )  # a near-pass mover is said again when its steps dropped by this much ...
        self.mo_again_gap = float(mo.get("againGapS", 1.5))  # ... since its last phrase, at least this long ago
        self.cut_cfg = mo.get("cut") or {}
        self.ahead_cfg = mo.get("ahead") or {}
        self.mover_state: dict[
            int, dict[str, Any]
        ] = {}  # track id -> {"out_t", "cut_t", "cut_run", "ahead_t0", "ahead_done", "fired_t", "away_t"}

    # -- memory (ContextMixin) and phrases (TextMixin): engine.speech -----

    STATE_WORDS = {"standing": "standing", "stopped": "stopped", "receding": "moving away", "approach": "approaching"}  # noqa: RUF012

    # -- predictive speech (v26.2.11) --------------------------------------

    def _view(self, it: Item, dt: float) -> Item | None:
        """The item as it is ``dt`` seconds from now: we walk ``ego_u`` m/s straight ahead, a static-like item stays, a mover with a trusted
        world track keeps its velocity (``pred_v``). None = passed (forward < ``passedM``)."""
        u = self.ego_u or 0.0
        if (
            self.pred_meas_floor > 0 and self.ego_meas is not None
        ):  # v26.2.12 (review 9, 23.51 s): the speed the items really close at
            u = min(u, max(self.ego_meas, self.pred_meas_floor * u))
        vf, vr = it.pred_v if it.pred_v is not None else (0.0, 0.0)
        f0 = it.distance_m
        f, r = f0 + (vf - u) * dt, it.lateral_m + vr * dt
        if f < self.pred_passed:
            return None  # passed by the end of the phrase (judged on the uncapped advance)
        if self.pred_max_adv > 0 and f0 - f > self.pred_max_adv:
            f = f0 - self.pred_max_adv  # (the cap moves the item along its line of approach only)
        bearing = math.degrees(math.atan2(r, f))
        cq = clock_quarter(bearing)
        if self.pred_clock_hold > 0 and abs(cq - it.clock_q) > self.pred_clock_hold:  # type: ignore[operator]  # clock_q is set in __post_init__
            cq = it.clock_q  # type: ignore[assignment]  # (set in __post_init__)  # no swing across the dial: "pole at 1:15" for a pole that is dead ahead
            bearing = it.bearing
        steps = it.steps * f / f0 if f0 > 1e-6 else it.steps
        return replace(
            it,
            distance_m=f,
            lateral_m=r,
            bearing=bearing,
            clock=clock_from_bearing(bearing),
            clock_q=cq,
            clock_text=clock_text(cq),
            steps=max(steps, self.pred_min_steps),
        )

    def _voice(self, it: Item | None) -> Item | None:
        """v26.2.12 (``speech.minVoiceSteps``, review 9, 0.17 s: "too close for voice notice, beeps will handle this one"): an item that is beeping
        (a collision danger / final) and whose spoken steps (the predicted ones when the phrase is predicted) are at most ``minVoiceSteps`` is left out
        of the phrase; the beeps stay. None = dropped."""
        if it is None or self.min_voice <= 0:
            return it
        if it.collision and it.role in ("danger", "final") and self._n(it.steps) <= self.min_voice + 1e-9:
            return None
        return it

    def _reannounce(self, t: float, it: Item, tr: Track) -> bool:
        """v26.2.12 (``speech.reannounce``, review 9, 13.0 s): a static collision item announced before is announced again when its spoken place
        changed a lot: its clock moved >= ``clockQuarters`` (4 = two half-hours) while it is a collision now, or its distance grew by >= ``growSteps``
        steps (it now means another part of the wall: "building at 12:45 in 2" -> "building at 12 in 9")."""
        if (
            not self.reann_on
            or it.group != "static"
            or not it.speak
            or not it.collision
            or not tr.danger_done
            or tr.said is None
        ):
            return False
        _d0, q0, s0, t0 = tr.said
        if t - t0 < self.reann_gap_s - 1e-9:
            return False
        return abs(it.clock_q - q0) >= self.reann_quarters or it.steps - s0 >= self.reann_steps  # type: ignore[no-any-return]  # tr.said is an untyped tuple

    def _closing_again(self, t: float, it: Item, tr: Track) -> bool:
        """v26.2.14 (``motion.againSteps`` / ``againGapS``, review 11, 59.16 / 69.34 s: "stops speaking when the person is already on top of me"): an
        approaching mover that passes within ``nearPassM`` of us (``near_pass``) and was said before is said again when its steps dropped by
        ``againSteps`` since its last phrase, at least ``againGapS`` s later: "person approaching at 11:30 in 3"."""
        if not (self.motion_on and it.near_pass and it.speak):
            return False
        ref = None  # (steps, t) of the last phrase for this mover: its remembered object (fragments of one person), else its track
        if self._mem and it.mem_id is not None:
            ref = self.world.entries.get(it.mem_id, {}).get("said")  # type: ignore[union-attr]  # guarded by self._mem
        if ref is None and tr.danger_done and tr.said is not None:
            ref = (tr.said[2], tr.said[3])
        if ref is None:
            return False
        return (
            ref[0] - it.steps >= self.mo_again_steps - 1e-9
            and t - ref[1] >= self.mo_again_gap - 1e-9
            and self._kind(it, "danger") == "approach"
        )

    def _zone_ok(self, it: Item) -> bool:
        """v26.2.12 (``speech.zoneOnly``, review 9, 1.17 / 23.51 s: "not within the collision zone"): a thin static (pole, sign, light, obstacle,
        manhole cover) is spoken only when it is a collision item NOW (inside the lane as the role rules judge it: the current position, not the
        predicted one)."""
        return (
            not self.zone_on
            or it.class_name not in self.zone_classes
            or it.collision
            or abs(it.lateral_m) <= self.zone_half
        )

    def _compose(self, build: Any, lead: Item | None, wrap: Any = None) -> Any:
        """(text, predicted info) of a phrase. ``build(view)`` -> list of (items, text) segments, ``view(item)`` -> the item to say (None =
        dropped from its segment). The phrase is built on today's positions; each item is timed to the END OF ITS OWN SEGMENT: ``dt_i`` =
        ``startLatencyS`` + words up to and including that segment / (``wordsPerSecond`` x speech rate). It is built once more on every item's
        position at ``t + dt_i`` (an item passed by then is dropped). ``wrap(text)`` adds the phrase template. Without prediction (off, our
        speed unknown) the first text."""
        wrap = wrap or (lambda t: t)
        parts = build(lambda it: self._voice(it))
        text = wrap(", ".join(t for _, t in parts)) if parts else None
        if not self.pred_on or self.ego_u is None or text is None:
            return text, None
        rate = max(self.pred_wps * self.speech_rate, 1e-6)
        dts: dict[int, float] = {}
        words = 0
        order: list[int] = []
        for grp, seg in parts:
            words += self._words(seg)
            for it in grp:
                dts[id(it)] = self.pred_latency + words / rate
                order.append(id(it))
        phrase_s = self.pred_latency + words / rate
        views = {}
        by_id = {id(it): it for grp, _ in parts for it in grp}
        for k, it in by_id.items():
            views[k] = self._view(it, dts[k])
        parts2 = build(lambda it: self._voice(views.get(id(it), it)))
        text2 = wrap(", ".join(t for _, t in parts2)) if parts2 else None
        self.pred_stats["phrases"] += 1
        self.pred_stats["dropped"] += sum(1 for v in views.values() if v is None)
        if text2 != text:
            self.pred_stats["changed"] += 1
        info = {"dt": round(dts.get(id(lead), phrase_s), 2), "phraseS": round(phrase_s, 2), "textNow": text}
        if len(order) > 1:
            info["dts"] = [round(dts[k], 2) for k in order]
        v = views.get(id(lead)) if lead is not None else None
        if v is not None:
            info.update(
                {
                    "steps": self._n(v.steps),
                    "clock": v.clock_text,
                    "fwd": round(v.distance_m, 2),
                    "right": round(v.lateral_m, 2),
                }
            )
        return text2, info

    def _with_prediction(self, ev: dict[str, Any], info: dict[str, Any] | None, lead: Item | None) -> dict[str, Any]:
        if info is not None:
            if lead is not None:
                info = {**info, "stepsNow": self._n(lead.steps)}
            ev["predicted"] = {
                k: info[k]
                for k in ("dt", "phraseS", "dts", "steps", "clock", "fwd", "right", "stepsNow", "textNow")
                if k in info
            }
        return ev

    def _feature_allowed(self, t: float, it: Item) -> bool:
        """The same label is not repeated within featureLabelGapSeconds unless it is a different crossing: its
        position along our walk (calibrated steps ahead plus steps walked) differs by >= featureNewCrossingSteps.
        Fragments of one curb re-tracked under new ids sit at the same position and stay quiet."""
        last = self.feature_label_t.get(it.label)
        over = self.cfg.get("featureLabelOverrides", {}).get(it.class_name, {})
        if last is None or t - last[0] >= over.get("gapSeconds", self.feature_gap_s):
            return True
        return abs(self.travel_steps + it.steps - last[1]) >= over.get("newCrossingSteps", self.feature_new_steps)  # type: ignore[no-any-return]  # cfg is the untyped config block

    def _motion_pending(self, t: float, it: Item, tracks: dict[int, Track]) -> bool:
        """A person whose motion is not measured yet may "approach": wait a moment (the closing speed needs
        ~0.75 s of history) so that the phrase can say "approaching" - unless they are already close."""
        return (
            it.people
            and it.moving is None
            and it.ego_known
            and it.ego_settled
            and it.steps > self.motion_wait_steps
            and t - self.danger_first.get(it.track_id, t) < self.motion_wait_s
        )

    def _danger_recent(self, t: float) -> bool:
        """A danger / final phrase or a collision beep within ``contextAfterDangerSeconds`` (v26.1.16, review 8, 107.0 s: "in the middle
        of multiple danger notifications, no need for context")."""
        last = max((x for x in (self.last_danger_t, self.last_beep_t) if x is not None), default=None)
        return last is not None and t - last < self.after_danger_s - 1e-9

    def _gap_ok(self, t: float, priority: bool = False, danger: bool = False, urgent: bool = False) -> bool:
        """Global minimum gap between phrases. A danger/feature phrase (``priority``) waits only the
        shorter ``priorityMinGapSeconds``: it must not queue behind a scene-context phrase. A phrase with a
        danger in it (``danger``, v26.1.15, review 7: a person was held 0.8 s behind a pole) only counts
        earlier danger / final phrases: a feature or context phrase never delays a danger."""
        gap = self.cfg["globalMinGapSeconds"]
        if danger:
            gap = min(gap, self.cfg.get("priorityMinGapSeconds", gap))
            if urgent:  # v26.2.14: a near-pass mover waits only for the last SPOKEN phrase (a slot consumed silently does not delay it)
                return self.last_say_t is None or t - self.last_say_t >= gap - 1e-9
            return self.last_danger_t is None or t - self.last_danger_t >= gap - 1e-9
        if priority:
            # only earlier danger/feature phrases count: a context phrase never delays a danger
            gap = min(gap, self.cfg.get("priorityMinGapSeconds", gap))
            return self.last_prio_t is None or t - self.last_prio_t >= gap - 1e-9
        return self.last_t is None or t - self.last_t >= gap - 1e-9

    def _event(self, t: float, role: str, text: str, it: Item | None, urgency: str = "none") -> dict[str, Any]:
        self.last_t = t
        if text:
            self.last_say_t = t
        if role in ("danger", "final", "feature"):
            self.last_prio_t = t
        if role in ("danger", "final"):
            self.last_danger_t = t
        return {
            "t": round(t, 4),
            "type": "speech",
            "role": role,
            "text": text,
            "trackId": None if it is None else it.track_id,
            "urgency": urgency,
            "clock": None if it is None else it.clock,
            "clockText": None if it is None else it.clock_text,
            "pan": 0.0 if it is None else round(it.pan, 4),
        }

    def step(
        self, t: float, items: list[Item], tracks: dict[int, Track], surface_known: bool = True
    ) -> dict[str, Any] | None:
        """``surface_known``: a surface has been adopted (context waits for it)."""
        if self.summary_since is None:
            self.summary_since = t
        if self.summary and t - self.summary_since > WARMUP_S + 1e-9 and surface_known:
            self.summary = self.first_summary = False  # the scene had its chance to be summarised; back to normal
        everything = items
        # "beware poles" is said once, then not again while any thin object stays noticed (within thinNoticeSteps);
        # it re-arms after thinRearmSeconds with none noticed, or on a turn
        if any(i.thin and i.steps <= self.thin_range[0] for i in everything):
            self.last_thin_seen = t
        elif not self.thin_armed and t - self.last_thin_seen >= self.thin_rearm_s:
            self.thin_armed = True
        items = [i for i in items if i.settled]
        ok: Callable[[Item], bool] = lambda i: i.role_run >= self.confirm  # noqa: E731  (confirmed over consecutive frames)
        danger = sorted((i for i in items if i.role == "danger" and ok(i)), key=lambda i: i.steps)
        for i in danger:
            self.danger_first.setdefault(i.track_id, t)
        # 1. final: once per track, ignores the global gap
        for it in danger:
            tr = tracks[it.track_id]
            if it.urgency == "final" and not tr.final_done and it.speak and not it.unstable:
                again = self._closing_again(t, it, tr)
                tr.final_done = tr.danger_done = True
                tr.said = (it.distance_m, it.clock_q, it.steps, t)
                tr.approach_done = tr.approach_done or self._kind(it, "final") == "approach"
                tr.thin_done = tr.thin_done or it.thin
                self.memory_if_spoken(t, it)
                # v26.1.7: a final is only for what was never named. The slot is consumed all the same (the state
                # machine runs exactly as in v26.1.6, so nothing else moves earlier), but nothing is said: the
                # parking-sensor beeps carry the proximity.
                mute = (
                    self._seen_before(it, danger=True) and not again
                )  # v26.1.16: only an earlier danger / final for it mutes (not a context phrase)
                # ... and a never-named context-class thing (vegetation, a wall) reached in the middle of other dangers: its beeps are enough
                mute = mute or (
                    it.group == "static"
                    and not it.thin
                    and tr.context_seen
                    and not it.mem_named
                    and self._danger_recent(t)
                )
                mute = mute or it.followed  # v26.2.13: a wall walked along: the slot is consumed, nothing is said
                if not mute:
                    self._register(t, it, tracks, danger=True)
                    if self._mem and it.mem_id is not None:
                        self.world.mark_said(it.mem_id, it.steps, t)  # type: ignore[union-attr]  # guarded by self._mem
                kind = self._kind(it, "final")
                txt, info = self._compose(lambda v: [] if v(it) is None else [([it], self._text(kind, v(it)))], it)  # noqa: B023
                ev = self._event(t, "final", txt or "", it, "final")
                return None if (mute or txt is None) else self._with_prediction(ev, info, it)
        # 2./3. danger, features and the notice for thin objects, one phrase: danger leads, then features, then thin
        # v26.1.12 (review 5, 76.5 s): a mover announced before is announced again, once, when it turns to "approaching" on a
        # collision course ("moving away" at 63 s, then walking towards us); this is the only re-announcement
        reann = {i.track_id for i in danger if self._reannounce(t, i, tracks[i.track_id])}  # v26.2.12
        reann |= {
            i.track_id for i in danger if self._closing_again(t, i, tracks[i.track_id])
        }  # v26.2.14: a mover passing close, said again as it closes
        pend_d = [
            i
            for i in danger
            if i.speak
            and not i.unstable
            and (
                not tracks[i.track_id].danger_done
                or (not tracks[i.track_id].approach_done and self._kind(i, "danger") == "approach")
                or i.track_id in reann
            )
            and (t - self.danger_label_t.get(i.label, -math.inf) >= self.LABEL_COOLDOWN_S or i.track_id in reann)
            and not self._motion_pending(t, i, tracks)
        ]
        if any(
            i.followed or i.class_name in self.known_classes for i in pend_d
        ):  # v26.2.13: a wall that is walked along / known is not said
            kept = [i for i in pend_d if not i.followed and (i.track_id in reann or not self._known_wall(t, i))]
            if not kept and pend_d:
                self.quiet_t = t  # the slot is spent silently: no other phrase (the "blocked" one) takes its place
                fresh = [i for i in pend_d if i.track_id not in self.quiet_slot]
                if fresh:  # ... once per wall track, with the pacing the spoken phrase would have had (v26.1.7: same as a muted final)
                    self.quiet_slot.update(i.track_id for i in fresh)
                    self._event(t, "danger", "", None)
                    return None
            pend_d = kept
        dropped_close: list[Item] = []
        if (
            self.coloc_m > 0 and len(pend_d) > 1
        ):  # v26.2.12 (review 9, 13.0 s: "2 markers within the collision zone, use the closest one"): said once
            chosen: list[Any] = []
            for i in sorted(pend_d, key=lambda i: i.distance_m):
                if (
                    i.group == "static"
                    and i.collision
                    and any(
                        c.group == "static"
                        and c.collision
                        and math.hypot(i.distance_m - c.distance_m, i.lateral_m - c.lateral_m) <= self.coloc_m
                        for c in chosen
                    )
                ):
                    dropped_close.append(i)
                else:
                    chosen.append(i)
            if dropped_close:
                gone = {id(i) for i in dropped_close}
                pend_d = [i for i in pend_d if id(i) not in gone]
        pend_f = sorted(
            (
                i
                for i in items
                if i.role == "feature" and ok(i) and not tracks[i.track_id].feature_done and self._feature_allowed(t, i)
            ),
            key=lambda i: (i.class_name not in self.landmarks, i.steps),
        )  # crosswalks before curbs
        pend_t = [
            i
            for i in items
            if i.thin
            and i.present_run >= self.confirm
            and not tracks[i.track_id].thin_done
            and i.steps <= self.thin_range[0]
            and abs(i.lateral_m) <= self.thin_range[1]
            and not self.stationary
            and self._zone_ok(i)
            and not i.unstable
        ]
        in_danger = {i.track_id for i in pend_d}
        note = [i for i in pend_t if i.track_id not in in_danger]
        if (
            self.coloc_m > 0 and note and pend_d
        ):  # a thin notice co-located with a closer danger item in the phrase is the same marker
            near = [
                i
                for i in note
                if i.collision
                and any(
                    c.group == "static"
                    and c.collision
                    and c.distance_m <= i.distance_m
                    and math.hypot(i.distance_m - c.distance_m, i.lateral_m - c.lateral_m) <= self.coloc_m
                    for c in pend_d
                )
            ]
            if near:
                dropped_close.extend(near)
                gone = {id(i) for i in near}
                note = [i for i in note if id(i) not in gone]
        if not self.thin_armed:
            for i in note:  # covered by the earlier notice: not named, but not new either
                self._register(t, i, tracks, named=False)
            note = []  # said already; a noticed thin object keeps it quiet
        if pend_d or pend_f or note:
            if not self._gap_ok(
                t, priority=True, danger=bool(pend_d), urgent=self.motion_on and any(i.near_pass for i in pend_d)
            ):
                return None
            for i in dropped_close:  # co-located with a closer item that is said: consumed with it
                tracks[i.track_id].danger_done = True
                tracks[i.track_id].thin_done = tracks[i.track_id].thin_done or i.thin
                tracks[i.track_id].said = (i.distance_m, i.clock_q, i.steps, t)
                self._register(t, i, tracks, danger=True)
            entries: list[tuple[str, list[Item]]] = []  # (kind, same-label items)
            for kind, pool in (("danger", pend_d), ("feature", pend_f)):
                by: dict[tuple[Any, ...], list[Item]] = {}
                for i in pool:
                    by.setdefault((i.label, self._kind(i, "danger") if kind == "danger" else "feature"), []).append(i)
                for (_, template), grp in by.items():
                    entries.append((template, grp))
            by_thin: dict[str, list[Item]] = {}  # "poles at 11 and 1 in 8": same-label thin objects, nearest steps
            for i in note:
                by_thin.setdefault(i.label, []).append(i)
            entries.extend(("thin", grp) for grp in sorted(by_thin.values(), key=lambda g: min(i.steps for i in g)))
            entries = entries[: self.max_entries]
            cover: list[Item] = []
            for kind, grp in entries:  # the v26.1.6 bookkeeping, for everything the phrase would cover
                if kind == "thin":
                    for i in grp:
                        tracks[i.track_id].thin_done = True
                    mine = {i.track_id for i in grp}
                    for i in items:  # the whole cluster in view counts as warned about
                        if i.thin:
                            tracks[i.track_id].thin_done = True
                            if self._mem and i.steps <= self.thin_range[0] and i.track_id not in mine:
                                cover.append(i)  # ... covered, if near enough to be noticed
                    self.thin_armed = False
                    continue
                for i in grp:
                    tr = tracks[i.track_id]
                    if kind == "feature":
                        tr.feature_done = True
                        self.feature_label_t[i.label] = (t, self.travel_steps + i.steps)
                    else:
                        tr.danger_done = True
                        tr.said = (i.distance_m, i.clock_q, i.steps, t)
                        tr.approach_done = tr.approach_done or kind == "approach"
                        tr.thin_done = tr.thin_done or i.thin
                        self.danger_label_t[i.label] = t
                        self.memory_if_spoken(t, i)
            # v26.1.7: only what is not a remembered object is said. Objects remembered already leave the phrase; when
            # nothing is left the slot is consumed silently (same pacing as v26.1.6, see the final above).
            voiced: list[tuple[str, list[Item]]] = []
            for kind, grp in entries:
                is_danger = kind not in ("feature", "thin")
                vg = [
                    i
                    for i in grp
                    if i.track_id in reann
                    or not self._seen_before(i, named=(kind != "thin"), approach=(kind == "approach"), danger=is_danger)
                ]
                if vg:
                    voiced.append((kind, vg))
                    for i in vg:
                        self._register(t, i, tracks, approach=(kind == "approach"), danger=is_danger)
                        self.note_wall(t, i)
                        if is_danger and self._mem and i.mem_id is not None:
                            self.world.mark_said(i.mem_id, i.steps, t)  # type: ignore[union-attr]  # guarded by self._mem
            for i in cover:
                self._register(t, i, tracks, named=False)
            if not voiced:
                self._event(t, "feature", "", None)
                return None
            lead = next((grp[0] for kind, grp in voiced if kind != "thin"), voiced[0][1][0])

            def build(v: Any, voiced: Any = voiced) -> Any:
                parts = []
                for kind, grp in voiced:
                    alive = [(i, v(i)) for i in grp if v(i) is not None]
                    if alive:
                        parts.append(([i for i, _ in alive], self._entry(kind, [w for _, w in alive])))
                return parts

            text, info = self._compose(build, lead)
            if text is None:  # everything in it is passed by the end of the phrase: the beeps said it (slot consumed)
                self._event(t, "feature", "", None)
                return None
            if any(kind not in ("feature", "thin") for kind, _ in voiced):
                return self._with_prediction(self._event(t, "danger", text, lead, "danger"), info, lead)
            return self._with_prediction(self._event(t, "feature", text, lead), info, lead)
        if danger:  # context and surface wait while a danger is active
            self.pending_since.clear()
            return None
        # 4. surface
        if self.surface_pending is not None:
            if not self._gap_ok(t):
                return None
            label = self.surface_pending[1]
            self.surface_pending = None
            return self._event(t, "surface", self._text("surface", label=label), None)
        if self._danger_recent(t):  # v26.1.16: no context just after a danger / final phrase or a collision beep
            self.pending_since.clear()
            return None
        # 5. context (after the first surface: the user hears where they walk before what is around;
        #    the start summary does not wait for it and needs no track age, only the confirmation)
        if self.summary:
            pool = [i for i in everything if i.role_run >= self.confirm]
            if self.first_summary:
                pool = [i for i in pool if i.role == "context" or i.summary_ok]
        elif surface_known:
            pool = items
        else:
            return None
        cands: dict[str, Item] = {}  # one per label, the nearest
        for it in pool:
            if (
                (it.role == "context" or (self.summary and self.first_summary and it.summary_ok))
                and it.label in self.context_speak
                and self._zone_ok(it)
            ):
                key = self._key(it)
                if not self._known(key) and (key not in cands or it.distance_m < cands[key].distance_m):
                    cands[key] = it
        for key in list(self.pending_since):
            if key not in cands:
                del self.pending_since[key]
        for key in cands:
            self.pending_since.setdefault(key, t)
        for key in [k for k in cands if t - self.pending_since[k] > self.cfg["contextMaxDelaySeconds"] + 1e-9]:
            self.memory[key] = t  # too stale to say: treat as known, never spoken
            del cands[key]
            del self.pending_since[key]
        if not cands or not self._gap_ok(t):
            return None
        if (
            self.summary
            and t - min(self.pending_since[k] for k in cands) < self.cfg.get("summaryHoldSeconds", 0.0) - 1e-9
        ):
            return None  # let the rest of the first view get confirmed: one phrase, not three
        # one grouped phrase: all newly announceable labels, nearest first, at most contextMaxItems
        chosen = sorted(cands, key=lambda k: cands[k].distance_m)[: self.max_items]
        for key in chosen:
            self.memory[key] = t
            self.pending_since.pop(key, None)
        self.summary = self.first_summary = False
        # v26.1.7: a remembered object (turned back to, re-detected) is not named again; the slot is still consumed
        chosen = [k for k in chosen if not self._seen_before(cands[k])]
        if not chosen:
            self._event(t, "context", "", None)
            return None
        for key in chosen:
            self._register(t, cands[key], tracks)
        first = cands[chosen[0]]

        def build_ctx(v: Any) -> Any:
            return [([cands[k]], self._text("context", v(cands[k]))) for k in chosen if v(cands[k]) is not None]

        text, info = self._compose(
            build_ctx, first, lambda items: self.cfg["templates"].get("contextGroup", "{items}").format(items=items)
        )
        if text is None:
            self._event(t, "context", "", None)
            return None
        return self._with_prediction(self._event(t, "context", text, first), info, first)
