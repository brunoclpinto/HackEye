# engine/memory -- object permanence by dead reckoning

What the system remembers between frames: the user's dead-reckoned ground position and every announced object stored as
a world position, so a fragmented detection or a camera turn does not make the same object "new". Imports only
`engine.core` and the stdlib.

## API

| module | name | purpose | legacy |
|---|---|---|---|
| `world.py` | `WorldMemory` | `WorldMemory(cfg, enabled=True)`; `advance`, `locate`, `match`, `refresh`, `add`, `link`, `mark_said`, `said_at`; property `active` | `collision._WorldMemory` |

`engine/memory/__init__.py` re-exports `WorldMemory` (`__all__ = ["WorldMemory"]`). `engine.core.types.ObjectMemory` is
the Protocol speech types against (`active`, `entries`, `add`, `mark_said`, `said_at`).

## Inputs / outputs

- `advance(t, dt, speed, heading_deg, pose=None)` -> None. The pose part is delegated to a composed
  `engine.core.pose.DeadReckoner`; then entries are pruned with the new pose. A `heading_deg` of None sets `theta` to
  None (memory inactive) and returns before pruning. Entries in view (`t - seen <= seenHoldSeconds`) are kept; others are
  dropped when behind (`ahead < behindM`) or farther than `maxRangeM`.
- `locate(item)` -> world (x, y) of the item. `match(item, t)` -> entry id or None (same family within the radius,
  movers only within `moverTakeoverSeconds` of the entry's last refresh). `add(item, t, named=True)` -> new id.
  `refresh(id, item, t)` moves an entry. `link(items, tracks, t)` sets `it.mem_*` and `track.mem_id` for each item.
- `mark_said(mem_id, steps, t)` stores `(steps, t)` under `entries[mem_id]["said"]`; `said_at(mem_id)` returns it or
  None. Speech still writes the key directly; Phase 3 switches it over.
- Entry keys: `family, x, y, named, approach, danger, seen, fresh, owner` (and `said` once marked).

## Config keys read

Passed in as the `memory` block of `collision.json`: `enabled`, `matchRadiusM`, `matchRangeFraction`, `maxRangeM`,
`behindM`, `speedHoldSeconds`, `seenHoldSeconds`, `moverTakeoverSeconds`, `ownerAdoptSeconds`, `radiusOverrides`.

## Invariants

- `collision._WorldMemory is engine.memory.world.WorldMemory`.
- `x, y, theta, speed, speed_t, hold_s` are properties with setters over the composed `DeadReckoner` (tests assign them
  and build instances with `__new__`, so the reckoner is created lazily). Pose floats are bit-identical to the legacy
  inline code (pinned with `==`).
- `active` is `enabled and theta is not None`.
- Attributes after `__init__`: `enabled, radius, range_frac, max_range, behind, seen_hold_s, takeover_s, adopt_s,
  overrides, entries, _next` plus the pose properties.

## Changelog lines (from the `collision.py` module docstring)

> * **World memory by dead reckoning** (`_WorldMemory`). Identity used to exist only as image tracks, so a fragmented
>   detection or a camera turn made the same real object "new" and it was announced again. We now integrate the user's
>   ground position (calibrated ego speed = cadence x step length, along the heading of the motion track) and store
>   every announced object (any role, every member of a "poles" cluster or a grouped context phrase) as
>   `(label family, world x/y)`. A candidate of the same family within `memory.matchRadiusM` + 10 percent of its
>   distance of a remembered object is that object and is not announced again; a track that matched keeps the link and
>   refreshes the object's position. Objects are forgotten when passed (behind the user) or more than
>   `memory.maxRangeM` away. Without motion data the old per-track and per-label rules apply unchanged.
