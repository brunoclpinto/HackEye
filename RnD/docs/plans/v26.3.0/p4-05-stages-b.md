# p4-05 engine.pipeline.stages, part B (stages 13-24 + epilogue)

## What changes
Stage functions 13-24 of audit 3.2 (`motion_roles`, `tracking_jump_final`, `speech_passing`, `tracking_confirm`, `worldmap_keeps`,
`tracking_unseen`, `memory`, `worldtracks`, `egostate_pathchange`, `speech`, `sounds_beeps`, `output_frame`) appended to `STAGES`, and
`finish(s) -> tuple[dict, dict]` (the epilogue after the loop: tone events, `events.sort`, `hazards_doc`, `LAST_WORLD_TRACKS_MS[:] =`).
`run_collision` becomes: `s = setup(...)`; for each frame: preamble, `for st in STAGES: st.fn(s, f)`; `return finish(s)`.

The blocked state machine (`blk_*`) and the inline motion block inside stage 13 stay inside their stage, verbatim (audit 3.2 notes).

## Tests (Sonnet): extend `tests/engine/pipeline/test_stages.py` in a new file `test_stages_b.py`
- `[st.name for st in STAGES]` is the full 24-name list in order.
- The body of `run_collision` contains no statements except the setup call, the frame loop with the preamble and the stage loop, and
  the `finish` return (AST check).
