# p6-04 app.js → app/ + features

Audit 8.1 table: `app.js` sections → `js/app/state.js` (`S`, `video`, shared singletons registry), `js/app/bus.js` (a tiny event bus:
`on(name, fn)`, `emit(name, ...args)`), `js/app/bootstrap.js` (instance wiring, `init()`, calls each feature's `wire()` in today's order),
and `js/features/{library,settings,collisions,runs,transport}/`. `app.js` stays the page entry (`index.html` unchanged) and only imports
`app/bootstrap.js`. Cross-feature calls (today: closures in `app.js`, the `reviews` hook object) become bus events
(`seek`, `load-run`, `audio-events-changed`, ...) or calls through `state`; list each in the feature READMEs. Function bodies
verbatim except `S.` / singleton access through `state`. Export the pure functions p6-02 pinned.
- Gate: eslint (no new findings), node tests green, JS boundary test green, staging E2E 96/96.

## Opus notes (2026-11-16, after the worker)
- **Layout:**
  - `state.js` and `bus.js` sit at the js root, not under `app/`. The boundary rule takes the first path segment (`state`, `bus`).
  - The instances are live-binding exports of `state.js`, registered once by `app/bootstrap.js`.
  - `setProgress` / `markDefault` → `util/ui.js`.
- **Bus semantics:** `emit` returns the first handler's return value, so former cross-feature calls keep their awaits and results. The event table is in `js/README.md`.
- **Opus review:**
  - Each of the 76 functions of the old `app.js` was compared with its new copy, whitespace-normalised. 57 are identical. The other 19 differ only by:
    - cross-feature call → `emit("…")`;
    - the `first` parameter of `collSummary` / `collText` (callers pass `S.colls[0]`);
    - `export`;
    - the `wire()` split.
  - The listeners, grouped by target, are registered in the same order and number as before.
  - New guard `tests/js/bus_events.test.mjs` (Opus): a static scan that every emitted event has an `on()` handler and every handler is emitted. A misspelled event name would otherwise fail silently.
- **Results:**
  - eslint: only the 2 known `classes.js` findings;
  - node tests 67/67;
  - boundary test green;
  - staging E2E 96/96.
