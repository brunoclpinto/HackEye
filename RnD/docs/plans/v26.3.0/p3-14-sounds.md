# p3-14 engine.sounds

## Moves (collision.py → engine/sounds/tones.py)
`COLLISION_KINDS`, `SOUND_KINDS`, `SIDE_WORD`, `collision_kind`, `resolve_sounds`, `_tone_interval` → `tone_interval`, `_tone_events` →
`tone_events`, `_crosswalk_tones` → `crosswalk_tones`.

## Risks
- `resolve_sounds` is also called by `lab.sounds` through `collision`: unchanged (same object).
- `tone_events(frame_collision, times, tones_cfg, frame_proximity, cw_marks, sounds)` positional; 17 pinned uses.

## Tests (Sonnet): `tests/engine/sounds/test_tones.py`
- Identity of all eight names.
- `resolve_sounds` with and without a profile; `tone_interval` table; `tone_events` + `crosswalk_tones` on the inputs of the existing
  `_tone_events` tests: pin the event lists.
