# p3-10 engine.motion

## Moves (collision.py → engine/motion/)
| module | symbols |
|---|---|
| `state.py` | `_robust_speed` → `robust_speed`, `_motion_state` → `motion_state` |
| `own.py` | `_OwnMotion` → `OwnMotion` |

## Risks
- `robust_speed` mutates `hist` in place (`hist[:] = ...`); the list is owned by `run_collision` (`ego_hist`): keep the in-place write.
- `motion_state` writes `tr.still_t0` (also written by `run_collision`): document both writers in the README (field-ownership table, Phase 4).
- `OwnMotion.classify` writes `own`, `own_ok`, `own_closing`, `near_pass`, `from_side`, `moving`, `approaching`, `receding`.

## Tests (Sonnet): `tests/engine/motion/test_motion.py`
- Identity; `OwnMotion` attribute list.
- `robust_speed`: in-place trimming of `hist` (same list object, pinned contents) for 3 windows.
- `motion_state` over the synthetic track histories of `tests/test_collision_v26116.py`: pin the returned states and `still_t0`.
- `OwnMotion` on the sequence `tests/test_collision_v26214.py` builds: pin the item fields per step.
