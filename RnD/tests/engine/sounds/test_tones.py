"""Characterisation tests for engine.sounds.tones (v26.3.0 p3-14): sound kinds, profile, tone events, crosswalk tones.

Every literal below was printed by the legacy ``collision`` functions (``resolve_sounds``, ``_tone_interval``,
``_tone_events``, ``_crosswalk_tones``, ``collision_kind``) in the hackeye-rnd image before the move, by feeding them
the inputs built by the ``_*`` helpers of this file (the shapes of the existing ``_tone_events`` tests). The engine
modules are imported inside each test.
"""

from __future__ import annotations

import types
from typing import Any

import numpy as np
import pytest

import collision

FPS = 10.0
TONES: dict[str, Any] = collision.load_config()["tones"]


def _item(track: int, steps: float, quarter: int = 0, urgency: str = "danger", label: str = "person") -> Any:
    clock_text = {-5: "10:15", 0: "12", 3: "12:45"}.get(quarter, "12")
    return types.SimpleNamespace(
        track_id=track,
        steps=steps,
        clock_q=quarter,
        urgency=urgency,
        pan=0.0,
        label=label,
        clock=12,
        clock_text=clock_text,
    )


def _beeps(n: int, quarter_of: Any, steps: float = 3.0) -> tuple[Any, list[Any]]:
    times = np.arange(n) / FPS
    coll = [(_item(9, steps, quarter_of(i)), {9}) for i in range(n)]
    return times, coll


def _soft(n: int, steps_of: Any, coll_of: Any = None) -> tuple[Any, list[Any], list[Any]]:
    times = np.arange(n) / FPS
    soft: list[Any] = []
    coll: list[Any] = []
    for i in range(n):
        soft.append((_item(7, steps_of(i), urgency="none"), {7, 9}))
        on = bool(coll_of and coll_of(i))
        coll.append((_item(9, 3.0) if on else None, {7, 9}))
    return times, coll, soft


def _cases() -> dict[str, tuple[Any, ...]]:
    """name -> positional args of ``tone_events``."""
    right = {"collision-right": {"pitchHz": 1500, "durationMs": 120, "intervalS": 1.0}}
    sounds = collision.resolve_sounds(TONES, {"kinds": right})
    out: dict[str, tuple[Any, ...]] = {}
    t, c = _beeps(30, lambda i: -5)
    out["left"] = (c, t, TONES, None, None)
    t, c = _beeps(60, lambda i: -3 if i < 20 else 0 if i < 40 else 2)
    out["sector_change"] = (c, t, TONES, None, None)
    t, c = _beeps(20, lambda i: 0, steps=1.0)
    out["continuous"] = (c, t, TONES, None, None)
    t, c = _beeps(30, lambda i: 3)
    out["profile_right"] = (c, t, TONES, None, None, sounds)
    t, c, s = _soft(60, lambda i: 4.0 - i * 0.03)
    out["soft"] = (c, t, TONES, s)
    t, c, s = _soft(80, lambda i: 4.0, lambda i: 10 <= i < 30)
    out["soft_vs_collision"] = (c, t, TONES, s)
    t, c, s = _soft(80, lambda i: 4.0)
    slow = collision.resolve_sounds(TONES, {"kinds": {"proximity": {"intervalS": 2.4, "pitchHz": 500}}})
    out["soft_crosswalk"] = (c, t, TONES, s, [(2.0, "enter"), (8.0, "exit")], slow)
    t, c = _beeps(30, lambda i: 0, steps=4.0)
    out["crosswalk_busy"] = (c, t, TONES, None, [(0.5, "enter"), (2.0, "exit")])
    out["empty"] = ([(None, set())] * 5, np.arange(5) / FPS, TONES)
    return out


def _runs(items: list[str]) -> list[list[Any]]:
    out: list[list[Any]] = []
    for x in items:
        if out and out[-1][0] == x:
            out[-1][1] += 1
        else:
            out.append([x, 1])
    return out


