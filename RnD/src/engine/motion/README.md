# engine/motion -- the movers' own motion

How a moving item (person, rider, vehicle, animal) is judged by its own motion: the robust ego speed the motion states
are compared against, the approach / recede / still / side state with hysteresis, and the own ground velocity fitted
from the item's own positions on the dead-reckoned world plane. Imports only numpy, the stdlib and `engine.core`
(types only, under `TYPE_CHECKING`).

**Fields written** (`engine.core.types.FIELD_WRITERS`): owns `Item.moving`, `Item.approaching`, `Item.receding`, `Item.ego_known`, `Item.own_fast`, `Item.ego_settled`, `Item.lat_vel`, `Item.cross_mps`, `Item.own`, `Item.own_ok`, `Item.own_closing`, `Item.near_pass`, `Item.from_side`, `Track.moving`, `Track.lhist`, `Track.along_s`, `Track.along_t`, `Track.mstate`, `Track.still_t0`.

## API

| module | name | purpose | legacy |
|---|---|---|---|
| `state.py` | `robust_speed(hist, t, speed, window_s)` | median of the ego speed over the last `window_s` s; **updates `hist` in place** (`hist[:] = ...`) | `collision._robust_speed` |
| `state.py` | `motion_state(tr, t, along, side, cross, roles, vehicle=False)` | `"side"` / `"approach"` / `"recede"` / `"still"` / `None`, with hysteresis on `tr.mstate` | `collision._motion_state` |
| `own.py` | `OwnMotion` | Theil-Sen velocity of a mover from its own world positions; `advance`, `observe`, `estimate`, `classify` | `collision._OwnMotion` |

`engine/motion/__init__.py` re-exports the three names and the submodules `own`, `state` (`__all__`). No function shares a
name with a submodule.

## Inputs / outputs

- `robust_speed`: appends `(t, speed)` to `hist` (the list owned by `run_collision` as `ego_hist`), keeps the last
  `window_s` s (or the newest entry), returns the median as float. `window_s <= 0` returns the speed itself.
- `motion_state`: reads `tr.mstate` (the previous state) and **writes `tr.still_t0`** (the start of the current "still"
  candidate; reset to None on every other outcome). `run_collision` also writes `tr.still_t0` (field ownership, Phase 4).
- `OwnMotion.classify(it, t, u, words=True)` writes the item fields `own`, `own_ok`, `own_closing`, `near_pass`,
  `from_side`, `moving`, `approaching`, `receding`. With too few frames it writes nothing.
- `OwnMotion.advance(t, dt, speed, heading)` integrates our pose; `known` is False when speed or heading is unknown.

## Config keys read

- `motion_state` (`roles` block): `approachingMps`, `motionLeaveMps`, `vehicleApproachingMps`, `standingMps`,
  `standingHoldSeconds`, `standingMaxCrossMps`.
- `OwnMotion` (the `motion` block, passed as a dict): `enabled`, `windowS`, `minPoints`, `minSpanS`, `linkM`, `linkS`,
  `scatterFloorM`, `sigmaMaxMps`, `minSpeedMps` (`person`, `vehicle`), `sigmaK`, `sideMps`, `standingMps`,
  `nearPassMinClosingMps`, `nearPassS`, `nearPassM`.

## Invariants

- `collision._robust_speed`, `_motion_state`, `_OwnMotion` are the same objects as the engine ones.
- Attribute order of `OwnMotion` is pinned (`on, cfg, win, min_pts, min_span, link_m, link_s, floor, hist, last, x, y,
  theta, known, cache`); tests use `__new__` and the private attributes.
- `robust_speed` keeps the in-place write; the caller's list stays the same object.

## Changelog lines (from the `collision.py` module docstring)

> * **Motion states say nothing when unsure** (`_motion_state`): "standing" needs |speed along the line of sight| < 0.3 m/s ...
>
> * **Context beside the path** ...; the motion states use the median ego speed of 3 s (`_robust_speed`).
>
> v26.2.14 (`motion`): movers by their own motion (`_OwnMotion`): the own ground velocity from the item's own positions.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.8 Moving vs. standing

