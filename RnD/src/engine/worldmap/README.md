# engine/worldmap -- the fused bird's-eye world map

The world map fuses the class grid, the depth map and the frame's horizon and ego block into an ego-centric map. This
README covers the whole model (p3-01 to p3-08): the config loader, the pose integration, the hazards helpers, the observer, the fusion,
the `WorldMap` driver and the face / edge test. Imports only numpy, the stdlib and `engine.core`.

**Fields written** (`engine.core.types.FIELD_WRITERS`): owns `Item.map_source`, `Item.map_cells`, `Item.map_world`, `Item.image_dl`, `Item.solid_corrected`, `Item.raw_distance_m`, `Item.inside_solid`, `Item.ghost`, `Item.map_judged`, `Item.face_edge`, `Item.srcsel`, `Item.track_motion`, `Item.pred_v`, `Track.ghost_src`, `Track.ghost_t0`; also writes `Item.distance_m`, `Item.lateral_m`, `Item.bearing`, `Item.clock`, `Item.pan`, `Item.clipped`, `Item.closing`, `Item.role`, `Item.urgency`, `Item.summary_ok`, `Item.speak`, `Item.collision`, `Item.proximity`, `Item.shape`, `Item.clock_q`, `Item.clock_text`, `Item.full_ref`.

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
| `faceedge.py` | `EDGE`, `FACE`, `NONE`, `VERDICT_NAMES`, `DEFAULTS`, `settings`, `fit_line`, `fit_wall_lines`, `local_orientation`, `classify`, `summarize`, `lines_json` | face / edge verdict per corridor cell of a static family from wall-line fits and local orientation (whole legacy module, verbatim; `VERDICT_NAMES` is unused) | same names on `faceedge` |
| `staticmap.py` | `StaticMap(wmod, grids, times, class_names, config, settings, lat_off, projection, source, lane_half, step_len, obj_mode="depth", wcfg=None)` | the collision pass's online world map: `update`, `measure`, `snap_solid`, `region`, `ghost`, `keeps`, `corridor`, `locate`, `faceedge`, `recent_obstacle_points`, `blocked_ahead` (inherited from `BlockedMixin`) and the private helpers `_lut`, `_corridor_cells`, `_apply`, `_footprint` | `collision._StaticMap` |
| `blocked.py` | `BlockedMixin` | mixin with `blocked_ahead(bcfg)`: lane blocked by a wall or an obstacle and the free direction; reads `self.classes`, `conf`, `ob`, `lane_half`, `min_conf`, `_names`, `obs_widths`, `obs_min_w_frames`, `recent_obstacle_points()`; caches in `self._blk` | `collision._StaticMap.blocked_ahead` |
| `staticmap.py` | `set_position(it, fwd, right)`, `mute_solid(it, smap)` | move an item to (forward, right) m keeping the image measurement in `image_dl`; `insideSolid.mode` "suppress" mutes an item inside a wall face | `collision._set_position`, `collision._mute_solid` |
| `source.py` | `map_source(items, tracks, smap, wtracks, cfg, t, step_len, u, counts)` | `source.mode` "map": where each real item's position comes from (`item.srcsel` `map` / `track` / `image`) and the `counts` tally; calls `smap.region`, `smap._apply`, `set_position`, `ego_frame`, `trusted_track` | `collision._map_source` |

`engine/worldmap/__init__.py` re-exports all of these with `__all__`; the face / edge API is exported as the submodule `faceedge` only (its `settings` must not shadow anything).

## Config keys read

- `load_config`: reads the file only. `class_kinds`: `classes.surface`, `classes.object`, `classes.mover`.
- `Fusion`: `cellM`, `windowM`, `decay` (`none` | `time`), `halfLifeSeconds`, `conflictFactor`, `voteCap`, `weightFloor`,
  `confFullWeight`, `objectWinShare`, `objectClearFactor`, `objectClearMarginM`, `objectClearBottomM`, `surfaceHiddenFactor`.
- `WorldMap`: `poseAlign`, `alignStride`, `alignMinVotes`, `alignMinCells`, `alignDeg`, `alignStepDeg`, `alignShiftM`, `alignShiftStepM`,
  `alignMinGain`, `alignWindow`, `alignMoveDeg`; `cellM` (read by `build`).
- `faceedge`: the `DEFAULTS` keys (`enabled`, `maxAheadM`, `lineAheadM`, `lineMaxSideM`, `lineMinCells`, `lineMinSpanM`, `lineTrials`, `maxLineAngleDeg`, `edgeBandM`, `edgeBlurPerM`, `faceProtrusionM`, `crossRadiusM`, `crossAngleDeg`, `crossElongation`, `crossMinCells`, `minFaceCells`, `crossSideEdge`, `seed`), overridden by the dict passed in.
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

- `faceedge.py` (legacy) is a pure facade (docstring and re-exports). `DEFAULTS["seed"]` seeds `np.random.default_rng` per `fit_wall_lines` call: never reseed. Coordinates are the `Observer` ego frame (`fwd` ahead, `right` of the body line).

## Changelog lines (from the `worldmap.py` module docstring)

> 2. Pose: ``collision._WorldMemory.advance`` (cadence speed x dt along the optical-flow heading, 0 when stationary).

- `StaticMap` (p3-06): tests build it with `__new__` and set only some attributes, so methods read only what they read today. `wmod` (the
  `worldmap` facade module) supplies `load_config()`, `WorldMap` and `KIND_OBJECT`. `_lut` is keyed by `id(lut)` in `_fe_cache` and `blocked_ahead`
  caches lazily in `self._blk` (`"_blk" not in self.__dict__`); both verbatim. The method `faceedge` and the module global `faceedge` share a
  name: method bodies resolve the module global. Config keys read: `roles.map*`, `roles.insideSolid`, `roles.faceEdge`, `spokenLabels`, `blocked`.
- `BlockedMixin` (p3-07): no `__init__`, no class values (bare annotations only); `StaticMap(BlockedMixin)`; `blocked` does not import `staticmap`. Body verbatim, including the lazy `_blk` cache. Config keys read: `blocked.*` (`solidClasses`, `walkableClasses`, `wallClasses`, `obstacle`, `minAheadM`, `aheadM`, `widthFrac`, `walkableLabels`, `freeHalfWidthM`, `walkMinConf`, `angleStepDeg`, `angleDeg`, `minClearM`).
- `map_source` (p3-08): body verbatim; `smap` and `wtracks` are typed by local Protocols (stubs in tests, no isinstance). Config keys read (`source.*`): `imageNetSteps`, `imageNetFrames`, `regionPadM`, `regionMinCells`, `maxTrackJumpM`, `maxTrackJumpFrac`. Mutates the items in place and `counts[srcsel] += 1` per real item.
