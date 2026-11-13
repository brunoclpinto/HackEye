# p2-12 engine.memory (breaks the worldmap ↔ collision cycle, part 1)

## Moves
- `collision._WorldMemory` → `engine/memory/world.py` as `WorldMemory`; `collision._WorldMemory` is the same class.
- Inside `WorldMemory.advance`, the pose part is replaced by a call to a composed `engine.core.pose.DeadReckoner`. This is the one sanctioned non-verbatim edit of Phase 2.
  - `WorldMemory` keeps the attributes `x`, `y`, `theta`, `speed`, `speed_t`, `hold_s`, as properties delegating to the reckoner, with setters, because tests assign them.
  - It also keeps `entries`, `enabled`, `active`, `radius`, `range_frac`, `max_range`, `behind`, `seen_hold_s`, `takeover_s`, `adopt_s`, `overrides`, `_next`.
  - The signature `WorldMemory(cfg, enabled=True)` is unchanged.
  - Order inside `advance`: the pose update (the reckoner) first, then the pruning loop over `entries` using the new pose, exactly as today, including the `heading_deg is None` early return before pruning.
  - Alternative if properties break a pinned test (`__new__` plus attribute assignment): subclass `DeadReckoner` instead (`class WorldMemory(DeadReckoner)`). Report which one was used and why.
- **Said contract** (plan decision 4): add the methods `mark_said(mem_id: int, t: float) -> None` and `said_at(mem_id: int) -> float | None`. They read and write `entries[mem_id]["said"]`, the same key and value the speech code writes today (read `SpeechPolicy` at the audit lines 2743, 2893, 3008 for the exact value type).
  - They are not yet called by speech; Phase 3 speech switches over.
- Add `ObjectMemory(Protocol)` to `engine.core.types`, not to `engine.memory` (`active`, `entries`, `add(...)`, `mark_said`, `said_at`): speech types against core and never imports memory.
- `worldmap.PoseTracker` keeps using `collision._WorldMemory` until Phase 3: no change there.

## Tests (Sonnet): `tests/engine/memory/test_world.py`
- Identity.
- The attribute list after `__init__`.
- A long sequence of `advance` / `add` / `match` / `refresh` / `link` / `locate` calls on stub items and tracks (build them from `engine.core.types.Item` / `Track` the way the old memory tests do; grep for `_WorldMemory` in tests). Pin `entries` and pose after every step.
  - Literals come from the **legacy** class, captured before the change.
  - This is the guard for the delegation edit: exact equality (`==`) on pose floats.
- `mark_said` / `said_at` round trip, and that pruning in `advance` drops said entries the same way as others.
