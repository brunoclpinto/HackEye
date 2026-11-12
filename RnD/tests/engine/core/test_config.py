from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

# Expected values / messages were produced by running the legacy lab.collisions / common_paths / collision.load_config
# functions in the hackeye-rnd image.

_CFG: dict[str, Any] = {"a": {"b": 1, "c": "x", "d": [1], "e": None}, "f": True, "g": 2.5, "source": {}}
_WM: dict[str, Any] = {"a": 1}


def test_find_common_dir_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from engine.core import paths

    monkeypatch.setenv("HACKEYE_COMMON_DIR", str(tmp_path))
    assert paths.find_common_dir() == tmp_path


def test_find_common_dir_unset_container(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.core import paths

    if not Path("/common").exists():
        pytest.skip("only in the container")
    monkeypatch.delenv("HACKEYE_COMMON_DIR", raising=False)
    assert paths.find_common_dir() == Path("/common")


def test_find_common_dir_env_missing_falls_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from engine.core import paths

    if not Path("/common").exists():
        pytest.skip("only in the container")
    monkeypatch.setenv("HACKEYE_COMMON_DIR", str(tmp_path / "nope"))
    assert paths.find_common_dir() == Path("/common")


def test_find_common_dir_facade_identity() -> None:
    import common_paths
    from engine.core import paths

    assert common_paths.find_common_dir is paths.find_common_dir


def test_load_config_real_file() -> None:
    from engine.core import config, paths

    with open(paths.find_common_dir() / "config" / "collision.json") as f:
        expected = json.load(f)
    got = config.load_config()
    assert got["version"] == expected["version"]
    assert got == expected


def test_load_config_explicit_path(tmp_path: Path) -> None:
    from engine.core import config

    p = tmp_path / "x.json"
    p.write_text(json.dumps({"version": "t", "k": [1, 2]}))
    assert config.load_config(p) == {"version": "t", "k": [1, 2]}


def test_load_config_facade() -> None:
    import collision
    from engine.core import config

    assert hasattr(collision, "load_config")
    assert config.load_config.__module__ == "engine.core.config"


@pytest.mark.parametrize(
    "value, kind",
    [(True, "bool"), (1, "number"), (1.5, "number"), ("s", "string"), ([1], "list"), ({}, "object"), (None, "null")],
)
def test_value_kind(value: object, kind: str) -> None:
    from engine.core import config

    assert config.value_kind(value) == kind


def test_validate_overrides_valid() -> None:
    from engine.core import config

    assert config.validate_overrides(None) == {}
    assert config.validate_overrides({}) == {}
    assert config.validate_overrides({"collision": {"a.b": 1}, "worldmap": {}}) == {"collision": {"a.b": 1}}
    assert config.validate_overrides({"collision": {}}) == {}


@pytest.mark.parametrize(
    "bad, msg",
    [
        (5, "overrides must be an object"),
        ({"foo": {}}, "overrides: unknown config 'foo' (expected collision or worldmap)"),
        ({"collision": [1]}, "overrides.collision must be an object of dotted keys"),
        ({"worldmap": None}, "overrides.worldmap must be an object of dotted keys"),
    ],
)
def test_validate_overrides_errors(bad: object, msg: str) -> None:
    from engine.core import config

    with pytest.raises(config.OverrideError) as ei:
        config.validate_overrides(bad)
    assert str(ei.value) == msg
    assert isinstance(ei.value, ValueError)


def test_apply_overrides_values() -> None:
    from engine.core import config

    assert config.apply_overrides(_CFG, {"collision": {"a.b": 2.5, "f": False}}, "collision") == {
        "a": {"b": 2.5, "c": "x", "d": [1], "e": None},
        "f": False,
        "g": 2.5,
        "source": {},
    }
    # other group untouched
    assert config.apply_overrides(_CFG, {"collision": {"a.b": 2.5}}, "worldmap") == _CFG
    assert config.apply_overrides(_CFG, {}, "collision") == _CFG
    assert config.apply_overrides(_CFG, {"worldmap": {"a.b": 3}}, "worldmap")["a"]["b"] == 3
    assert config.apply_overrides(_CFG, {"collision": {"a.e": "anything"}}, "collision")["a"]["e"] == "anything"
    assert config.apply_overrides(_CFG, {"collision": {"a.d": [2, 3]}}, "collision")["a"]["d"] == [2, 3]


def test_apply_overrides_does_not_mutate() -> None:
    from engine.core import config

    before = copy.deepcopy(_CFG)
    out = config.apply_overrides(_CFG, {"collision": {"a.b": 9}}, "collision")
    assert out["a"]["b"] == 9
    assert before == _CFG


def test_apply_overrides_pending_keys_created() -> None:
    from engine.core import config

    assert config.apply_overrides(_CFG, {"collision": {"source.mode": "map"}}, "collision")["source"] == {"mode": "map"}
    out = config.apply_overrides(
        _CFG, {"collision": {"speech.predictive.enabled": True, "horizon.source": "fused"}}, "collision"
    )
    assert out["speech"] == {"predictive": {"enabled": True}}
    assert out["horizon"] == {"source": "fused"}


def test_pending_keys_and_is_pending() -> None:
    from engine.core import config

    assert config.PENDING_KEYS == {
        "collision": {
            "source.mode": ("image", "map"),
            "speech.predictive.enabled": (True, False),
            "ego.headingSource": ("auto", "imu", "gyro", "flow"),
            "horizon.source": ("image", "gravity", "fused"),
            "ego.cadenceSource": ("auto", "imu", "image"),
        },
        "worldmap": {},
    }
    assert config.is_pending("collision", "source.mode", "image") is True
    assert config.is_pending("collision", "source.mode", "bad") is False
    assert config.is_pending("collision", "speech.predictive.enabled", 1) is False
    assert config.is_pending("worldmap", "x", 1) is False
    assert config.is_pending("zz", "x", 1) is False


@pytest.mark.parametrize(
    "group, overrides, msg",
    [
        ("collision", {"source.mode": "bogus"}, "overrides.collision: unknown key 'source.mode'"),
        ("collision", {"a.b": "s"}, "overrides.collision: 'a.b' must be a number, not a string"),
        ("collision", {"a": 1}, "overrides.collision: 'a' is a section; name a value inside it"),
        ("collision", {"a.zz": 1}, "overrides.collision: unknown key 'a.zz'"),
        ("collision", {"zz.y": 1}, "overrides.collision: unknown key 'zz.y'"),
        ("collision", {"": 1}, "overrides.collision: bad key ''"),
        ("collision", {5: 1}, "overrides.collision: bad key 5"),
        ("collision", {"a.b.q": 1}, "overrides.collision: unknown key 'a.b.q'"),
    ],
)
def test_apply_overrides_errors(group: str, overrides: dict[Any, Any], msg: str) -> None:
    from engine.core import config

    with pytest.raises(config.OverrideError) as ei:
        config.apply_overrides(_CFG, {group: overrides}, group)
    assert str(ei.value) == msg


def test_apply_overrides_pending_allowed_values() -> None:
    from engine.core import config

    cfg = {"ego": {"headingSource": "auto"}, "speech": {"predictive": {"enabled": False}}}
    assert config.apply_overrides(cfg, {"collision": {"ego.headingSource": "gyro"}}, "collision") == {
        "ego": {"headingSource": "gyro"},
        "speech": {"predictive": {"enabled": False}},
    }
    with pytest.raises(config.OverrideError) as ei:
        config.apply_overrides(cfg, {"collision": {"ego.headingSource": "bogus"}}, "collision")
    assert str(ei.value) == "overrides.collision: 'ego.headingSource' must be one of ['auto', 'imu', 'gyro', 'flow']"
    with pytest.raises(config.OverrideError) as ei2:
        config.apply_overrides(cfg, {"collision": {"speech.predictive.enabled": 1}}, "collision")
    assert str(ei2.value) == "overrides.collision: 'speech.predictive.enabled' must be a bool, not a number"
    assert config.apply_overrides(cfg, {"collision": {"speech.predictive.enabled": True}}, "collision")["speech"] == {
        "predictive": {"enabled": True}
    }


def test_check_overrides() -> None:
    from engine.core import config

    assert config.check_overrides({"collision": {"a.b": 2}}, _CFG, _WM) is None
    with pytest.raises(config.OverrideError) as e1:
        config.check_overrides({"collision": {"a.b": "x"}}, _CFG, _WM)
    assert str(e1.value) == "overrides.collision: 'a.b' must be a number, not a string"
    with pytest.raises(config.OverrideError) as e2:
        config.check_overrides({"worldmap": {"a": "x"}}, _CFG, _WM)
    assert str(e2.value) == "overrides.worldmap: 'a' must be a number, not a string"
    with pytest.raises(config.OverrideError) as e3:
        config.check_overrides({"worldmap": {"q": "x"}}, _CFG, _WM)
    assert str(e3.value) == "overrides.worldmap: unknown key 'q'"


def test_lab_wrappers_raise_collision_error_422() -> None:
    from engine.core import config
    from lab import collisions as lab_collisions

    assert issubclass(config.OverrideError, ValueError)
    with pytest.raises(lab_collisions.CollisionError) as e1:
        lab_collisions.validate_overrides(5)
    assert e1.value.status == 422
    assert str(e1.value) == "overrides must be an object"
    with pytest.raises(lab_collisions.CollisionError) as e2:
        lab_collisions.apply_overrides(_CFG, {"collision": {"a.b": "s"}}, "collision")
    assert e2.value.status == 422
    assert str(e2.value) == "overrides.collision: 'a.b' must be a number, not a string"
    with pytest.raises(lab_collisions.CollisionError) as e3:
        lab_collisions.check_overrides({"worldmap": {"q": "x"}}, _CFG, _WM)
    assert e3.value.status == 422
    assert str(e3.value) == "overrides.worldmap: unknown key 'q'"


def test_lab_aliases_same_objects() -> None:
    from engine.core import config
    from lab import collisions as lab_collisions

    assert lab_collisions.PENDING_KEYS is config.PENDING_KEYS
    assert lab_collisions._kind is config.value_kind
    assert lab_collisions._pending is config.is_pending
