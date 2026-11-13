# engine.gait

Gait model: the metric scale of the pinhole geometry, calibrated against walking (step cadence) and the GPS.
Module `scale.py`; imports only numpy and the stdlib.

## Public API
- `Scale(cfg, prior_step_m)` (legacy `collision._Scale`): `update(t, cadence, raw_speed, dt)`, property `value`
  (the applied scale), attributes `k` (target, None until the first estimate), `applied`, `from_gait`, `samples`.
- `GpsSpeedScale(cfg)` (legacy `collision.GpsSpeedScale`): `update(t, gps_speed, model_speed) -> k`.

## Inputs / outputs
- `Scale.update`: time `t` (s), cadence (Hz) or None, raw ego speed (m/s) or None, frame `dt`. Output: `value`, the
  scale k slewed in log space towards the target at most `max_rate` per second.
- `GpsSpeedScale.update`: GPS 2D speed and model speed (m/s) or None. Returns k (1 until the samples span `speedMinS`).

## Config keys read
- `Scale` (ego config): `calibrationWindowSeconds` (20), `calibrationMinSamples` (18), `calibrationEmaMinSeconds` (3),
  `calibrationEmaSeconds` (40), `scaleRange` ([0.5, 4.0]), `calibrationMinRawSpeed` (0.2),
  `scaleMaxChangePerSecond` (0.25), `scalePrior` (null), `scalePriorSeconds` (30).
- `GpsSpeedScale` (`ego.gps.speedScale`): `speedMinS` (20), `speedWindowS` (60), `speedTauS` (40), `speedMinScale` (0.5),
  `speedMaxScale` (1.6).

## Invariants
- k = median(cadence) * prior step length / median(raw ego speed) over the window; a cold start estimates as soon as
  `calibrationMinSamples` exist; later estimates blend in with a time constant growing from the min to the max.
- Without cadence nothing is added and k is held; before the first estimate k is 1. Estimates below
  `calibrationMinRawSpeed` are ignored.
- Walking is the ruler: camera height / field-of-view errors cancel in the ratio. Distances, laterals and areas are
  multiplied by k (equivalently the camera height is H * k); the raw closing speeds used for k stay uncalibrated, so
  there is no feedback loop.
- The GPS scale needs >= 10 samples of moving frames (both speeds > 0.3 m/s) spanning >= `speedMinS`; k is clipped to
  the scale range; `speedTauS` 0 jumps to the target (v26.2.11).
- Attribute names and definition order are pinned by tests (`vars()` lists).
