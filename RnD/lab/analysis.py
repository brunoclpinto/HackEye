"""Analysis runs for the Lab: segmentation over a time range, stored for
playback, plus the collision pass on top.

Design notes:
- One worker thread owns the GPU and runs jobs FIFO. The model is loaded on
  the first job and released after IDLE_SECONDS without work, so the
  always-on web service holds no VRAM between runs. Only one model is cached
  at a time: segmentation.CLASSES / SAFETY_LEVELS are process-global and get
  reassigned by each SegmentationModel constructor, so two live models with
  different taxonomies would mislabel each other's masks.
- Stored class grids have the letterbox padding cropped off and are resized
  to a fixed-width grid that maps 1:1 onto the original frame (CONTRACTS §1).
  All letterbox math ends here; collision logic and the frontend never see it.
- Frames are addressed by chapter-local frame index (not by timestamp seek
  per frame): seek once, then grab() forward, like src/pipeline.py, so
  skipped frames cost a decode but no colour conversion or inference.
- The collision pass is imported lazily so the Lab still runs inference
  while src/collision.py is absent or broken.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import profiles  # noqa: E402
from lab import recordings  # noqa: E402

LAB_DIR = recordings.LAB_DIR
GRID_W = 240
ANALYSIS_VERSION = 2  # 2: ego-motion track (motion.npz); v26.1.0 runs are implicitly 1
PROFILES = ["default", "production", "half", "quarter"]  # legacy names, still accepted
RESOLUTIONS = [f"{n}p" for n in profiles.SHORT_SIDE_OPTIONS]  # what the UI offers
IDLE_SECONDS = float(os.environ.get("HACKEYE_LAB_IDLE_SECONDS", "300"))
RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")
DEPTH_MODELS = ("none", "da3-small", "da3-base", "da2-metric-outdoor-small", "unidepth-v2-s")
DEPTH_W, DEPTH_H = 120, 68          # stored depth map size (CONTRACTS depth.npz)
DEPTH_MIN_REL = 1e-3             # floor for relative depth (non-finite / <= 0 become nan)
DEPTH_MIN_M, DEPTH_MAX_M = 0.1, 200.0   # clip range for metric depth (metres)
DEFAULT_MODEL = os.environ.get("HACKEYE_LAB_DEFAULT_MODEL", "Yolo26m-sem-HackEye20261011.pt")
MODEL_DIRS = [(Path(os.environ.get("HACKEYE_MODELS_DIR", "/models")), "*.pt"),
              (Path(os.environ.get("HACKEYE_RELEASES_DIR", "/hackeye-models")), "*HackEye*.pt")]


class RunError(ValueError):
    """Bad request (maps to HTTP 4xx)."""


class RunConflict(RunError):
    """Request conflicts with current state (maps to HTTP 409)."""


class _Cancelled(Exception):
    """Raised inside the worker when a run's cancel flag is seen."""


def _log(msg: str) -> None:
    print(f"[lab] {msg}", file=sys.stderr, flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

def list_models() -> list[dict]:
    paths: list[Path] = []
    for directory, pattern in MODEL_DIRS:
        if directory.is_dir():
            paths += sorted(directory.glob(pattern))
    releases = [p for p in paths if "HackEye" in p.name]
    # Newest by the YYYYMMDD in the release name (plain name order would rank
    # "...HackEyeV1" above "...HackEye20261012"); undated names rank last.
    def release_key(p: Path) -> tuple[str, str]:
        m = re.search(r"HackEye(\d{8})", p.name)
        return (m.group(1) if m else "", p.name)

    # Pinned default (by file name); without that file, the newest release.
    default = next((p for p in releases if p.name == DEFAULT_MODEL), None)
    if default is None and releases:
        default = max(releases, key=release_key)
    return [{"path": str(p), "name": p.name, "default": p == default} for p in paths]


# --------------------------------------------------------------------------
# Run storage
# --------------------------------------------------------------------------

def run_dir(run_id: str) -> Path:
    return LAB_DIR / "runs" / run_id


def _write_json(path: Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc))
    os.replace(tmp, path)


_state_lock = threading.Lock()
_active: dict[str, dict] = {}  # run_id -> live run.json (queued/running)


