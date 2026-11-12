"""Field-ownership guard for the shared engine types (skeleton; enabled in Phase 4).

Intended behaviour once ``engine.core.types`` exposes ``FIELD_OWNERS`` (a mapping
``"<TypeName>.<field>" -> "<model>"``):

* every dataclass field of every shared type in ``engine.core.types`` has exactly one owning model;
* a model may write (assign / ``replace(...)``) only the fields it owns; the guard scans engine/<model>/** with the AST
  for attribute assignments and ``replace``/``__setattr__`` keyword targets on those types and fails on a write to a
  field owned by another model (message: file:line, field, owner);
* reads are unrestricted; ``engine.pipeline`` may write any field it merges between models only through the
  documented merge functions;
* every field has an owner and no owner names an unknown model (checked against BOUNDARIES.toml).
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest


def _owners() -> dict[str, str] | None:
    if importlib.util.find_spec("engine.core.types") is None:
        return None
    types = importlib.import_module("engine.core.types")
    owners = getattr(types, "FIELD_OWNERS", None)
    return dict(owners) if owners is not None else None


def test_every_field_has_one_known_owner() -> None:
    owners = _owners()
    if owners is None:
        pytest.skip("enabled in Phase 4 (engine.core.types ownership guard)")
    from tests.test_module_boundaries import load_config

    models = set(load_config()["models"])
    assert all(o in models for o in owners.values()), {k: v for k, v in owners.items() if v not in models}
