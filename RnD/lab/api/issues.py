"""Issues router: the issue catalogue and its state."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from lab import issues

router = APIRouter()


@router.get("/api/issues")
def get_issues() -> dict[str, Any]:
    return issues.list_issues()  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.put("/api/issues/{issue_id}")
def put_issue(issue_id: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        return issues.update(issue_id, body)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)
    except issues.IssuesError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.delete("/api/issues/{issue_id}/state")
def reset_issue(issue_id: str) -> dict[str, Any]:
    try:
        return issues.reset(issue_id)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)
    except issues.IssuesError as exc:
        raise HTTPException(exc.status, exc.message) from None
