# HackEye Lab — contracts (v26.1.9, current rules)

History, user feedback and the reasons behind each rule: see `../docs/DECISIONS.md`.

This is the single source of truth that `lab/server.py`, `lab/*.py`, `src/collision.py`, `common/config/collision.json`
and `lab/static/` are built against. It describes how things work **now**; where the code and this text disagree, fix
whichever is wrong in the same commit.

**What the Lab is:** a web UI on the headless R&D box (reached over Tailscale) that lets you pick footage from `media/`,
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
  runs/<runId>/hazards.json      collision output (§7.15)
  runs/<runId>/events.json       collision output (§7.15)
  reviews/<recId>.json           notification reviews / ground truth (§10)
  display/<mapping file>.json    saved Lab view: class→level/show and level colour/opacity overrides (§9.3); survives version wipes
  .ultralytics/                  YOLO_CONFIG_DIR
```

- Media is read from `/media` (env `HACKEYE_MEDIA_DIR`), read-only. Video extensions: `.mp4 .mov .m4v .mkv .avi`.
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
  "stepLengthM": null          // null = the prior step length (collision.json ego.priorStepLengthM, 0.70 m)
}
```

- Missing file = the defaults (`mount` = `defaultMount`, the rest null). Unknown keys in a stored file (e.g. an old `corridor`) are ignored on read and dropped on write.
- `PUT` validates (422 otherwise) and stores:
  - `mount` must be a known preset (empty/missing = `defaultMount`)
  - `hfovDeg` null or a number in [10, 180)
  - `cameraHeightM` null or a number in [0.5, 2.5]
  - `stepLengthM` null or a number in [0.3, 2.0]
- Step length is **never estimated from the footage**: steps are `distance / stepLength`, where the length is the stored
  value or the prior (§7.7).
- The Lab saves the settings before starting an analysis and before every collision re-run, so the post-inference collision pass always uses the stored settings.

## 5. Analysis runs  (`lab/analysis.py`)

**Request:** `{"recording": "4927", "start": 60.0, "end": 120.0, "model": "/hackeye-models/Yolo26m-sem-HackEye20261012-544.pt", "profile": "default", "fps": 6.0}`

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
- `end` is clamped to the recording duration (the clamped value is stored and hashed). Must satisfy `0 ≤ start < end` and `0 < fps ≤ 60`. `model` must be one of `GET /api/models`. Violations → 422.
- **`runId`** = first 12 hex chars of sha1 over the canonical JSON (sorted keys, compact) of the normalised request **plus `"analysisVersion": 2`**, followed by `|<model file mtime>`. A finished run with the same id is reused.
- **`analysisVersion`** is 2: the run has an ego-motion track (`motion.npz`). `run.json` and the review annotations record it.

**One run per recording.** While any run of the **same recording** is `queued` or `running`, `POST /api/runs` returns
**409** `{"detail": "Analysis already running for <rec> (run <id>, <pct>%)"}`. An identical request returns that in-flight run
instead; an identical request for a done run returns the cached run. Other recordings queue as usual (FIFO, one GPU job at a
time). A run.json left `queued/running` by a crashed process (no live entry) is redone. While a version cleanup is in progress
(§11) every submission is refused with 409.

**Per sampled frame** (times `start + k/fps`, `k = 0 … ceil((end − start)·fps) − 1`, i.e. `< end`; decoded sequentially,
crossing chapter boundaries; the stored `t` is the exact time of the source frame used):
1. BGR→RGB, then `letterbox_with_meta(rgb, spec.dst_w, spec.dst_h)`.
2. `SegmentationModel.predict_class_grid(...)` (it hands the RGB array to Ultralytics as BGR via `models.to_ultralytics`, because `predict()` assumes numpy input is BGR), then `grid_from_semantic_mask(class_ids, meta)`.
3. **Crop the padding:** keep rows `[round(pad_y), round(pad_y + src_h·scale))` and the matching columns. Resize nearest-neighbour to `GRID_W = 240` × `GRID_H = round(240·src_h/src_w)`, `uint8`.
4. Write `masks/<i>.png`: an RGBA image at grid size; pixel colour = `SAFETY_LEVELS[level]["color"]` with alpha 255; safety level 0 (ignored) is fully transparent.

**Ego-motion track:**
- For **every source frame** from the first sampled frame up to (not including) `end` — all ~24 fps, not only the sampled ones — convert to grayscale at 160×90 (`cv2.resize`, `INTER_AREA`, float32).
- `(sx, sy), _ = cv2.phaseCorrelate(prev, cur, hanning)`; store `dx = sx/160`, `dy = sy/90`: the image-content shift between consecutive frames, normalised to frame size. The first frame gets `dx = dy = 0`. The track continues across chapter boundaries.
- **Sign:** `dx > 0` = content moved right = the camera turned left. `dy > 0` = content moved down = the camera moved up.
- Skipped frames are decoded with `grab()` and `retrieve()`d only for this track; full-resolution conversion and inference happen only for sampled frames.
- Output `motion.npz`: `t` float64 (M,) recording seconds, `dx` float32 (M,), `dy` float32 (M,).

**`grids.npz`:** `grids` uint8 (N, GRID_H, GRID_W), `t` float64 (N,) recording seconds, `index` int32 (N,).

**`run.json`:**
```jsonc
{
  "id": "a1b2c3d4e5f6", "request": {...as above, normalised...}, "analysisVersion": 2,
  "status": "queued|running|done|error|cancelled", "progress": 0.0, "error": null,
  "createdAt": "2026-10-16T12:00:00Z", "finishedAt": null,
  "frameCount": 360, "motionFrames": 1439, "gridW": 240, "gridH": 135,
  "srcW": 1920, "srcH": 1080,
  "inputSpec": {"w": 960, "h": 544, "description": "..."},
  "modelName": "Yolo26m-sem-HackEye20261012-544.pt",
  "classNames": ["animal", "barrier", ...],     // from the model, in id order
  "msPerFrame": 123.4, "seekSeconds": 0.3,
  "collisionVersion": "v26.1.7"                   // version of the last collision pass
}
```

- After inference the runner immediately does a collision pass (§7) with the recording's current settings, then sets `done`. If the collision pass fails, it is logged and the run is still `done` (without hazards/events).
- `motion` is loaded from `motion.npz` when present, else `None` (then ego estimates and the world memory are unavailable).
- `POST /api/runs/{id}/collision` re-runs only the collision pass from `grids.npz` + `motion.npz` with the recording's **current** settings and rewrites `hazards.json`, `events.json` and `collisionVersion`.

