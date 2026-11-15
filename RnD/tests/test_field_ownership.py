# ruff: noqa: E501
"""Field-ownership guard for ``Item`` / ``Track`` (v26.3.0 p4-07), a static AST scan.

``engine.core.types.FIELD_WRITERS`` maps ``"Item.<field>"`` / ``"Track.<field>"`` to the models allowed to write the field (owner
first). The scan reads every ``src/engine/<model>/**/*.py`` except ``pipeline`` and ``core`` and finds writes to those fields:
assignments / augmented assignments to ``<expr>.<field>`` and keyword arguments of ``replace(...)`` / ``Item(...)`` / ``Track(...)``.
A write by a model that is not in the field's entry fails; so does a field without an entry or an entry naming an unknown model.

Attribute assignments cannot be told apart by type, so ``<expr>.<field>`` is allowed when the model is a writer of ``Item.<field>`` or of
``Track.<field>`` (``replace(...)`` likewise); ``Item(...)`` / ``Track(...)`` keywords are checked against their own type.
The scanner takes the source text and the tables as arguments, so the negative tests run it on synthetic strings.
"""

from __future__ import annotations

import ast
import dataclasses
from dataclasses import dataclass
from pathlib import Path

RnD = Path(__file__).resolve().parents[1]
ENGINE_DIR = RnD / "src" / "engine"

EXEMPT_MODELS = frozenset({"pipeline", "core"})  # pipeline may write any field; core defines the types
CONSTRUCTORS = ("Item", "Track")

# Writes to an attribute that has the name of an Item / Track field but belongs to an unrelated object.
# Key: (path relative to src/engine, attribute, receiver source text) -> reason.
ALLOWED_UNRELATED: dict[tuple[str, str, str], str] = {
    ("depthscale/anchors.py", "last_t", "self"): "depth anchor's own last-update time, not Track.last_t",
    ("speech/policy.py", "last_t", "self"): "SpeechPolicy's own last-step time, not Track.last_t",
    ("worldtracks/tracks.py", "id", "self"): "the world-track record's own id, not Track.id",
    ("worldtracks/tracks.py", "group", "self"): "the world-track record's own group, not Item.group / Track.group",
    ("worldtracks/tracks.py", "family", "self"): "the world-track record's own family, not Item.family",
    ("worldtracks/tracks.py", "group", "tr"): "a world-track record (tr.cls, tr.group = m[...]), not a Track",
}


@dataclass(frozen=True)
class Write:
    """One write to an Item / Track field found in a source file."""

    path: str  # relative to src/engine, posix
    line: int
    field: str
    kind: str  # "attr" | "replace" | "Item" | "Track"
    receiver: str  # source text of the object written to ("" for keyword arguments)

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind} write to {self.field}"


def _target_attrs(target: ast.expr) -> list[ast.Attribute]:
    """Attribute targets of an assignment, looking inside tuple / list unpacking."""
    if isinstance(target, ast.Attribute):
        return [target]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [a for elt in target.elts for a in _target_attrs(elt)]
    if isinstance(target, ast.Starred):
        return _target_attrs(target.value)
    return []


def _call_name(call: ast.Call) -> str:
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def scan_source(source: str, path: str, names: frozenset[str]) -> list[Write]:
    """Every write to an attribute / keyword whose name is in ``names``, in source order."""
    tree = ast.parse(source, filename=path)
    found: list[tuple[int, int, Write]] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for tgt in targets:
            for attr in _target_attrs(tgt):
                if attr.attr in names:
                    found.append(
                        (
                            attr.lineno,
                            attr.col_offset,
                            Write(path, attr.lineno, attr.attr, "attr", ast.unparse(attr.value)),
                        )
                    )
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name == "replace" or name in CONSTRUCTORS:
                kind = "replace" if name == "replace" else name
                found.extend(
                    (kw.value.lineno, kw.value.col_offset, Write(path, kw.value.lineno, kw.arg, kind, ""))
                    for kw in node.keywords
                    if kw.arg and kw.arg in names
                )
    found.sort(key=lambda t: (t[0], t[1]))
    return [w for _, _, w in found]


def type_fields() -> dict[str, frozenset[str]]:
    from engine.core.types import Item, Track

    return {
        "Item": frozenset(f.name for f in dataclasses.fields(Item)),
        "Track": frozenset(f.name for f in dataclasses.fields(Track)),
    }


def known_models() -> set[str]:
    from tests.test_module_boundaries import load_config

    return set(load_config()["models"])


