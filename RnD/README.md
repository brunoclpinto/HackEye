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

**Default is the footage's native size and aspect ratio.** The GoPro clips in
`media/` are 3840x2160 (16:9, landscape); production's detector input is
512x896 (portrait). Letterboxing native footage into the production shape
would pad ~68% of the frame black and downscale content ~7.5x — see the plan
doc for the numbers. Don't do that unless you're deliberately reproducing app
geometry.

- (no flag) — native size, stride-32 aligned (2160 -> 2176, reported not silent)
- `--profile production` — pins 512x896 to reproduce app geometry exactly
- `--profile half` / `--profile third` — native aspect, scaled down for faster iteration
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
- **Segmentation**: Cityscapes 19-class *semantic* segmentation isn't a
  standard Ultralytics task, so this calls the checkpoint's underlying
  `nn.Module` directly for raw logits (`src/models.py:SegmentationModel`).
  **Unverified against the actual checkpoint** — `src/segmentation.py`
  raises a clear error if the channel count isn't 19, but a checkpoint whose
  forward pass does its own postprocessing, or outputs something structurally
  different, isn't guaranteed to be caught. Verify with `models/export.py`
  first.

## Cross-implementation parity (once you have both sides to compare)

Don't diff end-to-end output — the ONNX/PyTorch and INT8 CoreML models won't
produce identical tensors, so an end-to-end diff conflates model differences
with logic differences. Instead: dump a raw output tensor from the Apple CLI
for a few frames, feed that *same tensor* through
`src/segmentation.parse_grid` / `src/detect.parse_detections`, and compare
`result.json`. Exact match is the bar.
