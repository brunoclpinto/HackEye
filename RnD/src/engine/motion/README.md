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
