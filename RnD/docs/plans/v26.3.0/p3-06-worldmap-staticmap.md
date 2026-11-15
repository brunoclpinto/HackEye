# p3-06 engine.worldmap.staticmap

## Moves (collision.py → engine/worldmap/staticmap.py)
`_StaticMap` → `StaticMap`, with every method except `blocked_ahead` (p3-07); plus the free functions `_set_position` → `set_position` and
`_mute_solid` → `mute_solid`. `collision._StaticMap is engine.worldmap.staticmap.StaticMap`.

In this task `StaticMap` still defines `blocked_ahead` (verbatim); p3-07 moves it out to a mixin.

Inside the moved code: `faceedge.<name>` stays as is with `from engine.worldmap import faceedge`; `_set_position` calls become
`set_position` (named rename). The `wmod` constructor argument stays (`wmod.load_config()`, `wmod.WorldMap`, `wmod.KIND_OBJECT`).

## Risks
- Tests build it with `__new__` and set only some attributes (audit 6.4): methods may read only what they read today.
- `test_collision_v2621` replaces `col._StaticMap.update` on the class: the class object must be the one `run_collision` instantiates.
- The `_lut` cache keyed by `id(lut)` and the lazy `_blk` guard (`"_blk" not in self.__dict__`): verbatim.
- The method `faceedge` and the module global `faceedge` share a name: keep it (method bodies resolve the module global).

## Tests (Sonnet): `tests/engine/worldmap/test_staticmap.py`
- Identity (class and both functions); the method list of the class (sorted names defined on the class, including inherited ones after p3-07:
  assert the set of callables reachable with `dir`, filtered to the legacy list).
- On a `__new__` instance set up the way `tests/test_collision_v26211.py` does: `measure`, `snap_solid`, `_apply`, `_footprint` on stub
  items: pin the written item fields.
- `set_position` and `mute_solid` on stub items: pin every written field.
