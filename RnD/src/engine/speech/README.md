# engine/speech -- phrases and when they are said

The speech policy of the Lab, moved out of `collision.py` (p3-12, p3-13). `SpeechPolicy` (state, priorities, the one-phrase-per-frame
`step`, predictive speech, events) lives in `policy.py`; its text, context-memory, known-wall and mover methods are mixins.
Imports only the stdlib and `engine.core`.

**Fields written** (`engine.core.types.FIELD_WRITERS`): owns `Item.followed`, `Track.danger_done`, `Track.final_done`, `Track.feature_done`, `Track.thin_done`, `Track.approach_done`, `Track.said`; also writes `Item.distance_m`, `Item.lateral_m`, `Item.bearing`, `Item.clock`, `Item.steps`, `Item.mem_id`, `Item.mem_named`, `Item.mem_approach`, `Item.mem_danger`, `Item.clock_q`, `Item.clock_text`, `Track.mem_id`.

## API

| module | name | purpose | legacy |
|---|---|---|---|
| `text.py` | `TextMixin` | `_n`, `_join_clocks`, `_steps_txt`, `_fmt`, `_text`, `_plural`, `_kind`, `_entry`, `_words` (statics keep their decorators) | `collision.SpeechPolicy` methods |
| `context.py` | `ContextMixin` | `clear_context`, `_key`, `_known`, `_mem` (property), `_seen_before`, `_register`, `observe_context`, `surface_adopted`, `memory_if_spoken` | `collision.SpeechPolicy` methods |
| `walls.py` | `WallsMixin` | `note_wall`, `_known_wall` | `collision.SpeechPolicy` methods |
| `movers.py` | `MoversMixin` | `observe_movers`, `away_speech`, `motion_speech` | `collision.SpeechPolicy` methods |
| `policy.py` | `SpeechPolicy` | `__init__`, `_view`, `_voice`, `_reannounce`, `_closing_again`, `_zone_ok`, `_compose`, `_with_prediction`, `_feature_allowed`, `_motion_pending`, `_danger_recent`, `_gap_ok`, `_event`, `step`; class values `STATE_WORDS`, `LABEL_COOLDOWN_S` | `collision.SpeechPolicy` (same object) |
| `walls.py` | `followed_wall(it, t, state, cfg)` | True = a beep driver is a wall being walked along (no new beep episode) | `collision._followed_wall` |
| `walls.py` | `WallFollow(cfg)` | per-track distance history; `advance`, `observe` (writes `it.followed`), `quiet`, `candidate`, `beeped` | `collision._WallFollow` |
| `walls.py` | `passing_close(it, cfg)` | a closing mover passing close outside the lane gets the soft sound | `collision._passing_close` |

`engine/speech/__init__.py` re-exports all of them (`__all__`). No function shares a name with a submodule.

## Composition

`engine.speech.policy.SpeechPolicy` is `class SpeechPolicy(TextMixin, ContextMixin, WallsMixin, MoversMixin)` (`collision.SpeechPolicy` is the same object); its `__init__` is unchanged and
sets every attribute the mixins read. The mixins have no `__init__` and no class-level values; they declare the
attributes they read as bare annotations (for mypy only, so `__new__`-built policies in tests keep the same state).
`STATE_WORDS` and `LABEL_COOLDOWN_S` stay class attributes of `SpeechPolicy`. No method name is defined in two mixins.

## Config keys read

Through the policy's own attributes (`cfg` = the `speech` block): `templates` (`approachFast`, `approachSide`, `multi`,
`thinNotice`, ...), `contextMemory.forgetAfterSeconds`, `speech.knownWall`, `beeps.follow.classes`. The free functions
and `WallFollow` read the `beeps.follow` / `beeps.passing` dicts passed in. `SpeechPolicy.__init__` also reads `speech.{contextMaxItems,maxEntries,
thinRearmSeconds,featureLabelGapSeconds,featureNewCrossingSteps,peopleMotionWait*,predictive,minVoiceSteps,zoneOnly,reannounce,colocatedM,away}`,
`roles.{finalSteps,confirmFrames,thinNotice*,contextAfterDangerSeconds}`, `classes.landmark`, `contextSpeak`, `geometry.laneHalfWidthM`, `motion.{enabled,againSteps,againGapS,cut,ahead}`.

