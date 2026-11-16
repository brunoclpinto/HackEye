# features/library

The recordings list, proxy build, video attach, recording selection and the URL hash (`#rec=..&run=..&t=..`).

Exports: `wire`, `readHash`, `refreshRecordings`, `selectRecording` (used by `app/bootstrap.js`).

**Bus handled:** `write-hash`, `refresh-recordings`, `select-recording`.
**Bus emitted:** `set-busy`, `unload-run`, `label-resolutions`, `load-settings`, `load-runs`, `watch-active-run`, `sync-default-range`.
**State read/written:** `S.recs`, `S.rec`, `S.run`, `S.pendingSeek`, `S.loadedVideoRec`, `S.rangeTouched`, `S.recPoll`, `S.runPoll`; `video`, `notesPanel`, `reviews`.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 9 Frontend — library and proxy

**Library and proxy:** each recording shows duration, size, fps, chapter count and a proxy tag; "Build proxy" / "Retry build proxy" starts a build; the list polls every 2 s while a proxy builds. The video is attached once the proxy is ready.
