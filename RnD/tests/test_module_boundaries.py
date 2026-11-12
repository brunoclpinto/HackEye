"""Import boundaries of src/engine (models), lab packages and lab/static/js, from src/engine/BOUNDARIES.toml.

Everything is an AST / regex scan of the source files; nothing is imported. The scanner functions take the trees
and the config as arguments so the unit tests at the bottom can run them on fake trees in tmp_path.
"""

from __future__ import annotations

import ast
import posixpath
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

RnD = Path(__file__).resolve().parents[1]
ENGINE_DIR = RnD / "src" / "engine"
LAB_DIR = RnD / "lab"
BOUNDARIES = ENGINE_DIR / "BOUNDARIES.toml"

# Flat modules / packages that engine code must never import (the legacy side); `lab` is added by the scanner.
LEGACY_EXTRA = frozenset(
    {
        "collision",
        "groundfuse",
        "geometry",
        "worldmap",
        "worldtracks",
        "faceedge",
        "sensors",
        "common_paths",
        "egoflow",
        "depth",
        "segmentation",
        "models",
        "letterbox",
        "config",
        "profiles",
        "gpu_guard",
        "detect",
        "track",
        "overlay",
        "pipeline",
        "debug_output",
        "replay",
        "cli",
    }
)

Config = dict[str, Any]


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    rule: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}"


def load_config(path: Path = BOUNDARIES) -> Config:
    with path.open("rb") as f:
        return tomllib.load(f)


def legacy_names(src_dir: Path) -> frozenset[str]:
    """Top-level names under src/ that are not engine, plus the fixed legacy list and `lab`."""
    found = {p.stem for p in src_dir.glob("*.py")} | {
        p.name for p in src_dir.iterdir() if p.is_dir() and p.name != "engine"
    }
    return frozenset(found | LEGACY_EXTRA | {"lab"})


# --------------------------------------------------------------------------------------------------------------
# Import extraction


@dataclass(frozen=True)
class ImportRef:
    line: int
    target: str  # absolute dotted name, or "" when a relative import escapes the root package
    escaped: bool = False


