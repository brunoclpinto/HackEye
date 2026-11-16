# features/notes

The Notes panel.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 9.4 Notes panel  (`js/features/notes/notes.js`, `lab/features/notes.py`; v26.2.4 follow-up)

A collapsible **Notes** section at the top of `#reviewPanel` (open by default; open/closed remembered in localStorage) where the user writes reviews, remarks and fix requests in free text. **One document for the whole Lab**, not per recording.
- **Box:** `#notesText`, a plain textarea (about 8 rows, vertically resizable). **⏱ Insert time** (`#notesStamp`) inserts `[<recId> @ m:ss.s · run <runId>] ` at the cursor (no run part without a loaded run; disabled without a recording).
- **Saving:** autosave 800 ms after the last keystroke and on blur (`PUT /api/notes` with `baseUpdatedAt`); status `#notesStatus` (`Saving…` / `Saved ✓ HH:MM` / `Not saved: …, retrying`). Failed saves retry with backoff (2, 4, 8 s, then every 15 s); an unsaved edit is mirrored to localStorage `hackeye.lab.notes.draft`; `beforeunload` warns only while a save is pending.
- **Conflict:** a 409 (the notes changed on another device or tab) shows a notice with **Load theirs** and **Keep mine** (`force`); nothing is overwritten without a click.
- **Sync:** on `visibilitychange` (visible) and window `focus`, with no unsaved edit, the box re-reads the server.
- **Storage:** `LAB_DIR/notes.json` (§2), outside the version wipe (§11); each save first copies the old file to `notes.prev.json`. The export (§10) carries the notes, so they are read with the reviews at the start of every Lab task. Claude never edits or clears them.
