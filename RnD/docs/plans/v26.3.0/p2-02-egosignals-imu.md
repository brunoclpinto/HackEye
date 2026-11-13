# p2-02 engine.egosignals.imu (from sensors.py 262–511)

## Moves (sensors.py → engine/egosignals/imu.py)
`_smooth`, `default_imu_cfg`, `gravity_unit`, `yaw_rate`, `_spans`, `estimate_bias`, `heading_series`, `gravity_angles`, `vertical_signals`, `motion_energy`, `gps_good`, `gps_xy`, `crop`, `_wrap`, `gps_course_offset`, `gps_step_length`.
- Private names become public (`smooth`, `spans`, `wrap_deg` for `_wrap`).
- `sensors.py` keeps every name as a re-export.

## Risks
- `gps_step_length` is pinned 10× by `test_collision_v26212`.
- `heading_series` and `gps_course_offset` are pinned.

## Tests (Sonnet): `tests/engine/egosignals/test_imu.py`
- Identity through `sensors`.
- Every function on the real sensor stream of a fixture with sensors (load it the way `tests/test_sensors_v26211.py` does) and on small synthetic arrays.
- Pin digests and scalars.
- `crop` boundaries.
- `wrap_deg` at ±180.
