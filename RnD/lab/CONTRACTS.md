# HackEye Lab — contracts (v26.1)

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
  "corridor": null             // null = the mount preset's corridor; else a Corridor (§6)
}
```
`GET` returns the stored settings or the defaults (`mount = defaultMount`).
`PUT` validates and stores them.

## 5. Analysis runs  (`lab/analysis.py`)

**Request:** `{"recording": "4927", "start": 60.0, "end": 120.0, "model": "/hackeye-models/Yolo26m-sem-HackEye20261012-544.pt", "profile": "default", "fps": 6.0}`
- `profile` ∈ `default | production | half | quarter`, passed to `profiles.resolve_input_spec(src_w, src_h, profile_or_None, None, None)`. `default` → `None`.
- `runId` = first 12 hex chars of sha1 over the canonical JSON of the request plus the model file's mtime. If a finished run with that id exists, it is reused.

**Per sampled frame** (times `start, start + 1/fps, …, < end` in recording time; decode sequentially with `grab()`/`retrieve()` like `src/pipeline.py`, crossing chapter boundaries):
1. BGR→RGB, then `letterbox_with_meta(rgb, spec.dst_w, spec.dst_h)`.
2. `SegmentationModel.predict_class_grid(...)`, then `grid_from_semantic_mask(class_ids, meta)`.
3. **Crop the padding:** keep rows `[round(pad_y), round(pad_y + src_h*scale))` and the matching columns. Resize nearest-neighbour to `GRID_W = 240`, `GRID_H = round(240 * src_h / src_w)`, as `uint8`.
4. Write `masks/<i>.png`: an RGBA image at grid size. Pixel colour is `SAFETY_LEVELS[level]["color"]` with alpha 255; level 0 (ignored) is fully transparent.

**`grids.npz`:** `grids` uint8 (N, GRID_H, GRID_W), `t` float64 (N,) in recording seconds, `index` int32 (N,).

**`run.json`:**
```jsonc
{
  "id": "a1b2c3d4e5f6", "request": {...as above...},
  "status": "queued|running|done|error", "progress": 0.0, "error": null,
  "createdAt": "2026-10-16T12:00:00Z", "finishedAt": null,
  "frameCount": 360, "gridW": 240, "gridH": 135,
  "srcW": 1920, "srcH": 1080,
  "inputSpec": {"w": 960, "h": 544, "description": "..."},
  "modelName": "Yolo26m-sem-HackEye20261012-544.pt",
  "classNames": ["animal", "barrier", ...],     // from the model, in id order
  "msPerFrame": 123.4,
  "collisionVersion": "v26.1.0"                   // version of the last collision pass
}
```
After inference finishes, the runner immediately does a collision pass (§7)
with the recording's current settings.

**GPU:**
- One worker thread runs one job at a time; extra jobs wait in a FIFO queue.
- `gpu_guard.assert_torch_cuda()` is called at job start.
- The `SegmentationModel` is cached by path and released after 300 s idle (`del` + `torch.cuda.empty_cache()`), so the always-on service holds no VRAM between runs.

## 6. Collision config  (`common/config/collision.json`)

```jsonc
{
  "version": "v26.1.0",
  "obstacleClasses": {
    "static": ["pole", "sign", "traffic-light", "traffic-light pedestrians", "traffic-sign",
               "sidewalk-obstacle", "barrier", "barrier fence", "barrier guard-rail",
               "divider", "barrier wall", "nature vegetation"],
    "moving": ["person", "rider", "vehicle", "animal"]
  },
  "spokenLabels": {"traffic-light pedestrians": "traffic light", "sidewalk-obstacle": "obstacle",
                   "barrier fence": "fence", "barrier wall": "wall", "nature vegetation": "vegetation",
                   "rider": "cyclist", "...": "..."},   // fallback: name with '-' -> ' '
  "defaultMount": "chest",
  "defaultHfovDeg": 118,
  "mountPresets": {
    "chest":    {"label": "Chest",          "corridor": {"horizon": 0.45, "bottomY": 1.0, "topWidth": 0.12, "bottomWidth": 0.60, "centerX": 0.5}},
    "head":     {"label": "Head / helmet",  "corridor": {"horizon": 0.40, "bottomY": 1.0, "topWidth": 0.10, "bottomWidth": 0.45, "centerX": 0.5}},
    "handheld": {"label": "Handheld",       "corridor": {"horizon": 0.50, "bottomY": 1.0, "topWidth": 0.14, "bottomWidth": 0.70, "centerX": 0.5}}
  },
  "minComponentFraction": 0.0004,       // of grid area, counted inside the corridor
  "urgency": {                           // a level fires if proximity >= p OR (ttc != null AND ttc <= ttc)
    "static": {"caution": {"proximity": 0.35, "ttc": null}, "warning": {"proximity": 0.60, "ttc": 3.0}, "imminent": {"proximity": 0.85, "ttc": 1.5}},
    "moving": {"caution": {"proximity": 0.25, "ttc": null}, "warning": {"proximity": 0.50, "ttc": 4.0}, "imminent": {"proximity": 0.75, "ttc": 2.0}}
  },
  "tracking": {"iouMatch": 0.2, "maxMissedSeconds": 1.0, "approachWindowSeconds": 1.5},
  "speech": {"template": "{label}, {clock} o'clock", "trackCooldownSeconds": 4.0, "globalMinGapSeconds": 1.2},
  "tones": {
    "intervalSeconds": {"caution": 1.0, "warning": 0.5, "imminent": 0.2},
    "frequencyHz":     {"caution": 660, "warning": 880, "imminent": 1100},
    "durationSeconds": 0.08
  }
}
```
**Corridor** (normalised, §1) is a trapezoid:
- Its top edge sits at y = `horizon`, `topWidth` wide.
- Its bottom edge sits at y = `bottomY`, `bottomWidth` wide.
- Both edges are centred on `centerX`.

## 7. Collision logic  (`src/collision.py`)

**Pure logic:** numpy + scipy and `geometry.Box` only. No cv2, no torch, no file
I/O except `load_config`. The Swift app should be able to port it.

```python
@dataclass
class Corridor: horizon: float; bottom_y: float; top_width: float; bottom_width: float; center_x: float
@dataclass
class CollisionSettings: corridor: Corridor; hfov_deg: float

