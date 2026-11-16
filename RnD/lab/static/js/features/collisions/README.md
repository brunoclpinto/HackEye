# features/collisions

Collision runs of the open run: the re-run job (start, follow, resume, cancel), the rows inside each run group, selection, labels,
delete, and the A/B compare. `summary.js` holds the pure row helpers (`lsKey`, `shortVal`, `flatKeys`, `collTags`, `collSummary(d, first)`,
`collText(d, first)`); `first` is `S.colls[0]`, passed by the caller.

Exports: `wire`, `rerunCollision` (also used by the sounds panel through `app/bootstrap.js`).

**Bus handled:** `refresh-collisions`, `pick-collision`, `render-coll`, `render-compare`, `reset-compare-defaults`, `load-run-colls`,
`colls-of`, `coll-row`, `resume-collision-job`.
**Bus emitted:** `put-settings`, `all-overrides`, `render-runs`, `load-run-data`, `apply-run-meta`, `load-run`, `seek`.
**DOM wiring:** `#rerunBtn`, `#secCompare`, `#cmpA`, `#cmpB`.
**State read/written:** `S.colls`, `S.cid`, `S.run`, `S.rec`, `S.runColls`, `S.events`, `S.collFollow`; `hazards`, `video`; `localStorage` key `lab.collision.<runId>`.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 9 Frontend — collision runs and compare

- **Collision runs (v26.2.8, §5.1; rows of the run's group since v26.2.10):** the rows list the run's collision runs (summary = the settings and overrides that differ from the first one, short, e.g. `objDist ground+depth · horizon off · itemLens off`; the first says `first`; the Compare selects show `c<n> · <label or summary> · HH:MM`). Selecting one reloads every collision-dependent panel (events, speech, beeps, timeline, hazards overlay, world map, reviews, notifications) through the path a re-run takes (`loadRunData(run, cid)`); the run object the panels get carries `collisionId` and that collision run's `collisionVersion`, and every collision URL carries `collision=<cid>`. The choice is kept per run in `localStorage` `lab.collision.<runId>` (falls back to the latest). The row label saves on change (PATCH); Delete asks for confirmation and shows the 409 message when refused. A run with no collision run shows only the badge and empty panels.
- **Compare section `#secCompare`** (in `#main`, above the timeline; collapsed by default): selects A `#cmpA` and B `#cmpB` (defaults: B = the selected collision run, A = the one before it), then the settings table `#cmpSettings` (key, A, B; rows `data-key`), the counts, the lists changed `#cmpChanged`, only A `#cmpOnlyA`, only B `#cmpOnlyB` and `#cmpSame` ("N the same"); every list row shows time, type and text and seeks the video on click. Tables scroll inside their own wrapper (no horizontal page scroll at 390 px).
