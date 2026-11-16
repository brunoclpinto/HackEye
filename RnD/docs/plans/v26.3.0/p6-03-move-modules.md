# p6-03 shared util dir + feature dirs (paths and exports only)

- `js/util.js` → `js/util/index.js`; `js/eta.js`, `js/autofill.js`, `js/selection.js` → `js/util/`; new `js/util/clock.js` exports
  `clockQuarter` / `clockText` (moved out of `worldmap.js`, which imports them).
- `js/<feature>.js` → `js/features/<feature>/<feature>.js` for audio, classes, hazards, issues, notes, overlay, reviews, sounds,
  timeline, worldmap; `audio.js`'s pure exports move to `js/features/audio/speech.js` (the engine class imports them).
- `js/api.js` stays. Update every import path (and `app.js`'s); export the functions p6-02's tests import. No other edits.
- Gate: eslint on the moved files (no new findings vs p6-01's count), node tests, the JS boundary test, and the staging E2E
  (`tools/staging.sh up|seed|e2e|down|clean`) 96/96.
