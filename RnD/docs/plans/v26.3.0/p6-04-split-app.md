# p6-04 app.js → app/ + features

Audit 8.1 table: `app.js` sections → `js/app/state.js` (`S`, `video`, shared singletons registry), `js/app/bus.js` (a tiny event bus:
`on(name, fn)`, `emit(name, ...args)`), `js/app/bootstrap.js` (instance wiring, `init()`, calls each feature's `wire()` in today's order),
and `js/features/{library,settings,collisions,runs,transport}/`. `app.js` stays the page entry (`index.html` unchanged) and only imports
`app/bootstrap.js`. Cross-feature calls (today: closures in `app.js`, the `reviews` hook object) become bus events
(`seek`, `load-run`, `audio-events-changed`, ...) or calls through `state`; list each in the feature READMEs. Function bodies
verbatim except `S.` / singleton access through `state`. Export the pure functions p6-02 pinned.
- Gate: eslint (no new findings), node tests green, JS boundary test green, staging E2E 96/96.
