"""Forwarding facades for the flat Lab modules (v26.3.0 p5-00 decision 1).

A name that moved into a `lab.<pkg>.<module>` home is deleted from its flat module (`analysis`, `collisions`, `recordings`);
`install` makes reads, writes and deletes of that name on the flat module go to the home module. Tests that rebind a module
global on the flat module (`monkeypatch.setattr(analysis, "_active", {})`) therefore rebind the home's global, which is the
one the moved code reads.
"""

from __future__ import annotations

import importlib
import sys
import types


def install(module_name: str, forwards: dict[str, str]) -> None:
    """forwards: legacy name -> 'lab.pkg.module'. Reads and writes of those names on the flat module go to the home module."""
    targets = dict(forwards)

    def _home(name: str) -> types.ModuleType:
        return importlib.import_module(targets[name])

    class _Forwarding(types.ModuleType):
        def __getattr__(self, name: str) -> object:
            # Only reached when the normal lookup failed, i.e. for names that are not in the flat module's own dict.
            if name in targets:
                return getattr(_home(name), name)
            raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

        def __setattr__(self, name: str, value: object) -> None:
            if name in targets:
                setattr(_home(name), name, value)
            else:
                super().__setattr__(name, value)

        def __delattr__(self, name: str) -> None:
            if name in targets:
                delattr(_home(name), name)
            else:
                super().__delattr__(name)

    module = sys.modules[module_name]
    for name in targets:  # a stale copy in the flat module's own dict would shadow the forwarding
        module.__dict__.pop(name, None)
    module.__class__ = _Forwarding
