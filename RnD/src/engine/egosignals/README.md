# engine/egosignals -- IMU, heading and cadence signals of the wearer

Signals about the wearer's own motion. Imports only the stdlib and numpy; no other model.

**Fields written:** none (`Item` / `Track` fields, `engine.core.types.FIELD_WRITERS`).

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

## gpmf.py (v26.3.0 p2-03, moved from `sensors.py` 28-255)

| name | kind | purpose | legacy |
|---|---|---|---|
| `parse_payload` | function | one GPMF payload (nested KLV, `SCAL`, big-endian types) -> `{stream: {...}}` | `sensors.parse_payload` |
| `split_payloads` | function | raw `gpmd` bytes -> list of payloads (stops at the first malformed header) | `sensors.split_payloads` |
| `build` | function | payloads + packet `(pts, duration)` -> time-stamped sensor arrays | `sensors.build` |
| `extract` | function | `gpmd` stream of a media file via ffmpeg/ffprobe -> sensor dict, or None without the stream | `sensors.extract` |
| `hilights` | function | HiLight tag times (s) of a media file | `sensors.hilights` |
| `concat` | function | chapters `[(start_s, sensors)]` -> one sensor dict on the recording time line | `sensors.concat` |
| `save` / `load` | function | npz cache of a sensor dict (atomic write; `load` gives None when missing or unreadable) | `sensors.save` / `sensors.load` |
| `_FMT`, `_STREAMS`, `_klv`, `_numbers`, `_gpmd_stream`, `_utc_epoch` | private | parser internals; reached by tests through the `sensors` facade | same names in `sensors` |

Legacy names are re-exports of the same objects. The package `__init__` re-exports the public names (not the
private ones). `lab.recordings` and `tools/sensors_report.py` call `sensors.extract` etc. through the module, so
`sensors.extract` stays patchable.

### Inputs / outputs
`extract(media_path)` returns `gyro, gyro_t, accl, accl_t, gps, gps_t, gps_fix, gps_dop, gps_utc, shut, shut_t,
isog, isog_t` (seconds from the start of the file) or None. Needs `ffmpeg`/`ffprobe` on PATH.

### Config keys read
None.

### Invariants
- Code moved verbatim; the stdlib (`json`, `struct`, `subprocess`, `tempfile`) is the only addition to numpy.
- Sample times are spread evenly over each payload's packet pts / duration; fix and DOP repeat per payload.

## series.py (v26.3.0 p2-04, moved from `collision.py`)

| name | kind | purpose | legacy |
|---|---|---|---|
| `motion_series` | function | `(t, cadence, cumulative heading deg, stationary flag or None)` of the image motion track, or None | `collision._motion_series` |
| `IMU_STATIONARY_DEFAULT` | constant | defaults of `ego.imu.stationary` (median 0.3 s, enter 0.5 px, leave 0.8 px, 1.5 s / 1.0 s) | `collision.IMU_STATIONARY_DEFAULT` |
| `nearest` | function | index of the sorted `tu` sample at or just before each `t` (clipped) | `collision._nearest` |
| `sensor_series` | function | device-sensor series on the motion time base: `mt`, `s`, `cad`, `stat_imu`, `pitch`, `roll`; None without usable sensors | `collision._sensor_series` |
| `gps_at` | function | GPS state `{lat, lon, speedMps, dop, fix, good}` at a time, or None | `collision._gps_at` |
| `auto_stationary` | function | `ego.stationarySource` "auto": `(imu_stat, "imu")` | `collision._auto_stationary` |
| `sensor_heading` | function | fills `sser` in place with `heading_imu`, `info`, `heading_gps` (bias from the stationary spans) | `collision._sensor_heading` |

Legacy names are re-exports of the same objects (`tools/sensors_report.py` calls `collision._sensor_series`). These
functions call `cadence`, `imu` and `gpmf` through `engine.egosignals.*`.

