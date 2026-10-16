# HackEye Lab — contracts (v26.1.5)

The single source of truth that `lab/server.py`, `src/collision.py` and
`lab/static/` are built against. Change this file first, then the code.

**What the Lab is:** a web UI on the headless R&D box (reached over Tailscale)
that lets you pick footage from `media/`, analyse a time range with the
segmentation model, then play it back with overlays plus collision-warning
audio.

**Version:** v26.1 = collision detection. Versions are `v<YY>.<major>.<minor>`.

---

## 1. Coordinate convention (everything)

Every position exchanged between backend, collision logic and frontend is
**normalised to the original video frame**: `x, y ∈ [0, 1]`, top-left
origin, `x = col / W`, `y = row / H`.

The stored class grid has the letterbox padding **cropped off** and is
resized (nearest-neighbour) so it maps 1:1 onto the frame. There is never any
letterbox math outside `analysis.py`.

## 2. Paths

`LAB_DIR` = env `HACKEYE_LAB_DIR`, default `/debug/lab` (host
`HackEye/debug/lab`, gitignored).

```
LAB_DIR/
  proxies/<recId>.mp4            browser proxy (see §3)
  proxies/<recId>.json           {"status","progress","error"} while building
  recordings/<recId>.json        per-recording settings (§4)
  runs/<runId>/run.json          run metadata + status (§5)
  runs/<runId>/grids.npz         class grids (§5)
  runs/<runId>/motion.npz        ego-motion track at full source fps (§5)
  reviews/<recId>.json           speech reviews / ground truth (§10)
  runs/<runId>/masks/<i>.png     overlay masks, i = 0..frameCount-1 (§5)
  runs/<runId>/hazards.json      collision output (§7)
  runs/<runId>/events.json       collision output (§7)
  .ultralytics/                  YOLO_CONFIG_DIR
```
Media is at `/media` (read-only). Models are at `/models/*.pt` and
`/hackeye-models/*HackEye*.pt`. Common config is under
`find_common_dir()/config`.

## 3. Recordings + proxy  (`lab/recordings.py`)

**GoPro chapter grouping:** `GOPRnnnn.MP4` is chapter 1 of recording `nnnn`,
and `GPccnnnn.MP4` is chapter `cc+1` (`GP01` → 2, `GP02` → 3, …). Any other
video file in `/media` is its own single-chapter recording with
`id = file stem`. Chapters play back-to-back as one continuous timeline.

```jsonc
// Recording (GET /api/recordings returns a list of these)
{
  "id": "4927",
  "name": "GoPro 4927",
  "chapters": [{"file": "/media/GOPR4927.MP4", "start": 0.0, "duration": 532.1, "frames": 12760}, ...],
  "duration": 1601.4,          // seconds, sum of chapters
  "width": 3840, "height": 2160, "fps": 23.976,
  "proxy": {"status": "missing|building|ready|error", "progress": 0.0, "error": null}
}
```
- Read duration, frames, fps and size with `cv2.VideoCapture` (fast, no decode).
- **Proxy:**
  - ffmpeg concat demuxer over the chapters, with `-vf scale=960:-2 -c:v libx264 -preset veryfast -crf 23 -g <round(fps)> -c:a aac -b:a 96k -movflags +faststart`.
  - Built in a background thread; progress is parsed from ffmpeg `-progress pipe:1` (`out_time_ms`) over the total duration.
  - Written to a `.part` file and renamed when done.
  - **Recording time `t` equals proxy time `t`.**
- **`recording_frame_at(rec, t)`:** maps a recording time to (chapter file, time within that chapter) for the analysis reader.

## 4. Per-recording settings  (`LAB_DIR/recordings/<recId>.json`)

```jsonc
{
  "mount": "chest",            // key of collision.json mountPresets
  "hfovDeg": null,             // null = collision.json defaultHfovDeg
  "cameraHeightM": null,       // null = the mount preset's cameraHeightM
  "stepLengthM": null          // null = estimate from footage (speed / cadence), else geometry.defaultStepLengthM
}
```
- `GET` returns the stored settings or the defaults.
- `PUT` validates and stores them:
  - `mount` must be a known preset
  - `hfovDeg` must be null or in [10, 180)
  - `cameraHeightM` must be null or in [0.5, 2.5]
  - `stepLengthM` must be null or in [0.3, 2.0]
- Settings files from v26.1.0 may still carry a `corridor` key; ignore it on read and drop it on write.

## 5. Analysis runs  (`lab/analysis.py`)

**Request:** `{"recording": "4927", "start": 60.0, "end": 120.0, "model": "/hackeye-models/Yolo26m-sem-HackEye20261012-544.pt", "profile": "default", "fps": 6.0}`
- `profile` ∈ `default | production | half | quarter`, passed to `profiles.resolve_input_spec(src_w, src_h, profile_or_None, None, None)`. `default` → `None`.
- `runId` = first 12 hex chars of sha1 over the canonical JSON of the request, **plus `"analysisVersion": 2`**, plus the model file's mtime.
  - v26.1.0 runs (implicit version 1) keep their ids, stay listable and playable, and have no `motion.npz`.
  - A finished run with the same id is reused.

**Per sampled frame** (times `start, start + 1/fps, …, < end` in recording time; decode sequentially, crossing chapter boundaries):
1. BGR→RGB, then `letterbox_with_meta(rgb, spec.dst_w, spec.dst_h)`.
2. `SegmentationModel.predict_class_grid(...)`, then `grid_from_semantic_mask(class_ids, meta)`.
3. **Crop the padding:** keep rows `[round(pad_y), round(pad_y + src_h*scale))` and the matching columns. Resize nearest-neighbour to `GRID_W = 240`, `GRID_H = round(240 * src_h / src_w)`, as `uint8`.
4. Write `masks/<i>.png`: an RGBA image at grid size. Pixel colour is `SAFETY_LEVELS[level]["color"]` with alpha 255; level 0 (ignored) is fully transparent.

