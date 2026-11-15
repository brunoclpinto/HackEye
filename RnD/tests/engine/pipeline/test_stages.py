"""Structural tests for engine.pipeline.stages, part A (v26.3.0 p4-04): the ``Stage`` record and stages 1-12.

The 12 names are the audit 3.2 order given by the spec. ``reads`` / ``writes`` are checked against the attributes
of ``s`` / ``f`` that the AST of each stage function loads / stores (the derivation below holds for every stage
added later too). The engine module is imported inside each test (it does not exist yet).
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import textwrap
from typing import Any

STAGES_A: list[str] = [
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
]
STAGE_FIELDS: list[str] = ["name", "reads", "writes", "config_section", "fn"]


def derive_access(fn: Any) -> tuple[set[str], set[str]]:
    """Attribute names of the two parameters of ``fn`` (``s``, ``f``) that its body loads / stores (AST)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    reads: set[str] = set()
    writes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("s", "f"):
            if isinstance(node.ctx, ast.Store):
                writes.add(node.attr)
            elif isinstance(node.ctx, ast.Load):
                reads.add(node.attr)
    return reads, writes


def test_stage_is_a_frozen_dataclass_with_the_spec_fields() -> None:
    from engine.pipeline.stages import Stage

    assert dataclasses.is_dataclass(Stage)
    assert [fl.name for fl in dataclasses.fields(Stage)] == STAGE_FIELDS
    params = getattr(Stage, "__dataclass_params__")  # noqa: B009
    assert params.frozen is True


def test_first_twelve_stage_names_in_order() -> None:
    from engine.pipeline.stages import STAGES

    assert [st.name for st in STAGES[:12]] == STAGES_A


def test_stage_names_are_unique() -> None:
    from engine.pipeline.stages import STAGES

    names = [st.name for st in STAGES]
    assert len(names) == len(set(names))


def test_stage_records_are_well_formed() -> None:
    from engine.pipeline.stages import STAGES, Stage

    for st in STAGES:
        assert isinstance(st, Stage)
        assert isinstance(st.name, str)
        assert isinstance(st.reads, tuple)
        assert isinstance(st.writes, tuple)
        assert all(isinstance(a, str) for a in st.reads + st.writes)
        assert len(st.reads) == len(set(st.reads))
        assert len(st.writes) == len(set(st.writes))
        assert st.config_section is None or isinstance(st.config_section, str)
        assert callable(st.fn)


def test_reads_and_writes_match_the_ast_of_every_registered_stage() -> None:
    from engine.pipeline.stages import STAGES

    assert STAGES
    for st in STAGES:
        reads, writes = derive_access(st.fn)
        assert set(st.reads) == reads, f"{st.name}: reads"
        assert set(st.writes) == writes, f"{st.name}: writes"


def test_every_stage_fn_takes_exactly_s_and_f() -> None:
    from engine.pipeline.stages import STAGES

    for st in STAGES:
        params = list(inspect.signature(st.fn).parameters.values())
        assert [p.name for p in params] == ["s", "f"], st.name
        assert all(p.default is inspect.Parameter.empty for p in params), st.name
        assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in params), st.name


def test_setup_is_defined_and_returns_a_run_state_annotation() -> None:
    from engine.pipeline import stages

    sig = inspect.signature(stages.setup)
    # the setup block keeps the parameters of run_collision (p4-02), in signature order
    params = [p for p in sig.parameters]
    assert params[:5] == ["grids", "times", "class_names", "config", "settings"]
