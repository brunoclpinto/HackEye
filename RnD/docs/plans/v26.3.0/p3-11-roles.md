# p3-11 engine.roles

## Moves (collision.py → engine/roles/roles.py)
`_speed_witness`, `_pole_like`, `_is_static_like`, `_not_approaching`, `_sideways_mps`, `_course`, `_on_collision_course`, `_fast_warning`,
`_assign_role`, all without the leading underscore.

## Risks
- `assign_role`'s first line resets six fields in one statement (`role, urgency, collision, summary_ok, proximity, speak`): verbatim.
- It reads `it.map_cells` / `it.map_judged` (written by the static map): fields only, no import.

## Tests (Sonnet): `tests/engine/roles/test_roles.py`
- Identity of all nine.
- A table of ~20 stub items (`engine.core.types.Item` with the fields each predicate reads) through every predicate: pin the booleans /
  floats.
- `assign_role` on the scenarios of the existing `_assign_role` tests (grep `_assign_role` in tests/): pin the six written fields.
