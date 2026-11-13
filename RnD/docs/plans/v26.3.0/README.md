# v26.3.0 task specs: how workers use them

Plan: [../v26.3.0.md](../v26.3.0.md). Audit (symbol spans, pins, traps): [../v26.3.0-audit.md](../v26.3.0-audit.md).
Engine rules: [../../../src/engine/README.md](../../../src/engine/README.md). Read all three before starting a task.

Each spec `pN-NN-<name>.md` has three sections:
- **Tests**, for the tests worker;
- **Implementation**, for the implementation worker;
- **Done**, the acceptance criteria.

## Common rules
- Work only in the worktree `~/repos/HackEye/.worktrees/modular`, never in `~/repos/HackEye`.
- Workers never commit.
- Before reporting, kill every background process you started, check with `ps`, and say so in the report.
- Gate: `RnD/tools/check.sh --files <changed files> <task test files> --tests <task tests> --related` must end with 0 errors and 0 warnings. Always list the task's test files under `--files` too: they get mypy-checked in their final (green) state only then. In p1-03, a locked test failed mypy only at the phase check.

## Tests worker
1. Write only the files listed under **Tests**: `tests/engine/<model>/test_*.py`.
2. Import the engine module **inside each test function** (it does not exist yet). Preferred: a plain `from engine.core.x import y`; in the red phase the only allowed mypy errors are `import-not-found` / `attr-defined` for the missing engine module, and no `# type: ignore` (it becomes an unused-ignore error later). `importlib.import_module(...)` is also accepted. Fully type-hinted: annotate pytest fixtures (`monkeypatch: pytest.MonkeyPatch`, `capsys: pytest.CaptureFixture[str]`, `tmp_path: Path`) and `-> None`.
3. **Characterisation literals.** Every expected value in an assert must be computed by running the **legacy** function on today's code in the `hackeye-rnd` image (`docker compose run --rm -T --entrypoint python rnd -c ...` from `RnD/`). Paste the printed values in as literals; never compute by hand. Floats: use `pytest.approx(v, rel=1e-12, abs=1e-12)` unless the spec says otherwise.
4. **Facade identity tests:** `assert collision._old_name is engine.core.x.new_name`. Use `import collision` with a `# type: ignore[import-untyped]` only if mypy needs it; the check config already treats legacy modules as `Any`.
5. Prove the tests are **red**: run them and show that they fail only with `ModuleNotFoundError` / `ImportError` / `AttributeError` for the not-yet-existing engine names. Run `tools/check.sh --files <your test files>`: lint and types must pass; only pytest may fail, and only for that reason.
6. Report: the test names, which legacy calls produced which literals, and the red-run output.

## Implementation worker
1. The task's tests are **locked**: never edit them. If you believe a test is wrong, stop and report why.
2. Move code **verbatim**: copy whole definitions (decorators and the comment block above included), then delete them from the legacy file and add a re-export. Only the edits listed in the spec and in the engine README are allowed.
3. Legacy modules re-export **the same objects**: `from engine.core.clock import quarter_of_hour as _quarter_of_hour  # noqa: F401`.
4. Each new engine module gets:
   - a short docstring: what it owns;
   - `from __future__ import annotations`;
   - full type hints;
   - the package `__init__.py` re-exporting the public API with `__all__`.
5. Update the package `README.md` (purpose, API, inputs/outputs, config keys, invariants) when the spec says so.
6. Run `tools/check.sh --files <changed> --tests <task tests> --related` until it is green, and paste the final summary into the report.
