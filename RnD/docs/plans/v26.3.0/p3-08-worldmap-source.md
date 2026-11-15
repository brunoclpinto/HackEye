# p3-08 engine.worldmap.source

## Moves (collision.py → engine/worldmap/source.py)
`_map_source` → `map_source`. Positional signature `(items, tracks, smap, wtracks, cfg, t, step_len, u, counts)` unchanged.
It calls `smap._apply` (private method of the same package's class), `set_position`, `_ego_frame` (core.groundgeom) and `_trusted_track` (core.types).

## Risks
- Tests pass stubs for `smap` (`pose`, `judged`, `region`, `_apply`) and `wtracks` (`on`, `lookup`): annotate both with local Protocols, no
  isinstance checks.

## Tests (Haiku): `tests/engine/worldmap/test_source.py`
- Identity.
- The stub scenarios of `tests/test_collision_v26211.py` (lines around the `_map_source` calls): pin the written item fields and `counts`.
