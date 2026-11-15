"""What the wearer hears: sound kinds, the sound profile, collision / proximity beeps and crosswalk tones."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from engine.core.types import Item

__all__ = [
    "COLLISION_KINDS",
    "SIDE_WORD",
    "SOUND_KINDS",
    "collision_kind",
    "crosswalk_tones",
    "resolve_sounds",
    "tone_events",
    "tone_interval",
]

COLLISION_KINDS = ("collision-left", "collision-center", "collision-right")
SOUND_KINDS = COLLISION_KINDS + ("crosswalk-in", "crosswalk-out", "proximity")  # noqa: RUF005
SIDE_WORD = {"collision-left": "left", "collision-center": "center", "collision-right": "right"}


def collision_kind(quarter: int, center_quarters: int = 1) -> str:
    """Sound kind of a collision tone from the item's clock quarter (v26.1.16): center = 11:45-12:15 (quarters -1..+1),
    left = 9:00-11:30 (<= -2), right = 12:30-3:00 (>= +2). The boundaries 11:45 and 12:15 belong to the center."""
    return (
        "collision-center"
        if abs(quarter) <= center_quarters
        else "collision-left"
        if quarter < 0
        else "collision-right"
    )


def resolve_sounds(tones_cfg: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """The Lab-wide sound profile: ``tones.sounds`` defaults overridden by ``profile`` ({"kinds": {kind: {pitchHz,
    durationMs, intervalS}},
    "speechRate"}), every value clamped to ``tones.soundRanges``; unknown kinds / fields and non-numbers are ignored. A
    field that is
    ``null`` in the defaults (the crosswalk-in repeat interval) stays unused."""
    rng = tones_cfg["soundRanges"]
    kinds = {k: dict(v) for k, v in tones_cfg["sounds"].items()}

    def num(v: Any) -> float | None:
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None

    for k, ent in ((profile or {}).get("kinds") or {}).items():
        if k not in kinds or not isinstance(ent, dict):
            continue
        for f in ("pitchHz", "durationMs", "intervalS"):
            v = num(ent.get(f))
            if v is not None and kinds[k].get(f) is not None:
                kinds[k][f] = max(rng[f][0], min(rng[f][1], v))
    rate = num((profile or {}).get("speechRate"))
    rate = (
        float(tones_cfg.get("speechRate", 1.0))
        if rate is None
        else max(rng["speechRate"][0], min(rng["speechRate"][1], rate))
    )
    return {"kinds": kinds, "speechRate": rate}


def tone_interval(steps: float, by_steps: list[list[float]]) -> float:
    """Beep interval in seconds, linearly interpolated by steps, clamped to the table ends.
    ``by_steps`` rows are ``[steps, intervalSeconds]`` (extra columns are ignored)."""
    table = sorted(by_steps, key=lambda r: r[0])
    return float(np.interp(steps, [r[0] for r in table], [r[1] for r in table]))


def tone_events(
    frame_collision: list[tuple[Item | None, bool]],
    times: npt.NDArray[np.float64],
    tones_cfg: dict[str, Any],
    frame_proximity: list[tuple[Item | None, set[int]]] | None = None,
    crosswalk: list[tuple[float, str]] | None = None,
    sounds: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Notification sounds (CONTRACTS.md 14.1.9/10) -> (tone events, beeps-episode events).

    ``collision-left`` / ``-center`` / ``-right`` (v26.1.16; ``collision`` before): parking-sensor beeps. One
    phase-continuous stream
    driven by the nearest collision track of each frame: interval shrinking with steps, a gapless continuous tone at
    ``continuousSteps``
    or closer. The kind of each tone is that of the driving item's clock quarter at that moment (``collision_kind``), so
    the pitch
    changes where the item changes sector. A track that is merely lost from view (absent from the frame, not changed to
    a
    non-collision) keeps beeping for ``holdSeconds``. ``frame_collision`` holds, per frame, (nearest collision item or
    None, track ids
    present in that frame).

    ``proximity`` (v26.1.13 follow-up): a soft double chirp at a fixed slow rhythm for the nearest person measured
    approaching nearby
    (``frame_proximity``, same shape). It never plays while a collision stream is active (the collision beeps win) and a
    track that
    turns into a collision course simply continues as collision beeps.

    ``crosswalk`` (v26.1.14): ``(t, "enter" | "exit")`` marks from ``_CrosswalkTracker`` -> kinds ``crosswalk-in`` (one
    deep, long tone)
    and ``crosswalk-out`` (the same deep tone twice, short). They are never dropped: one that would sound over a
    collision /
    proximity tone waits for it to end, at most ``maxOffsetSeconds``.

    ``sounds`` = ``resolve_sounds`` output (the Lab profile): pitch, duration and interval per kind. The collision
    interval is the one
    at ``maxSteps`` (5 steps); ``bySteps`` is scaled by ``intervalS / bySteps(maxSteps)`` (the continuous chunk is not
    scaled). The
    proximity interval is its repeat period, the crosswalk-out interval the gap between its two tones.
    """
    sounds = sounds or resolve_sounds(tones_cfg)
    kinds = sounds["kinds"]
    last_dt = float(np.median(np.diff(times))) if len(times) > 1 else 1.0
    hold_s = float(tones_cfg.get("holdSeconds", 0.5))
    gap_s = float(tones_cfg.get("episodeGapSeconds", 1.5))
    by_steps = tones_cfg["bySteps"]
    ref_interval = tone_interval(float(tones_cfg.get("maxSteps", 5)), by_steps)
    center_q = int(tones_cfg.get("centerQuarters", 1))
    prox = tones_cfg.get("proximity") or {}
    chirp = dict(prox.get("chirp") or {})
    n_chirp = int(chirp.get("count", 2))
    chirp_gap = float(chirp.get("gapSeconds", 0.1))

    def stream(
        frames: Any, name: str
    ) -> tuple[list[dict[str, Any]], list[tuple[float, float, Item, str]], list[tuple[float, float]]]:
        soft = name == "proximity"
        chunk = float(tones_cfg.get("continuousChunkSeconds", 0.25))
        cont_steps = float(tones_cfg.get("continuousSteps", 1.5))
        events: list[dict[str, Any]] = []
        marks: list[tuple[float, float, Item, str]] = []  # (t, tEnd, driving item, kind) per tone event
        active: list[tuple[float, float]] = []  # frame spans in which the stream is driven
        next_due = -math.inf
        last_beep = -math.inf
        held: tuple[Item, float] | None = None
        for i, (top, present) in enumerate(frames):
            t0 = float(times[i])
            t1 = float(times[i + 1]) if i + 1 < len(times) else t0 + last_dt
            if top is not None:
                held = (top, t0)
            elif held is not None and held[0].track_id not in present and t0 - held[1] <= hold_s:
                top = held[0]
            else:
                held = None
                continue
            active.append((t0, t1))
            kind = "proximity" if soft else collision_kind(top.clock_q, center_q)
            snd = kinds[kind]
            freq, dur = float(snd["pitchHz"]), float(snd["durationMs"]) / 1000.0
            if soft:
                interval, length = float(snd["intervalS"]), n_chirp * dur + (n_chirp - 1) * chirp_gap
            else:
                continuous = top.steps <= cont_steps
                interval = (
                    chunk if continuous else tone_interval(top.steps, by_steps) * float(snd["intervalS"]) / ref_interval
                )
                length = chunk if continuous else dur
            # a faster stream must not wait out the previous slower interval
            due = max(t0, min(next_due, last_beep + interval))
            while due < t1 - 1e-9:
                ev = {
                    "t": round(due, 4),
                    "type": "tone",
                    "kind": kind,
                    "role": "danger",
                    "trackId": top.track_id,
                    "urgency": top.urgency,
                    "pan": round(top.pan, 4),
                    "frequencyHz": round(freq, 1),
                    "durationSeconds": round(dur if soft else length, 4),
                }
                if not soft and top.steps <= cont_steps:
                    ev["continuous"] = (
                        True  # a gapless chunk: the player keeps its length whatever the profile's duration
                    )
                if soft:
                    ev["gain"] = float(prox.get("gain", 0.25))
                    ev["chirp"] = {
                        "count": n_chirp,
                        "gapSeconds": chirp_gap,
                        "attackSeconds": float(chirp.get("attackSeconds", 0.03)),
                    }
                events.append(ev)
                marks.append((due, due + length, top, kind))
                last_beep = due
                due += interval
            next_due = due
        return events, marks, active

    events, marks, busy = stream(frame_collision, "collision")
    soft_events: list[dict[str, Any]] = []
    soft_marks: list[tuple[float, float, Item, str]] = []
    if frame_proximity and prox:
        # the collision beeps win: a collision stream is active in these frame spans (held tracks included)
        soft_events, soft_marks, _ = stream(frame_proximity, "proximity")
        keep = [k for k, e in enumerate(soft_events) if not any(a - 1e-9 <= e["t"] < b + 1e-9 for a, b in busy)]
        soft_events = [soft_events[k] for k in keep]
        soft_marks = [soft_marks[k] for k in keep]
    # episodes: one per continuous stream of one track (gap < episodeGapSeconds) and kind
    episodes: list[dict[str, Any]] = []
    cw_events, cw_episodes = crosswalk_tones(
        crosswalk or [], tones_cfg.get("crosswalk") or {}, marks + soft_marks, kinds
    )

    def build(marks_: list[tuple[float, float, Item, str]]) -> None:
        cur: list[tuple[float, float, Item, str]] = []

        def flush() -> None:
            if not cur:
                return
            nearest = min(cur, key=lambda m: m[2].steps)[2]
            first = cur[0][2]
            kind = cur[0][3]
            lo, hi = max(1, int(round(nearest.steps))), max(1, int(round(first.steps)))  # noqa: RUF046
            steps_txt = f"{hi}→{lo} steps" if hi != lo else f"{lo} steps"
            head = "soft" if kind == "proximity" else f"beeps · {SIDE_WORD[kind]}"
            episodes.append(
                {
                    "t": round(cur[0][0], 4),
                    "tEnd": round(cur[-1][1], 4),
                    "type": "beeps",
                    "kind": kind,
                    "role": "danger",
                    "trackId": nearest.track_id,
                    "label": nearest.label,
                    "clock": nearest.clock,
                    "clockText": nearest.clock_text,
                    "minSteps": round(nearest.steps, 1),
                    "urgency": nearest.urgency,
                    "text": f"{head} · {nearest.label} at {nearest.clock_text} · {steps_txt}",
                }
            )

        for m in marks_:
            # a new episode when the track changes, after a gap, or where the item changes sector (the kind)
            if cur and (m[2].track_id != cur[-1][2].track_id or m[3] != cur[-1][3] or m[0] - cur[-1][1] >= gap_s):
                flush()
                cur = []
            cur.append(m)
        flush()

    build(marks)
    build(soft_marks)
    episodes.extend(cw_episodes)
    episodes.sort(key=lambda e: e["t"])
    return events + soft_events + cw_events, episodes


