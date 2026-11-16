"""Sounds router: the shared sound profile."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from lab import sounds
from lab.api.deps import _collision

router = APIRouter()

if TYPE_CHECKING:
    from collections.abc import Callable


def _sounds_call(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except sounds.SoundsError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.get("/api/sounds")
def get_sounds() -> dict[str, Any]:
    _collision()
    return _sounds_call(sounds.get)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.put("/api/sounds")
def put_sounds(body: dict[str, Any]) -> dict[str, Any]:
    _collision()
    return _sounds_call(sounds.put, body)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.delete("/api/sounds")
def delete_sounds() -> dict[str, Any]:
    _collision()
    return _sounds_call(sounds.reset)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)
