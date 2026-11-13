# p2-01 engine.egosignals.cadence

## Moves (collision.py → engine/egosignals/cadence.py)
`_spectrum`, `_refine`, `_peak`, `CORROBORATED_RATIO_FRAC`, `_window_cadence`, `estimate_cadence`, `_hold_last`, `estimate_stationary`.
Public names drop the underscore. `estimate_cadence` and `estimate_stationary` are already public.

## Risks
- FFT/polyfit numerics: the move must be verbatim.
- `_refine` is pinned by 3 old tests.

## Tests (Sonnet): `tests/engine/egosignals/test_cadence.py`
- Identity of all 8 names.
- `spectrum`, `refine` and `peak` on synthetic sinusoids: 1.6, 1.9 and 2.2 Hz at fs 30 and 60, plus noise from `default_rng(0)`.
- `window_cadence` and `estimate_cadence` on a synthetic 60 s walking/standing/walking signal, and on the vertical-acceleration series of a real fixture with sensors (`chest0004_review9`; see how `_motion_series` / `_sensor_series` build their input).
- `hold_last` edge cases.
- `estimate_stationary` on the same signals.
- Pin values with `approx(rel=1e-12)`.
