"""Class-id resolution: config class names -> ids of the loaded model, plus the item groups and grid constants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from engine.core.log import warn_once as _warn_once

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["FOUR_CONNECTIVITY", "ITEM_GROUPS", "NO_DATA", "ClassIds", "resolve_class_ids"]

FOUR_CONNECTIVITY: npt.NDArray[np.int64] = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
ITEM_GROUPS: tuple[str, ...] = ("static", "moving", "feature")
NO_DATA = 255  # grid cell outside the analysed window (a portrait run): no class, never a surface or an item


# --------------------------------------------------------------------------
# Class ids
# --------------------------------------------------------------------------


@dataclass
class ClassIds:
    """Config class names resolved to ids of this model."""

    surface_groups: dict[str, npt.NDArray[np.int64]]
    inside: npt.NDArray[np.int64]
    items: dict[str, list[int]]  # group -> class ids (static/moving/feature)
    names: list[str]  # class id -> name
    people: frozenset[str] = frozenset()  # class names treated as movers unless measured stationary
    # class names that cover 5-10 m/s (rider, vehicle): warned about early (v26.1.13)
    fast: frozenset[str] = frozenset()
    thin: frozenset[str] = frozenset()  # class names warned about as "beware poles"
    landmark: frozenset[str] = frozenset()  # feature class names announced as a landmark (crosswalk)


def resolve_class_ids(config: dict[str, Any], class_names: list[str]) -> ClassIds:
    index = {n: i for i, n in enumerate(class_names)}

    def ids_of(names: Iterable[str]) -> npt.NDArray[np.int64]:
        out: list[int] = []
        for name in names:
            if name in index:
                out.append(index[name])
            else:
                _warn_once(f"class '{name}' not in this model, skipped")
        return np.array(out, dtype=np.int64)

    surf = config["surfaces"]
    return ClassIds(
        surface_groups={g: ids_of(v["classes"]) for g, v in surf["groups"].items()},
        inside=ids_of(surf["inside"]),
        items={g: [int(i) for i in ids_of(config["classes"].get(g, []))] for g in ITEM_GROUPS},
        names=list(class_names),
        people=frozenset(config["classes"].get("people", [])),
        fast=frozenset(config["classes"].get("fast", [])),
        thin=frozenset(config["classes"].get("thin", [])),
        landmark=frozenset(config["classes"].get("landmark", [])),
    )
