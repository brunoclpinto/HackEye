"""Characterisation tests for engine.pipeline.state and the locals -> state conversion of run_collision (v26.3.0 p4-03).

The expected literals were produced by running the legacy ``collision.run_collision`` on today's code (hackeye-rnd
image, under the test conftest) and by an AST scan of that function; the engine modules are imported inside each test
(they do not exist yet).

How the allow-lists below were derived (an AST scan of today's ``collision.run_collision``, which is the same body
that lives in ``engine.pipeline.run`` after p4-02). Every ``ast.Name`` in Store context was classified by what binds
it:

* plain assignment targets (``x = ...``, ``a, b = ...``, augmented / annotated assignment): these are the function's
  real locals and all must become ``s.x`` / ``f.x`` (so no bare Store is allowed for them);
* ``for`` targets: only loop variables are allowed to stay bare when the name is *only* a loop variable or is read
  only inside its own loop body. Today these are ``i`` (the frame loop; ``f`` cannot exist before the loop, so it
  stays bare), ``_g``, ``ii``, ``it`` and ``tid`` / ``tr`` (the ``for tid, tr in tracks.items()`` loops and ``for tid
  in list(coast.active)``);
* comprehension targets: ``h``, ``it``, ``k``, ``v``;
* lambda parameters (``ast.arg`` of a ``Lambda``): ``e``, ``it``, ``tid``;
* ``with`` targets and ``except ... as`` names: none exist today, so the allow-list is empty.

``tid``, ``tr`` and ``k`` are *also* plain locals of today's function (``tid = matches.get(ii)``, ``tr =
tracks[tid]``, ``k = scale.value``) and are read outside any loop that binds them: those plain Stores and the leaking
reads are what the conversion must turn into ``f.`` attributes (spec: "tr leaks"). That is why two checks exist: the
Store check is kind-aware, and the leak check requires every bare read of an allowed name to sit inside a ``for`` body
/ comprehension / lambda that binds it.

Today's function also has a plain local named ``f`` (``f = focal_px(gw, hfov)``, the focal length in pixels): it
collides with the ``FrameState`` variable ``f``. A bare Store of ``s`` / ``f`` is therefore only accepted as ``s =
RunState()`` / ``f = FrameState()``; the focal length has to become an attribute (``s.f``).

The "green against legacy" proof does not apply to the AST tests (red by design until the conversion); the smoke test
and the dataclass-shape helpers were proven green with a throwaway shim.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

import collision
import worldmap
from lab import collisions

if TYPE_CHECKING:
    from collections.abc import Iterator

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
FIXTURE = "chest0004_review9"
N_FRAMES = 10

# Bare Store allow-lists, by what binds the name (derivation in the module docstring).
# "st": the stage loop of p4-05 (``for st in STAGES: st.fn(s, f)``; Opus, 2026-11-15).
FOR_TARGETS = {"i", "_g", "ii", "it", "tid", "tr", "st"}
COMP_TARGETS = {"h", "it", "k", "v"}
LAMBDA_PARAMS = {"e", "it", "tid"}
WITH_EXCEPT_TARGETS: set[str] = set()
BARE_STORE_OK = FOR_TARGETS | COMP_TARGETS | WITH_EXCEPT_TARGETS

PARAMS = [
    "grids",
    "times",
    "class_names",
    "config",
    "settings",
    "motion",
    "depth",
    "window",
    "sounds",
    "worldmap_config",
    "progress",
    "sensors",
]
# Loop-carried locals named by spec p4-03 / audit 5.1; each is assigned in today's function (checked on the legacy AST).
RUN_LEVEL = [
    "prev_t",
    "beep_run",
    "last_hard_pan_t",
    "prev_heading",
    "held_speed",
    "held_t",
    "ego_hist",
    "ego_hist_t0",
    "h_state",
    "raws",
    "prev_left",
    "prev_right",
    "prev_group",
    "last_estimate_t",
    "first_t",
    "meas_hist",
    "follow",
    "dscale",
    "gait_check",
    "anchor",
]
DIGEST: dict[str, Any] = {"nFrames": 10, "hazardCounts": [20, 25, 25, 24, 29, 28, 32, 29, 28, 23], "nEvents": 5}

_Scope = (ast.For, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Lambda)


def _function() -> ast.FunctionDef:
    from engine.pipeline import run

    tree = ast.parse(inspect.getsource(run.run_collision))
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert fn.name == "run_collision"
    return fn


def _parents(fn: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(fn) for child in ast.iter_child_nodes(parent)}


def _names(target: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def _is_state_assign(node: ast.Name, parent: ast.AST | None) -> bool:
    """``s = RunState()`` / ``f = FrameState()``: the only bare Stores of ``s`` and ``f``.

    Since p4-05 (Opus, 2026-11-15) ``s = setup(...)`` is the other accepted form: ``setup`` builds the ``RunState``
    (checked in ``test_state_objects_are_built_where_the_spec_says``)."""
    want = {"s": ("RunState", "setup"), "f": ("FrameState",)}.get(node.id)
    if (
        node.id == "s"
        and isinstance(parent, ast.Assign)
        and parent.targets == [node]
        and isinstance(parent.value, ast.Call)
        and isinstance(parent.value.func, ast.Name)
        and parent.value.func.id == "setup"
    ):
        return True
    return (
        want is not None
        and isinstance(parent, ast.Assign)
        and parent.targets == [node]
        and isinstance(parent.value, ast.Call)
        and isinstance(parent.value.func, ast.Name)
        and parent.value.func.id == want[0]
        and not parent.value.args
        and not parent.value.keywords
    )


def _store_kind(node: ast.Name, parents: dict[ast.AST, ast.AST]) -> str:
    """What binds this Store: for / comp / with / plain."""
    child: ast.AST = node
    while child in parents:
        parent = parents[child]
        if isinstance(parent, ast.For) and child is parent.target:
            return "for"
        if isinstance(parent, ast.comprehension) and child is parent.target:
            return "comp"
        if isinstance(parent, ast.withitem) and child is parent.optional_vars:
            return "with"
        if isinstance(parent, (ast.stmt, ast.comprehension)):
            break
        child = parent
    return "plain"


def _bare_store_violations(fn: ast.FunctionDef) -> list[str]:
    parents = _parents(fn)
    bad: list[str] = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)):
            continue
        if node.id in ("s", "f"):
            if not _is_state_assign(node, parents.get(node)):
                bad.append(f"{node.id}@{node.lineno}")
            continue
        kind = _store_kind(node, parents)
        ok = {"for": FOR_TARGETS, "comp": COMP_TARGETS, "with": WITH_EXCEPT_TARGETS}.get(kind, set())
        if node.id not in ok:
            bad.append(f"{node.id}@{node.lineno}({kind})")
    return bad


def _binds(scope: ast.AST, child: ast.AST, name: str) -> bool:
    """True when ``name`` is bound by ``scope`` for the node reached through ``child``."""
    if isinstance(scope, ast.For):
        return name in _names(scope.target) and (child in scope.body or child in scope.orelse)
    if isinstance(scope, ast.Lambda):
        return name in {a.arg for a in scope.args.args + scope.args.kwonlyargs}
    if isinstance(scope, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return any(name in _names(g.target) for g in scope.generators)
    return False


def _leaking_reads(fn: ast.FunctionDef) -> list[str]:
    """Bare reads of an allowed loop / comprehension / lambda name outside every scope that binds it."""
    parents = _parents(fn)
    bad: list[str] = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
            continue
        if node.id not in FOR_TARGETS | COMP_TARGETS | LAMBDA_PARAMS:
            continue
        child: ast.AST = node
        bound = False
        while child in parents:
            parent = parents[child]
            if isinstance(parent, _Scope) and _binds(parent, child, node.id):
                bound = True
                break
            child = parent
        if not bound:
            bad.append(f"{node.id}@{node.lineno}")
    return bad


def _lambda_params(fn: ast.FunctionDef) -> set[str]:
    return {
        a.arg
        for n in ast.walk(fn)
        if isinstance(n, ast.Lambda)
        for a in n.args.posonlyargs + n.args.args + n.args.kwonlyargs
    }


def _attrs_of(fn: ast.FunctionDef, var: str) -> set[str]:
    return {
        n.attr
        for n in ast.walk(fn)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == var
    }


def _main_loop(fn: ast.FunctionDef) -> ast.For:
    loops = [n for n in fn.body if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "i"]
    assert len(loops) == 1
    return loops[0]


def _fields(cls: type) -> list[dataclasses.Field[Any]]:
    assert dataclasses.is_dataclass(cls)
    return list(dataclasses.fields(cls))


def _shape_problems(cls: type) -> list[str]:
    """Every field defaults to None or to a factory making a fresh empty list / dict."""
    problems: list[str] = []
    for fld in _fields(cls):
        if fld.default_factory is not dataclasses.MISSING:
            made = fld.default_factory()
            if made not in ([], {}) or type(made) not in (list, dict):
                problems.append(f"{fld.name}: factory makes {made!r}")
        elif fld.default is not None:
            problems.append(f"{fld.name}: default {fld.default!r}")
    return problems


def _shared_containers(cls: type) -> list[str]:
    a, b = cls(), cls()
    return [
        fld.name
        for fld in _fields(cls)
        if fld.default_factory is not dataclasses.MISSING and getattr(a, fld.name) is getattr(b, fld.name)
    ]


def _fixture_args() -> tuple[Any, ...]:
    """Positional args and kwargs of ``run_collision`` for the first N_FRAMES frames of the fixture window."""
    meta = json.loads((FIXTURES / f"{FIXTURE}.json").read_text())
    with np.load(FIXTURES / f"{FIXTURE}.npz") as z:
        grids, times = z["w0_grids"][:N_FRAMES], z["w0_t"][:N_FRAMES]
        motion = {"t": z["w0_mt"], "dx": z["w0_mdx"], "dy": z["w0_mdy"], "resid": z["w0_mresid"]}
        d = meta["depth"]
        depth = {"t": times, "depth": z["w0_depth"][:N_FRAMES], "units": d["units"], "anchor": d["anchor"]}
        sensors = {k[len("sensors_") :]: z[k] for k in z.files if k.startswith("sensors_")}
    config = collisions.apply_overrides(collision.load_config(), meta.get("overrides", {}), "collision")
    s = meta["settings"]
    settings = collision.resolve_settings(
        config,
        s["mount"],
        s["hfovDeg"],
        s["cameraHeightM"],
        s["stepLengthM"],
        projection=s.get("projection"),
        distance_source=s.get("distanceSource", "ground"),
        user_height_m=s.get("userHeightM"),
        camera_location=s.get("cameraLocation"),
        camera_side=s.get("cameraSide"),
        object_distance=s.get("objectDistance"),
        use_horizon=s.get("useHorizon"),
    )
    sounds = {"kinds": {}, "speechRate": meta.get("speechRate", 1.0)}
    return (grids, times, meta["classNames"], config, settings, motion, depth, sounds, worldmap.load_config(), sensors)


def _iter_run_state_fields() -> Iterator[str]:
    from engine.pipeline import state

    for fld in _fields(state.RunState):
        yield fld.name


def test_state_classes_are_dataclasses_with_none_or_empty_defaults() -> None:
    from engine.pipeline import state

    for cls in (state.RunState, state.FrameState):
        assert _fields(cls)
        assert _shape_problems(cls) == []
        inst = cls()
        for fld in _fields(cls):
            if fld.default_factory is dataclasses.MISSING:
                assert getattr(inst, fld.name) is None


def test_state_instances_never_share_containers() -> None:
    from engine.pipeline import state

    assert _shared_containers(state.RunState) == []
    assert _shared_containers(state.FrameState) == []


def test_state_classes_have_no_slots_and_distinct_field_names() -> None:
    from engine.pipeline import state

    for cls in (state.RunState, state.FrameState):
        assert not hasattr(cls, "__slots__")
    run_names = [f.name for f in _fields(state.RunState)]
    frame_names = [f.name for f in _fields(state.FrameState)]
    assert len(run_names) == len(set(run_names))
    assert len(frame_names) == len(set(frame_names))
    assert set(run_names) & set(frame_names) == set()


def test_run_state_holds_the_parameters_in_signature_order() -> None:
    names = list(_iter_run_state_fields())
    assert [n for n in names if n in PARAMS] == PARAMS


def test_run_state_holds_the_loop_carried_locals() -> None:
    names = set(_iter_run_state_fields())
    assert [n for n in RUN_LEVEL if n not in names] == []


def test_run_state_attrs_used_by_run_collision_are_fields() -> None:
    from engine.pipeline import state

    fn = _function()
    used_s = _attrs_of(fn, "s")
    assert used_s
    assert sorted(used_s - {f.name for f in _fields(state.RunState)}) == []


def test_frame_state_attrs_used_by_run_collision_are_fields() -> None:
    from engine.pipeline import state

    fn = _function()
    used_f = _attrs_of(fn, "f")
    assert used_f
    assert sorted(used_f - {f.name for f in _fields(state.FrameState)}) == []


def _calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [c for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == name]


def test_state_objects_are_built_where_the_spec_says() -> None:
    """One ``RunState()`` before the frame loop: in ``run_collision`` itself (p4-03, p4-04) or, since p4-05, inside the
    ``setup`` it calls as ``s = setup(...)`` (Opus, 2026-11-15: the final shape of test_stages_b.py wins)."""
    fn = _function()
    top = [n for n in fn.body if isinstance(n, ast.Assign)]
    run_assigns = [
        n
        for n in top
        if isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id in ("RunState", "setup")
    ]
    assert len(run_assigns) == 1
    assert fn.body.index(run_assigns[0]) < fn.body.index(_main_loop(fn))
    value = run_assigns[0].value
    assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
    if value.func.id == "setup":
        from engine.pipeline import stages

        setup_fn = ast.parse(textwrap.dedent(inspect.getsource(stages.setup))).body[0]
        assert len(_calls(setup_fn, "RunState")) == 1
    first = _main_loop(fn).body[0]
    assert isinstance(first, ast.Assign)
    assert isinstance(first.value, ast.Call)
    assert isinstance(first.value.func, ast.Name)
    assert first.value.func.id == "FrameState"
    assert [t.id for t in first.targets if isinstance(t, ast.Name)] == ["f"]


def test_no_bare_store_names_except_the_allow_list() -> None:
    """Red today: every plain local is still a bare name (``f = focal_px(...)`` also collides with FrameState ``f``)."""
    assert _bare_store_violations(_function()) == []


def test_allowed_names_are_not_read_outside_their_scope() -> None:
    """A loop / comprehension name left bare must not be read after its loop (audit 5.1: ``tr`` leaks)."""
    assert _leaking_reads(_function()) == []


def test_lambda_parameters_stay_within_the_allow_list() -> None:
    assert _lambda_params(_function()) <= LAMBDA_PARAMS


def test_run_collision_still_returns_hazards_and_events() -> None:
    from engine.pipeline import run

    grids, times, names, config, settings, motion, depth, sounds, wcfg, sensors = _fixture_args()
    out = run.run_collision(
        grids, times, names, config, settings, motion, depth=depth, sounds=sounds, worldmap_config=wcfg, sensors=sensors
    )
    assert isinstance(out, tuple)
    assert len(out) == 2
    hazards_doc, events_doc = out
    digest = {
        "nFrames": len(hazards_doc["frames"]),
        "hazardCounts": [len(fr["hazards"]) for fr in hazards_doc["frames"]],
        "nEvents": len(events_doc["events"]),
    }
    assert digest == DIGEST
