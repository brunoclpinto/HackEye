# p1-05 engine.core.classes

## Moves (to engine.core.classes)
| legacy | engine name |
|---|---|
| `collision.ClassIds`, `collision.resolve_class_ids`, `collision.ITEM_GROUPS`, `collision.NO_DATA` | same names |
| `collision._4_CONNECTIVITY` | `FOUR_CONNECTIVITY` (collision alias `_4_CONNECTIVITY`, the same array object) |

- `segmentation._4_CONNECTIVITY` and `lab.analysis.NO_DATA` stay untouched (infer / lab later).
- Item order depends on `ITEM_GROUPS`; it is a tuple, keep it.

## Tests (Haiku): `tests/engine/core/test_classes.py`
- Identity of all moved names through `collision`.
- `ITEM_GROUPS == ("static", "moving", "feature")`.
- `NO_DATA == 255`.
- `FOUR_CONNECTIVITY` equals the legacy array (values, dtype).
- `resolve_class_ids(collision.load_config(), names)`: build `names` from a real fixture's class list (tests/fixtures/chest0004_review7.json or the npz; find where class names live) and from a small hand list with unknown names. Compare `dataclasses.asdict`, or the attributes if not a dataclass, to legacy literals.

## Implementation (Sonnet)
- Pure move.

## Done
- `check.sh` green with `--related`.
