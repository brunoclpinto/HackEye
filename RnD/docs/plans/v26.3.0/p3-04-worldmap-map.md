# p3-04 engine.worldmap.map

## Moves (worldmap.py → engine/worldmap/map.py)
`WorldMap`, `build`.

Allowed edits besides p3-00's renames:
- `WorldMap.__init__`: `self.cfg = cfg or load_config()` → `self.cfg = cfg or config.default_config_loader()` (p3-00).
- `build` keeps its signature `(grids, times, class_names, hazards, coll_cfg, cfg=None, depth=None, hook=None)`.

After this task `worldmap.py` is a pure facade (docstring + re-exports + the hook + `import collision`, `import groundfuse`).

## Risks
- `worldmap.build` is monkeypatched in `test_collision_runs.py` (spy): the Lab calls it through the facade module, unchanged.
- `step(...)` returns `ms` from `time.perf_counter`: excluded from equivalence (decision 10); tests must not pin it.
- The conftest `_v2629_map_settings` patch must reach `WorldMap(...)` built with `cfg=None`: covered by a test below.

## Tests (Sonnet): `tests/engine/worldmap/test_map.py`
- Identity (`worldmap.WorldMap`, `worldmap.build`).
- With `monkeypatch.setattr(worldmap, "load_config", lambda path=None: {...real, "marker": 1})`, `worldmap.WorldMap(..., cfg=None).cfg["marker"] == 1`.
- `build` on a short fixture window (3–5 frames): pin the returned dict's keys and array digests, excluding `ms`.