def load_config(path: Path | None = None) -> dict                      # default find_common_dir()/config/collision.json
def resolve_settings(config: dict, mount: str | None, hfov_deg: float | None, corridor: dict | None) -> CollisionSettings
def corridor_mask(grid_w: int, grid_h: int, c: Corridor) -> np.ndarray   # bool (H, W)
def bearing_deg(x_norm: float, hfov_deg: float) -> float                # pinhole: atan((x-0.5)*2*tan(hfov/2)), degrees, + = right
def clock_from_bearing(bearing: float) -> int                           # 12 + round(b/30) -> 9,10,11,12,1,2,3 (clamped to ±90°)
def run_collision(grids, times, class_names, config, settings) -> tuple[dict, dict]   # (hazards_doc, events_doc)
```

**Per frame:**
1. Split the obstacle mask into `static` and `moving` groups (class names resolved against `class_names`; names not present are skipped).
2. Find 4-connected components per group (`scipy.ndimage.label`), restricted to pixels inside the corridor.
3. Keep a component if its in-corridor pixel count is at least `minComponentFraction × grid area`.
4. For each kept component:
   - `className`: the majority class.
   - `bbox`: normalised, from its in-corridor pixels.
   - `contactY`: (max in-corridor row + 1) / H.
   - `proximity = clamp((contactY − horizon) / (bottomY − horizon), 0, 1)`.
   - `bearingDeg` from the mean in-corridor x, then `clock`.
   - `pan = clamp(sin(bearing), −1, 1)`.

**Tracking:**
- Greedy IoU matching on `bbox`, same group only, threshold `iouMatch` (same approach as `src/track.py`).
- A track survives `maxMissedSeconds` without a match.
- **TTC:** take the slope `dp/dt` of a linear fit of (t, proximity) over the last `approachWindowSeconds`. If the slope > 0, `ttc = (1 − proximity) / slope`; otherwise `null`.

**Urgency** is the highest level whose rule fires for the track's group (§6), else `none`.

**Speech events:**
- A track triggers speech when its urgency first reaches `caution`, or rises to a higher level than it last spoke at.
- Speech is suppressed if the same track spoke less than `trackCooldownSeconds` ago, unless the new level is `imminent`.
- Speech is dropped (not delayed) if any speech happened less than `globalMinGapSeconds` ago, again unless the new level is `imminent`.
- If several hazards qualify in the same frame, only the most urgent one speaks; ties go to the higher proximity.
- Text: `template.format(label=spokenLabel, clock=clock)`.

**Tone events:**
- **Only one beep stream, so it never turns into noise.** In each frame interval `[t_i, t_{i+1})`, the most urgent hazard (ties → higher proximity) at `caution` or above emits beeps.
- Beeps follow that hazard's urgency interval and keep their phase across frames: the next beep is due `interval` after the previous one, whichever hazard it came from.
- The last frame's interval is `1/fps`, taken from the median frame spacing.

**`hazards.json`:**
```jsonc
{"version": "v26.1.0", "settings": {"corridor": {...}, "hfovDeg": 118, "mount": "chest"},
 "gridW": 240, "gridH": 135,
 "frames": [{"index": 0, "t": 60.0, "hazards": [
   {"trackId": 3, "className": "pole", "group": "static", "label": "pole",
    "bbox": [0.48, 0.52, 0.55, 0.81], "contactY": 0.81, "proximity": 0.65,
    "bearingDeg": 4.1, "clock": 12, "pan": 0.07, "ttc": 2.4, "urgency": "warning", "areaFrac": 0.012}
 ]}]}