def check_writes(
    writes: list[Write],
    model: str,
    writers: dict[str, tuple[str, ...]],
    allowed: dict[tuple[str, str, str], str],
) -> list[str]:
    """Violation messages for the writes of one model (``file:line, field, allowed writers``)."""
    bad: list[str] = []
    for w in writes:
        if w.kind == "attr" and (w.path, w.field, w.receiver) in allowed:
            continue
        if w.kind in CONSTRUCTORS:
            keys = [f"{w.kind}.{w.field}"]
        else:
            keys = [f"Item.{w.field}", f"Track.{w.field}"]
        owners: list[str] = []
        for key in keys:
            owners.extend(writers.get(key, ()))
        if model not in owners:
            bad.append(f"{w}: model {model!r} is not a writer (allowed: {sorted(set(owners))})")
    return bad


def model_files() -> list[tuple[str, Path]]:
    """(model, file) of every python file of the models that are guarded."""
    out: list[tuple[str, Path]] = []
    for sub in sorted(
        p for p in ENGINE_DIR.iterdir() if p.is_dir() and p.name not in EXEMPT_MODELS and p.name != "__pycache__"
    ):
        out.extend((sub.name, f) for f in sorted(sub.rglob("*.py")))
    return out


def scan_engine(names: frozenset[str]) -> dict[str, list[Write]]:
    """Writes per model over the whole of src/engine (pipeline and core excluded)."""
    result: dict[str, list[Write]] = {}
    for model, file in model_files():
        rel = file.relative_to(ENGINE_DIR).as_posix()
        result.setdefault(model, []).extend(scan_source(file.read_text(encoding="utf-8"), rel, names))
    return result


def _writers() -> dict[str, tuple[str, ...]]:
    from engine.core import types

    table: dict[str, tuple[str, ...]] = dict(types.FIELD_WRITERS)
    return table


# --------------------------------------------------------------------------------------------------------------
# The three checks on the real tree


def test_every_field_has_an_entry_with_known_models() -> None:
    writers = _writers()
    models = known_models()
    expected = {f"{t}.{f}" for t, fs in type_fields().items() for f in fs}
    assert sorted(expected - set(writers)) == [], "fields without a FIELD_WRITERS entry"
    assert sorted(set(writers) - expected) == [], "FIELD_WRITERS entries that are not Item / Track fields"
    empty = sorted(k for k, v in writers.items() if not v)
    assert empty == [], "entries with no writer"
    unknown = {k: [m for m in v if m not in models] for k, v in writers.items() if any(m not in models for m in v)}
    assert unknown == {}, "entries naming a model that is not in BOUNDARIES.toml"
    assert all(m not in EXEMPT_MODELS for v in writers.values() for m in v), "pipeline / core are never listed"
    dupes = sorted(k for k, v in writers.items() if len(set(v)) != len(v))
    assert dupes == [], "a model listed twice"


def test_no_model_writes_a_field_it_does_not_own() -> None:
    writers = _writers()
    names = frozenset().union(*type_fields().values())
    violations: list[str] = []
    for model, writes in scan_engine(names).items():
        violations.extend(check_writes(writes, model, writers, ALLOWED_UNRELATED))
    assert violations == []


def test_allow_list_entries_are_still_needed() -> None:
    """A stale allow-list entry (the unrelated write is gone) hides nothing, but must be removed."""
    names = frozenset().union(*type_fields().values())
    seen = {(w.path, w.field, w.receiver) for ws in scan_engine(names).values() for w in ws if w.kind == "attr"}
    assert sorted(set(ALLOWED_UNRELATED) - seen) == []
    assert all(reason.strip() for reason in ALLOWED_UNRELATED.values())


def test_scan_sees_the_known_writers() -> None:
    """The scan is not vacuous: writers observed in the engine on 2026-11-15 are found."""
    names = frozenset().union(*type_fields().values())
    per_model = scan_engine(names)
    seen = {(m, w.field) for m, ws in per_model.items() for w in ws}
    expected = {
        ("detection", "distance_m"),
        ("detection", "bbox"),
        ("tracking", "closing_raw"),
        ("tracking", "present_run"),
        ("motion", "own_ok"),
        ("motion", "still_t0"),
        ("roles", "urgency"),
        ("worldmap", "map_world"),
        ("memory", "mem_id"),
        ("speech", "thin_done"),
        ("depthscale", "dist_source"),
    }
    assert expected <= seen
    assert not any(m in EXEMPT_MODELS for m in per_model)


# --------------------------------------------------------------------------------------------------------------
# Negative / unit tests of the scanner on synthetic sources

NAMES = frozenset({"role", "closing", "moving", "bbox"})
TABLE: dict[str, tuple[str, ...]] = {
    "Item.role": ("roles",),
    "Item.closing": ("tracking",),
    "Track.closing": ("tracking",),
    "Item.moving": ("motion",),
    "Track.moving": ("motion",),
    "Item.bbox": ("detection",),
}


