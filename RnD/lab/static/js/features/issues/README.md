# features/issues

The Open issues panel.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 9.5 Open issues panel  (`js/features/issues/issues.js`, `lab/features/issues.py`, catalogue `lab/issues.json`; v26.2.4 follow-up)

A collapsible **Open issues (N open)** section at the very top of `#reviewPanel`, above Notes, where the user closes and comments on the known issues, like reviews.
- **Catalogue:** `lab/issues.json` in the repo, maintained by Claude together with `docs/plans/v26.2.md` (same ids and groups: `open` O1…, `decision` 5–9, `debt` 10–14, `hold` 15–17, `closed`). Items: `{id, group, title, details: [lines], refs?, status?, closedAt?, reason?}`. Read on every request, so catalogue edits show without a restart.
- **User state:** `LAB_DIR/issues-state.json` `{id: {status, closedAt, note, noteUpdatedAt}}`, outside the version wipe. The status is the user's when set, else the catalogue's (default open). Closed items are listed in the **Closed** group (collapsed by default) and keep their `group` of origin.
- **Rows:** id badge, title, **Close** / **Reopen** toggle (optimistic, serial write queue, toast + reload on failure). A click on the title expands the details (`backticks` as code), refs, the reason / origin of closed items, and a note that autosaves 600 ms after the last keystroke and on blur ("saved ✓"), as the review notes. Open/closed sections are remembered in localStorage; the panel re-reads on focus when no note is being edited.
- **Export:** `issues` in the reviews export lists every item the user touched (closed, reopened or commented) with its catalogue text. Claude acts on it: a closed issue moves to "Closed" in `plans/v26.2.md` and `issues.json` (date, the user's comment as reason); a comment on an open issue is a decision or request. New known issues of a shipped version are added to `issues.json`.