## Invariants

- `collision.SpeechPolicy._text is engine.speech.text.TextMixin._text` (and every other moved method); the three free
  names on `collision` are the same objects as `followed_wall`, `WallFollow`, `passing_close`.
- MRO: `SpeechPolicy, TextMixin, ContextMixin, WallsMixin, MoversMixin, object`.
- `world.mark_said(mem_id, steps, t)` replaces the two `world.entries[id]["said"] = (steps, t)` writes (same tuple); the `said` read stays on `entries`.
- `step` stays one function.
- `WallFollow.observe` writes `it.followed`.
- Moved code is verbatim; only `_Item` / `_Track` became `Item` / `Track` annotations, `_WorldMemory` became `ObjectMemory`, and the two `said` writes became `mark_said`.

## Changelog lines (from the `collision.py` module docstring)

> * **v26.2.12** `beeps.follow`: a wall the user walks along does not start a new beep episode.
> * **v26.2.13** `beeps.follow.windowS` (`WallFollow`), `beeps.passing`, `speech.knownWall`.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.10 Speech policy  (class `SpeechPolicy`)

At most **one phrase per frame**. Priority: final > danger/feature/thin notice (one combined phrase) > surface > context. Only the highest class that has candidates is considered, so a waiting danger is never overtaken. Context and surface are held back while any confirmed danger track is active.

**Gaps:** final ignores the gap. Feature phrases wait for `priorityMinGapSeconds` after the previous danger/feature/final phrase (a context phrase never delays them). A phrase that contains a danger entry (v26.1.15, review 7: a person was held 0.8 s behind a pole) waits only for the previous danger/final phrase: a feature or context phrase never delays a danger. Context and surface wait for `globalMinGapSeconds` after any phrase.

**Templates** (`speech.templates`; `{clock}` is the quarter clock text, `clock_text`: `12`, `12:15`, `11:45`, `1:30` … from 9 to 3; no "o'clock"):

| Key | Template |
|---|---|
| `context`, `feature`, `danger`, `final` | `{label} at {clock} in {steps}` |
| `standing` | `{label} standing at {clock} in {steps}` (person, animal) |
| `stopped` | `{label} stopped at {clock} in {steps}` (cyclist) |
| `approach` | `{label} approaching at {clock} in {steps}` (people: with the distance, v26.1.13) |
| `approachFast` | `{label} approaching at {clock}` — riders and vehicles: **no distance**: at their speed the number means nothing |
| `receding` | `{label} moving away at {clock} in {steps}` (v26.1.13: with the distance) |
| `surface` | `{label}` |
| `contextGroup` | `{items}` (items = context entries joined by `", "`) |
| `multi` | `{label} at {clocks} in {steps}` |
| `thinNotice` | `{label} at {clocks} in {steps}` |

`{clocks}` lists the distinct quarter clocks left to right (by quarter index): `"1"`, `"12:45 and 1:30"`, `"10, 12 and 2"`. Every announced object has a position and (unless the distance is unknown, or it is a rider / vehicle "approaching") steps.

