#!/usr/bin/env bash
# Runs inside the gate container (cwd /rnd); called by tools/check.sh. Do not run directly.
set -uo pipefail
cd /rnd
read -r -a files <<<"${CHECK_FILES:-}"
read -r -a tests <<<"${CHECK_TESTS:-}"

strict=(); legacy=()
for f in "${files[@]}"; do
  case "$f" in
    *.py) ;;
    *) continue ;;
  esac
  case "$f" in
    src/engine/*|tests/engine/*|tests/test_module_boundaries.py|tests/test_field_ownership.py|tools/equivalence.py|tests/test_equivalence_*.py|lab/store/*|lab/jobs/*|lab/stages/*|lab/api/*) strict+=("$f") ;;
    *) legacy+=("$f") ;;
  esac
done

step() { echo; echo "=== $1"; }
fail() { echo; echo "CHECK FAILED at step: $1"; exit 1; }
summary=()

if [ ${#strict[@]} -gt 0 ]; then
  step "1a ruff check (strict) on ${#strict[@]} file(s)"
  ruff check --config tools/ruff-engine.toml --no-cache "${strict[@]}" || fail "ruff check"
  step "1b ruff format --check (strict)"
  ruff format --config tools/ruff-engine.toml --no-cache --check --diff "${strict[@]}" || fail "ruff format"
  summary+=("ruff check/format: ${#strict[@]} strict file(s) ok")
else
  summary+=("ruff check/format: no strict files, skipped")
fi

if [ ${#legacy[@]} -gt 0 ]; then
  step "2 pyflakes-level ruff on ${#legacy[@]} legacy file(s)"
  ruff check --isolated --no-cache --select F401,F403,F405,F811,F821,F822,F823 "${legacy[@]}" || fail "pyflakes (legacy)"
  summary+=("pyflakes: ${#legacy[@]} legacy file(s) ok")
else
  summary+=("pyflakes: no changed legacy files, skipped")
fi

if [ ${#strict[@]} -gt 0 ]; then
  step "3 mypy --strict on ${#strict[@]} file(s)"
  mypy --config-file tools/mypy-engine.ini "${strict[@]}" || fail "mypy"
  summary+=("mypy --strict: ok")
else
  summary+=("mypy: skipped")
fi

targets=("${tests[@]}" tests/test_module_boundaries.py tests/test_field_ownership.py)
[ -f tests/test_equivalence_quick.py ] && targets+=(tests/test_equivalence_quick.py)
if [ "${CHECK_RELATED:-0}" = 1 ] && [ ${#legacy[@]} -gt 0 ]; then
  mapfile -t rel < <(python - "${legacy[@]}" <<'PY'
import ast, re, sys
from pathlib import Path
names = set()
for f in sys.argv[1:]:
    for n in ast.parse(Path(f).read_text()).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
names = {n for n in names if len(n) >= 4 and not n.startswith("__")}
pat = re.compile(r"\b(" + "|".join(map(re.escape, sorted(names))) + r")\b") if names else None
for t in sorted(Path("tests").glob("test_*.py")):
    if pat and pat.search(t.read_text(errors="replace")):
        print(t)
PY
)
  targets+=("${rel[@]}")
fi
if [ "${CHECK_FULL:-0}" = 1 ]; then
  step "4 pytest: whole suite (--ignore=tests/e2e)"
  python -m pytest tests -q --ignore=tests/e2e || fail "pytest (full)"
  summary+=("pytest: full suite ok")
else
  mapfile -t targets < <(printf '%s\n' "${targets[@]}" | awk 'NF && !seen[$0]++')
  step "4 pytest: ${targets[*]}"
  python -m pytest "${targets[@]}" -q --ignore=tests/e2e || fail "pytest"
  summary+=("pytest: ${#targets[@]} target(s) ok")
fi

echo; echo "=== CHECK OK"
printf '  %s\n' "${summary[@]}"
