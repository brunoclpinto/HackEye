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
