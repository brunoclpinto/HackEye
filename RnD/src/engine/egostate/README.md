# engine/egostate -- ego speed and path-change state

The per-run state of the wearer's motion that the frame loop updates: an EMA-smoothed walking speed from the closing
rates of static witnesses, and the detector for a sustained heading change (a turn). Imports only numpy and the stdlib.

**Fields written:** none (`Item` / `Track` fields, `engine.core.types.FIELD_WRITERS`).

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

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.6 Ego motion — speed witnesses and ego speed

- **Speed witnesses:** only pole-like static items (bbox height ≥ 3× width, not clipped, not running along the path) with raw closing speed in [0, `speedMaxMps`] judge our speed: the median, EMA `speedEma`, dropped when stale for > 5 s.
- **Ego speed** (calibrated, used for moving-vs-standing and the world memory), v26.1.11: 0 while stationary; else `cadence × stepLength` once the scale is known (or the distances come from depth: they are metres from the start) and a cadence exists; when the cadence drops out that **last cadence-based speed is held for `cadenceWindowSeconds`, then the speed is unknown** (people then get no motion word). The witness speed × scale is only the cold-start guess before any gait scale or cadence-based speed exists (it read 0.59 m/s while walking at 1.4, so a standing person "approached" at 178.7 s). **Settled (v26.1.15, review 7):** the robust speed (median of `egoMedianSeconds`, §6) counts as *settled* when its history has been unbroken for the full window (`_Item.ego_settled`; a measured standing user is settled at once; a gap in the ego speed, i.e. none known, restarts the history). Before that the median is still ramping (0.59 m/s at 2.0 s, 1.28 at 3.2 s on Chest-center-0004, so a standing person read "approaching"): see the motion words.

### 7.12 Path change

A **turn**: the heading differs from a slow reference (time constant `referenceTauSeconds`) by more than `headingDeg` for `sustainSeconds`; the reference is then reset to the heading. (If `onSurfaceChange` were true, an adopted surface change would count too; it is false.) A path change clears the label memory and pending context, re-arms the thin notice and starts a new start summary. It does **not** clear the world memory.
