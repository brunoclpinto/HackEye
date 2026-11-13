# p2-04 engine.egosignals.series (per-run ego signal series)

## Moves (collision.py → engine/egosignals/series.py)
`_motion_series`, `IMU_STATIONARY_DEFAULT`, `_nearest`, `_sensor_series`, `_gps_at`, `_auto_stationary`, `_sensor_heading` (public names without the underscore).
- They call the cadence (p2-01) and imu/gpmf (p2-02/03) functions: import them from `engine.egosignals.*`.

## Risks
- `_sensor_series` is pinned by `tools/sensors_report.py`, which calls `collision._sensor_series`; keep the alias.
- `_sensor_heading` mutates its `sser` argument in place: keep that.

## Tests (Sonnet): `tests/engine/egosignals/test_series.py`
- Identity.
- `motion_series` and `sensor_series` on the real fixture with sensors (`chest0004_review9`) and on one without: pin keys, lengths and digests.
- `nearest`, `gps_at` and `auto_stationary` edge cases.
- `sensor_heading` mutation: before/after digests.
