# engine/tracking -- items to tracks

Per-frame items are followed across frames: track velocities (closing speed, sideways speed, bearing rate), the greedy
frame-to-frame matcher, and the coasting of movers that left the image. Imports only `engine.core.*`, numpy and its own modules.

**Fields written** (`engine.core.types.FIELD_WRITERS`): owns `Item.track_id`, `Item.closing`, `Item.settled`, `Item.role_run`, `Item.closing_raw`, `Item.prox_run`, `Item.present_run`, `Item.coasting`, `Item.unstable`, `Item.jumped`, `Track.id`, `Track.group`, `Track.class_name`, `Track.box`, `Track.last_t`, `Track.first_t`, `Track.last_distance`, `Track.last_lateral`, `Track.history`, `Track.closing`, `Track.contact_s`, `Track.present_run`, `Track.role`, `Track.role_run`, `Track.dhist`, `Track.lane_part`, `Track.prox_run`, `Track.context_seen`, `Track.d_prev`, `Track.d_prev_t`, `Track.df_prev`, `Track.df_prev_t`, `Track.jump_t`, `Track.under_last`, `Track.under_fired`; also writes `Item.distance_m`, `Item.lateral_m`, `Item.bearing`, `Item.clock`, `Item.pan`, `Item.clipped`, `Item.speak`, `Item.shape`, `Item.clock_q`, `Item.clock_text`, `Item.map_cells`, `Item.map_world`, `Item.image_dl`, `Item.srcsel`, `Item.full_ref`.

## API

| module | name | purpose | legacy |
|---|---|---|---|
| `velocity.py` | `closing_mps` | -slope of distance over time, history rows re-projected through the current horizon; None if too few points / too short / latest point near the horizon | `collision._closing_mps` |
| `velocity.py` | `depth_closing` | -slope of the metric depth history; latest point must be "now" | `collision._depth_closing` |
| `velocity.py` | `lateral_velocity` | sideways ground velocity (m/s, + right), own turn removed; needs a heading in every sample | `collision._lateral_velocity` |
| `velocity.py` | `cross_velocity` | velocity across the line of sight from the bearing rate; only used as a veto for "standing" | `collision._cross_velocity` |
| `match.py` | `match` | greedy matching `{item index: track id}`, same group + class + lane_part; IoU or the ground gate | `collision._match` |
| `coast.py` | `Coast` | movers that disappeared keep their last world velocity for a bounded time; `observe()`, `items()` | `collision._Coast` |

`engine/tracking/__init__.py` re-exports `Coast` and the four velocity functions. `match` is **not** re-exported (it
would shadow the submodule `engine.tracking.match`), nor are `coast` / `velocity` (no such functions exist). Import
`match` from `engine.tracking.match`.

## Inputs / outputs

- `closing_mps(history[(t, contact_y)], horizon, camera_height_m, gh, f, min_rows, min_span_s, min_points=3)`,
  `depth_closing(history[(t, depth)], t_now, min_span_s, min_points=3)`,
  `lateral_velocity(hist[(t, lat, dist, heading)], min_span_s, min_points=3)`,
  `cross_velocity(hist[(t, lat, dist, heading, bearing)], speed, window_s)`: all return `float | None`.
- `match(tracks, items, t, trk, pan_shift=0.0, people=frozenset())` -> `{item index: track id}`.
- `Coast(cfg)`; `observe(item, t, world)`, `items(t, seen, world, tracks, step_len, blocked=None, ext=None)` -> coasting
  `Item`s. `world` is read as `engine.core.pose.PoseLike` (`x, y, theta, speed, speed_t, hold_s`).

## Config keys read

- `tracking.iouMatch`, `tracking.groundGateLateralM`, `tracking.groundGateDistanceFrac` (required), `tracking.panMatchMinShift`
  (optional, 0.0) -- `match` (passed in as `trk`).
- `coast.enabled`, `seconds`, `vehicleSeconds`, `histSeconds`, `minPoints`, `minSpanSeconds`, `maxSpeedMps`, `maxRangeM`,
  `rematchRadiusM` (all optional with defaults) -- `Coast`.

## Invariants

- `match` builds pairs by iterating `tracks` in insertion order x items, then a stable sort by -score: ties depend on order.
- `Coast.hist` and `Coast._end` are touched from `run_collision` (`coast.hist.pop(...)`, `coast._end(...)`): keep both names.
  The attribute list (`on, seconds, vehicle_seconds, hist_s, min_points, min_span, max_speed, max_range, rematch, hist,
  last, active, episodes`) is pinned by tests.
- `Coast.items` mutates the matched `Track` (`last_t`, `last_distance`, `last_lateral`, `present_run`) in place.
- Legacy facade: `collision._closing_mps`, `_depth_closing`, `_lateral_velocity`, `_cross_velocity`, `_match`, `_Coast` are the
  same objects.

