# lab/stages -- model cache, frame reader, inference job, collision pass, world-map pass

The work one analysis run does: the GPU model cache, the sequential frame reader with the ego-motion track, the inference job
(segmentation, optional depth, grids / masks / motion written to the run folder), and the two passes that follow it, the collision
pass and the world-map pass. May import `lab.store` only (`BOUNDARIES.toml`: `may_import = ["lab.store"]`,
`engine = ["engine.pipeline", "engine.infer"]`, both unused for now). Flat modules (`models`, `depth`, `segmentation`, `egoflow`,
`letterbox`, `profiles`, `gpu_guard`, `collision`, `worldmap`, `lab.collisions`, `lab.recordings`, `lab.sounds`) stay as they are
(audit 7.8); the model wrappers and `egoflow` are imported lazily by their flat names, as before.

## API

| module | names | legacy |
|---|---|---|
| `models.py` | `_ModelCache` (`get`, `get_depth`, `release`, static `_torch_device`) | `analysis._ModelCache` |
| `frames.py` | `MOTION_W`, `MOTION_H`, `_FrameReader` | `analysis.*` |
| `inference.py` | `_run_job(run_id, cache, ctx)` | `analysis._run_job` |
| `collision.py` | `_build_worldmap`, `collision_pass` | `analysis.*` |
| `worldmap.py` | `worldmap_pass` | `analysis.worldmap_pass` |

`analysis` deletes these names and forwards each to its home through `lab/_forward.py`, so
`monkeypatch.setattr(analysis, "collision_pass", spy)` rebinds `lab.stages.collision.collision_pass`.

## Inputs / outputs

- `_run_job(run_id, cache, ctx)` reads `runs/<id>/run.json`, loads the model(s) from `cache`, writes `masks/*.png`, `grids.npz`,
  `depth.npz` (when asked), `motion.npz` and the progress fields of the run doc, then runs the collision pass and the map and
  calls `ctx.finish(status="done", progress=1.0)`. `ctx.check_cancel()` raises `errors._Cancelled` when the run was cancelled. A caller
  that passes no `ctx` (`ctx=None`) gets one built from the `analysis` facade (`_cancel_flags`, `_finish`).
- `collision_pass(run_id, overrides, label, job)` -> the `collision.json` document, or None when `collision` / `worldmap` do not
  import; writes `hazards.json`, `events.json`, `collision.json` under `collisions/<cid>/`. A `job` reports 0-0.4 of its progress.
- `worldmap_pass(run_id, cid, job)` -> `{version, elapsedSeconds, frames, msMean, msP95}`; writes `worldmap.npz` atomically and the
  `worldmapVersion` of the collision doc; a `job` reports 0.4-1.0.
- `_FrameReader(rec, motion_end)`: `read(t)` -> `(frame time, BGR)` or None, `finish_motion()`, `motion_track()`, `close()`.

## Config keys / environment read

`YOLO_CONFIG_DIR` is set (when unset) to `<LAB_DIR>/.ultralytics` before the first segmentation model load. The collision and
world-map configs come from `collision.load_config()` / `worldmap.load_config()` plus the run's overrides.

## Invariants

- The passes call `collision.run_collision`, `collision.resolve_settings`, `collision.load_config`, `worldmap.load_config` and
  `worldmap.build` as attributes of the flat modules at call time (tests patch them); `_run_job` reads `collision_pass` and
  `_build_worldmap` as attributes of `lab.stages.collision`, and `_build_worldmap` reads `worldmap_pass` of `lab.stages.worldmap`,
  so a patch through the `analysis` facade is seen.
- `_torch_device` stays a static method looked up on the class (tests patch it).
- The worker (`lab.jobs.worker`) calls `lab.stages.inference._run_job` and builds `lab.stages.models._ModelCache` as module
  attributes at call time.