def get_run(run_id: str) -> dict | None:
    with _state_lock:
        if run_id in _active:
            return dict(_active[run_id])
    try:
        return json.loads((run_dir(run_id) / "run.json").read_text())
    except (OSError, ValueError):
        return None


def list_runs(recording: str | None) -> list[dict]:
    runs = []
    root = LAB_DIR / "runs"
    if root.is_dir():
        for d in root.iterdir():
            if RUN_ID_RE.match(d.name):
                doc = get_run(d.name)
                if doc and (recording is None or doc["request"]["recording"] == recording):
                    runs.append(doc)
    runs.sort(key=lambda r: r["createdAt"], reverse=True)
    return runs


def _update_run(run_id: str, persist: bool = True, **fields) -> dict:
    with _state_lock:
        doc = _active.get(run_id)
        if doc is None:
            doc = json.loads((run_dir(run_id) / "run.json").read_text())
        doc.update(fields)
        if run_id in _active:
            _active[run_id] = doc
        snapshot = dict(doc)
    if persist:
        _write_json(run_dir(run_id) / "run.json", snapshot)
    return snapshot


# --------------------------------------------------------------------------
# Request handling
# --------------------------------------------------------------------------

def _normalise_request(req: dict) -> dict:
    rec = recordings.get_recording(str(req.get("recording", "")))
    if rec is None:
        raise RunError(f"Unknown recording: {req.get('recording')!r}")
    try:
        start, end, fps = float(req["start"]), float(req["end"]), float(req.get("fps", 6.0))
    except (KeyError, TypeError, ValueError):
        raise RunError("start, end and fps must be numbers") from None
    # An end past the footage is clamped (the UI's default range may overshoot
    # a short clip); the clamped value is what gets stored and hashed.
    end = min(end, rec["duration"])
    if not (0 <= start < end):
        raise RunError(f"Range must satisfy 0 <= start < end <= {rec['duration']:.1f}")
    if not (0 < fps <= 60):
        raise RunError("fps must be in (0, 60]")
    profile = req.get("profile") or "default"
    if profile not in RESOLUTIONS + PROFILES:
        raise RunError(f"profile must be one of {RESOLUTIONS + PROFILES}")
    if profile in RESOLUTIONS:
        try:
            profiles.short_side_spec(rec["width"], rec["height"], int(profile[:-1]))
        except ValueError as e:
            raise RunError(str(e)) from None
    model = req.get("model")
    if model not in {m["path"] for m in list_models()}:
        raise RunError(f"Unknown model: {model!r}")
    depth = req.get("depth") or "none"
    if depth not in DEPTH_MODELS:
        raise RunError(f"depth must be one of {list(DEPTH_MODELS)}")
    request = {"recording": rec["id"], "start": start, "end": end,
               "model": model, "profile": profile, "fps": fps}
    if depth != "none":  # omitted for "none" so ids of depth-less requests stay stable
        request["depth"] = depth
    return request


def _run_id(request: dict) -> str:
    mtime = Path(request["model"]).stat().st_mtime
    canon = json.dumps({**request, "analysisVersion": ANALYSIS_VERSION}, sort_keys=True,
                       separators=(",", ":")) + f"|{mtime}"
    return hashlib.sha1(canon.encode()).hexdigest()[:12]


_jobs: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None
_cache: "_ModelCache | None" = None  # the worker's model cache (set when the worker starts)
_cancel_flags: dict[str, threading.Event] = {}  # run_id -> set when cancellation requested
_busy: str | None = None  # run id the worker is executing right now
_maintenance = False  # True while a version wipe is in progress: submissions are refused
ACTIVE_STATUSES = ("queued", "running")


def find_active_for_recording(active: dict[str, dict], rec_id: str) -> dict | None:
    """The queued/running run doc of `rec_id` among `active`, if any (CONTRACTS 11a)."""
    for doc in active.values():
        if doc["request"]["recording"] == rec_id and doc["status"] in ACTIVE_STATUSES:
            return doc
    return None


def _conflict_message(doc: dict) -> str:
    return (f"Analysis already running for {doc['request']['recording']} "
            f"(run {doc['id']}, {round((doc.get('progress') or 0) * 100)}%)")


