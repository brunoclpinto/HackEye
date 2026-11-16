"""Notes router: the Lab-wide notes box."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from lab import notes

router = APIRouter()


@router.get("/api/notes")
def get_notes() -> dict[str, Any]:
    return notes.get()  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.put("/api/notes")
def put_notes(body: dict[str, Any]) -> Any:
    try:
        return notes.put(body)
    except notes.NotesError as exc:
        if exc.status == 409:
            return JSONResponse({"detail": {"message": exc.message, "current": exc.current}}, status_code=409)
        raise HTTPException(exc.status, exc.message) from None
