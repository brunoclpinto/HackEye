"""Characterisation tests for engine.roles.roles (v26.3.0 p3-11): the nine role predicates and ``assign_role``.

Every expected literal was printed by the legacy ``collision._speed_witness`` ... ``collision._assign_role`` in the
hackeye-rnd image before the move, by running the ``_pred_row`` / ``_role_row`` helpers below on the ``PRED_CASES`` /
``ROLE_CASES`` tables. The engine module is imported inside each test (it does not exist yet).
"""

from __future__ import annotations

from typing import Any

import pytest

import collision
from engine.core.types import Item

NAMES: list[str] = [
    "speed_witness",
    "pole_like",
    "is_static_like",
    "not_approaching",
    "sideways_mps",
    "course",
    "on_collision_course",
    "fast_warning",
    "assign_role",
]

ROLES_SMALL: dict[str, Any] = {
    "lateralVelDeadbandMps": 1.0,
    "lateralVelMaxMps": 3.0,
    "courseMinClosingMps": 0.5,
    "courseMaxSeconds": 5.0,
    "beepLateralM": 0.9,
    "fastWarnMaxM": 20.0,
    "fastWarnSeconds": 4.0,
    "movingLaneHalfWidthM": 2.0,
}

ROLE_FIELDS: list[str] = ["role", "urgency", "collision", "summary_ok", "proximity", "speak"]


def _item(**kw: Any) -> Item:
    """A stub item: a static pole-shaped thing unless the overrides say otherwise."""
    base: dict[str, Any] = {
        "group": "static",
        "class_name": "pole",
        "bbox": [0.4, 0.2, 0.45, 0.6],
        "contact_y": 0.6,
        "distance_m": 6.0,
        "lateral_m": 0.5,
        "bearing": 0.0,
        "clock": 12,
        "pan": 0.0,
        "area_frac": 0.01,
        "clipped": False,
        "touches": True,
        "lane_hit": False,
        "along_path": False,
        "lane_cover": 0.0,
        "area_m2": 1.0,
    }
    base.update(kw)
    return Item(**base)


# (name, overrides)
PRED_CASES: list[tuple[str, dict[str, Any]]] = [
    ("pole", {"closing_raw": 1.0}),
    ("pole_no_closing", {}),
    ("wide_static", {"bbox": [0.1, 0.2, 0.6, 0.4], "closing_raw": 1.0}),
    ("pole_clipped", {"clipped": True, "closing_raw": 1.0}),
    ("pole_along", {"along_path": True, "closing_raw": 1.0}),
    ("pole_lane_part", {"lane_part": True, "closing_raw": 1.0}),
    ("pole_stalled", {"closing_raw": 0.1}),
    ("pole_closing_neg", {"closing_raw": -0.4}),
    ("person_walking", {"group": "moving", "people": True, "moving": True, "closing": 1.5, "lat_vel": 0.2}),
    ("person_unknown", {"group": "moving", "people": True, "moving": None, "closing": 0.1}),
    ("car_unknown", {"group": "moving", "moving": None, "closing": 3.0, "fast": True}),
    ("car_still", {"group": "moving", "moving": False, "closing": 0.0, "fast": True}),
    (
        "car_crossing",
        {"group": "moving", "moving": True, "closing": 4.0, "lat_vel": 5.0, "lateral_m": -2.0, "fast": True},
    ),
    (
        "car_crossing_fast",
        {"group": "moving", "moving": True, "closing": 2.0, "lat_vel": -9.0, "lateral_m": 4.0, "fast": True},
    ),
    (
        "car_approaching",
        {
            "group": "moving",
            "moving": True,
            "closing": 5.0,
            "lat_vel": 0.5,
            "lateral_m": 0.3,
            "fast": True,
            "distance_m": 15.0,
        },
    ),
    (
        "car_far",
        {"group": "moving", "moving": True, "closing": 1.0, "lateral_m": 0.0, "fast": True, "distance_m": 40.0},
    ),
    (
        "rider_receding",
        {
            "group": "moving",
            "people": True,
            "fast": True,
            "moving": True,
            "closing": 3.0,
            "receding": True,
            "distance_m": 8.0,
        },
    ),
    (
        "rider_near_miss",
        {
            "group": "moving",
            "people": True,
            "fast": True,
            "moving": True,
            "closing": 4.0,
            "lateral_m": 1.9,
            "distance_m": 12.0,
        },
    ),
    ("slow_closing", {"group": "moving", "moving": True, "closing": 0.3, "distance_m": 10.0}),
    ("feature_crosswalk", {"group": "feature", "class_name": "crosswalk", "landmark": True}),
]

