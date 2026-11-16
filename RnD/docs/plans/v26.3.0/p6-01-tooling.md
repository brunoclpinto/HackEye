# p6-01 JS tooling (no tests-first; Opus reviews)

- `tools/js/package.json` + `package-lock.json`: devDependencies `eslint`, `@eslint/js`, `eslint-plugin-import`, `globals`, exact versions
  (no ranges), versions at least two weeks old.
- `tools/js-check.Dockerfile`: `FROM node:<exact tag>`; copies `tools/js/package*.json`, `npm ci`; working dir `/rnd`.
- `tools/js/eslint.config.js`: flat config for `lab/static/**/*.js` and `tests/js/**/*.mjs`: `js.configs.recommended`, browser globals for
  the page, node globals for tests, `import/no-cycle: error`, `no-unused-vars: error`. Do not fix lint findings in this task: report the
  count per rule (p6-05 brings it to 0); the gate step runs eslint only on the `--files` given, so today's code is not blocked.
- `tools/check.sh` / `check_inner.sh`: when `--files` has `.js` / `.mjs` files, run eslint on them and `node --test tests/js` in the
  js-check image (via `tools/check.compose.yaml`, a second service); print the step in the summary.
- `tests/js/smoke.test.mjs`: imports `lab/static/js/util.js` and asserts one function, to prove the runner works.
