# p4-07 field ownership (static guard)

## What changes
- `engine.core.types` gets `FIELD_WRITERS: dict[str, tuple[str, ...]]`: for every dataclass field of `Item` and `Track`,
  `"Item.<field>"` → the models allowed to write it (the owner first). Build it from audit section 4 (field writers) and re-verify it
  with the AST scan below on the current code; `pipeline` may write any field and is not listed.
  Construction-only fields (set only by the constructor / `replace(...)` in their model) list that model.
- `tests/test_field_ownership.py` (the Phase 0 skeleton; Opus rewrites it with the tests worker's code): it scans every
  `src/engine/<model>/**/*.py` except `pipeline` and `core` for writes to `Item` / `Track` fields: assignments to `<expr>.<field>` where
  `<field>` is a field name of those types, augmented assignments, and keyword arguments of `replace(...)` / `Item(...)` /
  `Track(...)`. It fails on a write by a model not in `FIELD_WRITERS[field]`, and on a field without an entry or an unknown model
  (checked against `BOUNDARIES.toml`). Attribute names that are not `Item` / `Track` fields are ignored; a field name shared with an
  unrelated object (e.g. `self.speed` in `WorldMemory`) is excluded by an explicit allow-list in the test, each with a reason.
- Each model README gets a "Fields written" line taken from the table.

## Tests (Sonnet): the rewritten `tests/test_field_ownership.py`
- The three checks above, plus a negative test: a synthetic source string with a forbidden write is reported.
