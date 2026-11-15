# p4-01 engine.pipeline.glue

## Moves (collision.py → engine/pipeline/glue.py)
`_bottom_distance` → `bottom_distance`, `_hidden_fn` → `hidden_fn`, `_predict_velocities` → `predict_velocities`, and the list
`LAST_WORLD_TRACKS_MS` (same name). `collision.LAST_WORLD_TRACKS_MS is engine.pipeline.glue.LAST_WORLD_TRACKS_MS`: the same list
object (`run_collision` assigns it with `[:] =`, and `tools/worldtracks_metrics.py` reads `col.LAST_WORLD_TRACKS_MS`).

Named rename: `groundfuse.ground_point` → `groundgeom.ground_point` in `bottom_distance`.

## Tests (Haiku): `tests/engine/pipeline/test_glue.py`
- Identity of the four names (the list by `is`).
- `bottom_distance` / `hidden_fn` on a `SimpleNamespace` observer (`geo` from `engine.core.groundgeom.Geometry`, `gh`, `gw`, `cam_h`,
  `ray_hidden`, `orow`, `oc`, `cell`): pin results from the legacy functions.
- `predict_velocities` with a stub `wtracks` (`lookup`): pin `it.pred_v` for 4 items (trusted, untrusted, missing, no track).
