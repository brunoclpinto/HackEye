"""Config loading and the Lab's dotted-key config overrides (validate, apply, check)."""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any

from engine.core.paths import find_common_dir

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "PENDING_KEYS",
    "OverrideError",
    "apply_overrides",
    "check_overrides",
    "is_pending",
    "load_config",
    "validate_overrides",
    "value_kind",
]


class OverrideError(ValueError):
    """A config override is malformed or names an unknown key; the message is shown to the user."""


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or (find_common_dir() / "config" / "collision.json")
    with open(path) as f:
        data: dict[str, Any] = json.load(f)
        return data


def value_kind(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return "null"


def validate_overrides(overrides: Any) -> dict[str, Any]:
    """Shape check: {} or {"collision": {key: value}, "worldmap": {key: value}}; returns the normalised dict
    (empty groups dropped)."""
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise OverrideError("overrides must be an object")
    out: dict[str, Any] = {}
    for group, items in overrides.items():
        if group not in ("collision", "worldmap"):
            raise OverrideError(f"overrides: unknown config {group!r} (expected collision or worldmap)")
        if not isinstance(items, dict):
            raise OverrideError(f"overrides.{group} must be an object of dotted keys")
        if items:
            out[group] = dict(items)
    return out


# v26.2.11: settings the Lab sends as overrides before (or while) the backend adds them to the config. A key missing
# from the config is accepted when it is listed here with one of its allowed values (it is then created); once the
# config has it, the normal checks apply.
PENDING_KEYS = {
    "collision": {
        "source.mode": ("image", "map"),
        "speech.predictive.enabled": (True, False),
        "ego.headingSource": ("auto", "imu", "gyro", "flow"),
        "horizon.source": ("image", "gravity", "fused"),
        "ego.cadenceSource": ("auto", "imu", "image"),
    },
    "worldmap": {},
}


def is_pending(group: str, key: str, value: Any) -> bool:
    allowed = PENDING_KEYS.get(group, {}).get(key)
    return allowed is not None and any(value == a and type(value) is type(a) for a in allowed)


def apply_overrides(config: dict[str, Any], overrides: dict[str, Any], group: str) -> dict[str, Any]:
    """A deep copy of `config` with the `group` overrides applied (dotted keys). Each key must exist and keep its JSON
    type; else OverrideError naming the key. The loaded config is never mutated."""
    out = copy.deepcopy(config)
    for key, value in (overrides.get(group) or {}).items():
        if not isinstance(key, str) or not key:
            raise OverrideError(f"overrides.{group}: bad key {key!r}")
        parts = key.split(".")
        node = out
        pending = is_pending(group, key, value)
        for p in parts[:-1]:
            if isinstance(node, dict) and p not in node and pending:
                node[p] = {}
            if not isinstance(node, dict) or p not in node:
                raise OverrideError(f"overrides.{group}: unknown key {key!r}")
            node = node[p]
        if isinstance(node, dict) and parts[-1] not in node and pending:
            node[parts[-1]] = value
            continue
        if not isinstance(node, dict) or parts[-1] not in node:
            raise OverrideError(f"overrides.{group}: unknown key {key!r}")
        old = node[parts[-1]]
        if value_kind(old) == "object":
            raise OverrideError(f"overrides.{group}: {key!r} is a section; name a value inside it")
        if old is not None and value_kind(value) != value_kind(old):
            raise OverrideError(f"overrides.{group}: {key!r} must be a {value_kind(old)}, not a {value_kind(value)}")
        allowed = PENDING_KEYS.get(group, {}).get(key)
        # v26.2.11: the keys of PENDING_KEYS keep their allowed values
        if allowed is not None and not is_pending(group, key, value):
            raise OverrideError(f"overrides.{group}: {key!r} must be one of {list(allowed)}")
        node[parts[-1]] = value
    return out


def check_overrides(overrides: dict[str, Any], collision_cfg: dict[str, Any], worldmap_cfg: dict[str, Any]) -> None:
    """Validate against the loaded configs before any work starts."""
    apply_overrides(collision_cfg, overrides, "collision")
    apply_overrides(worldmap_cfg, overrides, "worldmap")
