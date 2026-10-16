# RnD — Linux GPU rig

A Python/Docker port of the HackEye detection pipeline (`Apple/HackEye-cli`),
for running on this Linux box against footage in `media/` since the
production app and its CoreML models are Apple-only.

See `/home/megabeast/.claude/plans/create-a-new-branch-sharded-orbit.md` (or
your copy of it) for the full reasoning. Short version: this exists because
`common/` as shared Swift code wouldn't have run here at all — no Swift, and
the models are CoreML-only. This is a second implementation of the pipeline
logic, not the shared core; `common/config/*.json` is the first (cheap) step
toward not letting it drift from the Swift side.

## Setup

```
cd RnD
docker compose build
docker compose run --rm rnd nvidia-smi   # confirm GPU passthrough works first
```

GPU is required, not optional — see `src/gpu_guard.py`. The pipeline exits
immediately if CUDA isn't available; there is no CPU fallback path anywhere
in this rig.

Put model checkpoints in `../models/` (see `models/README.md`) before running.

## Running

```
docker compose run --rm rnd \
  --input /media/GOPR4927.MP4 \
  --stage1-model /models/detector.pt \
  --seg-model /models/segmentation.pt \
  --verbose --json
```

Debug dumps land in `../debug/` (gitignored) in the same per-frame folder
layout as `Apple/HackEye-cli`'s `CLIDebugOutput`
(`frame_NNNN/{original.png,info.json,BusDetection/,BusTracking/,SafetySegmentation/}`),
so output is directly comparable to the macOS CLI's dumps.

## Input resolution — read this before drawing conclusions

**Default is 960px wide at the footage's native aspect ratio** (e.g.
1920x1080 or 3840x2160 -> 960x544; never upscaled). The GoPro clips in
`media/` are 3840x2160 (16:9, landscape); production's detector input is
512x896 (portrait). Letterboxing native footage into the production shape
would pad ~68% of the frame black and downscale content ~7.5x — see the plan
doc for the numbers. Don't do that unless you're deliberately reproducing app
geometry.

- (no flag) — 960px wide, native aspect, stride-32 aligned (540 -> 544)
- `--profile native` — native size, stride-32 aligned (2160 -> 2176, reported not silent)
- `--profile production` — pins 512x896 to reproduce app geometry exactly
- `--profile half` / `third` / `quarter` — native aspect, scaled down for faster iteration
- `--size WxH` / `--aspect W:H` — explicit override

**Caveat that doesn't go away with any flag:** this footage is landscape;
production framing is portrait (chest-harnessed phone or glasses). Findings
here are evaluated on a different framing distribution than what ships.
Consider a portrait center-crop profile if you need directly transferable
tuning — not implemented yet.

**`--seg-min-pixel-count` is resolution-sensitive.** It's an absolute
grid-cell count (default 50, matching the Swift app), but a fixed count means
a wildly different real-world object size on a native 4K grid vs the 512x896
production grid. Prefer `--seg-min-pixel-fraction` for anything other than
`--profile production`; the CLI warns loudly if you don't.

## What's verified vs. assumed

- **Detection**: uses Ultralytics' own `.predict()` (decode + NMS included).
  Reliable today.
- **Segmentation**: uses Ultralytics' own `.predict()` with task='semantic'
  (`src/models.py:SegmentationModel`). The safety mapping is picked by
  matching the checkpoint's class names against
  `common/config/safety_mapping*.json` (124-class Mapillary Vistas v2.0 ->
  `safety_mapping.json`; 48-class HackEye merge, e.g.
  `Yolo26m-sem-HackEye20261011.pt` -> `safety_mapping_hackeye48.json`), and
  loading fails if none matches. `src/segmentation.py` also raises a clear
  error if the channel count doesn't match, but a checkpoint whose forward pass does its own postprocessing, or
  outputs something structurally different, isn't guaranteed to be caught.

## Cross-implementation parity (once you have both sides to compare)

Don't diff end-to-end output — the ONNX/PyTorch and INT8 CoreML models won't
produce identical tensors, so an end-to-end diff conflates model differences
with logic differences. Instead: dump a raw output tensor from the Apple CLI
for a few frames, feed that *same tensor* through
`src/segmentation.parse_grid` / `src/detect.parse_detections`, and compare
`result.json`. Exact match is the bar.

## Lab (v26.1 — collision detection)

A web UI for researching production behaviour on this headless box: pick
footage from `media/`, analyse a time range with the segmentation model, then
play it back with the safety mask, walking corridor and collision hazards
drawn over the video, and hear the warnings (speech in clock notation —
12 = straight ahead, 9 = left, 3 = right — plus left/right-panned beeps that
speed up as an obstacle gets closer).

- **Open:** `https://megabeast.tail97a14.ts.net/` from any tailnet device
  (`tailscale serve` → `127.0.0.1:8765`). Fallback: `ssh -L 8765:localhost:8765 megabeast`
  and open `http://localhost:8765`.
- **Runs always:** compose service `lab` (`restart: unless-stopped`). The GPU
  model loads per job and is released after 5 min idle.
  `docker compose up -d lab` / `docker compose logs -f lab`.
- **Workflow:**
  1. Pick a recording and build its proxy (one-time 960p H.264 copy of all
     chapters back to back).
  2. Choose a range, model and fps, then click **Analyse**. Segmentation-only
     runs take ~20 ms/frame, so 1 min at 6 fps finishes in seconds.
  3. Play the result. Tap **Enable audio** first; iOS requires a tap.
  4. Change the mount preset or HFOV, then **Re-run collision**. This only
     re-runs the collision logic over the stored grids, with no new inference,
     so tuning takes seconds.
- **Code:**
  - `lab/CONTRACTS.md`: the spec — coordinates, JSON shapes, API.
  - `lab/server.py`, `lab/recordings.py`, `lab/analysis.py`: the backend.
  - `lab/static/`: the frontend (vanilla JS).
  - `src/collision.py`: the collision logic (pure; meant to be ported to Swift).
  - `../common/config/collision.json`: the tunable rules. Bump its `version`
    (`v26.1.x`) when behaviour changes.
- **Output:** everything goes under `../debug/lab/` (gitignored): proxies,
  runs (grids, masks, hazards/events), and per-recording settings.
- **Tests:** `docker compose run --rm --entrypoint python rnd -m pytest tests -q`
