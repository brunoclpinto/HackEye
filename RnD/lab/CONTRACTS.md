# HackEye Lab — contracts (v26.3.0 layout, current rules)

History, user feedback and the reasons behind each rule: see `../docs/DECISIONS.md`.

This is the **Lab-level contract and the index of the model READMEs**: what crosses a package boundary (coordinates, storage layout, recordings and proxy, settings, analysis runs, the collision config, the `hazards.json` / `events.json` formats, the REST API, review storage, version-scoped content, testing). It describes how things work **now**; where the code and this text disagree, fix whichever is wrong in the same commit.

**What the Lab is:** a web UI on the headless R&D box (reached over Tailscale) that lets you pick footage from `~/media/hackeye/`,
analyse a time range with the segmentation model, then play it back with overlays plus collision-warning audio
(speech and parking-sensor beeps), and review every notification.

**Versions:** `v<YY>.<major>.<minor>`; v26.1 = collision detection. `RnD/VERSION` holds the current one (§11).

**How this document is organised (v26.3.0).** v26.3.0 split the monolith into independent packages: the engine models `src/engine/<model>/` (the Lab logic of the old `src/collision.py` and the flat modules), the Lab backend packages `lab/{store,jobs,stages,features,api}` (`lab/server.py` is the composition root; the flat `lab/*.py` modules are forwarding facades) and the front-end directories `lab/static/js/{util,app,features/*}` (`state.js`, `bus.js`). The section numbers below are unchanged, because tests and docs cite them ("CONTRACTS 12.2", "§13", "14.1.1", "§15"). What one model decides (most of §7, §8.1 and the per-panel parts of §9) now lives in **that model's README**, under the section "Contract rules moved from `lab/CONTRACTS.md`", with the old text kept verbatim; the heading stays here with a one-line summary and a link. A rule is documented in exactly one place.

**Boundaries are enforced.** `src/engine/BOUNDARIES.toml` lists, per engine model, which packages and third-party libraries it may import (only `engine.pipeline` imports other models), which engine models each Lab package may import, and the import rules of the front end (`[js]`); `tests/test_module_boundaries.py` fails the suite on a violation. Moving-code and facade rules: `src/engine/README.md`.

**Index**

| Model / package | README | Responsibility |
|---|---|---|
| `engine.core` | [`src/engine/core/README.md`](../src/engine/core/README.md) | Shared types, constants, geometry, config / settings loaders, clock / pose / distance-fusion helpers. |
| `engine.infer` | [`src/engine/infer/README.md`](../src/engine/infer/README.md) | GPU model wrappers: segmentation (letterbox, class grid), depth models, residual flow. |
| `engine.detection` | [`src/engine/detection/README.md`](../src/engine/detection/README.md) | Items (connected components with contact point, distance, bearing, clock) from a class grid. |
| `engine.surface` | [`src/engine/surface/README.md`](../src/engine/surface/README.md) | Walking region, horizon, surface-change and crosswalk trackers. |
| `engine.gait` | [`src/engine/gait/README.md`](../src/engine/gait/README.md) | Gait-calibrated metric scale `k`; GPS speed scale. |
| `engine.depthscale` | [`src/engine/depthscale/README.md`](../src/engine/depthscale/README.md) | Metric scale of the depth map: per-frame / plane / initial anchors, gait level, item depth. |
| `engine.groundfuse` | [`src/engine/groundfuse/README.md`](../src/engine/groundfuse/README.md) | Ground-fusion estimators: horizon jitter and range-correction curve. |
| `engine.egosignals` | [`src/engine/egosignals/README.md`](../src/engine/egosignals/README.md) | IMU / GPMF telemetry, heading, cadence and stationary signals. |
| `engine.egostate` | [`src/engine/egostate/README.md`](../src/engine/egostate/README.md) | Ego speed from witnesses; path-change (turn) detector. |
| `engine.tracking` | [`src/engine/tracking/README.md`](../src/engine/tracking/README.md) | Frame-to-frame matching, track velocities, coasting of movers. |
| `engine.motion` | [`src/engine/motion/README.md`](../src/engine/motion/README.md) | Movers' own motion: robust ego speed, approach / recede / still / side states, own velocity. |
| `engine.memory` | [`src/engine/memory/README.md`](../src/engine/memory/README.md) | Dead-reckoned pose and object permanence. |
| `engine.worldmap` | [`src/engine/worldmap/README.md`](../src/engine/worldmap/README.md) | Fused bird's-eye world map, face / edge test, static-map source, blocked-ahead. |
| `engine.worldtracks` | [`src/engine/worldtracks/README.md`](../src/engine/worldtracks/README.md) | Kalman world tracks (shadow mode). |
| `engine.roles` | [`src/engine/roles/README.md`](../src/engine/roles/README.md) | Role, urgency, collision and proximity flags of an item. |
| `engine.speech` | [`src/engine/speech/README.md`](../src/engine/speech/README.md) | Phrases and when they are said (policy, text, context, walls, movers). |
| `engine.sounds` | [`src/engine/sounds/README.md`](../src/engine/sounds/README.md) | Sound kinds / profile, collision beeps, proximity chirp, crosswalk tones. |
| `engine.output` | [`src/engine/output/README.md`](../src/engine/output/README.md) | The per-item `hazards.json` dict, outlines, lane polygon, region rows. |
| `engine.pipeline` | [`src/engine/pipeline/README.md`](../src/engine/pipeline/README.md) | The frame pipeline: `run_collision` as setup, 24 stages, finish; the only package that imports other models. |
| engine rules | [`src/engine/README.md`](../src/engine/README.md) | Moving-code rules, facade rules, typing, determinism checklist; import rules in `src/engine/BOUNDARIES.toml`. |
| `lab.store` | [`lab/store/README.md`](store/README.md) | Run docs, collision docs, request validation / run id, recordings scan and settings, model list, `JobContext`. |
| `lab.jobs` | [`lab/jobs/README.md`](jobs/README.md) | FIFO run queue, GPU worker, collision re-run job, proxy builder, version watcher. |
| `lab.stages` | [`lab/stages/README.md`](stages/README.md) | Model cache, frame reader, inference job, collision pass, world-map pass. |
| `lab.features` | [`lab/features/README.md`](features/README.md) | Reviews, notes, issues, sound profile, display mapping, A/B compare. |
| `lab.api` | [`lab/api/README.md`](api/README.md) | The REST routers; `lab/server.py` is the composition root. |
| front end (layout) | [`lab/static/js/README.md`](static/js/README.md) | Front-end layout, imports, bus event table, page layout (CONTRACTS §9). |
| js `library` | [`lab/static/js/features/library/README.md`](static/js/features/library/README.md) | Recordings list, proxy build, URL hash. |
| js `settings` | [`lab/static/js/features/settings/README.md`](static/js/features/settings/README.md) | Per-recording settings form, config overrides. |
| js `runs` | [`lab/static/js/features/runs/README.md`](static/js/features/runs/README.md) | Run list, analyse / follow / cancel, run badge. |
| js `collisions` | [`lab/static/js/features/collisions/README.md`](static/js/features/collisions/README.md) | Collision re-run job, rows, A/B compare. |
| js `transport` | [`lab/static/js/features/transport/README.md`](static/js/features/transport/README.md) | Playhead and player controls. |
| js `overlay` | [`lab/static/js/features/overlay/README.md`](static/js/features/overlay/README.md) | Video overlay layers and HUD. |
| js `hazards` | [`lab/static/js/features/hazards/README.md`](static/js/features/hazards/README.md) | Windowed hazards loader. |
| js `audio` | [`lab/static/js/features/audio/README.md`](static/js/features/audio/README.md) | Speech / tone playback. |
| js `sounds` | [`lab/static/js/features/sounds/README.md`](static/js/features/sounds/README.md) | Sound tuner. |
| js `worldmap` | [`lab/static/js/features/worldmap/README.md`](static/js/features/worldmap/README.md) | World-map panel. |
| js `timeline` | [`lab/static/js/features/timeline/README.md`](static/js/features/timeline/README.md) | Event timeline strip. |
| js `reviews` | [`lab/static/js/features/reviews/README.md`](static/js/features/reviews/README.md) | Review panel and add form / auto-fill (§9.1, §9.2). |
| js `classes` | [`lab/static/js/features/classes/README.md`](static/js/features/classes/README.md) | Classes & safety levels panel (§9.3). |
| js `issues` | [`lab/static/js/features/issues/README.md`](static/js/features/issues/README.md) | Open issues panel (§9.5). |
| js `notes` | [`lab/static/js/features/notes/README.md`](static/js/features/notes/README.md) | Notes panel (§9.4). |

**Contents:** 1 Coordinates · 2 Paths and storage · 3 Recordings and proxy · 4 Per-recording settings · 5 Analysis runs ·
6 Collision config · 7 Collision logic · 8 REST API · 9 Frontend · 10 Reviews · 11 Version-scoped Lab content · 12 Testing

---

## 1. Coordinates

Every position exchanged between backend, collision logic and frontend is **normalised to the original video frame**:
`x, y ∈ [0, 1]`, top-left origin, `x = col / W`, `y = row / H`.

The stored class grid has the letterbox padding **cropped off** and is resized (nearest-neighbour) so it maps 1:1 onto the
frame. There is no letterbox math outside `lab/stages/inference.py`.

**1a. Analysis window (v26.1.15 follow-up).** A run looks at the whole frame (landscape) or at a portrait window of it. Even then the stored grids, masks, depth maps, `hazards.json` and every position stay in **full-frame** coordinates at the same cell size (240 columns across the whole source): the window is a column range `[c0, c0+cols)` of the full grid and the cells outside it hold the class id **255 (`NO_DATA`)**, a transparent, never-surface, never-item cell (depth maps are NaN there). So bearings, clock, focal length, principal point, seed box and horizon are always those of the source lens ("real directions"), and the lane stays straight ahead. A full-frame run has no 255 cells and is byte-identical to before.

## 2. Paths and storage

`LAB_DIR` = env `HACKEYE_LAB_DIR`, default `/debug/lab` (host `HackEye/debug/lab`, gitignored).

```
LAB_DIR/
  .lab-version                   version marker (§11)
  proxies/<recId>.mp4            browser proxy (§3)
  proxies/<recId>.json           {"status","progress","error"} while building / after a failed build
  recordings/<recId>.json        per-recording settings (§4)
  sensors/<recId>.npz            v26.2.11: the recording's device telemetry (GoPro GPMF: gyro, accel, GPS, exposure; §7.17), built on the first collision pass that needs it (~1 s a clip); kept across version wipes like proxies/
  runs/<runId>/run.json          run metadata + status (§5)
  runs/<runId>/grids.npz         class grids (§5)
  runs/<runId>/motion.npz        ego-motion track at full source fps (§5)
  runs/<runId>/masks/<i>.png     overlay masks, i = 0..frameCount-1 (§5)
  runs/<runId>/depth.npz         metric depth maps 120×68, only for depth runs (§5)
  runs/<runId>/collisions/<cid>/hazards.json | events.json | worldmap.npz | collision.json
                                 one collision run `c<n>` of the analysis run (§5.1): collision output (§7.15), world map (§8.1), its settings / overrides / label
  reviews/<recId>.json           notification reviews / ground truth (§10)
  display/<mapping file>.json    saved Lab view: class→level/show and level colour/opacity overrides (§9.3); survives version wipes
  notes.json                     the user's freeform notes: reviews, remarks, fix requests (§9.4); survives version wipes
  notes.prev.json                the notes before the last save (one backup generation)
  issues-state.json              the user's close / reopen / comment per issue id (§9.5); survives version wipes
  .ultralytics/                  YOLO_CONFIG_DIR
```

- Media is read from `/media` (env `HACKEYE_MEDIA_DIR`), read-only. On the host it is `~/media/hackeye/` (compose env `HACKEYE_MEDIA_HOST_DIR`), outside the repo. Video extensions: `.mp4 .mov .m4v .mkv .avi`.
- Models: `/models/*.pt` and `/hackeye-models/*HackEye*.pt` (env `HACKEYE_MODELS_DIR`, `HACKEYE_RELEASES_DIR`). The default
  model is the `*HackEye*` release with the newest `HackEye<YYYYMMDD>` in its name (undated names rank last).
- Common config is under `find_common_dir()/config`.
- JSON files are written atomically (temp file + rename).

## 3. Recordings and proxy  (`lab/store/recordings.py`)

**GoPro chapter grouping:** `GOPRnnnn.MP4` is chapter 1 of recording `nnnn`, and `GPccnnnn.MP4` is chapter `cc+1`
(`GP01` → 2, `GP02` → 3, …). Any other video file in `/media` is its own single-chapter recording with `id = file stem`.
Chapters play back-to-back as one continuous timeline. Unreadable files are skipped (logged). Recordings are sorted by id.

```jsonc
// GET /api/recordings returns a list of these
{
  "id": "4927",
  "name": "GoPro 4927",              // "GoPro <id>" when chapter 1 is a GOPR file, else the id
  "chapters": [{"file": "/media/GOPR4927.MP4", "start": 0.0, "duration": 532.1, "frames": 12760}, ...],
  "duration": 1601.4,                // seconds, sum of chapter durations
  "width": 3840, "height": 2160, "fps": 23.976,      // of the first chapter
  "inputSizes": {"544p": [960, 544], "576p": [1024, 576], ...},   // model input [w, h] per offered resolution (§ run request); options that would upscale are omitted
  "inputSizesPortrait": {"544p": [544, 960], ...},                // the same for the portrait window (§5 Orientation)
  "nameHints": {"cameraLocation": "chest", "cameraSide": "center"},  // from a name <Location>-<side>-<nnnn>, else {}
  "proxy": {"status": "missing|building|ready|error", "progress": 0.0, "error": null}
}
```

- Width, height, fps and frame count come from `cv2.VideoCapture` properties (header only, no decode), cached per
  (path, mtime, size). **Chapter duration = `frames / fps`** (not the container duration), so the analysis reader can
  address a frame by index and land on the same `t` the proxy plays at.
- **Proxy:**
  - ffmpeg concat demuxer over the chapters, `-map 0:v:0 -map 0:a:0?`, `-vf scale=960:-2 -c:v libx264 -preset veryfast -crf 23 -g <round(fps)> -c:a aac -b:a 96k -movflags +faststart`.
  - Built in a background thread; progress is parsed from ffmpeg `-progress pipe:1` (`out_time_ms`, microseconds) over the total duration (capped at 0.999 until done).
  - Written to `<recId>.mp4.part` and renamed when done; a failed build removes the `.part` and reports `status: "error"` with the message.
  - A service restart during a build leaves no live build: status falls back to `missing`.
  - **Recording time `t` equals proxy time `t`.**
