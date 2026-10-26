# HackEye Lab — contracts (v26.1.16, current rules)

History, user feedback and the reasons behind each rule: see `../docs/DECISIONS.md`.

This is the single source of truth that `lab/server.py`, `lab/*.py`, `src/collision.py`, `common/config/collision.json`
and `lab/static/` are built against. It describes how things work **now**; where the code and this text disagree, fix
whichever is wrong in the same commit.

**What the Lab is:** a web UI on the headless R&D box (reached over Tailscale) that lets you pick footage from `~/media/hackeye/`,
analyse a time range with the segmentation model, then play it back with overlays plus collision-warning audio
(speech and parking-sensor beeps), and review every notification.

**Versions:** `v<YY>.<major>.<minor>`; v26.1 = collision detection. `RnD/VERSION` holds the current one (§11).

**Contents:** 1 Coordinates · 2 Paths and storage · 3 Recordings and proxy · 4 Per-recording settings · 5 Analysis runs ·
6 Collision config · 7 Collision logic · 8 REST API · 9 Frontend · 10 Reviews · 11 Version-scoped Lab content · 12 Testing

---

## 1. Coordinates

Every position exchanged between backend, collision logic and frontend is **normalised to the original video frame**:
`x, y ∈ [0, 1]`, top-left origin, `x = col / W`, `y = row / H`.

The stored class grid has the letterbox padding **cropped off** and is resized (nearest-neighbour) so it maps 1:1 onto the
frame. There is no letterbox math outside `analysis.py`.

**1a. Analysis window (v26.1.15 follow-up).** A run looks at the whole frame (landscape) or at a portrait window of it. Even then the stored grids, masks, depth maps, `hazards.json` and every position stay in **full-frame** coordinates at the same cell size (240 columns across the whole source): the window is a column range `[c0, c0+cols)` of the full grid and the cells outside it hold the class id **255 (`NO_DATA`)**, a transparent, never-surface, never-item cell (depth maps are NaN there). So bearings, clock, focal length, principal point, seed box and horizon are always those of the source lens ("real directions"), and the lane stays straight ahead. A full-frame run has no 255 cells and is byte-identical to before.

## 2. Paths and storage

`LAB_DIR` = env `HACKEYE_LAB_DIR`, default `/debug/lab` (host `HackEye/debug/lab`, gitignored).

```
LAB_DIR/
  .lab-version                   version marker (§11)
  proxies/<recId>.mp4            browser proxy (§3)
  proxies/<recId>.json           {"status","progress","error"} while building / after a failed build
  recordings/<recId>.json        per-recording settings (§4)
  runs/<runId>/run.json          run metadata + status (§5)
  runs/<runId>/grids.npz         class grids (§5)
  runs/<runId>/motion.npz        ego-motion track at full source fps (§5)
  runs/<runId>/masks/<i>.png     overlay masks, i = 0..frameCount-1 (§5)
  runs/<runId>/depth.npz         metric depth maps 120×68, only for depth runs (§5)
  runs/<runId>/hazards.json      collision output (§7.15)
  runs/<runId>/events.json       collision output (§7.15)
  reviews/<recId>.json           notification reviews / ground truth (§10)
  display/<mapping file>.json    saved Lab view: class→level/show and level colour/opacity overrides (§9.3); survives version wipes
  .ultralytics/                  YOLO_CONFIG_DIR
```

- Media is read from `/media` (env `HACKEYE_MEDIA_DIR`), read-only. On the host it is `~/media/hackeye/` (compose env `HACKEYE_MEDIA_HOST_DIR`), outside the repo. Video extensions: `.mp4 .mov .m4v .mkv .avi`.
- Models: `/models/*.pt` and `/hackeye-models/*HackEye*.pt` (env `HACKEYE_MODELS_DIR`, `HACKEYE_RELEASES_DIR`). The default
  model is the `*HackEye*` release with the newest `HackEye<YYYYMMDD>` in its name (undated names rank last).
- Common config is under `find_common_dir()/config`.
- JSON files are written atomically (temp file + rename).

## 3. Recordings and proxy  (`lab/recordings.py`)

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

## 5. Analysis runs  (`lab/analysis.py`)

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
- **Default model** offered by `GET /api/models`: `Yolo26m-sem-HackEye26.1-48-1280.pt` (`analysis.DEFAULT_MODEL`, env `HACKEYE_LAB_DEFAULT_MODEL`); if missing, the newest app release: versioned names (`…HackEye<ver>-…`) by version, then legacy dated names (`…HackEye<YYYYMMDD>…`). Dataset-creation models (`…-Vistas124-HackEye-…`) are listed but are never the fallback while an app release exists. The UI's default resolution is `736p`.
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
- Models (`src/depth.py`, `DepthModel(device, variant).predict(rgb) -> (map, units)`; only mobile-viable sizes; licences in `THIRD_PARTY_LICENSES.md`):

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
- **`resid`** (v26.1.11, `src/egoflow.py`, the "is the user standing still" signal): per source frame, the Farneback dense flow (`cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 3, 15, 3, 5, 1.2, 0)`) between the 160×90 uint8 gray frame and the one **6 source frames (0.25 s) earlier**; over the textured pixels of the earlier frame (Sobel magnitude > 40; fewer than 300 of them = no verdict) the median magnitude of the flow **after subtracting its median** (the global shift: pan, tilt, bob), in px of the 160×90 frame. NaN for the first 6 frames and for bland frames (sky, plain wall, glare). Walking expands the picture and adds parallax (4929: median 2.7 px, 5–95 % 0.9–4.7); standing leaves the scene rigid, whatever the body does (308–346 s: median 0.12 px, 5–95 % 0.05–0.47).
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
  "collisionVersion": "v26.1.13"                  // version of the last collision pass
}
```

- After inference the runner immediately does a collision pass (§7) with the recording's current settings, then sets `done`. If the collision pass fails, it is logged and the run is still `done` (without hazards/events).
- `motion` is loaded from `motion.npz` when present (`t`, `dx`, `dy`, and `resid` if the file has it), else `None` (then ego estimates and the world memory are unavailable).
- `depth` is loaded from `depth.npz` when present, else `None`.
- `POST /api/runs/{id}/collision` re-runs only the collision pass from `grids.npz` + `motion.npz` (+ `depth.npz`) with the recording's **current** settings and rewrites `hazards.json`, `events.json` and `collisionVersion`.

**Cancellation:** `POST /api/runs/{id}/cancel`.
- A queued run is removed from the queue; a running one has a per-run cancel flag that the worker checks between frames. The run ends as `status: "cancelled"` and its partial outputs (`masks/`, `grids.npz`, `motion.npz`, `depth.npz`, `hazards.json`, `events.json`) are removed; `run.json` stays.
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

**Module constants** (in `collision.py`, not config): `WARMUP_S 1.5` (the horizon is the mean of the raw estimates until then; since v26.1.15 it silences nothing); `MIN_TRACK_AGE_S 0.5` (a track must be this old to speak or beep; **not during the first `WARMUP_S` of a run** since v26.1.15, where the 2-frame confirmation is the only gate); `HORIZON_HOLD_S 3.0` (the last good horizon is held this long when an estimate fails); `LABEL_COOLDOWN_S 5.0` (a danger label is not repeated within 5 s); `POINT_ASPECT 3.0` (speed witnesses are at least 3× taller than wide).

## 7. Collision logic  (`src/collision.py`)

**Pure logic:** numpy + scipy and `geometry.Box`/`geometry.iou` only. No cv2, no torch, no file I/O except `load_config`. It must stay portable to Swift.

```python
@dataclass
class CollisionSettings:
    mount: str; hfov_deg: float; camera_height_m: float
    step_length_m: float | None        # None = use ego.priorStepLengthM
    horizon_default: float             # from the mount preset

load_config(path=None) -> dict
resolve_settings(config, mount=None, hfov_deg=None, camera_height_m=None, step_length_m=None,
                 projection=None, distance_source="ground") -> CollisionSettings
resolve_projection(projection, hfov_deg) -> "rectilinear" | "fisheye"   # None/"auto": fisheye when hfov >= 100
bearing_deg(x_norm, hfov_deg, projection)     # rectilinear: atan((x-0.5)*2*tan(hfov/2)); fisheye: (x-0.5)*hfov; + = right
clock_from_bearing(bearing) -> int            # whole hour: 12 + round(bearing/30), clamped to ±90°, as 9..12 and 1..3 (side logic, back-compat)
clock_quarter(bearing) -> int                 # q = round(bearing/7.5°) (half away from zero), clamped to ±12
clock_text(q) -> str                          # m = (720+15q) mod 720; "H" when on the hour, else "H:MM": 12, 12:15, 11:45, 1:30
focal_px(grid_w, hfov_deg)                    # (grid_w/2) / tan(hfov/2)
ground_distance_m(y_norm, horizon_y, camera_height_m, grid_h, f_px)   # H*f / ((y-horizon)*grid_h); None if y <= horizon
lateral_m(x_norm, distance_m, grid_w, f_px)   # (x-0.5)*grid_w*distance/f   (+ = right)
estimate_cadence(t, dy, window_s, band_hz, min_peak_ratio, dx=None, ...) -> per-sample Hz or nan
walking_region(grid, ids, config) -> Region | None
run_collision(grids, times, class_names, config, settings, motion=None, depth=None) -> (hazards_doc, events_doc)
    # depth: {"t", "depth" (N, 68, 120) metres} or None
    # motion: {"t","dx","dy"[, "resid"]} arrays or None -> no cadence, heading, ego speed from gait, or world memory;
    #         without "resid" the user is never stationary
