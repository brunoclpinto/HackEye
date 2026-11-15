# engine/sounds -- what the wearer hears

Sound kinds, the Lab-wide sound profile, the parking-sensor collision beeps, the soft proximity chirp and the crosswalk
enter / exit tones, as tone events plus "beeps" episodes for the timeline. Imports only the stdlib, numpy and
`engine.core` (`Item`).

**Fields written:** none (`Item` / `Track` fields, `engine.core.types.FIELD_WRITERS`).

## API (`tones.py`, re-exported by `__init__.py`)

| name | purpose | legacy |
|---|---|---|
| `COLLISION_KINDS` | `collision-left / -center / -right` | `collision.COLLISION_KINDS` |
| `SOUND_KINDS` | collision kinds + `crosswalk-in`, `crosswalk-out`, `proximity` | `collision.SOUND_KINDS` |
| `SIDE_WORD` | kind -> `left` / `center` / `right` | `collision.SIDE_WORD` |
| `collision_kind(quarter, center_quarters=1)` | sound kind from the item's clock quarter (11:45-12:15 is center) | `collision.collision_kind` |
| `resolve_sounds(tones_cfg, profile=None)` | `tones.sounds` defaults overridden by the profile, clamped to `soundRanges` | `collision.resolve_sounds` (also used by `lab.sounds`) |
| `tone_interval(steps, by_steps)` | beep interval, linear interpolation by steps, clamped at the table ends | `collision._tone_interval` |
| `tone_events(frame_collision, times, tones_cfg, frame_proximity, crosswalk, sounds)` | `(tone events, beeps episodes)` | `collision._tone_events` |
| `crosswalk_tones(marks, cfg, other_marks, kinds)` | crosswalk-in / -out tone events and episodes | `collision._crosswalk_tones` |

## Inputs / outputs

- `tone_events` reads items (`track_id`, `steps`, `clock_q`, `urgency`, `pan`, `label`, `clock_text`) and returns plain
  dict events (`type: "tone"`) and episodes (`type: "beeps"`); it never mutates its inputs.
- A collision stream is phase-continuous, driven by the nearest collision track per frame, with `holdSeconds` for a track
  lost from view. Proximity never plays while a collision stream is active. Crosswalk tones wait out a busy tone, at most
  `maxOffsetSeconds`.

## Config keys read (`tones` block)

`sounds`, `soundRanges`, `speechRate`, `maxSteps`, `bySteps`, `holdSeconds`, `continuousSteps`, `continuousChunkSeconds`, `episodeGapSeconds`, `centerQuarters`,
`crosswalk` (`in` / `out`: `count`, `gain`, `attackSeconds`; `maxOffsetSeconds`), and the proximity keys (see `tones.py`).

## Invariants

- The eight `collision.<name>` names are the same objects as the engine ones.
- The legacy private names (`_tone_interval`, `_tone_events`, `_crosswalk_tones`) stay on `collision`.