- `recording_frame_at(rec, t)` maps a recording time to (chapter file, time within that chapter); times past the end clamp to the last chapter's end.

## 4. Per-recording settings  (`LAB_DIR/recordings/<recId>.json`)

```jsonc
{
  "mount": "chest",            // key of collision.json mountPresets
  "hfovDeg": null,             // null = collision.json defaultHfovDeg
  "cameraHeightM": null,       // null = the mount preset's cameraHeightM
  "stepLengthM": null,         // null = the prior step length (collision.json ego.priorStepLengthM, 0.70 m)
  "projection": "auto",        // lens model for bearings/clocks and the depth focal: auto | rectilinear | fisheye (auto = fisheye when HFOV >= 100°)
  "distanceSource": "depth",   // ground | depth (§7.3a); without depth.npz depth behaves as ground
  "userHeightM": null,         // the user's full height; null = collision.json body.defaultUserHeightM (1.70)
  "cameraLocation": null,      // waist | chest | eye | head (body.cameraLocations); null = the legacy `mount` preset
  "cameraSide": "center",      // left | center | right
  "orientation": "landscape",  // landscape | portrait (§5 Orientation)
  "objectDistance": "depth",    // v26.2.3: depth | ground-contact | ground+depth (§7.3b); default = collision.json distance.objectDistance
  "useHorizon": true           // v26.2.3: false = no ground ray in any distance / map projection (§7.3b); default = distance.useHorizon
}
```

- Missing file = the defaults (`mount` = `defaultMount`, the rest null; **v26.1.15 follow-up:** `cameraLocation` and `cameraSide` default from a recording name `<Location>-<side>-<nnnn>` (`Chest-center-0004` → chest, center) when that location is in `body.cameraLocations`; `orientation` = `landscape`; a saved file wins, and `PUT {}` still resets to center / null). Unknown keys in a stored file (e.g. an old `corridor`) are ignored on read and dropped on write.
- `PUT` validates (422 otherwise) and stores:
  - `mount` must be a known preset (empty/missing = `defaultMount`)
  - `hfovDeg` null or a number in [10, 180)
  - `cameraHeightM` null or a number in [0.5, 2.5]
  - `stepLengthM` null or a number in [0.3, 2.0]
  - `userHeightM` null or a number in [1.0, 2.3]; `cameraLocation` null or a key of `body.cameraLocations`; `cameraSide` one of `left | center | right` (missing = `center`); `orientation` one of `landscape | portrait` (missing = `landscape`)
  - `projection` one of `auto | rectilinear | fisheye` (missing = `auto`); `distanceSource` one of `ground | depth` (missing = `depth`); `objectDistance` one of `depth | ground-contact | ground+depth` (missing = the config default `depth`); `useHorizon` a JSON boolean (missing = the config default `true`; 422 otherwise)
- **Body settings** (production asks the user once; camera, mounting height and angle are unknown): with a `cameraLocation`, camera height = `heightRatio × userHeightM + heightOffsetM` (waist 0.58, chest 0.72, eye 0.94, head 1.0 + 0.05 m), step length = `stepLengthRatio` (0.415) `× userHeightM`, horizon default from the location, and the side gives a lateral offset (`sideOffsetM`: 0.15 m waist/chest, 0.07 m eye/head; left −, right +). `cameraHeightM` / `stepLengthM` stay as explicit overrides. Without a location the legacy `mount` preset applies (offset 0). The Lab saves these on change.
- Step length is **never estimated from the footage**: steps are `distance / stepLength`, where the length is the stored
  value or the prior (§7.7).
- The Lab saves the settings before starting an analysis and before every collision re-run, so the post-inference collision pass always uses the stored settings.

## 5. Analysis runs  (`lab/stages/`, `lab/jobs/`; flat `lab/analysis.py` is a forwarding facade)

**Request:** `{"recording": "4927", "start": 60.0, "end": 120.0, "model": "/hackeye-models/Yolo26m-sem-HackEye26.1-48-1280.pt", "profile": "default", "fps": 6.0}`, plus the optional execution option `"device": "gpu" | "cpu"`, and `"orientation": "landscape" | "portrait"` with `"side": "left" | "center" | "right"`

- **Orientation and window** (v26.1.15 follow-up; `profiles.camera_window`): `landscape` (default) analyses the **full frame** exactly as before, whatever the side (the largest 16:9 window of a 16:9 source is the frame; the side then only moves the lane through the collision settings; alternative the user may revisit: a shifted full-size window with black padding). `portrait` analyses the **largest 9:16 window, full height**, `w = h·9/16` (4K 1215×2160, 2.7K 855×1520), placed by `side`: `left` x0 = 0, `center` x0 = (W−w)/2, `right` x0 = W−w. The window is scaled **evenly** (never stretched, never upscaled) with `short_side_spec` on the window (736p: 4K / 2.7K landscape 1280×736, portrait 736×1280); the only padding is the stride alignment, which the existing letterbox crop removes, so no vertical or extra padding exists. `side` is missing = the recording's saved Camera side. **Identity:** `orientation` and `side` enter the normalised request (hence the run id) **only for `portrait`**, so every landscape request and id is unchanged. Resolution that would need upscaling the window → 422. A portrait run's collision pass uses the run's own `side` (lane offset, window) instead of the recording's current one.

- `profile` ∈ `544p | 576p | 608p | 640p | 672p | 704p | 736p` (the inference **resolution** the UI offers) or the legacy `default | production | half | quarter` (accepted, not offered; missing = `default`). Stored as given (it is part of the run id). Passed to `profiles.resolve_input_spec(src_w, src_h, profile_or_None, None, None)`, `default` → `None`. The collision grid stays `GRID_W` = 240 wide regardless.
- **`Np` geometry** (`profiles.short_side_spec`): N is the padded **short side** of the model input; the aspect is the recording's native one and both input dimensions are multiples of 32. Landscape: content width `w` = the largest multiple of 32, `32 ≤ w ≤ src_w`, with `align32(round(src_h·w/src_w)) ≤ N`; content height `h = round(src_h·w/src_w)`; input `(w, align32(h))`. Portrait: the same with the axes swapped. Never upscaled: if N cannot be reached from the source's pixels, the request is a 422 (`RunError` with the reason) and the option is absent from the recording's `inputSizes`. For 1920×1080 (identical for 3840×2160):

  | profile | content | model input |
  |---|---|---|
  | 544p | 960×540 | 960×544 |
  | 576p | 1024×576 | 1024×576 |
  | 608p | 1056×594 | 1056×608 |
  | 640p | 1120×630 | 1120×640 |
  | 672p | 1184×666 | 1184×672 |
  | 704p | 1248×702 | 1248×704 |
  | 736p | 1280×720 | 1280×736 |

  A 1080×1920 portrait source gives the transposed sizes (544p → 544×960).
- `depth` ∈ `none | da3-small | da3-base | da2-metric-outdoor-small | unidepth-v2-s` (missing = `none`, 422 otherwise, including the removed `da3-metric-large`). The UI default is `da2-metric-outdoor-small`. Stored in the normalised request (and so in the run id) **only when not `none`**, so ids of depth-less requests are unchanged.
- `device` (missing/null = `gpu`; anything else → 422 `device must be one of ['gpu', 'cpu']`) says where the run executes. It is **not** part of the normalised request or the run id, so an identical finished run is reused whatever device is asked and existing ids are unchanged. A new run records it as the top-level run-doc field `"device"`; a reused run keeps the device it was recorded with; run docs without the field mean `gpu`.
- **Default model** offered by `GET /api/models`: `Yolo26m-sem-HackEye26.1-48-1280.pt` (`lab.store.constants.DEFAULT_MODEL`, env `HACKEYE_LAB_DEFAULT_MODEL`); if missing, the newest app release: versioned names (`…HackEye<ver>-…`) by version, then legacy dated names (`…HackEye<YYYYMMDD>…`). Dataset-creation models (`…-Vistas124-HackEye-…`) are listed but are never the fallback while an app release exists. The UI's default resolution is `736p`.
- `end` is clamped to the recording duration (the clamped value is stored and hashed). Must satisfy `0 ≤ start < end` and `0 < fps ≤ 60`. `model` must be one of `GET /api/models`. Violations → 422.
- **`runId`** = first 12 hex chars of sha1 over the canonical JSON (sorted keys, compact) of the normalised request **plus `"analysisVersion": 3`**, followed by `|<model file mtime>`. A finished run with the same id is reused.
- **`analysisVersion`** is 3: the run has an ego-motion track (`motion.npz`) that also carries `resid`, the residual image flow (§5, ego-motion track). 2 had no `resid`. `run.json` and the review annotations record it.

**One run per recording.** While any run of the **same recording** is `queued` or `running`, `POST /api/runs` returns
**409** `{"detail": "Analysis already running for <rec> (run <id>, <pct>%)"}`. An identical request returns that in-flight run
instead; an identical request for a done run returns the cached run with the response-only marker `"reused": true` (not stored in `run.json`). `"force": true` in the body re-runs a done / cancelled / failed run from scratch under the same id (partial outputs removed as on cancel, the recording's reviews untouched, the requested `device` used); a queued/running run is returned as is (no double run). Other recordings queue as usual (FIFO, one GPU job at a
time). A run.json left `queued/running` by a crashed process (no live entry) is redone. While a version cleanup is in progress
(§11) every submission is refused with 409.

**Per sampled frame** (times `start + k/fps`, `k = 0 … ceil((end − start)·fps) − 1`, i.e. `< end`; decoded sequentially,
crossing chapter boundaries; the stored `t` is the exact time of the source frame used):
1. BGR→RGB, then `letterbox_with_meta(rgb, spec.dst_w, spec.dst_h)`.
2. `SegmentationModel.predict_class_grid(...)` (it hands the RGB array to Ultralytics as BGR via `models.to_ultralytics`, because `predict()` assumes numpy input is BGR), then `grid_from_semantic_mask(class_ids, meta)`.
3. **Crop the padding:** keep rows `[round(pad_y), round(pad_y + src_h·scale))` and the matching columns. Resize nearest-neighbour to `GRID_W = 240` × `GRID_H = round(240·src_h/src_w)`, `uint8`.
4. Write `masks/<i>.png`: an RGBA image at grid size; pixel colour = `SAFETY_LEVELS[level]["color"]` with alpha 255; safety level 0 (ignored) is fully transparent.

**Depth pass** (only when the request has `depth`):
- Models (`src/engine/infer/depth/`, `DepthModel(device, variant).predict(rgb) -> (map, units)`; only mobile-viable sizes; licences in `THIRD_PARTY_LICENSES.md`):

  | Variant | Model | Units | Call |
  |---|---|---|---|
  | `da3-small`, `da3-base` | Depth Anything 3 Small / Base (Apache-2.0) | `relative` z-depth (larger = farther, one unknown scale); anchor `per-frame` | `model.inference([rgb], process_res=504)` (280×504 for 16:9) |
  | `da2-metric-outdoor-small` (**default**) | Depth Anything V2 Metric Outdoor Small (Apache-2.0; Virtual KITTI 2) | `metric` m, but biased (~2.2×) and very stable: anchor `plane` | transformers `AutoModelForDepthEstimation`, `post_process_depth_estimation` to the frame size |
  | `unidepth-v2-s` | UniDepth v2 ViT-S (CC BY-NC 4.0) | `metric` m; anchor `none` | `UniDepthV2.infer(rgb)` **without intrinsics**: it estimates the camera itself (production cameras are unknown); the estimate is logged once per run |

  Weights in host `~/models/{depth-anything,unidepth}/…`, mounted at `/base-models` (root overridable with `HACKEYE_DEPTH_MODEL_ROOT`); one variant cached, loaded on first use, released with the segmentation model. Metric Large is no longer offered.
- Per sampled frame, on the **un-letterboxed RGB frame** (true RGB).
- Resized to **120×68** (`INTER_AREA`), float16 → `depth.npz` (`depth` (N, 68, 120), `t` (N,), `units`), aligned 1:1 with `grids.npz`. Relative maps: non-finite / ≤ 0 → nan (floor 1e-3). Metric maps: clipped to [0.1, 200] m. `run.json` gets `"depth"` (variant or `"none"`), `"depthUnits"` and `"depthMsPerFrame"`. Older runs' `depth.npz` without `units` are metric metres.

**Ego-motion track:**
- For **every source frame** from the first sampled frame up to (not including) `end` — all ~24 fps, not only the sampled ones — convert to grayscale at 160×90 (`cv2.resize`, `INTER_AREA`, float32).
- `(sx, sy), _ = cv2.phaseCorrelate(prev, cur, hanning)`; store `dx = sx/160`, `dy = sy/90`: the image-content shift between consecutive frames, normalised to frame size. The first frame gets `dx = dy = 0`. The track continues across chapter boundaries.
- **Sign:** `dx > 0` = content moved right = the camera turned left. `dy > 0` = content moved down = the camera moved up.
- Skipped frames are decoded with `grab()` and `retrieve()`d only for this track; full-resolution conversion and inference happen only for sampled frames.
- **`resid`** (v26.1.11, `src/engine/infer/egoflow/`, the "is the user standing still" signal): per source frame, the Farneback dense flow (`cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 3, 15, 3, 5, 1.2, 0)`) between the 160×90 uint8 gray frame and the one **6 source frames (0.25 s) earlier**; over the textured pixels of the earlier frame (Sobel magnitude > 40; fewer than 300 of them = no verdict) the median magnitude of the flow **after subtracting its median** (the global shift: pan, tilt, bob), in px of the 160×90 frame. NaN for the first 6 frames and for bland frames (sky, plain wall, glare). Walking expands the picture and adds parallax (4929: median 2.7 px, 5–95 % 0.9–4.7); standing leaves the scene rigid, whatever the body does (308–346 s: median 0.12 px, 5–95 % 0.05–0.47).
- Output `motion.npz`: `t` float64 (M,) recording seconds, `dx` float32 (M,), `dy` float32 (M,), `resid` float32 (M,) (v26.1.11; absent in older runs: the collision logic then never sees a stationary user).