**Motion words (v26.1.11, "need to know if static, approaching or moving away"; v26.1.13).** A danger/final item's phrase kind is chosen per item: a mover with state `approach` → `approach` (people with the distance, `approachFast` for riders and vehicles, which also use it for any danger of theirs, e.g. one crossing sideways); a person measured walking away → `receding`; a person (cyclist: `stopped`) measured standing → `standing`; motion not measured yet, unsure (§7.8) or ego speed unknown → the plain `danger` / `final` phrase. **v26.1.15:** the three state words (`standing` / `stopped`, `moving away`, and `approaching` of a person) are used only when the ego speed is *settled* (§7.6); until then the plain phrase is said at once, with no motion wait. A rider / vehicle `approach` keeps its word without it (it closes at several m/s: a ramping ego speed does not change that, and the warning must not wait 3 s). **v26.1.16 (rule 8):** `approach` for a rider / vehicle needs a settled ego speed **or** `own_fast` (`closing − maxWalkingMps ≥ approachingMps`, i.e. faster than anyone could walk); otherwise they get the plain phrase. The early cyclist warnings (review 6) are unaffected (they close at 4+ m/s).

**Re-announcement (v26.1.12, review 5 at 76.5 s).** A mover announced before (plain, "standing" or "moving away") is announced **once more** when its kind becomes `approach` (`person approaching at 12:15 in 9`): `_Track.approach_done` is set by any phrase that said "approaching"; this is the only re-announcement. The label gap (`LABEL_COOLDOWN_S`) and the world memory (`mem_approach`) still apply. Items are grouped by (label, kind): `person standing at 1 and 2 in 7` (several clocks use `multi` with the state word in the label), `person approaching at 12 and 2 in 9`.

1. **Final** — a confirmed, settled danger track with urgency `final` that has not had one yet. Once per track; ignores the global gap; the template is `final`. **v26.1.16 (rule 6, review 8, 10.9 s: "collision and danger supersede notify-once"):** it is spoken unless the object is already in the world memory **with an earlier danger / final call** (`entry.danger`); having been named as context or feature (or covered by a thin notice) no longer mutes it, and the same holds for danger entries below. **Rule 9b:** a final for a *never-named* (`!mem_named`) non-thin static thing that has been a context item (`_Track.context_seen`: vegetation, a wall) within `contextAfterDangerSeconds` of a danger activity is consumed silently (the beeps carry it; review 8, 107.0 s). *Before v26.1.16:* it was spoken only if the object is not already in the world memory (§7.11, any entry, named or not) — something that appeared suddenly close. Otherwise the slot is consumed silently (pacing as if spoken) and the beeps carry the proximity. If a danger track is already within `finalSteps` when first announced, only the final call is made.
2. **Danger + feature + thin notice in one phrase** (at most `maxEntries` entries; danger first, then features — crosswalks before curbs, then by steps — then the thin notice):
   - *Danger entries:* confirmed danger tracks not yet announced, label not announced in the last `LABEL_COOLDOWN_S`, and not waiting for motion (a person with unknown motion, farther than `peopleMotionWaitSteps`, for up to `peopleMotionWaitSeconds` after becoming a danger; **v26.1.15: only once the ego speed is settled**, see below). Grouped by (label, kind) (see the motion words): same-label items of one kind merge into one entry with their clocks and the **nearest** item's steps (`person standing at 1 and 2 in 4`, `person approaching at 12 and 2 in 9`). Danger entries need `speak` (a person under 5 steps is a silent danger).
   - *Feature entries:* confirmed feature tracks not yet announced and allowed by the label gap (`featureLabelGapSeconds`, or `featureNewCrossingSteps` further along the walk; crosswalk: 20 s / 20 steps, curb: 20 s / 24 steps — once per crossing). Position along the walk = steps ahead plus steps walked so far. This keeps fragments of one curb, re-tracked under new ids, quiet.
   - *Thin notice:* (never while the user is stationary) thin objects (poles, lights, signs) present for ≥ `confirmFrames` frames, within `thinNoticeSteps` and `thinNoticeLateralM`, not already a danger entry: one entry per label, plural if several (`poles at 11 and 1 in 8`, steps of the nearest). Said **once**: afterwards the notice is disarmed while any thin object is noticed; it re-arms after `thinRearmSeconds` with none noticed, or on a path change. The whole thin cluster in view counts as warned about.
   - The phrase's role is `danger` if it contains a danger/approach entry, else `feature` (also for a thin-only phrase). Its clock/trackId/pan come from the leading item.
   - Danger and feature tracks are marked announced only when they enter a phrase; each is announced once.
