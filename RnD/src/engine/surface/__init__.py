"""Surface model: walkable surface classes and their confusion handling."""

from __future__ import annotations

from .horizon import HorizonGravity, estimate_horizon
from .region import smooth_bounds, walking_region
from .trackers import CrosswalkTracker, SurfaceTracker, seed_fraction

__all__ = [
    "CrosswalkTracker",
    "HorizonGravity",
    "SurfaceTracker",
    "estimate_horizon",
    "seed_fraction",
    "smooth_bounds",
    "walking_region",
]