**Ego-motion track (new in analysisVersion 2):**
- For **every source frame** in `[start, end)` (all ~24 fps, not just the sampled ones), convert to grayscale at 160×90 (`cv2.resize`, INTER_AREA).
- `(sx, sy), _ = cv2.phaseCorrelate(prev, cur)` (float32 inputs, with a Hanning window from `cv2.createHanningWindow`). Store `dx = sx / 160`, `dy = sy / 90`: the image-content shift between consecutive frames, normalised to frame size.
  - **Sign:** `dx > 0` means content moved right, i.e. the camera turned left. `dy > 0` means content moved down, i.e. the camera moved up.
- The first frame of the range gets `dx = dy = 0`.
- Skipped frames are already decoded by `grab()`; use `retrieve()` for them too, since gray 160×90 is cheap. Keep the full-res RGB conversion + inference only for sampled frames.
- **Output** `motion.npz`: `t` float64 (M,) recording seconds of each source frame, `dx` float32 (M,), `dy` float32 (M,). `run.json` gains `"motionFrames": M` and `"analysisVersion": 2`.

**`grids.npz`:** `grids` uint8 (N, GRID_H, GRID_W), `t` float64 (N,) in recording seconds, `index` int32 (N,).

**`run.json`:**
```jsonc
{
  "id": "a1b2c3d4e5f6", "request": {...as above...}, "analysisVersion": 2,
  "status": "queued|running|done|error", "progress": 0.0, "error": null,
  "createdAt": "2026-10-16T12:00:00Z", "finishedAt": null,
  "frameCount": 360, "motionFrames": 1439, "gridW": 240, "gridH": 135,
  "srcW": 1920, "srcH": 1080,
  "inputSpec": {"w": 960, "h": 544, "description": "..."},
  "modelName": "Yolo26m-sem-HackEye20261012-544.pt",
  "classNames": ["animal", "barrier", ...],     // from the model, in id order
  "msPerFrame": 123.4, "seekSeconds": 0.3,
  "collisionVersion": "v26.1.1"                   // version of the last collision pass
}
```
After inference finishes, the runner immediately does a collision pass (§7) with the recording's current settings. `motion` is loaded from `motion.npz` when present, else `None`.

**GPU:** one worker thread, FIFO queue, `gpu_guard.assert_torch_cuda()` at job start. The model is cached by path and released after `HACKEYE_LAB_IDLE_SECONDS` (default 300) idle.

## 6. Collision config  (`common/config/collision.json`, v26.1.1)

Class names below are the 48-class HackEye mapping's (`safety_mapping_hackeye48.json`). Names not present in a model's `class_names` are skipped, and that is logged once.

```jsonc
{
  "version": "v26.1.1",
  "defaultMount": "chest",
  "defaultHfovDeg": 118,
  "mountPresets": {                      // horizon = fallback horizon row (normalised y) when the per-frame estimate fails
    "chest":    {"label": "Chest",         "horizon": 0.45, "cameraHeightM": 1.30},
    "head":     {"label": "Head / helmet", "horizon": 0.40, "cameraHeightM": 1.65},
    "handheld": {"label": "Handheld",      "horizon": 0.50, "cameraHeightM": 1.10}
  },
  "geometry": {
    "defaultStepLengthM": 0.70,
    "laneHalfWidthM": 0.60,              // danger lane: |lateral| <= this
    "maxRangeM": 30.0,                   // ignore items whose contact point is farther (pinhole error grows)
    "horizonEma": 0.2,                   // smoothing of the per-frame horizon estimate
    "horizonValidRange": [0.25, 0.75],   // estimates outside -> fall back to the preset
    "minRegionRows": 12                  // need this many valid region rows to fit boundary lines
  },
  "surfaces": {                          // walking region: seed class group + classes allowed inside it
    "groups": {
      "pedestrian": {"label": "sidewalk",  "classes": ["flat sidewalk", "flat pedestrian-area", "flat traffic-island"]},
      "bikeLane":   {"label": "bike lane", "classes": ["flat bike-lane"]},
      "road":       {"label": "road",      "classes": ["flat road", "flat road-shoulder", "flat service-lane", "flat driveway", "parking"]},
      "rail":       {"label": "rail track","classes": ["flat rail-track"]}
    },
    "inside": ["crosswalk", "curb", "lane-line-dashed", "continuous solid", "marking-other", "discrete stop-line",
               "symbol bicycle", "utility-cover", "object pothole", "void ground"],
    "seedBox": [0.40, 0.90, 0.60, 1.00],  // x0, y0, x1, y1: majority surface class here picks the group
    "debounceSeconds": 1.5                 // a surface change must persist this long to count
  },
  "classes": {
    "static":  ["pole", "sign", "traffic-light", "traffic-light pedestrians", "traffic-sign", "sidewalk-obstacle",
                "barrier", "barrier fence", "barrier guard-rail", "divider", "barrier wall", "nature vegetation", "building"],
    "moving":  ["person", "rider", "vehicle", "animal"],
    "feature": ["curb", "crosswalk", "object pothole", "utility-cover"]
  },
  "spokenLabels": {"traffic-light pedestrians": "traffic light", "sidewalk-obstacle": "obstacle", "barrier fence": "fence",
                   "barrier wall": "wall", "barrier guard-rail": "guard rail", "nature vegetation": "vegetation",
                   "rider": "cyclist", "object pothole": "pothole", "utility-cover": "manhole", "...": "..."},
  "parkedLabels": {"vehicle": "parked car"},   // label for a moving-class item judged stationary
  "minComponentFraction": 0.0004,              // of grid area
  "roles": {
    "dangerSteps": 10, "finalSteps": 3,
    "featureSteps": 10,
    "contextMaxDistanceM": 25.0,               // context only announced if within this distance
    "boundaryMarginPx": 2,                     // region dilation used to decide "touches the region boundary"
    "stationaryMps": 0.5,                      // |ground speed| below this = parked / stationary
    "approachingMps": 0.5                      // moving object's own speed toward the user above this = approaching
  },
  "tracking": {"iouMatch": 0.2, "maxMissedSeconds": 1.0, "historySeconds": 2.0,
               "groundGateLateralM": 0.6, "groundGateDistanceFrac": 0.2},
  "ego": {
    "cadenceWindowSeconds": 4.0, "cadenceBandHz": [0.8, 3.5], "cadenceMinPeakRatio": 3.0,
    "speedMinTracks": 1, "speedMaxMps": 6.0, "speedEma": 0.3, "stepLengthRangeM": [0.3, 1.8]
  },
  "contextMemory": {"forgetAfterSeconds": 30.0},
  "pathChange": {"headingDeg": 20.0, "sustainSeconds": 2.0, "referenceTauSeconds": 30.0, "onSurfaceChange": true},
  "speech": {
    "globalMinGapSeconds": 2.5, "contextMaxDelaySeconds": 3.0,
    "templates": {
      "context":  "{label} at {clock} o'clock",
      "surface":  "{label}",
      "feature":  "{label} in {steps} steps",
      "danger":   "{label}, {clock} o'clock, {steps} steps",
      "approach": "{label} approaching, {clock} o'clock",
      "final":    "{label}, {steps} steps"
    }
  },
  "tones": {                                   // danger only; interval/frequency interpolated by stepsTo
    "bySteps": [[10, 1.0, 660], [6, 0.6, 780], [3, 0.3, 940], [1, 0.15, 1100]],   // [steps, intervalSeconds, frequencyHz]
    "durationSeconds": 0.08
  }
}
```

