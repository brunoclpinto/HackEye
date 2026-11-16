"""Config router: the collision config and the model lists."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from lab import analysis
from lab.api.deps import _collision

router = APIRouter()


@router.get("/api/config/collision")
def get_collision_config() -> dict[str, Any]:
    return _collision().load_config()  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.get("/api/models")
def get_models() -> dict[str, Any]:
    return {
        "models": analysis.list_models(),
        "profiles": analysis.RESOLUTIONS,
        "depthModels": list(analysis.DEPTH_MODELS),
    }