**`grids.npz`:** `grids` uint8 (N, GRID_H, GRID_W), `t` float64 (N,) recording seconds, `index` int32 (N,).

**`run.json`:**
```jsonc
{
  "id": "a1b2c3d4e5f6", "request": {...as above, normalised...}, "analysisVersion": 3,
  "status": "queued|running|done|error|cancelled", "progress": 0.0, "error": null,
  "createdAt": "2026-10-16T12:00:00Z", "finishedAt": null,
  "frameCount": 360, "motionFrames": 1439, "gridW": 240, "gridH": 135,
  "srcW": 1920, "srcH": 1080,
  "orientation": "landscape", "side": "center",   // side of a landscape run = the last one its lane offset was computed for
  "window": {"x0": 0, "y0": 0, "w": 1920, "h": 1080},   // analysed window, source pixels (the full frame for landscape)
  "gridWindow": null,                               // portrait: {"c0": 82, "cols": 76} on the 240-column grid
  "inputSpec": {"w": 960, "h": 544, "description": "..."},
  "modelName": "Yolo26m-sem-HackEye26.1-48-1280.pt",
  "classNames": ["animal", "barrier", ...],     // from the model, in id order
  "msPerFrame": 123.4, "seekSeconds": 0.3,
  "collisionVersion": "v26.1.13",                 // version of the last collision pass (the latest collision run's)
  "collisions": ["c1", "c2"], "collisionSeq": 2   // v26.2.8: the collision runs in creation order; the last id ever handed out (§5.1)
}
```

- After inference the runner immediately does a collision pass (§7) with the recording's current settings, then sets `done`. If the collision pass fails, it is logged and the run is still `done` (without hazards/events).
- `motion` is loaded from `motion.npz` when present (`t`, `dx`, `dy`, and `resid` if the file has it), else `None` (then ego estimates and the world memory are unavailable).
- `depth` is loaded from `depth.npz` when present, else `None`.
- `POST /api/runs/{id}/collision` makes a **new collision run** (§5.1) from `grids.npz` + `motion.npz` (+ `depth.npz`) with the recording's **current** settings (and optional config overrides); the analysis outputs are not touched. Since v26.2.10 it is a background job (§5.1 Job).

