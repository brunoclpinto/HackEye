"""Safety mapping of the segmentation classes: the loaded CLASSES / SAFETY_LEVELS and the selection by model names.

``NUM_CLASSES`` / ``SKY_CLASS_ID`` are module globals rebound by ``select_mapping`` (readers use ``mapping.<NAME>``).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from engine.core.paths import find_common_dir

if TYPE_CHECKING:
    from pathlib import Path

_CONFIG_DIR = find_common_dir() / "config"
_CONFIG_PATH = _CONFIG_DIR / "safety_mapping.json"


def _load_mapping(path: Path = _CONFIG_PATH) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    with open(path) as f:
        data = json.load(f)
    classes = {c["id"]: c for c in data["classes"]}
    levels = {int(k): v for k, v in data["safetyLevels"].items()}
    return classes, levels


# Defaults to the 124-class Vistas mapping until select_mapping() is called
# with a loaded model's class names (see models.SegmentationModel).
CLASSES, SAFETY_LEVELS = _load_mapping()
NUM_CLASSES = len(CLASSES)
SKY_CLASS_ID = next(c["id"] for c in CLASSES.values() if c["name"] == "nature sky")


def find_mapping(model_names: list[str]) -> tuple[Path, dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    """The common/config/safety_mapping*.json whose class names match model_names
    exactly, in id order, as (path, classes, levels). Pure: touches no module
    state (the Lab server uses it without loading a model). Raises ValueError
    if no mapping file matches.
    """
    for path in sorted(_CONFIG_DIR.glob("safety_mapping*.json")):
        classes, levels = _load_mapping(path)
        if [classes[i]["name"] for i in sorted(classes)] == list(model_names):
            return path, classes, levels
    raise ValueError(
        f"No safety mapping in {_CONFIG_DIR} matches this segmentation model's "
        f"{len(model_names)} class names. Add a safety_mapping_<name>.json whose "
        f"classes list the model's names in id order."
    )


def select_mapping(model_names: list[str]) -> Path:
    """Switch to the mapping find_mapping() picks. Mapping is by class id, so a
    checkpoint with a different taxonomy would otherwise be mislabeled
    silently. Raises if no mapping file matches.

    CLASSES / SAFETY_LEVELS are updated in place because overlay.py binds
    them at import time.
    """
    global NUM_CLASSES, SKY_CLASS_ID  # noqa: PLW0603
    path, classes, levels = find_mapping(model_names)
    CLASSES.clear()
    CLASSES.update(classes)
    SAFETY_LEVELS.clear()
    SAFETY_LEVELS.update(levels)
    NUM_CLASSES = len(CLASSES)
    SKY_CLASS_ID = next(c["id"] for c in CLASSES.values() if c["name"] == "nature sky")
    return path
