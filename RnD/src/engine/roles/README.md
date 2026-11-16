# engine/roles -- what each item is to the wearer

Decides the role of one item (`danger` / `context` / `feature` / `none`), its urgency, whether it is a collision (beep),
the summary and proximity flags, with the predicates behind it. Imports only the stdlib and `engine.core` (`Item`,
`POINT_ASPECT`).

**Fields written** (`engine.core.types.FIELD_WRITERS`): owns `Item.steps`, `Item.label`, `Item.role`, `Item.urgency`, `Item.family`, `Item.summary_ok`, `Item.speak`, `Item.collision`, `Item.proximity`, `Track.lp_strong_t`, `Track.feature_frames`.

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

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.7 Steps

`stepsTo = distanceM / stepLengthM` (the stored per-recording length, else `priorStepLengthM`). Spoken as `round(stepsTo)`, at least 1 (`"1 step"` for 1, else the number); `stepsTo` is kept with 1 decimal in JSON. Steps are *not* divided by the instantaneous ego speed (that made them jump). Distances are real-world thanks to the scale (§7.3). Steps are omitted from a phrase only if the distance is unknown (the `" in {steps}"` part is dropped).

### 7.9 Roles  (one per item per frame)

- **danger**
  - *Static, or a vehicle with `moving ≠ true` (measured parked, or unknown while ego speed is unknown):* component area ≥ `minObstacleAreaM2`, `lane_hit`, not running along the path, `stepsTo ≤ dangerSteps`. On a collision course (`collision = true`). A wall-like item judged on the map (§7.4, `staticSource: "map"`; under `"image"`: the **lane part**) is a lane hit when the face / edge test calls it a face (its image lane hit is ignored); a ghost (§7.4) is judged as the item it copies.
  - *Rider / vehicle measured approaching* (`classes.fast`, `moving = true`, v26.1.13, review 6 at 191.5 / 445.3 s: "warn as soon as possible, the 10-step rule does not apply to cyclists or vehicles on or close to a collision course"): in the row span, area ≥ `minObstacleAreaM2`, not receding, `|lateral|` now within `movingLaneHalfWidthM` (rider) or `laneHalfWidthM + 1.0` (vehicle), the gap closes (`closingMps ≥ courseMinClosingMps`), we meet within `fastWarnSeconds` (6 s: `T = distance / closing`), `distanceM ≤ fastWarnMaxM` (30) and the predicted `|lateral + lat_vel × T| ≤ movingLaneHalfWidthM` (3.0): a **danger with no step limit**, spoken `"cyclist approaching at 11"` (no distance). `collision` only when also `T ≤ courseMaxSeconds` and the predicted `|lateral| ≤ beepLateralM` (0.9): a cyclist passing at 1.9 m is announced, not beeped. A vehicle driving across the crosswalk ahead is far to the side now and silent (review 4, 39.0 s).
  - *People (person, animal; a rider who is not coming at us counts too)* (v26.1.13, review 6): `course` = measured mover: `on_collision_course` (closing, `T ≤ courseMaxSeconds`, predicted `|lateral| ≤ beepLateralM`, not receding); standing / unknown: `|lateral| ≤ beepLateralM`. In the row span (or no region), area ≥ `minObstacleAreaM2`, `stepsTo ≤ movingDangerSteps`:
    - `stepsTo ≥ peopleSpeakMinSteps` (4.5) and `|lateral| ≤ peopleSpeakLateralM` (2.75): **danger, spoken once, whatever the direction** (approaching, moving away, standing, unknown: "good to know someone is there"), with the distance; `collision = course`.
    - closer than that: only if `course`: a **silent danger** (`speak = false`, `collision = true`): no phrase, not even a final; beeps only. Otherwise `none`.
    - unknown motion and a person measured approaching at arm's length no longer beep (v26.1.12 did; review 6: four beep entries at 1.2–3.0 m were "not on a collision course").
  - `urgency` = `final` if `collision` and `stepsTo ≤ finalSteps`, else `danger`.
  - **While stationary** (§7.6) only a measured mover on a collision course keeps its danger role; everything else is `none`.
- **feature** (curb, crosswalk, pothole)
  - *Landmark* (crosswalk): touches the walking region, not clipped, `stepsTo ≤ landmarkSteps`. It need not cross the lane.
  - *Others:* `lane_hit`, not running along the path, not clipped (not already under the feet), `lane_cover ≥ featureMinLaneCover`, `stepsTo ≤ featureSteps`. A curb or median running alongside the path stays silent.
  - A track that held the feature role with `lane_hit` and not along the path for `confirmFrames` frames has "crossed the lane": only such a curb/crosswalk can be surface evidence (§7.14).
- **context:** a static/parked item that is not danger, `touches` the dilated region, `distanceM ≤ contextMaxDistanceM`, area ≥ `contextMinAreaFraction`, `distanceM ≤ contextMaxSteps × stepLength`, and `|lateral| ≤ contextMaxLateralM` (v26.1.13: 2.5 m; within `contextNearSteps` 3.0 m). (An item that fails only the lateral limit is allowed in the very first start summary of a run.) People never get `context`.
- **none:** everything else (still listed in `hazards.json`; the UI greys it).
- **No start silence (v26.1.15, review 7).** Until v26.1.14 danger and feature roles were forced to `none` during the first `WARMUP_S` of a run (no distances on a guessed horizon) and proximity was off; both are gone: the horizon is the mean of the raw estimates so far (else the mount / body preset), the distance is the ground-geometry one until the depth anchor has its first `initialAnchorMinFrames` (3) plane fits, and the only start gate left is the 2-frame confirmation (0.33 s at 6 fps). Gates that stay: `confirmFrames`, the start summary's `summaryHoldSeconds` (context only), `globalMinGapSeconds` (context / surface), `peopleSpeakMinSteps`, `movingDangerSteps` / `dangerSteps` (a person is a danger only within 10 steps).
- A role is **confirmed** after it has held for `confirmFrames` consecutive frames; speech and beeps use only confirmed roles of settled tracks.


### 7.11d v26.2.12 collision rules — passing close

- **Passing close** (`beeps.passing`: `enabled`, `minClosingMps` 0.8, `lateralM` 1.5, `maxSteps` 4): a moving person / rider / vehicle approaching at >= `minClosingMps` within `lateralM` and `maxSteps`, outside the lane, gets the soft `proximity` episode (any of these classes, unlike `proximitySteps`).