## 7a. v26.1.1 revisions after real-footage review (these override §6/§7 where they differ)

Found on 4929 at 1040–1100 s, run `8ab9a0e06ae3`:
- **Fake approach from horizon wobble.** Per-frame horizon jitter (±0.03) near the vanishing point turned a parked/far car (fixed contact row 0.570) into "approaching at 5–7 m/s", producing false final calls.
- **Lines along the path treated as obstacles.** The central median/curb running *along* the path became features and dangers.
- **Too much context.** Vegetation, fence and manhole phrases piled up.
- **Surface flicker.** The model relabels the same promenade road ↔ bike lane ↔ sidewalk, and each relabel reset the context memory.

The fixes:
1. **Steps use ego speed, not per-object closing.** `stepsTo = distanceM × cadenceHz / egoSpeedMps` when both are known. This is still independent of camera height, since distance and speed scale together. Otherwise use `distanceM / stepLengthM`.
   - The gate is "10 of *your* steps away": a proximity measure, not a time-to-contact measure.
   - Per-object `closingMps` is only used to classify movement.
2. **Common-horizon history for motion.** A track stores the contact **row** history.
   - `closingMps` is the slope of distances recomputed for all history points with the **current** smoothed horizon. It needs ≥ 0.75 s of history and contact ≥ `motionMinRowsBelowHorizon` (8) grid rows below the horizon; otherwise it is `None`.
   - `moving = null` (unknown) is treated as **static** for roles. Unknown movers never become "approaching".
3. **Horizon smoothing:** `horizonEma` 0.05, and the per-frame change is clamped to ≤ `horizonMaxStep` (0.004).
4. **Things that run along the path are boundary, not danger or feature.**
   - **Test:** look at the component's pixels inside the dilated region, from its far row to its near row. If its near/far distance ratio is < 0.5 (it spans a long stretch of path), it runs along the path.
   - **Feature requirement:** a feature must *cross* the lane. It must cover ≥ `featureMinLaneCover` (0.5) of the danger lane's width at its contact row.
   - **Static danger requirement:** a static item must not run along the path. A run-along item that touches the boundary is context; one that doesn't is none.
5. **Features:** `["curb", "crosswalk", "object pothole"]`. Utility covers (manholes) are dropped.
6. **Context:** only `contextSpeak` labels are spoken: `["wall", "fence", "guard rail", "barrier", "parked car"]`. Other context items still get role `context` for the overlay, but stay silent.
7. **Surface:** `pathChange.onSurfaceChange` = false by default, so surface changes no longer clear the context memory.
   - Surface is spoken only on a debounced change **into or out of** the `road`/`rail` groups (or a start on one of them). Debounce is 3.0 s.
   - Pedestrian ↔ bike-lane changes are silent.

New/changed config keys:
- `geometry.horizonEma: 0.05`, `geometry.horizonMaxStep: 0.004`
- `tracking.motionMinRowsBelowHorizon: 8`, `tracking.motionMinSeconds: 0.75`
- `roles.featureMinLaneCover: 0.5`, `roles.alongPathRatio: 0.5`
- `classes.feature` (updated), `contextSpeak`
- `surfaces.debounceSeconds: 3.0`, `surfaces.announceGroups: ["road", "rail"]`
- `pathChange.onSurfaceChange: false`

## 7. Collision logic  (`src/collision.py`, v26.1.1)

**Pure logic:** numpy + scipy and `geometry.Box`/`geometry.iou` only. No cv2, no torch, no file I/O except `load_config`. The Swift app should be able to port it.

