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
from engine.egosignals.imu import (
    crop,
    default_imu_cfg,
    estimate_bias,
    gps_course_offset,
    gps_good,
    gps_step_length,
    gps_xy,
    gravity_angles,
    gravity_unit,
    heading_series,
    motion_energy,
    smooth,
    spans,
    vertical_signals,
    wrap_deg,
    yaw_rate,
)

__all__ = [
    "CORROBORATED_RATIO_FRAC",
    "crop",
    "default_imu_cfg",
    "estimate_bias",
    "estimate_cadence",
    "estimate_stationary",
    "gps_course_offset",
    "gps_good",
    "gps_step_length",
    "gps_xy",
    "gravity_angles",
    "gravity_unit",
    "heading_series",
    "hold_last",
    "motion_energy",
    "peak",
    "refine",
    "smooth",
    "spans",
    "spectrum",
    "vertical_signals",
    "window_cadence",
    "wrap_deg",
    "yaw_rate",
]
