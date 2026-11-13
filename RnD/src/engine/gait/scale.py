"""Gait scale: metric-scale calibration from step cadence (Scale) and GPS speed (GpsSpeedScale)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = ["GpsSpeedScale", "Scale"]


class Scale:
    """Gait calibration of the metric scale (CONTRACTS.md section 14.1.1).

    ``k = median(cadence) * priorStepLengthM / median(raw ego speed)`` over the last
    ``calibrationWindowSeconds`` of frames where both are known. Walking is the ruler: whatever
    camera height / field of view error makes the raw metres wrong, the ratio absorbs it. The first
    estimate is taken as soon as ``calibrationMinSamples`` frames exist (a cold start must not wait
    20 s); later estimates are blended in with a slow, evidence-growing time constant. Without cadence (standing still)
    nothing is added, so the last k is held; before the first estimate k is 1.
    """

    def __init__(self, cfg: dict[str, Any], prior_step_m: float) -> None:
        self.window_s = float(cfg.get("calibrationWindowSeconds", 20.0))
        self.min_samples = int(cfg.get("calibrationMinSamples", 18))
        self.tau_min_s = float(cfg.get("calibrationEmaMinSeconds", 3.0))
        self.tau_s = float(cfg.get("calibrationEmaSeconds", 40.0))
        self.age_s = 0.0  # seconds of estimates blended so far
        self.lo, self.hi = cfg.get("scaleRange", [0.5, 4.0])
        self.min_raw = float(cfg.get("calibrationMinRawSpeed", 0.2))
        self.prior_step_m = prior_step_m
        self.samples: list[tuple[float, float, float]] = []  # (t, cadence Hz, raw speed m/s)
        self.k: float | None = None  # the measured target (None until the first estimate)
        self.applied = 1.0  # what the geometry uses: k slewed towards the target
        self.max_rate = float(cfg.get("scaleMaxChangePerSecond", 0.25))
        self.from_gait = False
        prior = cfg.get("scalePrior")
        if prior:  # optional warm start (null = k 1 until measured)
            self.k = self.applied = float(prior)
            self.age_s = float(cfg.get("scalePriorSeconds", 30.0))

    def update(self, t: float, cadence: float | None, raw_speed: float | None, dt: float) -> None:
        if cadence is not None and cadence > 0 and raw_speed is not None and raw_speed > 0:
            self.samples.append((t, cadence, raw_speed))
        self.samples = [x for x in self.samples if x[0] >= t - self.window_s - 1e-9]
        self._estimate(dt)
        if self.k is not None and self.applied != self.k:
            # steps are distance / step length, so a sudden change of k would make every step count jump:
            # the applied scale moves towards the target at most ``scaleMaxChangePerSecond`` (25 percent/s)
            lim = self.max_rate * max(dt, 0.0)
            self.applied = math.exp(
                math.log(self.applied) + max(-lim, min(lim, math.log(self.k) - math.log(self.applied)))
            )

    def _estimate(self, dt: float) -> None:
        if len(self.samples) < self.min_samples:
            return
        v = float(np.median([x[2] for x in self.samples]))
        if v < self.min_raw:
            return
        k_inst = min(self.hi, max(self.lo, float(np.median([x[1] for x in self.samples])) * self.prior_step_m / v))
        if self.k is None:
            self.k = k_inst
            self.from_gait = True
        else:
            self.from_gait = True
            # slow smoothing, but a young estimate (a cold start) may still move quickly: the time
            # constant grows with the evidence, from ``calibrationEmaMinSeconds`` to ``calibrationEmaSeconds``
            self.age_s += max(dt, 0.0)
            tau = min(self.tau_s, max(self.tau_min_s, self.age_s))
            a = 1.0 - math.exp(-max(dt, 0.0) / tau)
            self.k = math.exp(math.log(self.k) + a * (math.log(k_inst) - math.log(self.k)))

    @property
    def value(self) -> float:
        return self.applied


class GpsSpeedScale:
    """v26.2.11 (``ego.gps.speedScale``): the step length pulled toward what the GPS says. Samples (GPS 2D speed,
    cadence x prior step length) of moving frames with a good fix; once they span >= ``speedMinS`` the ratio of their
    medians (over the last ``speedWindowS``) is the target scale k, followed with the time constant ``speedTauS``.
    k stays 1 until then and is clipped to [``speedMinScale``, ``speedMaxScale``]."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.min_s = float(cfg.get("speedMinS", 20.0))
        self.win_s = float(cfg.get("speedWindowS", 60.0))
        self.tau = float(cfg.get("speedTauS", 40.0))
        self.lo, self.hi = float(cfg.get("speedMinScale", 0.5)), float(cfg.get("speedMaxScale", 1.6))
        self.k = 1.0
        self.samples: list[tuple[float, float, float]] = []
        self.prev_t: float | None = None

    def update(self, t: float, gps_speed: float | None, model_speed: float | None) -> float:
        dt = 0.0 if self.prev_t is None else max(0.0, t - self.prev_t)
        self.prev_t = t
        if gps_speed is not None and model_speed is not None and gps_speed > 0.3 and model_speed > 0.3:
            self.samples.append((t, gps_speed, model_speed))
        while self.samples and t - self.samples[0][0] > self.win_s:
            self.samples.pop(0)
        if len(self.samples) >= 10 and self.samples[-1][0] - self.samples[0][0] >= self.min_s:
            target = float(np.median([a for _, a, _ in self.samples]) / np.median([b for _, _, b in self.samples]))
            target = min(self.hi, max(self.lo, target))
            self.k += (1.0 - math.exp(-dt / self.tau)) * (target - self.k) if self.tau > 0 else target - self.k
        return self.k