def submit_run(req: dict) -> dict:
    """Queue a run, or return the existing one (done, or already in flight)."""
    request = _normalise_request(req)
    run_id = _run_id(request)
    existing = get_run(run_id)
    if existing and existing["status"] in ("done", "queued", "running"):
        # A run.json left as queued/running by a crashed service has no live
        # entry in _active; fall through and redo it.
        with _state_lock:
            live = run_id in _active
        if existing["status"] == "done" or live:
            return existing
    with _state_lock:
        if _maintenance:
            raise RunConflict("Lab is cleaning up for a new version; try again in a minute")
        busy = find_active_for_recording(_active, request["recording"])
        if busy is not None:
            raise RunConflict(_conflict_message(busy))

    doc = {
        "id": run_id, "request": request, "analysisVersion": ANALYSIS_VERSION, "status": "queued", "progress": 0.0, "error": None,
        "createdAt": _now(), "finishedAt": None,
        "frameCount": 0, "motionFrames": 0, "gridW": GRID_W, "gridH": 0, "srcW": 0, "srcH": 0,
        "inputSpec": None, "modelName": Path(request["model"]).name, "classNames": [],
        "msPerFrame": None, "collisionVersion": None,
        "depth": request.get("depth", "none"), "depthUnits": None, "depthMsPerFrame": None,
    }
    run_dir(run_id).mkdir(parents=True, exist_ok=True)
    with _state_lock:
        # Re-check under the same lock that registers the run, so two racing
        # POSTs for one recording can't both pass the guard above.
        busy = find_active_for_recording(_active, request["recording"])
        if busy is not None:
            raise RunConflict(_conflict_message(busy))
        _active[run_id] = doc
        _cancel_flags[run_id] = threading.Event()
    _write_json(run_dir(run_id) / "run.json", doc)
    _ensure_worker()
    _jobs.put(run_id)
    return dict(doc)


_PARTIAL_OUTPUTS = ("grids.npz", "motion.npz", "depth.npz", "hazards.json", "events.json")


def _remove_partial_outputs(run_id: str) -> None:
    import shutil

    out = run_dir(run_id)
    shutil.rmtree(out / "masks", ignore_errors=True)
    for name in _PARTIAL_OUTPUTS:
        try:
            (out / name).unlink()
        except FileNotFoundError:
            pass


def _finish_cancelled(run_id: str) -> None:
    _remove_partial_outputs(run_id)
    _finish(run_id, status="cancelled", error=None)
    with _state_lock:
        _cancel_flags.pop(run_id, None)
    _log(f"run {run_id}: cancelled")


def cancel_run(run_id: str) -> dict | None:
    """Cancel a queued/running run (CONTRACTS 11a).

    Returns the run doc (a queued run is already `cancelled`; a running one
    flips as soon as the worker sees the flag between frames). None if the
    run is unknown; raises RunConflict if it is not queued/running."""
    doc = get_run(run_id)
    if doc is None:
        return None
    with _state_lock:
        live = run_id in _active
        flag = _cancel_flags.get(run_id)
    if not live or doc["status"] not in ACTIVE_STATUSES:
        raise RunConflict(f"Run {run_id} is {doc['status']}; nothing to cancel")
    if flag is not None:
        flag.set()
    with _jobs.mutex:  # not started yet: pull it out of the queue
        try:
            _jobs.queue.remove(run_id)
            dequeued = True
        except ValueError:
            dequeued = False
    if dequeued:
        _jobs.task_done()
        _finish_cancelled(run_id)
    return get_run(run_id)


def cancel_all() -> list[str]:
    """Cancel every queued and running run; returns their ids."""
    with _state_lock:
        ids = [i for i, d in _active.items() if d["status"] in ACTIVE_STATUSES]
    for i in ids:
        try:
            cancel_run(i)
        except RunConflict:
            pass
    return ids


def is_idle() -> bool:
    with _state_lock:
        return _busy is None and not _active and _jobs.empty()