3. **Surface** — a pending adopted-surface change (§7.14): `{label}`, e.g. "road".
4. **Context** — grouped, label-level:
   - Candidates: items with role `context` whose label is in `contextSpeak`, from settled tracks (see the start summary below), one per label family, the nearest (vehicles are not in `contextSpeak`, §6). A label already in the **label memory** is skipped; the memory refreshes while the label is seen (context/danger static-like items), is forgotten after `contextMemory.forgetAfterSeconds` unseen, and is cleared on a path change. A danger/final phrase naming a `contextSpeak` label also puts it in the memory. Context is held until a surface is adopted, or `surfaces.debounceSeconds` since the start.
   - **No context among dangers (v26.1.16, rule 9, review 8, 107.0 s):** while a confirmed danger is active, and for `contextAfterDangerSeconds` (2.5 s) after the last danger / final **phrase** or **collision-beep stream** (≥ 2 frames in a row; one pass-by beep does not count: the building at 2 steps right after a passing person's first beep at 6.2 s was ticked), no context phrase is spoken and the pending candidates restart their delay. Surfaces and features are not held back. (Rule 9b for finals: §7.10 item 1.)
   - A candidate that cannot be spoken because of the gap stays pending, but is dropped (treated as known) after `contextMaxDelaySeconds`.
   - All newly announceable labels, nearest first, at most `contextMaxItems`, form **one phrase**: `contextGroup` of the `context` entries: `"obstacle at 12 in 5, building at 2 in 8"`.
   - **Start summary:** the first context phrase of a run, and the first after a path change, needs only confirmation (no track age, no adopted surface), is held `summaryHoldSeconds` so the first view becomes one phrase, and ends `WARMUP_S` after it began (once a surface is known). The run's very first summary also admits items beyond `contextMaxLateralM`.
5. **World memory** (§7.11) filters 1, 2 and 4: objects already remembered are not announced again; when nothing is left, the slot is consumed silently. Without motion data the track and label rules above apply unchanged.


### 7.11c Collision source and predictive speech — predictive speech

- **Predictive speech** (`speech.predictive.enabled` true default, `startLatencyS` 0.2, `wordsPerSecond` 2.8 at rate 1, `minSteps` 1, `passedM` 0.3, `maxMoverMps` 12; Lab override `speech.predictive.enabled`): a phrase (final, danger / feature / thin, context) is built on today's positions, its duration `dt` = latency + words / (wordsPerSecond x the sound profile's `speechRate`) (words = whitespace tokens, commas ignored), then built once more on every item's position at `t + dt`: we walk straight ahead at the calibrated ego speed (0 stationary; unknown speed = no prediction), static-like items stay, a mover with a trusted, moving world track keeps its velocity (`pred_v`, in both source modes), steps scale with the distance, the clock follows the bearing. An item whose predicted forward < `passedM` is dropped from the phrase; a phrase with nothing left consumes its slot silently (the beeps carry it). The event keeps `clock` / `clockText` / `pan` of today and gets `predicted: {dt, steps, clock, fwd, right, stepsNow, textNow}` (lead item; `textNow` = the unpredicted phrase). Beeps are untouched. `settings.predictive` = {phrases, changed, dropped}. 2.8 words/s is a guess (no client log carries speak start / end times).

### 7.11d v26.2.12 collision rules — voice, predictive, followed and known walls, moved away