def _summary(prof: dict[str, Any]) -> dict[str, Any]:
    kinds = {k: [v["pitchHz"], v["durationMs"], v["intervalS"]] for k, v in prof["kinds"].items()}
    return {"kinds": kinds, "speechRate": prof["speechRate"]}


def _digest(tn: list[dict[str, Any]], eps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n": len(tn),
        "first": tn[0] if tn else None,
        "last": tn[-1] if tn else None,
        "kinds": _runs([e["kind"] for e in tn]),
        "ts": [e["t"] for e in tn],
        "eps": eps,
    }


def _crosswalk_args() -> list[tuple[Any, ...]]:
    kinds = collision.resolve_sounds(TONES)["kinds"]
    cfg = TONES["crosswalk"]
    return [
        ([(10.0, "enter"), (20.0, "exit")], cfg, [], kinds),
        ([(10.0, "enter")], cfg, [(10.0, 10.08, None), (10.2, 10.28, None)], kinds),
        ([(10.0, "enter")], cfg, [(9.0, 12.0, None)], kinds),
        ([(10.0, "exit")], cfg, [(11.0, 11.08, None)], kinds),
        ([], cfg, [], kinds),
        ([(1.0, "enter")], {}, [], kinds),
    ]


PROFILES: list[dict[str, Any] | None] = [
    None,
    {},
    {
        "kinds": {
            "collision-left": {"pitchHz": 99999, "durationMs": "x", "intervalS": 0.0001},
            "crosswalk-in": {"intervalS": 3.0},
            "bogus": {"pitchHz": 1},
        },
        "speechRate": 7,
    },
    {"speechRate": 0.1},
    {"kinds": {"proximity": {"pitchHz": 500, "durationMs": True, "intervalS": float("nan")}, "crosswalk-out": "x"}},
]
BY = [[2, 0.12], [3, 0.25, 9], [4, 0.375], [5, 0.5], [8, 0.5]]
STEPS = [8, 5, 4, 3, 2.5, 0.2, 4.5, 6.0]