def crosswalk_tones(
    marks: list[tuple[float, str]], cfg: dict[str, Any], other_marks: list[tuple[Any, ...]], kinds: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Tone events + beeps-style episodes for the crosswalk enter / exit marks (see ``tone_events``): kinds
    ``crosswalk-in`` /
    ``crosswalk-out``; pitch and duration from the profile, the gap of the two ``crosswalk-out`` tones is its
    interval."""
    if not marks or not cfg:
        return [], []
    busy = sorted((m[0], m[1]) for m in other_marks)  # spans in which a collision / proximity tone sounds
    max_off = float(cfg.get("maxOffsetSeconds", 0.3))
    events: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []
    for t, what in marks:
        kind = "crosswalk-in" if what == "enter" else "crosswalk-out"
        c, snd = cfg["in" if what == "enter" else "out"], kinds[kind]
        count = int(c.get("count", 1))
        dur = float(snd["durationMs"]) / 1000.0
        gap = float(snd["intervalS"] or 0.0) if count > 1 else 0.0
        length = count * dur + (count - 1) * gap
        start = t
        for a, b in busy:  # wait out a tone we would sound over (<= maxOffsetSeconds)
            if a < start + length + 1e-9 and b > start - 1e-9:
                start = min(b + 0.02, t + max_off)
        ev = {
            "t": round(start, 4),
            "type": "tone",
            "kind": kind,
            "role": "feature",
            "urgency": "none",
            "pan": 0.0,
            "frequencyHz": round(float(snd["pitchHz"]), 1),
            "durationSeconds": round(dur, 4),
            "gain": float(c.get("gain", 0.5)),
            "chirp": {"count": count, "gapSeconds": gap, "attackSeconds": float(c.get("attackSeconds", 0.03))},
        }
        events.append(ev)
        arrow = "⇥ crosswalk in" if what == "enter" else "⇤ crosswalk out"
        episodes.append(
            {
                "t": ev["t"],
                "tEnd": round(start + length, 4),
                "type": "beeps",
                "kind": kind,
                "role": "feature",
                "urgency": "none",
                "text": f"{arrow} · {'one deep tone' if count == 1 else 'two deep tones'}",
            }
        )
    return events, episodes
