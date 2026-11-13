"""Ego signals: IMU, heading and cadence signals of the wearer."""

from __future__ import annotations

from engine.egosignals.cadence import (
    CORROBORATED_RATIO_FRAC,
    estimate_cadence,
    estimate_stationary,
    hold_last,
    peak,
    refine,
    spectrum,
    window_cadence,
)

__all__ = [
    "CORROBORATED_RATIO_FRAC",
    "estimate_cadence",
    "estimate_stationary",
    "hold_last",
    "peak",
    "refine",
    "spectrum",
    "window_cadence",
]
