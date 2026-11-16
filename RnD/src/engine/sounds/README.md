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

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.13 Beeps (parking-sensor)

- **Who:** only a **collision** track: a confirmed, settled danger with `collision = true` and `stepsTo ≤ tones.maxSteps` (**5**, v26.1.12: farther away the speech carries the warning). v26.1.13: on a real collision course only, `beepLateralM` (0.9 m, §7.9): people at 1.2–3.0 m no longer beep. The single nearest one drives the beeps each frame. Features, context and non-collision dangers never beep. Beeps are independent of the world memory and of muted phrases.
- **Sound:** the pitch and duration are those of the tone's **kind** (below, §7.16: left 660 Hz, center 880 Hz, right 1100 Hz, 80 ms by default); the interval is linearly interpolated from `bySteps` by `stepsTo` (clamped at the table ends) and scaled by `intervalS / bySteps(maxSteps)` of the kind (the profile's interval is the one at 5 steps; 0.5 s = the table as it is). A faster stream does not wait out a slower previous interval.
- **Very close:** at `stepsTo ≤ continuousSteps` a continuous tone: gapless back-to-back tone events of `continuousChunkSeconds` (not scaled by the interval; the events carry `"continuous": true` and the player keeps their length whatever the profile's duration).
- **Stopping:** the beeps stop when the track stops being a collision (passed, left the lane). A track that is merely absent from a frame keeps beeping for `holdSeconds`.
- **Episodes:** per continuous stream of one track (gap < `episodeGapSeconds`) the output also contains one `beeps` event (§7.15).
- **Kinds (v26.1.16).** Every `tone` and `beeps` event carries `kind`, one of the six sound kinds: `collision-left` / `collision-center` / `collision-right` (the parking beeps above; before v26.1.16 `collision`), `proximity` (v26.1.13 follow-up, below), `crosswalk-in` / `crosswalk-out` (v26.1.14, last bullet; before v26.1.16 `crosswalk-enter` / `-exit`; the player still maps the old names so that old runs sound the same).
  - **Sector of a collision tone** (`collision_kind`): from the **clock quarter** of the driving item at that tone (`tones.centerQuarters` 1): **center** = 11:45–12:15 (quarters −1…+1), **left** = 9:00–11:30 (≤ −2), **right** = 12:30–3:00 (≥ +2). The user wrote left "9:00–11:45" and right "12:15–3:00"; the shared boundaries 11:45 and 12:15 belong to the center. An item that changes sector switches kind per tone, and its episode is split there (`beeps` episodes are per track **and kind**); the episode text is `beeps · <left|center|right> · <label> at <clockText> · <first>→<min> steps`. The stereo `pan` by bearing is unchanged.
  - **Who gets `proximity`:** a person or animal (`_Item.proximity`, set in `_assign_role`; no role, so speech and context are untouched) that is measured **approaching** (motion state, not unknown / standing / receding), within `proximitySteps` (5) and \|lateral\| ≤ `proximityLateralM` (2.6 m), on **no collision course**, confirmed for `confirmFrames` frames. Riders and vehicles never (they are spoken early and beep on a course). Not while we stand still.
  - **Sound:** `tones.proximity`: 440 Hz sine, gain 0.25, a slow attack, one **double chirp** (`chirp.count` 2 sines of `durationSeconds`, `chirp.gapSeconds` apart) every `intervalSeconds` (the profile's `intervalS`, 1.2 s), a fixed rhythm (it does not encode distance; speech did at 5–10 steps). The `tone` event carries `frequencyHz`, `gain` and `chirp`; the nearest such person drives the stream, a lost track holds for `holdSeconds`.
  - **Switching:** the two never play at once. While a collision stream is active (held tracks included) no `proximity` tone is emitted; a track that turns into a collision course continues as collision beeps. Episodes are per kind and track; the `proximity` episode text is `soft · <label> at <clockText> · <first>→<min> steps`.
- **Crosswalk enter / exit (v26.1.14, `_CrosswalkTracker`, `_seed_fraction`, `_crosswalk_tones`).** A sound for stepping onto and off a crosswalk.
  - **State:** per frame the share of `crosswalk`-class cells in the **seed box** (`surfaces.seedBox`, bottom centre: what is under the feet; a crosswalk merely seen ahead never counts, and a crossing that runs along the walking direction keeps counting). **In:** share ≥ `crosswalk.enterFraction` (0.3) for `enterSeconds` (0.5 s) without a break, never while the user stands still (`stationary` restarts the hold). **Out:** share ≤ `exitFraction` (0.15) for `exitSeconds` (0.7 s) without a break (also while standing). Between the two levels the state holds, so a gap between stripes does not end a crossing. The decision frame is the event time.
  - **Sound (`tones.crosswalk`, kinds `crosswalk-in` / `crosswalk-out`):** 330 Hz by default (collision 660–1100, proximity 440), gain 0.5 (the collision peak). `crosswalk-in`: one tone of 600 ms (`in.count` 1). `crosswalk-out`: the same deep tone twice, 200 ms each, `intervalS` (0.12 s) apart. The `tone` event carries `frequencyHz`, `durationSeconds`, `gain` and `chirp` {count, gapSeconds, attackSeconds}, `role: "feature"`, `pan 0`. Each has one `beeps` episode (`kind` the same, `tEnd` = end of the sound, text `⇥ crosswalk in · one deep tone` / `⇤ crosswalk out · two deep tones`) for the review panel and the timeline.
  - **Overlap:** never dropped. A crosswalk tone that would sound over a collision or proximity tone waits for it to end, at most `maxOffsetSeconds` (0.3 s).
  - The speech phrase "crosswalk at 12 in N" is unchanged; the surface logic and its evidence (`under_last`) are unchanged.