**5.1 Collision runs (v26.2.8).** A collision run is one collision result of an analysis run, shown as `<runId> · c<n>`; the user compares behaviours and results of several configurations of one analysis.
- **Ids:** `c1`, `c2`, ... sequential per analysis run, **never reused** (`collisionSeq` in `run.json`; a deleted or failed id stays burnt). Every re-run makes a new id, even with identical settings. The analysis job makes `c1` (collision pass, then its world map). The latest (last of `collisions`) is the default wherever no id is named. A forced re-analysis of a run starts clean (its `collisions/` folder is removed with the other outputs). A run without `collisions` has no collision run (the Lab says so).
- **Storage:** `runs/<runId>/collisions/<cid>/` = `hazards.json`, `events.json`, `worldmap.npz` and `collision.json`: `{"id", "runId", "createdAt", "collisionVersion", "worldmapVersion", "settings" (the stored recording settings used, as `GET .../settings` stores them), "resolved" (`hazards.json.settings` plus `distanceSource`, `projection`), "overrides" ({} when none), "label" (user text, <= 60 chars, default ""), "elapsedSeconds", "counts": {"speech", "beeps"}}`. Nothing collision-related is written at the run's top level.
- **Config overrides:** `POST /api/runs/{id}/collision` takes an optional body `{"overrides": {"collision": {"distance.itemLens": "off", ...}, "worldmap": {"gapCloseM": 0, ...}}, "label"?}`: dotted keys into `collision.json` / `worldmap.json`. Each key must exist in the loaded config, be a leaf (not a section) and keep its JSON type (number, bool, string, list); otherwise **422** naming the key, and no id is made. They are applied to in-memory copies for this pass only, and reach both the collision pass's online map (`run_collision(worldmap_config=...)`) and `worldmap_pass`; a later map rebuild of that collision run re-applies its stored `overrides`. The shipped configs are never mutated. v26.2.11: `collisions.PENDING_KEYS` lists the keys the Lab's controls send (`source.mode`, `speech.predictive.enabled`, `ego.headingSource`, `horizon.source`, `ego.cadenceSource`): while the config lacks one it is accepted (and created in the in-memory copy) when its value is an allowed one; once the config has it the normal type checks apply and the value must still be one of the allowed ones (422 otherwise). `collision.json` and `hazards.json` `settings` carry `objectDistanceEffective` (`groundfuse.resolved_mode`; also in `GET .../settings` `resolved`).
- **Reading:** every endpoint that reads a collision output (`events.json`, `hazards.json`, `hazards`, `frame`, every `/worldmap` endpoint, `POST /worldmap`) takes an optional query `collision=<cid>`; missing = the latest; unknown id, or a run with none, **404**. Server caches (hazards LRU, world-map cache) are keyed by `(runId, cid)`.
- **Compare:** `GET /api/runs/{id}/collisions/compare?a=<cid>&b=<cid>` -> `{"a", "b", "settings": [{"key", "a", "b"}], "counts": {"a", "b"}, "events": {"same": n, "changed": [{"t", "type", "a", "b"}], "onlyA": [...], "onlyB": [...]}}`. `settings` lists every differing dotted key of `settings.*`, `resolved.*` and `overrides.*`. Events are speech and beeps (tones left out). Greedy, nearest first, each event used once: same type and same text (beeps: same `kind` and `clock`) within **1.0 s** = same; else same type within 1.0 s with a different text = changed; the rest are only-A / only-B. Each listed event has `t`, `type`, `text` (beeps also `kind`, `clock`).
- **Job (v26.2.10):** `POST /api/runs/{id}/collision` returns at once with the new collision doc in `"status": "running"` and runs the collision pass, then the world map, in a background thread (pure numpy; never the GPU queue). `collision.json` gains `status` (`running` | `done` | `cancelled` | `error`), `progress` (0-1: the collision pass's frame loop is 0-0.4, the map pass 0.4-1.0) and `error` (null, or the message). The id is allocated and registered at the start, so the row exists while it runs; `GET .../collisions` reports the live `progress`. A `running` doc with no live job (the service died) reads as `error` (`interrupted`). Overrides are validated before the job starts (422, no id burnt). **One collision job at a time per Lab, and never together with an analysis:** a second job, or a re-run while an analysis is queued / running, is **409**; an analysis submitted during a job is refused (`RunConflict`, 409). `POST /api/runs/{id}/collisions/{cid}/cancel` sets the job's flag (checked between frames in both passes), waits up to 10 s and returns `{"cancelled": cid, "collisions": [...]}`: the cancelled directory is removed, the id leaves `collisions` and stays burnt (`collisionSeq`); 409 if that collision is not running; 404 unknown. A version wipe / `cancel_all` also cancels the job. The default (no `collision=`) never resolves to a collision that is not `done`; deleting a running one is 409 (cancel it); an `error` row can always be deleted. The analysis job's own collision pass stays synchronous (its `collision.json` is written `done`).
- **Delete:** `DELETE /api/runs/{id}/collisions/{cid}` removes the folder and the id from `collisions`; **409** for the only collision run of the run, and for one that reviews (verdicts or notes) reference (the message says how many).

**Cancellation:** `POST /api/runs/{id}/cancel`.
- A queued run is removed from the queue; a running one has a per-run cancel flag that the worker checks between frames. The run ends as `status: "cancelled"` and its partial outputs (`masks/`, `grids.npz`, `motion.npz`, `depth.npz`, `collisions/`) are removed; `run.json` stays.
- The reply waits up to 3 s for the end state and returns the run doc; 409 if the run is not queued/running; 404 if unknown.
- Cancelled and error runs are listed but cannot be played. Re-POSTing the same request starts it fresh.

**GPU:** one worker thread, FIFO queue. A `gpu` run (the default) calls `gpu_guard.assert_torch_cuda()` at job start; with no CUDA it fails as ever. A `cpu` run happens only when the request asks for it (never as a fallback): the models load on `torch.device("cpu")` and `torch.set_num_threads(HACKEYE_LAB_CPU_THREADS)` is applied (default `max(1, cpu_count - 2)`). One segmentation model (keyed by path + device) and one depth model (variant + device) are cached; asking for another device reloads. Models are released after `HACKEYE_LAB_IDLE_SECONDS` (default 300) without work, so the service holds no VRAM while idle.

## 6. Collision config  (`common/config/collision.json`, version `v26.2.3`)

Class names are the 48-class HackEye mapping's (`safety_mapping_hackeye48.json`). Names missing from a model's `class_names` are skipped (logged once). All distances are metres, times seconds, "steps" are walking steps (§7.7).

**Top level**

| Key | Default | Meaning |
|---|---|---|
| `version` | `"v26.1.16"` | Written into `hazards.json`, `events.json` and `run.json.collisionVersion`. |
| `defaultMount` | `"chest"` | Mount preset used when a recording has none. |
| `defaultHfovDeg` | `118` | Horizontal field of view when the recording has none. |
| `mountPresets` | see below | `label`, `horizon` (fallback horizon row, normalised y), `cameraHeightM`. |
| `minComponentFraction` | `0.0004` | Minimum size of an item component, as a fraction of the grid area (about 13 px at 240×135). |
| `personSplit` | `{"enabled": true, "classes": ["person", "rider"], "personWidthM": 0.55, "splitWidthFactor": 1.4, "splitDepthJumpM": 0.6, "minPieceM": 0.25, "valleyRows": 2, "valleyFrac": 0.08}` | v26.2.10 (§7.4): people that touch are separate items. `enabled: false` = one item per connected component as before. |
| `spokenLabels` | see below | Class name → spoken word. Unlisted classes are spoken as the class name with `-` replaced by a space. |
| `contextSpeak` | `["obstacle","building"]` | Spoken labels (after `spokenLabels`/`parkedLabels`) that may be announced as context. Other context items keep the role `context` (overlay) but stay silent. **Vehicles and parked cars are not in it** (v26.1.11): a vehicle is only ever spoken as a danger. |
| `parkedLabels` | `{"vehicle": "parked car"}` | Label for a moving-group item measured stationary. |

Mount presets: `chest` (horizon 0.45, camera height 1.30 m), `head` ("Head / helmet", 0.40, 1.65 m), `handheld` (0.50, 1.10 m).

Spoken labels: pole→pole, sign→sign, traffic-light→traffic light, traffic-light pedestrians→pedestrian light, traffic-sign→traffic sign, sidewalk-obstacle / barrier / barrier fence / barrier guard-rail / barrier wall→**obstacle**, divider→divider, nature vegetation→vegetation, building→building, person→person, rider→cyclist, vehicle→vehicle, animal→animal, curb→curb, crosswalk→crosswalk, object pothole→pothole, utility-cover→manhole. (Only labels in `contextSpeak` are ever spoken as context, so "wall", "fence" and "vegetation" are never announced.)

**`geometry`**

| Key | Default | Meaning |
|---|---|---|
| `defaultStepLengthM` | `0.70` | Fallback step length only if `ego.priorStepLengthM` is missing; also the Lab's placeholder text. |
| `laneHalfWidthM` | `0.60` | Danger lane: `abs(lateral) ≤` this. |
| `maxRangeM` | `30.0` | Items whose contact point is farther (or at/above the horizon) are dropped. |
| `horizonEma` | `0.05` | Smoothing factor of the per-frame horizon. |
| `horizonMaxStep` | `0.004` | The horizon moves at most this much (normalised y) per analysed frame. |
| `horizonValidRange` | `[0.25, 0.75]` | Raw horizon estimates outside this are rejected (preset used). |
| `minRegionRows` | `12` | Minimum valid region rows per side to fit a boundary line. |

**`surfaces`**

| Key | Default | Meaning |
|---|---|---|
| `groups` | `pedestrian` ("sidewalk": flat sidewalk, flat pedestrian-area, flat traffic-island), `bikeLane` ("bike lane": flat bike-lane), `road` ("road": flat road, flat road-shoulder, flat service-lane, flat driveway, parking), `rail` ("rail track": flat rail-track) | Surface groups: label + classes. |
| `inside` | crosswalk, curb, lane-line-dashed, continuous solid, marking-other, discrete stop-line, symbol bicycle, utility-cover, object pothole, void ground | Classes allowed inside the walking region besides the seed group's classes. |
| `seedBox` | `[0.40, 0.90, 0.60, 1.00]` | x0, y0, x1, y1: the majority surface class here picks the group. |
| `debounceSeconds` | `3.0` | Context and the start summary wait this long for a first adopted surface, no longer. |
| `minPersistSeconds` | `8.0` | A new surface must run uninterrupted this long, and the window must span at least this long. |
| `windowSeconds` | `10.0` | Sliding window for the surface majority. |
| `majority` | `0.7` | Share of the window's frames the new surface must hold. |
| `announceFirstSurface` | `false` | The first surface of a run is adopted silently. |
| `requireCrossingEvidence` | `true` | A change needs a curb/crosswalk that passed under the user. |
| `passUnderRows` | `6` | Bottom grid rows that count as "under the feet". |
| `passUnderGoneSeconds` | `1.5` | The curb/crosswalk track must be gone this soon after being under the feet. |
| `passUnderMinWidth` | `0.15` | Minimum bbox width (normalised) of that curb/crosswalk. |
| `evidenceLookbackSeconds` / `evidenceLeadSeconds` | `3.0` / `2.0` | Evidence counts if it happened no earlier than 3 s before the new surface's stretch began (flickers of up to 1.5 s bridged) and no later than 2 s after: a crossing causes the change, it does not merely coincide with a model that has read the other surface for seconds. |
| `announceGroups` | `["road","rail"]` | A change into or out of one of these is spoken; all other changes are silent. |

**`classes`**

| Key | Default | Meaning |
|---|---|---|
| `static` | pole, sign, traffic-light, traffic-light pedestrians, traffic-sign, sidewalk-obstacle, barrier, barrier fence, barrier guard-rail, divider, barrier wall, nature vegetation, building | Static obstacles. |
| `moving` | person, rider, vehicle, animal | Potential movers. |
| `feature` | curb, crosswalk, object pothole | Ground features. |
| `people` | person, rider, animal | Movers that are never treated as stationary (§7.8). |
| `thin` | pole, traffic-light, traffic-light pedestrians, traffic-sign, sign | Easy-to-miss objects, announced as a "poles" notice (§7.10). |
| `landmark` | crosswalk | Features announced once as a location marker. |

**`roles`**

| Key | Default | Meaning |
|---|---|---|
| `dangerSteps` | `10` | Static/vehicle danger needs `steps ≤` this. Also the far end of the drawn danger lane. |
| `finalSteps` | `3` | A collision-course danger at or within this many steps has urgency `final`. |
| `featureSteps` | `10` | Lane-crossing features (curb, pothole) need `steps ≤` this. |
| `contextMaxDistanceM` | `25.0` | Context only within this distance. |
| `contextMinAreaFraction` | `0.003` | Context needs a component at least this fraction of the grid. |
| `contextMaxSteps` | `8` | Context only within this many steps. |
| `contextMaxLateralM` / `contextNearSteps` / `contextNearLateralM` | `2.5` / `3.0` / `3.0` | Context only within this sideways distance (v26.1.13: 3.0 → 2.5, review 6), except right under us: within `contextNearSteps` the older `contextNearLateralM` still counts. The very first start summary admits any lateral. |
| `featureMinLaneCover` | `0.2` | A feature must cover this share of the lane's width at its contact row. |
| `alongPathRatio` | `0.5` | Near/far distance ratio of an item's base below which it "runs along the path". |
| `staticSource` | `"map"` | `"map"`: the online world map (§8.1) judges the wall-like classes of `mapJudgedClasses` (v26.2.2, face / edge test, §7.4) and keeps a static danger that left the bottom of the image (ghost); `"image"` = v26.2.0 exactly (A/B, the tests that pin the old behaviour). |
| `laneBaseClasses` | `["building"]` | Only for `staticSource: "image"`: the classes that get the v26.1.16 lane part. Under `"map"` the lane part is not emitted (v26.2.2: the map judges all wall-like classes, `mapJudgedClasses`). |
| `mapJudgedClasses` / `mapImageFallback` | `[building, barrier, barrier wall, barrier fence, barrier guard-rail, nature vegetation]` / `true` | The static classes the map judges alone (the image rule's lane hit is ignored). A judged item with no cell of its family in the corridor on its footprint falls back to the image rule. |
| `faceEdge.*` | see file | The face / edge test (§7.4): `enabled`, `maxAheadM` 12, wall line (`lineAheadM` 8, `lineMaxSideM` 4, `lineMinCells` 15, `lineMinSpanM` 2, `lineTrials` 80, `maxLineAngleDeg` 25, `seed`), `edgeBandM` 0.25 + `edgeBlurPerM` 0.02 x range, `faceProtrusionM` 0.3, cross orientation (`crossRadiusM` 0.5, `crossAngleDeg` 45, `crossElongation` 2, `crossMinCells` 6), `crossSideEdge`, `minFaceCells` 3. |
| `insideSolid.*` | `mode "snap"`, `solidDepthM` 0.8, `minRayCells` 3 | An item whose map position lies inside / behind solid wall-like cells is moved to the near border of the solid area (§7.4). `"suppress"` mutes it instead (A/B), `"off"` disables. |
| `coast.*` | `enabled`, 2 s (vehicles 3 s) | Movers that leave the image are predicted on their last world velocity (§7.4): `seconds`, `vehicleSeconds`, `histSeconds` 1, `minPoints` 3, `minSpanSeconds` 0.5, `maxSpeedMps` 15, `maxRangeM` 30, `rematchRadiusM` 2. |
| `mapMinConf` / `mapFootprintRadiusM` | `0.7` / `0.3` | A map cell counts when its fused confidence is ≥ 0.7 (about two frames); an item's cells are looked up within 0.3 m of its ground-base points. |
| `mapGhostMinConf` / `mapGhostSeconds` / `mapGhostNearM` | `0.3` / `2.0` / `2.0` | A confirmed static danger that is clipped, or within 2 m, when the image loses it is followed on the map for ≤ 2 s (cells of its family, fused confidence ≥ 0.3, anywhere in the corridor) until passed. |
| `laneBaseMinColumns` / `laneBaseMinRowColumns` / `laneBaseMinConcentration` / `laneBaseHoldSeconds` / `laneBaseMinClosingMps` / `laneBaseMinAgeSeconds` | `2` / `4` / `0.42` / `3.0` / `0.3` / `1.0` | Only for `staticSource: "image"` (the v26.1.16 lane part: base cells in ≥ 2 columns, a flat base, held 3 s, closing ≥ 0.3 m/s, track ≥ 1 s). |
| `minObstacleAreaM2` | `0.08` | A danger needs a component at least this large (real area at its distance). |
| `boundaryMarginPx` | `2` | Dilation of the walking region used for "touches the region". |
| `stationaryMps` | `0.5` | (Unused since v26.1.12: replaced by `standingMps` / `approachingMps` / `motionLeaveMps`, §7.8.) |
| `standingMps` / `standingHoldSeconds` | `0.3` / `1.0` | A mover is "standing" only with a ground speed along the line of sight below this, held this long without a break, and without sideways motion (§7.8). |
| `approachingMps` / `motionLeaveMps` | `0.4` / `0.3` | A mover whose ground speed toward the user reaches `approachingMps` is approaching (away: receding); it stays so down to `motionLeaveMps` (hysteresis). In between: unknown. |
| `standingMaxCrossMps` / `crossWindowSeconds` | `0.6` / `1.0` | A speed across the line of sight (bearing rate, §7.8) at or above this vetoes "standing"; window of the bearing-rate fit. |
| `motionSmoothSeconds` | `1.0` | Time constant of the EMA that smooths a track's speed along the line of sight before it is judged (a far person's depth closing swings 1.0 ↔ 4.0 m/s between frames). |
| `courseMinClosingMps` / `courseMaxSeconds` | `0.2` / `8.0` | A mover is on a collision course only if the gap closes at least this fast and we would meet within this time (§7.9). |
| `lateralVelDeadbandMps` / `lateralVelMaxMps` | `2.0` / `8.0` | A sideways velocity below the deadband is taken as 0 (it is noise: a standing pole reads 0.5 median, 1.4–2.4 m/s at the 90th percentile), above the cap it is clamped. |
| `confirmFrames` | `2` | A role must hold this many consecutive analysed frames before it is spoken or beeps. |
| `movingLaneHalfWidthM` | `3.0` | A rider or vehicle approaching is a danger when its predicted `\|lateral\|` at the meeting is within this (riders also now; vehicles only within `laneHalfWidthM + 1.0` now). |
| `proximitySteps` / `proximityLateralM` | `5` / `2.6` | The soft proximity sound (§7.13): a person / animal measured **approaching** (not unknown / standing / receding), within this many steps and this \|lateral\|, on no collision course. Riders and vehicles never (v26.1.13 follow-up). |
| `beepLateralM` | `0.9` | A collision course (the only thing that beeps): `\|lateral\|` (people standing / unknown) or the predicted `\|lateral\|` when we meet (measured movers) within this: the lane half-width 0.6 plus the body (v26.1.13, replaces `movingCollisionHalfWidthM` 1.5). |
| `peopleSpeakMinSteps` / `peopleSpeakLateralM` | `4.5` / `2.75` | People (person, animal) are spoken from 4.5 steps (the phrase says 5) up to `movingDangerSteps`, inside this sideways distance, whatever their direction; closer they only beep (§7.9, v26.1.13). |
| `fastWarnSeconds` / `fastWarnMaxM` | `6.0` / `30.0` | A rider / vehicle (`classes.fast`) approaching is announced when it would reach us within this many seconds (distance / closing) and is within `fastWarnMaxM`, whatever the steps (v26.1.13). |
| `egoMedianSeconds` | `3.0` | The motion states are judged against the median of the last 3 s of the cadence-based ego speed (v26.1.13). |
| `movingDangerSteps` | `10` | People are spoken up to this many steps (v26.1.12: 15 → 10, the same as static dangers). (`unknownMotionBeepSteps` is gone: unknown motion no longer beeps, v26.1.13.) |
| `landmarkSteps` | `15` | A crosswalk landmark is announced within this many steps. |
| `thinNoticeSteps` | `15` | Thin objects are noticed within this many steps … |
| `thinNoticeLateralM` | `2.5` | … and this sideways distance. |
| `fastApproachingMps` | `1.0` | v26.1.16 (§7.8): a rider / vehicle is `approach` / `recede` only from this own speed along the line of sight (people keep `approachingMps` 0.4); the leave level is 0.7× this. |
| `maxWalkingMps` | `2.0` | v26.1.16: a rider / vehicle may be called "approaching" on an unsettled ego speed only if `closing − maxWalkingMps ≥ approachingMps`. |
| `panSettleSeconds` | `1.0` | v26.1.16 (§7.5): after a hard camera pan (`tracking.panMatchMinShift`) the ego speed counts as unsettled for this long, so no motion words (the plain phrase, no people motion wait). |
| `contextAfterDangerSeconds` | `2.5` | v26.1.16 (§7.10): no context phrase within this time of a danger / final phrase or of a collision-beep stream (≥ 2 frames in a row). |

**`tracking`:** `iouMatch 0.2`, `maxMissedSeconds 1.0`, `historySeconds 2.0`, `groundGateLateralM 0.6`, `groundGateDistanceFrac 0.2` (match gate, §7.5); `motionMinRowsBelowHorizon 8`, `motionMinSeconds 0.75`, `peopleMotionMinSeconds 0.45` (closing speed needs a contact at least 8 grid rows below the horizon and ≥ 0.75 s of history; for people, riders and animals ≥ 0.45 s (v26.1.12: 4 samples at 6 fps), so a person who steps into view close by has a motion state when their phrase is due); `contactEma 0.5` (smoothing of a track's contact row). **v26.1.16:** `panMatchMinShift 0.04` (§7.5: the pan-compensated person match applies from this scene shift per frame, normalised x).

**`ego`**

| Key | Default | Meaning |
|---|---|---|
| `cadenceWindowSeconds` | `4.0` | Window of the cadence spectrum. |
| `cadenceBandHz` | `[0.8, 3.5]` | Search band for the step rate. |
| `cadenceMinPeakRatio` | `3.0` | Peak-to-rest amplitude ratio required. |
| `minStepHz` | `1.4` | A dominant peak below this is the stride; the step rate is its second harmonic. |
| `harmonicMinRatio` | `0.25` | A harmonic peak with this share of the fundamental's power counts as the step rate. |
| `speedMinTracks` | `1` | Minimum speed witnesses. |
| `speedMaxMps` | `6.0` | Witness closing speeds above this are ignored. |
| `speedEma` | `0.3` | Smoothing of the witness speed. |
| `stepLengthRangeM` | `[0.3, 1.8]` | Present in the file but not read by the code. |
| `calibrationWindowSeconds` | `20.0` | Window of the gait calibration. |
| `calibrationMinSamples` | `12` | Frames with cadence and raw speed needed for the first scale. |
| `calibrationEmaMinSeconds` / `calibrationEmaSeconds` | `3.0` / `40.0` | Time constant of the scale smoothing, growing with the evidence from the first to the second. |
| `priorStepLengthM` | `0.70` | Step length used for the calibration and for steps when the recording has none. |
| `scalePrior` / `scalePriorSeconds` | `null` / `30.0` | Optional warm-start scale (tests only); `null` = scale 1 until measured. |
| `scaleMaxChangePerSecond` | `0.25` | The applied scale moves toward the measured one by at most 25 % per second (log scale). |
| `scaleRange` | `[0.5, 4.0]` | Clamp of the scale. |
| `calibrationMinRawSpeed` | `0.2` | No scale from a raw speed below this (m/s). |
| `stationary` | `{medianSeconds 1.0, enterPx 0.8, leavePx 1.0, enterSeconds 1.5, leaveSeconds 1.0}` | The stationary-user state machine on `motion.resid` (§7.6). |

**`contextMemory`:** `forgetAfterSeconds 30.0` — a spoken context label is forgotten after this long unseen.

**`memory`** (world memory, §7.11)

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Master switch (it is also off whenever there is no motion data). |
| `matchRadiusM` / `matchRangeFraction` | `2.5` / `0.10` | Same object if within `radius + fraction × its distance`. |
| `radiusOverrides` | `{}` | Per label family override of `matchRadiusM`. |
| `maxRangeM` | `30.0` | Entries farther than this from the user are forgotten. |
| `behindM` | `-1.0` | Entries with "ahead" below this (behind the user) are forgotten. |
| `speedHoldSeconds` | `5.0` | The last speed is held this long when none is known. |
| `seenHoldSeconds` | `1.0` | An entry seen this recently is never forgotten. |
| `moverTakeoverSeconds` | `1.0` | A mover entry matches again only within this time of its last refresh. |
| `ownerAdoptSeconds` | `3.0` | A track that has shown an entry this long becomes its owner. |

**`pathChange`:** `headingDeg 20.0`, `sustainSeconds 2.0`, `referenceTauSeconds 30.0`, `onSurfaceChange false`.

**`speech`**

| Key | Default | Meaning |
|---|---|---|
| `globalMinGapSeconds` | `2.5` | Minimum gap between phrases (context and surface). |
| `priorityMinGapSeconds` | `1.0` | Minimum gap after the previous danger/feature phrase for the next danger/feature phrase. |
| `contextMaxDelaySeconds` | `3.0` | A context label that waited longer than this for the gap is dropped (treated as known). |
| `contextMaxItems` | `3` | Entries in one grouped context phrase. |
| `maxEntries` | `3` | Entries in one danger/feature/thin phrase. |
| `summaryHoldSeconds` | `0.5` | The start summary waits this long so the first view becomes one phrase. |
| `peopleMotionWaitSeconds` / `peopleMotionWaitSteps` | `1.5` / `6` | A person with unknown motion, farther than 6 steps, waits up to 1.5 s after becoming a danger so the phrase can say "approaching". |
| `thinRearmSeconds` | `8.0` | The thin notice re-arms after this long with no thin object noticed. |
| `featureLabelGapSeconds` | `6.0` | The same feature label is not repeated within this time … |
| `featureNewCrossingSteps` | `5` | … unless its position along the walk differs by at least this many steps. |
| `featureLabelOverrides` | `{"crosswalk": {"gapSeconds": 20, "newCrossingSteps": 20}, "curb": {"gapSeconds": 20, "newCrossingSteps": 24}}` | Per class override of the two above: a crosswalk / curb is said once per crossing (the far-side curb of a ~15-step crossing is the same crossing). |
| `templates` | see §7.10 | Phrase templates. |

**`tones`** (§7.13, §7.16): `bySteps [[5,0.5],[3,0.25],[2,0.12]]` ([steps, interval s]; v26.1.12: beeps start at 5 steps, speech carries the warning beyond), `continuousSteps 1.5`, `continuousChunkSeconds 0.25`, `maxSteps 5`, `holdSeconds 0.5`, `episodeGapSeconds 1.5`, `centerQuarters 1` (v26.1.16: the center sector is \|clock quarter\| ≤ 1, i.e. 11:45–12:15); `proximity` (the soft sound): `gain 0.25` (half the collision peak 0.5), `chirp {count 2, gapSeconds 0.1, attackSeconds 0.04}`; `crosswalk` (v26.1.14): `maxOffsetSeconds 0.3`, `in {gain 0.5, count 1, attackSeconds 0.03}`, `out {gain 0.5, count 2, attackSeconds 0.02}` (was `enter` / `exit`). **v26.1.16 — `sounds`** (the defaults of the Lab-wide sound profile, §7.16; pitch / duration / repeat interval per kind, replaces the old `frequencyHz` / `durationSeconds` / `proximity.{frequencyHz,intervalSeconds,durationSeconds}` / crosswalk frequency, duration and gap keys): `collision-left {pitchHz 660, durationMs 80, intervalS 0.5}`, `collision-center {880, 80, 0.5}`, `collision-right {1100, 80, 0.5}`, `crosswalk-in {330, 600, intervalS null}`, `crosswalk-out {330, 200, intervalS 0.12}` (the gap of its two tones), `proximity {440, 120, intervalS 1.2}` (the repeat period); each also has a `label` for the tuner. `speechRate 1.0`, `soundRanges {pitchHz [150, 2000], durationMs [20, 1500], intervalS [0.05, 5], speechRate [0.5, 2]}`.

**`crosswalk`** (v26.1.14, `_CrosswalkTracker`, §7.13): `class "crosswalk"`, `enterFraction 0.3`, `enterSeconds 0.5`, `exitFraction 0.15`, `exitSeconds 0.7`. The share is measured in `surfaces.seedBox`.

**Module constants** (in `src/engine/core/settings.py` and `src/engine/core/types.py`, `LABEL_COOLDOWN_S` in `src/engine/speech/policy.py`; not config): `WARMUP_S 1.5` (the horizon is the mean of the raw estimates until then; since v26.1.15 it silences nothing); `MIN_TRACK_AGE_S 0.5` (a track must be this old to speak or beep; **not during the first `WARMUP_S` of a run** since v26.1.15, where the 2-frame confirmation is the only gate); `HORIZON_HOLD_S 3.0` (the last good horizon is held this long when an estimate fails); `LABEL_COOLDOWN_S 5.0` (a danger label is not repeated within 5 s); `POINT_ASPECT 3.0` (speed witnesses are at least 3× taller than wide).

**Which model reads which key** (the config is one cross-model contract; the rules behind each key are in the owner's README, see the index at the top)

| Config section / keys | Owner (README) |
|---|---|
| `version`, `defaultMount`, `defaultHfovDeg`, `mountPresets`, `body`, `geometry.defaultStepLengthM` | `engine.core` (settings), `engine.pipeline` (the pass) |
| `minComponentFraction`, `personSplit`, `tree`, `classes` | `engine.detection` |
| `geometry` (lane, range, horizon), `horizon`, `surfaces`, `crosswalk` | `engine.surface` |
| `distance.*` (anchors, depth level, `objectDistance`, `useHorizon`, `itemLens`) | `engine.depthscale`, `engine.groundfuse` |
| `tracking`, `coast`, `distance.jump` | `engine.tracking` |
| `ego.*` (cadence, stationary, sensors, GPS) | `engine.egosignals`, `engine.gait`, `engine.egostate` |
| `pathChange` | `engine.egostate` |
| `motion`, `roles.standing*` / `approaching*` / `fast*` | `engine.motion` |
| `roles.*` | `engine.roles`; the map-related keys (`staticSource`, `mapJudgedClasses`, `faceEdge`, `insideSolid`, `map*`) `engine.worldmap` |
| `memory`, `contextMemory` | `engine.memory`, `engine.speech` |
| `worldTracks` | `engine.worldtracks` |
| `source`, `blocked` | `engine.worldmap` |
| `speech`, `spokenLabels`, `contextSpeak`, `parkedLabels` | `engine.speech` |
| `tones`, `beeps` | `engine.sounds` (`beeps.follow`: `engine.speech`; `beeps.passing`: `engine.roles`) |
| `output` | `engine.output` |

## 7. Collision logic  (`src/engine/`, one README per model; frame loop `src/engine/pipeline/`)

The rules of the collision pass are owned by the engine models; this section keeps the numbering and the `hazards.json` / `events.json` format (§7.15). The pass contract (pure logic, `run_collision` signature, frame order) is in [`src/engine/pipeline/README.md`](../src/engine/pipeline/README.md).

### 7.1 Walking region

The walking region: the surface group under the user's feet. Moved to [`src/engine/surface/README.md`](../src/engine/surface/README.md).

### 7.2 Horizon

The horizon estimated from the region bounds. Moved to [`src/engine/surface/README.md`](../src/engine/surface/README.md).

### 7.3 Geometry and the gait-calibrated scale

Pinhole geometry and the gait-calibrated scale `k`. Moved to [`src/engine/gait/README.md`](../src/engine/gait/README.md).

### 7.3a Distance source  (`distanceSource`; experiment)

Ground / depth distance sources, anchor modes, depth to metres. Moved to [`src/engine/depthscale/README.md`](../src/engine/depthscale/README.md).

### 7.3b Object distance and the horizon switch  (`distance.objectDistance`, `distance.useHorizon`; v26.2.3, `src/engine/groundfuse/`)

Object distance modes, the horizon switch and the lens ground. Moved to [`src/engine/groundfuse/README.md`](../src/engine/groundfuse/README.md).

### 7.4 Items

Items from the class grid; walls judged on the map, inside-solid, ghosts and coasting are in the worldmap and tracking READMEs. Moved to [`src/engine/detection/README.md`](../src/engine/detection/README.md); Moved to [`src/engine/worldmap/README.md`](../src/engine/worldmap/README.md); Moved to [`src/engine/tracking/README.md`](../src/engine/tracking/README.md).

### 7.5 Tracking

Greedy matching, pan-compensated person match, closing speed, track runs. Moved to [`src/engine/tracking/README.md`](../src/engine/tracking/README.md).

### 7.6 Ego motion

Cadence, stationary user and heading; speed witnesses and the ego speed. Moved to [`src/engine/egosignals/README.md`](../src/engine/egosignals/README.md); Moved to [`src/engine/egostate/README.md`](../src/engine/egostate/README.md).

### 7.7 Steps

`stepsTo` and how steps are spoken. Moved to [`src/engine/roles/README.md`](../src/engine/roles/README.md).

### 7.8 Moving vs. standing

Ground velocity, motion states, vehicles and people. Moved to [`src/engine/motion/README.md`](../src/engine/motion/README.md).

### 7.9 Roles  (one per item per frame)

Danger / feature / context / none, confirmation, no start silence. Moved to [`src/engine/roles/README.md`](../src/engine/roles/README.md).

### 7.10 Speech policy  (class `SpeechPolicy`)

One phrase per frame, priorities, gaps, templates, motion words, re-announcement. Moved to [`src/engine/speech/README.md`](../src/engine/speech/README.md).

### 7.11 World memory — object permanence  (class `_WorldMemory`)

Dead-reckoned pose and remembered objects. Moved to [`src/engine/memory/README.md`](../src/engine/memory/README.md).

### 7.11b World tracks — shadow mode  (`src/engine/worldtracks/`, `collision.json` `worldTracks`; v26.2.9)

Kalman world tracks; nothing feeds a decision. Moved to [`src/engine/worldtracks/README.md`](../src/engine/worldtracks/README.md).

### 7.11c Collision source and predictive speech  (`collision.json` `source`, `speech.predictive`; v26.2.11; `_map_source`, `_StaticMap.region`, `SpeechPolicy._compose`)

`source.mode` (image | map | track) in the worldmap README; predictive speech in the speech README. Moved to [`src/engine/worldmap/README.md`](../src/engine/worldmap/README.md); Moved to [`src/engine/speech/README.md`](../src/engine/speech/README.md).

### 7.11d v26.2.12 collision rules  (`collision.json`; all behind config keys, so every one can be A/B-ed through the re-run overrides and the v26.2.11 behaviour restored by switching them off)

Config-switchable v26.2.12-14 rules, each in the README of the model that owns it (defaults: pipeline; GPS step length: gait; trees: detection; distance jumps: tracking; voice, predictive, followed / known walls, moved away: speech; passing close: roles; own motion: motion; blocked: worldmap; whole component: output). Moved to [`src/engine/pipeline/README.md`](../src/engine/pipeline/README.md); Moved to [`src/engine/gait/README.md`](../src/engine/gait/README.md); Moved to [`src/engine/detection/README.md`](../src/engine/detection/README.md); Moved to [`src/engine/tracking/README.md`](../src/engine/tracking/README.md); Moved to [`src/engine/speech/README.md`](../src/engine/speech/README.md); Moved to [`src/engine/roles/README.md`](../src/engine/roles/README.md); Moved to [`src/engine/motion/README.md`](../src/engine/motion/README.md); Moved to [`src/engine/worldmap/README.md`](../src/engine/worldmap/README.md); Moved to [`src/engine/output/README.md`](../src/engine/output/README.md).

### 7.17 Device sensors  (`src/engine/egosignals/`, `lab/store/recordings.py` `sensors_for`, `collision.json` `ego.*` / `horizon`; v26.2.11)

GPMF gyro / accel / GPS, heading, cadence, gravity (egosignals); the one-pose rule (memory). Moved to [`src/engine/egosignals/README.md`](../src/engine/egosignals/README.md); Moved to [`src/engine/memory/README.md`](../src/engine/memory/README.md).

### 7.12 Path change

A turn: sustained heading change against a slow reference. Moved to [`src/engine/egostate/README.md`](../src/engine/egostate/README.md).

### 7.13 Beeps (parking-sensor)

Parking-sensor beeps, sound kinds, proximity chirp, crosswalk tones. Moved to [`src/engine/sounds/README.md`](../src/engine/sounds/README.md).

### 7.14 Surface  (class `_SurfaceTracker`)

Adopted-surface rules (majority, persistence, crossing evidence). Moved to [`src/engine/surface/README.md`](../src/engine/surface/README.md).

### 7.15 Output  (`hazards.json`, `events.json`)

**`hazards.json`**
```jsonc
{"version": "v26.1.13",
 "settings": {"mount": "chest", "hfovDeg": 118, "cameraHeightM": 1.3, "stepLengthM": null,
              "laneHalfWidthM": 0.6, "priorStepLengthM": 0.7,   // priorStepLengthM = the step length actually used
              "objectDistance": "depth", "useHorizon": true},   // v26.2.3 (§7.3b); the world map reads both
 "gridW": 240, "gridH": 135, "egoAvailable": true,                // egoAvailable = a motion track was used
 // portrait runs only: "window": {"c0": 82, "cols": 76, "x0": 1312, "y0": 0, "w": 1215, "h": 2160, "srcW": 3840, "srcH": 2160}
 "frames": [{
   "index": 0, "t": 60.0,
   "horizonY": 0.452, "horizonEstimated": true,
   "region": {"surface": "bikeLane", "label": "bike lane",
              "rows": [[0.70, 0.21, 0.83], [0.73, 0.18, 0.86], ...]},   // [y, left, right], every 4th grid row, bottom→top; this is the model's region of this frame
   "lane": [[0.41, 1.0], [0.59, 1.0], [0.53, 0.58], [0.47, 0.58]],    // danger-lane polygon, near→far at dangerSteps × step length
   "ego": {"speedMps": 1.32, "cadenceHz": 1.85, "stepLengthM": 0.7, "headingDeg": -3.2, "stationary": false,    // stationary: v26.1.11, speedMps is 0 while true
           "scale": 1.62, "scaleSource": "gait",                       // gait | prior | none
           "depthAnchor": 6.1, "depthScale": 7.3, "depthScaleSource": "gait",   // depthScale = c × anchor, metres per relative unit (null = unusable); gait | ground | metric | none
           "estimated": {"speed": true, "cadence": true, "stepLength": false}},
   "pathChange": false,
   "depthCorrection": {"ref": 1.45, "sigmaRows": 0.62, "curve": [[4.1, 1.0], [9.8, 0.98], [14.2, 0.7]]},   // v26.2.3 (§7.3b, objectDistance != depth): ref q, horizon jitter in rows, rho(depth m); the map reads it
   "faceEdgeLines": {"left": null, "right": {"a": 1.45, "b": -0.1, "angleDeg": -5.7, "n": 114}},   // v26.2.2: the fitted wall lines of the frame (right = a + b x ahead)
   "corridor": {"nearestM": 5.6, "nearestSteps": 8.0, "className": "pole"},   // v26.2.1 (staticSource "map"): the nearest object cell of the world map in the walking corridor, or null
   "hazards": [                                                        // all items, nearest first (by steps)
     {"trackId": 3, "className": "pole", "group": "static", "label": "pole", "role": "danger", "moving": false,
      "bbox": [0.48, 0.52, 0.55, 0.81], "contactY": 0.81, "bearingDeg": 4.1, "clock": 12, "clockText": "12:15", "pan": 0.07,
      "distanceM": 5.6, "depthM": 5.9, "lateralM": 0.21, "stepsTo": 8.0, "closingMps": 1.3, "urgency": "danger",
      "areaFrac": 0.012, "collision": true, "latVelMps": null,   // own sideways velocity (m/s, + = right, raw, before the deadband), null = unknown
      "crossMps": null,                 // speed across the line of sight from the bearing rate (m/s, + = right), null = unknown (v26.1.12)
      "distanceSource": "fused", "rawDepthM": 11.8, "groundM": 14.9,   // v26.2.3 (objectDistance != depth, depth runs): depth | ground | fused; the scaled depth before the correction; the ground ray in depth metres (null outside contact / band)
      "lanePart": true,                 // only present (and true) on the extra item of a wall/building whose base crosses the lane (§7.4; staticSource "image" only); track ids ≥ 1000000
      "source": "map", "mapCells": 12,  // v26.2.1 (staticSource "map", static items): "map" = judged on the world map (mapCells = cells in the corridor core), "image" = its contact point
      "imageDistanceM": 1.9, "imageLateralM": 1.9,   // only when the map measurement replaced the image's
      "faceEdge": {"verdict": "face", "face": 5, "edge": 1, "none": 0, "cells": 6, "nearestFaceM": 7.1, "lines": {"left": null, "right": {"a": 1.45, "b": -0.1}}, "faceCells": [[7.1, 0.3]], "edgeCells": []},   // v26.2.2: the face / edge test (§7.4) of a static item with corridor cells
      "insideSolid": true, "solidCorrected": true, "rawDistanceM": 9.1,   // v26.2.2: snapped to the near border of a solid area (§7.4)
      "coasting": true,                 // v26.2.2: a mover that left the image, predicted on its last world velocity (§7.4)
      "ghost": true,                    // only on a ghost (§7.4): the image lost the item, the map still holds it
      "outline": [[0.48, 0.52], [0.55, 0.52], [0.55, 0.81], [0.48, 0.81]]}
   ]}]}
```
- Top level also has `"projection"` (resolved), `"distanceSource"` and (v26.2.2) `"coast"`. `depthM` is present only when the run has depth (null for an item without valid depth pixels).
- `region` is null when there is no surface. `moving` is `true/false/null` for moving-group items (null = unknown), `false` otherwise. `closingMps` is null when unknown. `urgency` ∈ `none | danger | final`.
- `ego` fields are null when unknown. `estimated.stepLength` is always false.
- `outline` (items with `role != "none"` only): the outer contour of the item's own connected component, traced on the grid in pixel-corner coordinates (so its extent equals `bbox`), simplified with Douglas–Peucker (epsilon 0.75 grid px, growing ×1.25 until ≤ 32 points), concavities kept, normalised and rounded to 4 decimals. Pure numpy/scipy. Role `none` items carry no outline to keep `hazards.json` small.

**`events.json`** — sorted by `t` (speech before beeps before tones at equal `t`):
```jsonc
{"version": "v26.1.16", "events": [
  {"t": 61.2, "type": "speech", "role": "context", "text": "building at 2 in 6", "trackId": 5, "urgency": "none", "clock": 2, "pan": 0.48},
  {"t": 64.0, "type": "speech", "role": "danger", "text": "pole at 12 in 8", "trackId": 3, "urgency": "danger", "clock": 12, "pan": 0.07},
  {"t": 64.0, "type": "tone", "kind": "collision-center", "role": "danger", "trackId": 3, "urgency": "danger", "pan": 0.07, "frequencyHz": 880.0, "durationSeconds": 0.08},
  {"t": 64.0, "tEnd": 67.4, "type": "beeps", "kind": "collision-center", "role": "danger", "trackId": 3, "label": "pole", "clock": 12, "minSteps": 2.0,
   "urgency": "final", "text": "beeps · center · pole at 12 · 8→2 steps"},
  {"t": 78.2, "type": "tone", "kind": "proximity", "role": "danger", "trackId": 7, "urgency": "danger", "pan": 0.4, "frequencyHz": 440.0, "durationSeconds": 0.12,
   "gain": 0.25, "chirp": {"count": 2, "gapSeconds": 0.1, "attackSeconds": 0.04}},
  {"t": 78.2, "tEnd": 78.5, "type": "beeps", "kind": "proximity", "role": "danger", "trackId": 7, "label": "person", "clock": 1, "minSteps": 4.0,
   "urgency": "danger", "text": "soft · person at 1 · 4 steps"},
  {"t": 41.33, "type": "tone", "kind": "crosswalk-in", "role": "feature", "urgency": "none", "pan": 0.0, "frequencyHz": 330.0, "durationSeconds": 0.6,
   "gain": 0.5, "chirp": {"count": 1, "gapSeconds": 0.0, "attackSeconds": 0.03}},
  {"t": 41.33, "tEnd": 41.93, "type": "beeps", "kind": "crosswalk-in", "role": "feature", "urgency": "none", "text": "⇥ crosswalk in · one deep tone"}
]}
```
- Speech and beeps events carry `clockText` next to `clock` (the whole hour, kept for back-compat).
- Speech `role` ∈ `context | surface | feature | danger | final`; surface events have `trackId: null`, `clock: null`, `pan: 0`.
- `tone` events drive the audio; `beeps` events (one per episode) are what the review panel and the timeline use. The `beeps` `text` is `beeps · <left|center|right> · <label> at <clockText> · <first>→<min> steps` (`<n> steps` when equal; v26.1.16: the side is the sector of the kind), with the label/clock of the nearest moment; a `kind: "proximity"` episode starts `soft ·` instead of `beeps · <side> ·`. `kind` is `collision-left`, `collision-center`, `collision-right`, `proximity`, `crosswalk-in` or `crosswalk-out` on both event types (§7.13; runs made before v26.1.16 have `collision`, `crosswalk-enter`, `crosswalk-exit`, which the player and the review panel still understand); the crosswalk episodes have no track, label or clock.

### 7.16 Sound profile  (`lab/features/sounds.py`, `collision.resolve_sounds`; v26.1.16)

The Lab-wide sound profile and its REST endpoints. Moved to [`lab/features/README.md`](features/README.md).



## 8. REST API  (`lab/server.py` composition root, routers in `lab/api/`, FastAPI)

Endpoints are plain `def` (threadpool). JSON responses are gzip-compressed (`minimum_size=1024`) except `/media/*` and `*.png`. Errors are `{"detail": "..."}`.

| Method + path | Body / query | Returns |
|---|---|---|
| `GET /` | | `lab/static/index.html` (static files under `/static/*`); both send `Cache-Control: no-cache` (revalidated on every load, ETag keeps it cheap: browsers must not heuristically cache `app.js` / `js/*.js`) |
| `GET /api/version` | | `{"version", "since", "lastWipe"}` (§11) |
| `GET /api/recordings` | | `[Recording]` (§3) |
| `POST /api/recordings/{id}/proxy` | | proxy status; starts a build if missing/error |
| `GET` / `HEAD /media/{id}.mp4` | | the proxy file (Range requests); 404 if not ready |
| `GET /api/recordings/{id}/settings` | | Settings (§4) + `"resolved": {"hfovDeg", "projection", "cameraHeightM", "stepLengthM" (null = prior), "horizon", "userHeightM", "cameraLocation", "cameraSide", "lateralOffsetM", "objectDistance", "useHorizon"}` (from `collision.resolve_settings`) |
| `PUT /api/recordings/{id}/settings` | Settings | same as GET; 422 on invalid |
| `GET /api/config/collision` | | the contents of collision.json |
| `GET /api/models` | | `{"models": [{"path","name","default"}], "profiles": ["544p", ..., "736p"], "depthModels": ["none", "da3-small", "da3-base", "da2-metric-outdoor-small", "unidepth-v2-s"]}` (the resolutions the UI offers; legacy names are accepted by `POST /api/runs` but not listed) |
| `POST /api/runs` | run request (§5; optional `"device": "gpu"\|"cpu"`, default `gpu`; optional `"force": true`) | `run.json`; queued, or the existing in-flight run, or the done run with `"reused": true` (response only); `force` re-runs a finished run under the same id; 409 / 422 as in §5 |
| `GET /api/runs?recording=<id>` | | `[run.json]`, newest first (all runs without the query) |
| `GET /api/runs/{runId}` | | `run.json` |
| `POST /api/runs/{runId}/cancel` | | run doc (§5) |
| `POST /api/runs/{runId}/collision` | optional `{"overrides"?, "label"?}` (§5.1) | v26.2.8: makes a **new collision run** with the recording's current settings; v26.2.10: returns at once with its `collision.json` (`status: "running"`, `progress`) plus `"version"`, `"hazards"` and `"events"` links (`?collision=<cid>`) while a background job works; 409 if the run is not done, another collision job runs or an analysis is queued / running; 422 bad overrides / label; 503 if the collision module is missing |
| `POST /api/runs/{runId}/collisions/{cid}/cancel` | | v26.2.10: stops the running collision job; `{"cancelled", "collisions"}`; 409 not running, 404 unknown (§5.1 Job) |
| `GET /api/runs/{runId}/collisions` | | `[collision.json...]` in creation order (§5.1; v26.2.10: each with `status`, live `progress`, `error`) |
| `PATCH /api/runs/{runId}/collisions/{cid}` | `{"label": str <= 60}` | the updated `collision.json`; 404 unknown id, 422 bad label |
| `DELETE /api/runs/{runId}/collisions/{cid}` | | `{"deleted", "collisions"}`; 409 only one / has reviews (§5.1) |
| `GET /api/runs/{runId}/collisions/compare` | `a`, `b` | the A / B comparison (§5.1) |
| `GET /api/runs/{runId}/hazards.json` · `events.json` | `collision=<cid>` optional | the files of that collision run (default the latest; §5.1) (`Cache-Control: no-cache`). The UI uses only `events.json`. |
| `GET /api/runs/{runId}/hazards?from=<s>&to=<s>` | both required; `collision` optional | `{version, settings, gridW, gridH, egoAvailable, from, to, frames}`, the frames with `from ≤ t ≤ to`. 422 if `to < from` or the window is over 600 s |
| `GET /api/runs/{runId}/frame?t=<s>` | `collision` optional | `{"frame": ...}`, the analysed frame with the largest `t ≤ s`; 404 before the first frame or more than 1 s after the last |
| `GET /api/runs/{runId}/frames/{i}/mask.png` | | the mask PNG (`Cache-Control: max-age=86400`); fallback only |
| `GET /api/runs/{runId}/frames/{i}/classes.png` | | 8-bit grayscale PNG of `grids[i]` (positional, frame-aligned class ids), `Cache-Control: max-age=86400`; 404 unknown frame, 409 run not done. `grids.npz` cached for 2 runs, keyed by mtime |
| `GET /api/runs/{runId}/depth/{i}.png` | | 8-bit RGB PNG of `depth.npz[i]` (120×68): turbo colormap on log depth, **near = warm (red)** — relative depth normalised per frame between its 2nd and 98th percentile, metric depth over 0.5–30 m; `Cache-Control: max-age=86400`; 404 when the run has no depth or `i` is out of range |
| `GET /api/runs/{runId}/classes` | | `{mapping, classes: [{id, name, level}], levels: [{level, label, color, opacity}]}` from the safety mapping matching the run's `classNames` (`segmentation.find_mapping`, no GPU); default opacity 0 for level 0, else 1; 404 if no `classNames` or no mapping matches |
| `POST /api/runs/{runId}/worldmap` | `collision` optional | v26.2 step 1 spike (§8.1): builds `worldmap.npz` of that collision run (its stored overrides re-applied) from the stored files (since v26.2.6 the analysis job already builds it after the collision pass; the endpoint stays for re-builds), synchronously, pure numpy (never the GPU queue); `{"version", "elapsedSeconds", "frames", "msMean", "msP95", "worldmap": "/api/runs/<id>/worldmap?collision=<cid>"}`; 404 without `grids.npz` / `hazards.json`; 409 run not done |
| `GET /api/runs/{runId}/worldmap` | `collision` optional | `{"exists": false}` or `{"exists": true, "collision": "<cid>", "frames", "cellM", "origin": [col, row], "width", "height", "msMean", "msP95", "builtAt"}` (v26.2.7: `builtAt` = `worldmap.npz` mtime in ns, as a string) |
| `GET /api/runs/{runId}/worldmap/{i}.png` | `alpha=binary` (default) \| `conf` \| `gray` | the ego-centric snapshot of frame `i` (§8.1); 404 no map yet or unknown frame. Like `worldmap/cell` and `pose.json`, it takes an optional `collision` (§5.1) and an optional `v` (the map's `builtAt`; ignored by the server, it only defeats the browser cache) |
| `GET /api/runs/{runId}/worldmap/cell` | `i`, `col`, `row` | v26.2.4 (§8.1): one cell of snapshot `i`: surface and object layers, combined class, confidence, metres ahead / right |
| `GET /api/runs/{runId}/worldmap/pose.json` | `collision` optional | `{"t": [...], "pose": [[x, y, headingDeg], ...], "alignDeg": [...], "alignM": [...], "agree": [...]}` (v26.2.10: the map's own pose, the accumulated alignment correction in deg / m and the per-frame agreement, §8.1; the three arrays are absent for maps built before v26.2.10) |
| `GET /api/sounds` | | v26.1.16 (§7.16): `{kinds: [{kind, label, pitchHz, durationMs, intervalS, default: {…}}], speechRate, defaultSpeechRate, ranges, updatedAt}`: the defaults of `collision.json` `tones` merged with the saved overrides |
| `PUT /api/sounds` | `{"kinds": {kind: {pitchHz, durationMs, intervalS}}, "speechRate": 1.25}` | replaces the saved overrides (values clamped to `ranges`, values equal to the defaults dropped, an unused field such as `crosswalk-in.intervalS` ignored; no file when nothing is left); returns the view above. 422 for an unknown kind or a non-number |
| `DELETE /api/sounds` | | back to the defaults |
| `GET /api/display/{mapping}` | | `{mapping, classes, levels, saved}`: defaults merged with saved overrides, plus the raw saved file |
| `PUT /api/display/{mapping}/classes` · `/levels` | `{"classes": {...}}` or `{"levels": {...}}` | replaces that section's overrides (values equal to defaults are dropped; the file is deleted when both sections are empty); 404 bad mapping, 422 bad values |
| `DELETE /api/display/{mapping}/classes` · `/levels` | | resets that section to defaults |
| `GET /api/recordings/{id}/reviews` | | `{"recording", "annotations"}` sorted by `t` (§10) |
| `POST /api/recordings/{id}/reviews` | annotation | the stored annotation, 201 |
| `PUT /api/recordings/{id}/reviews/{annId}` | fields | the updated annotation |
| `DELETE /api/recordings/{id}/reviews/{annId}` | | 204 |
| `GET /api/reviews/export?recording=<id>` | omit the query for all recordings | the export (§10), always with the top-level `notes` and `issues` |
| `GET /api/issues` | | `{"updatedAt", "groups": [{id, title, openCount, items: [catalogue item + status, closedAt, note, noteUpdatedAt, userChanged]}]}` (§9.5) |
| `PUT /api/issues/{id}` | `{"status"?: "open"\|"closed", "note"?}` (note ≤ 4000 chars) | the item; 404 unknown id, 422 bad values |
| `GET /api/notes` | | `{"text", "updatedAt"}` (§9.4); `{"text": "", "updatedAt": null}` when there is no file |
| `PUT /api/notes` | `{"text", "baseUpdatedAt", "force"?}` | the saved doc; **409** `detail = {"message", "current": {text, updatedAt}}` when `baseUpdatedAt` is not the stored `updatedAt` (unless `force`); 422 for non-string text or over 100 000 characters |

- The windowed `hazards`/`frame` endpoints (a full-length run's `hazards.json` is ~120 MB) parse a collision run's `hazards.json` once, keep an LRU of 2 `(runId, cid)` entries and invalidate when the file's mtime/size changes. They return 409 if the run is not done and 404 if the collision run (§5.1) or its `hazards.json` does not exist.
- The collision pass calls `collision.resolve_settings(config, mount, hfovDeg, cameraHeightM, stepLengthM)` and `collision.run_collision(grids, times, class_names, config, settings, motion)`.
- Unknown recording or run → 404.

### 8.1 World map  (`src/engine/worldmap/`, `common/config/worldmap.json`, `lab/stages/worldmap.py` `worldmap_pass`; v26.2.0 spike, read by the collision pass since v26.2.1)

The fused bird's-eye map: geometry, layers, projection, fusion, facts-only, metrics. Moved to [`src/engine/worldmap/README.md`](../src/engine/worldmap/README.md).

## 9. Frontend  (`lab/static/`: `index.html`, `style.css`, `app.js`, `js/`; vanilla JS, no build step)

`app.js` only imports `js/app/bootstrap.js`. The layout of `lab/static/js/` (directories, wiring order, import rules, the bus event table) and the page layout rules are in [`static/js/README.md`](static/js/README.md). The behaviour of each panel is in its feature README:

| Panel / topic | README |
|---|---|
| Page layout, URL hash | [`lab/static/js/README.md`](static/js/README.md) |
| Library and proxy | [`lab/static/js/features/library/README.md`](static/js/features/library/README.md) |
| Analyse panel, runs list, run badge | [`lab/static/js/features/runs/README.md`](static/js/features/runs/README.md) |
| Collision settings | [`lab/static/js/features/settings/README.md`](static/js/features/settings/README.md) |
| Collision runs and compare | [`lab/static/js/features/collisions/README.md`](static/js/features/collisions/README.md) |
| Windowed hazards | [`lab/static/js/features/hazards/README.md`](static/js/features/hazards/README.md) |
| Overlay and HUD | [`lab/static/js/features/overlay/README.md`](static/js/features/overlay/README.md) |
| Transport | [`lab/static/js/features/transport/README.md`](static/js/features/transport/README.md) |
| World map panel | [`lab/static/js/features/worldmap/README.md`](static/js/features/worldmap/README.md) |
| Sound tuner | [`lab/static/js/features/sounds/README.md`](static/js/features/sounds/README.md) |
| Audio (speech, tones, client log) | [`lab/static/js/features/audio/README.md`](static/js/features/audio/README.md) |
| Timeline | [`lab/static/js/features/timeline/README.md`](static/js/features/timeline/README.md) |

### 9.1 Notification review panel  (`js/features/reviews/reviews.js`)

The notification review panel. Moved to [`lab/static/js/features/reviews/README.md`](static/js/features/reviews/README.md).

### 9.2 Add form and auto-fill  ("+ Add notification at playhead")

The add form and auto-fill. Moved to [`lab/static/js/features/reviews/README.md`](static/js/features/reviews/README.md).

### 9.3 Classes & safety levels panel  (`js/features/classes/classes.js`; view-only)

The classes and safety levels panel. Moved to [`lab/static/js/features/classes/README.md`](static/js/features/classes/README.md).

### 9.5 Open issues panel  (`js/features/issues/issues.js`, `lab/features/issues.py`, catalogue `lab/issues.json`; v26.2.4 follow-up)

The open issues panel. Moved to [`lab/static/js/features/issues/README.md`](static/js/features/issues/README.md).

### 9.4 Notes panel  (`js/features/notes/notes.js`, `lab/features/notes.py`; v26.2.4 follow-up)

The notes panel. Moved to [`lab/static/js/features/notes/README.md`](static/js/features/notes/README.md).

## 10. Reviews: storage, matching, export  (`lab/features/reviews.py`)

**Purpose:** ground truth for analysing and planning later collision versions. The user judges each notification while watching and adds notifications the system missed. **Reviews belong to the recording, not the run**: what should be notified at a recording time is stable across re-analysis. Each verdict snapshots the event it judged plus the `runId` and `collisionVersion` it came from.

**Storage** — `LAB_DIR/reviews/<recId>.json` (atomic writes; the file is deleted when its last annotation is removed; a process-wide lock serialises read-modify-write):
```jsonc
{"recording": "4929", "annotations": [
  {"id": "a1b2c3d4", "kind": "verdict",
   "verdict": "correct|incorrect|remove",          // remove = "should not be said" (kept, struck through, undoable)
   "note": "free text (<= 2000 chars, may be empty)",
   "t": 1089.84,                                    // = event.t
   "event": {"t": 1089.84, "text": "vehicle at 12 in 9", "role": "danger", "trackId": 1416, "urgency": "danger",
             "clock": 12, "type": "speech"},        // snapshot; a beeps event also has tEnd, label, minSteps; type "speech"|"beeps" (missing = speech); v26.2.12: also clockText and, for a predictive phrase, the whole `predicted` object ({dt, phraseS, dts, steps, clock, fwd, right, stepsNow, textNow}), so the export carries it
   "runId": "8ab9a0e06ae3", "collisionId": "c2", "collisionVersion": "v26.1.13", "analysisVersion": 3,
   "modelName": "Yolo26m-sem-HackEye26.1-48-1280.pt",
   "createdAt": "2026-10-16T13:00:00Z", "updatedAt": "2026-10-16T13:00:00Z"},
  {"id": "e5f6a7b8", "kind": "added",               // a notification the system should have made
   "type": "speech|beeps", "t": 1052.3, "tEnd": 1055.3,   // tEnd only for beeps, tEnd > t
   "text": "bench at 1 in 4", "role": "context|surface|feature|danger|final|other", "note": "",
   "runId": "8ab9a0e06ae3", "collisionVersion": "v26.1.7",     // what was loaded when it was made (optional)
   "createdAt": "...", "updatedAt": "..."}
]}
```
- `id`: 8 random hex characters, assigned by the server. `analysisVersion` and `modelName` are filled from the run's `run.json` for verdicts. An `added` annotation without `type` means speech.
- **Matching key** (verdict ↔ event of the loaded collision run): `(runId, collisionId, collisionVersion, round(event.t, 3), event.text)`; a review without `collisionId` (stored before v26.2.8) matches `c1`. Re-running collision with the same version reproduces identical events, so verdicts stay attached. At most one verdict per key: POSTing a second returns **409**; the client PUTs instead.
- **Earlier items count as correct (v26.2.14, user request):** `POST` of a verdict or an added item at time t on a collision run also creates `verdict: "correct"`, `auto: true` for every notification (speech / beeps / soft / crosswalk) of that collision run with t' < t that has no verdict (same request, same lock; the response carries `autoCreated`, the stored annotation does not). A `PUT` with `verdict` or `note` drops `auto`; deleting the later verdict keeps the auto ones; an auto ✓ the user removed comes back when a later item is reviewed again. The export carries `auto: true` (counted under `correct`). The panel shows auto rows lighter (`.rv-row.auto`, title "counted correct (reviewed later items)").
- `added` annotations are shown with every run of the recording, whatever their `runId`/`collisionId`/`collisionVersion`. **Verdicts are per collision run (v26.2.8):** the panel shows the verdicts of the selected collision run; the others sit under "Other versions" with their `collisionId`.
- ⊘ on a beeps episode silences that episode in "Hear review edits".

**Validation (422 unless noted):**
- `kind` ∈ `verdict | added`. `runId`, if given, must exist (404). `collisionId` (v26.2.8; default the run's latest) must be one of the run's collision runs (404); it is stored with the annotation.
- *verdict:* `verdict` ∈ `correct | incorrect | remove`; `runId` required; `event` required with `event.t` in `0..duration` and non-empty `event.text`; `event.type` ∈ `speech | beeps` if present; `event.tEnd` (if present) in `(t, duration]`. The annotation's `t` is `event.t`.
- *added:* `t` in `0..duration`; `text` required, non-empty, ≤ 300 chars; `role` ∈ `context | surface | feature | danger | final | other` (default danger); `type` ∈ `speech | beeps` (default speech); beeps need `tEnd` in `(t, duration]`; `tEnd` with speech is rejected.
- `note` ≤ 2000 characters.
- `PUT` accepts `note` and `verdict` (verdict annotations only) and `t`, `text`, `role`, `tEnd` (added annotations only). Unknown recording or annotation → 404.

**Export** (`GET /api/reviews/export`):
```jsonc
{"exportedAt": "...", "notes": {"text": "...", "updatedAt": "..."},   // the Notes panel (§9.4), also with ?recording=
 "issues": [ ...issues the user closed, reopened or commented (§9.5)... ],
 "recordings": [
  {"recording": "4929", "summary": {"correct": 3, "incorrect": 1, "remove": 1, "added": 2},
   "annotations": [ { ...annotation...,
      "collisionId": "c2", "settings": {...}, "resolved": {...}, "overrides": {...},   // v26.2.8: that collision run's collision.json (so a fixture keeps its config); collisionId is c1 for a review stored without one
      "context": {                                   // from the annotation's collision run; null if it has no runId or the run's data is gone
        "frameT": 1089.84,                           // nearest analysed frame
        "items": [ ...hazards items with role != "none"... ],
        "ego": {...}, "surface": "road", "surfaceLabel": "road", "horizonY": 0.43,
        "nearbySpeech": [ ...the run's speech events within ±3 s... ],
        "nearbyBeeps": [ ...beeps episodes overlapping t ± 3 s... ]
      } } ] } ]}
```

## 11. Version-scoped Lab content  (`RnD/VERSION`, `lab/jobs/versioning.py`)

The rule: **each new version cleans up the previous version's Lab content, so it starts fresh.**
- **Version source:** `RnD/VERSION` holds one line, the current HackEye version (e.g. `v26.1.7`). It is bumped in every version commit, together with `collision.json`'s `version`.
- **Marker:** `LAB_DIR/.lab-version` = `{"version": "...", "since": "<UTC ISO>"}`.
- **At Lab startup** (before serving) `apply_version_policy(lab_dir, version_file)` runs:
  - `VERSION` missing, unreadable or empty → log an error, do **nothing**. Never wipe on doubt. A corrupt marker also means do nothing.
  - Marker missing → write it with the current version, wipe nothing (first adoption).
  - Marker version == current → nothing.
  - Marker version != current → **wipe the contents** of `LAB_DIR/runs/` and `LAB_DIR/reviews/` (only entries directly inside them; symlinks are unlinked, never followed; a `runs/` or `reviews/` that is itself a symlink is refused), then rewrite the marker and log `[lab] version A -> B: removed N runs, M review files`. If the wipe fails part-way, the marker is kept so the next start retries.
- **Kept:** `proxies/`, `recordings/` (settings), `display/`, `notes.json` / `notes.prev.json`, `issues-state.json`, `client-log.jsonl`, `.ultralytics/`.
- **Result** dict: `{"previous", "current", "wiped": bool, "runsRemoved", "reviewFilesRemoved"}`.
- **`GET /api/version`** → `{"version", "since", "lastWipe": <result of the last check>}`. The UI shows the version in the page header.
- **Live check:** a background thread re-reads `RnD/VERSION` every 30 s. If it differs from the marker it (1) refuses new submissions and cancels every queued and running job, (2) waits up to 30 s for the worker to go idle, (3) releases the GPU model, (4) runs the wipe. If the worker doesn't go idle in time it logs an error, skips the wipe and retries on the next check. Submissions are accepted again afterwards.

## 12. Testing

**Unit tests** (no GPU, no model): `docker compose run --rm --entrypoint python rnd -m pytest tests -q --ignore=tests/e2e` (from `RnD/`).
- `tests/test_collision.py` — synthetic-grid scenes with real perspective geometry (camera height, horizon, objects placed at chosen ground distances) for every rule of §7.
- `tests/test_collision_v26111.py` — one synthetic test per v26.1.11 rule (cadence refine, stationary state machine and its effect, held ego speed, sideways velocity, collision course, unmeasured vehicles, motion-word phrases, one curb per crossing, surface evidence).
- `tests/test_collision_v26112.py` — one synthetic test per v26.1.12 rule (reach, beeps from 5 steps, the "approaching" re-announcement, motion states and the cross-view veto, unknown-motion beeps, earlier people motion, the pronunciation map) and the review-5 block on `4929_review5.{json,npz}` (one window 0–110 s).
- `tests/test_collision_v26113.py` — one synthetic test per v26.1.13 rule (people window and silent dangers, rider / vehicle early warning, beeps on a real collision course only, context lateral, robust ego speed, rider position) and the review-6 block on `4929_review6.{json,npz}` (one window 0–452 s with depth maps: every review-6 entry — ✓, ⊘, added, noted — has its assertion).
- `tests/test_collision_proximity.py` — the soft proximity sound (v26.1.13 follow-up): the rule (approaching person, 5 steps, 2.6 m, no riders / vehicles, none on a collision course), the sound events (440 Hz, gain, double chirp, fixed 1.2 s rhythm), the switch-over (collision beeps win, a track turning into a collision continues as beeps, hold time) and one assertion per review-6 beep entry (✓ and ⊘). In `test_collision_regression.py` the run helpers split the episodes by `kind` (`beeps` / `tones` = collision, `soft` / `softTones` = proximity) and `_produced` accepts a soft episode for a ticked beeps entry.
- `tests/test_collision_crosswalk.py` — the crosswalk sounds (v26.1.14): the `_CrosswalkTracker` state machine (enter hold, flicker, hysteresis, stripe gaps, standing still), the seed-box share, the tone / episode events and the overlap rule, then the real footage: `chest0002_crosswalk` (six windows, 11 enter / exit pairs, the 354.2 s single-frame flicker gives none) and `4929_review6` (8 pairs in 0–452 s).
- `tests/test_collision_v26116.py` — sound kinds by sector (boundaries 11:45 / 12:15 belong to the center), the profile in the tone events (pitch, duration, interval scaling, proximity period, crosswalk-out gap), rule 6 (danger beats notify-once), the pan-compensated person match, the vehicle state level, rule 9 (no context among dangers), the review-8 regression (`tests/fixtures/chest0004_review8.{json,npz}`, 0–155 s from the start of the run: 87 system events, 46 annotations) and the lane-vs-center-band numbers. `tests/test_lab_sounds.py` — the `/api/sounds` store.
- `tests/test_collision_v26115.py` — review 7 (v26.1.15): the settled-ego-speed rule (motion words, the people motion wait; riders / vehicles keep `approach`), no start silence, a danger not delayed by a feature phrase, and the `chest0004_review7` block (the person said once at 2.0 s, plain; nothing at 3.2 s; ✓ entries after the start kept).
- `tests/test_orientation.py` — the window rule for 4K / 2.7K in all six combinations, even scaling, the grid column range, true bearings of a window run equal the full-frame ones, NO_DATA exclusion, the window edges as horizon crops, the matched path byte-identical (golden hash of `chest0004_review7`), request / id / `run.json`, name hints and the orientation setting.
- `tests/test_collision_regression.py` — see below.
- `tests/test_versioning.py` (§11) and `tests/test_analysis_cancel.py` (§5 cancellation, one run per recording).
- `tests/test_collision_job_v26210.py` — the collision re-run job (v26.2.10): returns `running` at once, progress grows and it ends `done`; a second job and an analysis are refused (409 / `RunConflict`) while it runs, a running collision cannot be deleted; a re-run is refused while an analysis runs; Cancel removes the directory and the id is not reused; a failing pass leaves an `error` row (deletable); a `running` doc without a live job reads `error` / `interrupted`. Other tests that POST a re-run wait for `done`.
- v26.2.12 UI: `tests/test_lab_reviews_v26212.py` (a verdict's `event` keeps `predicted` and `clockText`, a non-object `predicted` is dropped; both reach the export), `tests/test_lab_sounds.py` (default rate 1.25, a stored default is no override); E2E `tests/e2e/test_v26212_ui.py` (repeat count and interval, predicted marker / two times / seek / request carries `predicted`, an item above the horizon is hit and selected through `bboxFull` / `outlineFull`, speech speed "(default)" follows the config; the sounds PUT is intercepted so the Lab-wide profile is untouched). The re-run form test picks, per control, a value that is not the config default.
- E2E (v26.2.10): `test_collision_runs.py` — a re-run shows the progress bar + Cancel in its row, Cancel leaves nothing and burns the id; a finished re-run is a row of its run's group with label (saved) and Delete (the group folds); the older collision-run tests drive the rows. `test_worldmap.py` — hover on a video item shows the tooltip, click selects it on the video and marks the same track on the map (readout led by `Selected:`), Esc / empty click clears; a click on a map item selects it on the video; a click on a wall cell with no item outlines the whole region (`data-sel-region`, hover tooltip). Helper `conftest.collision_job(run)` POSTs a re-run and waits.
- `tests/test_collision_runs.py` (§5.1: ids, storage, `collision=` reads, overrides validated / applied / reaching both map builders, compare, delete, reviews per collision run and the export) and `tests/e2e/test_collision_runs.py`.
- `tests/test_lab_device.py` (§5 `device`: parsing, run doc, id independence, model cache per device).

**Engine and Lab package tests (v26.3.0).** `tests/engine/<model>/test_*.py` test one engine model alone (see `src/engine/README.md`); `tests/test_module_boundaries.py` enforces `src/engine/BOUNDARIES.toml` (engine, Lab and `[js]` import rules); `tools/equivalence.py` compares the engine with the legacy implementation; `tests/js/**/*.test.mjs` test the pure front-end functions (`node --test`). The gate is `tools/check.sh` (ruff, mypy --strict, pytest, and for `.js` eslint + node tests).

**Regression fixtures** (`tests/fixtures/4929_review{1,2,3,4,5,6}.{json,npz}`, read-only): real-footage windows from recording 4929 (renamed `Chest-center-0002` in 2026-10; the fixtures keep the old name) plus the user's annotations. **`chest0002_crosswalk.{json,npz}`** (v26.1.14, no annotations): six windows of run `341fd5511f4d` (36–66, 136–160, 350–358, 384–410, 580–590, 1034–1056 s) with grids, times, 24 Hz motion and DA2 depth (float16, two mantissa bits cleared), run by the same `_run_windows` helper. **`chest0004_review7.{json,npz}`** (v26.1.15, review 7 on Chest-center-0004, run `180acf11eedb`, 1.2 MB): one window 0–20 s from the start of the run (so the cold start reproduces the run exactly) with grids, 24 Hz motion incl. `resid`, DA2 depth (float16, two mantissa bits cleared), the settings, the v26.1.14 system events (`systemEventsV26_1_14`) and the 6 annotations (4 ✓, 1 ⊘ at 3.17 s, 1 added at 2.0 s with the user's note).
- `.json`: `settings`, `classNames`, `windows` (`start`, `end`, `key`), `annotations` (the user's verdicts and added notifications, with the earlier version's events). `.npz`: per window `w<i>_grids`, `w<i>_t`, `w<i>_mt`, `w<i>_mdx`, `w<i>_mdy`.
- Windows — review 1: 0–10, 14–21, 27–31 s; review 2: 0–10, 28–42, 45–62, 70–80, 114–126 s; review 3: 0–12, 36–62, 100–122, 192–218 s (from run `7b9d5ac14e14`, 0–247 s); **review 4** (run `ffc2e6f0bd66`, 4929 full length, model `Yolo26m-sem-HackEye20261011.pt`, 736p, depth `da2-metric-outdoor-small`, plane anchor, v26.1.10): 20–50, 66–105, 150–205, 236–270, 284–345, 352–410, 436–470 s; **review 5** (run `2ced2e0f2909`, 4929 0–120 s, `Yolo26m-sem-HackEye20261011-1280.pt`, default 960w profile, **no depth maps**, v26.1.11): one window 0–110 s with grids and 24 Hz motion incl. `resid` (`systemEventsV26_1_11` holds what the user heard); **review 6** (run `36d9d120d801`, 4929 0–900 s, `Yolo26m-sem-HackEye20261011-1280.pt`, 736p, depth `da2-metric-outdoor-small`, v26.1.12, reviewed up to 449 s: 36 ✓, 10 ⊘, 2 added): **one window 0–452 s from the run's start** (the depth scale and ego state need the whole history: cold windows do not reproduce the run), grids, 24 Hz motion incl. `resid` and `w0_depth` with the two lowest mantissa bits cleared (21 → 27 MB; the 0–452 s events are reproduced unchanged); `systemEventsV26_1_12` holds what the user heard, `annotations` also holds the two `added` kinds. Review 4's `.npz` also holds `w<i>_depth` (68×120 float16, metric) and `w<i>_mresid` (the residual flow, computed from the video with `egoflow.py` because the run predates it); its `.json` has the 63 annotations (52 ✓, 2 ✗, 9 ⊘, with the user's notes) and `systemEventsV26_1_10` (every v26.1.10 event inside the windows).
- **Every window is run as its own cold sequence** (no earlier state: cadence needs ~2.4 s, the scale needs witnesses plus cadence; no memory of earlier phrases), so assertions are the ones that hold for any plausible scale and tie each phrase to the item that triggered it. Review 3 additionally runs a **warm** variant (`ego.scalePrior = 1.25`) and a variant with `memory.enabled = false`.
- The tests assert, among others:
  - the start summary names building/obstacle within the first seconds as one grouped phrase; no repeats after a turn (7.84, 40.50, 59.85, 118.66 s of review 3); no final at 41.17 s but the beeps are present; no surface event near 199.16 s (nor 120.83 s);
  - crosswalk landmark with direction and steps near 33.9 s; curb ahead and a poles notice near 38.8 s; a person phrase near 48.5–49.5 s and "person approaching at 12 …" near 75.5 s; no far context at 52.34, 55.51, 58.02 s;
  - no phrase contains "o'clock"; every object phrase has "at <clock>" and "in <n>" (surface excepted); step counts of a spoken track don't jump by more than 30 % between consecutive frames while walking;
  - beeps are collision tracks only and every tone belongs to exactly one episode; no danger/feature starts before confirmation; the ego scale is reported;
  - with the world memory the speech is a subset of the speech without it (surface aside); beeps and tones are identical with and without it;
  - every annotation the user confirmed (✓) is still produced (same text pattern, ±1.5 s) and none of the "should not be said" ones — except the listed deliberate moves (v26.1.12: movers beyond 10 steps and beeps beyond 5 steps left on purpose: `R4_BEYOND_REACH`, `MOVED_TICKS`, and the review 5 block of `test_collision_v26112.py`; v26.1.13: people under 5 steps and beeps outside 0.9 m: `R4_KEPT`, `MOVED_TICKS`, the lost-ticks list of `test_collision_v26113.py`).
- **Fixture grids are frozen model output.** The review 1–3 fixtures were extracted before the v26.1.9 channel-order fix, so they test the collision logic on that older segmentation, not current model behaviour.
- **Channel order** (`tests/test_channel_order.py`): `models.to_ultralytics` reverses RGB→BGR contiguously. Opt-in with `HACKEYE_GPU_TESTS=1` in the lab container, `SegmentationModel.predict_class_grid(rgb)` must equal Ultralytics' own file-loader prediction of the same image.
- Fixtures are extracted from a real run **before** a version bump, as for reviews 1–3; existing reviews' expectations are updated only for deliberate wording changes.

**Browser E2E harness** (`tests/e2e/`, `RnD/tests/e2e/run.sh`)
- Playwright (Python) in `mcr.microsoft.com/playwright/python:v1.63.0-noble` (`PW_TAG`), with the **Google Chrome channel** (`playwright install chrome`; plays H.264), against the live Lab (`--network host`, `LAB_URL`, default `http://127.0.0.1:8765`). Extra arguments go to pytest (`run.sh -k audio -x`).
- Needs the `lab` compose service running. **Test recordings (v26.1.14, one place: `conftest.py`):** `HACKEYE_E2E_RECORDING` (default `Chest-center-0002`, at least 125 s: its first 120 s hold two crosswalk crossings) and `HACKEYE_E2E_SHORT_RECORDING` (default `Chest-center-0005`, 88 s); a session fixture stops with a clear message if one is missing and builds missing proxies first; durations come from the API (`durations`, `clock`), nothing is hard-coded. **No user run is needed:** an autouse session fixture analyses the long recording 0–120 s at 6 fps once (about 30 s), shares it across tests, and deletes it at session end if the session created it (`run.sh` mounts `debug/lab` as `LAB_DIR_MOUNT`; needs bash ≥ 4.4).
- **Player queue tests (v26.1.15, `test_lab.py` `test_player_queue_*`):** a stubbed `speechSynthesis` (`QUEUE_STUB`: one active utterance, `onstart` after `startDelay`, `onend` after `dur`, `cancel()` reports `interrupted`) and a fresh `AudioEngine` in the page. Covered: a danger preempts a speaking context phrase at once while an equal one waits (no extra cancel), the priority order of the waiting phrases, a stale queued phrase is dropped (`speech-dropped-late`, audio log and client log; staleness is produced with the user audio offset because the video is paused), three preemptions in a row (also of utterances that never started) trigger neither the watchdog, nor `speech-stuck`, nor the notice, and a lost end event (`utt-lost`) does not block the queue. The default `HOOKS` stub now reports `onstart`/`onend` (10 / 150 ms) because the queue waits for the end of each phrase.
- Launch flag `--autoplay-policy=no-user-gesture-required`; page hooks `window.__spoken` (every `speechSynthesis.speak`), `window.__acs` (every AudioContext), `window.__osc` (every oscillator start: frequency and audio time) and the Lab's `window.__labAudioLog`.
- Covers: default full-length range, audio armed by the first gesture, add form time following (two adds at two paused times, with a long run loaded and a slow run load), auto-fill (also on a long run and a slow link), added phrases spoken after a rewind, ⊘ phrases not spoken, windowed hazards + gzip and the windowed endpoints, renamed labels and counts line, beeps rows (verdict save, ⊘ silences the episode's tones), the two sounds (a collision and a soft episode: two distinct frequencies scheduled with their gains, the panel shows the kind, the Beeps checkbox covers both), the crosswalk sounds (an enter and an exit episode: one 330 Hz oscillator, then two 0.32 s apart; rows `⇥ crosswalk in` / `⇤ crosswalk out`; ⊘ silences; the run's own enter / exit tones alternate and one plays while the video runs), adding a beeps entry and hearing it in the preview, timeline beep bars, beeps annotation validation, the Classes & safety levels panel (48 rows, unchecking a class removes its pixels, level colour/opacity repaint, persistence across reload, `mask.png` fallback, server save → fresh browser shows it → reset restores defaults).
- Tests create their own short runs/reviews (on the short recording or a short range of the long one) and delete them afterwards. They must **never trigger a version change**.
- `test_run_controls.py` (no session run needed): a short CPU-device run of the long recording shows Cancel and the progress bar, survives a reload mid-run, and Cancel ends it as `cancelled` and hides both.
- `test_eta.py`: `formatEta` / `EtaTracker` evaluated in the page (formats, estimating, stalled, mid-run fallback, no creeping up) and the progress label of a real run (follows a run already in flight read-only instead of queuing behind it).
- **Sound tuner tests (v26.1.16, `test_lab.py` `test_sound_tuner_*`, `test_the_test_button_*`, `test_pitch_and_duration_*`, `test_speech_speed_*`, `test_the_review_panel_shows_the_collision_sectors_*`, `test_apply_timing_*`):** the tuner is in `#main` with a row per kind; changes persist through `/api/sounds` and a reload; ▶ test starts an oscillator at the chosen frequency (`window.__osc`), crosswalk-out two tones `interval` apart; injected events are played at the profile's pitch by kind; the speech speed multiplies the utterance rate (the stub records `u.rate`); the review panel shows the sector rows and each sector plays its pitch; "Apply timing" re-runs the session's own run and leaves only the new kinds. `open_lab(..., profile=True)` keeps the page's profile; the default clears it (`window.__labAudio.setSounds({}, 1)`) so that older tests' injected frequencies are heard as written. Tests that change the profile reset it (`DELETE /api/sounds`) before and after.
