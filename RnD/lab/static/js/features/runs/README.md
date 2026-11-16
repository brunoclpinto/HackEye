# features/runs

The run list, analysis start / follow / cancel, loading a run into every panel (`loadRun`, `loadRunData`, `unloadRun`), the run badge,
window and depth helpers, and `refreshAudioEvents`. Pure exports: `windowKey`, `runDepth`, `runOrientation`, `runLabel`, `isActive`.

Exports: `wire`, `loadRun`, `labelResolutions`, `DEPTH_LABELS` (used by `app/bootstrap.js`) and the pure helpers above.

**Bus handled:** `load-runs`, `watch-active-run`, `set-busy`, `unload-run`, `label-resolutions`, `render-runs`, `load-run`, `load-run-data`,
`apply-run-meta`, `audio-events-changed`.
**Bus emitted:** `put-settings`, `colls-of`, `coll-row`, `load-run-colls`, `refresh-recordings`, `select-recording`, `refresh-collisions`,
`pick-collision`, `render-coll`, `render-compare`, `reset-compare-defaults`, `resume-collision-job`, `seek`, `write-hash`.
**DOM wiring:** `#orientSel` / `#sideSel` (window change), `#distSel`, `#analyseBtn`, `#reanalyseBtn`, `#cancelBtn`.
**State read/written:** `S.runs`, `S.run`, `S.runColls`, `S.openRuns`, `S.eta`, `S.runPoll`, `S.events`, `S.speech`, `S.tones`, `S.notes`, `S.cid`,
`S.colls`, `S.rec`, `S.seekGen`, `S.pendingSeek`, `S.rangeTouched`; every panel instance (overlay, hazards, classesPanel, worldmap, audio, timeline, reviews, sounds, selection).
