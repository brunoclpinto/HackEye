# lab/jobs -- run queue, GPU worker, collision re-run job, proxy builder, version watcher

The threads of the Lab and the state they share: the FIFO of analysis runs with its cancel flags and idle / maintenance flags, the one
GPU worker thread, the collision re-run job (one at a time, a daemon thread), the ffmpeg proxy builder and the `VERSION` watcher.
May import `lab.store` and `lab.stages` only (`BOUNDARIES.toml`: `may_import = ["lab.stages", "lab.store"]`, `engine = []`). The
worker reads the inference job and the model cache as attributes of `lab.stages.inference` / `lab.stages.models` at call time; the
collision job still calls the two passes as attributes of the flat `analysis` facade, which forwards them to `lab.stages`.

## API

| module | names | legacy |
|---|---|---|
| `queue.py` | `_jobs`, `_worker`, `_cache`, `_cancel_flags`, `_busy`, `_maintenance`, `submit_run`, `cancel_run`, `_finish_cancelled`, `cancel_all`, `is_idle`, `analysis_active`, `wait_idle`, `release_model`, `begin_maintenance`, `end_maintenance` | `analysis.*` |
| `worker.py` | `_ensure_worker`, `_worker_loop`, `_check_cancel`, `_finish`, `_is_cancelled` (new: the cancel test of the job's `JobContext`) | `analysis.*` (not `_is_cancelled`) |
| `collision.py` | `Job`, `_job`, `job_active`, `cancel_job`, `start_job`, `_run_job` | `collisions.*` |
| `proxy.py` | `PROXY_WIDTH`, `_log`, `proxies_dir`, `proxy_path`, `_proxy_lock`, `_building`, `proxy_status`, `_set_proxy`, `start_proxy`, `_build_proxy` | `recordings.*` |
| `versioning.py` | `MARKER_NAME`, `WIPE_DIRS`, `read_version`, `marker_path`, `read_marker`, `write_marker`, `_wipe_contents`, `apply_version_policy`, `VersionWatcher` | `versioning.*` |

The flat modules `analysis`, `collisions`, `recordings` and `versioning` delete these definitions and forward each name to its home
through `lab/_forward.py` (`install`): reading, assigning or deleting `analysis._jobs` goes to `lab.jobs.queue._jobs`, so
`monkeypatch.setattr(analysis, "_jobs", q)` makes `submit_run` enqueue on `q`.

## Inputs / outputs

- `submit_run(req)` validates through `lab.store.requests`, registers the run in `runs._active` and `_cancel_flags`, starts the worker
  (`worker._ensure_worker()`) and puts the run id on `_jobs`; raises `RunConflict` while a collision job, a run of the same recording
  or a maintenance is active.
- `cancel_run(id)` sets the cancel flag; a queued run is pulled out of the queue and finished as `cancelled`, a running one flips when
  the job checks its flag.
- The worker builds one `JobContext(run_id, is_cancelled, finish)` per job (`lab.store.jobctx`) and passes it to the inference job as
  third argument; `JobContext.check_cancel()` raises `errors._Cancelled` once `cancel_run` set the flag. On `_Cancelled` the worker calls
  `_finish_cancelled`; on any other exception it writes `status="error"` and releases the model after a CUDA / memory error.
- `start_job(run_id, overrides, label)` allocates the next collision id, writes `collision.json` as `running`, registers it and starts
  the thread `collision-<run>-<cid>`; `Job.report(fraction)` clamps the progress and raises `errors._Cancelled` when cancelled.
- `proxy_status(rec_id)`: the live `_building` entry, else `ready` when the mp4 exists, else a failed build's error, else `missing`.
- `VersionWatcher(lab_dir, version_file, worker)` calls the worker's `begin_maintenance`, `wait_idle`, `release_model`,
  `end_maintenance`; the server passes the `analysis` facade, whose forwarded attributes reach `lab.jobs.queue`.

## Config keys / environment read

None here. `constants.IDLE_SECONDS` (store; `HACKEYE_LAB_IDLE_SECONDS`) decides when the idle worker releases the model.

## Invariants

- Lock order and thread start points are as before: `runs._state_lock` guards the queue globals; the collision job takes
  `collision_docs._lock` then `runs._state_lock`; the worker thread is started under `runs._state_lock`.
- Queue globals (`_jobs`, `_busy`, ...) are read and written as attributes of `lab.jobs.queue` (`jq._busy = run_id`), never as copies,
  so a patch through the `analysis` facade is seen by the worker; the same holds for `_ensure_worker` and `_worker_loop` in `worker`.
- `queue.py` and `worker.py` import each other as modules (circular by design: submit calls `worker._ensure_worker`, the worker reads
  the queue); neither uses the other at import time.
- `lab.store.collision_docs.read_doc` reads the live job as `lab.collisions._job` and `lab.store.recordings._proxy_status` calls
  `lab.recordings.proxy_status`; both flat facades forward to this package.
- `lab.stages.inference._run_job(run_id, cache, ctx)` takes the `JobContext` the worker built and uses it for cancellation and finish.