# Printed by the legacy functions (see the module docstring).
DEFAULT_LABELS = {
    "collision-left": "Collision left (9:00-11:30)",
    "collision-center": "Collision center (11:45-12:15)",
    "collision-right": "Collision right (12:30-3:00)",
    "crosswalk-in": "Crosswalk in",
    "crosswalk-out": "Crosswalk out",
    "proximity": "Person approaching (soft)",
}
PROFILE_SUMMARY = [
    {
        "kinds": {
            "collision-left": [660, 80, 0.5],
            "collision-center": [880, 80, 0.5],
            "collision-right": [1100, 80, 0.5],
            "crosswalk-in": [330, 600, None],
            "crosswalk-out": [330, 200, 0.12],
            "proximity": [440, 120, 1.2],
        },
        "speechRate": 1.25,
    },
    {
        "kinds": {
            "collision-left": [660, 80, 0.5],
            "collision-center": [880, 80, 0.5],
            "collision-right": [1100, 80, 0.5],
            "crosswalk-in": [330, 600, None],
            "crosswalk-out": [330, 200, 0.12],
            "proximity": [440, 120, 1.2],
        },
        "speechRate": 1.25,
    },
    {
        "kinds": {
            "collision-left": [2000, 80, 0.05],
            "collision-center": [880, 80, 0.5],
            "collision-right": [1100, 80, 0.5],
            "crosswalk-in": [330, 600, None],
            "crosswalk-out": [330, 200, 0.12],
            "proximity": [440, 120, 1.2],
        },
        "speechRate": 2.0,
    },
    {
        "kinds": {
            "collision-left": [660, 80, 0.5],
            "collision-center": [880, 80, 0.5],
            "collision-right": [1100, 80, 0.5],
            "crosswalk-in": [330, 600, None],
            "crosswalk-out": [330, 200, 0.12],
            "proximity": [440, 120, 1.2],
        },
        "speechRate": 0.5,
    },
    {
        "kinds": {
            "collision-left": [660, 80, 0.5],
            "collision-center": [880, 80, 0.5],
            "collision-right": [1100, 80, 0.5],
            "crosswalk-in": [330, 600, None],
            "crosswalk-out": [330, 200, 0.12],
            "proximity": [500.0, 120, 1.2],
        },
        "speechRate": 1.25,
    },
]
INTERVALS = [[0.5, 0.5, 0.375, 0.25, 0.185, 0.12, 0.4375, 0.5], [0.5, 0.5, 0.375, 0.25, 0.185, 0.12, 0.4375, 0.5]]
KINDS_Q1 = [
    "collision-left",
    "collision-left",
    "collision-left",
    "collision-left",
    "collision-left",
    "collision-left",
    "collision-left",
    "collision-left",
    "collision-left",
    "collision-left",
    "collision-left",
    "collision-center",
    "collision-center",
    "collision-center",
    "collision-right",
    "collision-right",
    "collision-right",
    "collision-right",
    "collision-right",
    "collision-right",
    "collision-right",
    "collision-right",
    "collision-right",
    "collision-right",
    "collision-right",
]
KINDS_Q2 = [
    "collision-left",
    "collision-left",
    "collision-center",
    "collision-center",
    "collision-center",
    "collision-center",
    "collision-center",
    "collision-right",
    "collision-right",
]
CONSTS = (
    ("collision-left", "collision-center", "collision-right"),
    ("collision-left", "collision-center", "collision-right", "crosswalk-in", "crosswalk-out", "proximity"),
    {"collision-left": "left", "collision-center": "center", "collision-right": "right"},
)
EVENTS = {
    "left": {
        "n": 12,
        "first": {
            "t": 0.0,
            "type": "tone",
            "kind": "collision-left",
            "role": "danger",
            "trackId": 9,
            "urgency": "danger",
            "pan": 0.0,
            "frequencyHz": 660.0,
            "durationSeconds": 0.08,
        },
        "last": {
            "t": 2.75,
            "type": "tone",
            "kind": "collision-left",
            "role": "danger",
            "trackId": 9,
            "urgency": "danger",
            "pan": 0.0,
            "frequencyHz": 660.0,
            "durationSeconds": 0.08,
        },
        "kinds": [["collision-left", 12]],
        "ts": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75],
        "eps": [
            {
                "t": 0.0,
                "tEnd": 2.83,
                "type": "beeps",
                "kind": "collision-left",
                "role": "danger",
                "trackId": 9,
                "label": "person",
                "clock": 12,
                "clockText": "10:15",
                "minSteps": 3.0,
                "urgency": "danger",
                "text": "beeps · left · person at 10:15 · 3 steps",
            }
        ],
    },
    "sector_change": {
        "n": 24,
        "first": {
            "t": 0.0,
            "type": "tone",
            "kind": "collision-left",
            "role": "danger",
            "trackId": 9,
            "urgency": "danger",
            "pan": 0.0,
            "frequencyHz": 660.0,
            "durationSeconds": 0.08,
        },
        "last": {
            "t": 5.75,
            "type": "tone",
            "kind": "collision-right",
            "role": "danger",
            "trackId": 9,
            "urgency": "danger",
            "pan": 0.0,
            "frequencyHz": 1100.0,
            "durationSeconds": 0.08,
        },
        "kinds": [["collision-left", 8], ["collision-center", 8], ["collision-right", 8]],
        "ts": [
            0.0,
            0.25,
            0.5,
            0.75,
            1.0,
            1.25,
            1.5,
            1.75,
            2.0,
            2.25,
            2.5,
            2.75,
            3.0,
            3.25,
            3.5,
            3.75,
            4.0,
            4.25,
            4.5,
            4.75,
            5.0,
            5.25,
            5.5,
            5.75,
        ],
        "eps": [
            {
                "t": 0.0,
                "tEnd": 1.83,
                "type": "beeps",
                "kind": "collision-left",
                "role": "danger",
                "trackId": 9,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 3.0,
                "urgency": "danger",
                "text": "beeps · left · person at 12 · 3 steps",
            },
            {
                "t": 2.0,
                "tEnd": 3.83,
                "type": "beeps",
                "kind": "collision-center",
                "role": "danger",
                "trackId": 9,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 3.0,
                "urgency": "danger",
                "text": "beeps · center · person at 12 · 3 steps",
            },
            {
                "t": 4.0,
                "tEnd": 5.83,
                "type": "beeps",
                "kind": "collision-right",
                "role": "danger",
                "trackId": 9,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 3.0,
                "urgency": "danger",
                "text": "beeps · right · person at 12 · 3 steps",
            },
        ],
    },
    "continuous": {
        "n": 8,
        "first": {
            "t": 0.0,
            "type": "tone",
            "kind": "collision-center",
            "role": "danger",
            "trackId": 9,
            "urgency": "danger",
            "pan": 0.0,
            "frequencyHz": 880.0,
            "durationSeconds": 0.25,
            "continuous": True,
        },
        "last": {
            "t": 1.75,
            "type": "tone",
            "kind": "collision-center",
            "role": "danger",
            "trackId": 9,
            "urgency": "danger",
            "pan": 0.0,
            "frequencyHz": 880.0,
            "durationSeconds": 0.25,
            "continuous": True,
        },
        "kinds": [["collision-center", 8]],
        "ts": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75],
        "eps": [
            {
                "t": 0.0,
                "tEnd": 2.0,
                "type": "beeps",
                "kind": "collision-center",
                "role": "danger",
                "trackId": 9,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 1.0,
                "urgency": "danger",
                "text": "beeps · center · person at 12 · 1 steps",
            }
        ],
    },
    "profile_right": {
        "n": 6,
        "first": {
            "t": 0.0,
            "type": "tone",
            "kind": "collision-right",
            "role": "danger",
            "trackId": 9,
            "urgency": "danger",
            "pan": 0.0,
            "frequencyHz": 1500.0,
            "durationSeconds": 0.12,
        },
        "last": {
            "t": 2.5,
            "type": "tone",
            "kind": "collision-right",
            "role": "danger",
            "trackId": 9,
            "urgency": "danger",
            "pan": 0.0,
            "frequencyHz": 1500.0,
            "durationSeconds": 0.12,
        },
        "kinds": [["collision-right", 6]],
        "ts": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
        "eps": [
            {
                "t": 0.0,
                "tEnd": 2.62,
                "type": "beeps",
                "kind": "collision-right",
                "role": "danger",
                "trackId": 9,
                "label": "person",
                "clock": 12,
                "clockText": "12:45",
                "minSteps": 3.0,
                "urgency": "danger",
                "text": "beeps · right · person at 12:45 · 3 steps",
            }
        ],
    },
    "soft": {
        "n": 5,
        "first": {
            "t": 0.0,
            "type": "tone",
            "kind": "proximity",
            "role": "danger",
            "trackId": 7,
            "urgency": "none",
            "pan": 0.0,
            "frequencyHz": 440.0,
            "durationSeconds": 0.12,
            "gain": 0.25,
            "chirp": {"count": 2, "gapSeconds": 0.1, "attackSeconds": 0.04},
        },
        "last": {
            "t": 4.8,
            "type": "tone",
            "kind": "proximity",
            "role": "danger",
            "trackId": 7,
            "urgency": "none",
            "pan": 0.0,
            "frequencyHz": 440.0,
            "durationSeconds": 0.12,
            "gain": 0.25,
            "chirp": {"count": 2, "gapSeconds": 0.1, "attackSeconds": 0.04},
        },
        "kinds": [["proximity", 5]],
        "ts": [0.0, 1.2, 2.4, 3.6, 4.8],
        "eps": [
            {
                "t": 0.0,
                "tEnd": 5.14,
                "type": "beeps",
                "kind": "proximity",
                "role": "danger",
                "trackId": 7,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 2.6,
                "urgency": "none",
                "text": "soft · person at 12 · 4→3 steps",
            }
        ],
    },
    "soft_vs_collision": {
        "n": 13,
        "first": {
            "t": 1.0,
            "type": "tone",
            "kind": "collision-center",
            "role": "danger",
            "trackId": 9,
            "urgency": "danger",
            "pan": 0.0,
            "frequencyHz": 880.0,
            "durationSeconds": 0.08,
        },
        "last": {
            "t": 7.2,
            "type": "tone",
            "kind": "proximity",
            "role": "danger",
            "trackId": 7,
            "urgency": "none",
            "pan": 0.0,
            "frequencyHz": 440.0,
            "durationSeconds": 0.12,
            "gain": 0.25,
            "chirp": {"count": 2, "gapSeconds": 0.1, "attackSeconds": 0.04},
        },
        "kinds": [["collision-center", 8], ["proximity", 5]],
        "ts": [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 0.0, 3.6, 4.8, 6.0, 7.2],
        "eps": [
            {
                "t": 0.0,
                "tEnd": 0.34,
                "type": "beeps",
                "kind": "proximity",
                "role": "danger",
                "trackId": 7,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 4.0,
                "urgency": "none",
                "text": "soft · person at 12 · 4 steps",
            },
            {
                "t": 1.0,
                "tEnd": 2.83,
                "type": "beeps",
                "kind": "collision-center",
                "role": "danger",
                "trackId": 9,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 3.0,
                "urgency": "danger",
                "text": "beeps · center · person at 12 · 3 steps",
            },
            {
                "t": 3.6,
                "tEnd": 7.54,
                "type": "beeps",
                "kind": "proximity",
                "role": "danger",
                "trackId": 7,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 4.0,
                "urgency": "none",
                "text": "soft · person at 12 · 4 steps",
            },
        ],
    },
    "soft_crosswalk": {
        "n": 6,
        "first": {
            "t": 0.0,
            "type": "tone",
            "kind": "proximity",
            "role": "danger",
            "trackId": 7,
            "urgency": "none",
            "pan": 0.0,
            "frequencyHz": 500.0,
            "durationSeconds": 0.12,
            "gain": 0.25,
            "chirp": {"count": 2, "gapSeconds": 0.1, "attackSeconds": 0.04},
        },
        "last": {
            "t": 8.0,
            "type": "tone",
            "kind": "crosswalk-out",
            "role": "feature",
            "urgency": "none",
            "pan": 0.0,
            "frequencyHz": 330.0,
            "durationSeconds": 0.2,
            "gain": 0.5,
            "chirp": {"count": 2, "gapSeconds": 0.12, "attackSeconds": 0.02},
        },
        "kinds": [["proximity", 4], ["crosswalk-in", 1], ["crosswalk-out", 1]],
        "ts": [0.0, 2.4, 4.8, 7.2, 2.3, 8.0],
        "eps": [
            {
                "t": 0.0,
                "tEnd": 0.34,
                "type": "beeps",
                "kind": "proximity",
                "role": "danger",
                "trackId": 7,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 4.0,
                "urgency": "none",
                "text": "soft · person at 12 · 4 steps",
            },
            {
                "t": 2.3,
                "tEnd": 2.9,
                "type": "beeps",
                "kind": "crosswalk-in",
                "role": "feature",
                "urgency": "none",
                "text": "⇥ crosswalk in · one deep tone",
            },
            {
                "t": 2.4,
                "tEnd": 2.74,
                "type": "beeps",
                "kind": "proximity",
                "role": "danger",
                "trackId": 7,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 4.0,
                "urgency": "none",
                "text": "soft · person at 12 · 4 steps",
            },
            {
                "t": 4.8,
                "tEnd": 5.14,
                "type": "beeps",
                "kind": "proximity",
                "role": "danger",
                "trackId": 7,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 4.0,
                "urgency": "none",
                "text": "soft · person at 12 · 4 steps",
            },
            {
                "t": 7.2,
                "tEnd": 7.54,
                "type": "beeps",
                "kind": "proximity",
                "role": "danger",
                "trackId": 7,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 4.0,
                "urgency": "none",
                "text": "soft · person at 12 · 4 steps",
            },
            {
                "t": 8.0,
                "tEnd": 8.52,
                "type": "beeps",
                "kind": "crosswalk-out",
                "role": "feature",
                "urgency": "none",
                "text": "⇤ crosswalk out · two deep tones",
            },
        ],
    },
    "crosswalk_busy": {
        "n": 10,
        "first": {
            "t": 0.0,
            "type": "tone",
            "kind": "collision-center",
            "role": "danger",
            "trackId": 9,
            "urgency": "danger",
            "pan": 0.0,
            "frequencyHz": 880.0,
            "durationSeconds": 0.08,
        },
        "last": {
            "t": 2.3,
            "type": "tone",
            "kind": "crosswalk-out",
            "role": "feature",
            "urgency": "none",
            "pan": 0.0,
            "frequencyHz": 330.0,
            "durationSeconds": 0.2,
            "gain": 0.5,
            "chirp": {"count": 2, "gapSeconds": 0.12, "attackSeconds": 0.02},
        },
        "kinds": [["collision-center", 8], ["crosswalk-in", 1], ["crosswalk-out", 1]],
        "ts": [0.0, 0.375, 0.75, 1.125, 1.5, 1.875, 2.25, 2.625, 0.8, 2.3],
        "eps": [
            {
                "t": 0.0,
                "tEnd": 2.705,
                "type": "beeps",
                "kind": "collision-center",
                "role": "danger",
                "trackId": 9,
                "label": "person",
                "clock": 12,
                "clockText": "12",
                "minSteps": 4.0,
                "urgency": "danger",
                "text": "beeps · center · person at 12 · 4 steps",
            },
            {
                "t": 0.8,
                "tEnd": 1.4,
                "type": "beeps",
                "kind": "crosswalk-in",
                "role": "feature",
                "urgency": "none",
                "text": "⇥ crosswalk in · one deep tone",
            },
            {
                "t": 2.3,
                "tEnd": 2.82,
                "type": "beeps",
                "kind": "crosswalk-out",
                "role": "feature",
                "urgency": "none",
                "text": "⇤ crosswalk out · two deep tones",
            },
        ],
    },
    "empty": {"n": 0, "first": None, "last": None, "kinds": [], "ts": [], "eps": []},
}
CROSSWALK = [
    (
        [
            {
                "t": 10.0,
                "type": "tone",
                "kind": "crosswalk-in",
                "role": "feature",
                "urgency": "none",
                "pan": 0.0,
                "frequencyHz": 330.0,
                "durationSeconds": 0.6,
                "gain": 0.5,
                "chirp": {"count": 1, "gapSeconds": 0.0, "attackSeconds": 0.03},
            },
            {
                "t": 20.0,
                "type": "tone",
                "kind": "crosswalk-out",
                "role": "feature",
                "urgency": "none",
                "pan": 0.0,
                "frequencyHz": 330.0,
                "durationSeconds": 0.2,
                "gain": 0.5,
                "chirp": {"count": 2, "gapSeconds": 0.12, "attackSeconds": 0.02},
            },
        ],
        [
            {
                "t": 10.0,
                "tEnd": 10.6,
                "type": "beeps",
                "kind": "crosswalk-in",
                "role": "feature",
                "urgency": "none",
                "text": "⇥ crosswalk in · one deep tone",
            },
            {
                "t": 20.0,
                "tEnd": 20.52,
                "type": "beeps",
                "kind": "crosswalk-out",
                "role": "feature",
                "urgency": "none",
                "text": "⇤ crosswalk out · two deep tones",
            },
        ],
    ),
    (
        [
            {
                "t": 10.3,
                "type": "tone",
                "kind": "crosswalk-in",
                "role": "feature",
                "urgency": "none",
                "pan": 0.0,
                "frequencyHz": 330.0,
                "durationSeconds": 0.6,
                "gain": 0.5,
                "chirp": {"count": 1, "gapSeconds": 0.0, "attackSeconds": 0.03},
            }
        ],
        [
            {
                "t": 10.3,
                "tEnd": 10.9,
                "type": "beeps",
                "kind": "crosswalk-in",
                "role": "feature",
                "urgency": "none",
                "text": "⇥ crosswalk in · one deep tone",
            }
        ],
    ),
    (
        [
            {
                "t": 10.3,
                "type": "tone",
                "kind": "crosswalk-in",
                "role": "feature",
                "urgency": "none",
                "pan": 0.0,
                "frequencyHz": 330.0,
                "durationSeconds": 0.6,
                "gain": 0.5,
                "chirp": {"count": 1, "gapSeconds": 0.0, "attackSeconds": 0.03},
            }
        ],
        [
            {
                "t": 10.3,
                "tEnd": 10.9,
                "type": "beeps",
                "kind": "crosswalk-in",
                "role": "feature",
                "urgency": "none",
                "text": "⇥ crosswalk in · one deep tone",
            }
        ],
    ),
    (
        [
            {
                "t": 10.0,
                "type": "tone",
                "kind": "crosswalk-out",
                "role": "feature",
                "urgency": "none",
                "pan": 0.0,
                "frequencyHz": 330.0,
                "durationSeconds": 0.2,
                "gain": 0.5,
                "chirp": {"count": 2, "gapSeconds": 0.12, "attackSeconds": 0.02},
            }
        ],
        [
            {
                "t": 10.0,
                "tEnd": 10.52,
                "type": "beeps",
                "kind": "crosswalk-out",
                "role": "feature",
                "urgency": "none",
                "text": "⇤ crosswalk out · two deep tones",
            }
        ],
    ),
    ([], []),
    ([], []),
]