```

Frames are processed in order; every state below carries over from frame to frame. "Frame" = analysed frame.

### 7.1 Walking region
- The majority surface class inside `seedBox` (surface-group classes only; ties → the group with more pixels) picks the group. No surface pixels → `region = None` for this frame.
- Region = the 4-connected components, containing seed-box pixels, of (that group's classes ∪ `surfaces.inside`).
- Per grid row: `left`/`right` = min/max region column (normalised). Rows without region pixels are invalid. After the horizon fit (below), `left/right` are smoothed per row with EMA 0.5 across frames (reset when the frame's group changes).
- The region follows the model frame by frame. The **adopted surface** (§7.14) is separate and slower.

### 7.2 Horizon
- Raw estimate: fit `x = a·y + b` to the left and the right bound, each over the lowest 70 % of that side's valid rows, **excluding rows where the bound is clamped to the image border** (a clamp is a crop, not an edge); each side needs ≥ `minRegionRows` rows. Accept only if the lines converge upward (`a_left < −0.02`, `a_right > 0.02`) and the intersection's y lies within `horizonValidRange`. Otherwise no estimate this frame.
- During the first `WARMUP_S` (1.5 s) the horizon is the mean of the raw estimates so far (the mount / body preset if none; v26.1.15: roles, speech and beeps work on it from the first confirmed frames). Afterwards: a failed estimate keeps the last horizon for `HORIZON_HOLD_S` (3 s), then the target is the preset; otherwise EMA (`horizonEma`) toward the target with each step clamped to `±horizonMaxStep`.
- `horizonEstimated` in the output = a raw estimate was accepted this frame.

### 7.3 Geometry and the gait-calibrated scale
- Pinhole flat-ground model: a ground point `dy` rows below the horizon is `H·f/dy` metres away; lateral = `(x − 0.5)·W·d/f`. `H` is the camera height times the scale `k` below, so **all distances, laterals, areas and closing speeds are real-world metres**.
- **Scale `k`** (class `_Scale`): over the last `calibrationWindowSeconds`, `k = median(cadence) × priorStepLengthM / median(raw ego speed)` for frames where both are known (raw speed ≥ `calibrationMinRawSpeed`; at least `calibrationMinSamples` frames; clamped to `scaleRange`). The first estimate is taken at once; later ones are blended in (log scale) with a time constant that grows from `calibrationEmaMinSeconds` to `calibrationEmaSeconds`. The **applied** scale slews toward the measured one at ≤ `scaleMaxChangePerSecond` (so step counts don't jump). Frames without cadence add nothing, so the last scale is held when standing still; until the first estimate `k = 1` (or `scalePrior`).
- The raw closing speeds that feed the calibration stay uncalibrated, so there is no feedback loop.
- **Per-recording `stepLengthM`** replaces `priorStepLengthM` for the calibration and for steps.

### 7.3a Distance source  (`distanceSource`; experiment)
- **Bearings** (clock, pan) use the resolved `projection`; lane, lateral and ground distance stay the pinhole model.
- **Side offset:** an item's lateral relative to the body = camera lateral + `lateralOffsetM` (right-mounted +). The body lateral drives the lane mask, the drawn lane, lane hits, world memory and `lateralM`; bearings, clock and pan stay camera-based (the effect is under a quarter beyond ~1.3 m). The lane's offset is decided in one place (`_walking_axis_offset_m`), so that eye and head mounts — whose camera turns with the head — can later switch to a body (IMU) heading.
- **Anchor mode** (`analysis.DEPTH_ANCHOR` per variant, stored as `anchor` in `depth.npz`; precedence npz > variant > units default — `per-frame` for relative, `none` for metric):
  - `per-frame`: the ground anchor below, re-measured every frame.
  - `plane` (`_PlaneAnchor`, **DA2 default**): per frame, the walking-region cells (below the anchor horizon + `motionMinRowsBelowHorizon`) are back-projected with the depth z and the pixel ray. Rays follow `distance.depthRayModel`: `"lens"` (default: the resolved projection; fisheye equidistant `f = W / hfov_rad`) or `"pinhole"` (`f = (W/2)/tan(HFOV/2)`, as depth models are trained on pinhole images; measured worse on 4929). The real lens still drives bearings, clock and pan., and a plane `Y/Z = c/Z + a·X/Z + b` is fitted (deterministic RANSAC start, then least squares with 2.5× MAD rejection; valid: ≥ `anchorMinCells` inliers, inlier fraction ≥ 0.6, normal within 35° of down, plane below the camera). Camera height in depth units `h_d = c/√(1+a²+b²)`, pitch `asin(−b/√(1+a²+b²))` (+ = looking down). Scale `s = cameraHeightM / h_d`: running median from 3 valid frames, frozen at 6 (`recalibrateOnPathChange` resets). **No gait level** (`levelModeByAnchor.plane = none`); the gait estimator runs as a check only (`depthGaitCheck`: ≈ 1 when camera height and walking agree).
  - `initial` (`_InitialAnchor`, older DA2 runs' stored mode, superseded by `plane` for DA2 via `analysis.SUPERSEDED_ANCHORS`): the same per-frame ground ratio is collected over the first valid frames; usable as the running median from `distance.initialAnchorMinFrames` (3) valid frames, **frozen** at `distance.initialAnchorFrames` (6). Before 3 valid frames depth is unusable (ground fallback). `distance.recalibrateOnPathChange` (default false) restarts the collection after a path change.
  - `none`: metric metres as given (UniDepth, old Metric Large runs): `c × a = 1`.
- **Depth → metres** = `c × a × z` (single-image relative depth is right *within* a frame up to one scale — ~4 % vs Metric Large on 4929 — but that scale drifts frame to frame, median 7 %, p90 ~20 % per 1.7 s, so it is re-anchored every frame):
  - **Per-frame ground anchor `a_t`** (class `_DepthAnchor`): over walking-region cells ≥ `motionMinRowsBelowHorizon` rows below the anchor horizon, `a_t = median(g / rel)`, with `g = H·f / (row − horizon·gh)` the flat-ground z-distance at the **uncalibrated** camera height; needs ≥ `distance.anchorMinCells` (150) cells; log-EMA `distance.anchorEmaSeconds` (0.4 s ≈ 2–3 frames); held `anchorHoldSeconds` (2 s) when a frame has none, then depth is unusable (`depthM` null, depth mode falls back to ground). **Anchor horizon** `distance.anchorHorizon`: `"fixed"` (default: the mount preset's horizon row, no estimation jitter; it is only wrong while turning/pitching, which is accepted), `"estimated"` (the frame's smoothed horizon) or a row fraction.
  - **Level `c`** (class `_DepthScale`, dimensionless, gait-calibrated): depth witnesses are the pole-like static items of the ground speed witnesses (bbox height ≥ 3× width, not clipped, not along the path) within ±`distance.depthWitnessMaxBearingDeg` (40°). A static object's **z-depth** falls at exactly our speed `v = cadence × step length` (v ≥ 0.5 m/s) whatever its bearing, so each frame's sample is the median of `v / r`, `r` = the negative slope of the witness's *anchored* depth history (same ≥ 3 points / ≥ `motionMinSeconds` / latest-point rule). Estimator as `_Scale` (median over `calibrationWindowSeconds`, ≥ `distance.depthLevelMinSamples` (30), first estimate at once, log-EMA, slew ≤ `scaleMaxChangePerSecond`), clamped to `distance.depthLevelRange` [0.3, 5]. Before its first estimate `c` = the applied ground scale `k`, so depth is usable from the start.
  - Track depth histories hold anchored depth; `c` is applied at use (no feedback through `c`). Metric depth (older runs) uses `c × a_t = 1`. The ground scale and its witnesses never see depth.
  - ego: `depthAnchor` (`a`, the frozen one in `initial`/`plane` mode, or null), `depthAnchorMode`, `depthPitchDeg`, `depthCameraHeightUnits`, `depthGaitCheck` (plane mode; null otherwise), `depthLevel` / `depthLevelSource` (`prior | ground | gait | frozen`; the `initial` anchor freezes `c` at its first estimate, `distance.depthLevelPrior` default `ground`, no camera prior), `depthScale` (`c × a`, metres per depth unit, or null), `depthScaleSource` ∈ `gait | ground | prior | plane | metric | none`.
- With depth, each item gets `depthM` = `s ×` median depth over its component pixels in the lowest `distance.depthLowestRowsFrac` (0.25) of its rows, mapped onto the 120×68 grid (null if none). It is reported in every mode.
- `ground`: §7.3 unchanged; output equals no-depth output apart from `depthM`.
- `depth` (**Lab default**): distance = `depthM` (metres via `s`: the ground scale `k` is **not** applied); lateral = the ground lateral × depth/ground; steps = depth / step length. Items without `depthM` fall back to ground.
- Tracking and the ground gate still match on ground distances; depth is substituted after matching. There is no mixing: every item takes its distance from the selected source (ground, or depth with a ground fallback when it has no depth pixels). When an item's distance came from depth, its closing speed is the negative slope of the track's own depth history (same ≥ 3 points / ≥ `motionMinSeconds` / latest-point rule). The raw closing speeds that feed the gait calibration stay ground-based.

### 7.3b Object distance and the horizon switch  (`distance.objectDistance`, `distance.useHorizon`; v26.2.3, `src/groundfuse.py`)
Per-run settings (§4, the Lab's Collision settings next to Camera side), `CollisionSettings.object_distance` / `use_horizon`, recorded in `hazards.json` `settings`. They apply to depth distances (`distanceSource` depth with a depth map). **One setting for the pass and the map:** the world map's object bases (§8.1) read `settings.objectDistance` / `useHorizon` and each frame's `depthCorrection` from `hazards.json`, so the map uses exactly what the pass used. A hazards file without the keys (older runs) means `depth` / `true`.
- `depth`: v26.2.2 (byte for byte; the golden hash of `chest0004_review7` is unchanged apart from the version and the two settings keys).
- `ground-contact`: a base that stands on a surface (not clipped, the pixel below it is a `worldmap.json` surface class) and is inside the band (>= `groundDepth.minRowsBelowHorizon` (4) grid rows below the horizon, ground ray <= `fuseMaxM`) takes the ground ray; else the depth.
- `ground+depth` (measured worse than `depth`, not the default): (1) **range correction**: the **ground ray** is the lens geometry (`groundfuse.ground_z`: the pixel's ray, equidistant fisheye or pinhole, the pitch the horizon row implies, the camera height `H` without any gait scale; it returns the z-depth of the ground point, the quantity the depth map holds). Per frame the walking-region cells (>= `minRowsBelowHorizon` rows below the horizon) give `ref` (q) = median(scaled depth / ground ray) over ground rays `refGroundM` (2-8 m) (~1 when camera height and horizon are right; 0.8 on the legacy-mount Chest-center-0004 settings) and the curve rho(d) = (depth / ground ray) / q binned by depth (`binEdgesM`, >= `minBinSamples` cells per bin, medians). The curve is log-EMA smoothed (`emaSeconds` 1 s), held `holdSeconds` (2 s) when a frame has too few samples, forced non-increasing and >= `rhoMin`; beyond the farthest fitted point `extrapolate` "prior" continues it with `priorCurve` (the measured DA2 squash) or "last" holds it. `corrected = depth / rho(depth)` (capped at `maxCorrectedM`); the near field is unchanged. Applied to every depth reading of items, movers included. (2) **fusion** of a base in contact inside the band: inverse-variance weights of the ground ray ( sigmaRows = sqrt(horizon jitter std over `horizonWindowSeconds` about its trend, `rowSigma` 0.5 row quantisation), turned into metres by the ground ray at row +- sigmaRows) and the corrected depth (sigma/D = `depthRelErr` (0.12) / max(rho, 0.25)); without contact or outside the band the corrected depth alone. (3) **sanity gate** (`groundDepth.gate`; `groundDepth.fuse` false = correction without fusion, for A/B): a base in contact (inside the band) is never nearer than `sanityFactor` (0.7) x its ground ray, else the ground ray wins; a base not on a surface is exempt (occlusion makes the ground ray an upper bound). Track depth histories (closing speed) stay on the raw depth.
- `useHorizon: false`: object distances use `depthScale x depth` only (no ground ray, no correction, no fusion); the world map's object bases use the depth and its surfaces are projected through the depth map (lens ray model, forward = z cos(pitch) - y sin(pitch) with the plane-fit pitch, pixel footprint splatted). **Kept on the horizon** (listed in DECISIONS v26.2.3): the horizon estimate itself, the pixel danger lane and the below-horizon / 30 m pre-filter of item detection, the ground-based tracking, items and bases with no depth (their ground fallback; map bases are dropped), the depth scale calibration (plane fit / gait anchors). `distanceSource` ground runs are unaffected.
- hazards: per item `distanceSource` (`depth | ground | fused`), `rawDepthM` (scaled depth before the correction), `groundM` (ground ray in depth metres, null outside contact / band) when the mode is not `depth`; per frame `depthCorrection` `{"ref", "sigmaRows", "curve": [[depth m, rho], ...]}` (rounded; absent when there is no `ref`).

### 7.4 Items
- 4-connected components of **each class** (not each group) of the `static`, `moving` and `feature` groups, only over rows whose bottom edge is below the horizon, with ≥ `minComponentFraction × grid area` pixels. A pole against a wall is two items.
- **Contact point:** static/moving = the component's lowest pixel (on that row, the column nearest the image centre); feature = its lowest pixel *inside the danger lane* if any, else the lowest pixel. Compute `distanceM`, `lateralM`, `bearingDeg`, `clock`, `clockQ`/`clockText` (quarters), `pan` (`sin(bearing)`, clamped) there. Drop items with `distanceM > maxRangeM` or no distance.
- **Danger lane:** half-width at a row = `laneHalfWidthM` in metres projected to pixels at that row's distance. `lane_hit` for static/moving = the component's lowest row itself touches the lane inside the (dilated) walking region (a car beside the path whose roof intrudes does not count); for features = any pixel in the lane. `lane_cover` = share of the lane's width at the contact row that the feature covers.
- `touches` = any pixel in the walking region dilated by `boundaryMarginPx`. `clipped` = the component touches the bottom image edge (its distance is only a lower bound).
- **Runs along the path:** look at the component's *base* pixels (those with walking region directly below them). If the base's near/far distance ratio is < `alongPathRatio` (0.5), the item spans a long stretch of path (a wall, median or curb alongside): it is boundary, never danger and never a lane-crossing feature. Also, a static/feature item whose raw closing speed is < 30 % of the raw ego speed (when that is ≥ 0.5 m/s) is treated as running along the path.
- **Lane part** (v26.1.16 follow-up, review 8 10.9 s): a wall/building whose side runs along the path and whose face juts into the lane is ONE component measured at its lowest pixel (the side wall's base: context). For static items of `laneBaseClasses` whose main item is not a lane hit (or runs along the path) an **extra item** is emitted: its *ground base* = component pixels with walking region directly below (`floor_below`) that lie in the lane inside the walking region (pixels above such a base never count; "any pixel over a lane cell" made every wall along a sidewalk beep). With ≥ `laneBaseMinColumns` columns of it the item has contact at the lowest base cell (on that row the column nearest the lane centre), `lane_hit` true, `along_path` false, `lane_cover` on that row, area / outline / bbox of the whole component, `lane_part` true. It has its own track (own id range from `1000000`, so ordinary track ids do not shift; never matched with the side wall's track) and its depth is read under the base cells. It is a danger (§7.9) only if: the base is flat (`laneBaseMinRowColumns` / `laneBaseMinConcentration`; a non-flat base continues a flat one for `laneBaseHoldSeconds`), the track is ≥ `laneBaseMinAgeSeconds` old, the ego speed is known and its raw closing ≥ `laneBaseMinClosingMps`; otherwise role `none` (context stays the side wall's). Not a speed witness (`_pole_like`).
- **Walls judged on the map** (v26.2.2, `staticSource: "map"`; replaces the v26.2.1 building section and the v26.1.16 lane part, which are no longer emitted): a static item of `mapJudgedClasses` is judged on the fused world map (§8.1) alone. Its footprint = the map cells of its own ground-base points grown by `mapFootprintRadiusM`; its cells = fused object cells of its family there with confidence ≥ `mapMinConf` inside the full corridor (`|right| ≤ laneHalfWidthM`, ahead > 0). The **face / edge test** (`src/faceedge.py`) classifies each cell: *edge* = within `edgeBandM` (+ blur per metre) of the wall line of its side (RANSAC line of the family's cells 0-8 m ahead, |angle| ≤ 25°; a cell on a side without a line is judged against the other side's line); *face* = not an edge and protruding past its line toward the axis by ≥ `faceProtrusionM`, or in a local cluster whose principal axis runs across the path (≥ 45°), or with no wall line at all. With ≥ `minFaceCells` face cells (and the user not standing still) the item is a lane danger and takes the nearest face cell as its measurement (distance = ahead, lateral = right, bearing = atan2(right, ahead), clock, steps); the image values are kept as `imageDistanceM` / `imageLateralM`. Edge cells, a wall beside the path, or too few face cells: no lane danger (the item stays context as before). With no cell of the item in the corridor the image rule decides (`mapImageFallback`). Poles, signs, sidewalk obstacles and parked vehicles keep the v26.2.0 image rule. Hazards JSON: `faceEdge` per static item with corridor cells (verdict, counts, `nearestFaceM`, `lines`, `faceCells` / `edgeCells` (≤ 60 each, forward / right m), `stationary`, image lane flags) and `faceEdgeLines` per frame.
- **Inside solid** (v26.2.2, `insideSolid.mode`): a non-wall item (static of another class, mover, coasting mover) whose map position lies more than `solidDepthM` inside the solid wall-like cells (fused, confidence ≥ `mapMinConf`) or behind a face of ≥ `minRayCells` consecutive solid cells on its own ray is a depth error: with mode `"snap"` its distance / lateral / bearing / clock are moved along its own bearing to the first solid cell of the ray (the near border), `distanceM`, `stepsTo` and every later rule use the corrected point; JSON `insideSolid: true`, `solidCorrected: true`, `rawDistanceM`. Mode `"suppress"` gives it no role, speech, beeps or proximity sound instead (A/B). A coasting mover that drifts into solid stops coasting.
- **Coasting movers** (v26.2.2, `coast.*`): a mover (`group "moving"`) measured for ≥ `minPoints` frames over ≥ `minSpanSeconds` (least-squares world velocity from the dead-reckoned pose) that disappears (out of frame, occluded, a segmentation dropout) is emitted as a predicted item (`coasting: true`, `clipped`, no outline) on its last world velocity for ≤ `seconds` (`vehicleSeconds` for vehicles). It keeps its track and motion state, is judged by the normal roles (collision course, beeps, proximity) but is never spoken (`speak` false); it ends on a rematch (the same track, or a new item of its class within `rematchRadiusM` + 10 % of range of the prediction), when passed (ahead ≤ 0), beyond `maxRangeM`, when the time is up, or inside solid. `hazards.json` top level `coast: {episodes: [{track, class, t0, t1, steps0, speedMps, moving, end}]}`.
- **Ghost** (v26.2.1): a confirmed static danger (`role_run ≥ confirmFrames`) that is clipped or within `mapGhostNearM` is remembered with its world position. When the image loses its track, a ghost item (a copy, `ghost: true`, `clipped`, no outline) is emitted each frame as long as fused object cells of its family (confidence ≥ `mapGhostMinConf`) are in the corridor near the dead-reckoned position, for ≤ `mapGhostSeconds`, until passed (`ahead ≤ 0`); it keeps the track, so the danger, beeps and the final call continue.
- `area_m2` = pixel count × (distance/f)².
- Distance, lateral and steps are read from a per-track **smoothed contact row** (`contactEma`); a clipped item has no smoothing.

### 7.5 Tracking
- Greedy matching within the same group **and** class. A pair matches if `iou(bbox) ≥ iouMatch` **or** the ground gate holds: `|Δlateral| ≤ groundGateLateralM` and `|Δdistance − expected| ≤ groundGateDistanceFrac × distance`, where `expected = −closing·dt` (0 if unknown). Score = IoU, plus 0.5 if the gate holds; highest first.
- **Pan-compensated person match (v26.1.16, review 8, 27.3 s).** `_match` gets the scene shift since the previous frame from the heading change (`−Δheading / hfov`, normalised x, capped ±0.25). For **people** (`classes.people`) and a shift of at least `tracking.panMatchMinShift` (0.04, a turn of ~5° per frame) the IoU is also taken against the track's box moved by that shift. At 27.2 s the head turned 9° in one frame: a person 5.7 m away jumped a full box width, lost its track three times in 0.5 s (age 0, no motion, confirmation restarting) and was announced 1.2 s late. The same hard pan makes the ego speed **unsettled** for `roles.panSettleSeconds` (1 s): a head turn throws the cadence off (2.09 against 1.2 m/s around 27 s), so the person read "standing" while crossing; now they get the plain phrase ("person at 11:45 in 8") at once. Poles, buildings and vehicles are not compensated (they are re-found by the ground gate; compensating them reshuffled the speech of reviews 3–7).
- A track survives `maxMissedSeconds` without a match. It keeps its contact **rows** (not distances) over `historySeconds`; a clipped detection clears the history.
- **Closing speed:** the (negative) slope of the distances obtained by re-projecting *all* history rows through the **current** smoothed horizon (so horizon wobble cannot fake motion). Points less than `motionMinRowsBelowHorizon` rows below the horizon are left out; it needs ≥ 3 points, ≥ `motionMinSeconds` of history and the latest point included; otherwise `None`. `closingMps` = raw closing × `k`.
- Per track: `present_run` (consecutive frames matched) and `role_run` (consecutive frames holding the same role). A track is `settled` after `MIN_TRACK_AGE_S` (v26.1.15: always during the first `WARMUP_S` of a run; `confirmFrames` = 2 still applies).

### 7.6 Ego motion
- **Cadence** (step rate, Hz), from the vertical bob `dy` of `motion` (nearest motion sample to `t`): causal power-spectrum peak in `cadenceBandHz` over `cadenceWindowSeconds` (needs 60 % of a window), accepted at `cadenceMinPeakRatio` (a weaker peak is accepted when the horizontal sway `dx` peaks at the same rhythm). **Stride-aware:** a chest camera bobs asymmetrically, so a dominant peak `f0` is often the stride; the step rate is the peak near `2·f0` if `f0 < minStepHz`, or that peak has ≥ `harmonicMinRatio` of the power, or `dx` peaks within 0.15 Hz of `f0`; otherwise `f0`. A value is held for one window when a later window has no clear peak.
- **Speed witnesses:** only pole-like static items (bbox height ≥ 3× width, not clipped, not running along the path) with raw closing speed in [0, `speedMaxMps`] judge our speed: the median, EMA `speedEma`, dropped when stale for > 5 s.
- **Cadence refine** (v26.1.11): the parabolic refine of the peak bin is rejected (the bin centre is kept) when it moves by more than one bin or leaves the search band (the peak search is band-limited, so a bigger neighbour outside it made one reading −16.3 Hz at 336 s of review 4).
- **Stationary user** (v26.1.11, `estimate_stationary`, config `ego.stationary`): from `motion.resid` (§5): `m` = causal median of the residual flow over `medianSeconds`, valid with half of the window's samples known. **Entered** after `m < enterPx` (0.8 px) for `enterSeconds` (1.5 s); **left** after `m ≥ leavePx` (1.0 px) for `leaveSeconds` (1 s); an unknown `m` never enters and counts as walking when leaving (a false "stationary" silences warnings, a false "walking" only says too much). On 4929: the 1 s median is 0.07–0.58 px standing (308–346 s) and ≥ 1.34 px at every moment of 0–296 s and 360–470 s, so the thresholds sit in the middle of a 2.3× gap. A turn in place is not recognised (the picture rotates). Without `resid` (old runs, fixtures 1–3) the user is never stationary. Reported as `ego.stationary`. **While stationary** the walking cadence is ignored (a standing chest camera bobs at 1–2 Hz: review 4 read 1.3–2.2 Hz and 1.1 m/s), the ego speed is 0, nothing static is announced (every item except a measured mover on a collision course gets role `none`: no context, feature, thin notice, danger, final or beep) and the world memory does not advance.
- **Ego speed** (calibrated, used for moving-vs-standing and the world memory), v26.1.11: 0 while stationary; else `cadence × stepLength` once the scale is known (or the distances come from depth: they are metres from the start) and a cadence exists; when the cadence drops out that **last cadence-based speed is held for `cadenceWindowSeconds`, then the speed is unknown** (people then get no motion word). The witness speed × scale is only the cold-start guess before any gait scale or cadence-based speed exists (it read 0.59 m/s while walking at 1.4, so a standing person "approached" at 178.7 s). **Settled (v26.1.15, review 7):** the robust speed (median of `egoMedianSeconds`, §6) counts as *settled* when its history has been unbroken for the full window (`_Item.ego_settled`; a measured standing user is settled at once; a gap in the ego speed, i.e. none known, restarts the history). Before that the median is still ramping (0.59 m/s at 2.0 s, 1.28 at 3.2 s on Chest-center-0004, so a standing person read "approaching"): see the motion words.
- **Heading:** the cumulative sum of `−dx × hfovDeg` (degrees; + = turned right), interpolated to `t`.

### 7.7 Steps
`stepsTo = distanceM / stepLengthM` (the stored per-recording length, else `priorStepLengthM`). Spoken as `round(stepsTo)`, at least 1 (`"1 step"` for 1, else the number); `stepsTo` is kept with 1 decimal in JSON. Steps are *not* divided by the instantaneous ego speed (that made them jump). Distances are real-world thanks to the scale (§7.3). Steps are omitted from a phrase only if the distance is unknown (the `" in {steps}"` part is dropped).

### 7.8 Moving vs. standing
- Static and feature items: `moving = false`. Moving-group items need a known `closingMps` and ego speed (0 while stationary, §7.6). Their **ground velocity** (v26.1.11): *along the line of sight* `along = (closing − egoSpeed / c) · c` (toward the user = positive), smoothed per track (EMA `motionSmoothSeconds`); `c` is the depth gait level (`depthGaitCheck`, clamped to [0.8, 2.5]) when the distances come from a plane-anchored depth map, else 1: depth closing rates read low against the gait (review 4: level 1.2–1.6; a standing person's closing was 0.85 m/s against our 1.4), so both are put on the gait's scale. *Sideways*: `lat_vel`, the slope of the lateral offset over the track's history, each point re-expressed in the newest heading (`lat − Δheading × distance`); a velocity under `lateralVelDeadbandMps` counts as 0 (§7.9).
- **Motion state** (v26.1.12, `_motion_state`, per track, with hysteresis; "a wrong state is worse than none"). With `along` the smoothed speed above:
  - `approach`: `along ≥ approachingMps` (0.4), kept down to `motionLeaveMps` (0.3); `recede`: `along ≤ −0.4`, kept up to −0.3; **v26.1.16 (rule 8, review 8, 52.2 s: a parked car was "approaching"):** for **riders and vehicles** (`fast`) the entry level is `fastApproachingMps` (1.0) and the leave level 0.7× that — their `along` comes from the contact row of a big, fragmenting component and read 0.5–1.5 m/s off for a parked car; a real approach is several m/s, so a car or cyclist at 0.4–1.0 m/s is `unknown` (static-like, no phrase) instead; `side`: a sideways velocity above the deadband (§7.9).
  - `still` ("standing"): `|along| < standingMps` (0.3) **held for `standingHoldSeconds` (1 s)** without a break, **and** no sideways motion (`|cross| < standingMaxCrossMps`, below); once standing it is kept while `|along| < 0.4`.
  - anything else — in between, a measurement shorter than the hold, or a possible sideways motion — is **unknown**: `moving = null` and the plain phrase `"{label} at {clock} in {steps}"` is said.
  - `moving = (state ≠ still)`, null for unknown; `approaching = state is approach`, `receding = state is recede`. No closing or no ego speed → `moving = null` as before.
  - **Across the line of sight** (`cross_mps`, `_cross_velocity`, reported as `crossMps`): the item's bearing (bbox centre) plus the camera heading, fitted over `crossWindowSeconds` (1 s, ≥ 4 points over ≥ 0.7 of it), gives a rate; `R · rate − v · sin(bearing)` (range `R = hypot(distance, lateral)`, bearing and range at the window's middle, `v` our speed) is the item's own speed across the view (a static point drifts outwards at `v sin θ / R`). It is **weak**: on 4929 0–110 s a static pole within 12 m reads 0.2–0.3 m/s median and 0.6–1.25 at p90 (12–32 % of frames above 0.6), a person measured walking left 0.57–0.8, so it cannot name a direction ("moving left") and is used only as the veto for "standing" at 0.6 m/s. There is no `crossing` state.
- **Vehicles** with `moving ≠ true` are treated as **static** for roles, and `moving == false` gives the label `parkedLabels["vehicle"]` ("parked car"); unknown keeps "vehicle". **While motion can be measured (ego speed known) a vehicle of unknown motion is not a static danger** (a moving car re-detected in fragments has no closing speed for ~0.75 s and was one: review 4, 39.0 s); it waits.
- **People (person, rider, animal)** are judged like any mover, on the smoothed ground velocity above: `moving = false` (state `still`) is spoken as "standing" (cyclist: "stopped"); an unmeasured or unsure person keeps the plain phrase (v26.1.6 – v26.1.10 never called a person standing; with the ego speed held and on the gait's scale, standing and walking are separable: 4929 standing people read −0.5 → ~0 m/s, approaching ones +0.5 … +2).

### 7.9 Roles  (one per item per frame)
- **danger**
  - *Static, or a vehicle with `moving ≠ true` (measured parked, or unknown while ego speed is unknown):* component area ≥ `minObstacleAreaM2`, `lane_hit`, not running along the path, `stepsTo ≤ dangerSteps`. On a collision course (`collision = true`). A wall-like item judged on the map (§7.4, `staticSource: "map"`; under `"image"`: the **lane part**) is a lane hit when the face / edge test calls it a face (its image lane hit is ignored); a ghost (§7.4) is judged as the item it copies.
  - *Rider / vehicle measured approaching* (`classes.fast`, `moving = true`, v26.1.13, review 6 at 191.5 / 445.3 s: "warn as soon as possible, the 10-step rule does not apply to cyclists or vehicles on or close to a collision course"): in the row span, area ≥ `minObstacleAreaM2`, not receding, `|lateral|` now within `movingLaneHalfWidthM` (rider) or `laneHalfWidthM + 1.0` (vehicle), the gap closes (`closingMps ≥ courseMinClosingMps`), we meet within `fastWarnSeconds` (6 s: `T = distance / closing`), `distanceM ≤ fastWarnMaxM` (30) and the predicted `|lateral + lat_vel × T| ≤ movingLaneHalfWidthM` (3.0): a **danger with no step limit**, spoken `"cyclist approaching at 11"` (no distance). `collision` only when also `T ≤ courseMaxSeconds` and the predicted `|lateral| ≤ beepLateralM` (0.9): a cyclist passing at 1.9 m is announced, not beeped. A vehicle driving across the crosswalk ahead is far to the side now and silent (review 4, 39.0 s).
  - *People (person, animal; a rider who is not coming at us counts too)* (v26.1.13, review 6): `course` = measured mover: `on_collision_course` (closing, `T ≤ courseMaxSeconds`, predicted `|lateral| ≤ beepLateralM`, not receding); standing / unknown: `|lateral| ≤ beepLateralM`. In the row span (or no region), area ≥ `minObstacleAreaM2`, `stepsTo ≤ movingDangerSteps`:
    - `stepsTo ≥ peopleSpeakMinSteps` (4.5) and `|lateral| ≤ peopleSpeakLateralM` (2.75): **danger, spoken once, whatever the direction** (approaching, moving away, standing, unknown: "good to know someone is there"), with the distance; `collision = course`.
    - closer than that: only if `course`: a **silent danger** (`speak = false`, `collision = true`): no phrase, not even a final; beeps only. Otherwise `none`.
    - unknown motion and a person measured approaching at arm's length no longer beep (v26.1.12 did; review 6: four beep entries at 1.2–3.0 m were "not on a collision course").
  - `urgency` = `final` if `collision` and `stepsTo ≤ finalSteps`, else `danger`.
  - **While stationary** (§7.6) only a measured mover on a collision course keeps its danger role; everything else is `none`.
- **feature** (curb, crosswalk, pothole)
  - *Landmark* (crosswalk): touches the walking region, not clipped, `stepsTo ≤ landmarkSteps`. It need not cross the lane.
  - *Others:* `lane_hit`, not running along the path, not clipped (not already under the feet), `lane_cover ≥ featureMinLaneCover`, `stepsTo ≤ featureSteps`. A curb or median running alongside the path stays silent.
  - A track that held the feature role with `lane_hit` and not along the path for `confirmFrames` frames has "crossed the lane": only such a curb/crosswalk can be surface evidence (§7.14).
- **context:** a static/parked item that is not danger, `touches` the dilated region, `distanceM ≤ contextMaxDistanceM`, area ≥ `contextMinAreaFraction`, `distanceM ≤ contextMaxSteps × stepLength`, and `|lateral| ≤ contextMaxLateralM` (v26.1.13: 2.5 m; within `contextNearSteps` 3.0 m). (An item that fails only the lateral limit is allowed in the very first start summary of a run.) People never get `context`.
- **none:** everything else (still listed in `hazards.json`; the UI greys it).
- **No start silence (v26.1.15, review 7).** Until v26.1.14 danger and feature roles were forced to `none` during the first `WARMUP_S` of a run (no distances on a guessed horizon) and proximity was off; both are gone: the horizon is the mean of the raw estimates so far (else the mount / body preset), the distance is the ground-geometry one until the depth anchor has its first `initialAnchorMinFrames` (3) plane fits, and the only start gate left is the 2-frame confirmation (0.33 s at 6 fps). Gates that stay: `confirmFrames`, the start summary's `summaryHoldSeconds` (context only), `globalMinGapSeconds` (context / surface), `peopleSpeakMinSteps`, `movingDangerSteps` / `dangerSteps` (a person is a danger only within 10 steps).
- A role is **confirmed** after it has held for `confirmFrames` consecutive frames; speech and beeps use only confirmed roles of settled tracks.

### 7.10 Speech policy  (class `SpeechPolicy`)
At most **one phrase per frame**. Priority: final > danger/feature/thin notice (one combined phrase) > surface > context. Only the highest class that has candidates is considered, so a waiting danger is never overtaken. Context and surface are held back while any confirmed danger track is active.

**Gaps:** final ignores the gap. Feature phrases wait for `priorityMinGapSeconds` after the previous danger/feature/final phrase (a context phrase never delays them). A phrase that contains a danger entry (v26.1.15, review 7: a person was held 0.8 s behind a pole) waits only for the previous danger/final phrase: a feature or context phrase never delays a danger. Context and surface wait for `globalMinGapSeconds` after any phrase.

**Templates** (`speech.templates`; `{clock}` is the quarter clock text, `clock_text`: `12`, `12:15`, `11:45`, `1:30` … from 9 to 3; no "o'clock"):

| Key | Template |
|---|---|
| `context`, `feature`, `danger`, `final` | `{label} at {clock} in {steps}` |
| `standing` | `{label} standing at {clock} in {steps}` (person, animal) |
| `stopped` | `{label} stopped at {clock} in {steps}` (cyclist) |
| `approach` | `{label} approaching at {clock} in {steps}` (people: with the distance, v26.1.13) |
| `approachFast` | `{label} approaching at {clock}` — riders and vehicles: **no distance**: at their speed the number means nothing |
| `receding` | `{label} moving away at {clock} in {steps}` (v26.1.13: with the distance) |
| `surface` | `{label}` |
| `contextGroup` | `{items}` (items = context entries joined by `", "`) |
| `multi` | `{label} at {clocks} in {steps}` |
| `thinNotice` | `{label} at {clocks} in {steps}` |

`{clocks}` lists the distinct quarter clocks left to right (by quarter index): `"1"`, `"12:45 and 1:30"`, `"10, 12 and 2"`. Every announced object has a position and (unless the distance is unknown, or it is a rider / vehicle "approaching") steps.

**Motion words (v26.1.11, "need to know if static, approaching or moving away"; v26.1.13).** A danger/final item's phrase kind is chosen per item: a mover with state `approach` → `approach` (people with the distance, `approachFast` for riders and vehicles, which also use it for any danger of theirs, e.g. one crossing sideways); a person measured walking away → `receding`; a person (cyclist: `stopped`) measured standing → `standing`; motion not measured yet, unsure (§7.8) or ego speed unknown → the plain `danger` / `final` phrase. **v26.1.15:** the three state words (`standing` / `stopped`, `moving away`, and `approaching` of a person) are used only when the ego speed is *settled* (§7.6); until then the plain phrase is said at once, with no motion wait. A rider / vehicle `approach` keeps its word without it (it closes at several m/s: a ramping ego speed does not change that, and the warning must not wait 3 s). **v26.1.16 (rule 8):** `approach` for a rider / vehicle needs a settled ego speed **or** `own_fast` (`closing − maxWalkingMps ≥ approachingMps`, i.e. faster than anyone could walk); otherwise they get the plain phrase. The early cyclist warnings (review 6) are unaffected (they close at 4+ m/s).

**Re-announcement (v26.1.12, review 5 at 76.5 s).** A mover announced before (plain, "standing" or "moving away") is announced **once more** when its kind becomes `approach` (`person approaching at 12:15 in 9`): `_Track.approach_done` is set by any phrase that said "approaching"; this is the only re-announcement. The label gap (`LABEL_COOLDOWN_S`) and the world memory (`mem_approach`) still apply. Items are grouped by (label, kind): `person standing at 1 and 2 in 7` (several clocks use `multi` with the state word in the label), `person approaching at 12 and 2 in 9`.

1. **Final** — a confirmed, settled danger track with urgency `final` that has not had one yet. Once per track; ignores the global gap; the template is `final`. **v26.1.16 (rule 6, review 8, 10.9 s: "collision and danger supersede notify-once"):** it is spoken unless the object is already in the world memory **with an earlier danger / final call** (`entry.danger`); having been named as context or feature (or covered by a thin notice) no longer mutes it, and the same holds for danger entries below. **Rule 9b:** a final for a *never-named* (`!mem_named`) non-thin static thing that has been a context item (`_Track.context_seen`: vegetation, a wall) within `contextAfterDangerSeconds` of a danger activity is consumed silently (the beeps carry it; review 8, 107.0 s). *Before v26.1.16:* it was spoken only if the object is not already in the world memory (§7.11, any entry, named or not) — something that appeared suddenly close. Otherwise the slot is consumed silently (pacing as if spoken) and the beeps carry the proximity. If a danger track is already within `finalSteps` when first announced, only the final call is made.
2. **Danger + feature + thin notice in one phrase** (at most `maxEntries` entries; danger first, then features — crosswalks before curbs, then by steps — then the thin notice):
   - *Danger entries:* confirmed danger tracks not yet announced, label not announced in the last `LABEL_COOLDOWN_S`, and not waiting for motion (a person with unknown motion, farther than `peopleMotionWaitSteps`, for up to `peopleMotionWaitSeconds` after becoming a danger; **v26.1.15: only once the ego speed is settled**, see below). Grouped by (label, kind) (see the motion words): same-label items of one kind merge into one entry with their clocks and the **nearest** item's steps (`person standing at 1 and 2 in 4`, `person approaching at 12 and 2 in 9`). Danger entries need `speak` (a person under 5 steps is a silent danger).
   - *Feature entries:* confirmed feature tracks not yet announced and allowed by the label gap (`featureLabelGapSeconds`, or `featureNewCrossingSteps` further along the walk; crosswalk: 20 s / 20 steps, curb: 20 s / 24 steps — once per crossing). Position along the walk = steps ahead plus steps walked so far. This keeps fragments of one curb, re-tracked under new ids, quiet.
   - *Thin notice:* (never while the user is stationary) thin objects (poles, lights, signs) present for ≥ `confirmFrames` frames, within `thinNoticeSteps` and `thinNoticeLateralM`, not already a danger entry: one entry per label, plural if several (`poles at 11 and 1 in 8`, steps of the nearest). Said **once**: afterwards the notice is disarmed while any thin object is noticed; it re-arms after `thinRearmSeconds` with none noticed, or on a path change. The whole thin cluster in view counts as warned about.
   - The phrase's role is `danger` if it contains a danger/approach entry, else `feature` (also for a thin-only phrase). Its clock/trackId/pan come from the leading item.
   - Danger and feature tracks are marked announced only when they enter a phrase; each is announced once.
3. **Surface** — a pending adopted-surface change (§7.14): `{label}`, e.g. "road".
4. **Context** — grouped, label-level:
   - Candidates: items with role `context` whose label is in `contextSpeak`, from settled tracks (see the start summary below), one per label family, the nearest (vehicles are not in `contextSpeak`, §6). A label already in the **label memory** is skipped; the memory refreshes while the label is seen (context/danger static-like items), is forgotten after `contextMemory.forgetAfterSeconds` unseen, and is cleared on a path change. A danger/final phrase naming a `contextSpeak` label also puts it in the memory. Context is held until a surface is adopted, or `surfaces.debounceSeconds` since the start.
   - **No context among dangers (v26.1.16, rule 9, review 8, 107.0 s):** while a confirmed danger is active, and for `contextAfterDangerSeconds` (2.5 s) after the last danger / final **phrase** or **collision-beep stream** (≥ 2 frames in a row; one pass-by beep does not count: the building at 2 steps right after a passing person's first beep at 6.2 s was ticked), no context phrase is spoken and the pending candidates restart their delay. Surfaces and features are not held back. (Rule 9b for finals: §7.10 item 1.)
   - A candidate that cannot be spoken because of the gap stays pending, but is dropped (treated as known) after `contextMaxDelaySeconds`.
   - All newly announceable labels, nearest first, at most `contextMaxItems`, form **one phrase**: `contextGroup` of the `context` entries: `"obstacle at 12 in 5, building at 2 in 8"`.
   - **Start summary:** the first context phrase of a run, and the first after a path change, needs only confirmation (no track age, no adopted surface), is held `summaryHoldSeconds` so the first view becomes one phrase, and ends `WARMUP_S` after it began (once a surface is known). The run's very first summary also admits items beyond `contextMaxLateralM`.
5. **World memory** (§7.11) filters 1, 2 and 4: objects already remembered are not announced again; when nothing is left, the slot is consumed silently. Without motion data the track and label rules above apply unchanged.

### 7.11 World memory — object permanence  (class `_WorldMemory`)
- **Active only with a motion track** (heading known) and `memory.enabled`. The user's ground position is dead-reckoned in an arbitrary metric frame (x east, y north; heading 0 = the initial direction, + = right turn) from `cadence × stepLength` (else ego speed; the last speed held `speedHoldSeconds`) along the heading. Items are located from their distance and lateral.
- Every announced object — every member of a "poles" cluster, a grouped context phrase or a merged entry, of any role — is stored as `{label family, world x/y, named, approach, seen, owner}`. Objects covered by a thin notice but not named individually are stored `named = false`.
- **Same object:** same label family within `matchRadiusM` (or `radiusOverrides`) + `matchRangeFraction × distance` of an entry. A track that matched keeps the link. Mover entries (people, or `moving`) match only within `moverTakeoverSeconds` of their last refresh (a person walks on). An announced object that matches is **not announced again**, with these exceptions: a covered-but-unnamed entry does not silence a named announcement, and an entry named but not as "approaching" does not silence an `approach` phrase (it is news once the person approaches).
- **Position upkeep:** a standing object stays where it was first put; a mover is followed by its owning track (or a hand-off within `moverTakeoverSeconds`). A track that has shown the entry for `ownerAdoptSeconds` becomes its owner; the owner seeing it keeps it "seen".
- **Forgotten when passed:** behind the user (`ahead < behindM` along the current heading) or farther than `maxRangeM`, unless seen within `seenHoldSeconds`.
- **v26.1.16 (rule 6):** each entry also has `danger` (a danger / final phrase was said for it). Context, feature and thin phrases are muted by any entry as before; **danger and final phrases are muted only by an entry with `danger`** (and, for an "approaching" phrase, `approach`): collision and danger supersede notify-once. The final-call rule (§7.10, item 1) therefore asks `_seen_before(danger=True)`.

### 7.12 Path change
A **turn**: the heading differs from a slow reference (time constant `referenceTauSeconds`) by more than `headingDeg` for `sustainSeconds`; the reference is then reset to the heading. (If `onSurfaceChange` were true, an adopted surface change would count too; it is false.) A path change clears the label memory and pending context, re-arms the thin notice and starts a new start summary. It does **not** clear the world memory.

### 7.13 Beeps (parking-sensor)
- **Who:** only a **collision** track: a confirmed, settled danger with `collision = true` and `stepsTo ≤ tones.maxSteps` (**5**, v26.1.12: farther away the speech carries the warning). v26.1.13: on a real collision course only, `beepLateralM` (0.9 m, §7.9): people at 1.2–3.0 m no longer beep. The single nearest one drives the beeps each frame. Features, context and non-collision dangers never beep. Beeps are independent of the world memory and of muted phrases.
- **Sound:** the pitch and duration are those of the tone's **kind** (below, §7.16: left 660 Hz, center 880 Hz, right 1100 Hz, 80 ms by default); the interval is linearly interpolated from `bySteps` by `stepsTo` (clamped at the table ends) and scaled by `intervalS / bySteps(maxSteps)` of the kind (the profile's interval is the one at 5 steps; 0.5 s = the table as it is). A faster stream does not wait out a slower previous interval.
- **Very close:** at `stepsTo ≤ continuousSteps` a continuous tone: gapless back-to-back tone events of `continuousChunkSeconds` (not scaled by the interval; the events carry `"continuous": true` and the player keeps their length whatever the profile's duration).
- **Stopping:** the beeps stop when the track stops being a collision (passed, left the lane). A track that is merely absent from a frame keeps beeping for `holdSeconds`.
- **Episodes:** per continuous stream of one track (gap < `episodeGapSeconds`) the output also contains one `beeps` event (§7.15).
- **Kinds (v26.1.16).** Every `tone` and `beeps` event carries `kind`, one of the six sound kinds: `collision-left` / `collision-center` / `collision-right` (the parking beeps above; before v26.1.16 `collision`), `proximity` (v26.1.13 follow-up, below), `crosswalk-in` / `crosswalk-out` (v26.1.14, last bullet; before v26.1.16 `crosswalk-enter` / `-exit`; the player still maps the old names so that old runs sound the same).
  - **Sector of a collision tone** (`collision_kind`): from the **clock quarter** of the driving item at that tone (`tones.centerQuarters` 1): **center** = 11:45–12:15 (quarters −1…+1), **left** = 9:00–11:30 (≤ −2), **right** = 12:30–3:00 (≥ +2). The user wrote left "9:00–11:45" and right "12:15–3:00"; the shared boundaries 11:45 and 12:15 belong to the center. An item that changes sector switches kind per tone, and its episode is split there (`beeps` episodes are per track **and kind**); the episode text is `beeps · <left|center|right> · <label> at <clockText> · <first>→<min> steps`. The stereo `pan` by bearing is unchanged.
  - **Who gets `proximity`:** a person or animal (`_Item.proximity`, set in `_assign_role`; no role, so speech and context are untouched) that is measured **approaching** (motion state, not unknown / standing / receding), within `proximitySteps` (5) and \|lateral\| ≤ `proximityLateralM` (2.6 m), on **no collision course**, confirmed for `confirmFrames` frames. Riders and vehicles never (they are spoken early and beep on a course). Not while we stand still.
  - **Sound:** `tones.proximity`: 440 Hz sine, gain 0.25, a slow attack, one **double chirp** (`chirp.count` 2 sines of `durationSeconds`, `chirp.gapSeconds` apart) every `intervalSeconds` (the profile's `intervalS`, 1.2 s), a fixed rhythm (it does not encode distance; speech did at 5–10 steps). The `tone` event carries `frequencyHz`, `gain` and `chirp`; the nearest such person drives the stream, a lost track holds for `holdSeconds`.
  - **Switching:** the two never play at once. While a collision stream is active (held tracks included) no `proximity` tone is emitted; a track that turns into a collision course continues as collision beeps. Episodes are per kind and track; the `proximity` episode text is `soft · <label> at <clockText> · <first>→<min> steps`.
- **Crosswalk enter / exit (v26.1.14, `_CrosswalkTracker`, `_seed_fraction`, `_crosswalk_tones`).** A sound for stepping onto and off a crosswalk.
  - **State:** per frame the share of `crosswalk`-class cells in the **seed box** (`surfaces.seedBox`, bottom centre: what is under the feet; a crosswalk merely seen ahead never counts, and a crossing that runs along the walking direction keeps counting). **In:** share ≥ `crosswalk.enterFraction` (0.3) for `enterSeconds` (0.5 s) without a break, never while the user stands still (`stationary` restarts the hold). **Out:** share ≤ `exitFraction` (0.15) for `exitSeconds` (0.7 s) without a break (also while standing). Between the two levels the state holds, so a gap between stripes does not end a crossing. The decision frame is the event time.
  - **Sound (`tones.crosswalk`, kinds `crosswalk-in` / `crosswalk-out`):** 330 Hz by default (collision 660–1100, proximity 440), gain 0.5 (the collision peak). `crosswalk-in`: one tone of 600 ms (`in.count` 1). `crosswalk-out`: the same deep tone twice, 200 ms each, `intervalS` (0.12 s) apart. The `tone` event carries `frequencyHz`, `durationSeconds`, `gain` and `chirp` {count, gapSeconds, attackSeconds}, `role: "feature"`, `pan 0`. Each has one `beeps` episode (`kind` the same, `tEnd` = end of the sound, text `⇥ crosswalk in · one deep tone` / `⇤ crosswalk out · two deep tones`) for the review panel and the timeline.
  - **Overlap:** never dropped. A crosswalk tone that would sound over a collision or proximity tone waits for it to end, at most `maxOffsetSeconds` (0.3 s).
  - The speech phrase "crosswalk at 12 in N" is unchanged; the surface logic and its evidence (`under_last`) are unchanged.

### 7.14 Surface  (class `_SurfaceTracker`)
- The adopted surface changes only when **all** hold:
  1. the new group holds ≥ `majority` of the frames of the last `windowSeconds`, and the window spans ≥ `minPersistSeconds`;
  2. the new group has run uninterrupted for ≥ `minPersistSeconds`;
  3. **evidence:** a curb or crosswalk really passed *under* the user (`requireCrossingEvidence`): an item of class curb/crosswalk with `lane_hit`, its contact within the bottom `passUnderRows` rows, bbox width ≥ `passUnderMinWidth`, whose track was gone within `passUnderGoneSeconds`; the track must also have **crossed the lane** (§7.9: role feature with `lane_hit`, not along the path, for ≥ `confirmFrames` frames) so that a curb that merely flickers under the feet is not evidence, and the evidence must belong to the change: no earlier than `evidenceLookbackSeconds` (3 s) before and no later than `evidenceLeadSeconds` (2 s) after the start of the new group's stretch (its first frame in the window, flickers of ≤ 1.5 s bridged). Review 4: a crosswalk at the left edge of the lane 7 s before and one 5 s after the road run began had backed the wrong "road" at 159.8 s.
- Otherwise the old surface is kept silently: the region still follows the model, nothing is spoken and no memory is reset.
- The **first** surface of a run needs only the majority and is adopted silently (`announceFirstSurface: false`).
- A change is spoken only if the new or the old group is in `announceGroups` (road, rail); sidewalk ↔ bike lane is silent. The phrase is the group's label; it waits for the gap and for dangers.

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

### 7.16 Sound profile  (`lab/sounds.py`, `collision.resolve_sounds`; v26.1.16)
The Lab-wide pitch / duration / repeat interval of every notification sound and the speech speed. One profile for all browsers, stored server-side in `LAB_DIR/display/sounds.json` (`{"kinds": {kind: {field: value}}, "speechRate", "updatedAt"}`, **overrides of the defaults only**, no file at the defaults; it survives version wipes like the mask display, §11).
- **Kinds and defaults** (`collision.json` `tones.sounds`): `collision-left` 660 Hz, `collision-center` 880 Hz, `collision-right` 1100 Hz (80 ms; interval 0.5 s), `crosswalk-in` 330 Hz 600 ms (one tone, no interval), `crosswalk-out` 330 Hz 200 ms ×2 with a 120 ms gap, `proximity` 440 Hz soft double chirp (120 ms, period 1.2 s); `speechRate` 1.0. Ranges (`soundRanges`): pitch 150–2000 Hz, duration 20–1500 ms, interval 0.05–5 s, speech 0.5–2.0; values are clamped, not refused.
- **`intervalS` means:** collision kinds — the repeat interval at 5 steps (the far end); the whole `bySteps` table is scaled by `intervalS / 0.5`, the continuous chunk is not. `crosswalk-out` — the gap between its two tones. `proximity` — the repeat period. `crosswalk-in` — unused.
- **Who reads it:** the collision pass (`analysis.collision_pass` -> `run_collision(sounds=profile)`) bakes pitch, duration and interval into the tone events; the player re-applies pitch, duration and speech speed live (§9), so only an interval change needs `POST /api/runs/{id}/collision`. A run therefore carries the profile of its last pass in its events; the player's live profile wins for pitch and duration.
- **API:** `GET` / `PUT` / `DELETE /api/sounds` (§8).

## 8. REST API  (`lab/server.py`, FastAPI)

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
| `POST /api/runs/{runId}/collision` | | re-runs the collision pass with the recording's current settings; `{"version", "elapsedSeconds", "hazards": "/api/runs/<id>/hazards.json", "events": "/api/runs/<id>/events.json"}`; 409 if the run is not done; 503 if the collision module is missing |
| `GET /api/runs/{runId}/hazards.json` · `events.json` | | the files (`Cache-Control: no-cache`). The UI uses only `events.json`. |
| `GET /api/runs/{runId}/hazards?from=<s>&to=<s>` | both required | `{version, settings, gridW, gridH, egoAvailable, from, to, frames}`, the frames with `from ≤ t ≤ to`. 422 if `to < from` or the window is over 600 s |
| `GET /api/runs/{runId}/frame?t=<s>` | | `{"frame": ...}`, the analysed frame with the largest `t ≤ s`; 404 before the first frame or more than 1 s after the last |
| `GET /api/runs/{runId}/frames/{i}/mask.png` | | the mask PNG (`Cache-Control: max-age=86400`); fallback only |
| `GET /api/runs/{runId}/frames/{i}/classes.png` | | 8-bit grayscale PNG of `grids[i]` (positional, frame-aligned class ids), `Cache-Control: max-age=86400`; 404 unknown frame, 409 run not done. `grids.npz` cached for 2 runs, keyed by mtime |
| `GET /api/runs/{runId}/depth/{i}.png` | | 8-bit RGB PNG of `depth.npz[i]` (120×68): turbo colormap on log depth, **near = warm (red)** — relative depth normalised per frame between its 2nd and 98th percentile, metric depth over 0.5–30 m; `Cache-Control: max-age=86400`; 404 when the run has no depth or `i` is out of range |
| `GET /api/runs/{runId}/classes` | | `{mapping, classes: [{id, name, level}], levels: [{level, label, color, opacity}]}` from the safety mapping matching the run's `classNames` (`segmentation.find_mapping`, no GPU); default opacity 0 for level 0, else 1; 404 if no `classNames` or no mapping matches |
| `POST /api/runs/{runId}/worldmap` | | v26.2 step 1 spike (§8.1): builds `worldmap.npz` from the stored files, synchronously, pure numpy (never the GPU queue); `{"version", "elapsedSeconds", "frames", "msMean", "msP95", "worldmap": "/api/runs/<id>/worldmap"}`; 404 without `grids.npz` / `hazards.json`; 409 run not done |
| `GET /api/runs/{runId}/worldmap` | | `{"exists": false}` or `{"exists": true, "frames", "cellM", "origin": [col, row], "width", "height", "msMean", "msP95"}` |
| `GET /api/runs/{runId}/worldmap/{i}.png` | `alpha=binary` (default) \| `conf` \| `gray` | the ego-centric snapshot of frame `i` (§8.1); 404 no map yet or unknown frame |
| `GET /api/runs/{runId}/worldmap/pose.json` | | `{"t": [...], "pose": [[x, y, headingDeg], ...]}` |
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
| `GET /api/reviews/export?recording=<id>` | omit the query for all recordings | the export (§10) |

- The windowed `hazards`/`frame` endpoints (a full-length run's `hazards.json` is ~120 MB) parse `hazards.json` once per run, keep an LRU of 2 runs and invalidate when the file's mtime/size changes (a collision re-run rewrites it). They return 409 if the run is not done and 404 if `hazards.json` does not exist.
- The collision pass calls `collision.resolve_settings(config, mount, hfovDeg, cameraHeightM, stepLengthM)` and `collision.run_collision(grids, times, class_names, config, settings, motion)`.
- Unknown recording or run → 404.

### 8.1 World map  (`src/worldmap.py`, `common/config/worldmap.json`, `lab/analysis.worldmap_pass`; v26.2.0 spike, read by the collision pass since v26.2.1)

A fused, ego-centric bird's-eye map built from the stored files of a run (`grids.npz`, `depth.npz`, and the horizon / ego block / calibration of `hazards.json`); no inference. Since v26.2.1 the collision pass runs the same incremental update online (`worldmap.WorldMap.step` with the frame's rounded ego values, causal), so the stored `worldmap.npz` equals the map the collision rules saw (test `test_online_map_equals_the_offline_build`); cost about 6 ms/frame. File `runs/<id>/worldmap.npz` (compressed): `classes` (N,200,200) uint8 (255 = unknown; class ids of the run's `classNames`), `conf` (N,200,200) uint8, `t` (N,), `pose` (N,3: x east m, y north m, heading deg; 0 = initial direction, + = right turn), `cellM` (0.10), `origin` ([100, 180] = the user's column, row), `ms` (N, per-frame cost of observation + fusion + snapshot).

- **Snapshot geometry:** 200 × 200 cells of 0.10 m (20 × 20 m), heading-up: forward is up, user at column 100 / row 180 (18 m ahead, 2 m behind); cell (row, col) is `(180 - row) · 0.1` m ahead and `(col - 100) · 0.1` m right of the body centre line (the same lateral convention as `hazards[].lateralM`).
- **PNG encoding** (`worldmap/{i}.png`): default 8-bit **RGBA**, R = G = B = class id (the browser reads the red channel exactly as for `classes.png`), alpha 255 where the cell is known and 0 where it is unknown. `alpha=conf`: alpha = confidence 0..255 (canvases premultiply: the class id is only exact where alpha is 255; use it for display only). `alpha=gray`: single channel, class ids, 255 = unknown (no confidence). `Cache-Control: max-age=86400`; cached server-side for 1 run, keyed by mtime.
- **v26.2.3:** object bases are placed by `settings.objectDistance` (`groundfuse.resolve` per base pixel, with the frame's `depthCorrection`, §7.3b) and `useHorizon: false` projects the surfaces through the depth map instead of the horizon (no depth: the horizon path stays, no object bases); `POST /api/runs/{id}/collision` rebuilds a `worldmap.npz` that already exists.
- **Projection:** surface classes (`worldmap.json` `classes.surface`) by inverse ground-plane sampling with the collision geometry (`focal_px`, the `ground_distance_m` / `lateral_m` formulas inverted, camera height x scale, `lateralOffsetM`, per-frame `horizonY`; scale 1.0 when `distanceSource` is depth, else the frame's gait `scale`). Objects (`classes.object`): only their base pixels (lowest pixel of each vertical run), at depth under the pixel x the frame's `depthScale` (the metres `distanceM` uses) when the run has depth, else at the ground distance of the row (only bases with surface below). Movers (`classes.mover`) are never mapped.
- **Pose:** `collision._WorldMemory.advance` fed with `ego.speedMps` (0 when `stationary`) and `ego.headingDeg`.
- **Fusion:** world window 64 m (0.10 m cells, recentred when the user is within 22 m of an edge); class votes weighted by range (`1 / (1 + (d / 8 m)^2)`), exponential decay (half-life 6 s, implemented lazily), cell class = argmax when the decayed weight is above `weightFloor` (0.25); `conf` = 255 · min(1, weight / 3) · vote share.
- **Metrics:** `tools/worldmap_metrics.py <runId>` (cost, wall straightness, re-observation spread, drift proxy, extrusion; `--set key=value` config overrides); `tools/worldmap_render.py <runId> <outDir> <t>...` (snapshot next to the camera frame).

## 9. Frontend  (`lab/static/`: `index.html`, `style.css`, `app.js`, `js/*.js`; vanilla JS, no build step)

**Layout (v26.2.0):** header (title, version badge from `/api/version`, run badge). Grid areas: `#viewer` (video stage + transport + seek bar on the left, `#secWorldmap` on the right; columns 16fr:9fr so the square map is as tall as the 16:9 video), `#sidebar` (Recordings, Analyse, Collision settings, Past runs), `#main` (Audio, Overlay, Sounds, Classes, timeline, role chips), `#reviewPanel`.
- >= 1200 px: columns 320 px | 1fr | 380 px; row 1 = viewer over columns 1-2, row 2 = sidebar | main; the review panel in column 3 spans both rows (sticky, own scroll, full viewport height). 900-1199 px: viewer full width on top, then sidebar | main, the review panel below. < 900 px: one column: video, world map (square, up to 480 px), sidebar, main, review (the Recordings section collapses after selecting).
- No horizontal page scroll at 390 px: wide tables (Sounds: `.snd-scroll`) scroll inside their own wrapper. E2E: `test_worldmap.py` layout tests.
- State is kept in the URL hash `#rec=<id>&run=<runId>&t=<s>` and restored on load.

**Library and proxy:** each recording shows duration, size, fps, chapter count and a proxy tag; "Build proxy" / "Retry build proxy" starts a build; the list polls every 2 s while a proxy builds. The video is attached once the proxy is ready.

**Analyse panel:** **Orientation** (`Landscape` / `Portrait`, above Resolution, saved per recording with the Camera side; Resolution labels follow the window: `inputSizesPortrait` for portrait; changing Orientation or Camera side loads the done run of the same range / fps / resolution / model / depth made with that window if there is one, else the next Analyse creates a new run; the "already analysed" note and Re-analyse still apply), range start/end (seconds, mm:ss or hh:mm:ss; default `0 → recording duration`; "from playhead" buttons; loading a run sets the range to the run's), model (default pre-selected), **Resolution** (`544p`–`736p`, default `736p`; each option reads e.g. `576p · 1024×576` from the recording's `inputSizes`, and options the recording cannot do without upscaling are disabled; loading a run selects the run's resolution), FPS (default 6), **Depth** (`Off` / `DA3 Small` / `DA3 Base` / `DA2 Metric Outdoor S` / `UniDepth v2 S`, from `depthModels`, **default DA2 Metric Outdoor S**; sent only when not off; loading a run selects its depth), **Device** (`GPU` default / `CPU`, always sent as `device`, remembered in localStorage `hackeye.lab.device`; CPU is much slower, for when the GPU is busy; the run badge and past-runs list append ` · CPU` for CPU runs). The run badge and the past-runs list show the run's input size (`inputSpec`) and depth model. The recording settings have **Lens** (`projection`, Auto shows the resolved lens) and **Distance** (`distanceSource`); changing Distance on a depth run highlights "Re-run collision" for a one-click A/B. Analyse saves the settings, then POSTs the run.
- **Progress and cancel:** whenever a recording is selected (or restored from the hash) the UI checks its runs for a `queued`/`running` one — including one started in another tab or on another device — and follows it: shows the progress bar (polling every 1 s), disables **Analyse** (the reason in the tooltip) and shows **Cancel analysis**. On completion it behaves as for a run started on this page (enables Analyse, lists the run, loads it). A 409 from Analyse follows the in-flight run. **ETA (v26.1.14 follow-up, client only, `static/js/eta.js`):** the bar label is `queued`, `running 3% · estimating…` (first ~10 s or < 2 % progress since the page started watching), `running 42% · about 3 min left` (`about N s` in 5 s steps under 1 min, `about N min` under 1 h, `about H h MM min` above) or `running 42% · stalled?` (progress unchanged for > 60 s). The rate comes from a sliding 60 s window of (time, progress) polls; a page opened mid-run (first poll already >= 2 %) falls back to the average since the run's `startedAt` (if run.json ever has it) or `createdAt`. The estimate is smoothed (EMA 0.3); the shown value counts down by itself, is re-based at most every 5 s or when the estimate differs by >= 10 %, and never creeps up by < 10 %. The same text is the status tag of the active run in the Runs list and the Analyse button's tooltip.
- Past runs: click a done run to load it; cancelled/error runs only show a message; an active one is followed.
- **Collision settings:** your height (default 1.78 m, user correction 2026-10-25), camera side / location, mount, HFOV, camera height (m), step length (m), lens, distance source, and (v26.2.3, below Lens / Distance) **Object distance** (`Depth | Ground contact | Ground + depth`, `#objDistSel`) and **Horizon** (`On | Off`, `#horizonSel`); both saved per recording with the settings; **Re-run collision** also rebuilds an existing `worldmap.npz` of the run. Empty = default; the placeholders show the resolved values (`118 (default)`, `1.3 (preset)` following the mount, `auto (default 0.7)`). **Re-run collision** saves the settings, re-runs §7 on the loaded run, reloads events and hazards, and reports compute time, speech and beeps counts.
- The run badge shows run id, range, fps, frame count, model, ms/frame, collision version, and "no motion track" when there is none.

**Windowed hazards:** the page never loads the whole `hazards.json`. It holds the frames within ±90 s of the playhead, prefetches the next stretch when the playhead is within 30 s of the window's end, and refetches on a seek outside the window (failed fetches back off 3 s). Overlay, HUD and frame stepping use the window; the timeline and review panel use `events.json` (small).

**Overlay** (canvas over the video content; frame-synchronised via `requestVideoFrameCallback`; drawn only inside the run's range). Each layer is a checkbox:
- **Mask:** coloured **in the browser** from `classes.png` through a lookup table class → (shown? → level → colour × level opacity), multiplied by the opacity slider (default 0.45), drawn nearest-neighbour. Edits in the Classes & safety levels panel (§9.3) repaint instantly without refetching. ±20 frames are preloaded; an earlier mask is reused only if < 0.5 s old. If `/classes` or a frame's `classes.png` fails, that frame falls back to the pre-rendered `masks/<i>.png`.
- **Window:** for a portrait run, everything outside the window rectangle (`run.window` over `srcW` × `srcH`) is dimmed (black 55%) and a thin white frame marks the window; mask, lane, region, outlines and boxes are in full-frame coordinates, so they fall inside it. The runs list and the run badge read `portrait · left` / `landscape · center`.
- **Region:** outline polygon from `frame.region.rows` (left edge bottom→top, then right edge top→bottom), thin white line, `region.label` near its top.
- **Lane:** the `frame.lane` polygon, semi-transparent red.
- **Horizon:** line at `horizonY`, solid yellow if `horizonEstimated`, dashed if the preset fallback.
- **Depth:** a Depth overlay toggle, enabled only for depth runs, draws `depth/{i}.png` at 50% opacity under the mask and items (a frame within 0.5 s is reused while loading; a 404 is skipped). Item labels add `· ground X m · depth Y m` when the item has `depthM`.
- **Items:** drawn as **outlines** (the item's `outline` polygon, 15% alpha fill) or **boxes** (`bbox`), chosen with the **Shapes** select (default Outlines, remembered in localStorage `hackeye.lab.shapes`); items without an outline always use their box. Each item is coloured by role — danger orange `#ff8c1a` (final urgency red `#ff2d2d`), feature cyan `#22d3ee`, context light grey `#c9ced6`, none dim grey `#6b7280` drawn thin. Label `"<label> · <clockText> · <n>st"` (steps rounded; context shows only `"<label> · <clock>"`). `none` labels show only when "Show all" is on. A dot marks the contact point of non-`none` items. Dim items are drawn first so dangers end up on top.
- **HUD** (top-left of the player): `speed` (m/s and km/h, `(est)` when estimated), `cadence` (steps/min = `cadenceHz × 60`), `step` (m; `(default)` for the prior, `(set)` for a per-recording value), `heading` (degrees, signed). `—` for unknown values; "no ego data (re-analyse)" when a frame has no `ego`. The gait scale is in `hazards.json` but not shown.

**Transport:** play/pause (Space), previous/next **analysed** frame (← / →; falls back to one video frame without a run), speed 0.25–2× (`[` / `]`), seek bar, `m` mutes all. Keyboard shortcuts are ignored while typing in an input, select or textarea.

**World map panel** (v26.2 step 1 spike, `js/worldmap.js`; `#secWorldmap` is always visible, right of the video in `#viewer` (v26.2.0; the legend is the canvas tooltip, the Build map button / `#wmInfo` / `#wmStatus` sit in a slim bar under the canvas)). Canvas `#wmCanvas` (square, fills its column, re-sized and redrawn at devicePixelRatio by a ResizeObserver) shows the fused snapshot of the frame at the playhead (§8.1; frame found by `pose.json` `t`, none outside the run range): cells coloured through the mask's class LUT (`overlay.style`, so colours, hidden classes and level edits follow the Classes panel; unknown cells stay background), the user marker (col 100 / row 180), the ±0.6 m corridor (red box) to 10 steps, clock spokes from the marker (hours 9..3 to the canvas edge, quarter hours at 7.5° to 10 steps; 1 h = 30°, 12 = straight ahead, as `clock_quarter` / `clock_text`), hour labels at the outer spoke ends, faint rings at every step to 10 steps with tick marks where the quarter spokes cross them, range rings every 5 steps labelled `N st` (step = the frame's `ego.stepLengthM`, default 0.7 m), and the current hazards frame's items at `(lateralM, distanceM)` (dots coloured by role, movers = diamonds with a white outline, role danger = extra ring, role none dimmed; v26.2.2: a coasting mover is a hollow dashed diamond, an item snapped to a solid area has a dashed line from its raw position to the corrected one). Toggle `#wmRules` ("wall lines", remembered in localStorage): the fitted wall lines (yellow), face cells (magenta) and edge cells (cyan) of the walls judged on the map. `#wmBuild` ("Build map", visible only when `GET /worldmap` says `exists:false`) calls `POST /worldmap` and `#wmInfo` shows the frame count, mean / p95 ms and, after a build, the elapsed seconds. Snapshots are fetched on every seek / playhead change when paused and at most 6 per second while playing (latest wins), decoded to class grids and kept in a 24-entry cache. E2E: `test_worldmap.py` (build on the session run, snapshot request 200, canvas non-empty, hover readout `#wmReadout` `12 · 5.0 st · 3.6 m` style: clock text · steps · metres of the pointed point, `behind` when below the marker).

**Sound tuner** (v26.1.16, `js/sounds.js`; panel `#secSounds` in the **middle section**, `#main`, under the Audio / Overlay panels). One row per sound kind (`#sndRows tr[data-kind]`, order: collision-left, -center, -right, crosswalk-in, crosswalk-out, proximity): a **low ↔ high pitch slider** on a log scale (0…1000 → 150…2000 Hz, shown as `N Hz`), a **duration** field (ms), a **repeat interval** field (s; disabled for crosswalk-in, which is one tone) and a **▶ test** button that plays that sound inside the click with the values shown (`AudioEngine.testSound`: collision kinds ~2 s of beeps at the 5-step rate, proximity chirps every interval, crosswalk-out two tones `interval` apart, crosswalk-in one; panned left / right for the sector kinds). Below: **Speech speed** (`#sndSpeech`, 0.5×–2.0×, default 1×) with a ▶ test (speaks "speech test" at that rate). Every change updates the player at once and is saved to the server profile after a 400 ms debounce (`PUT /api/sounds`; status `#sndStatus`: Saving… / Saved for every device.). **Live vs re-score:** pitch, duration and speech speed apply to playback live — the player overrides each tone event's `frequencyHz` / `durationSeconds` by its kind (a continuous chunk keeps its length) and multiplies the speech rate by the speed (clamped 0.5–2); the **intervals** shape the tone schedule, so an interval change shows **Apply timing to this run** (`#sndApply`), which saves, re-runs the collision pass (`POST /api/runs/{id}/collision`, which reads the profile; progress in the Collision settings line and `#sndStatus`) and reloads the run. **Reset sounds to defaults** (`#sndReset`) deletes the profile. All speech guards (system-voice rule, watchdog, stuck notice, priority queue and lateness drop, client-log diagnostics) are untouched; the speed only multiplies the rate. E2E hook: `window.__labAudio` (the engine; tests clear the page's profile with `setSounds({}, 1)` so injected events sound as written).

**Audio** (`js/audio.js`, WebAudio + speechSynthesis)
- **Armed by default.** The AudioContext and speech unlock on a user *activation* anywhere on the page: `pointerup`, `touchend`, `click` or `keydown` (not `pointerdown`: on Android Chrome a touch `pointerdown` is no activation). The listeners stay until the context is `running` and the silent speech prime was accepted, and afterwards resume a context the browser suspended again (`suspended`/`interrupted`; also on `visibilitychange`). Tones are scheduled only while `ctx.state === "running"`. The button toggles "🔊 Audio on" / "🔇 Audio off". Checkboxes: Speech, Beeps, Hear review edits, Mute all, Video sound; sliders: volume (0.8), audio delay (±300 ms).
- **Beeps** come only from `tone` events: sine waves with a 5 ms attack/release, scheduled on the audio clock ~0.25 s ahead of the playhead, panned by `pan`, at `frequencyHz`/`durationSeconds`. v26.1.13 follow-up: the sound comes **from the event**: `gain` (default 0.5, the collision peak), and `chirp` {count, gapSeconds, attackSeconds} makes the event `count` sines of `durationSeconds` each, `gapSeconds` apart, with `attackSeconds` edges (the `proximity` kind: 440 Hz, 0.25, double chirp). The `crosswalk-enter` / `crosswalk-exit` kinds (v26.1.14) use the same event fields (330 Hz, 0.6 s ×1 / 0.2 s ×2 with a 0.12 s gap); `audio.js` needed no new code. The Beeps checkbox covers all kinds. `__labAudioLog` has one tone entry per event with `kind` and `gain` (and `freq`).
- **Speech** is spoken when the playhead *crosses* a speech event's time during normal playback (never on seeks); the speech rate follows the playback rate (0.5–2). **Player queue (v26.1.15, review 7: "if speech is to start out of time, don't"):** `AudioEngine` owns the queue; only one utterance at a time is handed to `speechSynthesis`. **Priority** `final` 5 > `danger` (incl. approaching) 4 > `feature` / thin notice 3 > `surface` 2 > `context` 1 (unknown roles, e.g. an added "other", = 1; `SPEECH_PRIORITY`). **Preemption:** a phrase of higher priority than the one speaking cancels it (`cancelNow("preempt")`; the cancelled utterance is retired first, so the watchdog, the retry and the stuck notice never see it; an utterance cut off before it was heard goes back to the queue) and is spoken at once (on Android after 60 ms, like the watchdog retry). Equal or lower priority waits, best first, oldest first. **No late speech:** a waiting phrase that cannot start within `SPEECH_LATE_S` (1.0 s of media time, judged against the event time less the user audio offset) is dropped (`speech-dropped-late`). "Hear review edits" phrases take the same path (same speech list). Every phrase of one tick window is queued (before, only one of them was kept). Robustness: an utterance the engine silently lost (`speechSynthesis` idle for 500 ms after `speak()` with no end event: `utt-lost`) or one that never ends (4 s + 150 ms per character at rate 1: `utt-hung`, then cancelled) is let go, so one missing end event cannot block the queue. The "Test speech" button still speaks directly inside the click. Any discontinuity (seek, pause, rate change, end, emptied) drops everything scheduled and cancels speech; a buffering stall (`waiting`/`playing`) only restarts the tone schedule.
- **Review preview** ("Hear review edits", on by default): playback merges the recording's **added** speech annotations as speech events at their `t`, skips system speech events with a ⊘ verdict, plays **added beeps** as parking-style tones (every 0.5 s, 780 Hz, 0.08 s) and silences the tones of beeps episodes with a ⊘ verdict. Re-merged whenever reviews change. Off = only the system's audio.
- **Pronunciation map** (v26.1.12, Lab only, `PRONUNCIATIONS` / `pronounce()` in `audio.js`): the text given to `SpeechSynthesisUtterance` goes through a word map, `\bcurb\b` → `kerb` (review 5: the Mac voice read "curb" as "tarmac"). The event text, the review rows and `__labAudioLog` keep "curb"; the client-log `speak` entry has both: `text` and `spoken`.
- **E2E hook:** `window.__labAudioLog` holds `{at, mediaT, type: "speech"|"tone", text|freq, source: "system"|"added"}` for every phrase whose time the playhead crossed (v26.1.15: handed to the queue, which may preempt or drop it) and tone scheduled, plus `{type: "speech-preempted", text, by, started, source}` and `{type: "speech-dropped-late", text, lateS, role, source}`; a rejected utterance adds `{type: "speech-error", text, error, voice}` (also `console.warn`). Speech details (Chrome mobile): cancel() only when something is speaking or pending; `resume()` before `speak()` if the synthesis is stuck paused; on Android a `localService` English voice is preferred, and a voice that errors is dropped and the phrase retried once with lang `en-US` only.
- **Speech robustness (Chrome Android).** (1) The silent whitespace prime (`" "` at volume 0) is **skipped on Android** (its TTS engine may never fire end/error for it and the queue stays stuck behind it; Chrome only needs the sticky activation of the gesture); desktop still primes. (2) Watchdog: an utterance with no `onstart` within 1.5 s while `speechSynthesis.speaking || pending` is cancelled and spoken again once, without the voice; the voice is dropped for good (`voiceFailed`) only if that retry starts. The 1.5 s timer runs only while none of our utterances has started and not ended: a phrase queued behind a speaking one arms it when the one ahead ends/errors, and a watchdog or the pre-phrase clear never cancels an utterance of ours that has started. Before each phrase a busy queue that holds nothing of ours, or only an utterance older than 1.5 s (since its timer was armed) that never started, is cancelled; a paused synthesis is resumed. **System voice rule (`speechPlan`, v26.1.11 follow-up 4):** if the platform default voice (`getVoices()` entry with `default:true`, else the first listed) is English (`/^en([-_]|$)/i`), mode `system`: utterances set neither `lang` nor `voice`, exactly as before v26.1.11. Otherwise (e.g. an iPhone listing Joana pt-PT first) mode `english`: `lang` `en-US` + the ranked voice below (Samantha on iOS); while the voice list is still empty: mode `english`, `lang` alone. The `voices` client-log entry carries `mode` (`system`/`english`) and `chosen`. Voice ranking (`chooseEnglishVoice`, used in `english` mode): English voices only, minus the macOS novelty/Eloquence names (Albert, Bad News, Bahh, Bells, Boing, Bubbles, Cellos, Good News, Jester, Organ, Superstar, Trinoids, Whisper, Wobble, Zarvox, Fred, Junior, Ralph, Kathy, Eddy, Flo, Grandma, Grandpa, Reed, Rocko, Sandy, Shelley; name prefix, case-insensitive); then Android `localService`, the platform default voice, known natural voices (Samantha, Alex, Google US/UK English, Daniel, Karen, Moira, Tessa, Serena, Ava, Allison, Susan, Tom, Nicky; "(Enhanced)"/"(Premium)" first), en-US, any en. (3) Live utterances are referenced in a Set until they end/error (Chrome GCs unreferenced ones and drops their events).
- **Test speech** button (Audio panel, `#testSpeechBtn`): speaks "speech test" inside the click and shows a toast within ~3 s: started / ended / error code / no event, voice used, voices count, speaking / pending / paused flags.
- **Stuck speech engine (notice).** Detection only, speech logic untouched: `watchdog` firing counts an utterance that never fired `onstart` (a phrase and its retry count separately); at **2 consecutive** with no `onstart` in between the speech is marked stuck, `{type: "speech-stuck", consecutive}` goes to the client log **once per episode**, and a dismissable banner (`#speechStuck`, inside the Audio panel, not a toast) appears: "Speech isn't working: the browser's speech engine isn't responding. Quit the browser completely and reopen it." + platform hint (macOS: "Quit Chrome with Cmd+Q (closing the window is not enough), then reopen it."; iPhone/iPad/CriOS: "Close the browser from the app switcher, then reopen it."; else "Close all browser windows and reopen it.") + "Beeps still work." Any `onstart` resets the counter and hides the banner (a later stuck episode shows it again). The Test speech toast points to the notice when its outcome is "no event". Seen on a Mac: Chrome reported `speaking` for the whole session, no `onstart`, a reload did not help, only Cmd+Q did.
- **Client log (remote diagnostics).** `POST /api/client-log` takes a JSON array of objects (max 200 entries, 256 KB), appends each as one JSON line `{server, ua, ...entry}` (server UTC timestamp, request User-Agent) to `<LAB_DIR>/client-log.jsonl` (container `/debug/lab/client-log.jsonl`, host `debug/lab/client-log.jsonl`; outside the version wipe set, so it survives wipes). At 5 MB it rotates to `client-log.jsonl.1` (one generation). `audio.js` batches every 2 s (`fetch` keepalive) and on `visibilitychange` hidden (`sendBeacon`): `page`/`voices` (UA, speechSynthesis present, voice count, `chosen` voice name, first 20 voices `{name, lang, localService, default}`; again on `voiceschanged`), `unlock` (AudioContext state), `prime`, `speak` {text, voice, lang, rate, volume, speaking, pending, paused before the call}, `utt-start`/`utt-end`/`utt-error` with elapsed ms, `cancel` {reason: …, `preempt`, `utt-hung`}, `watchdog`, `speech-preempted` {text, by, role, byRole, started}, `speech-dropped-late` {text, role, lateS}, `utt-lost` / `utt-hung`, `test-speech(-result)`, and one `tones` {count} summary per batch.

**Timeline:** speech ticks coloured by role (click near a tick snaps to it; click/drag seeks), beep episodes as bars coloured by role (older runs without `beeps` events show a tone-density heat row instead), the playhead. The role chips (context, surface, feature, danger, final; all on by default) filter the timeline and the review panel.

### 9.1 Notification review panel  (`js/reviews.js`)
One row per **notification** of the loaded run (a spoken phrase, or a beeps episode with a 🔔 badge, or a soft proximity episode with 🔉 and text `soft · person at 1:30 · 4→2 steps`, or a crosswalk tone episode with 🔊 and text `⇥ crosswalk in · one deep tone` / `⇤ crosswalk out · two deep tones`) plus the user's added ones, sorted by `t`; soft and crosswalk episodes are verdicted like beeps (✓ ✗ ⊘, ⊘ silences their tones in the preview; the count line counts them as beeps). Reviews load on recording select and don't need a run; verdict rows need a run.
- **Header:** `N notifications · M beeps`; counts ✓ correct · ✗ incorrect · ⊘ should-not-be-said · + added · unreviewed (= notifications of the loaded run without a matching verdict); an Export link (`/api/reviews/export?recording=…`); mini transport buttons.
- **Event row:** timestamp `m:ss.s` (click seeks and pauses), role badge (overlay colours), for beeps the 🔔 badge (`🔉 soft` for a `proximity` episode, `🔊 tone` for a crosswalk one; the row's `data-kind` is the event `kind`) and the duration, the text, and toggles **✓ ✗ ⊘**. Clicking an inactive toggle creates or changes the verdict; clicking the active one deletes it. ⊘ shows the text struck through. A note `<textarea>` shows when a verdict exists or the row is expanded (click its text); until a verdict exists, the note is a local draft. Notes autosave 600 ms after the last keystroke and on blur, with a "saved ✓" indicator.
- **Added row:** "+ added" badge (and 🔔 for beeps); inline-editable time (with "⟲" set-to-playhead and "▸" seek), for beeps an end time ("⟲" end to playhead), role select, text (≤ 300 chars), note, 🗑 delete (confirm). Moving the start of an added beeps entry keeps its length.
- **Following playback:** the row nearest before the playhead is highlighted and scrolled into view (~⅓ from the top) within the nearest ancestor that actually scrolls — the list itself on narrow layouts, `#reviewPanel` at ≥ 1200 px; never the window — and only when it is out of view, except while the user is typing in the list.
- **"Other versions (n)":** a collapsed section with verdicts that match no notification of the loaded run (other run/version); read-only apart from 🗑 (confirm).
- **Keyboard** (ignored in input/textarea/select): `c` / `x` / `r` toggle correct / incorrect / remove on the highlighted event row; `a` opens the add form.
- **Optimistic updates:** local state changes first; writes go through one serial queue; on failure `api.js` shows a toast with the server's `detail` and the panel reloads from the server.

### 9.2 Add form and auto-fill  ("+ Add notification at playhead")
- **Fields:** time, type (speech | beeps), role (context, surface, feature, danger, final, other; default danger), for beeps an end time (default start + 3 s, clamped; "end from playhead" button), text (≤ 300 chars), note. Enter submits, Esc cancels, Cancel/submit fully reset the form (the next open re-reads the playhead). The new annotation carries the loaded run's `runId` and `collisionVersion`.
- **Time follows the paused playhead:** opening the form always takes the current playhead. While the video is paused, the time field tracks every seek, frame step and pause ("↻ following playhead"). Typing in the time field stops this until the next seek, pause or "⟲ playhead" click. While playing the field is left alone. For type beeps the start does not follow (two times: use the ⟲ buttons).
- **Auto-fill** (button next to the text): fetches `GET /api/runs/{id}/frame?t=<form time>` (spinner on the button; toast if outside the run), then:
  - **Candidates:** all of that frame's hazard items ordered by role (`final` → `danger` → `feature` → `context` → `none`), then `stepsTo` ascending (nulls last).
  - **Fill:** the text from the `speech.templates` of `GET /api/config/collision` using `{label}`, `{clock}`, `{steps}` = round(`stepsTo`): final/feature/context items use their own template, everything else (danger, none) uses `danger`, and a mover with `moving === true` and positive `closingMps` uses `approach`. The role select takes the item's role; `none` becomes `danger` (a missed item is usually a missed warning). For type beeps the text is `beeps · <label> at <clock>`.
  - **Cycling:** clicking again moves to the next candidate; an indicator shows `n/N · <className> · <role>`. Changing the form time resets the cycle. The text stays editable; auto-fill only overwrites text and role, never the note. With no candidates a toast says "nothing detected at this time".

### 9.3 Classes & safety levels panel  (`js/classes.js`; view-only)
Collapsible panel under the Overlay panel. It changes **only how the mask is painted**. The shared safety mapping and the collision behaviour are untouched.
- **Levels table:** each safety level (0 ignored, 1 safe, 2 safe-ish, 3 danger, 4 death) with a colour picker and an opacity slider (0–1).
- **Classes table:** every class of the run's model (48), each with a show checkbox, its current level's colour swatch, and a level dropdown. Above it: a text filter, "Show all", "Show none" and "Reset to defaults" (with confirm; it calls the DELETE endpoints).
- **Saving:** edits preview instantly and are kept as an unsaved draft in localStorage (`hackeye.lab.classes.<mapping>`; only sections differing from the server).
  - **"Save class levels"** and **"Save level colours"** PUT their section to the Lab server (`display/<mapping file>.json`), so every device shows the same view.
  - Each button is enabled only with unsaved changes in its section. An "unsaved changes" marker and a Discard link show until it is saved.
  - On load, the server-saved view wins over defaults, and a differing local draft wins over the server (marked unsaved).

## 10. Reviews: storage, matching, export  (`lab/reviews.py`)

**Purpose:** ground truth for analysing and planning later collision versions. The user judges each notification while watching and adds notifications the system missed. **Reviews belong to the recording, not the run**: what should be notified at a recording time is stable across re-analysis. Each verdict snapshots the event it judged plus the `runId` and `collisionVersion` it came from.

**Storage** — `LAB_DIR/reviews/<recId>.json` (atomic writes; the file is deleted when its last annotation is removed; a process-wide lock serialises read-modify-write):
```jsonc
{"recording": "4929", "annotations": [
  {"id": "a1b2c3d4", "kind": "verdict",
   "verdict": "correct|incorrect|remove",          // remove = "should not be said" (kept, struck through, undoable)
   "note": "free text (<= 2000 chars, may be empty)",
   "t": 1089.84,                                    // = event.t
   "event": {"t": 1089.84, "text": "vehicle at 12 in 9", "role": "danger", "trackId": 1416, "urgency": "danger",
             "clock": 12, "type": "speech"},        // snapshot; a beeps event also has tEnd, label, minSteps; type "speech"|"beeps" (missing = speech)
   "runId": "8ab9a0e06ae3", "collisionVersion": "v26.1.13", "analysisVersion": 3,
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
- **Matching key** (verdict ↔ event of the loaded run): `(runId, collisionVersion, round(event.t, 3), event.text)`. Re-running collision with the same version reproduces identical events, so verdicts stay attached. At most one verdict per key: POSTing a second returns **409**; the client PUTs instead.
- `added` annotations are shown with every run of the recording, whatever their `runId`/`collisionVersion`.
- ⊘ on a beeps episode silences that episode in "Hear review edits".

**Validation (422 unless noted):**
- `kind` ∈ `verdict | added`. `runId`, if given, must exist (404).
- *verdict:* `verdict` ∈ `correct | incorrect | remove`; `runId` required; `event` required with `event.t` in `0..duration` and non-empty `event.text`; `event.type` ∈ `speech | beeps` if present; `event.tEnd` (if present) in `(t, duration]`. The annotation's `t` is `event.t`.
- *added:* `t` in `0..duration`; `text` required, non-empty, ≤ 300 chars; `role` ∈ `context | surface | feature | danger | final | other` (default danger); `type` ∈ `speech | beeps` (default speech); beeps need `tEnd` in `(t, duration]`; `tEnd` with speech is rejected.
- `note` ≤ 2000 characters.
- `PUT` accepts `note` and `verdict` (verdict annotations only) and `t`, `text`, `role`, `tEnd` (added annotations only). Unknown recording or annotation → 404.

**Export** (`GET /api/reviews/export`):
```jsonc
{"exportedAt": "...", "recordings": [
  {"recording": "4929", "summary": {"correct": 3, "incorrect": 1, "remove": 1, "added": 2},
   "annotations": [ { ...annotation...,
      "context": {                                   // from the annotation's run; null if it has no runId or the run's data is gone
        "frameT": 1089.84,                           // nearest analysed frame
        "items": [ ...hazards items with role != "none"... ],
        "ego": {...}, "surface": "road", "surfaceLabel": "road", "horizonY": 0.43,
        "nearbySpeech": [ ...the run's speech events within ±3 s... ],
        "nearbyBeeps": [ ...beeps episodes overlapping t ± 3 s... ]
      } } ] } ]}
```

## 11. Version-scoped Lab content  (`RnD/VERSION`, `lab/versioning.py`)

The rule: **each new version cleans up the previous version's Lab content, so it starts fresh.**
- **Version source:** `RnD/VERSION` holds one line, the current HackEye version (e.g. `v26.1.7`). It is bumped in every version commit, together with `collision.json`'s `version`.
- **Marker:** `LAB_DIR/.lab-version` = `{"version": "...", "since": "<UTC ISO>"}`.
- **At Lab startup** (before serving) `apply_version_policy(lab_dir, version_file)` runs:
  - `VERSION` missing, unreadable or empty → log an error, do **nothing**. Never wipe on doubt. A corrupt marker also means do nothing.
  - Marker missing → write it with the current version, wipe nothing (first adoption).
  - Marker version == current → nothing.
  - Marker version != current → **wipe the contents** of `LAB_DIR/runs/` and `LAB_DIR/reviews/` (only entries directly inside them; symlinks are unlinked, never followed; a `runs/` or `reviews/` that is itself a symlink is refused), then rewrite the marker and log `[lab] version A -> B: removed N runs, M review files`. If the wipe fails part-way, the marker is kept so the next start retries.
- **Kept:** `proxies/`, `recordings/` (settings), `.ultralytics/`.
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
- `tests/test_lab_device.py` (§5 `device`: parsing, run doc, id independence, model cache per device).

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
