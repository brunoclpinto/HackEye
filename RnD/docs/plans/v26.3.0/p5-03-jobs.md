# p5-03 lab.jobs

## Moves
- `queue.py`: `_jobs`, `_worker`, `_cache`, `_cancel_flags`, `_busy`, `_maintenance`, `submit_run`, `cancel_run`, `_finish_cancelled`,
  `cancel_all`, `is_idle`, `analysis_active`, `wait_idle`, `release_model`, `begin_maintenance`, `end_maintenance`.
- `worker.py`: `_ensure_worker`, `_worker_loop`, `_check_cancel`, `_finish`; the worker builds a `JobContext` per job and passes it to the
  inference stage (still `analysis._run_job` until p5-04, which then takes `ctx`).
- `collision.py`: `Job`, `_job`, `job_active`, `cancel_job`, `start_job`, `_run_job` (of `collisions.py`); `Job.report` raises
  `store.errors._Cancelled`.
- `proxy.py`: the proxy builder thread of `lab/recordings.py` (`_proxy_lock`, `_building`, the build function).
- `versioning.py`: `lab/versioning.py`'s `VersionWatcher` and policy (the worker object stays injected; `server` passes the `analysis`
  facade, whose forwarded attributes reach `lab.jobs.queue`).
`lab.jobs` may import `lab.store` and `lab.stages` only. Facades forward every moved name (p5-00).

## Risks
- Lock order and thread start points: verbatim.
- `analysis.collision_pass` / `worldmap_pass` are patched by tests and called by the collision job: the job calls them as attributes of
  their home module at call time (after p5-04: `lab.stages.collision`), reached here through the `analysis` facade until then.

## Tests (Sonnet): `tests/lab/test_jobs.py`
- Identity through the facades; `monkeypatch.setattr(analysis, "_jobs", q)` makes `submit_run` enqueue on `q` (as the existing lab
  tests rely on).
- `JobContext.check_cancel` raises `_Cancelled` after `cancel_run`; `progress` / `finish` write the run doc (tmp `LAB_DIR`).
- The existing `tests/test_lab_*.py` and `test_collision_job_*.py` pass unchanged (they are the main guard).
