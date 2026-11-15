# engine/egostate -- ego speed and path-change state

The per-run state of the wearer's motion that the frame loop updates: an EMA-smoothed walking speed from the closing
rates of static witnesses, and the detector for a sustained heading change (a turn). Imports only numpy and the stdlib.

## API

| module | name | purpose | legacy |
|---|---|---|---|
| `ego.py` | `Ego` | dataclass; fields in order `speed, speed_t, cadence, heading, ref_heading, exceed_since` (order pinned); `update_speed()`, `update_heading()` | `collision._Ego` |

`engine/egostate/__init__.py` re-exports `Ego` (`__all__ = ["Ego"]`). No function shares a name with a submodule.

## Inputs / outputs

- `Ego()` starts with all fields None, `speed_t = -inf`.
- `update_speed(closings, t, cfg)` -> None. With at least `speedMinTracks` closings, `speed` is the EMA (`speedEma`) of
  their median and `speed_t = t`; otherwise a speed older than 5.0 s is dropped to None.
- `update_heading(heading, t, cfg, dt)` -> bool. Stores `heading`; the slow reference `ref_heading` follows it with time
  constant `referenceTauSeconds`; True (and the reference is reset to the heading) once the heading stayed more than
  `headingDeg` off the reference for `sustainSeconds`. A None heading returns False and leaves the reference alone.
- `cadence` is written by the caller (`collision`), never by `Ego`.

## Config keys read

Passed in by the caller as the dict, not read from a loaded config:

- `update_speed`: `speedMinTracks`, `speedEma` (the `ego` block of `collision.json`).
- `update_heading`: `headingDeg`, `sustainSeconds`, `referenceTauSeconds` (the `pathChange` block).

## Invariants

- `collision._Ego is engine.egostate.ego.Ego`; `collision.run` creates one `Ego()` per run.
- Field order and names are pinned (`tests/engine/egostate/test_ego.py`); tests use the private attribute names.
- The 5.0 s staleness limit is a literal in `update_speed`, not a config key.

## Changelog lines (from the `collision.py` module docstring)

> * **Ego motion.** Cadence is the step rate seen in the vertical camera bob (spectral peak in 0.8-3.5 Hz).
>
> * **Stationary user** (`estimate_stationary`, from the residual image flow of `egoflow.py`): the ego speed is 0 and
> nothing static is announced; only a mover on a collision course is.
>
> * **Ego speed** is held when the cadence drops out (no witness guess), the cadence refine cannot leave its band, ...
>
> * **Context beside the path** ...; the motion states use the median ego speed of 3 s (`_robust_speed`).
>
> ... ego speed is judged only from pole-like static items (`_speed_witness`) ...
