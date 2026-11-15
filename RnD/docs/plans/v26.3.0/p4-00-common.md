# Phase 4 (pipeline): rules shared by every p4 spec

Read this after [README.md](README.md), [p2-00-common.md](p2-00-common.md) and [p3-00-common.md](p3-00-common.md). Phase 4 turns
`run_collision` (collision.py, about 880 lines; audit section 3) into `engine.pipeline`. The output must not change: the quick
equivalence check runs in every gate and the full one at the checkpoint. Characterisation tests here are mostly structural; the
equivalence corpus is the behaviour guard.

## Order of work (each task leaves `run_collision` working)
1. p4-01 glue + `LAST_WORLD_TRACKS_MS` → `engine/pipeline/glue.py`.
2. p4-02 `run_collision` moved **verbatim** → `engine/pipeline/run.py` (imports rewired, one sanctioned line). `collision.run_collision`
   is the same object.
3. p4-03 locals → state objects: a **mechanical rename** of the function's locals to attributes of `RunState` (built once) and
   `FrameState` (rebuilt per frame). No statement moves, no reordering.
4. p4-04 / p4-05 cut the converted body into stage functions `(s: RunState, f: FrameState) -> None`, registered in audit-3.2 order.
   Pure cut and paste: every statement keeps its relative order.
5. p4-06 `Pipeline` + explicit stats; `collision.py` is re-exports only.
6. p4-07 field-ownership guard.

## Decisions (Opus, 2026-11-15)
- **No facade wrapper for `run_collision`** (plan decision 5, option b): the engine function resolves the worldmap config itself
  through the hook, so `collision.run_collision is engine.pipeline.run.run_collision`. Lab tests monkeypatch the attribute
  `collision.run_collision`, and the Lab keeps calling it through the module, so the patch still works.
- **The conftest stays unchanged.** `run_collision` never calls `collision.load_config` (checked 2026-11-15: its only loader use is
  `worldmap.load_config()`), so the caller-name logic is untouched. The plan's "Phase 4 replaces the conftest patch" is dropped; noted in
  the plan's changes during execution.
- **Ownership is a static guard** (p4-07): a declared table of allowed writer models per field, checked by an AST scan. The debug-mode
  `__setattr__` guard of the plan is dropped (a runtime hook on the hottest objects, and `replace()` bypasses it anyway).

## Allowed edits in p4-02 … p4-05
Only what the task spec lists. Never reorder statements, never merge or split an expression, never "centralise" a repeated default
(audit 5.7), never iterate a set (audit 5.2). Loop-carried locals (audit 5.1) become `RunState` attributes; per-frame locals become
`FrameState` attributes, reset at the top of every frame exactly where today's code first assigns them.
