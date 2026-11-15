# p3-07 engine.worldmap.blocked

## Moves (engine/worldmap/staticmap.py → engine/worldmap/blocked.py)
`StaticMap.blocked_ahead` → method of `class BlockedMixin` in `blocked.py`; `StaticMap(BlockedMixin)`. The method body is verbatim.
`BlockedMixin` declares, as bare annotations, the attributes `blocked_ahead` reads (p3-00 mixin rules).

## Risks
- The lazy `_blk` cache (`"_blk" not in self.__dict__`): verbatim; 5 pinned tests call `blocked_ahead` on `__new__` instances.
- `blocked` must not import `staticmap` (no cycle): the mixin reaches everything through `self`.

## Tests (Sonnet): `tests/engine/worldmap/test_blocked.py`
- `engine.worldmap.blocked.BlockedMixin in collision._StaticMap.__mro__`; `collision._StaticMap.blocked_ahead is BlockedMixin.blocked_ahead`.
- The scenarios of `tests/test_collision_v26212.py` (blocked) on `__new__` instances: pin the returned dicts.
