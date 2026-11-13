# p2-12 engine.memory (breaks the worldmap ↔ collision cycle, part 1)

## Moves
- `collision._WorldMemory` → `engine/memory/world.py` as `WorldMemory`; `collision._WorldMemory` is the same class.
- Inside `WorldMemory.advance`, the pose part is replaced by a call to a composed `engine.core.pose.DeadReckoner`. This is the one sanctioned non-verbatim edit of Phase 2.
  - `WorldMemory` keeps the attributes `x`, `y`, `theta`, `speed`, `speed_t`, `hold_s`, as properties delegating to the reckoner, with setters, because tests assign them.
  - It also keeps `entries`, `enabled`, `active`, `radius`, `range_frac`, `max_range`, `behind`, `seen_hold_s`, `takeover_s`, `adopt_s`, `overrides`, `_next`.
  - The signature `WorldMemory(cfg, enabled=True)` is unchanged.
  - Order inside `advance`: the pose update (the reckoner) first, then the pruning loop over `entries` using the new pose, exactly as today, including the `heading_deg is None` early return before pruning.
  - Alternative if properties break a pinned test (`__new__` plus attribute assignment): subclass `DeadReckoner` instead (`class WorldMemory(DeadReckoner)`). Report which one was used and why.
- **Said contract** (plan decision 4): speech today writes `entries[mem_id]["said"] = (it.steps, t)`, a `(steps, t)` tuple of floats (collision.py, `SpeechPolicy`), and reads it back in `_closing_again`. Add:
  - `mark_said(mem_id: int, steps: float, t: float) -> None`, which stores exactly `(steps, t)` under `"said"`;
  - `said_at(mem_id: int) -> tuple[float, float] | None`, which returns `entries[mem_id].get("said")`.
  - These keep the same key and the same value as today. Speech does not call them yet; Phase 3 speech switches over. (The tests worker caught this: an earlier draft stored only `t`.)
- Add `ObjectMemory(Protocol)` to `engine.core.types`, not to `engine.memory` (`active`, `entries`, `add(...)`, `mark_said`, `said_at`): speech types against core and never imports memory.
- `worldmap.PoseTracker` keeps using `collision._WorldMemory` until Phase 3: no change there.

## Tests (Sonnet): `tests/engine/memory/test_world.py`
- Identity.
- The attribute list after `__init__`.
- A long sequence of `advance` / `add` / `match` / `refresh` / `link` / `locate` calls on stub items and tracks (build them from `engine.core.types.Item` / `Track` the way the old memory tests do; grep for `_WorldMemory` in tests). Pin `entries` and pose after every step.
  - Literals come from the **legacy** class, captured before the change.
  - This is the guard for the delegation edit: exact equality (`==`) on pose floats.
- `mark_said` / `said_at` round trip, and that pruning in `advance` drops said entries the same way as others.
