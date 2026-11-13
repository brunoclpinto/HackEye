# engine/egosignals -- IMU, heading and cadence signals of the wearer

Signals about the wearer's own motion. Imports only the stdlib and numpy; no other model.

## cadence.py (v26.3.0 p2-01, moved from `collision.py`)

| name | kind | purpose | legacy |
|---|---|---|---|
| `spectrum` | function | power spectrum of a detrended, Hann-windowed window, zero-padded `pad` times | `collision._spectrum` |
| `refine` | function | parabolic interpolation around bin k; rejected when it moves > 1 bin or leaves `[lo, hi]` | `collision._refine` |
| `peak` | function | `(bin, ratio)` of the strongest peak in `[lo, hi]`; ratio = peak amplitude over RMS of the rest | `collision._peak` |
| `CORROBORATED_RATIO_FRAC` | constant (0.7) | a weaker dy peak is accepted when dx peaks at the same rhythm | `collision.CORROBORATED_RATIO_FRAC` |
| `window_cadence` | function | step cadence of one uniform window, stride aware (second harmonic), nan without a clear peak | `collision._window_cadence` |
| `estimate_cadence` | function | per-sample step cadence (Hz, nan unknown) from the vertical camera bob; causal, held one window | `collision.estimate_cadence` |
| `hold_last` | function | forward-fill nan for up to `hold_s` after the last valid value | `collision._hold_last` |
| `estimate_stationary` | function | per-sample "standing still" flag from the residual image flow, with enter/leave hysteresis | `collision.estimate_stationary` |

Legacy names are re-exports of the same objects. The package `__init__` re-exports all of them.

### Inputs / outputs
- `estimate_cadence(t, dy, window_s, band_hz, min_peak_ratio, dx=None, min_step_hz=1.4, harmonic_ratio=0.25)`:
  time (s) and vertical bob series (optional horizontal sway `dx`) -> float array, nan while unknown.
- `estimate_stationary(t, resid, cfg)`: time and residual flow (px) -> bool array.

### Config keys read
Passed in by the caller (`ego.*` of `collision.json`): `cadenceWindowSeconds`, `cadenceBandHz`, `cadenceMinPeakRatio`
become the `window_s`, `band_hz`, `min_peak_ratio` arguments. `estimate_stationary` reads its `cfg` dict
(`ego.stationary`): `medianSeconds` (1.0), `enterPx` (0.8), `leavePx` (1.0), `enterSeconds` (1.5), `leaveSeconds` (1.0).

### Invariants
- Numerics are bit-identical to the pre-move code (FFT, polyfit); do not reorder operations.
- Causal: the estimate at time t uses only samples in (t - window_s, t]; needs 60 percent of the window.
- A false "stationary" silences warnings, so unknown flow never enters it and counts as walking evidence when leaving.

### Changelog (from the `collision.py` docstring)
- Ego motion: cadence is the step rate seen in the vertical camera bob (spectral peak in 0.8-3.5 Hz). A chest camera
  bobs asymmetrically, so the dominant peak is often the *stride* (~1 Hz) and the step rate is its second harmonic;
  `estimate_cadence` is stride aware (see `window_cadence`).
- Stationary user (`estimate_stationary`, from the residual image flow of `egoflow.py`): the ego speed is 0 and nothing
  static is announced; only a mover on a collision course is.
- v26.1.11 (review 4: one -16.3 Hz cadence at 336 s): the cadence refine cannot leave its band.

## imu.py (v26.3.0 p2-02, moved from `sensors.py` 262-511)

| name | kind | purpose | legacy |
|---|---|---|---|
| `smooth` | function | centred moving average over `win_s` seconds of an irregularly stamped (N, C) signal | `sensors._smooth` |
| `default_imu_cfg` | function | defaults of `ego.imu` (axis conventions, signs, time constants, bias, `timeOffsetS`) | `sensors.default_imu_cfg` |
| `gravity_unit` | function | low-passed accelerometer = gravity direction, unit length, per accel sample | `sensors.gravity_unit` |
| `yaw_rate` | function | `(gyro times, yaw rate rad/s about gravity; + = right)` | `sensors.yaw_rate` |
| `spans` | function | `(start, end)` spans of a flag lasting >= `min_s` | `sensors._spans` |
| `estimate_bias` | function | `(gyro bias rad/s, source)`: stationary-span median or the lowest-|rate| fraction | `sensors.estimate_bias` |
| `heading_series` | function | heading degrees at given times (0 at the first; + = right) and `{biasDegPerS, biasSource}` | `sensors.heading_series` |
| `gravity_angles` | function | `(accel times, pitch deg, roll deg)` from the gravity direction | `sensors.gravity_angles` |
| `vertical_signals` | function | uniform-rate bob (along gravity) and sway, inputs of the cadence estimator | `sensors.vertical_signals` |
| `motion_energy` | function | accel std + 2 x gyro std over a window (quiet when the camera is still) | `sensors.motion_energy` |
| `gps_good` | function | mask of GPS samples with fix >= `min_fix` and DOP <= `max_dop` | `sensors.gps_good` |
| `gps_xy` | function | local east / north metres of every GPS sample | `sensors.gps_xy` |
| `crop` | function | the sensors restricted to `[t0, t1]`, each stream by its own `*_t` | `sensors.crop` |
| `wrap_deg` | function | wrap degrees to [-180, 180) | `sensors._wrap` |
| `gps_course_offset` | function | slow causal GPS correction of a heading series: `(offset deg per time, info)` | `sensors.gps_course_offset` |
| `gps_step_length` | function | user's step length from GPS speed / cadence, or None | `sensors.gps_step_length` |

Legacy names are re-exports of the same objects. The package `__init__` re-exports all of them (public names).

### Inputs / outputs
Sensor dict `s` as returned by `sensors.extract` (`gyro`, `gyro_t`, `accl`, `accl_t`, `gps`, `gps_t`, `gps_fix`,
`gps_dop`, ...). Functions return numpy arrays or small dicts; all are pure and causal where stated.

### Config keys read
- `ego.imu`: `yawSign`, `gravityTauS`, `yawGravityTauS`, `accelUpAxis`, `accelRightAxis`, `accelForwardAxis`,
  `pitchSign`, `rollSign`, `biasMinStationaryS`, `biasLowFraction`, `timeOffsetS`.
- `ego.gps`: `minFix`, `maxDop`, `courseWindowS`, `courseMinTravelM`, `courseMinSpeedMps`, `courseMaxTurnDeg`,
  `courseRejectDeg`, `courseTauS`, `courseInitN`.
- `ego.stepLength`: `minFix`, `maxDop`, `minCadenceHz`, `minSpeedMps`, `minS`, `rangeM`.

### Invariants
- Code moved verbatim; numerics bit-identical to the pre-move `sensors.py`.
- `gps_course_offset` is causal (holds the last update); `gps_step_length` is pinned by `test_collision_v26212`.
