"""Display router: the saved mask display (view-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from lab import display

router = APIRouter()

if TYPE_CHECKING:
    from collections.abc import Callable


def _display_call(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except display.DisplayError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.get("/api/display/{mapping}")
def get_display(mapping: str) -> dict[str, Any]:
    return _display_call(display.get, mapping)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.put("/api/display/{mapping}/{section}")
def put_display(mapping: str, section: str, body: dict[str, Any]) -> dict[str, Any]:
    if section not in ("classes", "levels"):
        raise HTTPException(404, "Not found")
    return _display_call(display.put, mapping, section, body)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.delete("/api/display/{mapping}/{section}")
def delete_display(mapping: str, section: str) -> dict[str, Any]:
    if section not in ("classes", "levels"):
        raise HTTPException(404, "Not found")
    return _display_call(display.reset, mapping, section)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)
