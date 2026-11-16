"""Shared helpers of the Lab routers: collision module (503), recording / run / collision-run lookups (404)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from lab import analysis, collisions, recordings

if TYPE_CHECKING:
    from collections.abc import Callable


def _collision() -> Any:
    """The collision module, or a 503 while src/collision.py doesn't exist."""
    try:
        import collision
    except ImportError as exc:
        raise HTTPException(503, f"Collision module unavailable: {exc}") from None
    return collision


def _recording(rec_id: str) -> dict[str, Any]:
    rec = recordings.get_recording(rec_id)
    if rec is None:
        raise HTTPException(404, f"Unknown recording: {rec_id}")
    return rec  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


def _run(run_id: str) -> dict[str, Any]:
    run = analysis.get_run(run_id) if analysis.RUN_ID_RE.match(run_id) else None
    if run is None:
        raise HTTPException(404, f"Unknown run: {run_id}")
    return run  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


def _coll_call(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except collisions.CollisionError as exc:
        raise HTTPException(exc.status, exc.message) from None


def _cid(run: dict[str, Any], collision: str | None) -> str:
    """The collision run an endpoint reads: the named one (404 when unknown) or the run's latest (404 when it has none)."""  # noqa: E501
    return _coll_call(collisions.resolve, run, collision)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)