```
**`events.json`:** sorted by `t`.
```jsonc
{"version": "v26.1.0", "events": [
  {"t": 61.2, "type": "speech", "text": "pole, 12 o'clock", "trackId": 3, "urgency": "caution", "clock": 12, "pan": 0.07},
  {"t": 61.2, "type": "tone", "trackId": 3, "urgency": "caution", "pan": 0.07, "frequencyHz": 660, "durationSeconds": 0.08}
]}
```
`mount` in `hazards.json.settings` is passed through by the caller (`server.py`).

## 8. REST API  (`lab/server.py`, FastAPI)

| Method + path | Body / query | Returns |
|---|---|---|
| `GET /` | | `lab/static/index.html` (static files at `/static/*`) |
| `GET /api/recordings` | | `[Recording]` (§3) |
| `POST /api/recordings/{id}/proxy` | | `{"status": ...}`; starts a build if missing/error |
| `GET /media/{id}.mp4` | | the proxy file, with HTTP Range support (FileResponse); 404 if not ready |
| `GET /api/recordings/{id}/settings` | | Settings (§4), with defaults resolved: `{"mount", "hfovDeg", "corridor", "resolved": {"corridor": {...}, "hfovDeg": ...}}` |
| `PUT /api/recordings/{id}/settings` | Settings | same as GET |
| `GET /api/config/collision` | | collision.json contents |
| `GET /api/models` | | `{"models": [{"path", "name", "default": bool}], "profiles": ["default", "production", "half", "quarter"]}`; default = newest `*HackEye*` by name, currently `Yolo26m-sem-HackEye20261012-544.pt` |
| `POST /api/runs` | run request (§5) | `run.json`; queued, or done if cached |
| `GET /api/runs?recording=<id>` | | `[run.json]`, newest first |
| `GET /api/runs/{runId}` | | `run.json` (poll every 1 s while queued/running) |
| `POST /api/runs/{runId}/collision` | | re-runs §7 from `grids.npz` with the recording's **current** settings (no inference); returns `{"version", "hazards": "/api/runs/<id>/hazards.json", "events": ...}` |
| `GET /api/runs/{runId}/hazards.json` · `events.json` | | the files |
| `GET /api/runs/{runId}/frames/{i}/mask.png` | | the mask PNG (`Cache-Control: max-age=86400`) |

Errors return `{"detail": "..."}` with 4xx/5xx status codes (FastAPI default).

## 9. Frontend  (`lab/static/`, vanilla JS, no build step)

**Library:**
- Lists recordings with duration and proxy state, plus a Build-proxy button with progress.
- Selecting a recording loads its settings and its past runs.
- **Range:** a start/end in `mm:ss`, plus "use current player position" buttons.

**Run panel:**
- Model select, profile select, fps (default 6), mount select (presets from `/api/config/collision`), HFOV.
- **Analyse:** POST `/api/runs`, then poll and show a progress bar.
- **Re-run collision:** PUT the settings, then POST `/api/runs/{id}/collision`, then reload hazards/events.

**Player:**
- `<video>` from `/media/<id>.mp4` with a `<canvas>` overlay of the same displayed size.
- Driven by `requestVideoFrameCallback` (fall back to `timeupdate` plus rAF).
- **Each frame:** pick the analysed frame with the largest `t ≤ mediaTime`. Draw only if `mediaTime ∈ [run.start, run.end]`.
- **Layers, each toggleable:**
  - Mask PNG at a chosen opacity (default 0.45), drawn over the whole frame. Preload a window of ±20 frames.
  - The corridor trapezoid.
  - Hazard bboxes coloured by urgency (caution yellow, warning orange, imminent red) with label `"pole · 12 · 0.65"`.
- **Controls:** frame step (±1 analysed frame), speed 0.25–2×, and seeking.

**Timeline:**
- A strip under the video spanning the run range.
- Speech events are markers, coloured by urgency; clicking one seeks to it.
- Tone density is shown as a thin heat bar.

**Audio:**
- Starts muted until the user clicks "Enable audio" (browser autoplay rules).
- **Speech:** `speechSynthesis.speak(new SpeechSynthesisUtterance(text))` when the playhead crosses `event.t`; cancelled on seek or pause.
- **Tones:** WebAudio `OscillatorNode → GainNode (short envelope) → StereoPannerNode(pan) → master gain`, scheduled about 0.25 s ahead from `events.json` against `video.currentTime` and `playbackRate`. Rescheduled on seek, pause or rate change.
- Mute toggles for speech and tones, and a master volume.

**State in the URL hash** (`#rec=4927&run=<id>&t=63.2`), so a view can be reopened or shared on the tailnet.
