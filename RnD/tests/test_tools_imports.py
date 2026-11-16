"""v26.3.0 p5-07: every ``RnD/tools/*.py`` imports cleanly and every facade name it reads resolves.

The tools reach the Lab and the engine through the flat facades (``collision``, ``worldmap``, ``lab.analysis``, ...). p5-07 moves
the plain functions and classes to their engine homes and keeps every facade name the tools (and the tests they share code with)
read. These tests pin that surface:

* ``test_tool_imports_cleanly``: each tool is loaded by path with ``importlib``; ``main()`` is never called. The three
  ``depth_*`` diagnostics are module-level scripts (no ``__main__`` guard, no ``main()``): loading one runs its analysis on
  ``/debug/lab/runs``, so they are skipped here and covered by the static checks below.
* ``test_facade_name_resolves``: one case per (tool, module, name) in ``FACADE_READS``.
* ``test_table_covers_static_reads`` / ``test_every_tool_listed``: the table is the full list of project names each tool reads
  (static AST scan), so a new read added to a tool fails here until it is listed.

``FACADE_READS`` is the inventory as of the Phase 5 start. ``equivalence.py`` reaches its names through ``importlib.import_module``
and in its ``_patched`` pairs, so its entries are written by hand. No engine module is imported here: the names must resolve on
the legacy facades now and after p5-07.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

RND = Path(__file__).resolve().parents[1]
TOOLS = RND / "tools"
# Flat test helpers (``worldtracks_fixtures``) are imported by name, as collision_score.py does; tests/ is not on sys.path by default.
sys.path.insert(0, str(RND / "tests"))
sys.path.insert(0, str(RND / "src"))
sys.path.insert(0, str(RND))

# p5-07 (2026-11-16): the depth_* scripts got main() + a __main__ guard, so every tool imports without running; none is excluded.
SCRIPTS_WITHOUT_MAIN: dict[str, str] = {}

# tool file -> {module the tool reads from -> names it reads}. Dotted names (``WorldMap.resolve_frame``) are resolved by attribute.
FACADE_READS: dict[str, dict[str, tuple[str, ...]]] = {
    "collision_score.py": {
        "collision": ("load_config", "resolve_settings", "run_collision"),
        "lab.collisions": ("apply_overrides",),
        "worldmap": ("load_config",),
        "worldtracks_fixtures": ("NAMES", "FIXTURES"),
        "tests.replay": ("fixture_sensors",),
    },
    "depth_delta_calibration.py": {
        "collision": ("focal_px", "load_config", "resolve_class_ids", "resolve_settings", "walking_region"),
    },
    "depth_lens_diagnostic.py": {
        "collision": ("load_config", "resolve_class_ids", "walking_region"),
    },
    "depth_lens_fit.py": {
        "collision": ("load_config", "resolve_class_ids", "walking_region"),
    },
    # Dynamic: importlib.import_module("collision") / ("worldmap") / ("lab.recordings") ... and the _patched() pairs.
    "equivalence.py": {
        "collision": ("load_config", "resolve_settings", "run_collision"),
        "worldmap": ("load_config", "build"),
        "lab.recordings": ("LAB_DIR", "get_recording", "list_recordings", "sensors_for"),
        "lab.analysis": ("LAB_DIR", "_active"),
        "lab.reviews": ("LAB_DIR", "secrets.token_hex"),
        "lab.server": ("_wm_cache", "_hz_cache", "OrderedDict"),
    },
    "ground_diag.py": {
        "lab.analysis": ("LAB_DIR", "run_dir"),
        "worldmap": (
            "Observer",
            "WorldMap",
            "WorldMap.resolve_frame",
            "class_kinds",
            "first_depth_scale",
            "frames_from_hazards",
            "groundfuse",
            "load_config",
            "settings_from_hazards",
        ),
        "groundfuse": ("settings",),
    },
    "make_fixture.py": {},
    "sensors_report.py": {
        "sensors": ("crop", "gps_course_offset", "gps_good", "gps_step_length", "gps_xy", "heading_series", "hilights", "vertical_signals"),
        "collision": ("_sensor_series", "estimate_cadence", "load_config"),
        "lab.analysis": ("get_run", "run_dir"),
        "lab.collisions": ("collision_dir", "resolve"),
        "lab.recordings": ("get_recording", "list_recordings", "sensors_for"),
    },
    "worldmap_agreement.py": {
        "collision": ("load_config",),
        "worldmap": ("build", "load_config"),
        "lab.analysis": ("run_dir",),
    },
    "worldmap_metrics.py": {
        "collision": ("load_config",),
        "worldmap": ("KIND_SURFACE", "UNKNOWN", "build", "class_kinds", "load_config"),
        "lab.analysis": ("run_dir",),
    },
    "worldmap_render.py": {
        "lab.analysis": ("LAB_DIR", "run_dir"),
        "segmentation": ("_CONFIG_DIR", "_load_mapping"),
    },
    "worldtracks_metrics.py": {
        "collision": ("LAST_WORLD_TRACKS_MS", "load_config"),
        "lab.analysis": ("run_dir",),
        "tests.worldtracks_fixtures": ("all_runs",),
    },
}

TOOL_FILES = sorted(p.name for p in TOOLS.glob("*.py"))
IMPORTABLE_TOOLS = [t for t in TOOL_FILES if t not in SCRIPTS_WITHOUT_MAIN]
TRIPLES = [(tool, mod, name) for tool, reads in sorted(FACADE_READS.items()) for mod, names in reads.items() for name in names]


def _load_tool(file_name: str) -> ModuleType:
    path = TOOLS / file_name
    mod_name = f"_p5_07_tool_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None, f"no loader for {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # dataclasses in equivalence.py look the module up while it executes
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(mod_name, None)
    return mod


def _is_project(module: str) -> bool:
    try:
        spec = importlib.util.find_spec(module.split(".")[0])
    except (ImportError, ValueError):
        return False
    origin = spec.origin if spec is not None else None
    return origin is not None and origin.startswith(str(RND))


def _static_reads(path: Path) -> dict[str, set[str]]:
    """module -> top-level names the file reads from it, for ``import X [as Y]``, ``from X import N`` and ``from lab|tests import m``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    alias: dict[str, str] = {}
    reads: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if _is_project(a.name):
                    alias[a.asname or a.name] = a.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and _is_project(node.module):
            for a in node.names:
                if node.module in ("lab", "tests"):
                    alias[a.asname or a.name] = f"{node.module}.{a.name}"
                else:
                    reads.setdefault(node.module, set()).add(a.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in alias:
            reads.setdefault(alias[node.value.id], set()).add(node.attr)
    return reads


def _resolve(module: str, dotted: str) -> object:
    obj: object = importlib.import_module(module)
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


@pytest.mark.parametrize("tool", IMPORTABLE_TOOLS)
def test_tool_imports_cleanly(tool: str) -> None:
    mod = _load_tool(tool)
    assert mod.__file__ == str(TOOLS / tool)


def test_every_tool_is_importable() -> None:
    assert sorted(IMPORTABLE_TOOLS) == TOOL_FILES


def test_every_tool_listed() -> None:
    assert sorted(FACADE_READS) == TOOL_FILES


@pytest.mark.parametrize("tool", TOOL_FILES)
def test_table_covers_static_reads(tool: str) -> None:
    listed = {
        (mod, name.split(".")[0]) for mod, names in FACADE_READS.get(tool, {}).items() for name in names
    }
    static = {(mod, name) for mod, names in _static_reads(TOOLS / tool).items() for name in names}
    assert static <= listed, f"{tool} reads names missing from FACADE_READS: {sorted(static - listed)}"


@pytest.mark.parametrize(("tool", "module", "name"), TRIPLES, ids=[f"{t}:{m}.{n}" for t, m, n in TRIPLES])
def test_facade_name_resolves(tool: str, module: str, name: str) -> None:
    try:
        _resolve(module, name)
    except AttributeError as exc:
        pytest.fail(f"{tool} reads {module}.{name}, which no longer resolves: {exc}")
