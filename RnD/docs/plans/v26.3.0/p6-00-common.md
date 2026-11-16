# Phase 6 (front end): rules shared by every p6 spec

The Lab page (`lab/static`: `index.html`, `app.js` 1,284 lines, `js/*.js` 4,274 lines; audit section 8) is split into
`js/app/` (`state.js`, `bus.js`, `bootstrap.js`) and one directory per feature under `js/features/`. A feature imports only `util`,
`api`, `state`, `bus` and files of its own directory (`BOUNDARIES.toml [js]`, enforced by `tests/test_module_boundaries.py`).

## Decisions (Opus, 2026-11-16)
1. **Tooling in its own pinned image.** `tools/js-check.Dockerfile` (pinned `node` tag + pinned `eslint`, `eslint-plugin-import` in a
   committed `tools/js/package.json` + `package-lock.json`), used by `tools/check.sh` when `--files` contains `.js` files: `eslint`
   (flat config `tools/js/eslint.config.js`: recommended + `import/no-cycle`, 0 errors / 0 warnings) and `node --test lab/static/tests`.
   No npm install on the host; nothing under `lab/static` is served that was not served before (tests live in `lab/static/tests/` but
   the static mount must not expose them: check `_RevalidatingStaticFiles` or move the tests to `RnD/tests/js/`; Opus prefers
   `RnD/tests/js/`, importing the page modules by relative path).
2. **Shared modules.** `selection` (used by overlay and worldmap) and `autofill` (used by reviews) become `js/util/selection.js` and
   `js/util/autofill.js`; today's `util.js` becomes `js/util/index.js` (or stays `js/util.js` with the two as siblings under `js/util/`;
   the BOUNDARIES rule treats `util` as a top-level module or directory). `eta.js` becomes `js/util/eta.js` (pure, used by runs).
3. **No behaviour change.** DOM ids, CSS classes, `window.__labAudio` / `__labWorldmap` / `__labAudioLog`, HTTP calls and their order
   stay. The staging E2E (96 tests) is the behaviour guard; node tests pin the pure functions.
4. **Hooks become bus events only where a feature would otherwise import another feature** (today's `reviews` hook object and the
   cross-feature calls from `app.js`); everything else keeps direct calls inside its feature.

## Order
p6-01 tooling (Opus reviews; no tests-first) → p6-02 node tests of the pure functions as they are today (red only where the spec moves
them; tests worker) → p6-03 shared util dir + move the existing `js/*.js` feature modules into `js/features/<name>/` (paths only) →
p6-04 split `app.js` into `app/` + features (library, settings, collisions, runs, transport) → p6-05 eslint 0/0 + no-cycle and the
JS boundary test green with the final layout.
