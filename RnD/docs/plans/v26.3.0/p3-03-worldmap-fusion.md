# p3-03 engine.worldmap.fusion

## Moves (worldmap.py → engine/worldmap/fusion.py)
`Fusion` (whole class). Named renames per p3-00 (`groundfuse.ground_point` at the bottom-distance line → `groundgeom.ground_point`).

## Risks
- The lazy vote decay (`decay: "time"`, votes pre-multiplied by `exp(lambda t)`) and `poseAlign` search: float order, move verbatim.
- Pinned by 6 uses in 3 files.

## Tests (Sonnet): `tests/engine/worldmap/test_fusion.py`
- Identity; attribute list.
- A 10-frame `update` / `snapshot` sequence from a fixture run (Observer from the facade, as `tests/test_worldmap.py` does), once with
  `decay "none"` and once with `decay "time"` + `poseAlign true`: pin per-step digests of the snapshot (class counts, `UNKNOWN` count,
  the chosen pose offset).
- `close_gaps` and `surface_at` on the final state.