def test_facade_identity() -> None:
    from engine.sounds import tones

    assert collision.COLLISION_KINDS is tones.COLLISION_KINDS
    assert collision.SOUND_KINDS is tones.SOUND_KINDS
    assert collision.SIDE_WORD is tones.SIDE_WORD
    assert collision.collision_kind is tones.collision_kind
    assert collision.resolve_sounds is tones.resolve_sounds
    assert collision._tone_interval is tones.tone_interval
    assert collision._tone_events is tones.tone_events
    assert collision._crosswalk_tones is tones.crosswalk_tones


def test_constants() -> None:
    from engine.sounds import tones

    assert (tones.COLLISION_KINDS, tones.SOUND_KINDS, tones.SIDE_WORD) == CONSTS


def test_collision_kind_table() -> None:
    from engine.sounds.tones import collision_kind

    assert [collision_kind(q) for q in range(-12, 13)] == KINDS_Q1
    assert [collision_kind(q, 2) for q in range(-4, 5)] == KINDS_Q2


def test_resolve_sounds_with_and_without_a_profile() -> None:
    from engine.sounds.tones import resolve_sounds

    default = resolve_sounds(TONES)
    assert {k: v["label"] for k, v in default["kinds"].items()} == DEFAULT_LABELS
    assert [_summary(resolve_sounds(TONES, p)) for p in PROFILES] == PROFILE_SUMMARY
    assert resolve_sounds(TONES, None) == resolve_sounds(TONES, {})
    assert resolve_sounds(TONES) is not resolve_sounds(TONES)
    assert TONES["sounds"]["collision-left"]["pitchHz"] == 660  # the defaults are copied, never mutated


def test_tone_interval_table() -> None:
    from engine.sounds.tones import tone_interval

    assert [tone_interval(s, BY) for s in STEPS] == pytest.approx(INTERVALS[0], rel=1e-12, abs=1e-12)
    assert [tone_interval(s, TONES["bySteps"]) for s in STEPS] == pytest.approx(INTERVALS[1], rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("name", list(EVENTS))
def test_tone_events_digest(name: str) -> None:
    from engine.sounds.tones import tone_events

    tn, eps = tone_events(*_cases()[name])
    assert _digest(tn, eps) == EVENTS[name]


@pytest.mark.parametrize("i", range(len(CROSSWALK)))
def test_crosswalk_tones(i: int) -> None:
    from engine.sounds.tones import crosswalk_tones

    assert crosswalk_tones(*_crosswalk_args()[i]) == CROSSWALK[i]