```python
@dataclass
class CollisionSettings:
    mount: str; hfov_deg: float; camera_height_m: float
    step_length_m: float | None        # None = estimate, fall back to geometry.defaultStepLengthM
    horizon_default: float             # from the mount preset

def load_config(path: Path | None = None) -> dict
def resolve_settings(config, mount=None, hfov_deg=None, camera_height_m=None, step_length_m=None) -> CollisionSettings
def bearing_deg(x_norm, hfov_deg) -> float            # unchanged from v26.1.0
def clock_from_bearing(bearing) -> int                # unchanged from v26.1.0
def focal_px(grid_w, hfov_deg) -> float               # (grid_w / 2) / tan(hfov / 2)
def ground_distance_m(y_norm, horizon_y, camera_height_m, grid_h, f_px) -> float | None
    # H * f / ((y - horizon) * grid_h); None if y <= horizon
def lateral_m(x_norm, distance_m, grid_w, f_px) -> float   # (x - 0.5) * grid_w * distance / f
def estimate_cadence(t, dy, window_s, band_hz, min_peak_ratio) -> np.ndarray   # per-sample Hz or nan
def walking_region(grid, ids, config) -> Region | None
def run_collision(grids, times, class_names, config, settings, motion=None) -> tuple[dict, dict]
    # motion: {"t": ndarray, "dx": ndarray, "dy": ndarray} or None -> ego estimates unavailable
```