- **Voice (`speech.*`):** `minVoiceSteps` 2: a beeping item (collision danger / final) whose spoken steps (the predicted ones when the phrase is predicted) are <= 2 is left out of the phrase, a phrase with nothing left is not said (the beeps stay). `zoneOnly` {`enabled`, `halfWidthM` 0, `classes`}: pole, sign, traffic sign, traffic lights, sidewalk-obstacle, utility-cover are spoken as thin notices / context only when `collision` is true NOW (the current position, not the predicted one). `thinStableS` 0.5: a thin item (or tree) whose distance jumped between consecutive frames (see `distance.jump`) is not spoken until it was stable that long. `reannounce` {`enabled`, `clockQuarters` 4, `growSteps` 3, `minGapS` 1}: a static collision item announced before is announced again (bypassing the label cooldown and the "already named" memory) when its clock moved >= 4 quarter-hours or its steps grew by >= 3 since the last phrase for the track (`_Track.said`). `colocatedM` 1.5: collision items (and the thin notice of the same marker) within that distance of a CLOSER item of the same phrase are consumed with it: one phrase with the closest item's label, clock and steps.
- **Predictive (`speech.predictive`):** `maxAdvanceM` 1.5 caps how far the phrase moves an item toward us (the item is still dropped as passed on the uncapped advance); `clockHoldQuarters` 2: when the predicted clock differs from today's by more than that, today's clock is said; `measuredFloor` 0.5 / `measuredWindowS` 1.5: the advance speed is min(cadence speed, the median closing speed of the static pole-like witnesses over the window), at least 0.5 x the cadence speed (`SpeechPolicy.ego_meas`).
- **Followed walls** (`beeps.follow`: `enabled`, `followQuietS` 6, `lateralM` 0.4, `nearSteps` 1, `gapS` 1.5, `classes`): a beep driver that is a building / wall / fence face on one side (left: clock <= 11:30, right: >= 12:30; the centre never) more than `nearSteps` away, with a real beep episode of the same family and side within `followQuietS` seconds whose lateral it matches within `lateralM`, does not start a new episode (`_followed_wall`; matched by family + side + lateral, not by track id; the memory is the last REAL beep, so a wall followed for longer beeps again).
- **Walls being followed, v26.2.13** (`beeps.follow` `windowS` 1.5, `minCloseRatio` 0.4, `minWalkM` 0.4, `minSpanS` 0.5, `gapMaxS` 0.7, `jumpM` 3, `besideS` 5, `recentS` 4.5): a building / wall / fence item, any clock, whose distance over the last `windowS` closed by less than `minCloseRatio` × the distance walked (the nearest value of the window's older half; history restarts on a gap > `gapMaxS` or a jump >= `jumpM`; >= `minWalkM` walked, >= `minSpanS` of history) is **followed** when its track was seen for `besideS` or a wall beep was due within `recentS`: it starts no beep episode and gets no phrase, except at <= `nearSteps` (final). A suppressed phrase still takes the speech slot once per track (silently).
- **Known walls** (`speech.knownWall`: `enabled`, `windowS` 30, `worldM` 2, `relativeS` 12, `steps` 1.5, `quarters` 1): a wall phrase is not said when a wall phrase / beep episode of the same family in the last `windowS` was at a world point within `worldM`, or in the last `relativeS` at the same relative place (steps ± `steps`, clock ± `quarters`); a suppressed phrase keeps the wall known for 1 s more.
- **Moved away** (`speech.away`: `enabled`, `recentS` 2, `marginM` 0.2, `minLatMps` 0.2, `latWindowS` 0.4, `minGrowM` 0.3, `maxClosingMps` 1, `staticS` 1, `confirmMovingS` 0.8, `cooldownS` 10, `templates`): an item that was a collision danger (or beeped) in the last `recentS` and leaves the lane by its own motion (|lateral| > lane half + `marginM` with lateral speed >= `minLatMps` away from the axis over `latWindowS`, or its distance grows by `minGrowM`; not closing faster than `maxClosingMps`; it stays out) is said once per track per `cooldownS`, role danger: "person at 12:30 moved away", or, when it stood still for `staticS` before, "person at 12:30 started walking away" ("started moving away" for non-people). The clock is where it was last a danger.
