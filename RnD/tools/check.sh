#!/usr/bin/env bash
# The gate command for v26.3.0 workers. Runs in the hackeye-rnd-check image (hackeye-rnd + pinned ruff/mypy), from any cwd.
#
#   tools/check.sh [--files f1 f2 ...] [--tests t1 ...] [--related] [--full]
#
#   --files    files to check (default: changed vs the merge-base with v26.2 + untracked, relative to RnD/)
#   --tests    extra pytest targets (paths relative to RnD/, or node ids)
#   --related  also run the old tests/*.py that mention a top-level symbol defined in a changed legacy file
#   --full     also run the whole suite (--ignore=tests/e2e)
#
# Steps (stops at the first failure, full output):
#   1 ruff check + ruff format --check (tools/ruff-engine.toml) on the strict paths among the files
#   2 pyflakes-level ruff on the other changed .py files
#   3 mypy --strict (tools/mypy-engine.ini) on the strict files
#   4 pytest: --tests, always-tests (boundaries, field ownership, equivalence quick), --related, --full
set -euo pipefail

RND="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
files=(); tests=(); related=0; full=0; explicit=0
mode=""
for a in "$@"; do
  case "$a" in
    --files) mode=files; explicit=1 ;;
    --tests) mode=tests ;;
    --related) related=1; mode="" ;;
    --full) full=1; mode="" ;;
    -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) echo "unknown option $a" >&2; exit 2 ;;
    *) case "$mode" in
         files) files+=("$a") ;;
         tests) tests+=("$a") ;;
         *) echo "unexpected argument $a" >&2; exit 2 ;;
       esac ;;
  esac
done

cd "$RND"
if [ "$explicit" = 0 ]; then
  base="$(git merge-base HEAD v26.2 2>/dev/null || git merge-base HEAD main)"
  mapfile -t files < <({ git diff --name-only --relative "$base" -- .; git ls-files --others --exclude-standard; } | sort -u)
fi
rel=()
for f in "${files[@]}"; do
  p="$(realpath -m -- "$f")"
  p="${p#"$RND"/}"
  [ -f "$RND/$p" ] && rel+=("$p")
done

export CHECK_FILES="${rel[*]:-}" CHECK_TESTS="${tests[*]:-}" CHECK_RELATED="$related" CHECK_FULL="$full"
exec docker compose -f "$RND/tools/check.compose.yaml" run --rm --no-deps --build -e CHECK_FILES -e CHECK_TESTS -e CHECK_RELATED -e CHECK_FULL check tools/check_inner.sh
