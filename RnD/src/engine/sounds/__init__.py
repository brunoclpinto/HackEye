"""Sounds model: beeps and audio cues."""

from __future__ import annotations

from engine.sounds import tones
from engine.sounds.tones import (
    COLLISION_KINDS,
    SIDE_WORD,
    SOUND_KINDS,
    collision_kind,
    crosswalk_tones,
    resolve_sounds,
    tone_events,
    tone_interval,
)

__all__ = [
    "COLLISION_KINDS",
    "SIDE_WORD",
    "SOUND_KINDS",
    "collision_kind",
    "crosswalk_tones",
    "resolve_sounds",
    "tone_events",
    "tone_interval",
    "tones",
]
