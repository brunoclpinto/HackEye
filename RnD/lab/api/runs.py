"""Runs router: submit, cancel, list and read analysis runs."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from lab import analysis
from lab.api.deps import _run

router = APIRouter()


@router.post("/api/runs")
def post_run(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return analysis.submit_run(body)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)
    except analysis.RunConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except analysis.RunError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    if not analysis.RUN_ID_RE.match(run_id):
        raise HTTPException(404, f"Unknown run: {run_id}")
    try:
        doc = analysis.cancel_run(run_id)
    except analysis.RunConflict as exc:
        raise HTTPException(409, str(exc)) from None
    if doc is None:
        raise HTTPException(404, f"Unknown run: {run_id}")
    # A running job stops between frames; give it a moment so the reply shows the end state.
    for _ in range(30):
        if doc["status"] not in analysis.ACTIVE_STATUSES:
            break
        time.sleep(0.1)
        doc = analysis.get_run(run_id) or doc
    return doc  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.get("/api/runs")
def list_runs(recording: str | None = None) -> list[dict[str, Any]]:
    return analysis.list_runs(recording)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return _run(run_id)
