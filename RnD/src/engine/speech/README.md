# engine/speech -- phrases and when they are said

The speech policy of the Lab, moved out of `collision.py` (p3-12, p3-13). `SpeechPolicy` (state, priorities, the one-phrase-per-frame
`step`, predictive speech, events) lives in `policy.py`; its text, context-memory, known-wall and mover methods are mixins.
Imports only the stdlib and `engine.core`.

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
