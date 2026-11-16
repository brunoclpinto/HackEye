"""The run queue (v26.3.0 p5-03): submit, cancel, idle / maintenance state and the worker's shared globals.

`_jobs` (the FIFO of run ids), `_worker`, `_cache`, `_cancel_flags`, `_busy` and `_maintenance` are module globals
that tests rebind through the `analysis` facade; code reads them here as globals and elsewhere as attributes of
this module at call time. The worker thread itself is in `lab.jobs.worker`. Lock order: `runs._state_lock` only, as
before."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any

from lab.jobs import worker
from lab.store import constants, errors, runs, util
from lab.store import recordings as store_recordings
from lab.store import requests as store_requests

_jobs: queue.Queue[str] = queue.Queue()
_worker: threading.Thread | None = None
_cache: Any = None  # the worker's model cache, a `_ModelCache` (set when the worker starts)
_cancel_flags: dict[str, threading.Event] = {}  # run_id -> set when cancellation requested
_busy: str | None = None  # run id the worker is executing right now
_maintenance = False  # True while a version wipe is in progress: submissions are refused


def submit_run(req: dict[str, Any]) -> dict[str, Any]:
    """Queue a run, or return the existing one (done, or already in flight).

    A reused finished run comes back with the response-only marker `"reused": true`
    (never stored in run.json). `"force": true` re-runs a finished/cancelled/failed
    run from scratch under the same id (old outputs removed, reviews untouched); an
    in-flight run is returned as is."""
    device = store_requests._parse_device(req)
    request = store_requests._normalise_request(req)
    rec = store_recordings.get_recording(request["recording"])
    force = req.get("force") is True
    run_id = store_requests._run_id(request)
    existing: dict[str, Any] | None = runs.get_run(run_id)
    if existing and existing["status"] in ("done", "queued", "running"):
        # A run.json left as queued/running by a crashed service has no live
        # entry in _active; fall through and redo it.
        with runs._state_lock:
            live = run_id in runs._active
        if live:
            return existing
        if existing["status"] == "done" and not force:
            return {**existing, "reused": True}
    from lab import collisions

    if collisions.job_active():
        raise errors.RunConflict("A collision re-run is running; wait for it or cancel it")
    with runs._state_lock:
        if _maintenance:
            raise errors.RunConflict("Lab is cleaning up for a new version; try again in a minute")
        busy = runs.find_active_for_recording(runs._active, request["recording"])
        if busy is not None:
            raise errors.RunConflict(runs._conflict_message(busy))

    doc = {
        "id": run_id,
        "request": request,
        "orientation": request.get("orientation", "landscape"),
        "side": request.get("side") or req.get("side") or "center",
        "window": store_requests.run_window(rec, request) if rec else None,
        "device": device,
        "analysisVersion": constants.ANALYSIS_VERSION,
        "status": "queued",
        "progress": 0.0,
        "error": None,
        "createdAt": util._now(),
        "finishedAt": None,
        "frameCount": 0,
        "motionFrames": 0,
        "gridW": constants.GRID_W,
        "gridH": 0,
        "srcW": 0,
        "srcH": 0,
        "inputSpec": None,
        "modelName": Path(request["model"]).name,
        "classNames": [],
        "msPerFrame": None,
        "collisionVersion": None,
        "depth": request.get("depth", "none"),
        "depthUnits": None,
        "depthMsPerFrame": None,
    }
    runs.run_dir(run_id).mkdir(parents=True, exist_ok=True)
    with runs._state_lock:
        # Re-check under the same lock that registers the run, so two racing
        # POSTs for one recording can't both pass the guard above.
        busy = runs.find_active_for_recording(runs._active, request["recording"])
        if busy is not None:
            raise errors.RunConflict(runs._conflict_message(busy))
        if existing:  # a forced / retried run starts clean (reviews live outside the run dir)
            runs._remove_partial_outputs(run_id)
        runs._active[run_id] = doc
        _cancel_flags[run_id] = threading.Event()
    util._write_json(runs.run_dir(run_id) / "run.json", doc)
    worker._ensure_worker()
    _jobs.put(run_id)
    return dict(doc)


def _finish_cancelled(run_id: str) -> None:
    runs._remove_partial_outputs(run_id)
    worker._finish(run_id, status="cancelled", error=None)
    with runs._state_lock:
        _cancel_flags.pop(run_id, None)
    util._log(f"run {run_id}: cancelled")


def cancel_run(run_id: str) -> dict[str, Any] | None:
    """Cancel a queued/running run (CONTRACTS 11a).

    Returns the run doc (a queued run is already `cancelled`; a running one
    flips as soon as the worker sees the flag between frames). None if the
    run is unknown; raises RunConflict if it is not queued/running."""
    doc = runs.get_run(run_id)
    if doc is None:
        return None
    with runs._state_lock:
        live = run_id in runs._active
        flag = _cancel_flags.get(run_id)
    if not live or doc["status"] not in runs.ACTIVE_STATUSES:
        raise errors.RunConflict(f"Run {run_id} is {doc['status']}; nothing to cancel")
    if flag is not None:
        flag.set()
    with _jobs.mutex:  # not started yet: pull it out of the queue
        try:
            _jobs.queue.remove(run_id)
            dequeued = True
        except ValueError:
            dequeued = False
    if dequeued:
        _jobs.task_done()
        _finish_cancelled(run_id)
    current: dict[str, Any] | None = runs.get_run(run_id)
    return current


def cancel_all() -> list[str]:
    """Cancel every queued and running run; returns their ids. (v26.2.10: and the collision re-run job.)"""
    from lab import collisions

    collisions.cancel_job()
    with runs._state_lock:
        ids = [i for i, d in runs._active.items() if d["status"] in runs.ACTIVE_STATUSES]
    for i in ids:
        try:  # noqa: SIM105
            cancel_run(i)
        except errors.RunConflict:
            pass
    return ids


def is_idle() -> bool:
    from lab import collisions

    with runs._state_lock:
        return _busy is None and not runs._active and _jobs.empty() and not collisions.job_active()


def analysis_active() -> bool:
    """A run is queued or running (v26.2.10: a collision re-run job never runs together with one)."""
    with runs._state_lock:
        return any(d["status"] in runs.ACTIVE_STATUSES for d in runs._active.values())


def wait_idle(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if is_idle():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def release_model() -> None:
    if _cache is not None:
        _cache.release()


def begin_maintenance() -> None:
    """Refuse new submissions and cancel everything in flight (version wipe)."""
    global _maintenance  # noqa: PLW0603
    with runs._state_lock:
        _maintenance = True
    cancel_all()


def end_maintenance() -> None:
    global _maintenance  # noqa: PLW0603
    with runs._state_lock:
        _maintenance = False
