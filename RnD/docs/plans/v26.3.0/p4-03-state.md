# p4-03 engine.pipeline.state (locals → RunState / FrameState)

## What changes (engine/pipeline/run.py + new engine/pipeline/state.py)
`state.py` defines two plain classes (no `__slots__`, no `__init__` logic beyond `pass`-like defaults): `RunState` and `FrameState`.
Use `@dataclass` with every field defaulting to `None` (or a fresh list / dict via `field(default_factory=...)` where today's code
initialises one), in the order of first assignment in `run_collision`.

In `run_collision`, rename **every local variable** of the function body to `s.<name>` (run-level: assigned in setup or carried across
frames) or `f.<name>` (assigned inside the frame loop and not read before its first assignment in the same frame). Classification
rule: a name assigned inside the loop and read in a later frame before being reassigned is run-level (audit 5.1 lists them: `prev_t`,
`beep_run`, `last_hard_pan_t`, `prev_heading`, `held_speed`, `held_t`, `ego_hist`, `ego_hist_t0`, `h_state`, `raws`, `prev_left`,
`prev_right`, `prev_group`, `last_estimate_t`, `first_t`, `meas_hist`, `follow`, `blk_*`, `dscale`, `gait_check`, `anchor`, ...).
`s = RunState()` is created at the top; `f = FrameState()` at the top of each frame iteration.

Not renamed:
- comprehension and generator variables, and the loop variables of inner `for` loops (`it`, `tr`, `tid`, `g`, ...) **unless** the
  name is read after its loop ends (audit 5.1: `tr` leaks; find every such read and make that name `f.` if it is read after the loop);
- lambda parameters;
- the function parameters (`grids`, `times`, `config`, ...): they become `s.<param>` with one assignment block right after
  `s = RunState()`, in signature order. The parameters themselves stay in the signature.

No statement moves, no expression changes. Report the full classification table (name, s/f, first assignment line, reason) in the
README `engine/pipeline/README.md`.

## Risks
- A name wrongly classified as per-frame that is read in the next frame before reassignment: today it keeps the old value; on `f.` it
  would be `None`. The equivalence check catches most; the classification rule above prevents it.
- Names assigned in only one branch (`c_source`, `level`, `ds`, ...; audit 5.1): keep the same branch structure; reading an unset `f.`
  attribute gives `None` where today it would raise `UnboundLocalError` (never happens today, so no output change).
- Performance: attribute access in the hot loop costs a little; acceptable.

## Tests (Sonnet): `tests/engine/pipeline/test_state.py`
- `RunState` / `FrameState` are dataclasses whose fields all default to None or a fresh empty container (two instances never share a
  list / dict).
- AST check of `run.run_collision`: inside the function there is no `ast.Name` in Store context except `s`, `f`, comprehension /
  inner-loop variables, lambda parameters and `with`/`except` targets (allow-list them explicitly: the tests worker computes the list
  from the legacy function and pins it). This is the test that fails red today.
- `run_collision` still returns `(hazards_doc, events_doc)` for one fixture window (a smoke test; equivalence covers the values).

## Note (Opus, 2026-11-15, from the tests worker)
- The setup local `f = focal_px(gw, hfov)` clashes with the `FrameState` variable `f`: it becomes the run-level attribute `s.f`
  (field name `f` on `RunState`), every read of the focal length becomes `s.f`.
- `tid`, `tr` and `k` are also plain locals read outside a loop that binds them (`k = scale.value` is the frame-start scale,
  audit 5.1): they become `f.tid` / `f.tr` / `f.k` where so assigned; their for/comprehension uses stay bare.
- The frame-loop variable `i` stays bare (the loop starts before `f` exists).
