"""Worldmap config: the loader, the class-kind lookup and the default-loader hook (plan decision 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from engine.core.paths import find_common_dir

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "KIND_IGNORE",
    "KIND_MOVER",
    "KIND_OBJECT",
    "KIND_SURFACE",
    "UNKNOWN",
    "class_kinds",
    "default_config_loader",
    "load_config",
]

UNKNOWN = 255
KIND_IGNORE, KIND_SURFACE, KIND_OBJECT, KIND_MOVER = 0, 1, 2, 3


def load_config(path: Path | None = None) -> dict[str, Any]:
    import json

    path = path or (find_common_dir() / "config" / "worldmap.json")
    with open(path) as f:
        cfg: dict[str, Any] = json.load(f)
    return cfg


def class_kinds(cfg: dict[str, Any], class_names: list[str]) -> npt.NDArray[np.uint8]:
    """(n_classes,) uint8 lookup: ignore / surface / object / mover."""
    kind = np.zeros(max(len(class_names), 256), dtype=np.uint8)
    index = {n: i for i, n in enumerate(class_names)}
    for k, key in ((KIND_SURFACE, "surface"), (KIND_OBJECT, "object"), (KIND_MOVER, "mover")):
        for name in cfg["classes"][key]:
            if name in index:
                kind[index[name]] = k
    return kind


def _default_loader() -> dict[str, Any]:
    return load_config()


# Engine code calls ``config.default_config_loader()`` (looked up on the module at call time); the legacy facade
# replaces it.
default_config_loader: Callable[[], dict[str, Any]] = _default_loader
