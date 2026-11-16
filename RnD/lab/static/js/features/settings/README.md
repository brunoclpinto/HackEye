# features/settings

The per-recording settings form (mount, body, lens, distance), its placeholders and the Config overrides (JSON text + dotted-key selects).

Exports: `wire`, `fillMountSelect`, `ovDefaults` (used by `app/bootstrap.js`).

**Bus handled:** `load-settings`, `put-settings`, `all-overrides`.
**Bus emitted:** `label-resolutions`.
**DOM wiring:** `#horizonSel`, `#mountSel`, `#locSel`, `#sideSel` (geometry hint), `#userHeightInput`.
**State read/written:** `S.config`, `S.rec`, `S.settings`, `S.run` (read, for the re-run hint).
