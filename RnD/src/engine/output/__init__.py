"""Output model: frame outputs and hazards items."""

from __future__ import annotations

from engine.output import hazards, outline
from engine.output.hazards import hazard_dict, hazard_json, lane_polygon, region_rows
from engine.output.outline import (
    DIRS,
    OUTLINE_EPS_PX,
    OUTLINE_MAX_POINTS,
    dp_open,
    item_full,
    item_outline,
    simplify_polygon,
    trace_outline,
)

__all__ = [
    "DIRS",
    "OUTLINE_EPS_PX",
    "OUTLINE_MAX_POINTS",
    "dp_open",
    "hazard_dict",
    "hazard_json",
    "hazards",
    "item_full",
    "item_outline",
    "lane_polygon",
    "outline",
    "region_rows",
    "simplify_polygon",
    "trace_outline",
]
