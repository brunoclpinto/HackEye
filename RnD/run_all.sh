#!/usr/bin/env bash
# Full-footage run across all clips in media/. See common/README.md and
# RnD/README.md for context. Not committed as project infra -- this is a
# one-off driver script for this specific run.
set -euo pipefail
cd "$(dirname "$0")"

for clip in GOPR4927 GP014927 GP024927; do
  echo "=== $clip ===" >&2
  docker compose run --rm -e PYTHONUNBUFFERED=1 rnd \
    --input "/media/${clip}.MP4" \
    --stage1-model /models/detector.pt \
    --seg-model /models/segmentation.pt \
    --target-fps 10 \
    --seg-min-pixel-fraction 0.0001089 \
    --no-original-png \
    --debug-destination /debug/full_run \
    --verbose --json > "/tmp/hackeye_run_${clip}.json" 2> "/tmp/hackeye_run_${clip}.log"
  echo "=== $clip done ===" >&2
done
echo "ALL CLIPS DONE" >&2
