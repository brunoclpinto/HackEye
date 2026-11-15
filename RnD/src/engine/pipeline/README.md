# engine/pipeline -- the frame pipeline

The only engine package that may import other models (`BOUNDARIES.toml`: `engine = ["*"]`). It is being built up in
Phase 4: `run_collision` moves here, then is cut into stages. So far it holds the small glue helpers that
`run_collision` calls between stages. Imports only the stdlib and `engine.core`.

## API

| module | name | purpose | legacy |
|---|---|---|---|
| `glue.py` | `bottom_distance(ob, horizon, cam_h, gh, f)` | forward distance of the last image row on the centre column (the ground seen at the bottom); 0.0 on any error or non-finite value | `collision._bottom_distance` |
| `glue.py` | `hidden_fn(ob)` | `(fwd, right) -> bool` closure: the online map's cell there is hidden behind a building; None without a map | `collision._hidden_fn` |
| `glue.py` | `predict_velocities(items, wtracks, t, theta, pcfg)` | sets `pred_v` (velocity in our frame) on movers with a trusted, moving world track | `collision._predict_velocities` |
| `glue.py` | `LAST_WORLD_TRACKS_MS` | list of the world-track step ms per frame of the last run (metrics tool only; not in the output) | `collision.LAST_WORLD_TRACKS_MS` |

`engine/pipeline/__init__.py` re-exports these four names (`__all__`). No function shares a name with a submodule.

## Inputs / outputs

- `bottom_distance`: `ob` is the online-map observer (attributes `geometry`, `geo`, `gh`, `gw`, `cam_h`) or None. With `geometry`
  it uses `groundgeom.ground_point` at the bottom row and the observer's camera height; otherwise the flat formula
  `cam_h * f / ((1 - horizon) * gh)` with the argument camera height.
- `hidden_fn`: `ob` needs `ray_hidden`, `orow`, `oc`, `cell`; cells outside the grid are not hidden.
- `predict_velocities`: only `moving` items that are not `lane_part` / `ghost`; skips untrusted, static or faster-than-`maxMoverMps`
  (default 12.0) tracks.
- `LAST_WORLD_TRACKS_MS` is one list object: `run_collision` assigns it with `[:] =` and never rebinds it.

## Config keys read

- `predict_velocities`: `maxMoverMps` from the `predictive` block, passed in as `pcfg`.

## Invariants

- `collision._bottom_distance`, `_hidden_fn`, `_predict_velocities` and `LAST_WORLD_TRACKS_MS` are the same objects as the engine
  names (`tests/engine/pipeline/test_glue.py`); `tools/worldtracks_metrics.py` reads `col.LAST_WORLD_TRACKS_MS`.
- Named rename only: `groundfuse.ground_point` became `groundgeom.ground_point` (the same function).