def test_forbidden_attribute_write_is_reported() -> None:
    src = "def f(it):\n    it.role = 'x'\n"
    writes = scan_source(src, "tracking/x.py", NAMES)
    assert [(w.line, w.field, w.kind) for w in writes] == [(2, "role", "attr")]
    bad = check_writes(writes, "tracking", TABLE, {})
    assert len(bad) == 1
    assert "tracking/x.py:2" in bad[0]
    assert "role" in bad[0]
    assert "roles" in bad[0]


def test_owner_write_is_accepted() -> None:
    src = "def f(it):\n    it.role = 'x'\n"
    writes = scan_source(src, "roles/x.py", NAMES)
    assert check_writes(writes, "roles", TABLE, {}) == []


def test_augmented_annotated_and_tuple_writes_are_found() -> None:
    src = "def f(it, tr):\n    it.closing += 1.0\n    it.role, tr.moving = 'a', True\n    it.bbox: list[float] = []\n"
    writes = scan_source(src, "motion/x.py", NAMES)
    assert [(w.line, w.field) for w in writes] == [(2, "closing"), (3, "role"), (3, "moving"), (4, "bbox")]
    bad = check_writes(writes, "motion", TABLE, {})
    assert [b.split(":")[1] for b in bad] == ["2", "3", "4"]


def test_replace_and_constructor_keywords_are_found() -> None:
    src = (
        "import dataclasses\n"
        "def f(it):\n"
        "    a = replace(it, role='x', other=1)\n"
        "    b = dataclasses.replace(it, closing=None)\n"
        "    c = Item(bbox=[0.0], role='none')\n"
        "    d = Track(moving=True)\n"
    )
    writes = scan_source(src, "speech/x.py", NAMES)
    assert [(w.line, w.field, w.kind) for w in writes] == [
        (3, "role", "replace"),
        (4, "closing", "replace"),
        (5, "bbox", "Item"),
        (5, "role", "Item"),
        (6, "moving", "Track"),
    ]
    assert len(check_writes(writes, "speech", TABLE, {})) == 5
    assert check_writes(writes, "detection", TABLE, {}) != []


def test_constructor_keywords_are_checked_against_their_own_type() -> None:
    table: dict[str, tuple[str, ...]] = {"Item.role": ("roles",), "Track.role": ("tracking",)}
    src = "def f():\n    Track(role='x')\n    Item(role='x')\n"
    writes = scan_source(src, "tracking/x.py", frozenset({"role"}))
    bad = check_writes(writes, "tracking", table, {})
    assert len(bad) == 1
    assert ":3:" in bad[0]


def test_attribute_write_is_allowed_by_either_type() -> None:
    table: dict[str, tuple[str, ...]] = {"Item.moving": ("motion",), "Track.moving": ("tracking",)}
    src = "def f(tr):\n    tr.moving = True\n"
    writes = scan_source(src, "tracking/x.py", NAMES)
    assert check_writes(writes, "tracking", table, {}) == []
    assert check_writes(writes, "motion", table, {}) == []
    assert check_writes(writes, "roles", table, {}) != []


def test_names_that_are_not_fields_are_ignored() -> None:
    src = "def f(it):\n    it.other = 1\n    x = replace(it, other=2)\n    dict(role=1)\n    y = it.role\n"
    assert scan_source(src, "tracking/x.py", NAMES) == []


def test_allow_list_excludes_an_unrelated_object() -> None:
    src = "class W:\n    def __init__(self):\n        self.role = 'x'\n"
    writes = scan_source(src, "memory/world.py", NAMES)
    assert len(check_writes(writes, "memory", TABLE, {})) == 1
    allowed = {("memory/world.py", "role", "self"): "WorldMemory's own attribute"}
    assert check_writes(writes, "memory", TABLE, allowed) == []
    other_file = scan_source(src, "memory/other.py", NAMES)
    assert len(check_writes(other_file, "memory", TABLE, allowed)) == 1


def test_unknown_field_entry_and_missing_entry_are_detected_by_the_table_check() -> None:
    """The table check compares against the dataclass fields: a table with a hole or a stale key differs from the expected key set."""
    expected = {f"{t}.{f}" for t, fs in type_fields().items() for f in fs}
    holed = dict.fromkeys(expected, ("detection",))
    del holed["Item.bbox"]
    holed["Item.not_a_field"] = ("detection",)
    assert sorted(expected - set(holed)) == ["Item.bbox"]
    assert sorted(set(holed) - expected) == ["Item.not_a_field"]


def test_scan_ignores_the_exempt_models() -> None:
    assert not any(model in EXEMPT_MODELS for model, _ in model_files())
    assert {"detection", "tracking", "roles", "motion", "speech", "worldmap", "memory"} <= {m for m, _ in model_files()}


def test_boundaries_models_include_every_guarded_directory() -> None:
    assert {m for m, _ in model_files()} <= known_models()
