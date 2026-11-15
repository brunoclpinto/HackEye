"""Roles model: what each item is to the wearer."""

from __future__ import annotations

from engine.roles import roles
from engine.roles.roles import (
    assign_role,
    course,
    fast_warning,
    is_static_like,
    not_approaching,
    on_collision_course,
    pole_like,
    sideways_mps,
    speed_witness,
)

__all__ = [
    "assign_role",
    "course",
    "fast_warning",
    "is_static_like",
    "not_approaching",
    "on_collision_course",
    "pole_like",
    "roles",
    "sideways_mps",
    "speed_witness",
]
