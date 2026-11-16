# lab/store -- run docs, collision docs, request validation, recordings, job context

The persistent state of the Lab and the pure functions around it: run docs under `LAB_DIR/runs/<id>/run.json` with the in-flight
registry, collision docs under `runs/<id>/collisions/<cid>/`, request validation and the run id, the recordings scan and settings,
the model list and the `JobContext` the worker hands to a stage. Imports no other lab package and no engine package
(`BOUNDARIES.toml`: `may_import = []`, `engine = []`). Legacy flat modules (`profiles`, `cv2`, `numpy`, lazy `collision`,
`sensors`, `groundfuse`) stay as they are (audit 7.8).

## API

| module | names | legacy |
|---|---|---|
| `constants.py` | `GRID_W`, `NO_DATA`, `ANALYSIS_VERSION`, `PROFILES`, `RESOLUTIONS`, `IDLE_SECONDS`, `RUN_ID_RE`, `DEPTH_MODELS`, `DEPTH_ANCHOR`, `SUPERSEDED_ANCHORS`, `DEPTH_W`, `DEPTH_H`, `DEPTH_MIN_REL`, `DEPTH_MIN_M`, `DEPTH_MAX_M`, `DEFAULT_MODEL`, `MODEL_DIRS` | `analysis.<name>` |
| `errors.py` | `RunError`, `RunConflict`, `_Cancelled` (legacy spelling), `CollisionError(status, message)` | `analysis.*`, `collisions.CollisionError` |
| `util.py` | `_now`, `_log`, `_write_json` (no `mkdir`), `_atomic_write_json` (creates the parent) | `analysis._now/_log/_write_json`, `recordings._atomic_write_json` |
| `runs.py` | `LAB_DIR`, `run_dir`, `_state_lock`, `_active`, `get_run`, `list_runs`, `_update_run`, `ACTIVE_STATUSES`, `find_active_for_recording`, `_conflict_message`, `_remove_partial_outputs`, `_PARTIAL_OUTPUTS` | `analysis.*` |
| `requests.py` | `_normalise_request`, `request_side`, `run_window`, `DEVICES`, `_parse_device`, `_cpu_threads`, `_run_id` | `analysis.*` |
| `models.py` | `list_models` | `analysis.list_models` |
| `collision_docs.py` | `CID_RE`, `MAX_LABEL`, `MATCH_WINDOW_S`, `FILES`, `_lock`, `collisions_root`, `collision_dir`, `ids`, `latest`, `resolve`, `read_doc`, `_add_effective`, `list_docs`, `write_doc`, `update_doc`, `allocate`, `register`, `set_label`, `delete` | `collisions.*` |
| `recordings.py` | `MEDIA_DIR`, `LAB_DIR`, `scan_recordings`, `get_recording`, `list_recordings`, `recording_frame_at`, `name_hints`, `_input_sizes`, `_info_cache`, `get_settings`, `save_settings`, `sensors_path`, `sensors_for` (+ the private scan helpers) | `recordings.*` |
| `jobctx.py` | `JobContext(run_id, is_cancelled, finish)`, `JobContextLike` (Protocol) | new |

`lab/_forward.py` (`install(module_name, forwards)`) turns the flat modules `analysis`, `collisions` and `recordings` into forwarding
modules: a name in the table above is not defined there any more; reading, assigning or deleting it on the flat module goes to its home
module here, under the same (legacy) spelling. `monkeypatch.setattr(analysis, "_active", {})` therefore rebinds `runs._active`.

## Inputs / outputs

- `get_run(id)` returns a copy of the live doc from `_active`, else `run.json`, else None. `_update_run(id, persist=True, **fields)`
  merges into the live doc (or the file) and returns a snapshot; `persist=False` skips the file write (progress ticks).
- `_normalise_request(req)` returns the canonical request dict (its sha1 with `ANALYSIS_VERSION` and the model mtime is the run id)
  or raises `RunError` (HTTP 4xx).
- `write_doc` / `_write_json` raise `FileNotFoundError` when the parent directory is missing; `_atomic_write_json` creates it.
- `JobContext.check_cancel()` raises `errors._Cancelled` when `is_cancelled()`; `progress(p)` calls
  `runs._update_run(run_id, persist=False, progress=p)`; `finish(**fields)` calls `finish(run_id, **fields)`.

## Config keys / environment read

`HACKEYE_LAB_IDLE_SECONDS`, `HACKEYE_LAB_DEFAULT_MODEL`, `HACKEYE_MODELS_DIR`, `HACKEYE_RELEASES_DIR` (constants, read at import);
`HACKEYE_MEDIA_DIR`, `HACKEYE_LAB_DIR` (recordings); `HACKEYE_LAB_DEFAULT_DEVICE`, `HACKEYE_LAB_CPU_THREADS` (requests, read per call).

## Invariants

- Three independent `LAB_DIR` globals, as before: `runs.LAB_DIR` (`analysis.LAB_DIR`), `recordings.LAB_DIR` (`recordings.LAB_DIR`) and
  `lab.reviews.LAB_DIR`. Patching one leaves the others alone; all start from the same path.
- Code in this package that must see a test patch reads the name as an attribute of its home module at call time
  (`recordings.get_recording`, `models.list_models`, `constants.MODEL_DIRS`, `runs.get_run`), never a from-imported copy.
  Code that stays in a flat module does the same (`runs._active`, `cdocs._lock`).
- `_active` is a `dict`, `_state_lock` a `threading.Lock`, `collision_docs._lock` a `threading.RLock`; the flat names are the same objects.
- Two lazy reads of flat modules remain: `recordings._proxy_status` calls `lab.recordings.proxy_status` (the proxy builder, forwarded to `lab.jobs.proxy`
  and its `_building` dict), and `collision_docs.read_doc` reads the live job `lab.collisions._job`.
- `_proxy_status` is the only new name (the old `get_recording` called `proxy_status` directly).
