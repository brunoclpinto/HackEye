"""Tests of lab._forward.install (v26.3.0 p5-02) on synthetic modules, not on the real facades.

``install(module_name, forwards)`` turns the flat module into a forwarding module: reads, writes and deletes of the
listed names go to the home module (``forwards`` maps legacy name -> home module name); every other name behaves
normally.
"""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

FLAT = "p5fwd_flat"
FLAT2 = "p5fwd_flat2"
HOME_A = "p5fwd_home_a"
HOME_B = "p5fwd_home_b"


@pytest.fixture
def mods() -> Iterator[tuple[Any, Any, Any]]:
    flat = types.ModuleType(FLAT)
    home_a = types.ModuleType(HOME_A)
    home_b = types.ModuleType(HOME_B)
    home_a.__dict__.update(counter=1, registry={"k": 1}, double=lambda x: 2 * x)
    home_b.__dict__.update(limit=60)
    flat.__dict__.update(local="flat-only", helper=lambda: "h")
    for m in (flat, home_a, home_b):
        sys.modules[m.__name__] = m
    try:
        yield flat, home_a, home_b
    finally:
        for name in (FLAT, FLAT2, HOME_A, HOME_B):
            sys.modules.pop(name, None)


def _install(forwards: dict[str, str] | None = None) -> None:
    from lab import _forward

    _forward.install(
        FLAT,
        forwards
        if forwards is not None
        else {"counter": HOME_A, "registry": HOME_A, "double": HOME_A, "limit": HOME_B},
    )


def test_reads_forward_to_the_home_object(mods: tuple[Any, Any, Any]) -> None:
    flat, home_a, home_b = mods
    _install()
    assert flat.counter == 1
    assert flat.registry is home_a.registry
    assert flat.double is home_a.double
    assert flat.double(4) == 8
    assert flat.limit == 60
    assert getattr(flat, "limit") is home_b.limit  # noqa: B009


def test_reads_follow_later_changes_of_the_home(
    mods: tuple[Any, Any, Any],
) -> None:
    flat, home_a, _ = mods
    _install()
    home_a.counter = 7
    assert flat.counter == 7


def test_writes_forward_and_do_not_stay_on_the_flat_module(
    mods: tuple[Any, Any, Any],
) -> None:
    flat, home_a, _ = mods
    _install()
    new: dict[str, int] = {"z": 9}
    flat.registry = new
    flat.counter = 5
    assert home_a.registry is new
    assert home_a.counter == 5
    assert "registry" not in vars(flat)
    assert "counter" not in vars(flat)
    assert flat.registry is new


def test_delattr_forwards(mods: tuple[Any, Any, Any]) -> None:
    flat, home_a, _ = mods
    _install()
    del flat.counter
    assert not hasattr(home_a, "counter")
    assert not hasattr(flat, "counter")
    assert hasattr(home_a, "registry")


def test_monkeypatch_setattr_changes_the_home_and_undo_restores(
    mods: tuple[Any, Any, Any],
) -> None:
    flat, home_a, _ = mods
    _install()
    old = home_a.registry
    mp = pytest.MonkeyPatch()
    replacement: dict[str, int] = {}
    mp.setattr(flat, "registry", replacement)
    assert home_a.registry is replacement
    mp.setattr(flat, "counter", 99)
    assert home_a.counter == 99
    mp.setattr(flat, "double", lambda x: x)
    assert home_a.double(3) == 3
    mp.undo()
    assert home_a.registry is old
    assert home_a.counter == 1
    assert home_a.double(3) == 6
    assert flat.registry is old
    assert "registry" not in vars(flat)


def test_home_code_sees_a_patch_made_on_the_flat_module(
    mods: tuple[Any, Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    flat, home_a, _ = mods
    exec("def read():\n    return counter\n", home_a.__dict__)  # a function whose globals are the home's
    _install()
    monkeypatch.setattr(flat, "counter", 41)
    assert home_a.read() == 41


def test_non_forwarded_names_behave_normally(mods: tuple[Any, Any, Any]) -> None:
    flat, home_a, _ = mods
    _install()
    assert flat.local == "flat-only"
    assert flat.helper() == "h"
    flat.local = "changed"
    assert vars(flat)["local"] == "changed"
    assert not hasattr(home_a, "local")
    flat.fresh = 3
    assert vars(flat)["fresh"] == 3
    del flat.fresh
    assert not hasattr(flat, "fresh")
    with pytest.raises(AttributeError):
        _ = flat.nothing_here
    with pytest.raises(AttributeError):
        del flat.nothing_here


def test_module_identity_is_kept(mods: tuple[Any, Any, Any]) -> None:
    flat, _, _ = mods
    _install()
    assert sys.modules[FLAT] is flat
    assert flat.__name__ == FLAT
    assert isinstance(flat, types.ModuleType)


def test_two_flat_modules_forward_to_one_home(
    mods: tuple[Any, Any, Any],
) -> None:
    from lab import _forward

    flat, home_a, _ = mods
    flat2: Any = types.ModuleType(FLAT2)
    sys.modules[FLAT2] = flat2
    _install({"registry": HOME_A})
    _forward.install(FLAT2, {"registry": HOME_A})
    assert flat.registry is flat2.registry is home_a.registry
    flat2.registry = {"w": 1}
    assert flat.registry == {"w": 1}


def test_a_forwarded_name_missing_in_the_home_is_an_attribute_error(
    mods: tuple[Any, Any, Any],
) -> None:
    flat, _, _ = mods
    _install({"ghost": HOME_A})
    with pytest.raises(AttributeError):
        _ = flat.ghost
