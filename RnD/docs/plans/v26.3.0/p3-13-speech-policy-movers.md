# p3-13 engine.speech: movers + policy

## Moves (collision.py → engine/speech/)
| module | symbols |
|---|---|
| `movers.py` | `class MoversMixin`: `observe_movers`, `away_speech`, `motion_speech` |
| `policy.py` | `class SpeechPolicy(TextMixin, ContextMixin, WallsMixin, MoversMixin)`: `__init__` and every remaining method (`_view`, `_voice`, `_reannounce`, `_closing_again`, `_zone_ok`, `_compose`, `_with_prediction`, `_feature_allowed`, `_motion_pending`, `_danger_recent`, `_gap_ok`, `_event`, `step`) |

`collision.SpeechPolicy is engine.speech.policy.SpeechPolicy`. `step` stays one function (audit 1.2).

## Sanctioned edits (plan decision 4)
- `self.world: _WorldMemory | None` → `self.world: ObjectMemory | None`.
- The two writes `self.world.entries[<id>.mem_id]["said"] = (<x>.steps, t)` → `self.world.mark_said(<id>.mem_id, <x>.steps, t)`.
  `mark_said` stores exactly the same tuple (p2-12).
- The read `self.world.entries.get(it.mem_id, {}).get("said")` stays verbatim: `said_at` raises on a missing id, the read does not.

## Risks
- `id()` keys inside `_compose` are call-local: verbatim.
- Driver-written attributes (`world`, `motion_on`, `speech_rate`, `travel_steps`, `stationary`, `ego_u`, `ego_meas`, `last_beep_t`) and
  driver-read ones (`confirm`, `pred_on`, `pred_meas_floor`, `quiet_t`, `cfg`, `pred_stats`) are created in `__init__`: unchanged.
- `tests/test_collision_v26116.py` assigns `policy.world = world` with a real `_WorldMemory`: `mark_said` exists on it.
- The biggest move of the phase: the quick equivalence check must stay at 0 violations.

## Tests (Sonnet): `tests/engine/speech/test_policy.py`
- Identity of the class and of the movers methods; MRO `SpeechPolicy, TextMixin, ContextMixin, WallsMixin, MoversMixin, object`.
- Sorted `vars(SpeechPolicy(CONFIG))` keys (the attribute list).
- A 40-tick `step` sequence on the review-11 fixture window (as `tests/replay.py` drives it, or a reduced driver from the existing policy
  tests): pin the spoken texts and their times per tick.
- `mark_said` path: after a tick that speaks a remembered item, `world.entries[mem_id]["said"] == (steps, t)`.
