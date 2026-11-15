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
