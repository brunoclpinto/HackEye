# p6-05 eslint 0 / 0 and no-cycle

Bring `eslint` on `lab/static/**/*.js` and `tests/js/**` to 0 errors / 0 warnings with lint-only edits (unused vars removed only when
truly unused; no logic changes), `import/no-cycle` clean, and make the check gate run eslint on the whole tree when any `.js` changes.
- Gate: eslint 0/0, node tests, JS boundary test, staging E2E 96/96.

## Done (Opus, 2026-11-16)
- **Edits:**
  - `features/classes/classes.js`: removed the unused `KEY` constant and the unused `name` parameter of `changed()`. Callers still pass it, and it is ignored as before.
  - `tools/check_js_inner.sh`: any `.js` / `.mjs` in `--files` now lints all of `lab/static` + `tests/js` (`import/no-cycle` needs the whole graph).
- **Results:**
  - eslint 0 errors / 0 warnings;
  - `import/no-cycle` clean;
  - node tests 67/67;
  - boundary test green.
- The staging E2E runs at the Phase 6 checkpoint.
