# p1-07 engine.core.distfuse (from groundfuse.py)

Goal: the stateless distance-fusion helpers move to core. The `groundfuse` model later keeps only the stateful estimators.

## Moves (groundfuse.py -> engine.core.distfuse, same names; `_prior_interp` becomes `prior_interp`)
- `MODES`, `SRC_DEPTH`, `SRC_GROUND`, `SRC_FUSED`, `SRC_NAMES`.
- `settings`, `resolved_mode`, `_prior_interp`, `rho_at`, `correct_depth`, `resolve`.
- `resolve` uses only `correct_depth` among the moved names (Opus checked), so this task has no ordering dependency on p1-08.
- `groundfuse.py` keeps `HorizonSigma`, `Corrector` and `_wmedian`, and re-exports every moved name (same objects; `_prior_interp` as an alias).
- `lab/collisions.py` `_add_effective` lazily imports `groundfuse`. Leave that untouched (Phase 5).

## Tests (Sonnet): `tests/engine/core/test_distfuse.py`
- Identity: every moved name through `groundfuse`.
- `settings({})` and `settings(real collision config section)`: legacy literal dicts. Find how callers pass the config: `grep -rn "groundfuse.settings(" src`.
- `resolved_mode` for each mode string in `MODES` and for an invalid one: legacy results.
- `prior_interp`, `rho_at` and `correct_depth` on small fixed numpy arrays: legacy outputs compared with `np.testing.assert_array_equal`. They should be bitwise identical, since it's the same code.
- `resolve(...)` for each mode on a small synthetic case built from a `Geometry` like the legacy tests do (see tests/test_collision_v2623.py): legacy outputs.

## Implementation (Sonnet)
- Pure move.

## Done
- `check.sh` green with `--related`, which must include tests/test_collision_v2623.py and tests/test_worldmap_v2627.py.