## Changelog lines (from the `collision.py` module docstring, unchanged there)

- "A track keeps contact *rows*; closing speed re-projects them through the current smoothed horizon, so horizon wobble
  cannot fake motion. Unknown movers count as static and never "approach"."
- v26.1.11: "**Only a collision course is a danger for a measured mover** (``_on_collision_course``): where it will be when we
  get there (closing speed, sideways velocity), not where it is now; vehicles are never context (``contextSpeak``)."
- v26.1.12: "**Motion states say nothing when unsure** (``_motion_state``): ... The bearing rate across the view
  (``_cross_velocity``) is too weak to name a direction; it only vetoes "standing"."
- Function docstrings carry the rest: v26.1.11 own sideways velocity (`lateral_velocity`), v26.1.12 review 5
  (`cross_velocity`), v26.1.16 review 8 pan-shifted matching and lane parts (`match`), v26.2.2 coasting (`Coast`).

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.5 Tracking

- Greedy matching within the same group **and** class. A pair matches if `iou(bbox) ≥ iouMatch` **or** the ground gate holds: `|Δlateral| ≤ groundGateLateralM` and `|Δdistance − expected| ≤ groundGateDistanceFrac × distance`, where `expected = −closing·dt` (0 if unknown). Score = IoU, plus 0.5 if the gate holds; highest first.
- **Pan-compensated person match (v26.1.16, review 8, 27.3 s).** `_match` gets the scene shift since the previous frame from the heading change (`−Δheading / hfov`, normalised x, capped ±0.25). For **people** (`classes.people`) and a shift of at least `tracking.panMatchMinShift` (0.04, a turn of ~5° per frame) the IoU is also taken against the track's box moved by that shift. At 27.2 s the head turned 9° in one frame: a person 5.7 m away jumped a full box width, lost its track three times in 0.5 s (age 0, no motion, confirmation restarting) and was announced 1.2 s late. The same hard pan makes the ego speed **unsettled** for `roles.panSettleSeconds` (1 s): a head turn throws the cadence off (2.09 against 1.2 m/s around 27 s), so the person read "standing" while crossing; now they get the plain phrase ("person at 11:45 in 8") at once. Poles, buildings and vehicles are not compensated (they are re-found by the ground gate; compensating them reshuffled the speech of reviews 3–7).
- A track survives `maxMissedSeconds` without a match. It keeps its contact **rows** (not distances) over `historySeconds`; a clipped detection clears the history.
- **Closing speed:** the (negative) slope of the distances obtained by re-projecting *all* history rows through the **current** smoothed horizon (so horizon wobble cannot fake motion). Points less than `motionMinRowsBelowHorizon` rows below the horizon are left out; it needs ≥ 3 points, ≥ `motionMinSeconds` of history and the latest point included; otherwise `None`. `closingMps` = raw closing × `k`.
- Per track: `present_run` (consecutive frames matched) and `role_run` (consecutive frames holding the same role). A track is `settled` after `MIN_TRACK_AGE_S` (v26.1.15: always during the first `WARMUP_S` of a run; `confirmFrames` = 2 still applies).


### 7.4 Items — coasting movers

- **Coasting movers** (v26.2.2, `coast.*`): a mover (`group "moving"`) measured for ≥ `minPoints` frames over ≥ `minSpanSeconds` (least-squares world velocity from the dead-reckoned pose) that disappears (out of frame, occluded, a segmentation dropout) is emitted as a predicted item (`coasting: true`, `clipped`, no outline) on its last world velocity for ≤ `seconds` (`vehicleSeconds` for vehicles). It keeps its track and motion state, is judged by the normal roles (collision course, beeps, proximity) but is never spoken (`speak` false); it ends on a rematch (the same track, or a new item of its class within `rematchRadiusM` + 10 % of range of the prediction), when passed (ahead ≤ 0), beyond `maxRangeM`, when the time is up, or inside solid. `hazards.json` top level `coast: {episodes: [{track, class, t0, t1, steps0, speedMps, moving, end}]}`.

### 7.11d v26.2.12 collision rules — distance jumps

- **Distance jumps** (`distance.jump`: `enabled`, `frac` 0.4, `minM` 1.0, `nearM` 15, `maxGapS` 0.4, `resetClasses` [vehicle, rider]): a track whose measured distance changes by more than max(`minM`, `frac` x the previous distance) between consecutive frames (nearer one <= `nearM`) is a measurement glitch. Its `jump_t` makes thin items / trees `unstable` (`thinStableS`), and for the `resetClasses` its closing history, along speed and motion state are cut (no "approaching" from a history across the glitch; a vehicle with unknown motion is judged with the static lane) and its coasting history is dropped. A second check on the FINAL distance (after the map / solid snap) feeds `thinStableS` only.