- Static and feature items: `moving = false`. Moving-group items need a known `closingMps` and ego speed (0 while stationary, §7.6). Their **ground velocity** (v26.1.11): *along the line of sight* `along = (closing − egoSpeed / c) · c` (toward the user = positive), smoothed per track (EMA `motionSmoothSeconds`); `c` is the depth gait level (`depthGaitCheck`, clamped to [0.8, 2.5]) when the distances come from a plane-anchored depth map, else 1: depth closing rates read low against the gait (review 4: level 1.2–1.6; a standing person's closing was 0.85 m/s against our 1.4), so both are put on the gait's scale. *Sideways*: `lat_vel`, the slope of the lateral offset over the track's history, each point re-expressed in the newest heading (`lat − Δheading × distance`); a velocity under `lateralVelDeadbandMps` counts as 0 (§7.9).
- **Motion state** (v26.1.12, `_motion_state`, per track, with hysteresis; "a wrong state is worse than none"). With `along` the smoothed speed above:
  - `approach`: `along ≥ approachingMps` (0.4), kept down to `motionLeaveMps` (0.3); `recede`: `along ≤ −0.4`, kept up to −0.3; **v26.1.16 (rule 8, review 8, 52.2 s: a parked car was "approaching"):** for **riders and vehicles** (`fast`) the entry level is `fastApproachingMps` (1.0) and the leave level 0.7× that — their `along` comes from the contact row of a big, fragmenting component and read 0.5–1.5 m/s off for a parked car; a real approach is several m/s, so a car or cyclist at 0.4–1.0 m/s is `unknown` (static-like, no phrase) instead; `side`: a sideways velocity above the deadband (§7.9).
  - `still` ("standing"): `|along| < standingMps` (0.3) **held for `standingHoldSeconds` (1 s)** without a break, **and** no sideways motion (`|cross| < standingMaxCrossMps`, below); once standing it is kept while `|along| < 0.4`.
  - anything else — in between, a measurement shorter than the hold, or a possible sideways motion — is **unknown**: `moving = null` and the plain phrase `"{label} at {clock} in {steps}"` is said.
  - `moving = (state ≠ still)`, null for unknown; `approaching = state is approach`, `receding = state is recede`. No closing or no ego speed → `moving = null` as before.
  - **Across the line of sight** (`cross_mps`, `_cross_velocity`, reported as `crossMps`): the item's bearing (bbox centre) plus the camera heading, fitted over `crossWindowSeconds` (1 s, ≥ 4 points over ≥ 0.7 of it), gives a rate; `R · rate − v · sin(bearing)` (range `R = hypot(distance, lateral)`, bearing and range at the window's middle, `v` our speed) is the item's own speed across the view (a static point drifts outwards at `v sin θ / R`). It is **weak**: on 4929 0–110 s a static pole within 12 m reads 0.2–0.3 m/s median and 0.6–1.25 at p90 (12–32 % of frames above 0.6), a person measured walking left 0.57–0.8, so it cannot name a direction ("moving left") and is used only as the veto for "standing" at 0.6 m/s. There is no `crossing` state.
- **Vehicles** with `moving ≠ true` are treated as **static** for roles, and `moving == false` gives the label `parkedLabels["vehicle"]` ("parked car"); unknown keeps "vehicle". **While motion can be measured (ego speed known) a vehicle of unknown motion is not a static danger** (a moving car re-detected in fragments has no closing speed for ~0.75 s and was one: review 4, 39.0 s); it waits.
- **People (person, rider, animal)** are judged like any mover, on the smoothed ground velocity above: `moving = false` (state `still`) is spoken as "standing" (cyclist: "stopped"); an unmeasured or unsure person keeps the plain phrase (v26.1.6 – v26.1.10 never called a person standing; with the ego speed held and on the gait's scale, standing and walking are separable: 4929 standing people read −0.5 → ~0 m/s, approaching ones +0.5 … +2).


### 7.11d v26.2.12 collision rules — own motion of movers

- **Own motion of movers, v26.2.14** (`motion`: `enabled`, `windowS` 1.2, `minPoints` 4, `minSpanS` 0.6, `sigmaMaxMps` 0.5, `minSpeedMps` {person 0.4, vehicle 0.8}, `sideMps` 0.5, `nearPassM` 1.3, `nearPassS` 4, `againSteps` 1.5, `againGapS` 1.0, `cut` {`maxSteps` 4, `withinS` 1.5}, `ahead` {`maxSteps` 5, `stableS` 1.0}): per mover a line fit of its own relative positions over `windowS` (own velocity = d(fwd)/dt + ego speed, d(right)/dt; outliers rejected; a new track continues a lost fragment within 1.5 m / 0.7 s), kept with its sigma (hazards items `ownMps` [fwd, right, sigma], `fromSide`, `nearPass`). A person is "approaching" only with own motion toward the user >= its min speed; for riders / vehicles the own estimate can only confirm or veto a closing-rate "approaching" (parked cars read noisy). **Near-pass:** an approaching mover whose predicted lateral at passing is within `nearPassM` and passing within `nearPassS` is a collision danger (collision beeps by steps) and is said again when its steps dropped by `againSteps` (>= `againGapS`). **From a side:** own lateral speed >= `sideMps` adds "from left / right" (template `speech.templates.approachSide`: "vehicle approaching from right at 12:30 in 5"). **Cutting in front:** a person within `cut.maxSteps` whose own lateral motion takes it into the lane within `cut.withinS` after being outside it: "person cutting in front" (role final, once per track per 10 s). **Moving away ahead:** a person in the lane ahead walking away (own forward >= 0.4 m/s, gap steady or growing) for `ahead.stableS`, within `ahead.maxSteps`: "person moving away at 12 in 4". Motion words wait until the ego speed settled.
