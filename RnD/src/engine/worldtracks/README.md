# engine/worldtracks -- world tracks (shadow mode)

Every item of the collision pass is tracked in the dead-reckoned world frame (x east, y north, m) with a
constant-velocity Kalman filter (state `[x, y, vx, vy]`, 4 x 4 covariance, white acceleration noise: small for
static-like items, large for movers). Nothing computed here feeds a decision; it only adds `worldTracks` to each hazards
frame. Imports only numpy and the stdlib.

## API

| module | name | purpose | legacy |
|---|---|---|---|
| `tracks.py` | `DEFAULTS` | default config dict | `worldtracks.DEFAULTS` |
| `tracks.py` | `settings(cfg)` | defaults overlaid with `cfg` | `worldtracks.settings` |
| `tracks.py` | `WT` | slotted per-track state | `worldtracks._WT` |
| `tracks.py` | `rot`, `eig_radius`, `interval` | helpers | `_rot`, `_eig_radius`, `_interval` |
| `tracks.py` | `WorldTracks(cfg, lane_half_m, hfov_deg)` | tracker: `step`, `lookup` | `worldtracks.WorldTracks` |

`engine/worldtracks/__init__.py` exports `WorldTracks`, `DEFAULTS` and the submodule `tracks` (`settings` stays at
`engine.worldtracks.tracks.settings`).

## Inputs / outputs

- A measurement is the item's reported (forward, right) position located with the current pose; its covariance is built
  in range / bearing and rotated to the world.
- A track without a measurement stays predicted: `out-of-view` for `coastMaxS`, `missing` for `missDropFrames` frames.
- Association is greedy in `items` list order. `WorldTracks.ms` is a clock reading and is not pinned.

## Config keys read

The `worldTracks` block of `collision.json`, passed as a dict: see `DEFAULTS` (enabled, accel*, *SigmaFrac, gateChi2,
coastMaxS, missDrop*, skipClasses, extendedClasses, trust*, ...).

## Invariants

- `worldtracks.X is engine.worldtracks.tracks.Y` for every moved name; `worldtracks.py` is a pure facade.
- Slot list of `WT` and attribute list of `WorldTracks` are pinned (`tests/engine/worldtracks/test_tracks.py`).

## Changelog (from the `worldtracks.py` module docstring)

> World tracks (v26.2.9, shadow mode): every item of the collision pass tracked in the world with position, velocity and
> uncertainty. Nothing computed here feeds a decision of `collision.run_collision`; it only adds `worldTracks` to each
> hazards frame.
