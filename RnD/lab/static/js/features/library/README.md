# features/library

The recordings list, proxy build, video attach, recording selection and the URL hash (`#rec=..&run=..&t=..`).

Exports: `wire`, `readHash`, `refreshRecordings`, `selectRecording` (used by `app/bootstrap.js`).

**Bus handled:** `write-hash`, `refresh-recordings`, `select-recording`.
**Bus emitted:** `set-busy`, `unload-run`, `label-resolutions`, `load-settings`, `load-runs`, `watch-active-run`, `sync-default-range`.
**State read/written:** `S.recs`, `S.rec`, `S.run`, `S.pendingSeek`, `S.loadedVideoRec`, `S.rangeTouched`, `S.recPoll`, `S.runPoll`; `video`, `notesPanel`, `reviews`.