### Config keys read
`ego`: `cadenceWindowSeconds`, `cadenceBandHz`, `cadenceMinPeakRatio`, `minStepHz`, `harmonicMinRatio`, `stationary`,
`gravityTauS`; plus the sensor sections `imu` (`activityWindowS`, `cadenceRateHz`, `stationary`), `gps` (`enabled`,
`minFix`, `maxDop`).

### Invariants
- `sensor_heading` mutates its `sser` argument in place (keep it).
- Code moved verbatim; numerics bit-identical.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.6 Ego motion — cadence, stationary user, heading

- **Cadence** (step rate, Hz), from the vertical bob `dy` of `motion` (nearest motion sample to `t`): causal power-spectrum peak in `cadenceBandHz` over `cadenceWindowSeconds` (needs 60 % of a window), accepted at `cadenceMinPeakRatio` (a weaker peak is accepted when the horizontal sway `dx` peaks at the same rhythm). **Stride-aware:** a chest camera bobs asymmetrically, so a dominant peak `f0` is often the stride; the step rate is the peak near `2·f0` if `f0 < minStepHz`, or that peak has ≥ `harmonicMinRatio` of the power, or `dx` peaks within 0.15 Hz of `f0`; otherwise `f0`. A value is held for one window when a later window has no clear peak.
- **Cadence refine** (v26.1.11): the parabolic refine of the peak bin is rejected (the bin centre is kept) when it moves by more than one bin or leaves the search band (the peak search is band-limited, so a bigger neighbour outside it made one reading −16.3 Hz at 336 s of review 4).
- **Stationary user** (v26.1.11, `estimate_stationary`, config `ego.stationary`): from `motion.resid` (§5): `m` = causal median of the residual flow over `medianSeconds`, valid with half of the window's samples known. **Entered** after `m < enterPx` (0.8 px) for `enterSeconds` (1.5 s); **left** after `m ≥ leavePx` (1.0 px) for `leaveSeconds` (1 s); an unknown `m` never enters and counts as walking when leaving (a false "stationary" silences warnings, a false "walking" only says too much). On 4929: the 1 s median is 0.07–0.58 px standing (308–346 s) and ≥ 1.34 px at every moment of 0–296 s and 360–470 s, so the thresholds sit in the middle of a 2.3× gap. A turn in place is not recognised (the picture rotates). Without `resid` (old runs, fixtures 1–3) the user is never stationary. Reported as `ego.stationary`. **While stationary** the walking cadence is ignored (a standing chest camera bobs at 1–2 Hz: review 4 read 1.3–2.2 Hz and 1.1 m/s), the ego speed is 0, nothing static is announced (every item except a measured mover on a collision course gets role `none`: no context, feature, thin notice, danger, final or beep) and the world memory does not advance.
- **Heading:** with sensors (§7.17) the gyro heading (`ego.headingSource`); without, the cumulative sum of `−dx × hfovDeg` (degrees; + = turned right), interpolated to `t`. With sensors the cadence and the stationary flag also come from the accelerometer / gyro (§7.17).

### 7.17 Device sensors  (v26.2.11)

