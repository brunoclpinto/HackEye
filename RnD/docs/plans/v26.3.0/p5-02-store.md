# p5-02 lab.store + the forwarding helper

## Creates
- `lab/_forward.py`: `install(module_name, forwards)` (p5-00 decision 1).
- `lab/store/` modules (audit 7.4 / 7.5 / 7.8):
  - `constants.py`: the constants of `analysis.py` 43-64 (`GRID_W`, `NO_DATA`, `ANALYSIS_VERSION`, `PROFILES`, `RESOLUTIONS`,
    `IDLE_SECONDS`, `RUN_ID_RE`, `DEPTH_*`, `DEFAULT_MODEL`, `MODEL_DIRS`, `SUPERSEDED_ANCHORS`).
  - `errors.py`: `RunError`, `RunConflict`, `_Cancelled` (legacy spelling), `CollisionError`.
  - `util.py`: `_now`, `_log`, `_write_json`, `_atomic_write_json` (from `recordings`).
  - `runs.py`: `LAB_DIR`, `run_dir`, `_state_lock`, `_active`, `get_run`, `list_runs`, `_update_run`, `ACTIVE_STATUSES`,
    `find_active_for_recording`, `_conflict_message`, `_remove_partial_outputs`.
  - `requests.py`: `_normalise_request`, `request_side`, `run_window`, `DEVICES`, `_parse_device`, `_cpu_threads`, `_run_id`.
  - `models.py`: `list_models`.
  - `collision_docs.py`: `CID_RE`, `MAX_LABEL`, `MATCH_WINDOW_S`, `FILES`, `_lock`, `collisions_root`, `collision_dir`, `ids`, `latest`,
    `resolve`, `read_doc`, `_add_effective` (its lazy `import groundfuse` stays), `list_docs`, `write_doc`, `update_doc`, `allocate`,
    `register`, `set_label`, `delete`.
  - `recordings.py`: the scan / ffprobe info / chapters / settings / sensors-path part of `lab/recordings.py` with its `LAB_DIR`,
    `_info_cache`; the proxy thread stays in `lab/recordings.py` until p5-03.
  - `jobctx.py`: `JobContext` (Protocol + a plain implementation used by the worker in p5-03).
- `lab.store` imports no other lab package and no engine package (BOUNDARIES). Legacy flat modules (`profiles`, `cv2`, `numpy`, lazy
  `collision` / `sensors` / `groundfuse`) stay as they are (audit 7.8 decision).

## Facades
`analysis.py`, `collisions.py`, `recordings.py` delete the moved definitions and `install(__name__, {...})` forwarding each moved name to
its home. Code still in those flat modules that reads a moved name reads it as a module attribute of the home
(`runs._active`, not a local copy). `override` functions are already `engine.core.config` objects re-exported by `collisions` (check;
keep them re-exported).

## Tests (Sonnet): `tests/lab/test_store.py` + `tests/lab/test_forward.py`
- `install`: get / set / delattr forward; `monkeypatch.setattr(flat, name, x)` changes the home global and the undo restores it; a
  non-forwarded name behaves normally.
- Identity: every moved name read through its flat module is the home object (the dict / lock / queue objects by `is`).
- The three `LAB_DIR` names are independent: patching one does not change the others.
- Run-doc round trip on a `tmp_path` `LAB_DIR` (`_update_run`, `get_run`, `list_runs`), collision-doc round trip (`allocate`, `write_doc`,
  `read_doc`, `ids`, `latest`), `_normalise_request` on 6 requests from the existing lab tests: pin results from the legacy functions.
