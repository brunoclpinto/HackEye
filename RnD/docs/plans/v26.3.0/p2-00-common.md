# Phase 2 (perception): rules shared by every p2 spec

Read this after [README.md](README.md). Each p2 spec lists only its moves, its facade names and its specific risks.

## Moves
- Code moves **verbatim** into `src/engine/<model>/<module>.py`.
- Engine names lose their leading underscore (`_Scale` → `Scale`). The legacy module (`collision.py` or `sensors.py`) keeps every old name as an alias of the **same object**.
- The model package `__init__.py` re-exports the public API with `__all__`. Never re-export a function whose name equals a submodule name (the `engine.core.log` lesson).
- A model may import only `engine.core.*`, its own modules, numpy and scipy (see `BOUNDARIES.toml`). If a moved symbol needs another model, stop and report it; Opus decides.
- Allowed lint-only edits:
  - type annotations, using a local `Protocol` where a legacy type would be needed;
  - `_` prefixes on unused variables;
  - comments moved above long lines;
  - `# noqa: <rule>` on verbatim expressions;
  - formatting.
  Nothing else.
- Each model gets a `README.md`: purpose, public API, inputs/outputs, config keys read (grep `cfg.get(` / `config[`), invariants. Take the relevant changelog lines from the `collision.py` module docstring (lines 1–185, audit 1.1) into the README, and leave the docstring unchanged.
- Code still in `collision.py` keeps calling the old names unqualified.

## Tests
- **Characterisation:** pin literals produced by the legacy code.
- For big functions on real data (`detect_items`, trackers, anchors), use a fixture from `tests/fixtures/*.npz` and see how the existing `tests/test_collision*.py` load them. Pin compact digests instead of huge literals: counts, ordered label lists, sums or means rounded with `pytest.approx(rel=1e-12)`, and the first and last elements.
- Include the facade identity tests and the exact field or attribute lists of every moved class (tests use `__new__` and private attributes; audit 6.4).
- Seeded randomness (`_plane_fit` uses `RandomState(12345)`): pin results; never reseed.

## Gate
- `tools/check.sh --files <changed> --tests tests/engine/<model> --related` must be green; it includes the quick equivalence check.

## Order
- Tests for all p2 tasks can be written up front. They are red until implemented, so write them only between checkpoints: a red test breaks the full suite.
- Implementation order: p2-01 → p2-02 → p2-03 → p2-04 (series needs 01–03), then p2-05, p2-06, p2-07, p2-08, p2-09, p2-10, p2-11, p2-12.
- Implementations that touch only disjoint files may run in parallel. `sensors.py`-only tasks (p2-02, p2-03) are disjoint from the `collision.py` tasks, but p2-02 and p2-03 share `sensors.py`, so they run one after the other.