The GoPro writes a GPMF telemetry stream (`gpmd`) into every clip; the Lab reads it (the iPhone has the same sensors through CoreMotion: this is a device sensor, not a camera prior). `sensors.extract(file)` copies the stream with ffmpeg, parses the KLV payloads (nested type 0, `SCAL`, big-endian `s S l L j J f d b B`; sample times spread evenly over each payload's packet pts / duration) and returns `gyro` (rad/s, channel order z, x, y), `accl` (m/s2; up/down, right/left, forward/back), `gps` (lat, lon, alt, 2D speed, 3D speed) with `gps_fix` (0/2/3), `gps_dop` (DOP, 9999 = none; per 1 s payload), `gps_utc`, `shut` / `isog` (exposure, gain per frame), each with `*_t` (s). `recordings.sensors_for(recId)` joins the chapters on the recording's timeline and caches `sensors/<recId>.npz` (+ the chapter file size / mtime; an empty marker for a clip without telemetry). `hilights(file)` reads the udta `HMMT` HiLight tags (none on any of the 19 clips). `collision_pass` hands the sensors to `run_collision(sensors=...)`; **without them (no gpmd stream, fixtures, `ego.sensors: false`) the pass is exactly the v26.2.10 one** (the hazards keys below are only written with sensors).
- **Heading** (`ego.headingSource` `auto` = imu when present, `imu`, `flow`): yaw rate = `yawSign` (-1: + = right turn, the flow heading's sign) x (gyro . g), g = the accelerometer low-passed over `yawGravityTauS` (1 s) and normalised, integrated; bias = median yaw rate over the stationary spans >= `biasMinStationaryS` (the pass's own stationary series, interpolated between spans) else the median of the clip's lowest-|rate| `biasLowFraction` (20 %). Computed on the pass's range only. 0 at the first motion sample, as the flow heading. It feeds `ego.headingDeg` (so `_WorldMemory`, the online map, `worldmap.build`, the turn detector `pathChange`, the lateral history); the pan-compensated track match (`pan_shift`) keeps the flow heading (it is an image shift). `settings.headingSource` in hazards says `flow`, `imu` or `imu+gps`.
- **GPS** (`ego.gps`: `enabled`, `maxDop` 2.5, `minFix` 3): per frame `ego.gps` = {lat, lon, speedMps, dop, fix, good} (nearest sample, null beyond 1.5 s); no decision reads a sample that is not `good`. **Course correction** (`gps.course`): the chord over the last `courseWindowS` (8 s) of good fixes, when >= `courseMinTravelM` (6) at >= `courseMinSpeedMps` (0.6) and the heading turned < `courseMaxTurnDeg` (25), gives a residual course - heading; an exponential average of it (`courseTauS` 30 s, residuals > `courseRejectDeg` from it ignored; first value = the median of `courseInitN` residuals; causal, held between updates) is applied as its CHANGE since the first value (the heading stays "0 = the initial direction"): removes the gyro's residual trend. **Speed scale** (`gps.speedScale`, default off): the step length is pulled toward GPS speed / (cadence x prior step) (median over `speedWindowS`, needs `speedMinS` 20 s of good moving frames, time constant `speedTauS`, clipped [0.5, 1.6]); `stepLengthM` of the frame shows it, `settings.priorStepLengthM` stays the prior.
- **Cadence / stationary** (`ego.cadenceSource` `auto` = imu when present, `imu`, `image`; `ego.stationarySource` `auto` | `imu` | `image` | `both` | `either`): the same estimator (`estimate_cadence`) on the acceleration along gravity at 60 Hz, the sideways acceleration as the sway cross-check; stationary = `estimate_stationary` on a 1 s accel-std + 2 x gyro-std activity (`ego.imu.stationary`: enter 0.5 / leave 0.8, 1.5 s / 1 s). Without a motion track the analysed frame times are the time base.
- **Gravity** (`ego.gravityTauS` 0.5 s low-pass of the accelerometer): `ego.pitchDeg` (+ = looking up; `imu.pitchSign` -1: accel channel 2 reads + when the lens looks down) and `ego.rollDeg` (+ = right side down); the mount offset is in the values. `horizon.source` `image` (default) | `gravity` | `fused`: the horizon row = (image horizon - gravity horizon) averaged over `levelTauS` (30 s) + `f_eq` rows per radian x pitch; `gravity` uses it, `fused` pulls the image horizon toward it by `gravityWeight`; the image estimate keeps its own state (no feedback); the frame then carries `ego.horizonImageY`. `ego.rollCorrect` (default false): the frame's `ego.rollCorrectDeg` = the roll, and `groundfuse.Geometry.roll` undoes it in `ray_dir` / `ground_pixel` (items on a fisheye run, the world map's ground surfaces, depth surfaces, object bases).
- Hazards `settings` (with sensors): `headingSource`, `cadenceSource`, `stationarySource`, `horizonSource`, `gyroBiasDegPerS`, `gyroBiasSource` (`stationary` | `lowest`), `gpsUpdates`, `onePose`. `tools/sensors_report.py <rec> [--run id --collision cid]` prints the clip table and the heading / speed comparison against the GPS.
