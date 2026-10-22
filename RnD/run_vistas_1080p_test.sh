#!/usr/bin/env bash
# One-off test run of the Vistas-trained segmentation checkpoint
# (models/segmentation.pt == HackEye-Models/models/Yolo26m-sem-HackEye20261011-1280.pt)
# against the newly added 1080p clips in media/, at native 1080p and 1fps.
# Not committed as project infra -- mirrors run_all.sh's pattern for this run.
set -euo pipefail
cd "$(dirname "$0")"

for clip in GOPR4928 GOPR4929 GP014929 GP024929; do
  echo "=== $clip ===" >&2
  docker compose run --rm -e PYTHONUNBUFFERED=1 rnd \
    --input "/media/${clip}.MP4" \
    --stage1-model /models/detector.pt \
    --seg-model /models/segmentation.pt \
    --size 1920x1080 \
    --target-fps 1 \
    --seg-min-pixel-fraction 0.0001089 \
    --no-original-png \
    --debug-destination /debug/vistas_1080p_test \
    --verbose --json > "/tmp/hackeye_vistas_${clip}.json" 2> "/tmp/hackeye_vistas_${clip}.log"
  echo "=== $clip done ===" >&2
done
echo "ALL CLIPS DONE" >&2
