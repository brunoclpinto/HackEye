# p1-09 engine.core.types (Item, Track, Region, shared helpers)

Goal: the shared per-frame data types become core. This is the riskiest Phase 1 task: tests pin field order, positional construction, `__new__` and `dataclasses.replace`.

## Moves (collision.py -> engine.core.types)
| legacy | engine name | note |
|---|---|---|
| `_Item` | `Item` | 90 fields + `__post_init__` (audit 4.1); `collision._Item` is the SAME class |
| `_Track` | `Track` | 43 fields, positional construction pinned (audit 4.2) |
| `Region` | `Region` | |
| `LANE_PART_ID_BASE`, `POINT_ASPECT` | same | |
| `_trusted_track` | `trusted_track` | |

- Class `__name__` / `__qualname__` become `Item` / `Track`. Before changing them, grep for anything that serialises a class name or a dataclass `repr` of these types (`repr(`, `__name__`, `type(it).__name__`, f-strings of items) in src/lab/tools. If any output depends on the name, keep the old class names inside engine and report it.
- `FIELD_OWNERS` is NOT added here; it comes in Phase 4. `tests/test_field_ownership.py` must keep skipping.
- `PoseLike` lives in `engine.core.pose` (p1-06). Add `ObjectMemory(Protocol)` only if a moved type annotates with it; otherwise leave it for p2 memory.

## Tests (Sonnet): `tests/engine/core/test_types.py`
- Identity: `collision._Item is types.Item`, `collision._Track is types.Track`, `collision.Region is types.Region`, the constants, and `collision._trusted_track is types.trusted_track`.
- Exact field-name order lists of `Item`, `Track` and `Region`: literals generated from legacy `dataclasses.fields`.
- Defaults: `dataclasses.asdict(Item(<minimal required args>))` equals the legacy literal. Find the minimal args from existing tests that build `_Item(...)`.
- `__post_init__`: the `clock_q` / `clock_text` fill-in when missing, and no overwrite when given.
- `dataclasses.replace(item, distance_m=...)` re-runs `__post_init__` (legacy behaviour: assert the same).
- Positional `Track(id, group, class_name, box, last_t, first_t, last_distance, last_lateral)` and with `history`, exactly as tests/test_collision_v2622.py does.
- `Item.__new__(Item)` followed by attribute assignment works, as in the old tests.
- `trusted_track` with a stub `lookup` returning None, `{"trusted": False}` or `{"trusted": True}`.

## Implementation (Sonnet)
- A pure move plus the two class renames, with aliases in collision.
- **Do not reorder fields.** Keep `slots`/`eq`/`order` arguments as they are.

## Done
- `check.sh` green with `--related`; this hits most of the suite, so expect a long run.
- Also run the equivalence quick test.
