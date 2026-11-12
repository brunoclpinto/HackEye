# engine/ -- v26.3.0 independent model packages

The Lab logic of `collision.py` (and the flat modules) is split into packages `engine/<model>/`. Each model is
testable alone and may import only what `BOUNDARIES.toml` allows (stdlib, numpy/scipy, `engine.core`, its own
subpackages, plus per-model extras). **Only `engine.pipeline` imports other models.** Legacy modules keep every name as a
re-export of the same object. `tests/test_module_boundaries.py` enforces the import rules.

The gate command is `tools/check.sh` (ruff, mypy --strict, pytest). Run it before reporting; 0 errors, 0 warnings.

## Moving code (verbatim)

- Copy whole definitions (function, class, constant block) with a script or editor; **never retype** them.
- Allowed edits: imports, type annotations, docstrings, names the spec renames, lint-only `_` prefix for unused
  variables, wrapping long lines / comments. Anything else (logic, order of operations, constants, defaults) is not
  yours to change; if lint or mypy seems to demand it, stop and ask.
- Engine names are public (no leading underscore). The legacy module keeps the old private name as an alias of the
  **same object**: `_Item = engine.detection.Item`.

## Facade rules (legacy side)

- Aliases are the same objects (`collision.X is engine.m.X`). Tests monkeypatch `collision.X`, so code that stays in
  `collision` keeps calling names **unqualified** (a patched module attribute is seen only through the global lookup).
- Tests build `collision._Item(...)` / `_Track(...)` positionally and with `__new__`: keep attribute names and the
  **field order** of every moved dataclass.
- Keep calling `collision.load_config` (do not import or call the engine's loader from `collision`). `tests/conftest.py`
  replaces `collision.load_config` in `pytest_configure` with a wrapper that looks at the **caller's module name**
  (`sys._getframe(1)`) to switch the per-version defaults off for the older test modules, and a per-module fixture
  patches `worldmap.load_config` / `collision.load_config`. A call through any other name bypasses the patch and
  changes every pinned output.

## Imports

- Absolute imports (`from engine.core import ...`) or relative inside the same model. A relative import must not leave
  `engine`. Legacy flat modules (`collision`, `geometry`, `config`, ...) and `lab` are never imported from engine code.
- Imports anywhere count (inside functions, under `if TYPE_CHECKING`). No import cycles between models.
- Third-party packages: only those in `BOUNDARIES.toml` (default numpy + scipy; `infer` adds the GPU stack).
  Changing `BOUNDARIES.toml` is the planner's decision.

## Typing and style

- `from __future__ import annotations` at the top of every module; `__all__` lists the public names.
- `mypy --strict` clean (`tools/mypy-engine.ini`). Arrays: `npt.NDArray[np.float64]`, `npt.NDArray[np.bool_]`, ... with
  `import numpy.typing as npt`. No `Any` unless the legacy code is truly dynamic; no `# type: ignore` without a reason.
- Ruff config `tools/ruff-engine.toml` (line length 120, no docstring rules).

## Tests

- `tests/engine/<model>/test_*.py` (each dir has `__init__.py`; names need not be unique across models).
- Import `engine.<model>` **inside the test function** so a red test fails on its own and does not break collection.
- Equivalence against the legacy implementation is a separate tool (`tools/equivalence.py`).

## Determinism checklist

Moved code must produce bit-identical output. Check each:

- Iteration and insertion order of dicts/sets/lists is unchanged (no `set` where a `list` was, no re-sorting).
- Sorts are stable and keep the same keys and tie behaviour (`sorted(..., key=...)`, `argsort(kind=...)`).
- Nothing is keyed on `id()` / object identity differently than before (caches keyed on `id(x)` need the same lifetime).
- In-place mutation stays in place (arrays and lists that were mutated by the caller still are; no new copies, no lost
  aliasing); conversely do not start mutating inputs.
- Separate integrators / accumulators stay separate (do not merge two running sums that happened to look alike).
- Function-local variable scope is preserved (a variable assigned in one branch and read later; loop variables that
  leak after the loop; closures capturing by reference).
- Float evaluation order and dtype promotion are unchanged (`a * b / c` stays that way; no `np.float32` <-> float64 drift).