def wait_idle(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if is_idle():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def release_model() -> None:
    if _cache is not None:
        _cache.release()


def begin_maintenance() -> None:
    """Refuse new submissions and cancel everything in flight (version wipe)."""
    global _maintenance
    with _state_lock:
        _maintenance = True
    cancel_all()


def end_maintenance() -> None:
    global _maintenance
    with _state_lock:
        _maintenance = False


# --------------------------------------------------------------------------
# GPU worker
# --------------------------------------------------------------------------

class _ModelCache:
    def __init__(self) -> None:
        self.path: str | None = None
        self.model = None
        self.class_names: list[str] = []
        self.depth_model = None
        self.depth_variant: str | None = None
        self.last_used = 0.0

    def get(self, path: str):
        if self.path != path:
            self.release()
            (LAB_DIR / ".ultralytics").mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("YOLO_CONFIG_DIR", str(LAB_DIR / ".ultralytics"))
            import gpu_guard
            import segmentation
            from models import SegmentationModel

            t0 = time.perf_counter()
            self.model = SegmentationModel(path, gpu_guard.assert_torch_cuda())
            self.path = path
            self.class_names = [segmentation.CLASSES[i]["name"] for i in sorted(segmentation.CLASSES)]
            _log(f"model loaded: {Path(path).name} ({time.perf_counter() - t0:.1f}s)")
        self.last_used = time.monotonic()
        return self.model

    def get_depth(self, variant: str = "da3-small"):
        """The depth model of `variant`, loaded on first use (only runs that ask for depth pay for it)."""
        if self.depth_model is not None and self.depth_variant != variant:
            self.depth_model = None
            import gc

            gc.collect()
        if self.depth_model is None:
            import gpu_guard
            from depth import DepthModel

            t0 = time.perf_counter()
            self.depth_model = DepthModel(gpu_guard.assert_torch_cuda(), variant)
            self.depth_variant = variant
            _log(f"depth model {variant} loaded ({time.perf_counter() - t0:.1f}s)")
        self.last_used = time.monotonic()
        return self.depth_model

    def release(self) -> None:
        if self.model is None and self.depth_model is None:
            return
        import torch

        name = Path(self.path).name if self.path else None
        had_depth = self.depth_model is not None
        self.model, self.path, self.depth_model = None, None, None
        import gc

        gc.collect()
        torch.cuda.empty_cache()
        _log(f"model released: {name}{' + depth' if had_depth else ''}")


def _ensure_worker() -> None:
    global _worker, _cache
    with _state_lock:
        if _cache is None:
            _cache = _ModelCache()
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="gpu-worker", daemon=True)
            _worker.start()


def _worker_loop() -> None:
    global _busy
    cache = _cache
    while True:
        try:
            run_id = _jobs.get(timeout=1.0)
        except queue.Empty:
            if (cache.model is not None or cache.depth_model is not None) and time.monotonic() - cache.last_used > IDLE_SECONDS:
                cache.release()
            continue
        with _state_lock:
            _busy = run_id
        try:
            _run_job(run_id, cache)
        except _Cancelled:
            _finish_cancelled(run_id)
        except BaseException as exc:  # noqa: BLE001 - incl. SystemExit from gpu_guard
            _log(f"run {run_id} FAILED: {exc!r}")
            _finish(run_id, status="error", error=str(exc) or repr(exc))
            if isinstance(exc, MemoryError) or "CUDA" in str(exc):
                cache.release()
        finally:
            with _state_lock:
                _busy = None
                _cancel_flags.pop(run_id, None)


def _check_cancel(run_id: str) -> None:
    flag = _cancel_flags.get(run_id)
    if flag is not None and flag.is_set():
        raise _Cancelled()


def _finish(run_id: str, **fields) -> None:
    _update_run(run_id, finishedAt=_now(), **fields)
    with _state_lock:
        _active.pop(run_id, None)


MOTION_W, MOTION_H = 160, 90


