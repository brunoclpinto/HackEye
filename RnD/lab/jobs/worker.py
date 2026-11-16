"""The GPU worker (v26.3.0 p5-03): one daemon thread takes run ids from the queue and runs the inference job.

The worker builds one `JobContext` per job (cancel flag of the run, `_finish`) and passes it to the inference job.
The queue globals (`_jobs`, `_busy`, `_cancel_flags`, `_cache`, `_worker`) live in `lab.jobs.queue` and are read
and written there as module attributes at call time, so a patch through the `analysis` facade is seen. Until p5-04
the job is `analysis._run_job` and the model cache class is `analysis._ModelCache` (both read from the flat module
at call time)."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

from lab.jobs import queue as jq
from lab.store import constants, errors, runs, util
from lab.store.jobctx import JobContext


def _ensure_worker() -> None:
    from lab import analysis  # `_ModelCache` stays in analysis until p5-04 (lab.stages.models)

    with runs._state_lock:
        if jq._cache is None:
            jq._cache = analysis._ModelCache()
        if jq._worker is None or not jq._worker.is_alive():
            jq._worker = threading.Thread(target=_worker_loop, name="gpu-worker", daemon=True)
            jq._worker.start()


def _worker_loop() -> None:
    from lab import analysis  # the inference job `_run_job` stays in analysis until p5-04 (lab.stages.inference)

    cache = jq._cache
    while True:
        try:
            run_id = jq._jobs.get(timeout=1.0)
        except queue.Empty:
            if (
                cache.model is not None or cache.depth_model is not None
            ) and time.monotonic() - cache.last_used > constants.IDLE_SECONDS:
                cache.release()
            continue
        with runs._state_lock:
            jq._busy = run_id
        ctx = JobContext(run_id, is_cancelled=lambda run_id=run_id: _is_cancelled(run_id), finish=_finish)
        try:
            analysis._run_job(run_id, cache, ctx)
        except errors._Cancelled:
            jq._finish_cancelled(run_id)
        except BaseException as exc:  # incl. SystemExit from gpu_guard
            util._log(f"run {run_id} FAILED: {exc!r}")
            _finish(run_id, status="error", error=str(exc) or repr(exc))
            if isinstance(exc, MemoryError) or "CUDA" in str(exc):
                cache.release()
        finally:
            with runs._state_lock:
                jq._busy = None
                jq._cancel_flags.pop(run_id, None)


def _is_cancelled(run_id: str) -> bool:
    flag = jq._cancel_flags.get(run_id)
    return flag is not None and flag.is_set()


def _check_cancel(run_id: str) -> None:
    flag = jq._cancel_flags.get(run_id)
    if flag is not None and flag.is_set():
        raise errors._Cancelled()


def _finish(run_id: str, **fields: Any) -> None:
    runs._update_run(run_id, finishedAt=util._now(), **fields)
    with runs._state_lock:
        runs._active.pop(run_id, None)
