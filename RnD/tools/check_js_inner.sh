#!/usr/bin/env bash
# Runs inside the js-check container (cwd /rnd, read-only mount); called by tools/check.sh when --files has .js/.mjs files.
set -uo pipefail
cd /rnd
read -r -a jsfiles <<<"${CHECK_JS_FILES:-}"
# v26.3.0 p6-05: any .js/.mjs change lints the whole front end + node tests (import/no-cycle needs the whole graph).
echo; echo "=== 5a eslint (tools/js/eslint.config.js, 0 errors / 0 warnings) on lab/static + tests/js (${#jsfiles[@]} changed file(s))"
eslint --config tools/js/eslint.config.js --max-warnings 0 lab/static tests/js || { echo; echo "CHECK FAILED at step: eslint"; exit 1; }
echo; echo "=== 5b node --test tests/js"
if [ -d tests/js ]; then
  node --test 'tests/js/**/*.test.mjs' || { echo; echo "CHECK FAILED at step: node --test"; exit 1; }
else
  echo "no tests/js directory, skipped"
fi