class _FrameReader:
    """Sequential reader over a recording's chapters, addressed by recording
    time. Seeks once to the first sampled frame, then decodes forward.

    With `motion_end` set it also builds the ego-motion track (CONTRACTS §5):
    every source frame in [first sampled frame, motion_end) is retrieve()d,
    reduced to 160x90 gray and phase-correlated against its predecessor. The
    track continues across chapter boundaries (the rest of a chapter is
    drained before the next one is opened, and decoding of the next starts at
    its frame 0), so no long-gap seek is used in that mode."""

    MAX_GRAB_GAP = 240  # frames; beyond this a seek is cheaper than decoding through (no-motion mode only)

    def __init__(self, rec: dict, motion_end: float | None = None) -> None:
        self.rec = rec
        self.fps = rec["fps"]
        self.chapters = rec["chapters"]
        self.cap: cv2.VideoCapture | None = None
        self.ch = -1
        self.pos = 0
        self.last: tuple[int, int, np.ndarray] | None = None  # (chapter, frame, bgr)
        self.seek_seconds = 0.0
        self.motion_end = motion_end
        self.motion_seconds = 0.0  # time spent on gray/resize/phaseCorrelate
        self._m_t: list[float] = []
        self._m_dx: list[float] = []
        self._m_dy: list[float] = []
        self._m_prev: np.ndarray | None = None
        self._m_win = cv2.createHanningWindow((MOTION_W, MOTION_H), cv2.CV_32F)

    def _locate(self, t: float) -> tuple[int, int]:
        """Recording time -> (chapter index, chapter-local frame index)."""
        for i, ch in enumerate(self.chapters):
            f = round((t - ch["start"]) * self.fps)
            if t < ch["start"] + ch["duration"] and f < ch["frames"]:
                return i, max(0, f)
        return len(self.chapters), 0

    def _motion(self, bgr: np.ndarray, frame_t: float) -> None:
        if self.motion_end is None or frame_t >= self.motion_end:
            return
        t0 = time.perf_counter()
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (MOTION_W, MOTION_H), interpolation=cv2.INTER_AREA).astype(np.float32)
        dx = dy = 0.0
        if self._m_prev is not None:
            (sx, sy), _ = cv2.phaseCorrelate(self._m_prev, small, self._m_win)
            dx, dy = sx / MOTION_W, sy / MOTION_H
        self._m_prev = small
        self._m_t.append(frame_t)
        self._m_dx.append(dx)
        self._m_dy.append(dy)
        self.motion_seconds += time.perf_counter() - t0

    def _step_skipped(self) -> bool:
        """Decode the frame at self.pos without returning it (motion only)."""
        ch = self.chapters[self.ch]
        frame_t = ch["start"] + self.pos / self.fps
        if self.motion_end is None or frame_t >= self.motion_end:
            return self.cap.grab()
        if not self.cap.grab():
            return False
        ok, bgr = self.cap.retrieve()
        if not ok:
            return False
        self._motion(bgr, frame_t)
        return True

    def read(self, t: float) -> tuple[float, np.ndarray] | None:
        """Frame nearest to recording time t as (its exact time, BGR), or None at the end."""
        i, f = self._locate(t)
        if i >= len(self.chapters):
            return None
        ch = self.chapters[i]
        frame_t = ch["start"] + f / self.fps
        if self.last and self.last[:2] == (i, f):
            return frame_t, self.last[2]
        tracking = self.motion_end is not None
        if i != self.ch:
            if tracking and self.cap is not None:  # finish the old chapter's motion frames
                while self.pos < self.chapters[self.ch]["frames"] and self._step_skipped():
                    self.pos += 1
            self._seek(i, f, from_start=tracking and self.ch != -1)
        elif f < self.pos or (not tracking and f - self.pos > self.MAX_GRAB_GAP):
            self._seek(i, f)
        while self.pos < f:
            if not self._step_skipped():
                return None
            self.pos += 1
        ok, bgr = self.cap.read()
        if not ok:
            return None
        self.pos += 1
        self._motion(bgr, frame_t)
        self.last = (i, f, bgr)
        return frame_t, bgr

    def _seek(self, i: int, f: int, from_start: bool = False) -> None:
        t0 = time.perf_counter()
        if i != self.ch:
            if self.cap is not None:
                self.cap.release()
            self.cap = cv2.VideoCapture(self.chapters[i]["file"])
            if not self.cap.isOpened():
                raise RuntimeError(f"Cannot open {self.chapters[i]['file']}")
            self.ch, self.pos = i, 0
        if f != self.pos and not from_start:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            self.pos = f
        self.seek_seconds += time.perf_counter() - t0

    def finish_motion(self) -> None:
        """Process the remaining source frames up to motion_end (after the last sampled frame)."""
        if self.motion_end is None or self.cap is None:
            return
        while True:
            ch = self.chapters[self.ch]
            if self.pos >= ch["frames"]:
                if self.ch + 1 >= len(self.chapters):
                    return
                self._seek(self.ch + 1, 0)
                continue
            if ch["start"] + self.pos / self.fps >= self.motion_end or not self._step_skipped():
                return
            self.pos += 1

    def motion_track(self) -> dict[str, np.ndarray]:
        return {"t": np.array(self._m_t, np.float64), "dx": np.array(self._m_dx, np.float32),
                "dy": np.array(self._m_dy, np.float32)}

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()


