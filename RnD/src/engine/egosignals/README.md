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
