"""Collisions router: collision re-runs of a run (start, cancel, list, compare, label, delete)."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from lab import collisions, reviews
from lab.api import rundata, worldmap
from lab.api.deps import _cid, _coll_call, _collision, _run

router = APIRouter()


@router.post("/api/runs/{run_id}/collision")
def rerun_collision(run_id: str, body: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:  # noqa: B008
    """A NEW collision run (v26.2.8): next id, current recording settings, optional config ``overrides``; its world map is built too.
    v26.2.10: a background job. Returns at once with the new collision doc in status ``running`` (``progress`` 0-1); poll
    ``/collisions`` or cancel with ``POST /collisions/{cid}/cancel``. 409 while another collision job or an analysis runs."""  # noqa: E501
    run = _run(run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"Run is {run['status']}, not done")
    _collision()
    body = body or {}
    label = body.get("label", "")
    if not isinstance(label, str) or len(label) > collisions.MAX_LABEL:
        raise HTTPException(422, f"label must be a string of at most {collisions.MAX_LABEL} characters")
    doc = _coll_call(collisions.start_job, run_id, body.get("overrides"), label)
    q = f"?collision={doc['id']}"
    return {
        **doc,
        "version": doc["collisionVersion"],
        "hazards": f"/api/runs/{run_id}/hazards.json{q}",
        "events": f"/api/runs/{run_id}/events.json{q}",
    }


@router.post("/api/runs/{run_id}/collisions/{cid}/cancel")
def cancel_collision(run_id: str, cid: str) -> dict[str, Any]:
    """Stop a running collision re-run between frames; its directory is removed and its id is not reused (v26.2.10)."""
    run = _run(run_id)
    _cid(run, cid)
    if not collisions.cancel_job(run_id, cid):
        raise HTTPException(409, f"{cid} is not running; nothing to cancel")
    for _ in range(100):  # give the job a moment so the reply shows the end state
        if not collisions.job_active():
            break
        time.sleep(0.1)
    return {"cancelled": cid, "collisions": collisions.ids(_run(run_id))}


@router.get("/api/runs/{run_id}/collisions")
def list_collisions(run_id: str) -> list[dict[str, Any]]:
    _run(run_id)
    return collisions.list_docs(run_id)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.get("/api/runs/{run_id}/collisions/compare")
def compare_collisions(run_id: str, a: str = Query(), b: str = Query()) -> dict[str, Any]:
    _run(run_id)
    return _coll_call(collisions.compare, run_id, a, b)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.patch("/api/runs/{run_id}/collisions/{cid}")
def patch_collision(run_id: str, cid: str, body: dict[str, Any]) -> dict[str, Any]:
    run = _run(run_id)
    _cid(run, cid)
    return _coll_call(collisions.set_label, run_id, cid, body.get("label"))  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.delete("/api/runs/{run_id}/collisions/{cid}")
def delete_collision(run_id: str, cid: str) -> dict[str, Any]:
    run = _run(run_id)
    _cid(run, cid)
    count = reviews.count_for_collision(run["request"]["recording"], run_id, cid)
    _coll_call(collisions.delete, run_id, cid, count)
    with rundata._hz_lock:
        rundata._hz_cache.pop((run_id, cid), None)
    with worldmap._wm_lock:
        worldmap._wm_cache.pop((run_id, cid), None)
    return {"deleted": cid, "collisions": collisions.ids(_run(run_id))}
