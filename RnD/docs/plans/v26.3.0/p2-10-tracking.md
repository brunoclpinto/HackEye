# p2-10 engine.tracking (+ coast)

## Moves (collision.py → engine/tracking/)
| module | symbols |
|---|---|
| `velocity.py` | `_closing_mps`, `_depth_closing`, `_lateral_velocity`, `_cross_velocity` |
| `match.py` | `_match` |
| `coast.py` | `_Coast` |

Engine names are public (`Coast`).

## Risks
- `_match` builds its pairs by iterating `tracks` (insertion order) × items, then stable-sorts by -score; ties depend on order.
- `_Coast` uses `replace()` and reads the user pose duck-typed: annotate it as `engine.core.pose.PoseLike`.
- `run_collision` touches `coast.hist.pop(...)` and `coast._end(...)` from outside. Keep both names (private attribute and method) unchanged.
- Pinned by `test_collision_v2622`.

## Tests (Sonnet): `tests/engine/tracking/test_*.py`
- Identity.
- `Coast` attribute list.
- The velocity functions on synthetic track histories.
- `match` with deliberate score ties: pin the pairing.
- `Coast` over a sequence, as `test_collision_v2622` builds it: pin the items it emits per step.