**Per frame:**
1. **Walking region:**
   - Find the majority surface class inside `seedBox` (surface-group classes only; ties → the group with more pixels). No surface pixels → `region = None`.
   - Region = the 4-connected component, containing seed pixels, of (that group's classes ∪ `surfaces.inside`).
   - Per grid row, take `left/right` = min/max column of region pixels in that row.
   - Rows with no pixels are invalid. Smooth `left/right` per row with EMA 0.5 across frames (reset when the surface group changes).
2. **Horizon:**
   - Fit lines `x = a·y + b` to the left and right bounds of the lowest 70% of valid region rows (least squares, needs ≥ `minRegionRows`).
   - The intersection's y is the raw horizon. Accept it if it lies within `horizonValidRange` and the lines converge upward (left slope < 0 < right slope, in x-per-y terms with y downward); otherwise use `horizon_default`.
   - EMA with `horizonEma`. `horizonEstimated` = whether the raw estimate was accepted this frame.
3. **Items:**
   - 4-connected components of each class group (static / moving / feature) over the whole grid below the horizon, with in-image pixel count ≥ `minComponentFraction` × grid area.
   - **Contact point** = the bottom-most row of the component (static/moving). For features, use the bottom-most row *inside the danger lane* if any, else the bottom-most row.
   - Compute `distanceM`, `lateralM` (at the contact point; lateral from the column of the contact row's pixels nearest to x = 0.5), `bearingDeg`, `clock`, `pan`.
   - Drop items with `distanceM > maxRangeM` or `None`.
4. **Tracking:**
   - Greedy matching within the same group and label. A pair matches if `iou(bbox) ≥ iouMatch` **or** the ground gate holds: `|Δlateral| ≤ groundGateLateralM` and `|Δdistance − expected| ≤ groundGateDistanceFrac × distance`, where `expected = −closing·dt` (0 if unknown).
   - Score = IoU, plus 0.5 if the ground gate holds. Highest score first.
   - Tracks survive `maxMissedSeconds`. Keep `(t, distanceM)` over `historySeconds`. `closingMps` = −slope (least squares, ≥ 3 points), else `None`.
5. **Ego:**
   - **Cadence:** from `motion` (the nearest motion sample to `t`).
   - **Speed:** the median `closingMps` over **static**-group tracks with `closingMps` in [0, speedMaxMps] (≥ `speedMinTracks`), then EMA `speedEma`. None if there are no tracks yet.
   - **Step length:** `settings.step_length_m` if set; else `speed / cadence` clamped to `stepLengthRangeM` when both are known (EMA-smoothed); else `defaultStepLengthM`.
   - **Heading:** integrate `−dx × hfov_deg` over motion samples (degrees, + = turned right).
6. **Steps:**
   - If `closingMps ≥ 0.3` and cadence is known: `stepsTo = distanceM / closingMps × cadenceHz`.
   - Otherwise `stepsTo = distanceM / stepLengthM`.
   - Round to an integer for speech; keep 1 decimal in JSON.
7. **Moving vs parked:** only for moving-group tracks with known ego speed and `closingMps`. `groundSpeed = closingMps − egoSpeed` (toward the user = positive).
   - `|groundSpeed| < stationaryMps` → `moving = false`; the item is treated as **static** from here, and its label comes from `parkedLabels`.
   - `groundSpeed > approachingMps` → approaching.
   - If unknown: `moving = null`; treat it as moving.
8. **Roles** (one per item):
   - **danger:**
     - A static (or parked) item with any pixel of its component inside the walking region (dilated by `boundaryMarginPx`) at a row where its `|lateralM| ≤ laneHalfWidthM`, and `stepsTo ≤ dangerSteps`.
     - A moving item whose contact point is within the region's row span and within `laneHalfWidthM + 1.0` m laterally, and either approaching or with `|lateralM| ≤ laneHalfWidthM`, and `stepsTo ≤ dangerSteps`.
   - **feature:** a feature-class item whose component overlaps the danger lane and that has `stepsTo ≤ featureSteps`.
   - **context:** a static/parked item that touches the dilated region boundary but isn't danger, with `distanceM ≤ contextMaxDistanceM`.
   - **none:** everything else.
   - `urgency` = `final` if danger and `stepsTo ≤ finalSteps`, `danger` if danger, else `none`.
9. **Path change** → clear the context memory:
   - |heading − reference| > `headingDeg` sustained for `sustainSeconds`. The reference follows the heading with time constant `referenceTauSeconds`, and is reset to the heading on a path change.
   - Or (if `onSurfaceChange`) a debounced surface-group change.

**Speech** (at most one phrase per frame; this is "less is more"):
- **Candidates, in priority order:**
  1. **final:** a danger track crossing ≤ `finalSteps` for the first time. Spoken once per track; it ignores the global gap.
  2. **danger:** a danger track not yet announced. Use the `approach` template for approaching movers, else `danger`. Once per track.
  3. **feature:** a feature track not yet announced. Once per track; also suppressed if the same label was announced < 5 s ago.
  4. **surface:** a debounced surface change (including the first surface of the run).
  5. **context:** a `(label, side)` pair not in memory. `side` = `left` if clock ∈ {9, 10}, `ahead` if {11, 12, 1}, `right` if {2, 3}. A pair stays in memory while seen within `forgetAfterSeconds`; it is cleared on path change.
- A candidate that can't be spoken because of `globalMinGapSeconds` stays pending, except that context older than `contextMaxDelaySeconds` is dropped.
- Context and surface are held back while any danger track is active.
- Danger/feature tracks are marked announced only when actually spoken. If a danger track is already within `finalSteps` when first announced, speak only the final call.

**Tones:** only while a danger track is active.
- The single danger track with the smallest `stepsTo` drives one phase-continuous beep stream, as in v26.1.0.
- Interval and frequency are linearly interpolated from `tones.bySteps` by `stepsTo` (clamped to the table ends). Pan comes from that track's bearing.

**`hazards.json`:**
```jsonc
{"version": "v26.1.1",
 "settings": {"mount": "chest", "hfovDeg": 118, "cameraHeightM": 1.3, "stepLengthM": null, "laneHalfWidthM": 0.6},
 "gridW": 240, "gridH": 135, "egoAvailable": true,
 "frames": [{
   "index": 0, "t": 60.0,
   "horizonY": 0.452, "horizonEstimated": true,
   "region": {"surface": "bikeLane", "label": "bike lane",
              "rows": [[0.70, 0.21, 0.83], [0.73, 0.18, 0.86], ...]},   // [y, left, right], every 4th grid row, bottom→top
   "lane": [[0.41, 1.0], [0.59, 1.0], [0.53, 0.58], [0.47, 0.58]],    // danger-lane polygon (normalised), near→far at dangerSteps
   "ego": {"speedMps": 1.32, "cadenceHz": 1.85, "stepLengthM": 0.71, "headingDeg": -3.2,
           "estimated": {"speed": true, "cadence": true, "stepLength": true}},
   "pathChange": false,
   "hazards": [
     {"trackId": 3, "className": "pole", "group": "static", "label": "pole", "role": "danger", "moving": false,
      "bbox": [0.48, 0.52, 0.55, 0.81], "contactY": 0.81, "bearingDeg": 4.1, "clock": 12, "pan": 0.07,
      "distanceM": 5.6, "lateralM": 0.21, "stepsTo": 7.9, "closingMps": 1.3, "urgency": "danger", "areaFrac": 0.012}
   ]}]}
```
- `region` is null when there is no surface.
- `lane` is computed from the geometry: half-width in px at row y = `laneHalfWidthM · (y − horizon)·grid_h / H` (converted to normalised x). It runs from y = 1.0 up to the row at `dangerSteps × stepLengthM`.
- Items with role `none` are still listed (the UI greys them).

**`events.json`:** sorted by `t`.
```jsonc
{"version": "v26.1.1", "events": [
  {"t": 61.2, "type": "speech", "role": "context", "text": "wall at 1 o'clock", "trackId": 5, "urgency": "none", "clock": 1, "pan": 0.48},
  {"t": 64.0, "type": "speech", "role": "danger", "text": "pole, 12 o'clock, 8 steps", "trackId": 3, "urgency": "danger", "clock": 12, "pan": 0.07},
  {"t": 64.0, "type": "tone", "role": "danger", "trackId": 3, "urgency": "danger", "pan": 0.07, "frequencyHz": 690, "durationSeconds": 0.08}
]}
```
- The `role` of a speech event is one of `context | surface | feature | danger | final`.
- Surface events have `trackId: null` and `clock: null`.

## 8. REST API  (`lab/server.py`, FastAPI)

| Method + path | Body / query | Returns |
|---|---|---|
| `GET /` | | `lab/static/index.html` (static files at `/static/*`) |
| `GET /api/recordings` | | `[Recording]` (§3) |
| `POST /api/recordings/{id}/proxy` | | `{"status": ...}`; starts a build if missing/error |
| `GET /media/{id}.mp4` | | the proxy file, with HTTP Range support; 404 if not ready |
| `GET /api/recordings/{id}/settings` | | Settings (§4) + `"resolved": {"hfovDeg", "cameraHeightM", "stepLengthM" (null = auto), "horizon"}` |
| `PUT /api/recordings/{id}/settings` | Settings | same as GET |
| `GET /api/config/collision` | | collision.json contents |
| `GET /api/models` | | `{"models": [{"path", "name", "default": bool}], "profiles": [...]}` |
| `POST /api/runs` | run request (§5) | `run.json`; queued, or done if cached |
| `GET /api/runs?recording=<id>` | | `[run.json]`, newest first |
| `GET /api/runs/{runId}` | | `run.json` |
| `POST /api/runs/{runId}/collision` | | re-runs §7 from `grids.npz` (+ `motion.npz` if present) with the recording's **current** settings; returns `{"version", "hazards", "events", "elapsedSeconds"}` |
| `GET /api/runs/{runId}/hazards.json` · `events.json` | | the files |
| `GET /api/runs/{runId}/frames/{i}/mask.png` | | the mask PNG (`Cache-Control: max-age=86400`) |

The collision pass calls `collision.resolve_settings(config, mount, hfovDeg, cameraHeightM, stepLengthM)` and `collision.run_collision(grids, times, class_names, config, settings, motion)`.

## 9. Frontend  (`lab/static/`, vanilla JS, no build step)

Same as v26.1.0, with these differences:
- **Overlay** (each layer toggleable):
  - **Mask:** as before.
  - **Walking region:** an outline polygon from `frame.region.rows` (left edge bottom→top, then right edge top→bottom), in a thin white line, with `region.label` written near its top.
  - **Danger lane:** the `frame.lane` polygon, semi-transparent red fill.
  - **Horizon:** a dashed line at `horizonY`, solid if `horizonEstimated`.
  - **Items**, coloured by role:
    - danger orange `#ff8c1a`, with a final call in red `#ff2d2d`
    - feature cyan `#22d3ee`
    - context light grey `#c9ced6`
    - none dim grey `#6b7280`, drawn thin, label hidden unless "show all" is on
  - **Labels:** `"<label> · <clock> · <stepsTo>st"`; context labels show only `"<label> · <clock>"`.
  - The v26.1.0 corridor trapezoid layer is removed.
- **HUD** in the player's top-left corner:
  - speed in m/s and km/h
  - cadence in steps/min (`cadenceHz × 60`)
  - step length in m
  - heading
  
  Show "—" for unknown values, and mark estimated vs default values (e.g. `0.70 m (default)`).
- **Settings panel:** mount, HFOV, camera height (m), step length (m). Empty = auto/default, with the resolved default value as placeholder.
- **Event list and timeline:** role filter chips (context, surface, feature, danger, final), all on by default. Timeline ticks are coloured by role.
- **Audio:** as v26.1.0 (tones come only from danger events). Final calls pre-empt any phrase currently being spoken.
- **Old runs** (no `region`/`ego` in hazards): draw what's present, and the HUD shows "no ego data (re-analyse)".

## 10. Speech reviews  (v26.1.2: `lab/reviews.py`, `lab/server.py`, `lab/static/js/reviews.js`)

**Purpose:** ground truth for analysing and planning later collision versions. The user judges each spoken phrase while watching, and adds phrases the system missed.

**Reviews belong to the recording, not the run.** What should be said at a recording time is stable across re-analysis and new collision versions. Each verdict snapshots the event it judged, plus the `runId` and `collisionVersion` it came from.

### Storage — `LAB_DIR/reviews/<recId>.json` (atomic writes, like `recordings._atomic_write_json`)
```jsonc
{"recording": "4929", "annotations": [
  {"id": "a1b2c3d4", "kind": "verdict",
   "verdict": "correct|incorrect|remove",          // remove = "should not be said" (kept, struck through, undoable)
   "note": "free text (<= 2000 chars, may be empty)",
   "t": 1089.84,                                    // = event.t
   "event": {"t": 1089.84, "text": "vehicle, 12 o'clock, 9 steps", "role": "danger",
             "trackId": 1416, "urgency": "danger", "clock": 12},
   "runId": "8ab9a0e06ae3", "collisionVersion": "v26.1.1", "analysisVersion": 2,
   "modelName": "Yolo26m-sem-HackEye20261012-544.pt",
   "createdAt": "2026-10-16T13:00:00Z", "updatedAt": "2026-10-16T13:00:00Z"},
  {"id": "e5f6a7b8", "kind": "added",               // a phrase the system should have said
   "t": 1052.3, "text": "bench, 1 o'clock, 4 steps",
   "role": "context|surface|feature|danger|final|other", "note": "",
   "runId": "8ab9a0e06ae3", "collisionVersion": "v26.1.1",
   "createdAt": "...", "updatedAt": "..."}
]}
```
- `id`: 8 random hex characters, assigned by the server.
- `analysisVersion` and `modelName` are filled by the server from the run's `run.json` when `runId` is given.
- **Matching key** (verdict ↔ event of the loaded run): `(runId, collisionVersion, round(event.t, 3), event.text)`. Re-running collision with the same version reproduces identical events, so verdicts stay attached.
- There is at most one verdict per matching key. POSTing a second one for the same key returns **409**; the client PUTs instead.
- `added` annotations are shown with every run of the recording, whatever its `runId`/`collisionVersion`; those fields only record what was loaded when they were made.

### API
| Method + path | Body | Returns |
|---|---|---|
| `GET /api/recordings/{id}/reviews` | | `{"recording", "annotations": [...]}` (sorted by `t`) |
| `POST /api/recordings/{id}/reviews` | annotation without `id`/`createdAt`/`updatedAt` | the stored annotation, 201 |
| `PUT /api/recordings/{id}/reviews/{annId}` | any of `{verdict, note, t, text, role}` | the updated annotation |
| `DELETE /api/recordings/{id}/reviews/{annId}` | | 204 |
| `GET /api/reviews/export?recording=<id>` | omit the query to export all recordings | the export below |

**Validation (422 otherwise):**
- `kind` ∈ `verdict | added`; `verdict` is required for kind verdict.
- `verdict` ∈ `correct | incorrect | remove`.
- `role` ∈ `context | surface | feature | danger | final | other`.
- `0 ≤ t ≤ recording.duration`.
- `text` is required and non-empty for `added`, at most 300 characters.
- `note` is at most 2000 characters.
- `event` is required for `verdict`.
- `runId`, if given, must exist.
- Unknown recording or annotation → 404.

**Export** (`GET /api/reviews/export`):
```jsonc
{"exportedAt": "...", "recordings": [
  {"recording": "4929", "summary": {"correct": 3, "incorrect": 1, "remove": 1, "added": 2},
   "annotations": [ { ...annotation...,
      "context": {                                   // from the annotation's run (null if the run or its hazards are gone)
        "frameT": 1089.84,                           // nearest analysed frame
        "items": [ ...hazards items with role != "none"... ],
        "ego": {...}, "surface": "road", "horizonY": 0.43,
        "nearbySpeech": [ ...the run's speech events within ±3 s... ]
      } } ] } ]}
```

### UI (right-hand review panel)
- **Layout:**
  - Width ≥ 1200 px: three columns, i.e. sidebar | player | review panel (about 380 px, `position: sticky`, own scroll, full viewport height).
  - 900–1199 px: the panel goes under the player.
  - Below 900 px: stacked.
  - The old "Speech events" list under the timeline is **replaced** by this panel; the role chips keep filtering it.
- **Header counts:** ✓ correct · ✗ incorrect · ⊘ should-not-be-said · + added · unreviewed (= speech events of the loaded run without a matching verdict).
- **Rows**, one per speech event of the loaded run plus added annotations, sorted by `t`:
  - timestamp `m:ss.s`, which seeks on click
  - role badge, coloured as the overlay roles
  - text
  - toggles **✓**, **✗**, **⊘**:
    - Clicking an inactive toggle creates or updates the verdict.
    - Clicking the active one deletes the verdict.
    - ⊘ shows the text struck through.
  - a note `<textarea>`, shown when a verdict is set or the row is expanded; autosaves after 600 ms of inactivity and on blur, with a small "saved ✓" indicator
- **Added rows:**
  - A distinct style with a "+ added" badge.
  - Inline-editable time (plus a "⟲ playhead" button), text, role select and note.
  - 🗑 delete, with confirm.
- **"+ Add speech at playhead"**: an inline form (time prefilled from the playhead, text, role defaulting to danger, note). It POSTs a `kind: added` annotation with the loaded `runId`/`collisionVersion`.
- **Following playback:** the row nearest before the playhead is highlighted and scrolled into view during playback (not while the user is typing).
- **"Other versions (n)":** a collapsed section with verdicts whose matching key doesn't match the loaded run, read-only apart from 🗑.
- **Keyboard** (ignored while focus is in an input, textarea or select):
  - `c` / `x` / `r` toggle correct / incorrect / remove on the highlighted row.
  - `a` opens "add at playhead".
- **Optimistic updates:** on API failure, show a toast with `detail` and revert. Reviews load when a recording is selected; they don't depend on a run being loaded, but verdict rows need a run.

### 10a. Add-form helpers (v26.1.3)
- **Time follows the paused playhead.**
  - While the video is paused, the add form's time field tracks the playhead. It updates on `seeked`, on frame step and on `pause`, and is filled when the form opens.
  - A manual edit of the time field stops this until the next pause, seek or reopen of the form. The "⟲ playhead" button also re-enables it.
  - While playing, the field is left alone.
- **Auto-fill button** (next to the text field):
  - **Frame:** the analysed frame with the largest `t ≤ form time` from the loaded run's hazards (nothing if outside the run range: show a toast).
  - **Candidates:** all of that frame's `hazards` items, ordered by role (`final` → `danger` → `feature` → `context` → `none`), then by `stepsTo` ascending (nulls last).
  - **Fill:** text from `collision.json` `speech.templates` (from `GET /api/config/collision`):
    - danger/final/none → `danger`
    - feature → `feature`
    - context → `context`
    - movers with `moving === true` and positive `closingMps` → `approach`
    
    Use `{label}`, `{clock}` and `{steps}` = round(`stepsTo`). The role select is set to the item's role; `none` maps to `danger`, since a missed item is usually a missed warning, and the user can change it.
  - **Cycling:** clicking Auto-fill again cycles to the next candidate. An indicator shows `n/N · <className> · <role>`. Changing the form time resets the cycle.
  - **Behaviour:** the text stays editable after auto-fill; auto-fill only overwrites text and role, never the note. With no candidates, show a toast "nothing detected at this time".

## 11. Version-scoped Lab content  (v26.1.3: `RnD/VERSION`, `lab/versioning.py`)

The user's rule: **each new version cleans up the previous version's Lab content, so it starts fresh.**
- **Version source:** `RnD/VERSION` holds one line, the current HackEye version (e.g. `v26.1.3`). Claude bumps it in every version commit.
- **Marker:** `LAB_DIR/.lab-version` = `{"version": "v26.1.3", "since": "<UTC ISO>"}`.
- **At Lab startup** (FastAPI lifespan/startup, before serving), `apply_version_policy(lab_dir, version_file)` runs:
  - **`VERSION` missing, unreadable or empty:** log an error and do **nothing**. Never wipe on doubt.
  - **Marker missing:** write the marker with the current version and wipe nothing. That's the first adoption.
  - **Marker version == current:** nothing.
  - **Marker version != current:** **wipe** the contents of `LAB_DIR/runs/` and `LAB_DIR/reviews/`. Delete only paths that resolve inside those two directories; never follow symlinks out. Then rewrite the marker and log `[lab] version v26.1.3 -> v26.1.4: removed N runs, M review files`.
- **Kept:** `proxies/` (version-independent, slow to rebuild), `recordings/` (per-recording settings), `.ultralytics/`.
- **Result:** returns a dict `{"previous", "current", "wiped": bool, "runsRemoved", "reviewFilesRemoved"}`, which is also logged.
- **`GET /api/version`** → `{"version", "since", "lastWipe": <result of the startup check>}`.
- **The UI** shows the version in the page header (small, muted), e.g. `HackEye Lab · v26.1.3`.

### 11a. One analysis per recording, visible progress, cancellation (v26.1.3)
- **One active run per recording.** `POST /api/runs` returns **409** `{"detail": "Analysis already running for <rec> (run <id>, <pct>%)"}` while any run of the **same recording** is `queued` or `running`. An identical request still returns that in-flight run as today; a done identical request still returns the cached run. Other recordings can queue as before (FIFO, one GPU job at a time).
- **Cancellation:**
  - The GPU worker checks a per-run cancel flag between frames.
  - `POST /api/runs/{id}/cancel` sets the flag, or removes the run from the queue if it hasn't started yet. The run ends as `status: "cancelled"` with partial outputs removed.
  - Returns the run doc; 409 if the run is already done, error or cancelled.
  - Cancelled runs are listed but can't be played (like error runs). Re-POSTing the same request starts it fresh.
- **Progress when selecting a recording:** whenever a recording is selected (or on page load via the URL hash), the UI checks `GET /api/runs?recording=` for a queued or running run. If there is one it:
  - shows the existing progress bar, polling every 1 s;
  - disables **Analyse**, with the reason as a tooltip;
  - shows a **Cancel** button.
  
  This must work for runs started in another tab or on another device. On completion it behaves as for a run started on this page (enable Analyse, list the run, offer to load it).
- **Version cleanup kills analyses:**
  - **At startup:** besides the startup check, a background thread re-reads `RnD/VERSION` every 30 s. If it differs from the marker it:
    1. cancels every queued and running job (clears the queue, sets the cancel flags);
    2. waits up to 30 s for the worker to go idle;
    3. releases the GPU model;
    4. runs the wipe (§11).
  - **If the worker doesn't go idle within 30 s:** log an error and skip the wipe, then retry on the next check.
  - **Before any wipe** (startup or live), run docs left `queued`/`running` from a previous process are irrelevant, because they get deleted.

## 12. v26.1.5 changes

### 12.1 Large runs: windowed hazards (Lab)
- A full-length run's `hazards.json` is about 118 MB (18,558 frames), too big for the browser to load whole.
- **New endpoints:**
  - `GET /api/runs/{id}/hazards?from=<s>&to=<s>` → `{version, settings, gridW, gridH, egoAvailable, from, to, frames: [...]}`, the frames with `from ≤ t ≤ to`. A window is at most 600 s (422 otherwise).
  - `GET /api/runs/{id}/frame?t=<s>` → `{frame}`, the analysed frame with the largest `t ≤ s`, or 404 when outside the run.
- **Server cache:** it parses `hazards.json` once per run, keeps an LRU of 2 runs, and invalidates on the file's mtime (a collision re-run rewrites it).
- **Gzip:** `GZipMiddleware(minimum_size=1024)` for all JSON.
- **Frontend:** holds a window of ±90 s around the playhead, prefetches the next window when the playhead is within 30 s of the window's end, and refetches on seek outside the window.
  - Overlay and HUD use the window.
  - The timeline and review panel use `events.json`, which stays small.
  - The old full `hazards.json` route stays for compatibility, but the UI no longer uses it.

### 12.2 UI defaults and fixes (Lab)
- **Analysis range:** defaults to `0 → recording duration` on recording select; the "from playhead" buttons stay.
- **Audio:**
  - Armed by default. The `AudioContext`/speech unlock happens on the **first** `pointerdown`, `keydown` or `touchend` anywhere in the page (once).
  - The audio button becomes a toggle: "🔊 Audio on" / "🔇 Audio off". Speech and tones stay checked by default.
  - For E2E tests, expose `window.__labAudioLog`, an array of `{at, mediaT, type, text|freq, source}` pushed whenever speech is spoken or a tone is scheduled (`source` = `system` | `added`).
- **Auto-fill** fetches `GET /api/runs/{id}/frame?t=<form time>` (spinner on the button meanwhile), then uses the existing `orderCandidates`/`fillFor`.
- **Add form:**
  - Opening it always takes the current playhead.
  - While paused, the time follows every seek and frame step.
  - Submit fully resets the form, so the next open re-reads the playhead.
  - The time field shows a "↻ following playhead" indicator while it is tracking.
  - **Bug to reproduce and fix:** the user's second added phrase got the first one's time (both saved with `t=0.2`).
- **Review preview** ("Hear review edits" checkbox in the Audio panel, on by default):
  - Playback merges added annotations as speech events at their `t` (`source: "added"`).
  - System speech events with a ⊘ `remove` verdict are skipped.
  - Re-merged whenever reviews change. Toggle off = only the system's speech.

### 12.3 Collision v26.1.5 (`collision.json` `"version": "v26.1.5"`), from the user's review (`RnD/tests/fixtures/4929_review1.json`)
1. **Confirmation:** danger, final and feature speech need the track to hold that role in **≥ `roles.confirmFrames` (2) consecutive analysed frames**.
2. **Final template** becomes `"{label}, {clock} o'clock, {steps} steps"`, so the location is always included.
3. **Danger for non-moving items:**
   - An item with `moving !== true` (static, parked, or unknown) is danger **only if its contact point is inside the danger lane**: `|lateralM| ≤ laneHalfWidthM` at the contact row, inside the region.
   - Pixel intrusion alone no longer counts. A vehicle beside the path is context, never danger.
4. **Context memory by label:**
   - Once a spoken context label (e.g. "parked car") has been announced, it isn't repeated while seen within `forgetAfterSeconds` (30), on any side or clock position.
   - It is cleared on a path change (turn).
5. **Grouped context phrase:**
   - In a frame where at least one context label is newly announceable, all newly announceable context items (nearest first, at most `speech.contextMaxItems` = 3, one per label) are joined into **one phrase**: `"{label} at {clock}"` items joined by `", "`.
   - Examples: `"obstacle at 12, building at 2"`, `"vehicle at 11, building at 1"`.
   - The template key is `speech.templates.contextGroup` = `"{items}"`, with item template `"{label} at {clock}"`.
6. **contextSpeak** adds `"building"` and `"obstacle"`. `spokenLabels` maps barrier-type and `sidewalk-obstacle` classes to "obstacle".
7. **Start summary:** the first context phrase of a run, and after a path change, may come before the 1.5 s warm-up. It needs only `confirmFrames` frames, so the user hears the scene within about the first second.
8. **Regression tests** (`tests/test_collision_regression.py`) run `run_collision` on the fixture windows and assert the expectations recorded in the fixture's annotations.

## 13. Browser E2E harness (`RnD/tests/e2e/`)
- Playwright (Python) in `mcr.microsoft.com/playwright/python` with the **Google Chrome channel** (`playwright install chrome`, which plays H.264), against the live Lab (`--network host`, `http://127.0.0.1:8765`).
- Launch flags: `--autoplay-policy=no-user-gesture-required`; the audio checks use `window.__labAudioLog`.
- Run with `RnD/tests/e2e/run.sh`.
- Tests create their own short runs/reviews (on 4928, or a short 4929 range) and delete them afterwards.
- Never trigger a version change.
