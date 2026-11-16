# features/reviews

Review notes and the auto-fill panel. Unchanged by p6-04 except how it is wired: its hook object is built in `app/bootstrap.js`.

**Bus emitted (from the hooks in bootstrap):** `seek` (`seek`), `load-run` (`ensureRun`), `audio-events-changed` (`changed`).
**Reads through hooks:** `S.run`, `S.runs`, `S.config.speech.templates`, `hazards.frameAt`, `overlay.style`, video time/paused.
Panel calls made on it by other features go through `state.reviews` (`setRun`, `setRecording`, `setRoles`, `highlight`, `playheadChanged`, `isRemoved`, `addedEvents`, `silencedBeeps`, `addedTones`).
