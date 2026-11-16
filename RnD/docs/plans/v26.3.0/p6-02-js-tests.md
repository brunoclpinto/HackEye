# p6-02 node tests of the pure front-end functions (tests worker)

Write `tests/js/*.test.mjs` (`node:test` + `node:assert/strict`) for the pure functions of audit 8.2, importing them from their
**final** paths (red until p6-03 / p6-04 move them), with literals printed by running the **current** modules in the js-check image:
- `util` (`parseTime`, `fmtTime`, `clamp`, `lastAtOrBefore`, `firstAtOrAfter`, `eventRole`, `eventColor`, `beepRepeats`) →
  `js/util/index.js`; `eta` → `js/util/eta.js`; `autofill` → `js/util/autofill.js`; `selection` (`worldTrackOf`, `itemTooltip`) →
  `js/util/selection.js`.
- `sounds` (`sliderToHz`, `hzToSlider`, `PITCH_STEPS`) → `js/features/sounds/sounds.js`; `worldmap` (`isMassive`, `itemLine`,
  `markerOf`, `itemsNear`, `footprintOf`, `footprintDistance`, `regionOf`, `trackOf`, `worldTrackLine`, `wallEdgeSegments`) →
  `js/features/worldmap/worldmap.js`; `overlay` (`fullBox`, `fullOutline`) → `js/features/overlay/overlay.js`; `audio`'s pure exports
  (`speechPriority`, `pronounce`, `canonSoundKind`, `rankVoice`, `chooseEnglishVoice`, `speechPlan`, `stuckHint`) →
  `js/features/audio/speech.js` (split from the DOM class in p6-03; tests import with a minimal `window`/`document`/`navigator` shim
  only if the split is not possible).
- The pure `app.js` functions of audit 8.2 (`windowKey`, `runDepth`, `runOrientation`, `runLabel`, `isActive`, `lsKey`, `shortVal`,
  `flatKeys`, `collTags`, `collText`, `collSummary(d, first)`) → `js/features/runs/runs.js` and `js/features/collisions/summary.js`
  (exported after p6-04).
- **Cross-language fixture:** `worldmap.js`'s private `clockQuarter` / `clockText` duplicate `engine.core.clock.clock_quarter` /
  `clock_text`: write `tests/fixtures/clock_cases.json` from the Python functions (bearings -180..180 step 7.5 plus edge cases) and a JS
  test that the JS functions (exported from `js/util/clock.js` after p6-03) match it.
Prove: every test passes against the current module through a temporary import map / copy outside the worktree, and is red today only
on missing paths / exports.
