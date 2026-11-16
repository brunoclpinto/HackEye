"""The collision re-run job (v26.3.0 p5-03): one at a time per Lab, in a thread (pure numpy, never the GPU queue).

`start_job` validates the overrides, allocates the next collision id, writes its `collision.json` as `running`,
registers it and runs the passes in a daemon thread; `Job.report` raises `errors._Cancelled` once the job was
cancelled. `_job` is the live job (a module global that tests rebind through the `collisions` facade;
`lab.store.collision_docs.read_doc` reads it from the flat facade). The two passes are called as attributes of the
flat `analysis` facade at call time (it forwards them to `lab.stages.collision` / `worldmap`)."""

from __future__ import annotations

import shutil
import threading
from typing import Any

from lab import analysis
from lab.jobs import queue as jq
from lab.store import collision_docs as cdocs
from lab.store import errors, runs, util

# --------------------------------------------------------------------------
# Re-run job (v26.2.10): one at a time per Lab, in a thread (pure numpy, never the GPU queue)
# --------------------------------------------------------------------------


class Job:
    def __init__(self, run_id: str, cid: str):
        self.run_id, self.cid = run_id, cid
        self.cancel = threading.Event()
        self.progress = 0.0
        self.thread: threading.Thread | None = None

    def report(self, fraction: float) -> None:
        """Called between frames by the passes; raises when the job was cancelled."""
        if self.cancel.is_set():
            raise errors._Cancelled()
        self.progress = min(max(float(fraction), 0.0), 1.0)


_job: Job | None = None


def job_active() -> bool:
    j = _job
    return j is not None and j.thread is not None and j.thread.is_alive()


def cancel_job(run_id: str | None = None, cid: str | None = None) -> bool:
    """Ask the running job to stop (between frames); True when there was one (and it is the named one)."""
    j = _job
    if j is None or not job_active() or (run_id is not None and (j.run_id, j.cid) != (run_id, cid)):
        return False
    j.cancel.set()
    return True


def start_job(run_id: str, overrides: Any, label: str) -> dict[str, Any]:
    """Allocate the next id, write its collision.json as `running`, register it and run the passes in a thread.
    409 when a collision job or an analysis is running. Returns the new document."""
    global _job  # noqa: PLW0603
    try:
        import collision
        import worldmap
    except ImportError as exc:
        raise errors.CollisionError(503, f"collision module unavailable ({exc})") from None
    from lab import collisions  # validate/check_overrides: flat until p5-05

    overrides = collisions.validate_overrides(overrides)
    collisions.check_overrides(overrides, collision.load_config(), worldmap.load_config())
    with cdocs._lock:
        if job_active() and _job is not None:
            raise errors.CollisionError(409, f"A collision re-run is already running ({_job.run_id} {_job.cid})")
        if jq.analysis_active():
            raise errors.CollisionError(409, "An analysis is running; wait for it to finish")
        cid = cdocs.allocate(run_id)
        cdocs.collision_dir(run_id, cid).mkdir(parents=True, exist_ok=True)
        doc = {
            "id": cid,
            "runId": run_id,
            "createdAt": util._now(),
            "collisionVersion": None,
            "worldmapVersion": None,
            "settings": {},
            "resolved": {},
            "overrides": overrides,
            "label": (label or "")[: cdocs.MAX_LABEL],
            "elapsedSeconds": None,
            "counts": {},
            "status": "running",
            "progress": 0.0,
            "error": None,
        }
        cdocs.write_doc(run_id, cid, doc)
        cdocs.register(run_id, cid)
        job = Job(run_id, cid)
        job.thread = threading.Thread(
            target=_run_job, args=(job, overrides, label), name=f"collision-{run_id}-{cid}", daemon=True
        )
        _job = job
        job.thread.start()
    return doc


def _run_job(job: Job, overrides: dict[str, Any], label: str) -> None:
    run_id, cid = job.run_id, job.cid
    try:
        analysis.collision_pass(run_id, overrides, label, job=job)
        try:  # v26.2.6: the map is always rebuilt after a collision re-run (object distance / horizon switch change it)
            analysis.worldmap_pass(run_id, cid, job=job)
        except errors._Cancelled:
            raise
        except Exception as exc:  # the collision result stands
            util._log(f"run {run_id}: worldmap refresh failed: {exc!r}")
        cdocs.update_doc(run_id, cid, status="done", progress=1.0, error=None)
    except errors._Cancelled:
        with cdocs._lock:
            shutil.rmtree(cdocs.collision_dir(run_id, cid), ignore_errors=True)
            run = runs.get_run(run_id) or {}
            runs._update_run(run_id, collisions=[c for c in cdocs.ids(run) if c != cid])
        util._log(f"run {run_id}: collision {cid} cancelled")
    except BaseException as exc:
        util._log(f"run {run_id}: collision {cid} FAILED: {exc!r}")
        cdocs.update_doc(run_id, cid, status="error", error=getattr(exc, "message", None) or str(exc) or repr(exc))
