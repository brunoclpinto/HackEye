# p4-04 engine.pipeline.stages, part A (setup + stages 1-12)

## What changes
New `engine/pipeline/stages.py` with:
```python
@dataclass(frozen=True)
class Stage:
    name: str
    reads: tuple[str, ...]      # FrameState / RunState attribute names read (documentation, checked by a test)
    writes: tuple[str, ...]
    config_section: str | None
    fn: Callable[[RunState, FrameState], None]
```
and `STAGES: list[Stage]`. In this task: `setup(...) -> RunState` (the setup block of audit 3.1, verbatim, ending where the frame loop
starts) and the stage functions 1-12 of audit 3.2 (`surface_region`, `surface_horizon`, `egosignals_lookup`, `surface_crosswalk`,
`detection`, `tracking`, `depthscale`, `tracking_jump`, `egostate`, `depthscale_report`, `worldmap_step`, `tracking_coast`), each the
verbatim block of the converted body (p4-03). `run_collision` calls `setup`, then per frame the per-frame preamble (`progress`, `t`,
`dt`, `f = FrameState()`), then the 12 stage functions in order, then the remaining inline body (stages 13-24), then the epilogue.

Stage boundaries are the line ranges of audit 3.2 (recompute them on the current file: name the first and last statement of each stage
in the README). A statement belongs to exactly one stage; nothing is reordered. `reads` / `writes` are filled from the AST of each stage
function (attribute names of `s` and `f` loaded / stored).

## Tests (Sonnet): `tests/engine/pipeline/test_stages.py`
- `[st.name for st in STAGES[:12]]` equals the 12 names above in order.
- For every registered stage, `reads` / `writes` equal the AST-derived sets of `s.`/`f.` attributes loaded / stored in `fn`
  (write the derivation in the test; it holds for every stage added later too).
- Every `Stage.fn` takes exactly `(s, f)`.
