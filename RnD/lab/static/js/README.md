# lab/static/js -- layout of the Lab front end

`index.html` loads `/static/app.js`, which only imports `js/app/bootstrap.js`. Imports are enforced by
`src/engine/BOUNDARIES.toml [js]` (`tests/test_module_boundaries.py`) and `import/no-cycle` (eslint, `tools/js/eslint.config.js`).

| path | role |
|---|---|
| `app/bootstrap.js` | builds the panels, calls `register()` (state), wires every feature in a fixed order, runs `init()`. The only file that imports features. |
| `state.js` | `S` (page record), `video`, the singleton instances (live bindings set by `register()`), `recById`, `durOf`, `isNarrow`. |
| `bus.js` | `on(name, fn)`, `emit(name, ...args)`: synchronous; `emit` returns the first handler's return value. |
| `api.js` | fetch wrapper (errors become toasts). |
| `util/` | shared, pure or DOM-helper modules: `index.js`, `clock.js`, `eta.js`, `autofill.js`, `selection.js`, `ui.js` (`setProgress`, `markDefault`). |
| `features/<name>/` | one directory per feature; imports only `util`, `api`, `state`, `bus` and its own files. |

state.js and bus.js sit at the js root (not under `app/`) because the boundary test names them `state` / `bus` by their first path segment.

Features: `library`, `settings`, `collisions` (+ `summary.js`), `runs`, `transport` (wired from `app.js` pieces), and the panel classes
`overlay`, `audio` (+ `speech.js`), `timeline`, `reviews`, `hazards`, `classes`, `sounds`, `notes`, `issues`, `worldmap`
(constructed in `bootstrap.js`, driven through state and callbacks, not through the bus).

## Wiring order (bootstrap `init()`)
`wireLibrary` (bus handlers only), `wireTransport`, `wireSettings`, `wireRuns`, `wireCollisions`. Settings must wire before runs:
both listen on `#sideSel` (geometry hint first, then the window change), as in the old `wire()`.

## Bus events
Name: handler (feature) <- emitters. Arguments in parentheses.

| event | handler | emitted by |
|---|---|---|
| `seek` (t) | transport `seekTo` | collisions (compare list), runs (`loadRun`), bootstrap (timeline, reviews hooks) |
| `sync-default-range` | transport | library |
| `write-hash` | library `writeHash` | transport (pause, seeked, 1 s timer), runs |
| `refresh-recordings` | library | runs |
| `select-recording` (id, {keepRun}) | library | runs |
| `load-settings` | settings | library |
| `put-settings` | settings (async) | collisions, runs |
| `all-overrides` | settings (returns object, undefined or null) | collisions |
| `load-runs` | runs | library |
| `watch-active-run` | runs | library |
| `set-busy` (run, label) | runs | library |
| `unload-run` | runs | library |
| `label-resolutions` | runs | library, settings |
| `render-runs` | runs | collisions |
| `load-run` (runId, {seek, t}) | runs `loadRun` | collisions, bootstrap (reviews `ensureRun`) |
| `load-run-data` (run, cid) | runs (returns the run) | collisions |
| `apply-run-meta` | runs | collisions |
| `audio-events-changed` | runs `refreshAudioEvents` | transport (`#reviewPreviewChk`), bootstrap (reviews `changed`) |
| `refresh-collisions` | collisions (async) | runs |
| `pick-collision` (runId) | collisions (returns cid) | runs |
| `render-coll`, `render-compare`, `reset-compare-defaults`, `resume-collision-job` | collisions | runs |
| `load-run-colls` (runId) | collisions | runs |
| `colls-of` (runId) | collisions (returns the list) | runs |
| `coll-row` (runId, d) | collisions (returns the `<li>`) | runs |
