"""World map model."""

from __future__ import annotations

from engine.worldmap import faceedge
from engine.worldmap.blocked import BlockedMixin
from engine.worldmap.config import (
    KIND_IGNORE,
    KIND_MOVER,
    KIND_OBJECT,
    KIND_SURFACE,
    UNKNOWN,
    class_kinds,
    load_config,
)
from engine.worldmap.fusion import Fusion
from engine.worldmap.helpers import (
    face_contact_samples,
    first_depth_scale,
    frames_from_hazards,
    settings_from_hazards,
)
from engine.worldmap.map import WorldMap, build
from engine.worldmap.observer import Observer
from engine.worldmap.pose import PoseTracker, integrate_pose
from engine.worldmap.staticmap import StaticMap, mute_solid, set_position

__all__ = [
    "KIND_IGNORE",
    "KIND_MOVER",
    "KIND_OBJECT",
    "KIND_SURFACE",
    "UNKNOWN",
    "BlockedMixin",
    "Fusion",
    "Observer",
    "PoseTracker",
    "StaticMap",
    "WorldMap",
    "build",
    "class_kinds",
    "face_contact_samples",
    "faceedge",
    "first_depth_scale",
    "frames_from_hazards",
    "integrate_pose",
    "load_config",
    "mute_solid",
    "set_position",
    "settings_from_hazards",
]