def module_name(root: Path, file: Path, top: str) -> str:
    """Dotted module name of `file` under `root`, where `root` is the package called `top`."""
    parts = [top, *file.relative_to(root).with_suffix("").parts]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def extract_imports(tree: ast.AST, module: str, is_package: bool, root_pkg: str) -> list[ImportRef]:
    """Every import in the tree (any nesting, TYPE_CHECKING included) as absolute dotted names.

    `from X import a` yields X.a (a may be a module); relative imports are resolved against `module`; one that climbs
    above `root_pkg` is flagged escaped.
    """
    refs: list[ImportRef] = []
    pkg = module.split(".") if is_package else module.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs.extend(ImportRef(node.lineno, a.name) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                up = node.level - 1
                base = pkg[: len(pkg) - up] if up <= len(pkg) else []
                if not base or base[0] != root_pkg:
                    refs.append(ImportRef(node.lineno, "", escaped=True))
                    continue
                prefix = ".".join([*base, node.module] if node.module else base)
            else:
                prefix = node.module or ""
            refs.extend(ImportRef(node.lineno, f"{prefix}.{a.name}" if a.name != "*" else prefix) for a in node.names)
    return refs


def parse(file: Path) -> ast.AST:
    return ast.parse(file.read_text(encoding="utf-8"), filename=str(file))


def name_matches(target: str, allowed: list[str]) -> bool:
    return "*" in allowed or any(target == a or target.startswith(a + ".") for a in allowed)


# --------------------------------------------------------------------------------------------------------------
# Engine


def model_settings(cfg: Config, model: str) -> Config | None:
    models: Config = cfg.get("models", {})
    if model not in models:
        return None
    merged: Config = {**cfg.get("defaults", {}), **models[model]}
    return merged


def engine_target_model(target: str) -> str | None:
    parts = target.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "engine" else None


def scan_engine(engine_dir: Path, cfg: Config, legacy: frozenset[str]) -> tuple[list[Violation], dict[str, set[str]]]:
    """Violations and the model -> model import graph of every .py under `engine_dir` (the `engine` package)."""
    violations: list[Violation] = []
    graph: dict[str, set[str]] = {}
    for file in sorted(engine_dir.rglob("*.py")):
        rel = file.relative_to(engine_dir)
        if rel.parts[0] == "__init__.py" and len(rel.parts) == 1:
            continue
        model = rel.parts[0] if len(rel.parts) > 1 else rel.with_suffix("").name
        settings = model_settings(cfg, model)
        if settings is None:
            violations.append(
                Violation(file, 1, f"engine model '{model}' is not declared in BOUNDARIES.toml [models.{model}]")
            )
            continue
        module = module_name(engine_dir, file, "engine")
        for ref in extract_imports(parse(file), module, file.name == "__init__.py", "engine"):
            if ref.escaped:
                violations.append(Violation(file, ref.line, "relative import escapes the engine package"))
                continue
            violations.extend(check_engine_import(file, ref, model, settings, legacy, graph))
    return violations, graph


def check_engine_import(
    file: Path, ref: ImportRef, model: str, settings: Config, legacy: frozenset[str], graph: dict[str, set[str]]
) -> list[Violation]:
    top = ref.target.split(".")[0]
    if top == "engine":
        target_model = engine_target_model(ref.target)
        if target_model is None or target_model == model:
            return []
        graph.setdefault(model, set()).add(target_model)
        if not name_matches(ref.target, settings.get("engine", [])):
            return [
                Violation(
                    file,
                    ref.line,
                    f"model '{model}' may not import '{ref.target}' (allowed: {settings.get('engine', [])})",
                )
            ]
        return []
    if top in legacy:
        return [Violation(file, ref.line, f"engine code may not import legacy module / lab '{ref.target}'")]
    if top in sys.stdlib_module_names:
        return (
            []
            if settings.get("stdlib", True)
            else [Violation(file, ref.line, f"model '{model}' may not import stdlib '{top}'")]
        )
    if top not in settings.get("third_party", []):
        return [
            Violation(
                file,
                ref.line,
                f"third-party package '{top}' is not allowed in model '{model}' "
                f"(allowed: {settings.get('third_party', [])})",
            )
        ]
    return []


# --------------------------------------------------------------------------------------------------------------
# Lab packages


def lab_package_of(module: str) -> str | None:
    parts = module.split(".")
    return ".".join(parts[:2]) if len(parts) > 1 and parts[0] == "lab" else None


def scan_lab(lab_dir: Path, cfg: Config) -> tuple[list[Violation], dict[str, set[str]]]:
    """Rules for the lab packages that exist (lab/<name>/__init__.py) plus the 'only X may import lab.api' rule."""
    lab_cfg: Config = cfg.get("lab", {})
    packages: Config = lab_cfg.get("packages", {})
    only: dict[str, list[str]] = lab_cfg.get("only_importer_of", {})
    violations: list[Violation] = []
    graph: dict[str, set[str]] = {}
    for file in sorted(lab_dir.rglob("*.py")):
        if "static" in file.relative_to(lab_dir).parts:
            continue
        module = module_name(lab_dir, file, "lab")
        own = lab_package_of(module) if len(file.relative_to(lab_dir).parts) > 1 else None
        own_rules: Config | None = packages.get(own) if own else None
        for ref in extract_imports(parse(file), module, file.name == "__init__.py", "lab"):
            if ref.escaped:
                violations.append(Violation(file, ref.line, "relative import escapes the lab package"))
                continue
            top = ref.target.split(".")[0]
            target_pkg = lab_package_of(ref.target) if top == "lab" else None
            for restricted, importers in only.items():
                if target_pkg == restricted and own != restricted and module not in importers:
                    violations.append(
                        Violation(file, ref.line, f"only {importers} may import '{restricted}' (found in '{module}')")
                    )
            if own_rules is None or own is None:
                continue
            if top == "lab" and target_pkg and target_pkg != own and target_pkg in packages:
                graph.setdefault(own, set()).add(target_pkg)
                if target_pkg not in own_rules.get("may_import", []):
                    violations.append(
                        Violation(
                            file,
                            ref.line,
                            f"'{own}' may not import '{target_pkg}' (allowed: {own_rules.get('may_import', [])})",
                        )
                    )
            elif top == "engine" and not name_matches(ref.target, own_rules.get("engine", [])):
                violations.append(
                    Violation(
                        file,
                        ref.line,
                        f"'{own}' may not import '{ref.target}' (allowed engine: {own_rules.get('engine', [])})",
                    )
                )
    return violations, graph


# --------------------------------------------------------------------------------------------------------------
# Cycles


def find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            if state.get(nxt, 0) == 1:
                return [*stack[stack.index(nxt) :], nxt]
            if state.get(nxt, 0) == 0 and (cyc := visit(nxt)):
                return cyc
        stack.pop()
        state[node] = 2
        return None

    for start in sorted(graph):
        if state.get(start, 0) == 0 and (cyc := visit(start)):
            return cyc
    return None


# --------------------------------------------------------------------------------------------------------------
# JS

_JS_PATTERNS = (
    re.compile(r"""\b(?:import|export)\b[^'";]*?\bfrom\s*['"]([^'"]+)['"]"""),
    re.compile(r"""\bimport\s*['"]([^'"]+)['"]"""),
    re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
)


def js_imports(text: str) -> list[tuple[int, str]]:
    found: dict[tuple[int, str], None] = {}
    for pat in _JS_PATTERNS:
        for m in pat.finditer(text):
            found[(text.count("\n", 0, m.start(1)) + 1, m.group(1))] = None
    return sorted(found)


def scan_js(js_root: Path, cfg: Config) -> list[Violation]:
    js_cfg: Config = cfg.get("js", {})
    features = str(js_cfg.get("features_dir", "features"))
    allowed: list[str] = js_cfg.get("feature_may_import", [])
    violations: list[Violation] = []
    for file in sorted(js_root.rglob("*.js")):
        rel = file.relative_to(js_root).as_posix()
        if not rel.startswith(features + "/"):
            continue
        parts = rel.split("/")
        own_dir = "/".join(parts[:2]) if len(parts) > 2 else None  # features/<name>/...
        for line, spec in js_imports(file.read_text(encoding="utf-8")):
            if spec.startswith("/static/js/"):
                resolved = spec[len("/static/js/") :]
            elif spec.startswith("."):
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
            else:
                continue  # bare / external specifiers are not ours
            if resolved.startswith(".."):
                violations.append(Violation(file, line, f"js import '{spec}' escapes the js root"))
                continue
            first = resolved.split("/")[0].removesuffix(".js")
            if own_dir and (resolved == own_dir or resolved.startswith(own_dir + "/")):
                continue
            if first not in allowed:
                violations.append(Violation(file, line, f"feature module may import only {allowed} (found '{spec}')"))
    return violations


def format_violations(vs: list[Violation], base: Path = RnD) -> str:
    def rel(p: Path) -> str:
        try:
            return str(p.relative_to(base))
        except ValueError:
            return str(p)

    return "\n".join(f"  {rel(v.path)}:{v.line}: {v.rule}" for v in vs)


# --------------------------------------------------------------------------------------------------------------
# The real tree


def test_engine_boundaries() -> None:
    cfg = load_config()
    violations, _ = scan_engine(ENGINE_DIR, cfg, legacy_names(RnD / "src"))
    assert not violations, "engine import boundary violations:\n" + format_violations(violations)


def test_engine_models_are_declared() -> None:
    cfg = load_config()
    on_disk = {p.name for p in ENGINE_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    assert on_disk <= set(cfg["models"]), f"undeclared models: {sorted(on_disk - set(cfg['models']))}"


def test_engine_has_no_model_cycles() -> None:
    _, graph = scan_engine(ENGINE_DIR, load_config(), legacy_names(RnD / "src"))
    assert find_cycle(graph) is None, f"import cycle between engine models: {find_cycle(graph)}"


def test_lab_package_boundaries() -> None:
    violations, graph = scan_lab(LAB_DIR, load_config())
    assert not violations, "lab import boundary violations:\n" + format_violations(violations)
    assert find_cycle(graph) is None, f"import cycle between lab packages: {find_cycle(graph)}"


def test_js_feature_boundaries() -> None:
    cfg = load_config()
    root = RnD / str(cfg["js"]["root"])
    if not root.is_dir():
        pytest.skip("lab/static/js does not exist yet")
    violations = scan_js(root, cfg)
    assert not violations, "js import boundary violations:\n" + format_violations(violations)


# --------------------------------------------------------------------------------------------------------------
# Scanner unit tests on fake trees

CFG: Config = {
    "defaults": {"stdlib": True, "third_party": ["numpy"], "engine": ["engine.core"]},
    "models": {
        "core": {"engine": []},
        "a": {},
        "b": {"engine": ["engine.core", "engine.a"]},
        "infer": {"third_party": ["numpy", "torch"]},
        "pipeline": {"engine": ["*"]},
    },
    "lab": {
        "only_importer_of": {"lab.api": ["lab.server"]},
        "packages": {
            "lab.store": {"may_import": [], "engine": []},
            "lab.jobs": {"may_import": ["lab.store"], "engine": []},
            "lab.api": {"may_import": ["lab.jobs", "lab.store"], "engine": []},
        },
    },
    "js": {"features_dir": "features", "feature_may_import": ["util", "api"]},
}
LEGACY = frozenset({"collision", "lab", "geometry"})


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def engine_rules(tmp_path: Path, files: dict[str, str]) -> list[str]:
    write(tmp_path, files)
    vs, _ = scan_engine(tmp_path, CFG, LEGACY)
    return [v.rule for v in vs]


def test_scanner_accepts_clean_tree(tmp_path: Path) -> None:
    rules = engine_rules(
        tmp_path,
        {
            "__init__.py": "",
            "core/__init__.py": "import math\nimport numpy as np\n",
            "a/__init__.py": "from engine.core import x\nfrom .sub import y\n",
            "a/sub.py": "from ..core import z\nfrom engine import core\n",
            "b/__init__.py": "from engine.a import q\n",
            "infer/__init__.py": "import torch\n",
            "pipeline/__init__.py": "from engine.b import w\nfrom engine import a\n",
        },
    )
    assert rules == []


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ("from engine.b import x\n", "may not import 'engine.b.x'"),
        ("from engine import b\n", "may not import 'engine.b'"),
        ("def f():\n    import collision\n", "legacy module"),
        ("if TYPE_CHECKING:\n    from lab.store import s\n", "legacy module / lab"),
        ("import torch\n", "third-party package 'torch'"),
        ("from ... import x\n", "escapes"),
    ],
)
def test_scanner_flags_violations(tmp_path: Path, body: str, needle: str) -> None:
    rules = engine_rules(tmp_path, {"__init__.py": "", "core/__init__.py": "", "a/__init__.py": body})
    assert any(needle in r for r in rules), rules


