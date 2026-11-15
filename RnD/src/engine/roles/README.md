# engine/roles -- what each item is to the wearer

Decides the role of one item (`danger` / `context` / `feature` / `none`), its urgency, whether it is a collision (beep),
the summary and proximity flags, with the predicates behind it. Imports only the stdlib and `engine.core` (`Item`,
`POINT_ASPECT`).

## API (`roles.py`, re-exported by `__init__.py`)

| name | purpose | legacy |
|---|---|---|
| `speed_witness(it)` | can this item tell us our own speed (a pole-like item with a raw closing speed) | `collision._speed_witness` |
| `pole_like(it)` | static, tall and thin (`h >= POINT_ASPECT * w`), not clipped, not along the path, not a lane part | `collision._pole_like` |
| `is_static_like(it)` | static things and vehicles of unknown / stationary motion; people are never static | `collision._is_static_like` |
| `not_approaching(it, ego_speed_raw)` | a "closing" object whose contact row stays put while we move (end of a line along the path) | `collision._not_approaching` |
| `sideways_mps(it, roles)` | the sideways velocity if above `lateralVelDeadbandMps`, capped by `lateralVelMaxMps`, else 0 | `collision._sideways_mps` |
| `course(it, roles)` | `(time to meet, lateral position at the meeting)` of a closing mover, else None | `collision._course` |
| `on_collision_course(it, roles)` | the meeting is within `courseMaxSeconds` and `beepLateralM` | `collision._on_collision_course` |
| `fast_warning(it, roles)` | a rider / vehicle reaches us within `fastWarnSeconds` inside `movingLaneHalfWidthM` | `collision._fast_warning` |
| `assign_role(it, span, roles, lane_half_m, step_length_m, stationary=False)` | writes the role fields (below) | `collision._assign_role` |

## Inputs / outputs

- All predicates are pure reads of item fields.
- `assign_role` **writes** `role, urgency, collision, summary_ok, proximity` (first statement) and, for a near-pass
  person, `speak`; `urgency` is set to `final` / `danger` at the end for a danger. It reads `map_cells` / `map_judged`
  (written by the static map) as fields only; `stationary` is unused.

## Config keys read (`roles` block, passed as a dict)

`dangerSteps`, `finalSteps`, `minObstacleAreaM2`, `contextMaxDistanceM`, `contextMinAreaFraction`, `contextMaxSteps`,
`contextMaxLateralM`, `contextNearSteps`, `contextNearLateralM`, `movingLaneHalfWidthM`, `beepLateralM`,
`peopleSpeakMinSteps`, `peopleSpeakLateralM`, `movingDangerSteps`, `proximitySteps`, `proximityLateralM`, `landmarkSteps`,
`featureSteps`, `featureMinLaneCover`, `lateralVelDeadbandMps`, `lateralVelMaxMps`, `courseMinClosingMps`,
`courseMaxSeconds`, `fastWarnMaxM`, `fastWarnSeconds`.

## Invariants

- The nine `collision._<name>` aliases are the same objects as the engine ones.
- The first line of `assign_role` resets its fields in one statement; verbatim.
