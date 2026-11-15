"""Structural tests for engine.pipeline.stages, part B (v26.3.0 p4-05): stages 13-24, ``finish``, ``run_collision``.

The 24 names are the audit 3.2 order given by the spec. The AST check pins the shape ``run_collision`` must have
once the stages are cut out: the setup call, the frame loop (preamble + stage loop) and the ``finish`` return. The
engine modules are imported inside each test (they do not exist yet).
"""

from __future__ import annotations

import ast
import inspect
import textwrap

STAGES_ALL: list[str] = [
    "surface_region",
    "surface_horizon",
    "egosignals_lookup",
    "surface_crosswalk",
    "detection",
    "tracking",
    "depthscale",
    "tracking_jump",
    "egostate",
    "depthscale_report",
    "worldmap_step",
    "tracking_coast",
    "motion_roles",
    "tracking_jump_final",
    "speech_passing",
    "tracking_confirm",
    "worldmap_keeps",
    "tracking_unseen",
    "memory",
    "worldtracks",
    "egostate_pathchange",
    "speech",
    "sounds_beeps",
    "output_frame",
]
PREAMBLE_STORES: set[str] = {"f", "t", "dt"}


def _run_collision_func() -> ast.FunctionDef:
    from engine.pipeline import run

    tree = ast.parse(textwrap.dedent(inspect.getsource(run.run_collision)))
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    return fn


def _body_without_docstring(fn: ast.FunctionDef) -> list[ast.stmt]:
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr):
        first = body[0].value
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            body = body[1:]
    return body


def _called_name(call: ast.expr) -> str | None:
    if isinstance(call, ast.Call):
        if isinstance(call.func, ast.Name):
            return call.func.id
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
    return None


def test_all_twenty_four_stage_names_in_order() -> None:
    from engine.pipeline.stages import STAGES

    assert [st.name for st in STAGES] == STAGES_ALL


def test_finish_takes_only_the_run_state() -> None:
    from engine.pipeline import stages

    params = list(inspect.signature(stages.finish).parameters)
    assert params == ["s"]


def test_run_collision_body_is_setup_frame_loop_finish() -> None:
    body = _body_without_docstring(_run_collision_func())
    assert len(body) == 3
    setup, loop, ret = body
    # s = setup(...)
    assert isinstance(setup, ast.Assign)
    assert [t.id for t in setup.targets if isinstance(t, ast.Name)] == ["s"]
    assert _called_name(setup.value) == "setup"
    # for ...: <preamble>; for st in STAGES: st.fn(s, f)
    assert isinstance(loop, ast.For)
    # return finish(s)
    assert isinstance(ret, ast.Return)
    assert ret.value is not None
    assert _called_name(ret.value) == "finish"
    assert isinstance(ret.value, ast.Call)
    assert [a.id for a in ret.value.args if isinstance(a, ast.Name)] == ["s"]
    assert len(ret.value.args) == 1
    assert ret.value.keywords == []


def test_frame_loop_is_preamble_then_the_stage_loop() -> None:
    body = _body_without_docstring(_run_collision_func())
    loop = body[1]
    assert isinstance(loop, ast.For)
    assert loop.orelse == []
    *preamble, stage_loop = loop.body
    # the stage loop: for st in STAGES: st.fn(s, f)
    assert isinstance(stage_loop, ast.For)
    assert isinstance(stage_loop.target, ast.Name)
    assert isinstance(stage_loop.iter, ast.Name) and stage_loop.iter.id == "STAGES"
    assert len(stage_loop.body) == 1
    call = stage_loop.body[0]
    assert isinstance(call, ast.Expr) and isinstance(call.value, ast.Call)
    func = call.value.func
    assert isinstance(func, ast.Attribute) and func.attr == "fn"
    assert isinstance(func.value, ast.Name) and func.value.id == stage_loop.target.id
    assert [a.id for a in call.value.args if isinstance(a, ast.Name)] == ["s", "f"]
    assert len(call.value.args) == 2
    # the preamble builds the per-frame state and nothing else of substance
    assert preamble
    assigned_f = [
        st
        for st in preamble
        if isinstance(st, ast.Assign)
        and [t.id for t in st.targets if isinstance(t, ast.Name)] == ["f"]
        and _called_name(st.value) == "FrameState"
    ]
    assert len(assigned_f) == 1
    for st in preamble:
        assert isinstance(st, (ast.Assign, ast.If, ast.Expr))
        for node in ast.walk(st):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                assert node.id in PREAMBLE_STORES, node.id
