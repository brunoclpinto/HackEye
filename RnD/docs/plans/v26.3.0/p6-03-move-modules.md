# p6-03 shared util dir + feature dirs (paths and exports only)

- `js/util.js` → `js/util/index.js`; `js/eta.js`, `js/autofill.js`, `js/selection.js` → `js/util/`; new `js/util/clock.js` exports
  `clockQuarter` / `clockText` (moved out of `worldmap.js`, which imports them).
- `js/<feature>.js` → `js/features/<feature>/<feature>.js` for audio, classes, hazards, issues, notes, overlay, reviews, sounds,
  timeline, worldmap; `audio.js`'s pure exports move to `js/features/audio/speech.js` (the engine class imports them).
- `js/api.js` stays. Update every import path (and `app.js`'s); export the functions p6-02's tests import. No other edits.
- Gate: eslint on the moved files (no new findings vs p6-01's count), node tests, the JS boundary test, and the staging E2E
  (`tools/staging.sh up|seed|e2e|down|clean`) 96/96.

## Opus notes (2026-11-16, after the worker)
- **Edits beyond paths:**
  - `util/clock.js` holds `clockQuarter` / `clockText`, which `worldmap.js` imports.
  - `features/audio/speech.js` holds the pure speech exports, moved verbatim. It also exports the guarded `ANDROID`, which `audio.js` imports for its own two uses, so there is only one copy. Nothing imported those names from `audio.js`.
  - The E2E import URLs in `test_eta.py`, `test_lab.py` and `test_worldmap.py` were updated.
  - `smoke.test.mjs` (p6-01, not a p6-02 locked test) now imports `util/index.js`.
- **Results:**
  - eslint over `lab/static`: still only the 2 known `no-unused-vars` in `features/classes/classes.js`, and 0 `import/no-cycle`;
  - node tests 55/57: only `runs` and `summary` are red, and those are p6-04's;
  - boundary test green;
  - staging E2E 96/96.
- **Docs:** the doc references to the old `js/*.js` paths (`lab/CONTRACTS.md`) are rewritten in Phase 7 (CONTRACTS becomes an index of the model READMEs). `DECISIONS.md` is history and is left as is.
