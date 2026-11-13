# p2-09 engine.groundfuse (model: stateful estimators)

## Moves (groundfuse.py → engine/groundfuse/estimators.py)
`HorizonSigma`, `Corrector`, `_wmedian` (`wmedian`).
- After this task `groundfuse.py` contains only re-exports, from engine.core.groundgeom, engine.core.distfuse and engine.groundfuse.

## Risks
- `Corrector` keeps EMA/log state, and its update signature (`update(t, region_mask, dmap, sc_total, horizon, sig_rows, extra=walls)`) is pinned by 2 tests and by `test_worldmap_v2627`.

## Tests (Sonnet): `tests/engine/groundfuse/test_estimators.py`
- Identity.
- Attribute lists.
- `HorizonSigma` sequence.
- `Corrector.update` over 30 frames of a depth fixture: pin the curve/rep per frame (compact digests).
- `wmedian` cases.
