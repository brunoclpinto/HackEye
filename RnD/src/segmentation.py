"""Facade: the safety mapping and the segmentation grid live in engine.infer.segmentation (v26.3.0 p5-01).

``NUM_CLASSES`` / ``SKY_CLASS_ID`` are rebound by ``select_mapping`` in ``mapping``: they are forwarded by a module
``__getattr__`` (never copied by value), so ``segmentation.NUM_CLASSES`` always reads the current value.
"""

from typing import Any

from engine.infer.segmentation import mapping as _mapping
from engine.infer.segmentation.grid import (  # noqa: F401
    SegmentationGrid,
    _4_CONNECTIVITY,
    _convex_hull,
    _mask_padding_and_finish,
    extract_objects,
    grid_from_semantic_mask,
    parse_grid,
)
from engine.infer.segmentation.mapping import (  # noqa: F401
    _CONFIG_DIR,
    _CONFIG_PATH,
    CLASSES,
    SAFETY_LEVELS,
    _load_mapping,
    find_mapping,
    select_mapping,
)


def __getattr__(name: str) -> Any:
    if name in ("NUM_CLASSES", "SKY_CLASS_ID"):
        return getattr(_mapping, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
