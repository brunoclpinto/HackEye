# engine.gait

Gait model: the metric scale of the pinhole geometry, calibrated against walking (step cadence) and the GPS.
Module `scale.py`; imports only numpy and the stdlib.

**Fields written:** none (`Item` / `Track` fields, `engine.core.types.FIELD_WRITERS`).

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

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.3 Geometry and the gait-calibrated scale

- Pinhole flat-ground model: a ground point `dy` rows below the horizon is `H·f/dy` metres away; lateral = `(x − 0.5)·W·d/f`. `H` is the camera height times the scale `k` below, so **all distances, laterals, areas and closing speeds are real-world metres**.
- **Scale `k`** (class `_Scale`): over the last `calibrationWindowSeconds`, `k = median(cadence) × priorStepLengthM / median(raw ego speed)` for frames where both are known (raw speed ≥ `calibrationMinRawSpeed`; at least `calibrationMinSamples` frames; clamped to `scaleRange`). The first estimate is taken at once; later ones are blended in (log scale) with a time constant that grows from `calibrationEmaMinSeconds` to `calibrationEmaSeconds`. The **applied** scale slews toward the measured one at ≤ `scaleMaxChangePerSecond` (so step counts don't jump). Frames without cadence add nothing, so the last scale is held when standing still; until the first estimate `k = 1` (or `scalePrior`).
- The raw closing speeds that feed the calibration stay uncalibrated, so there is no feedback loop.
- **Per-recording `stepLengthM`** replaces `priorStepLengthM` for the calibration and for steps.


### 7.11d v26.2.12 collision rules — step length from the GPS

- **Step length from the GPS** (`ego.stepLength`: `source` `auto` | `prior`, `minS` 60, `rangeM` [0.5, 1.1], `minCadenceHz` 1.0, `minSpeedMps` 0.5): with sensors and a GPS fix (`ego.gps.minFix` / `maxDop`: good samples only), the step length is the median of GPS 2D speed / step cadence over the good-fix samples that are moving (not stationary, cadence known, speed >= 0.5 m/s), clamped to `rangeM`, when they add up to >= `minS` seconds (`sensors.gps_step_length`); it replaces the body prior for the ego speed (cadence x step), the spoken steps and the map, and switches `ego.gps.speedScale` off for the run (no double correction). A step length typed by the user (`resolve_settings(step_length_m=...)`, `settings.step_length_user`) wins; without a good GPS the body prior stays. `hazards.json` `settings`: `stepLengthM` (the GPS step when the source is `gps`; else as before: the typed / body one, null = `priorStepLengthM`), `stepLengthSource` `gps` | `prior` | `user`, `gpsStepWindowsS` (the seconds the median is over), `gpsStep` {stepM, raw, windowsS, samples, p10, p90} when `gps`. `tools/sensors_report.py` prints `gpsStep` per clip.
