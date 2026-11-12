"""Characterisation tests for engine.core.settings (literals produced by the legacy collision functions)."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from common_paths import find_common_dir

_BASE: dict[str, Any] = {
    "mount": "chest",
    "hfov_deg": 118.0,
    "camera_height_m": 1.3,
    "step_length_m": None,
    "horizon_default": 0.45,
    "projection": "fisheye",
    "distance_source": "ground",
    "depth_level_prior": None,
    "user_height_m": None,
    "camera_location": None,
    "camera_side": None,
    "lateral_offset_m": 0.0,
    "object_distance": "depth",
    "use_horizon": True,
    "step_length_user": False,
}

_FIELDS = [
    "mount",
    "hfov_deg",
    "camera_height_m",
    "step_length_m",
    "horizon_default",
    "projection",
    "distance_source",
    "depth_level_prior",
    "user_height_m",
    "camera_location",
    "camera_side",
    "lateral_offset_m",
    "object_distance",
    "use_horizon",
    "step_length_user",
]


def _real_config() -> dict[str, Any]:
    with open(find_common_dir() / "config" / "collision.json") as f:
        cfg: dict[str, Any] = json.load(f)
    return cfg


def _check(actual: Any, **over: Any) -> None:
    exp = {**_BASE, **over}
    got = dataclasses.asdict(actual)
    assert list(got) == list(exp)
    for k, v in exp.items():
        if isinstance(v, float):
            assert got[k] == pytest.approx(v, rel=1e-12, abs=1e-12), k
        else:
            assert got[k] == v, k


def test_identity_of_moved_names() -> None:
    import collision
    from engine.core import settings

    assert collision.CollisionSettings is settings.CollisionSettings
    assert collision.resolve_projection is settings.resolve_projection
    assert collision.resolve_settings is settings.resolve_settings
    assert collision.AUTO_FISHEYE_HFOV_DEG is settings.AUTO_FISHEYE_HFOV_DEG
    assert collision.DISTANCE_SOURCES is settings.DISTANCE_SOURCES
    assert collision.OBJECT_DISTANCES is settings.OBJECT_DISTANCES
    assert collision.SIDE_SIGN is settings.SIDE_SIGN
    assert collision.WARMUP_S is settings.WARMUP_S
    assert collision.HORIZON_HOLD_S is settings.HORIZON_HOLD_S
    assert collision.MIN_TRACK_AGE_S is settings.MIN_TRACK_AGE_S


def test_constants() -> None:
    from engine.core import settings

    assert settings.AUTO_FISHEYE_HFOV_DEG == 100.0
    assert settings.DISTANCE_SOURCES == ("ground", "depth")
    assert settings.OBJECT_DISTANCES == ("depth", "ground-contact", "ground+depth")
    assert settings.SIDE_SIGN == {"left": -1.0, "center": 0.0, "right": 1.0}
    assert list(settings.SIDE_SIGN) == ["left", "center", "right"]
    assert settings.WARMUP_S == 1.5
    assert settings.HORIZON_HOLD_S == 3.0
    assert settings.MIN_TRACK_AGE_S == 0.5


def test_collision_settings_field_order() -> None:
    from engine.core.settings import CollisionSettings

    assert [f.name for f in dataclasses.fields(CollisionSettings)] == _FIELDS


def test_collision_settings_positional_and_defaults() -> None:
    from engine.core.settings import CollisionSettings

    s = CollisionSettings("chest", 118.0, 1.3, None, 0.45)
    assert dataclasses.asdict(s) == {**_BASE, "projection": "rectilinear"}


@pytest.mark.parametrize(
    ("projection", "hfov", "expected"),
    [
        (None, 100, "fisheye"),
        (None, 140, "fisheye"),
        (None, 99.9, "rectilinear"),
        (None, 60, "rectilinear"),
        ("rectilinear", 140, "rectilinear"),
        ("fisheye", 60, "fisheye"),
        ("auto", 140, "fisheye"),
        ("auto", 60, "rectilinear"),
        ("bogus", 140, "fisheye"),
        ("bogus", 60, "rectilinear"),
    ],
)
def test_resolve_projection(projection: str | None, hfov: float, expected: str) -> None:
    from engine.core.settings import resolve_projection

    assert resolve_projection(projection, hfov) == expected


@pytest.mark.parametrize("mount", [None, "left", "center", "right"])
@pytest.mark.parametrize("hfov", [None, 100.0, 140.0])
def test_resolve_settings_grid_unknown_and_default_mounts(mount: str | None, hfov: float | None) -> None:
    from engine.core.settings import resolve_settings

    # "left"/"center"/"right" are not mount presets: legacy falls back to the default mount "chest".
    _check(resolve_settings(_real_config(), mount=mount, hfov_deg=hfov), hfov_deg=118.0 if hfov is None else hfov)


@pytest.mark.parametrize(
    ("mount", "hfov", "over"),
    [
        ("head", None, {"mount": "head", "camera_height_m": 1.65, "horizon_default": 0.4}),
        (
            "head",
            60.0,
            {
                "mount": "head",
                "hfov_deg": 60.0,
                "camera_height_m": 1.65,
                "horizon_default": 0.4,
                "projection": "rectilinear",
            },
        ),
        ("head", 140.0, {"mount": "head", "hfov_deg": 140.0, "camera_height_m": 1.65, "horizon_default": 0.4}),
        ("handheld", None, {"mount": "handheld", "camera_height_m": 1.1, "horizon_default": 0.5}),
        (
            "handheld",
            60.0,
            {
                "mount": "handheld",
                "hfov_deg": 60.0,
                "camera_height_m": 1.1,
                "horizon_default": 0.5,
                "projection": "rectilinear",
            },
        ),
        ("handheld", 140.0, {"mount": "handheld", "hfov_deg": 140.0, "camera_height_m": 1.1, "horizon_default": 0.5}),
    ],
)
def test_resolve_settings_real_mounts(mount: str, hfov: float | None, over: dict[str, Any]) -> None:
    from engine.core.settings import resolve_settings

    _check(resolve_settings(_real_config(), mount=mount, hfov_deg=hfov), **over)


def test_resolve_settings_depth_source_and_explicit_projection() -> None:
    from engine.core.settings import resolve_settings

    _check(
        resolve_settings(_real_config(), distance_source="depth", projection="rectilinear", hfov_deg=140.0),
        hfov_deg=140.0,
        projection="rectilinear",
        distance_source="depth",
    )


def test_resolve_settings_body_mode_default_height() -> None:
    from engine.core.settings import resolve_settings

    _check(
        resolve_settings(_real_config(), user_height_m=1.7),
        camera_height_m=1.224,
        step_length_m=0.7054999999999999,
        user_height_m=1.7,
        camera_location="chest",
        camera_side="center",
    )


def test_resolve_settings_body_mode_all_overrides() -> None:
    from engine.core.settings import resolve_settings

    s = resolve_settings(
        _real_config(),
        camera_location="eye",
        user_height_m=1.9,
        camera_side="left",
        step_length_m=0.5,
        camera_height_m=1.2,
        projection="fisheye",
        use_horizon=False,
        object_distance="ground-contact",
    )
    _check(
        s,
        camera_height_m=1.2,
        step_length_m=0.5,
        horizon_default=0.5,
        user_height_m=1.9,
        camera_location="eye",
        camera_side="left",
        lateral_offset_m=-0.07,
        object_distance="ground-contact",
        use_horizon=False,
        step_length_user=True,
    )


def test_resolve_settings_body_waist_right() -> None:
    from engine.core.settings import resolve_settings

    _check(
        resolve_settings(_real_config(), camera_location="waist", user_height_m=1.6, camera_side="right"),
        camera_height_m=0.9279999999999999,
        step_length_m=0.664,
        user_height_m=1.6,
        camera_location="waist",
        camera_side="right",
        lateral_offset_m=0.15,
    )


def test_resolve_settings_body_head_default_height() -> None:
    from engine.core.settings import resolve_settings

    _check(
        resolve_settings(_real_config(), camera_location="head", camera_side="center"),
        camera_height_m=1.83,
        step_length_m=0.7387,
        horizon_default=0.48,
        user_height_m=1.78,
        camera_location="head",
        camera_side="center",
    )


def test_resolve_settings_unknown_mount_edge() -> None:
    from engine.core.settings import resolve_settings

    _check(resolve_settings(_real_config(), mount="nope"))


def test_resolve_settings_unknown_distance_source_edge() -> None:
    from engine.core.settings import resolve_settings

    _check(resolve_settings(_real_config(), distance_source="x"))


def test_resolve_settings_unknown_object_distance_edge() -> None:
    from engine.core.settings import resolve_settings

    _check(resolve_settings(_real_config(), object_distance="x"))


def test_resolve_settings_unknown_location_and_side_edge() -> None:
    from engine.core.settings import resolve_settings

    _check(
        resolve_settings(_real_config(), camera_location="zzz", camera_side="zzz"),
        camera_height_m=1.2816,
        step_length_m=0.7387,
        user_height_m=1.78,
        camera_location="chest",
        camera_side="center",
    )


def test_resolve_settings_missing_body_section_ignores_body_args() -> None:
    from engine.core.settings import resolve_settings

    cfg = {k: v for k, v in _real_config().items() if k not in ("body", "distance")}
    _check(resolve_settings(cfg, user_height_m=1.7, camera_location="eye"))


def test_resolve_settings_missing_presets_section_raises() -> None:
    from engine.core.settings import resolve_settings

    cfg = {k: v for k, v in _real_config().items() if k != "mountPresets"}
    with pytest.raises(KeyError, match="mountPresets"):
        resolve_settings(cfg)


_MINI: dict[str, Any] = {
    "defaultMount": "m",
    "defaultHfovDeg": 90,
    "mountPresets": {"m": {"horizon": 0.3, "cameraHeightM": 2.0, "depthLevelPrior": 2.5}},
}


def test_resolve_settings_minimal_config_with_depth_prior() -> None:
    from engine.core.settings import resolve_settings

    _check(
        resolve_settings(_MINI),
        mount="m",
        hfov_deg=90.0,
        camera_height_m=2.0,
        horizon_default=0.3,
        projection="rectilinear",
        depth_level_prior=2.5,
    )


def test_resolve_settings_minimal_config_explicit_values() -> None:
    from engine.core.settings import resolve_settings

    _check(
        resolve_settings(_MINI, camera_height_m=1.0, step_length_m=0.6, projection="fisheye", use_horizon=False),
        mount="m",
        hfov_deg=90.0,
        camera_height_m=1.0,
        step_length_m=0.6,
        horizon_default=0.3,
        projection="fisheye",
        depth_level_prior=2.5,
        use_horizon=False,
        step_length_user=True,
    )


def test_resolve_settings_minimal_config_body_args_ignored_without_body() -> None:
    from engine.core.settings import resolve_settings

    _check(
        resolve_settings(_MINI, user_height_m=1.7, camera_location="eye"),
        mount="m",
        hfov_deg=90.0,
        camera_height_m=2.0,
        horizon_default=0.3,
        projection="rectilinear",
        depth_level_prior=2.5,
    )