**Cancellation:** `POST /api/runs/{id}/cancel`.
- A queued run is removed from the queue; a running one has a per-run cancel flag that the worker checks between frames. The run ends as `status: "cancelled"` and its partial outputs (`masks/`, `grids.npz`, `motion.npz`, `hazards.json`, `events.json`) are removed; `run.json` stays.
- The reply waits up to 3 s for the end state and returns the run doc; 409 if the run is not queued/running; 404 if unknown.
- Cancelled and error runs are listed but cannot be played. Re-POSTing the same request starts it fresh.

**GPU:** one worker thread, FIFO queue, `gpu_guard.assert_torch_cuda()` at job start. One model is cached by path and released after `HACKEYE_LAB_IDLE_SECONDS` (default 300) without work, so the service holds no VRAM while idle.

## 6. Collision config  (`common/config/collision.json`, version `v26.1.9`)

Class names are the 48-class HackEye mapping's (`safety_mapping_hackeye48.json`). Names missing from a model's `class_names` are skipped (logged once). All distances are metres, times seconds, "steps" are walking steps (§7.7).

**Top level**

| Key | Default | Meaning |
|---|---|---|
| `version` | `"v26.1.7"` | Written into `hazards.json`, `events.json` and `run.json.collisionVersion`. |
| `defaultMount` | `"chest"` | Mount preset used when a recording has none. |
| `defaultHfovDeg` | `118` | Horizontal field of view when the recording has none. |
| `mountPresets` | see below | `label`, `horizon` (fallback horizon row, normalised y), `cameraHeightM`. |
| `minComponentFraction` | `0.0004` | Minimum size of an item component, as a fraction of the grid area (about 13 px at 240×135). |
| `spokenLabels` | see below | Class name → spoken word. Unlisted classes are spoken as the class name with `-` replaced by a space. |
| `contextSpeak` | `["obstacle","building","vehicle","parked car"]` | Spoken labels (after `spokenLabels`/`parkedLabels`) that may be announced as context. Other context items keep the role `context` (overlay) but stay silent. |
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
| `evidenceLookbackSeconds` | `10.0` | Evidence counts if it happened no earlier than this before the new surface's current run began. |
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
| `contextMaxLateralM` | `3.0` | Context only within this sideways distance (except in the very first start summary). |
| `featureMinLaneCover` | `0.2` | A feature must cover this share of the lane's width at its contact row. |
| `alongPathRatio` | `0.5` | Near/far distance ratio of an item's base below which it "runs along the path". |
| `minObstacleAreaM2` | `0.08` | A danger needs a component at least this large (real area at its distance). |
| `boundaryMarginPx` | `2` | Dilation of the walking region used for "touches the region". |
| `stationaryMps` | `0.5` | A vehicle whose ground speed is below this is parked (1.5× while it was already parked). |
| `approachingMps` | `0.5` | A mover whose ground speed toward the user exceeds this is approaching (away: receding). |
| `confirmFrames` | `2` | A role must hold this many consecutive analysed frames before it is spoken or beeps. |
| `movingLaneHalfWidthM` | `3.0` | People (person/rider/animal) can be a danger up to this sideways distance. |
| `movingCollisionHalfWidthM` | `1.5` | An approaching person counts as on a collision course up to this sideways distance. |
| `movingDangerSteps` | `15` | People can be a danger from this many steps. |
| `landmarkSteps` | `15` | A crosswalk landmark is announced within this many steps. |
| `thinNoticeSteps` | `15` | Thin objects are noticed within this many steps … |
| `thinNoticeLateralM` | `2.5` | … and this sideways distance. |

