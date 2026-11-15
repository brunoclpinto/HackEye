# p4-06 Pipeline class, explicit stats, facade-only collision.py

## What changes
- `engine/pipeline/pipeline.py`: `class Pipeline` with `__init__(self, stages: list[Stage] = STAGES)` and
  `run(self, grids, times, class_names, config, settings, **kw) -> tuple[dict, dict]` (same keywords as `run_collision`), and
  `self.stats: PipelineStats` (`world_tracks_ms: list[float]`, `map_ms: list[float]`: the timings that today go to
  `wtracks.ms` / `smap.ms` and the dead `map_ms` list). `run_collision(...)` becomes `Pipeline().run(...)` (same signature), and still
  fills `LAST_WORLD_TRACKS_MS[:]` from `stats.world_tracks_ms` for the tools.
- `collision.py` keeps its module docstring and re-exports only: no `def`, no `class`, no assignment except re-export aliases. A
  test checks it (below). Names defined there today that are still used (e.g. `_side_of_clock`, dead per audit 5.8) move to their
  model or are deleted only if no test or tool reads them (grep first; report each).

## Tests (Sonnet): `tests/engine/pipeline/test_pipeline.py`
- `Pipeline().run(...)` on a fixture window equals `collision.run_collision(...)` (hazards and events, ms/version excluded).
- `Pipeline(STAGES).stats.world_tracks_ms` has one entry per frame where world tracks ran, and `collision.LAST_WORLD_TRACKS_MS` equals it
  after a run.
- AST of `src/collision.py`: only the docstring, `from __future__`, imports (with or without alias) and `__all__`, if present.

## Note (Opus, 2026-11-15)
p4-02 put a file-level `# mypy: ignore-errors` on `engine/pipeline/run.py` (the verbatim body has ~60 strict errors from
`None`-initialised locals). By the end of this task no `engine/pipeline/*.py` file may carry it: the state fields of p4-03 are typed
(`Any` where the legacy value is dynamic) and the stage functions are annotated.