def test_scanner_flags_core_importing_a_model_and_undeclared_model(tmp_path: Path) -> None:
    rules = engine_rules(tmp_path, {"core/__init__.py": "from engine.a import x\n", "zzz/__init__.py": ""})
    assert any("may not import" in r for r in rules)
    assert any("not declared" in r for r in rules)


def test_scanner_reports_file_and_line(tmp_path: Path) -> None:
    write(tmp_path, {"a/__init__.py": "x = 1\n\nimport collision\n"})
    vs, _ = scan_engine(tmp_path, CFG, LEGACY)
    assert [(v.path.name, v.line) for v in vs] == [("__init__.py", 3)]


def test_cycle_detection() -> None:
    assert find_cycle({"a": {"b"}, "b": {"c"}, "c": {"a"}}) == ["a", "b", "c", "a"]
    assert find_cycle({"a": {"b"}, "b": set()}) is None


def test_engine_cycle_between_models(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "b/__init__.py": "from engine.a import x\n",
            "pipeline/__init__.py": "",
            "a/__init__.py": "from engine.b import y\n",
        },
    )
    _, graph = scan_engine(tmp_path, CFG, LEGACY)
    assert find_cycle(graph) is not None


def test_lab_rules(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "store/__init__.py": "from lab.jobs import j\nimport engine.pipeline\n",
            "jobs/__init__.py": "from lab.store import s\n",
            "api/__init__.py": "from lab.jobs import j\n",
            "feature.py": "import lab.api\n",
            "server.py": "import lab.api\n",
        },
    )
    vs, graph = scan_lab(tmp_path, CFG)
    rules = [v.rule for v in vs]
    assert any(
        "'lab.store' may not import 'lab.jobs.j'" in r or "'lab.store' may not import 'lab.jobs'" in r for r in rules
    ), rules
    assert any("may not import 'engine.pipeline'" in r for r in rules), rules
    assert any("only ['lab.server'] may import 'lab.api'" in r and "lab.feature" in r for r in rules), rules
    assert not any("found in 'lab.server'" in r for r in rules)
    assert find_cycle(graph) == ["lab.jobs", "lab.store", "lab.jobs"]


def test_lab_ignores_missing_packages(tmp_path: Path) -> None:
    write(tmp_path, {"other.py": "import json\n"})
    assert scan_lab(tmp_path, CFG)[0] == []


def test_js_scan(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "features/x.js": (
                "import { a } from './../util.js';\nimport b from './y.js';\nconst m = await import('../state.js');\n"
            ),
            "features/own/p.js": "import q from './q.js';\nexport * from '../../api.js';\n",
            "other.js": "import z from './features/x.js';\n",
        },
    )
    vs = scan_js(tmp_path, CFG)
    found = sorted((v.path.name, v.line) for v in vs)
    assert found == [("x.js", 2), ("x.js", 3)], [str(v) for v in vs]


def test_js_import_patterns() -> None:
    text = (
        "import a from './a.js';\nimport './side.js';\nexport { b } from './b.js';\n"
        "import('./c.js');\nconst s = 'import x';\n"
    )
    assert [s for _, s in js_imports(text)] == ["./a.js", "./side.js", "./b.js", "./c.js"]
