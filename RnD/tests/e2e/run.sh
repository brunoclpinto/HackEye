#!/usr/bin/env bash
# Browser E2E tests for the HackEye Lab (CONTRACTS section 13).
#
#   RnD/tests/e2e/run.sh                 # all tests
#   RnD/tests/e2e/run.sh -k audio -x     # extra args go to pytest
#   LAB_URL=http://127.0.0.1:8765 PW_TAG=v1.63.0-noble RnD/tests/e2e/run.sh
#
# Needs the `lab` compose service running (with the recordings' proxies ready:
# 4928, 4929, and the full run 7b9d5ac14e14 on 4929). The Playwright image is
# ~3.5 GB; pull it once with
#   docker pull mcr.microsoft.com/playwright/python:v1.63.0-noble
# and `docker rmi` it when you no longer need it. Google Chrome (not the
# bundled Chromium: it plays H.264) is installed inside the throwaway
# container on every run (~20 s).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG="${PW_TAG:-v1.63.0-noble}"
PWV="${TAG#v}"; PWV="${PWV%%-*}"   # python package version matching the image
docker run --rm --network host --ipc host \
  -e LAB_URL="${LAB_URL:-http://127.0.0.1:8765}" \
  -e PYTHONDONTWRITEBYTECODE=1 -e PWV="$PWV" \
  -v "$HERE:/e2e:ro" -w /e2e \
  "mcr.microsoft.com/playwright/python:$TAG" \
  bash -c 'pip install -q --root-user-action=ignore pytest playwright==$PWV 2>&1 | tail -2; python -m playwright install chrome >/tmp/chrome-install.log 2>&1 || { cat /tmp/chrome-install.log; exit 1; }; exec python -m pytest -p no:cacheprovider -v "$@"' _ "$@"
