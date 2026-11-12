#!/usr/bin/env bash
# Staging Lab (compose project rnd-modular, 127.0.0.1:8775) built from this worktree.
#   tools/staging.sh up|seed|e2e|down|clean|status
# See RnD/README.md "Staging Lab". Never touches the live Lab: the live LAB_DIR is only read (seed).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RND="$(cd "$HERE/.." && pwd)"
MAIN_REPO="$(dirname "$(cd "$RND" && git rev-parse --path-format=absolute --git-common-dir)")"
export MAIN_REPO
export STAGING_LAB_DIR="${STAGING_LAB_DIR:-$MAIN_REPO/debug/lab-staging}"
LIVE_LAB_DIR="$MAIN_REPO/debug/lab"
PORT=8775
LONG="${HACKEYE_E2E_RECORDING:-Chest-center-0002}"
SHORT="${HACKEYE_E2E_SHORT_RECORDING:-Chest-center-0005}"
dc() { (cd "$RND" && docker compose -f compose.staging.yaml "$@"); }

case "${1:-}" in
  up)
    mkdir -p "$STAGING_LAB_DIR"
    dc up -d lab
    for _ in $(seq 60); do
      curl -sf "http://127.0.0.1:$PORT/api/recordings" >/dev/null && { echo "staging Lab up on :$PORT"; exit 0; }
      sleep 1
    done
    echo "staging Lab did not answer on :$PORT" >&2; dc logs --tail 30 lab; exit 1 ;;
  seed)
    mkdir -p "$STAGING_LAB_DIR"/{proxies,recordings,sensors}
    for r in "$LONG" "$SHORT"; do
      for f in proxies/$r.mp4 proxies/$r.json recordings/$r.json sensors/$r.npz; do
        if [ -f "$LIVE_LAB_DIR/$f" ]; then cp --update=none "$LIVE_LAB_DIR/$f" "$STAGING_LAB_DIR/$f"; echo "seeded $f"
        else echo "skip (not in live lab): $f"; fi
      done
    done ;;
  e2e)
    shift
    HACKEYE_E2E_LAB_DIR="$STAGING_LAB_DIR" LAB_URL="http://127.0.0.1:$PORT" "$RND/tests/e2e/run.sh" "$@" ;;
  down) dc down ;;
  clean) dc down; rm -rf "$STAGING_LAB_DIR"; echo "removed $STAGING_LAB_DIR" ;;
  status)
    dc ps
    echo "LAB_DIR: $STAGING_LAB_DIR"; ls "$STAGING_LAB_DIR" 2>/dev/null || echo "(absent)"
    curl -s "http://127.0.0.1:$PORT/api/version" || echo "not answering on :$PORT"; echo ;;
  *) echo "usage: $0 up|seed|e2e|down|clean|status" >&2; exit 2 ;;
esac
