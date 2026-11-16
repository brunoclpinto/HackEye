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

## Opus notes (2026-11-16, after the worker)
- **Versions:**
  - eslint 9.39.5 rather than 10.x, because `eslint-plugin-import` 2.32.0 supports eslint up to 9;
  - `globals` 17.14.0;
  - `node:22.23.5-bookworm-slim`.
- The config is CommonJS. The packages live in the image under `/opt/js`, and only `require()` honours `NODE_PATH`.
- Node tests must be named `tests/js/**/*.test.mjs`, because node 22's `--test` does not take a bare directory.
- The JS step runs first and stops the gate on failure. Python-only invocations are unchanged.
- Baseline over `lab/static`: 2 `no-unused-vars` in `js/classes.js` (`KEY` at line 7, `name` at line 174) and 0 `import/no-cycle`. The rule was checked on a scratch a.js/b.js cycle. p6-05 brings the count to 0.