**`tracking`:** `iouMatch 0.2`, `maxMissedSeconds 1.0`, `historySeconds 2.0`, `groundGateLateralM 0.6`, `groundGateDistanceFrac 0.2` (match gate, §7.5); `motionMinRowsBelowHorizon 8`, `motionMinSeconds 0.75` (closing speed needs a contact at least 8 grid rows below the horizon and ≥ 0.75 s of history); `contactEma 0.5` (smoothing of a track's contact row).

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
| `featureLabelOverrides` | `{"crosswalk": {"gapSeconds": 20, "newCrossingSteps": 14}}` | Per class override of the two above. |
| `templates` | see §7.10 | Phrase templates. |

**`tones`** (§7.13): `frequencyHz 880`, `bySteps [[10,1.0],[6,0.5],[3,0.25],[2,0.12]]` ([steps, interval s]), `durationSeconds 0.08`, `continuousSteps 1.5`, `continuousChunkSeconds 0.25`, `maxSteps 10`, `holdSeconds 0.5`, `episodeGapSeconds 1.5`.

**Module constants** (in `collision.py`, not config): `WARMUP_S 1.5` (no danger/feature role during the first 1.5 s of a run, while the horizon settles); `MIN_TRACK_AGE_S 0.5` (a track must be this old to speak or beep); `HORIZON_HOLD_S 3.0` (the last good horizon is held this long when an estimate fails); `LABEL_COOLDOWN_S 5.0` (a danger label is not repeated within 5 s); `POINT_ASPECT 3.0` (speed witnesses are at least 3× taller than wide).

## 7. Collision logic  (`src/collision.py`)

**Pure logic:** numpy + scipy and `geometry.Box`/`geometry.iou` only. No cv2, no torch, no file I/O except `load_config`. It must stay portable to Swift.

```python
@dataclass
class CollisionSettings:
    mount: str; hfov_deg: float; camera_height_m: float
    step_length_m: float | None        # None = use ego.priorStepLengthM
    horizon_default: float             # from the mount preset

load_config(path=None) -> dict
resolve_settings(config, mount=None, hfov_deg=None, camera_height_m=None, step_length_m=None) -> CollisionSettings
bearing_deg(x_norm, hfov_deg)                 # atan((x-0.5)*2*tan(hfov/2)); + = right
clock_from_bearing(bearing) -> int            # 12 + round(bearing/30), clamped to ±90°, as 9..12 and 1..3
focal_px(grid_w, hfov_deg)                    # (grid_w/2) / tan(hfov/2)
ground_distance_m(y_norm, horizon_y, camera_height_m, grid_h, f_px)   # H*f / ((y-horizon)*grid_h); None if y <= horizon
lateral_m(x_norm, distance_m, grid_w, f_px)   # (x-0.5)*grid_w*distance/f   (+ = right)
estimate_cadence(t, dy, window_s, band_hz, min_peak_ratio, dx=None, ...) -> per-sample Hz or nan
walking_region(grid, ids, config) -> Region | None
run_collision(grids, times, class_names, config, settings, motion=None) -> (hazards_doc, events_doc)
    # motion: {"t","dx","dy"} arrays or None -> no cadence, heading, ego speed from gait, or world memory
```

Frames are processed in order; every state below carries over from frame to frame. "Frame" = analysed frame.

### 7.1 Walking region
- The majority surface class inside `seedBox` (surface-group classes only; ties → the group with more pixels) picks the group. No surface pixels → `region = None` for this frame.
- Region = the 4-connected components, containing seed-box pixels, of (that group's classes ∪ `surfaces.inside`).
- Per grid row: `left`/`right` = min/max region column (normalised). Rows without region pixels are invalid. After the horizon fit (below), `left/right` are smoothed per row with EMA 0.5 across frames (reset when the frame's group changes).
- The region follows the model frame by frame. The **adopted surface** (§7.14) is separate and slower.

### 7.2 Horizon
- Raw estimate: fit `x = a·y + b` to the left and the right bound, each over the lowest 70 % of that side's valid rows, **excluding rows where the bound is clamped to the image border** (a clamp is a crop, not an edge); each side needs ≥ `minRegionRows` rows. Accept only if the lines converge upward (`a_left < −0.02`, `a_right > 0.02`) and the intersection's y lies within `horizonValidRange`. Otherwise no estimate this frame.
- During the first `WARMUP_S` (1.5 s) the horizon is the mean of the raw estimates so far (preset if none). Afterwards: a failed estimate keeps the last horizon for `HORIZON_HOLD_S` (3 s), then the target is the preset; otherwise EMA (`horizonEma`) toward the target with each step clamped to `±horizonMaxStep`.
- `horizonEstimated` in the output = a raw estimate was accepted this frame.

### 7.3 Geometry and the gait-calibrated scale
- Pinhole flat-ground model: a ground point `dy` rows below the horizon is `H·f/dy` metres away; lateral = `(x − 0.5)·W·d/f`. `H` is the camera height times the scale `k` below, so **all distances, laterals, areas and closing speeds are real-world metres**.
- **Scale `k`** (class `_Scale`): over the last `calibrationWindowSeconds`, `k = median(cadence) × priorStepLengthM / median(raw ego speed)` for frames where both are known (raw speed ≥ `calibrationMinRawSpeed`; at least `calibrationMinSamples` frames; clamped to `scaleRange`). The first estimate is taken at once; later ones are blended in (log scale) with a time constant that grows from `calibrationEmaMinSeconds` to `calibrationEmaSeconds`. The **applied** scale slews toward the measured one at ≤ `scaleMaxChangePerSecond` (so step counts don't jump). Frames without cadence add nothing, so the last scale is held when standing still; until the first estimate `k = 1` (or `scalePrior`).
- The raw closing speeds that feed the calibration stay uncalibrated, so there is no feedback loop.
- **Per-recording `stepLengthM`** replaces `priorStepLengthM` for the calibration and for steps.

### 7.4 Items
- 4-connected components of **each class** (not each group) of the `static`, `moving` and `feature` groups, only over rows whose bottom edge is below the horizon, with ≥ `minComponentFraction × grid area` pixels. A pole against a wall is two items.
- **Contact point:** static/moving = the component's lowest pixel (on that row, the column nearest the image centre); feature = its lowest pixel *inside the danger lane* if any, else the lowest pixel. Compute `distanceM`, `lateralM`, `bearingDeg`, `clock`, `pan` (`sin(bearing)`, clamped) there. Drop items with `distanceM > maxRangeM` or no distance.
- **Danger lane:** half-width at a row = `laneHalfWidthM` in metres projected to pixels at that row's distance. `lane_hit` for static/moving = the component's lowest row itself touches the lane inside the (dilated) walking region (a car beside the path whose roof intrudes does not count); for features = any pixel in the lane. `lane_cover` = share of the lane's width at the contact row that the feature covers.
- `touches` = any pixel in the walking region dilated by `boundaryMarginPx`. `clipped` = the component touches the bottom image edge (its distance is only a lower bound).
- **Runs along the path:** look at the component's *base* pixels (those with walking region directly below them). If the base's near/far distance ratio is < `alongPathRatio` (0.5), the item spans a long stretch of path (a wall, median or curb alongside): it is boundary, never danger and never a lane-crossing feature. Also, a static/feature item whose raw closing speed is < 30 % of the raw ego speed (when that is ≥ 0.5 m/s) is treated as running along the path.
- `area_m2` = pixel count × (distance/f)².
- Distance, lateral and steps are read from a per-track **smoothed contact row** (`contactEma`); a clipped item has no smoothing.

### 7.5 Tracking
- Greedy matching within the same group **and** class. A pair matches if `iou(bbox) ≥ iouMatch` **or** the ground gate holds: `|Δlateral| ≤ groundGateLateralM` and `|Δdistance − expected| ≤ groundGateDistanceFrac × distance`, where `expected = −closing·dt` (0 if unknown). Score = IoU, plus 0.5 if the gate holds; highest first.
- A track survives `maxMissedSeconds` without a match. It keeps its contact **rows** (not distances) over `historySeconds`; a clipped detection clears the history.
- **Closing speed:** the (negative) slope of the distances obtained by re-projecting *all* history rows through the **current** smoothed horizon (so horizon wobble cannot fake motion). Points less than `motionMinRowsBelowHorizon` rows below the horizon are left out; it needs ≥ 3 points, ≥ `motionMinSeconds` of history and the latest point included; otherwise `None`. `closingMps` = raw closing × `k`.
- Per track: `present_run` (consecutive frames matched) and `role_run` (consecutive frames holding the same role). A track is `settled` after `MIN_TRACK_AGE_S`.

### 7.6 Ego motion
- **Cadence** (step rate, Hz), from the vertical bob `dy` of `motion` (nearest motion sample to `t`): causal power-spectrum peak in `cadenceBandHz` over `cadenceWindowSeconds` (needs 60 % of a window), accepted at `cadenceMinPeakRatio` (a weaker peak is accepted when the horizontal sway `dx` peaks at the same rhythm). **Stride-aware:** a chest camera bobs asymmetrically, so a dominant peak `f0` is often the stride; the step rate is the peak near `2·f0` if `f0 < minStepHz`, or that peak has ≥ `harmonicMinRatio` of the power, or `dx` peaks within 0.15 Hz of `f0`; otherwise `f0`. A value is held for one window when a later window has no clear peak.
- **Speed witnesses:** only pole-like static items (bbox height ≥ 3× width, not clipped, not running along the path) with raw closing speed in [0, `speedMaxMps`] judge our speed: the median, EMA `speedEma`, dropped when stale for > 5 s.
- **Ego speed** (calibrated, used for parked-vs-moving and the world memory): `cadence × stepLength` once the scale is known and a cadence exists; otherwise witness speed × scale; otherwise unknown.
- **Heading:** the cumulative sum of `−dx × hfovDeg` (degrees; + = turned right), interpolated to `t`.

### 7.7 Steps
`stepsTo = distanceM / stepLengthM` (the stored per-recording length, else `priorStepLengthM`). Spoken as `round(stepsTo)`, at least 1 (`"1 step"` for 1, else the number); `stepsTo` is kept with 1 decimal in JSON. Steps are *not* divided by the instantaneous ego speed (that made them jump). Distances are real-world thanks to the scale (§7.3). Steps are omitted from a phrase only if the distance is unknown (the `" in {steps}"` part is dropped).

### 7.8 Moving vs. parked
- Static and feature items: `moving = false`. Moving-group items need a known `closingMps` and ego speed: `groundSpeed = closingMps − egoSpeed` (toward the user = positive). `moving = |groundSpeed| ≥ stationaryMps` (hysteresis ×1.5 for a track that was parked); `approaching = moving and groundSpeed > approachingMps`; `receding = moving and groundSpeed < −approachingMps`. Unknown → `moving = null`, never approaching.
- **Vehicles** with `moving` ≠ true (parked or unknown) are treated as **static** for roles, and `moving == false` gives the label `parkedLabels["vehicle"]` ("parked car"); unknown keeps "vehicle".
- **People (person, rider, animal) are never treated as static or "stationary"**: their measured motion only decides approaching/receding, because chest-camera motion for walking people is unreliable and they are the ones that step into the path.

### 7.9 Roles  (one per item per frame)
- **danger**
  - *Static or vehicle with `moving ≠ true`:* component area ≥ `minObstacleAreaM2`, `lane_hit`, not running along the path, `stepsTo ≤ dangerSteps`. On a collision course (`collision = true`).
  - *Person/rider/animal:* in the walking region's row span (or no region at all, e.g. on a crosswalk), area ≥ `minObstacleAreaM2`, `|lateral| ≤ movingLaneHalfWidthM` (3.0), not (receding and `|lateral| > laneHalfWidthM`), `stepsTo ≤ movingDangerSteps` (15). `collision = |lateral| ≤ laneHalfWidthM` or (approaching and `|lateral| ≤ movingCollisionHalfWidthM`, 1.5).
  - *Vehicle measured moving:* in the row span, `|lateral| ≤ laneHalfWidthM + 1.0`, (approaching or `|lateral| ≤ laneHalfWidthM`), area ≥ `minObstacleAreaM2`, `stepsTo ≤ dangerSteps`. Collision course.
  - `urgency` = `final` if `collision` and `stepsTo ≤ finalSteps`, else `danger`. A person merely beside the path is a danger without collision (speech, no beeps, never a final).
- **feature** (curb, crosswalk, pothole)
  - *Landmark* (crosswalk): touches the walking region, not clipped, `stepsTo ≤ landmarkSteps`. It need not cross the lane.
  - *Others:* `lane_hit`, not running along the path, not clipped (not already under the feet), `lane_cover ≥ featureMinLaneCover`, `stepsTo ≤ featureSteps`. A curb or median running alongside the path stays silent.
- **context:** a static/parked item that is not danger, `touches` the dilated region, `distanceM ≤ contextMaxDistanceM`, area ≥ `contextMinAreaFraction`, `distanceM ≤ contextMaxSteps × stepLength`, and `|lateral| ≤ contextMaxLateralM`. (An item that fails only the lateral limit is allowed in the very first start summary of a run.) People never get `context`.
- **none:** everything else (still listed in `hazards.json`; the UI greys it).
- During the first `WARMUP_S` of a run danger and feature roles are forced to `none` (no distances on a guessed horizon).
- A role is **confirmed** after it has held for `confirmFrames` consecutive frames; speech and beeps use only confirmed roles of settled tracks.

### 7.10 Speech policy  (class `SpeechPolicy`)
At most **one phrase per frame**. Priority: final > danger/feature/thin notice (one combined phrase) > surface > context. Only the highest class that has candidates is considered, so a waiting danger is never overtaken. Context and surface are held back while any confirmed danger track is active.

**Gaps:** final ignores the gap. Danger/feature phrases wait for `priorityMinGapSeconds` after the previous danger/feature/final phrase (a context phrase never delays them). Context and surface wait for `globalMinGapSeconds` after any phrase.

**Templates** (`speech.templates`; `{clock}` is 9–12 or 1–3; no "o'clock"):

| Key | Template |
|---|---|
| `context`, `feature`, `danger`, `final` | `{label} at {clock} in {steps}` |
| `approach` | `{label} approaching at {clock} in {steps}` |
| `surface` | `{label}` |
| `contextGroup` | `{items}` (items = context entries joined by `", "`) |
| `multi` | `{label} at {clocks} in {steps}` |
| `thinNotice` | `{label} at {clocks} in {steps}` |

`{clocks}` lists the distinct clocks left to right (9 10 11 12 1 2 3): `"1"`, `"1 and 2"`, `"10, 12 and 2"`. Every announced object has a position and (unless the distance is unknown) steps.

1. **Final** — a confirmed, settled danger track with urgency `final` that has not had one yet. Once per track; ignores the global gap; the template is `final`. It is spoken **only if the object is not already in the world memory** (§7.11, any entry, named or not) — something that appeared suddenly close. Otherwise the slot is consumed silently (pacing as if spoken) and the beeps carry the proximity. If a danger track is already within `finalSteps` when first announced, only the final call is made.
2. **Danger + feature + thin notice in one phrase** (at most `maxEntries` entries; danger first, then features — crosswalks before curbs, then by steps — then the thin notice):
   - *Danger entries:* confirmed danger tracks not yet announced, label not announced in the last `LABEL_COOLDOWN_S`, and not waiting for motion (a person with unknown motion, farther than `peopleMotionWaitSteps`, for up to `peopleMotionWaitSeconds` after becoming a danger). Grouped by (label, approaching): approaching ones use `approach`; same-label items merge into one entry with their clocks and the **nearest** item's steps (`person at 1 and 2 in 4`, `person approaching at 12 in 6`).
   - *Feature entries:* confirmed feature tracks not yet announced and allowed by the label gap (`featureLabelGapSeconds`, or `featureNewCrossingSteps` further along the walk; crosswalk: 20 s / 14 steps). Position along the walk = steps ahead plus steps walked so far. This keeps fragments of one curb, re-tracked under new ids, quiet.
   - *Thin notice:* thin objects (poles, lights, signs) present for ≥ `confirmFrames` frames, within `thinNoticeSteps` and `thinNoticeLateralM`, not already a danger entry: one entry per label, plural if several (`poles at 11 and 1 in 8`, steps of the nearest). Said **once**: afterwards the notice is disarmed while any thin object is noticed; it re-arms after `thinRearmSeconds` with none noticed, or on a path change. The whole thin cluster in view counts as warned about.
   - The phrase's role is `danger` if it contains a danger/approach entry, else `feature` (also for a thin-only phrase). Its clock/trackId/pan come from the leading item.
   - Danger and feature tracks are marked announced only when they enter a phrase; each is announced once.
3. **Surface** — a pending adopted-surface change (§7.14): `{label}`, e.g. "road".
4. **Context** — grouped, label-level:
   - Candidates: items with role `context` whose label is in `contextSpeak`, from settled tracks (see the start summary below), one per label family (vehicle and parked car are one), the nearest. A label already in the **label memory** is skipped; the memory refreshes while the label is seen (context/danger static-like items), is forgotten after `contextMemory.forgetAfterSeconds` unseen, and is cleared on a path change. A danger/final phrase naming a `contextSpeak` label also puts it in the memory. Context is held until a surface is adopted, or `surfaces.debounceSeconds` since the start.
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
- The final-call rule (§7.10, item 1) uses any matching entry.

### 7.12 Path change
A **turn**: the heading differs from a slow reference (time constant `referenceTauSeconds`) by more than `headingDeg` for `sustainSeconds`; the reference is then reset to the heading. (If `onSurfaceChange` were true, an adopted surface change would count too; it is false.) A path change clears the label memory and pending context, re-arms the thin notice and starts a new start summary. It does **not** clear the world memory.

### 7.13 Beeps (parking-sensor)
- **Who:** only a **collision** track: a confirmed, settled danger with `collision = true` and `stepsTo ≤ tones.maxSteps`. The single nearest one drives the beeps each frame. Features, context and non-collision dangers never beep. Beeps are independent of the world memory and of muted phrases.
- **Sound:** constant pitch `frequencyHz`; interval linearly interpolated from `bySteps` by `stepsTo` (clamped at the table ends); each tone lasts `durationSeconds`. A faster stream does not wait out a slower previous interval.
- **Very close:** at `stepsTo ≤ continuousSteps` a continuous tone: gapless back-to-back tone events of `continuousChunkSeconds`.
- **Stopping:** the beeps stop when the track stops being a collision (passed, left the lane). A track that is merely absent from a frame keeps beeping for `holdSeconds`.
- **Episodes:** per continuous stream of one track (gap < `episodeGapSeconds`) the output also contains one `beeps` event (§7.15).

### 7.14 Surface  (class `_SurfaceTracker`)
- The adopted surface changes only when **all** hold:
  1. the new group holds ≥ `majority` of the frames of the last `windowSeconds`, and the window spans ≥ `minPersistSeconds`;
  2. the new group has run uninterrupted for ≥ `minPersistSeconds`;
  3. **evidence:** a curb or crosswalk really passed *under* the user (`requireCrossingEvidence`): an item of class curb/crosswalk with `lane_hit`, its contact within the bottom `passUnderRows` rows, bbox width ≥ `passUnderMinWidth`, whose track was gone within `passUnderGoneSeconds`; the evidence must be no older than `evidenceLookbackSeconds` before the new group's current run began.
- Otherwise the old surface is kept silently: the region still follows the model, nothing is spoken and no memory is reset.
- The **first** surface of a run needs only the majority and is adopted silently (`announceFirstSurface: false`).
- A change is spoken only if the new or the old group is in `announceGroups` (road, rail); sidewalk ↔ bike lane is silent. The phrase is the group's label; it waits for the gap and for dangers.

### 7.15 Output  (`hazards.json`, `events.json`)

**`hazards.json`**
```jsonc
{"version": "v26.1.7",
 "settings": {"mount": "chest", "hfovDeg": 118, "cameraHeightM": 1.3, "stepLengthM": null,
              "laneHalfWidthM": 0.6, "priorStepLengthM": 0.7},   // priorStepLengthM = the step length actually used
 "gridW": 240, "gridH": 135, "egoAvailable": true,                // egoAvailable = a motion track was used
 "frames": [{
   "index": 0, "t": 60.0,
   "horizonY": 0.452, "horizonEstimated": true,
   "region": {"surface": "bikeLane", "label": "bike lane",
              "rows": [[0.70, 0.21, 0.83], [0.73, 0.18, 0.86], ...]},   // [y, left, right], every 4th grid row, bottom→top; this is the model's region of this frame
   "lane": [[0.41, 1.0], [0.59, 1.0], [0.53, 0.58], [0.47, 0.58]],    // danger-lane polygon, near→far at dangerSteps × step length
   "ego": {"speedMps": 1.32, "cadenceHz": 1.85, "stepLengthM": 0.7, "headingDeg": -3.2,
           "scale": 1.62, "scaleSource": "gait",                       // gait | prior | none
           "estimated": {"speed": true, "cadence": true, "stepLength": false}},
   "pathChange": false,
   "hazards": [                                                        // all items, nearest first (by steps)
     {"trackId": 3, "className": "pole", "group": "static", "label": "pole", "role": "danger", "moving": false,
      "bbox": [0.48, 0.52, 0.55, 0.81], "contactY": 0.81, "bearingDeg": 4.1, "clock": 12, "pan": 0.07,
      "distanceM": 5.6, "lateralM": 0.21, "stepsTo": 8.0, "closingMps": 1.3, "urgency": "danger",
      "areaFrac": 0.012, "collision": true,
      "outline": [[0.48, 0.52], [0.55, 0.52], [0.55, 0.81], [0.48, 0.81]]}
   ]}]}
```
- `region` is null when there is no surface. `moving` is `true/false/null` for moving-group items (null = unknown), `false` otherwise. `closingMps` is null when unknown. `urgency` ∈ `none | danger | final`.
- `ego` fields are null when unknown. `estimated.stepLength` is always false.
- `outline` (items with `role != "none"` only): the outer contour of the item's own connected component, traced on the grid in pixel-corner coordinates (so its extent equals `bbox`), simplified with Douglas–Peucker (epsilon 0.75 grid px, growing ×1.25 until ≤ 32 points), concavities kept, normalised and rounded to 4 decimals. Pure numpy/scipy. Role `none` items carry no outline to keep `hazards.json` small.

**`events.json`** — sorted by `t` (speech before beeps before tones at equal `t`):
```jsonc
{"version": "v26.1.7", "events": [
  {"t": 61.2, "type": "speech", "role": "context", "text": "building at 2 in 6", "trackId": 5, "urgency": "none", "clock": 2, "pan": 0.48},
  {"t": 64.0, "type": "speech", "role": "danger", "text": "pole at 12 in 8", "trackId": 3, "urgency": "danger", "clock": 12, "pan": 0.07},
  {"t": 64.0, "type": "tone", "role": "danger", "trackId": 3, "urgency": "danger", "pan": 0.07, "frequencyHz": 880.0, "durationSeconds": 0.08},
  {"t": 64.0, "tEnd": 67.4, "type": "beeps", "role": "danger", "trackId": 3, "label": "pole", "clock": 12, "minSteps": 2.0,
   "urgency": "final", "text": "beeps · pole at 12 · 8→2 steps"}
]}
```
- Speech `role` ∈ `context | surface | feature | danger | final`; surface events have `trackId: null`, `clock: null`, `pan: 0`.
- `tone` events drive the audio; `beeps` events (one per episode) are what the review panel and the timeline use. The `beeps` `text` is `beeps · <label> at <clock> · <first>→<min> steps` (`<n> steps` when equal), with the label/clock of the nearest moment.

## 8. REST API  (`lab/server.py`, FastAPI)

Endpoints are plain `def` (threadpool). JSON responses are gzip-compressed (`minimum_size=1024`) except `/media/*` and `*.png`. Errors are `{"detail": "..."}`.

| Method + path | Body / query | Returns |
|---|---|---|
| `GET /` | | `lab/static/index.html` (static files under `/static/*`) |
| `GET /api/version` | | `{"version", "since", "lastWipe"}` (§11) |
| `GET /api/recordings` | | `[Recording]` (§3) |
| `POST /api/recordings/{id}/proxy` | | proxy status; starts a build if missing/error |
| `GET` / `HEAD /media/{id}.mp4` | | the proxy file (Range requests); 404 if not ready |
| `GET /api/recordings/{id}/settings` | | Settings (§4) + `"resolved": {"hfovDeg", "cameraHeightM", "stepLengthM" (null = prior), "horizon"}` |
| `PUT /api/recordings/{id}/settings` | Settings | same as GET; 422 on invalid |
| `GET /api/config/collision` | | the contents of collision.json |
| `GET /api/models` | | `{"models": [{"path","name","default"}], "profiles": ["544p", ..., "736p"]}` (the resolutions the UI offers; legacy names are accepted by `POST /api/runs` but not listed) |
| `POST /api/runs` | run request (§5) | `run.json`; queued, or the existing in-flight/done run; 409 / 422 as in §5 |
| `GET /api/runs?recording=<id>` | | `[run.json]`, newest first (all runs without the query) |
| `GET /api/runs/{runId}` | | `run.json` |
| `POST /api/runs/{runId}/cancel` | | run doc (§5) |
| `POST /api/runs/{runId}/collision` | | re-runs the collision pass with the recording's current settings; `{"version", "elapsedSeconds", "hazards": "/api/runs/<id>/hazards.json", "events": "/api/runs/<id>/events.json"}`; 409 if the run is not done; 503 if the collision module is missing |
| `GET /api/runs/{runId}/hazards.json` · `events.json` | | the files (`Cache-Control: no-cache`). The UI uses only `events.json`. |
| `GET /api/runs/{runId}/hazards?from=<s>&to=<s>` | both required | `{version, settings, gridW, gridH, egoAvailable, from, to, frames}`, the frames with `from ≤ t ≤ to`. 422 if `to < from` or the window is over 600 s |
| `GET /api/runs/{runId}/frame?t=<s>` | | `{"frame": ...}`, the analysed frame with the largest `t ≤ s`; 404 before the first frame or more than 1 s after the last |
| `GET /api/runs/{runId}/frames/{i}/mask.png` | | the mask PNG (`Cache-Control: max-age=86400`); fallback only |
| `GET /api/runs/{runId}/frames/{i}/classes.png` | | 8-bit grayscale PNG of `grids[i]` (positional, frame-aligned class ids), `Cache-Control: max-age=86400`; 404 unknown frame, 409 run not done. `grids.npz` cached for 2 runs, keyed by mtime |
| `GET /api/runs/{runId}/classes` | | `{mapping, classes: [{id, name, level}], levels: [{level, label, color, opacity}]}` from the safety mapping matching the run's `classNames` (`segmentation.find_mapping`, no GPU); default opacity 0 for level 0, else 1; 404 if no `classNames` or no mapping matches |
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

## 9. Frontend  (`lab/static/`: `index.html`, `style.css`, `app.js`, `js/*.js`; vanilla JS, no build step)

**Layout:** header (title, version badge `· v26.1.7` from `/api/version`, run badge). Sidebar: Recordings, Analyse, Collision settings, Past runs. Main: player stage, transport, Audio and Overlay panels, timeline, role chips. Right: the notification review panel.
- ≥ 1200 px: three columns (sidebar 320 px | player | review panel 380 px, sticky, own scroll, full viewport height). 900–1199 px: the panel goes under the player. < 900 px: stacked (the Recordings section collapses after selecting).
- State is kept in the URL hash `#rec=<id>&run=<runId>&t=<s>` and restored on load.

**Library and proxy:** each recording shows duration, size, fps, chapter count and a proxy tag; "Build proxy" / "Retry build proxy" starts a build; the list polls every 2 s while a proxy builds. The video is attached once the proxy is ready.

**Analyse panel:** range start/end (seconds, mm:ss or hh:mm:ss; default `0 → recording duration`; "from playhead" buttons; loading a run sets the range to the run's), model (default pre-selected), **Resolution** (`544p`–`736p`, default `544p`; each option reads e.g. `576p · 1024×576` from the recording's `inputSizes`, and options the recording cannot do without upscaling are disabled; loading a run selects the run's resolution), FPS (default 6). The run badge and the past-runs list show the run's input size (`inputSpec`). Analyse saves the settings, then POSTs the run.
- **Progress and cancel:** whenever a recording is selected (or restored from the hash) the UI checks its runs for a `queued`/`running` one — including one started in another tab or on another device — and follows it: shows the progress bar (polling every 1 s), disables **Analyse** (the reason in the tooltip) and shows **Cancel analysis**. On completion it behaves as for a run started on this page (enables Analyse, lists the run, loads it). A 409 from Analyse follows the in-flight run.
- Past runs: click a done run to load it; cancelled/error runs only show a message; an active one is followed.
- **Collision settings:** mount, HFOV, camera height (m), step length (m). Empty = default; the placeholders show the resolved values (`118 (default)`, `1.3 (preset)` following the mount, `auto (default 0.7)`). **Re-run collision** saves the settings, re-runs §7 on the loaded run, reloads events and hazards, and reports compute time, speech and beeps counts.
- The run badge shows run id, range, fps, frame count, model, ms/frame, collision version, and "no motion track" when there is none.

**Windowed hazards:** the page never loads the whole `hazards.json`. It holds the frames within ±90 s of the playhead, prefetches the next stretch when the playhead is within 30 s of the window's end, and refetches on a seek outside the window (failed fetches back off 3 s). Overlay, HUD and frame stepping use the window; the timeline and review panel use `events.json` (small).

**Overlay** (canvas over the video content; frame-synchronised via `requestVideoFrameCallback`; drawn only inside the run's range). Each layer is a checkbox:
- **Mask:** coloured **in the browser** from `classes.png` through a lookup table class → (shown? → level → colour × level opacity), multiplied by the opacity slider (default 0.45), drawn nearest-neighbour. Edits in the Classes & safety levels panel (§9.3) repaint instantly without refetching. ±20 frames are preloaded; an earlier mask is reused only if < 0.5 s old. If `/classes` or a frame's `classes.png` fails, that frame falls back to the pre-rendered `masks/<i>.png`.
- **Region:** outline polygon from `frame.region.rows` (left edge bottom→top, then right edge top→bottom), thin white line, `region.label` near its top.
- **Lane:** the `frame.lane` polygon, semi-transparent red.
- **Horizon:** line at `horizonY`, solid yellow if `horizonEstimated`, dashed if the preset fallback.
- **Items:** drawn as **outlines** (the item's `outline` polygon, 15% alpha fill) or **boxes** (`bbox`), chosen with the **Shapes** select (default Outlines, remembered in localStorage `hackeye.lab.shapes`); items without an outline always use their box. Each item is coloured by role — danger orange `#ff8c1a` (final urgency red `#ff2d2d`), feature cyan `#22d3ee`, context light grey `#c9ced6`, none dim grey `#6b7280` drawn thin. Label `"<label> · <clock> · <n>st"` (steps rounded; context shows only `"<label> · <clock>"`). `none` labels show only when "Show all" is on. A dot marks the contact point of non-`none` items. Dim items are drawn first so dangers end up on top.
- **HUD** (top-left of the player): `speed` (m/s and km/h, `(est)` when estimated), `cadence` (steps/min = `cadenceHz × 60`), `step` (m; `(default)` for the prior, `(set)` for a per-recording value), `heading` (degrees, signed). `—` for unknown values; "no ego data (re-analyse)" when a frame has no `ego`. The gait scale is in `hazards.json` but not shown.

**Transport:** play/pause (Space), previous/next **analysed** frame (← / →; falls back to one video frame without a run), speed 0.25–2× (`[` / `]`), seek bar, `m` mutes all. Keyboard shortcuts are ignored while typing in an input, select or textarea.

**Audio** (`js/audio.js`, WebAudio + speechSynthesis)
- **Armed by default.** The AudioContext and speech unlock on the **first** `pointerdown`, `keydown` or `touchend` anywhere on the page (once). The button toggles "🔊 Audio on" / "🔇 Audio off". Checkboxes: Speech, Beeps, Hear review edits, Mute all, Video sound; sliders: volume (0.8), audio delay (±300 ms).
- **Beeps** come only from `tone` events: sine waves with a 5 ms attack/release, scheduled on the audio clock ~0.25 s ahead of the playhead, panned by `pan`, at `frequencyHz`/`durationSeconds`.
- **Speech** is spoken when the playhead *crosses* a speech event's time during normal playback (never on seeks); the speech rate follows the playback rate (0.5–2). A final call pre-empts the phrase being spoken; other phrases queue. Any discontinuity (seek, pause, rate change, stall) drops everything scheduled.
- **Review preview** ("Hear review edits", on by default): playback merges the recording's **added** speech annotations as speech events at their `t`, skips system speech events with a ⊘ verdict, plays **added beeps** as parking-style tones (every 0.5 s, 780 Hz, 0.08 s) and silences the tones of beeps episodes with a ⊘ verdict. Re-merged whenever reviews change. Off = only the system's audio.
- **E2E hook:** `window.__labAudioLog` holds `{at, mediaT, type: "speech"|"tone", text|freq, source: "system"|"added"}` for every phrase spoken and tone scheduled.

**Timeline:** speech ticks coloured by role (click near a tick snaps to it; click/drag seeks), beep episodes as bars coloured by role (older runs without `beeps` events show a tone-density heat row instead), the playhead. The role chips (context, surface, feature, danger, final; all on by default) filter the timeline and the review panel.

### 9.1 Notification review panel  (`js/reviews.js`)
One row per **notification** of the loaded run (a spoken phrase, or a beeps episode with a 🔔 badge) plus the user's added ones, sorted by `t`. Reviews load on recording select and don't need a run; verdict rows need a run.
- **Header:** `N notifications · M beeps`; counts ✓ correct · ✗ incorrect · ⊘ should-not-be-said · + added · unreviewed (= notifications of the loaded run without a matching verdict); an Export link (`/api/reviews/export?recording=…`); mini transport buttons.
- **Event row:** timestamp `m:ss.s` (click seeks and pauses), role badge (overlay colours), for beeps the 🔔 badge and the duration, the text, and toggles **✓ ✗ ⊘**. Clicking an inactive toggle creates or changes the verdict; clicking the active one deletes it. ⊘ shows the text struck through. A note `<textarea>` shows when a verdict exists or the row is expanded (click its text); until a verdict exists, the note is a local draft. Notes autosave 600 ms after the last keystroke and on blur, with a "saved ✓" indicator.
- **Added row:** "+ added" badge (and 🔔 for beeps); inline-editable time (with "⟲" set-to-playhead and "▸" seek), for beeps an end time ("⟲" end to playhead), role select, text (≤ 300 chars), note, 🗑 delete (confirm). Moving the start of an added beeps entry keeps its length.
- **Following playback:** the row nearest before the playhead is highlighted and scrolled into view, except while the user is typing in the list.
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
   "runId": "8ab9a0e06ae3", "collisionVersion": "v26.1.7", "analysisVersion": 2,
   "modelName": "Yolo26m-sem-HackEye20261012-544.pt",
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
- `tests/test_collision_regression.py` — see below.
- `tests/test_versioning.py` (§11) and `tests/test_analysis_cancel.py` (§5 cancellation, one run per recording).

**Regression fixtures** (`tests/fixtures/4929_review{1,2,3}.{json,npz}`, read-only): real-footage windows from recording 4929 plus the user's annotations.
- `.json`: `settings`, `classNames`, `windows` (`start`, `end`, `key`), `annotations` (the user's verdicts and added notifications, with the earlier version's events). `.npz`: per window `w<i>_grids`, `w<i>_t`, `w<i>_mt`, `w<i>_mdx`, `w<i>_mdy`.
- Windows — review 1: 0–10, 14–21, 27–31 s; review 2: 0–10, 28–42, 45–62, 70–80, 114–126 s; review 3: 0–12, 36–62, 100–122, 192–218 s (from run `7b9d5ac14e14`, 0–247 s).
- **Every window is run as its own cold sequence** (no earlier state: cadence needs ~2.4 s, the scale needs witnesses plus cadence; no memory of earlier phrases), so assertions are the ones that hold for any plausible scale and tie each phrase to the item that triggered it. Review 3 additionally runs a **warm** variant (`ego.scalePrior = 1.25`) and a variant with `memory.enabled = false`.
- The tests assert, among others:
  - the start summary names building/obstacle within the first seconds as one grouped phrase; no repeats after a turn (7.84, 40.50, 59.85, 118.66 s of review 3); no final at 41.17 s but the beeps are present; no surface event near 199.16 s (nor 120.83 s);
  - crosswalk landmark with direction and steps near 33.9 s; curb ahead and a poles notice near 38.8 s; a person phrase near 48.5–49.5 s and "person approaching at 12 …" near 75.5 s; no far context at 52.34, 55.51, 58.02 s;
  - no phrase contains "o'clock"; every object phrase has "at <clock>" and "in <n>" (surface excepted); step counts of a spoken track don't jump by more than 30 % between consecutive frames while walking;
  - beeps are collision tracks only and every tone belongs to exactly one episode; no danger/feature starts before confirmation; the ego scale is reported;
  - with the world memory the speech is a subset of the speech without it (surface aside); beeps and tones are identical with and without it;
  - every annotation the user confirmed (✓) is still produced (same text pattern, ±1.5 s) and none of the "should not be said" ones.
- **Fixture grids are frozen model output.** The review 1–3 fixtures were extracted before the v26.1.9 channel-order fix, so they test the collision logic on that older segmentation, not current model behaviour.
- **Channel order** (`tests/test_channel_order.py`): `models.to_ultralytics` reverses RGB→BGR contiguously. Opt-in with `HACKEYE_GPU_TESTS=1` in the lab container, `SegmentationModel.predict_class_grid(rgb)` must equal Ultralytics' own file-loader prediction of the same image.
- Fixtures are extracted from a real run **before** a version bump, as for reviews 1–3; existing reviews' expectations are updated only for deliberate wording changes.

**Browser E2E harness** (`tests/e2e/`, `RnD/tests/e2e/run.sh`)
- Playwright (Python) in `mcr.microsoft.com/playwright/python:v1.63.0-noble` (`PW_TAG`), with the **Google Chrome channel** (`playwright install chrome`; plays H.264), against the live Lab (`--network host`, `LAB_URL`, default `http://127.0.0.1:8765`). Extra arguments go to pytest (`run.sh -k audio -x`).
- Needs the `lab` compose service running with ready proxies for 4928 and 4929. **No user run is needed:** an autouse session fixture analyses 4929 0–120 s at 6 fps once (about 30 s), shares it across tests, and deletes it at session end if the session created it (`run.sh` mounts `debug/lab` as `LAB_DIR_MOUNT`; needs bash ≥ 4.4).
- Launch flag `--autoplay-policy=no-user-gesture-required`; page hooks `window.__spoken` (every `speechSynthesis.speak`), `window.__acs` (every AudioContext) and the Lab's `window.__labAudioLog`.
- Covers: default full-length range, audio armed by the first gesture, add form time following (two adds at two paused times, with a long run loaded and a slow run load), auto-fill (also on a long run and a slow link), added phrases spoken after a rewind, ⊘ phrases not spoken, windowed hazards + gzip and the windowed endpoints, renamed labels and counts line, beeps rows (verdict save, ⊘ silences the episode's tones), adding a beeps entry and hearing it in the preview, timeline beep bars, beeps annotation validation, the Classes & safety levels panel (48 rows, unchecking a class removes its pixels, level colour/opacity repaint, persistence across reload, `mask.png` fallback, server save → fresh browser shows it → reset restores defaults).
- Tests create their own short runs/reviews (on 4928 or a short 4929 range) and delete them afterwards. They must **never trigger a version change**.