def _run_job(run_id: str, cache: _ModelCache) -> None:
    import segmentation
    from letterbox import letterbox_with_meta
    from profiles import resolve_input_spec
    from segmentation import grid_from_semantic_mask

    doc = get_run(run_id)
    req = doc["request"]
    rec = recordings.get_recording(req["recording"])
    if rec is None:
        raise RuntimeError("Recording disappeared")
    _check_cancel(run_id)
    _update_run(run_id, status="running", progress=0.0)

    model = cache.get(req["model"])
    src_w, src_h = rec["width"], rec["height"]
    profile = None if req["profile"] == "default" else req["profile"]
    spec = resolve_input_spec(src_w, src_h, profile, None, None)
    grid_h = round(GRID_W * src_h / src_w)

    # class id -> RGBA; safety level 0 (ignored) stays fully transparent.
    lut = np.zeros((max(segmentation.CLASSES) + 1, 4), np.uint8)
    for cid, info in segmentation.CLASSES.items():
        level = info["safetyLevel"]
        if level:
            lut[cid] = (*segmentation.SAFETY_LEVELS[level]["color"], 255)

    start, end, fps = req["start"], req["end"], req["fps"]
    n_target = int(np.ceil((end - start) * fps - 1e-9))
    out = run_dir(run_id)
    masks_dir = out / "masks"
    if masks_dir.exists():
        for old in masks_dir.glob("*.png"):
            old.unlink()
    masks_dir.mkdir(parents=True, exist_ok=True)
    _update_run(run_id, gridW=GRID_W, gridH=grid_h, srcW=src_w, srcH=src_h,
                inputSpec={"w": spec.dst_w, "h": spec.dst_h, "description": spec.description},
                classNames=cache.class_names)

    depth_model = None
    if req.get("depth", "none") != "none":
        depth_model = cache.get_depth(req["depth"])
        _log(f"run {run_id}: depth {req['depth']}")
    depth_units = None
    depth_maps: list[np.ndarray] = []
    depth_seconds = 0.0

    reader = _FrameReader(rec, motion_end=end)
    grids: list[np.ndarray] = []
    times: list[float] = []
    t_start = time.perf_counter()
    try:
        for k in range(n_target):
            _check_cancel(run_id)
            got = reader.read(start + k / fps)
            if got is None:
                break
            frame_t, bgr = got
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            if depth_model is not None:
                td = time.perf_counter()
                raw, depth_units = depth_model.predict(rgb)
                small_d = cv2.resize(raw, (DEPTH_W, DEPTH_H), interpolation=cv2.INTER_AREA)
                small_d[~np.isfinite(small_d) | (small_d <= 0)] = np.nan
                if depth_units == "metric":
                    depth_maps.append(np.clip(small_d, DEPTH_MIN_M, DEPTH_MAX_M).astype(np.float16))
                else:
                    depth_maps.append(np.maximum(small_d, DEPTH_MIN_REL).astype(np.float16))
                depth_seconds += time.perf_counter() - td
            letterboxed, meta = letterbox_with_meta(rgb, spec.dst_w, spec.dst_h)
            class_ids = model.predict_class_grid(letterboxed, spec.dst_w, spec.dst_h)
            grid = grid_from_semantic_mask(class_ids, meta).class_ids

            # Crop the letterbox padding, then map 1:1 onto the frame.
            y0 = round(meta.pad_y)
            y1 = round(meta.pad_y + meta.src_h * meta.scale)
            x0 = round(meta.pad_x)
            x1 = round(meta.pad_x + meta.src_w * meta.scale)
            crop = grid[y0:y1, x0:x1].astype(np.uint8)
            small = cv2.resize(crop, (GRID_W, grid_h), interpolation=cv2.INTER_NEAREST)

            i = len(grids)
            rgba = lut[small]
            cv2.imwrite(str(masks_dir / f"{i}.png"), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
            grids.append(small)
            times.append(frame_t)
            if i == 0:
                _log(f"run {run_id}: first frame ready, seek {reader.seek_seconds:.2f}s")
            _update_run(run_id, persist=False, progress=(k + 1) / n_target)
        _check_cancel(run_id)
        reader.finish_motion()
    finally:
        reader.close()

    if not grids:
        raise RuntimeError("No frames could be read from the requested range")
    elapsed = time.perf_counter() - t_start
    np.savez_compressed(out / "grids.npz", grids=np.stack(grids), t=np.array(times, np.float64),
                        index=np.arange(len(grids), dtype=np.int32))
    if depth_model is not None:
        np.savez_compressed(out / "depth.npz", depth=np.stack(depth_maps), t=np.array(times, np.float64),
                            units=np.array(depth_units))
        _update_run(run_id, depth=req["depth"], depthUnits=depth_units,
                    depthMsPerFrame=round(depth_seconds * 1000 / len(depth_maps), 1))
    motion = reader.motion_track()
    np.savez_compressed(out / "motion.npz", **motion)
    n_motion = len(motion["t"])
    _log(f"run {run_id}: motion {n_motion} source frames, {reader.motion_seconds * 1000 / max(n_motion, 1):.2f} ms/frame")
    _update_run(run_id, analysisVersion=ANALYSIS_VERSION, motionFrames=n_motion,
                frameCount=len(grids), msPerFrame=round(elapsed * 1000 / len(grids), 1),
                seekSeconds=round(reader.seek_seconds, 3), progress=1.0)
    _log(f"run {run_id}: {len(grids)} frames in {elapsed:.1f}s")

    _check_cancel(run_id)
    try:
        collision_pass(run_id)
    except Exception as exc:  # noqa: BLE001 - inference results are still usable
        _log(f"run {run_id}: collision pass failed: {exc!r}")
    _finish(run_id, status="done", progress=1.0)


# --------------------------------------------------------------------------
# Collision pass
# --------------------------------------------------------------------------

def collision_pass(run_id: str) -> dict | None:
    """(Re)compute hazards.json / events.json from grids.npz using the
    recording's current settings. Returns {"version": ...}, or None when
    src/collision.py is missing (the run stays valid without hazards)."""
    try:
        import collision
    except ImportError as exc:
        _log(f"collision module unavailable ({exc}); skipping collision pass")
        return None

    doc = get_run(run_id)
    config = collision.load_config()
    stored = recordings.get_settings(doc["request"]["recording"], config["defaultMount"])
    settings = collision.resolve_settings(config, stored["mount"], stored["hfovDeg"],
                                          stored["cameraHeightM"], stored["stepLengthM"],
                                          projection=stored["projection"],
                                          distance_source=stored["distanceSource"])
    out = run_dir(run_id)
    with np.load(out / "grids.npz") as z:
        grids, times = z["grids"], z["t"]
    motion = None  # v26.1.0 runs have no motion track
    if (out / "motion.npz").exists():
        with np.load(out / "motion.npz") as z:
            motion = {"t": z["t"], "dx": z["dx"], "dy": z["dy"]}
    depth = None  # runs without a depth model have no depth.npz
    if (out / "depth.npz").exists():
        with np.load(out / "depth.npz") as z:
            units = str(z["units"]) if "units" in z.files else "metric"   # pre-v26.2.x runs are metric
            depth = {"t": z["t"], "depth": z["depth"], "units": units}
    t0 = time.perf_counter()
    hazards, events = collision.run_collision(grids, times, doc["classNames"], config, settings, motion,
                                              depth=depth)
    elapsed = round(time.perf_counter() - t0, 3)
    hazards.setdefault("settings", {})["mount"] = stored["mount"]
    _write_json(out / "hazards.json", hazards)
    _write_json(out / "events.json", events)
    _update_run(run_id, collisionVersion=config["version"])
    _log(f"run {run_id}: collision pass {elapsed:.2f}s")
    return {"version": config["version"], "elapsedSeconds": elapsed}
