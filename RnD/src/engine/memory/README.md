# engine/memory -- object permanence by dead reckoning

What the system remembers between frames: the user's dead-reckoned ground position and every announced object stored as
a world position, so a fragmented detection or a camera turn does not make the same object "new". Imports only
`engine.core` and the stdlib.

**Fields written** (`engine.core.types.FIELD_WRITERS`): owns `Item.wx`, `Item.wy`, `Item.mem_id`, `Item.mem_named`, `Item.mem_approach`, `Item.mem_danger`, `Track.mem_id`, `Track.linked_t`.

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

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.11 World memory — object permanence  (class `_WorldMemory`)

- **Active only with a motion track** (heading known) and `memory.enabled`. The user's ground position is dead-reckoned in an arbitrary metric frame (x east, y north; heading 0 = the initial direction, + = right turn) from `cadence × stepLength` (else ego speed; the last speed held `speedHoldSeconds`) along the heading. Items are located from their distance and lateral.
- Every announced object — every member of a "poles" cluster, a grouped context phrase or a merged entry, of any role — is stored as `{label family, world x/y, named, approach, seen, owner}`. Objects covered by a thin notice but not named individually are stored `named = false`.
- **Same object:** same label family within `matchRadiusM` (or `radiusOverrides`) + `matchRangeFraction × distance` of an entry. A track that matched keeps the link. Mover entries (people, or `moving`) match only within `moverTakeoverSeconds` of their last refresh (a person walks on). An announced object that matches is **not announced again**, with these exceptions: a covered-but-unnamed entry does not silence a named announcement, and an entry named but not as "approaching" does not silence an `approach` phrase (it is news once the person approaches).
- **Position upkeep:** a standing object stays where it was first put; a mover is followed by its owning track (or a hand-off within `moverTakeoverSeconds`). A track that has shown the entry for `ownerAdoptSeconds` becomes its owner; the owner seeing it keeps it "seen".
- **Forgotten when passed:** behind the user (`ahead < behindM` along the current heading) or farther than `maxRangeM`, unless seen within `seenHoldSeconds`.
- **v26.1.16 (rule 6):** each entry also has `danger` (a danger / final phrase was said for it). Context, feature and thin phrases are muted by any entry as before; **danger and final phrases are muted only by an entry with `danger`** (and, for an "approaching" phrase, `approach`): collision and danger supersede notify-once. The final-call rule (§7.10, item 1) therefore asks `_seen_before(danger=True)`.


### 7.17 Device sensors — one pose

- **One pose** (`ego.onePose` `auto` = on with sensors, `on`, `off`; a string so the override keeps its type): `_WorldMemory.advance(pose=...)` takes the online map's corrected pose (`_StaticMap.pose` = dead reckoning + `poseAlign`, computed before the world memory in the same frame) instead of integrating its own, so the memory, the world tracks (`wtracks.step`) and the map agree; `settings.onePose` true when active.
