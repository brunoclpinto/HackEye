# engine/worldtracks -- world tracks (shadow mode)

Every item of the collision pass is tracked in the dead-reckoned world frame (x east, y north, m) with a
constant-velocity Kalman filter (state `[x, y, vx, vy]`, 4 x 4 covariance, white acceleration noise: small for
static-like items, large for movers). Nothing computed here feeds a decision; it only adds `worldTracks` to each hazards
frame. Imports only numpy and the stdlib.

**Fields written:** none (`Item` / `Track` fields, `engine.core.types.FIELD_WRITERS`).

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

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.11b World tracks — shadow mode  (`src/engine/worldtracks/`, `collision.json` `worldTracks`; v26.2.9)

- **Nothing it computes feeds a decision:** speech, beeps and every other `hazards.json` key are byte-identical with `worldTracks.enabled` true or false (test `test_events_and_every_other_hazards_key_are_byte_identical...`, hashes of v26.2.8 in `tests/fixtures/worldtracks_baseline_v2628.json`). Active only with a motion track (pose of `_WorldMemory`); otherwise `worldTracks` is `[]`.
- **Filter:** per world track `[x, y, vx, vy]` (the `_WorldMemory` frame, m, m/s) with a 4 x 4 covariance, constant velocity, predicted every analysed frame (white acceleration `accelStaticMps2` 0.05 for static-like items, `accelMoverMps2` 1.5 for movers). Measurement = the item's final `distanceM` / `lateralM` located with the current pose; σ_range = `rangeSigmaFrac` 0.12 x distance (x `nonDepthRangeFactor` 2 when the distance did not come from depth, floor `rangeSigmaMinM`), σ_bearing = `bearingSigmaDeg` 1, rotated to the world. Start: velocity 0, σ_v `initSpeedSigmaStaticMps` 0.3 / `initSpeedSigmaMoverMps` 2. The user's pose uncertainty is not modelled.
- **Association:** an image track linked to a world track updates it when the Mahalanobis² <= `gateChi2` 9.21, else it starts a new world track (the old link ends). A new image track first takes the nearest unseen world track of the same family (`family or label`) inside the gate (re-identification through a gap), else starts a new one. Ids `W1, W2, ...` per run; `imageTracks` lists every image track id a world track has had. Not measured: lane parts, ghost and coasting items, `skipClasses` (building, bridge, tunnel).
- **Unseen tracks:** `out-of-view` = predicted outside the field of view (|bearing| > hfov / 2 - `fovMarginDeg`), behind the user, nearer than the ground at the bottom image row, or in a cell the online map hides this frame (`Observer.ray_hidden`); kept predicting for `coastMaxS` 4 s. `missing` = expected in view and not detected; dropped after `missDropFrames` 3 frames. Any track is dropped (state `dropped`, for that frame only) when its 1-σ radius exceeds `maxSigmaM` 3, it is more than `behindDropM` 2 behind, or beyond `maxRangeM`. States: `seen`, `out-of-view`, `missing`, `dropped`.
- **Path test:** relative velocity in the ego frame = the world velocity rotated minus the user's speed straight ahead (from the pose steps); `cpaS` = closest-approach time clamped to `horizonS` 8, `cpaM` the distance there; `onCourse` = `cpaM` <= `laneHalfWidthM` + `itemRadiusM` 0.3 and `cpaS` > 0; `ttcS` = first time inside that half width sideways and within `itemRadiusM` along (null when none).
- **Output:** each frame `worldTracks` (nearest first, <= `maxTracksOut` 40): `id, class, family, group, staticLike, state, imageTracks, trackId (current or null), x, y, vx, vy, fwd, right, speedMps, headingDeg (world, 0 = initial direction), relHeadingDeg (of the relative velocity, ego frame), sigmaM, cpaM, cpaS, onCourse, ttcS, innovM (predicted vs measured position this frame: the re-acquisition error), age, unseenS`; top level `worldTracksSettings` (the block used); `GET .../hazards` windows carry it too. Cost ~1.3 ms/frame (p95 2.1).
- **v26.2.11 (all switchable; the v26.2.10 behaviour = `extendedClasses` [], `headingSigmaDegPerS` 0, `staticVelocityDamping` 1.0, `moverPromoteMps` 0, `missDropS` 0, `reviveS` 0, `reidOneToOne` false; `tools/worldtracks_metrics.py --legacy`):**
  - **Pose noise:** the gate / update covariance gets a tangential term `(r x radians(headingSigmaDegPerS) x min(unseen s, poseSigmaMaxS))^2` (r = range of the measurement from the pose; defaults 0.5 deg/s, 4 s): after a gap the heading may have drifted.
  - **Extended objects have no world track** (`extendedClasses`: curb, crosswalk, barrier, barrier fence / guard-rail / wall, divider, nature vegetation / vegetation, terrain, fence, wall, guard-rail; the map holds them). Poles, signs, traffic lights, obstacles, potholes, vehicles, people keep tracks.
  - **Static model:** a static-like track's velocity is multiplied by `staticVelocityDamping` (0.5) per second unless its position innovations of the last `dampingDirectionalS` (1 s) point consistently one way (net >= `dampingDirectionalMinM` 0.15 m and >= `dampingDirectionalRatio` 0.6 of the mean innovation size); a static-like track faster than `moverPromoteMps` (0.8) for `moverPromoteS` (1 s) is **promoted** to a mover for the rest of its life (`promoted` true, `staticLike` false).
  - **Re-id:** a `missing` track is dropped after `missDropFrames` frames AND `missDropS` (1 s), then kept (not in the output) for `reviveS` (1 s) in a graveyard where it is still predicted and can be re-identified (same id, state `seen`); it is reported once as `dropped` when that time ends (or when it leaves range / sigma). Re-identification looks at out-of-view, missing and graveyard tracks of the same `family`; the assignment is one-to-one, greedy by Mahalanobis^2 (+ `classMismatchCost` 2 when the class differs) inside the gate (`reidOneToOne`).
  - **`trusted`** per track: `seenS` (accumulated seen time, gaps count at most 0.5 s) >= `trustMinS` 0.5 AND position sigma `sigmaM` <= `trustMaxSigmaM` 0.5 AND velocity sigma `speedSigmaMps` <= `trustMaxSpeedSigmaMps` 0.3 AND state not `dropped`. It is independent of `seen` / `missing` (a coasting track loses it when its sigma grows). **Consumers (predictive speech, map source) use a track's velocity only when `trusted`**; an untrusted track is a position at best.
  - New output keys per track: `trusted, speedSigmaMps, seenS, promoted`.
- **Metrics:** `tools/worldtracks_metrics.py <runId> [--collision cid] | --dir <collision dir> | --fixtures [--mode depth|ground+depth]`: pose-drift proxy (static-like tracks seen >= 2 s: world speed, position spread), continuity (image tracks per world track, re-identification gaps and errors), agreement of role `danger` with `onCourse` (movers, statics), `missing` states and drops, cost (fixtures only).
