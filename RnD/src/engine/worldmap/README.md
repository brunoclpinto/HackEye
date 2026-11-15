# engine/worldmap -- the fused bird's-eye world map

The world map fuses the class grid, the depth map and the frame's horizon and ego block into an ego-centric map. This
README covers the whole model (p3-01 to p3-04): the config loader, the pose integration, the hazards helpers, the observer, the fusion
and the `WorldMap` driver. Imports only numpy, the stdlib and `engine.core`.

## API

| module | name | purpose | legacy |
|---|---|---|---|
| `config.py` | `load_config(path=None)` | reads `config/worldmap.json` (dir from `engine.core.paths.find_common_dir()`) | `worldmap.load_config` |
| `config.py` | `class_kinds(cfg, class_names)` | `(max(len(class_names), 256),)` uint8 lookup: ignore / surface / object / mover | `worldmap.class_kinds` |
| `config.py` | `UNKNOWN`, `KIND_IGNORE`, `KIND_SURFACE`, `KIND_OBJECT`, `KIND_MOVER` | 255 and 0..3 | same names on `worldmap` |
| `config.py` | `default_config_loader` | hook: what engine code calls when it has no cfg; replaced by the facade | installed by `worldmap.py` |
| `pose.py` | `PoseTracker(coll_cfg)` | frame-by-frame pose from speed x dt along the heading (composes `engine.core.pose.DeadReckoner`) | `worldmap.PoseTracker` |
| `pose.py` | `integrate_pose(times, egos, coll_cfg)` | `(N, 3)` x east, y north (m), heading deg over a run | `worldmap.integrate_pose` |
| `observer.py` | `Observer(cfg, settings, kind, gh, gw, gd_cfg, class_names)` | one frame's ego-centric observation (`observe`, `object_bases`, `face_contact_samples`); surfaces by inverse ground projection | `worldmap.Observer` |
| `fusion.py` | `Fusion(cfg, kind, present, start_xy)` | world-frame vote grid (0.10 m cells, recentred as the user moves): `update`, `snapshot`, `close_gaps`, `surface_at`, `world_classes` | `worldmap.Fusion` |
| `map.py` | `WorldMap(grids, times, class_names, frames, settings, coll_cfg, cfg=None, depth=None)` | drives the passes frame by frame (`step`: pose, optional pose alignment, observation, fusion, snapshot); `cfg=None` calls `config.default_config_loader()` | `worldmap.WorldMap` |
| `map.py` | `build(grids, times, class_names, hazards, coll_cfg, cfg=None, depth=None, hook=None)` | the whole run -> the arrays of `worldmap.npz` (`classes`, `conf`, `surface`, `object`, `t`, `pose`, `cellM`, `origin`, `ms`, `alignDeg`, `alignM`, `agree`, `agreePrior`) | `worldmap.build` |
| `helpers.py` | `face_contact_samples`, `frames_from_hazards`, `first_depth_scale`, `settings_from_hazards` | per-frame inputs and settings from a stored hazards dict | same names on `worldmap` |

`engine/worldmap/__init__.py` re-exports all of these with `__all__`.

## Config keys read

- `load_config`: reads the file only. `class_kinds`: `classes.surface`, `classes.object`, `classes.mover`.
- `Fusion`: `cellM`, `windowM`, `decay` (`none` | `time`), `halfLifeSeconds`, `conflictFactor`, `voteCap`, `weightFloor`,
  `confFullWeight`, `objectWinShare`, `objectClearFactor`, `objectClearMarginM`, `objectClearBottomM`, `surfaceHiddenFactor`.
- `WorldMap`: `poseAlign`, `alignStride`, `alignMinVotes`, `alignMinCells`, `alignDeg`, `alignStepDeg`, `alignShiftM`, `alignShiftStepM`,
  `alignMinGain`, `alignWindow`, `alignMoveDeg`; `cellM` (read by `build`).
- `PoseTracker`: `memory.speedHoldSeconds` of the `collision.json` dict passed in (default 5.0).

## Invariants

- The legacy `worldmap` module re-exports the same objects and installs the loader hook:
  `engine.worldmap.config.default_config_loader` calls `sys.modules["worldmap"].load_config()` at call time, so a
  monkeypatch of `worldmap.load_config` is seen. Engine code must call `config.default_config_loader()` through the module.
- `PoseTracker` composes `DeadReckoner(hold_s)` (the one sanctioned non-verbatim edit): the pose is identical to the old
  `collision._WorldMemory` one, and the load-time import of `collision` is gone from this path.
- `class_kinds` always returns at least 256 entries.

- `Observer` attribute names (`geo`, `gh`, `gw`, `cam_h`, `ray_hidden`, `orow`, `oc`, `cell`, `fwd`, `right`, `size`) are read from outside (collision); frozen.
- `Fusion` attribute names (`votes`, `count`, `classes`, `x0`, `y0`, `n`, ...) are read by the tests; frozen. With `decay` `time` the votes are
  stored pre-multiplied by `exp(lambda t)` (lazy decay); the float order is verbatim.
- `groundfuse.*` became `groundgeom.*` / `distfuse.*` (same objects); `focal_px`, `ground_distance_m`, `lateral_m` come from `engine.core.geom`.

- `WorldMap` takes its default config from `config.default_config_loader()` (call-time lookup on the module); `ms` from `step` is a
  `time.perf_counter` timing and is not part of any equivalence. `build` is monkeypatched on the facade by tests: the Lab calls `worldmap.build`.
- `worldmap.py` is a pure facade: docstring, re-exports, the loader hook, `import collision`, `import groundfuse`.

## Changelog lines (from the `worldmap.py` module docstring)

> 2. Pose: ``collision._WorldMemory.advance`` (cadence speed x dt along the optical-flow heading, 0 when stationary).