EGO_SPEEDS: list[float | None] = [None, 0.4, 1.0, 2.0]

# (name, overrides, span, stationary)
ROLE_CASES: list[tuple[str, dict[str, Any], tuple[float, float] | None, bool]] = [
    (
        "building_near_side",
        {
            "class_name": "building",
            "distance_m": 3.5,
            "steps": 5.0,
            "lateral_m": 2.0,
            "label": "building",
            "ego_settled": True,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "building_far_ahead",
        {
            "class_name": "building",
            "distance_m": 12.0,
            "steps": 17.0,
            "lateral_m": 1.0,
            "label": "building",
            "ego_settled": True,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "building_far_side",
        {
            "class_name": "building",
            "distance_m": 3.5,
            "steps": 5.0,
            "lateral_m": 4.0,
            "label": "building",
            "ego_settled": True,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "pole_in_lane",
        {"lane_hit": True, "distance_m": 2.8, "steps": 4.0, "lateral_m": 0.1, "label": "pole", "ego_settled": True},
        (0.4, 1.0),
        False,
    ),
    (
        "pole_in_lane_final",
        {"lane_hit": True, "distance_m": 1.4, "steps": 2.0, "lateral_m": 0.1, "label": "pole"},
        (0.4, 1.0),
        False,
    ),
    (
        "pole_map_judged_out",
        {"lane_hit": True, "map_judged": True, "map_cells": 0, "distance_m": 2.8, "steps": 4.0, "label": "pole"},
        (0.4, 1.0),
        False,
    ),
    (
        "pole_map_judged_in",
        {"map_judged": True, "map_cells": 3, "distance_m": 2.8, "steps": 4.0, "label": "pole"},
        (0.4, 1.0),
        False,
    ),
    (
        "pole_tiny",
        {"lane_hit": True, "area_m2": 0.0, "distance_m": 2.8, "steps": 4.0, "label": "pole"},
        (0.4, 1.0),
        True,
    ),
    (
        "car_unknown_near",
        {
            "group": "moving",
            "class_name": "vehicle",
            "distance_m": 3.5,
            "steps": 5.0,
            "lateral_m": 1.5,
            "label": "vehicle",
            "fast": True,
            "moving": None,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "car_unmeasured_ego_known",
        {
            "group": "moving",
            "class_name": "vehicle",
            "distance_m": 3.5,
            "steps": 5.0,
            "lateral_m": 1.5,
            "label": "vehicle",
            "fast": True,
            "moving": None,
            "ego_known": True,
            "lane_hit": True,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "person_beside_9",
        {
            "group": "moving",
            "class_name": "person",
            "distance_m": 6.3,
            "steps": 9.0,
            "lateral_m": 2.5,
            "label": "person",
            "people": True,
            "moving": None,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "person_on_path_8",
        {
            "group": "moving",
            "class_name": "person",
            "distance_m": 5.6,
            "steps": 8.0,
            "lateral_m": 0.3,
            "label": "person",
            "people": True,
            "moving": None,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "person_standing_8",
        {
            "group": "moving",
            "class_name": "person",
            "distance_m": 5.6,
            "steps": 8.0,
            "lateral_m": 1.0,
            "label": "person",
            "people": True,
            "moving": False,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "person_approach_collision",
        {
            "group": "moving",
            "class_name": "person",
            "distance_m": 5.6,
            "steps": 8.0,
            "lateral_m": 0.7,
            "label": "person",
            "people": True,
            "moving": True,
            "approaching": True,
            "closing": 2.5,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "person_approach_beside",
        {
            "group": "moving",
            "class_name": "person",
            "distance_m": 5.6,
            "steps": 8.0,
            "lateral_m": 1.2,
            "label": "person",
            "people": True,
            "moving": True,
            "approaching": True,
            "closing": 2.5,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "person_receding",
        {
            "group": "moving",
            "class_name": "person",
            "distance_m": 5.6,
            "steps": 8.0,
            "lateral_m": 1.2,
            "label": "person",
            "people": True,
            "moving": True,
            "receding": True,
            "closing": 0.5,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "person_near_beep",
        {
            "group": "moving",
            "class_name": "person",
            "distance_m": 2.1,
            "steps": 3.0,
            "lateral_m": 0.3,
            "label": "person",
            "people": True,
            "moving": True,
            "near_pass": True,
            "closing": 1.0,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "person_proximity",
        {
            "group": "moving",
            "class_name": "person",
            "distance_m": 2.8,
            "steps": 4.0,
            "lateral_m": 1.8,
            "label": "person",
            "people": True,
            "moving": True,
            "approaching": True,
            "closing": 1.0,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "person_no_span",
        {
            "group": "moving",
            "class_name": "person",
            "distance_m": 5.6,
            "steps": 8.0,
            "lateral_m": 0.3,
            "label": "person",
            "people": True,
            "moving": None,
        },
        None,
        False,
    ),
    (
        "person_coasting",
        {
            "group": "moving",
            "class_name": "person",
            "distance_m": 5.6,
            "steps": 8.0,
            "lateral_m": 0.3,
            "label": "person",
            "people": True,
            "moving": None,
            "coasting": True,
            "contact_y": 0.0,
        },
        (0.7, 1.0),
        False,
    ),
    (
        "rider_fast_warning",
        {
            "group": "moving",
            "class_name": "rider",
            "distance_m": 14.0,
            "steps": 20.0,
            "lateral_m": 0.5,
            "label": "rider",
            "people": True,
            "fast": True,
            "moving": True,
            "closing": 4.0,
            "lat_vel": 0.0,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "vehicle_fast_collision",
        {
            "group": "moving",
            "class_name": "vehicle",
            "distance_m": 7.0,
            "steps": 10.0,
            "lateral_m": 0.2,
            "label": "vehicle",
            "fast": True,
            "moving": True,
            "closing": 5.0,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "vehicle_crossing",
        {
            "group": "moving",
            "class_name": "vehicle",
            "distance_m": 14.0,
            "steps": 20.0,
            "lateral_m": 1.5,
            "label": "vehicle",
            "fast": True,
            "moving": True,
            "closing": 3.0,
            "lat_vel": 6.0,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "crosswalk",
        {
            "group": "feature",
            "class_name": "crosswalk",
            "distance_m": 8.4,
            "steps": 12.0,
            "lateral_m": 4.0,
            "label": "crosswalk",
            "landmark": True,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "crosswalk_far",
        {
            "group": "feature",
            "class_name": "crosswalk",
            "distance_m": 30.0,
            "steps": 60.0,
            "label": "crosswalk",
            "landmark": True,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "crosswalk_clipped",
        {
            "group": "feature",
            "class_name": "crosswalk",
            "distance_m": 8.4,
            "steps": 12.0,
            "label": "crosswalk",
            "landmark": True,
            "clipped": True,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "curb_crossing_lane",
        {
            "group": "feature",
            "class_name": "curb",
            "distance_m": 5.6,
            "steps": 8.0,
            "lateral_m": 0.0,
            "label": "curb",
            "lane_hit": True,
            "lane_cover": 0.6,
        },
        (0.4, 1.0),
        False,
    ),
    (
        "curb_beside",
        {"group": "feature", "class_name": "curb", "distance_m": 5.6, "steps": 8.0, "lateral_m": 4.0, "label": "curb"},
        (0.4, 1.0),
        False,
    ),
    (
        "curb_along",
        {
            "group": "feature",
            "class_name": "curb",
            "distance_m": 5.6,
            "steps": 8.0,
            "label": "curb",
            "lane_hit": True,
            "lane_cover": 0.6,
            "along_path": True,
        },
        (0.4, 1.0),
        False,
    ),
]

# --- literals printed by the legacy functions (see the module docstring) ---
PRED_EXPECTED: dict[str, Any] = {
    "pole": {
        "speed_witness": True,
        "pole_like": True,
        "is_static_like": True,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "pole_no_closing": {
        "speed_witness": False,
        "pole_like": True,
        "is_static_like": True,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "wide_static": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": True,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "pole_clipped": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": True,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "pole_along": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": True,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "pole_lane_part": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": True,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "pole_stalled": {
        "speed_witness": True,
        "pole_like": True,
        "is_static_like": True,
        "not_approaching": [False, False, True, True],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "pole_closing_neg": {
        "speed_witness": True,
        "pole_like": True,
        "is_static_like": True,
        "not_approaching": [False, False, True, True],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "person_walking": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": False,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": (4.0, 0.5),
        "collision_course_default": True,
        "fast_warning_default": True,
        "sideways_small": 0.0,
        "course_small": (4.0, 0.5),
        "collision_course_small": True,
        "fast_warning_small": True,
    },
    "person_unknown": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": False,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "car_unknown": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": True,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": (2.0, 0.5),
        "collision_course_default": True,
        "fast_warning_default": True,
        "sideways_small": 0.0,
        "course_small": (2.0, 0.5),
        "collision_course_small": True,
        "fast_warning_small": True,
    },
    "car_still": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": True,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "car_crossing": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": False,
        "not_approaching": [False, False, False, False],
        "sideways_default": 5.0,
        "course_default": (1.5, 5.5),
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 3.0,
        "course_small": (1.5, 2.5),
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "car_crossing_fast": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": False,
        "not_approaching": [False, False, False, False],
        "sideways_default": -8.0,
        "course_default": (3.0, -20.0),
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": -3.0,
        "course_small": (3.0, -5.0),
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "car_approaching": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": False,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": (3.0, 0.3),
        "collision_course_default": True,
        "fast_warning_default": True,
        "sideways_small": 0.0,
        "course_small": (3.0, 0.3),
        "collision_course_small": True,
        "fast_warning_small": True,
    },
    "car_far": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": False,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": (40.0, 0.0),
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": (40.0, 0.0),
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "rider_receding": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": False,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": (2.6666666666666665, 0.5),
        "collision_course_default": True,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": (2.6666666666666665, 0.5),
        "collision_course_small": True,
        "fast_warning_small": False,
    },
    "rider_near_miss": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": False,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": (3.0, 1.9),
        "collision_course_default": False,
        "fast_warning_default": True,
        "sideways_small": 0.0,
        "course_small": (3.0, 1.9),
        "collision_course_small": False,
        "fast_warning_small": True,
    },
    "slow_closing": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": False,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": (33.333333333333336, 0.5),
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
    "feature_crosswalk": {
        "speed_witness": False,
        "pole_like": False,
        "is_static_like": False,
        "not_approaching": [False, False, False, False],
        "sideways_default": 0.0,
        "course_default": None,
        "collision_course_default": False,
        "fast_warning_default": False,
        "sideways_small": 0.0,
        "course_small": None,
        "collision_course_small": False,
        "fast_warning_small": False,
    },
}

ROLE_EXPECTED: dict[str, Any] = {
    "building_near_side": ["context", "none", False, False, False, True],
    "building_far_ahead": ["none", "none", False, False, False, True],
    "building_far_side": ["none", "none", False, True, False, True],
    "pole_in_lane": ["danger", "danger", True, False, False, True],
    "pole_in_lane_final": ["danger", "final", True, False, False, True],
    "pole_map_judged_out": ["context", "none", False, False, False, True],
    "pole_map_judged_in": ["danger", "danger", True, False, False, True],
    "pole_tiny": ["context", "none", False, False, False, True],
    "car_unknown_near": ["context", "none", False, False, False, True],
    "car_unmeasured_ego_known": ["context", "none", False, False, False, True],
    "person_beside_9": ["danger", "danger", False, False, False, True],
    "person_on_path_8": ["danger", "danger", True, False, False, True],
    "person_standing_8": ["danger", "danger", False, False, False, True],
    "person_approach_collision": ["danger", "danger", True, False, False, True],
    "person_approach_beside": ["danger", "danger", False, False, False, True],
    "person_receding": ["danger", "danger", False, False, False, True],
    "person_near_beep": ["danger", "final", True, False, False, True],
    "person_proximity": ["none", "none", False, False, True, True],
    "person_no_span": ["danger", "danger", True, False, False, True],
    "person_coasting": ["danger", "danger", True, False, False, True],
    "rider_fast_warning": ["danger", "danger", True, False, False, True],
    "vehicle_fast_collision": ["danger", "danger", True, False, False, True],
    "vehicle_crossing": ["none", "none", False, False, False, True],
    "crosswalk": ["feature", "none", False, False, False, True],
    "crosswalk_far": ["none", "none", False, False, False, True],
    "crosswalk_clipped": ["none", "none", False, False, False, True],
    "curb_crossing_lane": ["feature", "none", False, False, False, True],
    "curb_beside": ["none", "none", False, False, False, True],
    "curb_along": ["none", "none", False, False, False, True],
}


def _legacy_or_engine(prefix: str, name: str) -> Any:
    if prefix == "legacy":
        return getattr(collision, "_" + name)
    from engine.roles import roles

    return getattr(roles, name)


def _pred_row(prefix: str, over: dict[str, Any]) -> dict[str, Any]:
    def f(n: str) -> Any:
        return _legacy_or_engine(prefix, n)

    it = _item(**over)
    row: dict[str, Any] = {
        "speed_witness": f("speed_witness")(it),
        "pole_like": f("pole_like")(it),
        "is_static_like": f("is_static_like")(it),
        "not_approaching": [f("not_approaching")(it, e) for e in EGO_SPEEDS],
    }
    for tag, roles_cfg in (("default", {}), ("small", ROLES_SMALL)):
        row[f"sideways_{tag}"] = f("sideways_mps")(it, roles_cfg)
        row[f"course_{tag}"] = f("course")(it, roles_cfg)
        row[f"collision_course_{tag}"] = f("on_collision_course")(it, roles_cfg)
        row[f"fast_warning_{tag}"] = f("fast_warning")(it, roles_cfg)
    return row


def _role_row(
    prefix: str, over: dict[str, Any], span: tuple[float, float] | None, stationary: bool, roles_cfg: dict[str, Any]
) -> list[Any]:
    it = _item(**over)
    # stale values the reset must overwrite
    it.role, it.urgency, it.collision, it.summary_ok, it.proximity, it.speak = "x", "x", True, True, True, False
    it.speak = True
    _legacy_or_engine(prefix, "assign_role")(it, span, roles_cfg, 0.6, 0.7, stationary)
    return [getattr(it, f) for f in ROLE_FIELDS]


def _real_roles() -> dict[str, Any]:
    cfg = collision.load_config()
    roles: dict[str, Any] = cfg["roles"]
    return roles


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return bool(a == pytest.approx(b, rel=1e-12, abs=1e-12))
    if isinstance(a, tuple | list) and isinstance(b, tuple | list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def test_identity_of_all_nine() -> None:
    from engine.roles import roles

    for n in NAMES:
        assert getattr(collision, "_" + n) is getattr(roles, n), n


def test_predicates_on_stub_items() -> None:
    assert [n for n, _ in PRED_CASES] == list(PRED_EXPECTED)
    for name, over in PRED_CASES:
        got = _pred_row("engine", over)
        exp = PRED_EXPECTED[name]
        assert got.keys() == exp.keys(), name
        for k in exp:
            assert _same(got[k], exp[k]), (name, k, got[k], exp[k])


def test_assign_role_scenarios() -> None:
    roles_cfg = _real_roles()
    assert [n for n, *_ in ROLE_CASES] == list(ROLE_EXPECTED)
    for name, over, span, stationary in ROLE_CASES:
        got = _role_row("engine", over, span, stationary, roles_cfg)
        assert got == ROLE_EXPECTED[name], (name, got)


def test_assign_role_resets_the_six_fields_first() -> None:
    from engine.roles.roles import assign_role

    it = _item(group="feature", class_name="curb", label="curb")
    it.role, it.urgency, it.collision, it.summary_ok, it.proximity = "danger", "final", True, True, True
    assign_role(it, None, _real_roles(), 0.6, 0.7)
    assert [getattr(it, f) for f in ROLE_FIELDS[:5]] == ["none", "none", False, False, False]
