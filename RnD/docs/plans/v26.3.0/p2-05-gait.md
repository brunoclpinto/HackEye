# p2-05 engine.gait

## Moves (collision.py → engine/gait/scale.py)
`_Scale` → `Scale`, `GpsSpeedScale`.

## Risks
- `_Scale` is pinned by `test_collision.py`.
- Log-space slew.
- Keep the attribute names: tests read private attributes; grep `_Scale` in tests.

## Tests (Haiku): `tests/engine/gait/test_scale.py`
- Identity.
- Attribute lists after `__init__`.
- `update` sequences, about 50 steps from `default_rng(1)` with the gaps and outliers the old tests use: pin `value` after each step (a list literal).
- `GpsSpeedScale`, as `test_sensors_v26211` uses it.
