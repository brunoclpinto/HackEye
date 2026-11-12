# p1-03 engine.core.paths + engine.core.config (incl. Lab overrides)

Goal: config location, loading and dotted overrides become core. The Lab keeps its HTTP error type.

## Moves
| legacy | engine | note |
|---|---|---|
| `common_paths.find_common_dir` | `engine.core.paths.find_common_dir` | allowed edit: the repo-relative fallback `Path(__file__).resolve().parents[2]` becomes the right depth for `src/engine/core/paths.py` (`parents[4]`); verify it resolves to `<repo>/common` on the host |
| `collision.load_config` | `engine.core.config.load_config` | collision re-exports it as a **plain module attribute** (the conftest replaces `collision.load_config`). Code in collision keeps calling `load_config` unqualified (engine README) |
| `lab.collisions._kind`, `validate_overrides`, `PENDING_KEYS`, `_pending`, `apply_overrides`, `check_overrides` | `engine.core.config`: `value_kind`, `validate_overrides`, `PENDING_KEYS`, `is_pending`, `apply_overrides`, `check_overrides` | raise `engine.core.config.OverrideError(message)` (new, subclass of `ValueError`) where today they raise `CollisionError(422, msg)`, with identical message text |
| `collision._4_CONNECTIVITY` | (not here: p1-05) | |

- `common_paths.py` re-exports `find_common_dir`.
- `lab/collisions.py` keeps the names `validate_overrides`, `apply_overrides` and `check_overrides` as thin wrappers that call the engine function and translate `OverrideError` into `CollisionError(422, str(e))`.
  - Wrappers are only needed where a 422 can be raised; non-raising functions are re-exported as the same object.
  - It also keeps `PENDING_KEYS`, `_kind` and `_pending` as aliases (same objects).
- Every non-422 `CollisionError` stays in lab.

## Tests (Sonnet): `tests/engine/core/test_config.py`
- `find_common_dir()` with `HACKEYE_COMMON_DIR` set to a tmp dir; unset in the container (`/common`); facade identity `common_paths.find_common_dir is paths.find_common_dir`.
- `load_config()` returns the real collision.json (compare `["version"]` to the file read directly); `load_config(tmp_path/"x.json")`.
- Facade: `hasattr(collision, "load_config")`. Do not assert identity, because the conftest replaces it during tests. Assert instead that `engine.core.config.load_config.__module__ == "engine.core.config"`.
- Overrides, with every case's result or message computed from legacy `lab.collisions` functions:
  - `validate_overrides` with valid input, non-dict, unknown group, non-dict group, unknown dotted key, wrong value kind;
  - `apply_overrides` with nested dotted keys and pending keys;
  - `check_overrides` with a good and a bad case.
- `OverrideError` is raised with exactly the legacy message.
- The Lab wrapper still raises `CollisionError` with status 422 and the same message.

## Implementation (Sonnet)
- Read `lab/collisions.py` 231-313 and every caller (`grep -rn "validate_overrides\|apply_overrides\|check_overrides" lab src tools tests`).

## Done
- `check.sh` green with `--related`, plus `tests/test_collision_runs.py` and every Lab test that hits the overrides endpoints.
