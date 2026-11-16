# p5-05 lab.features

## Moves
`reviews.py` (whole module, incl. its own `LAB_DIR`, `_RunData`, `_save`), `notes.py`, `issues.py` (`CATALOGUE` patched by tests),
`sounds.py`, `display.py` → `lab/features/<name>.py`; the compare / match functions of `collisions.py` (`_flatten`, `_settings_diff`,
`_events`, `_same`, `match_events`, `compare`) → `lab/features/compare.py`. `lab.features` may import `lab.store` only: their
`recordings._atomic_write_json` use becomes `store.util._atomic_write_json`; reviews' `analysis.get_run` / `RUN_ID_RE` / `run_dir` and lazy
`collisions` use become `lab.store.runs` / `constants` / `collision_docs`.
The flat modules forward every moved name.

## Tests (Sonnet): `tests/lab/test_features.py`
- Identity through the facades; `issues.CATALOGUE` patch is seen by the issues functions.
- `match_events` on the inputs of the existing compare tests: pin results from the legacy function.
- The existing review / notes / issues / sounds / display tests pass unchanged.
