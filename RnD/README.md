# RnD — Linux GPU rig

A Python/Docker port of the HackEye detection pipeline (`Apple/HackEye-cli`),
for running on this Linux box against footage in `~/media/hackeye/` (mounted at `/media`) since the
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
`~/media/hackeye/` are 3840x2160 (16:9, landscape); production's detector input is
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
  `Yolo26m-sem-HackEye26.1-48-1280.pt` -> `safety_mapping_hackeye48.json`), and
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
footage from `~/media/hackeye/`, analyse a time range with the segmentation model, then
play it back with the safety mask, walking corridor and collision hazards
drawn over the video, and hear the warnings (speech in clock notation —
12 = straight ahead, 9 = left, 3 = right — plus left/right-panned parking-sensor beeps that
speed up as a collision gets closer).

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
  3. Play the result. Audio is armed by default and unlocks on your first tap or
     key press anywhere on the page (iOS needs that tap); the button toggles it.
  4. Change the mount preset or HFOV, then **Re-run collision**. This only
     re-runs the collision logic over the stored grids, with no new inference,
     so tuning takes seconds.
  5. Review the notifications in the right-hand **Notification review** panel
     (v26.1.6): each row is a spoken phrase or a 🔔 beeps episode (a collision
     parking-sensor run). Mark it ✓ / ✗ / ⊘ with a note, or add a missed one
     (type speech or beeps, with an end time for beeps). "Hear review edits"
     plays your additions and skips what you marked ⊘ (including a beeps
     episode's tones). **Export** downloads the reviews as JSON (with `type`).
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
- **Browser E2E tests** (`tests/e2e/`, CONTRACTS section 13): Playwright (Python)
  in Docker, driving real Google Chrome (the bundled Chromium can't play the
  H.264 proxies) against the live Lab on `127.0.0.1:8765`.
  `tests/e2e/run.sh` (extra args go to pytest, e.g. `-k audio -x`).
  - Needs the `lab` service up and the test recordings (`HACKEYE_E2E_RECORDING`,
    default `Chest-center-0002`; `HACKEYE_E2E_SHORT_RECORDING`, default
    `Chest-center-0005`; missing proxies are built first). The session analyses
    the first 120 s of the long one itself and removes that run afterwards.
  - Tests that create review annotations delete exactly those ids afterwards.
  - The image is ~3.5 GB and not kept around. Pull it before the first run and
    remove it when done:
    `docker pull mcr.microsoft.com/playwright/python:v1.63.0-noble`
    `docker rmi mcr.microsoft.com/playwright/python:v1.63.0-noble`
    (`PW_TAG=...` selects another tag; Chrome is installed into the throwaway
    container on every run, about 20 s.)
  - Unit tests exclude it: `... pytest tests -q --ignore=tests/e2e`.

## Documentation
- [`lab/CONTRACTS.md`](lab/CONTRACTS.md): the current rules for the Lab and the collision logic.
- [`docs/DECISIONS.md`](docs/DECISIONS.md): the per-version decision log, covering user feedback, decisions, deviations, limitations and results.
- [`docs/plans/`](docs/plans/): the approved plan for each version.
- [`tests/fixtures/`](tests/fixtures/): the user's Lab reviews, kept as regression ground truth.

## Depth model

The Lab can estimate per-frame depth (`depth` in `POST /api/runs`; UI "Depth" select, default DA3 Small).
Only mobile-viable sizes are offered:

| Option | Model | Output | Licence |
|---|---|---|---|
| `da3-small` (default) | Depth Anything 3 Small, 0.08B | relative z-depth: the collision pass anchors it per frame to the flat ground and gait-calibrates the level | Apache-2.0 |
| `da3-base` | Depth Anything 3 Base, 0.12B | relative z-depth (as above) | Apache-2.0 |
| `da2-metric-outdoor-small` | Depth Anything V2 Metric Outdoor Small, 24.8M | metric metres | Apache-2.0 (fine-tuned on Virtual KITTI 2, CC BY-NC-SA 3.0) |
| `unidepth-v2-s` | UniDepth v2 ViT-S, ~34M; estimates the camera intrinsics itself | metric metres | **CC BY-NC 4.0** (non-commercial) |

What these licences require is summarised in [THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md).

DA3 Metric Large was removed from the Lab because it isn't mobile-sized. Runs made with it still load and are treated as metric.

**Weights** are not in the repo. Download them once into the shared models dir. The containers mount it read-only as `/base-models`, and `HACKEYE_DEPTH_MODEL_ROOT` (default `/base-models`) overrides the root that each variant's subpath (`depth-anything/…`, `unidepth/…`) is resolved under:

```bash
for v in SMALL BASE; do d=~/models/depth-anything/DA3-$v; mkdir -p $d && for f in config.json model.safetensors README.md; do curl -L -o $d/$f https://huggingface.co/depth-anything/DA3-$v/resolve/main/$f; done; done
d=~/models/depth-anything/DA2-METRIC-OUTDOOR-SMALL-hf; mkdir -p $d && for f in config.json preprocessor_config.json model.safetensors README.md; do curl -L -o $d/$f https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Outdoor-Small-hf/resolve/main/$f; done
d=~/models/unidepth/unidepth-v2-vits14; mkdir -p $d && for f in config.json model.safetensors README.md; do curl -L -o $d/$f https://huggingface.co/lpiccinelli/unidepth-v2-vits14/resolve/main/$f; done
```

The package is pinned in the `Dockerfile` (installed `--no-deps`; see the comments
there and in `requirements.txt`). The model is loaded on the first run that asks for depth and released with the
segmentation model when the worker goes idle.
