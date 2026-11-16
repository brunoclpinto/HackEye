# p6-05 eslint 0 / 0 and no-cycle

Bring `eslint` on `lab/static/**/*.js` and `tests/js/**` to 0 errors / 0 warnings with lint-only edits (unused vars removed only when
truly unused; no logic changes), `import/no-cycle` clean, and make the check gate run eslint on the whole tree when any `.js` changes.
- Gate: eslint 0/0, node tests, JS boundary test, staging E2E 96/96.
