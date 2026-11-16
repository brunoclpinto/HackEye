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

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 9 Frontend — page layout

**Layout (v26.2.0):** header (title, version badge from `/api/version`, run badge, the collision-run bar is gone since v26.2.10: collision runs are rows of their run's group in the Past runs list). Grid areas: `#viewer` (video stage + transport + seek bar on the left, `#secWorldmap` on the right; columns 16fr:9fr so the square map is as tall as the 16:9 video), `#sidebar` (Recordings, Analyse, Collision settings, Past runs), `#main` (Audio, Overlay, Sounds, Classes, the Compare section `#secCompare`, timeline, role chips), `#reviewPanel`.
- >= 1200 px: columns 320 px | 1fr | 380 px; row 1 = viewer over columns 1-2, row 2 = sidebar | main; the review panel in column 3 spans both rows (sticky, own scroll, full viewport height). 900-1199 px: viewer full width on top, then sidebar | main, the review panel below. < 900 px: one column: video, world map (square, up to 480 px), sidebar, main, review (the Recordings section collapses after selecting).
- No horizontal page scroll at 390 px: wide tables (Sounds: `.snd-scroll`) scroll inside their own wrapper. E2E: `test_worldmap.py` layout tests.
- State is kept in the URL hash `#rec=<id>&run=<runId>&t=<s>` and restored on load.
