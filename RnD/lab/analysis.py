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

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import egoflow  # noqa: E402
import profiles  # noqa: E402
from lab import recordings  # noqa: E402
from lab._forward import install  # noqa: E402
from lab.store import constants, errors, runs, util  # noqa: E402
from lab.store import requests as store_requests  # noqa: E402

# v26.3.0 p5-02: the names below moved to lab.store (audit 7.4) and stay reachable here as forwards to their home module
# (reads, writes and deletes); code in this module reads them as attributes of the home (`runs._active`), never as a local copy.
install(__name__, {
    **dict.fromkeys(
        ("GRID_W", "NO_DATA", "ANALYSIS_VERSION", "PROFILES", "RESOLUTIONS", "IDLE_SECONDS", "RUN_ID_RE", "DEPTH_MODELS",
         "DEPTH_ANCHOR", "SUPERSEDED_ANCHORS", "DEPTH_W", "DEPTH_H", "DEPTH_MIN_REL", "DEPTH_MIN_M", "DEPTH_MAX_M",
         "DEFAULT_MODEL", "MODEL_DIRS"), "lab.store.constants"),
    **dict.fromkeys(("RunError", "RunConflict", "_Cancelled"), "lab.store.errors"),
    **dict.fromkeys(("_now", "_log", "_write_json"), "lab.store.util"),
    **dict.fromkeys(
        ("LAB_DIR", "run_dir", "_state_lock", "_active", "get_run", "list_runs", "_update_run", "ACTIVE_STATUSES",
         "find_active_for_recording", "_conflict_message", "_remove_partial_outputs", "_PARTIAL_OUTPUTS"), "lab.store.runs"),
    **dict.fromkeys(
        ("_normalise_request", "request_side", "run_window", "DEVICES", "_parse_device", "_cpu_threads", "_run_id"),
        "lab.store.requests"),
    "list_models": "lab.store.models",
})



_jobs: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None
_cache: "_ModelCache | None" = None  # the worker's model cache (set when the worker starts)
_cancel_flags: dict[str, threading.Event] = {}  # run_id -> set when cancellation requested
_busy: str | None = None  # run id the worker is executing right now
_maintenance = False  # True while a version wipe is in progress: submissions are refused


def submit_run(req: dict) -> dict:
    """Queue a run, or return the existing one (done, or already in flight).

    A reused finished run comes back with the response-only marker `"reused": true`
    (never stored in run.json). `"force": true` re-runs a finished/cancelled/failed
    run from scratch under the same id (old outputs removed, reviews untouched); an
    in-flight run is returned as is."""
    device = store_requests._parse_device(req)
    request = store_requests._normalise_request(req)
    rec = recordings.get_recording(request["recording"])
    force = req.get("force") is True
    run_id = store_requests._run_id(request)
    existing = runs.get_run(run_id)
    if existing and existing["status"] in ("done", "queued", "running"):
        # A run.json left as queued/running by a crashed service has no live
        # entry in _active; fall through and redo it.
        with runs._state_lock:
            live = run_id in runs._active
        if live:
            return existing
        if existing["status"] == "done" and not force:
            return {**existing, "reused": True}
    from lab import collisions
    if collisions.job_active():
        raise errors.RunConflict("A collision re-run is running; wait for it or cancel it")
    with runs._state_lock:
        if _maintenance:
            raise errors.RunConflict("Lab is cleaning up for a new version; try again in a minute")
        busy = runs.find_active_for_recording(runs._active, request["recording"])
        if busy is not None:
            raise errors.RunConflict(runs._conflict_message(busy))

    doc = {
        "id": run_id, "request": request, "orientation": request.get("orientation", "landscape"),
        "side": request.get("side") or req.get("side") or "center",
        "window": store_requests.run_window(rec, request) if rec else None,
        "device": device, "analysisVersion": constants.ANALYSIS_VERSION, "status": "queued", "progress": 0.0, "error": None,
        "createdAt": util._now(), "finishedAt": None,
        "frameCount": 0, "motionFrames": 0, "gridW": constants.GRID_W, "gridH": 0, "srcW": 0, "srcH": 0,
        "inputSpec": None, "modelName": Path(request["model"]).name, "classNames": [],
        "msPerFrame": None, "collisionVersion": None,
        "depth": request.get("depth", "none"), "depthUnits": None, "depthMsPerFrame": None,
    }
    runs.run_dir(run_id).mkdir(parents=True, exist_ok=True)
    with runs._state_lock:
        # Re-check under the same lock that registers the run, so two racing
        # POSTs for one recording can't both pass the guard above.
        busy = runs.find_active_for_recording(runs._active, request["recording"])
        if busy is not None:
            raise errors.RunConflict(runs._conflict_message(busy))
        if existing:  # a forced / retried run starts clean (reviews live outside the run dir)
            runs._remove_partial_outputs(run_id)
        runs._active[run_id] = doc
        _cancel_flags[run_id] = threading.Event()
    util._write_json(runs.run_dir(run_id) / "run.json", doc)
    _ensure_worker()
    _jobs.put(run_id)
    return dict(doc)


def _finish_cancelled(run_id: str) -> None:
    runs._remove_partial_outputs(run_id)
    _finish(run_id, status="cancelled", error=None)
    with runs._state_lock:
        _cancel_flags.pop(run_id, None)
    util._log(f"run {run_id}: cancelled")


def cancel_run(run_id: str) -> dict | None:
    """Cancel a queued/running run (CONTRACTS 11a).

    Returns the run doc (a queued run is already `cancelled`; a running one
    flips as soon as the worker sees the flag between frames). None if the
    run is unknown; raises RunConflict if it is not queued/running."""
    doc = runs.get_run(run_id)
    if doc is None:
        return None
    with runs._state_lock:
        live = run_id in runs._active
        flag = _cancel_flags.get(run_id)
    if not live or doc["status"] not in runs.ACTIVE_STATUSES:
        raise errors.RunConflict(f"Run {run_id} is {doc['status']}; nothing to cancel")
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
    return runs.get_run(run_id)


def cancel_all() -> list[str]:
    """Cancel every queued and running run; returns their ids. (v26.2.10: and the collision re-run job.)"""
    from lab import collisions
    collisions.cancel_job()
    with runs._state_lock:
        ids = [i for i, d in runs._active.items() if d["status"] in runs.ACTIVE_STATUSES]
    for i in ids:
        try:
            cancel_run(i)
        except errors.RunConflict:
            pass
    return ids


def is_idle() -> bool:
    from lab import collisions
    with runs._state_lock:
        return _busy is None and not runs._active and _jobs.empty() and not collisions.job_active()


def analysis_active() -> bool:
    """A run is queued or running (v26.2.10: a collision re-run job never runs together with one)."""
    with runs._state_lock:
        return any(d["status"] in runs.ACTIVE_STATUSES for d in runs._active.values())


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
    with runs._state_lock:
        _maintenance = True
    cancel_all()


def end_maintenance() -> None:
    global _maintenance
    with runs._state_lock:
        _maintenance = False


# --------------------------------------------------------------------------
# GPU worker
# --------------------------------------------------------------------------

class _ModelCache:
    def __init__(self) -> None:
        self.path: str | None = None
        self.device: str | None = None  # "gpu" | "cpu" the segmentation model was built for
        self.model = None
        self.class_names: list[str] = []
        self.depth_model = None
        self.depth_variant: str | None = None
        self.depth_device: str | None = None
        self.last_used = 0.0

    @staticmethod
    def _torch_device(device: str):
        """GPU asserts CUDA (no fallback, exits like before); CPU is only used when the run asks for it."""
        if device == "cpu":
            import torch

            torch.set_num_threads(store_requests._cpu_threads())
            return torch.device("cpu")
        import gpu_guard

        return gpu_guard.assert_torch_cuda()

    def get(self, path: str, device: str = "gpu"):
        if self.path != path or self.device != device:
            self.release()
            (runs.LAB_DIR / ".ultralytics").mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("YOLO_CONFIG_DIR", str(runs.LAB_DIR / ".ultralytics"))
            import segmentation
            from models import SegmentationModel

            t0 = time.perf_counter()
            self.model = SegmentationModel(path, self._torch_device(device))
            self.path, self.device = path, device
            self.class_names = [segmentation.CLASSES[i]["name"] for i in sorted(segmentation.CLASSES)]
            util._log(f"model loaded: {Path(path).name} on {device} ({time.perf_counter() - t0:.1f}s)")
        self.last_used = time.monotonic()
        return self.model

    def get_depth(self, variant: str = "da3-small", device: str = "gpu"):
        """The depth model of `variant` on `device`, loaded on first use (only runs that ask for depth pay for it)."""
        if self.depth_model is not None and (self.depth_variant, self.depth_device) != (variant, device):
            self.depth_model = None
            import gc

            gc.collect()
        if self.depth_model is None:
            from depth import DepthModel

            t0 = time.perf_counter()
            self.depth_model = DepthModel(self._torch_device(device), variant)
            self.depth_variant, self.depth_device = variant, device
            util._log(f"depth model {variant} loaded ({time.perf_counter() - t0:.1f}s)")
        self.last_used = time.monotonic()
        return self.depth_model

    def release(self) -> None:
        if self.model is None and self.depth_model is None:
            return
        import torch

        name = Path(self.path).name if self.path else None
        had_depth = self.depth_model is not None
        self.model, self.path, self.device, self.depth_model = None, None, None, None
        import gc

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        util._log(f"model released: {name}{' + depth' if had_depth else ''}")


def _ensure_worker() -> None:
    global _worker, _cache
    with runs._state_lock:
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
            if (cache.model is not None or cache.depth_model is not None) and time.monotonic() - cache.last_used > constants.IDLE_SECONDS:
                cache.release()
            continue
        with runs._state_lock:
            _busy = run_id
        try:
            _run_job(run_id, cache)
        except errors._Cancelled:
            _finish_cancelled(run_id)
        except BaseException as exc:  # noqa: BLE001 - incl. SystemExit from gpu_guard
            util._log(f"run {run_id} FAILED: {exc!r}")
            _finish(run_id, status="error", error=str(exc) or repr(exc))
            if isinstance(exc, MemoryError) or "CUDA" in str(exc):
                cache.release()
        finally:
            with runs._state_lock:
                _busy = None
                _cancel_flags.pop(run_id, None)


def _check_cancel(run_id: str) -> None:
    flag = _cancel_flags.get(run_id)
    if flag is not None and flag.is_set():
        raise errors._Cancelled()


def _finish(run_id: str, **fields) -> None:
    runs._update_run(run_id, finishedAt=util._now(), **fields)
    with runs._state_lock:
        runs._active.pop(run_id, None)


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
        self._m_resid: list[float] = []
        self._m_flow = egoflow.ResidualFlowTrack()
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
        small_u8 = cv2.resize(gray, (MOTION_W, MOTION_H), interpolation=cv2.INTER_AREA)
        small = small_u8.astype(np.float32)
        dx = dy = 0.0
        if self._m_prev is not None:
            (sx, sy), _ = cv2.phaseCorrelate(self._m_prev, small, self._m_win)
            dx, dy = sx / MOTION_W, sy / MOTION_H
        self._m_prev = small
        self._m_t.append(frame_t)
        self._m_dx.append(dx)
        self._m_dy.append(dy)
        self._m_resid.append(self._m_flow.push(small_u8))
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
                "dy": np.array(self._m_dy, np.float32), "resid": np.array(self._m_resid, np.float32)}

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()


def _run_job(run_id: str, cache: _ModelCache) -> None:
    import segmentation
    from letterbox import letterbox_with_meta
    from profiles import resolve_input_spec
    from segmentation import grid_from_semantic_mask

    doc = runs.get_run(run_id)
    req = doc["request"]
    device = doc.get("device") or "gpu"  # older run docs predate the field
    rec = recordings.get_recording(req["recording"])
    if rec is None:
        raise RuntimeError("Recording disappeared")
    _check_cancel(run_id)
    runs._update_run(run_id, status="running", progress=0.0)

    model = cache.get(req["model"], device)
    src_w, src_h = rec["width"], rec["height"]
    profile = None if req["profile"] == "default" else req["profile"]
    # The analysed window of the frame (CONTRACTS section 1a): the full frame, or a portrait window of it. The stored grids,
    # masks and depth maps always span the whole source frame at the same cell size; cells outside the window hold NO_DATA.
    win = store_requests.run_window(rec, req)
    windowed = not profiles.is_full_window(win, src_w, src_h)
    spec = resolve_input_spec(win["w"], win["h"], profile, None, None)
    grid_h = round(constants.GRID_W * src_h / src_w)
    g0, gcols = profiles.grid_columns(win, src_w, constants.GRID_W) if windowed else (0, constants.GRID_W)
    d0, d1 = round(g0 * constants.DEPTH_W / constants.GRID_W), round((g0 + gcols) * constants.DEPTH_W / constants.GRID_W)

    # class id -> RGBA; safety level 0 (ignored) stays fully transparent. Row 255 (no data) too.
    lut = np.zeros((max(max(segmentation.CLASSES) + 1, 256 if windowed else 0), 4), np.uint8)
    for cid, info in segmentation.CLASSES.items():
        level = info["safetyLevel"]
        if level:
            lut[cid] = (*segmentation.SAFETY_LEVELS[level]["color"], 255)

    start, end, fps = req["start"], req["end"], req["fps"]
    n_target = int(np.ceil((end - start) * fps - 1e-9))
    out = runs.run_dir(run_id)
    masks_dir = out / "masks"
    if masks_dir.exists():
        for old in masks_dir.glob("*.png"):
            old.unlink()
    masks_dir.mkdir(parents=True, exist_ok=True)
    runs._update_run(run_id, gridW=constants.GRID_W, gridH=grid_h, srcW=src_w, srcH=src_h,
                inputSpec={"w": spec.dst_w, "h": spec.dst_h, "description": spec.description},
                classNames=cache.class_names, window=win,
                gridWindow={"c0": g0, "cols": gcols} if windowed else None)

    depth_model = None
    if req.get("depth", "none") != "none":
        depth_model = cache.get_depth(req["depth"], device)
        util._log(f"run {run_id}: depth {req['depth']}")
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
            if windowed:
                bgr = np.ascontiguousarray(bgr[win["y0"]:win["y0"] + win["h"], win["x0"]:win["x0"] + win["w"]])
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            if depth_model is not None:
                td = time.perf_counter()
                raw, depth_units = depth_model.predict(rgb)
                small_d = cv2.resize(raw, (d1 - d0, constants.DEPTH_H) if windowed else (constants.DEPTH_W, constants.DEPTH_H), interpolation=cv2.INTER_AREA)
                small_d[~np.isfinite(small_d) | (small_d <= 0)] = np.nan
                if windowed:     # full-frame depth map: NaN outside the window
                    full_d = np.full((constants.DEPTH_H, constants.DEPTH_W), np.nan, small_d.dtype)
                    full_d[:, d0:d1] = small_d
                    small_d = full_d
                if depth_units == "metric":
                    depth_maps.append(np.clip(small_d, constants.DEPTH_MIN_M, constants.DEPTH_MAX_M).astype(np.float16))
                else:
                    depth_maps.append(np.maximum(small_d, constants.DEPTH_MIN_REL).astype(np.float16))
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
            if windowed:
                small = np.full((grid_h, constants.GRID_W), constants.NO_DATA, np.uint8)
                small[:, g0:g0 + gcols] = cv2.resize(crop, (gcols, grid_h), interpolation=cv2.INTER_NEAREST)
            else:
                small = cv2.resize(crop, (constants.GRID_W, grid_h), interpolation=cv2.INTER_NEAREST)

            i = len(grids)
            rgba = lut[small]
            cv2.imwrite(str(masks_dir / f"{i}.png"), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
            grids.append(small)
            times.append(frame_t)
            if i == 0:
                util._log(f"run {run_id}: first frame ready, seek {reader.seek_seconds:.2f}s")
            runs._update_run(run_id, persist=False, progress=(k + 1) / n_target)
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
                            units=np.array(depth_units), anchor=np.array(constants.DEPTH_ANCHOR.get(req["depth"], "")))
        runs._update_run(run_id, depth=req["depth"], depthUnits=depth_units,
                    depthMsPerFrame=round(depth_seconds * 1000 / len(depth_maps), 1))
    motion = reader.motion_track()
    np.savez_compressed(out / "motion.npz", **motion)
    n_motion = len(motion["t"])
    util._log(f"run {run_id}: motion {n_motion} source frames, {reader.motion_seconds * 1000 / max(n_motion, 1):.2f} ms/frame")
    runs._update_run(run_id, analysisVersion=constants.ANALYSIS_VERSION, motionFrames=n_motion,
                frameCount=len(grids), msPerFrame=round(elapsed * 1000 / len(grids), 1),
                seekSeconds=round(reader.seek_seconds, 3), progress=1.0)
    util._log(f"run {run_id}: {len(grids)} frames in {elapsed:.1f}s")

    _check_cancel(run_id)
    cdoc = None
    try:
        cdoc = collision_pass(run_id)
    except Exception as exc:  # noqa: BLE001 - inference results are still usable
        util._log(f"run {run_id}: collision pass failed: {exc!r}")
    if cdoc is not None:
        _build_worldmap(run_id, cdoc["id"])
    _finish(run_id, status="done", progress=1.0)


def _build_worldmap(run_id: str, cid: str) -> None:
    """v26.2.6: the world map is built with the run, after the collision pass. A failure is logged; the run is still done."""
    try:
        worldmap_pass(run_id, cid)
    except Exception as exc:  # noqa: BLE001 - the run is usable without a map
        util._log(f"run {run_id}: worldmap pass failed: {exc!r}")


# --------------------------------------------------------------------------
# Collision pass
# --------------------------------------------------------------------------

def collision_pass(run_id: str, overrides: dict | None = None, label: str = "", job=None) -> dict | None:
    """Compute a NEW collision run (v26.2.8: next id c<n>, never reused) from grids.npz using the recording's current settings, plus
    optional config `overrides` ({"collision": {dotted key: value}, "worldmap": {...}}, validated, applied to in-memory copies).
    Writes runs/<id>/collisions/<cid>/{hazards.json, events.json, collision.json}; the world map is built by `worldmap_pass`.
    Returns the collision.json document, or None when src/collision.py is missing (the run stays valid without hazards).
    Raises lab.collisions.CollisionError (422) for bad overrides.
    v26.2.10: `job` (a lab.collisions.Job) = the id is already allocated and registered, its collision.json is in status `running`; the
    frame loop reports to `job.progress` (0-0.4) and stops when the job is cancelled; the job finishes the document after the map."""
    try:
        import collision
        import worldmap
    except ImportError as exc:
        util._log(f"collision module unavailable ({exc}); skipping collision pass")
        return None
    from lab import collisions

    doc = runs.get_run(run_id)
    overrides = collisions.validate_overrides(overrides)
    base_config = collision.load_config()
    base_wcfg = worldmap.load_config()
    collisions.check_overrides(overrides, base_config, base_wcfg)
    config = collisions.apply_overrides(base_config, overrides, "collision")
    wcfg = collisions.apply_overrides(base_wcfg, overrides, "worldmap")
    stored = recordings.get_settings(doc["request"]["recording"], config["defaultMount"])
    # A windowed (portrait) run was cut for the side it was requested with: its collision pass uses that side.
    side = doc["request"].get("side") or stored["cameraSide"]
    settings = collision.resolve_settings(config, stored["mount"], stored["hfovDeg"],
                                          stored["cameraHeightM"], stored["stepLengthM"],
                                          projection=stored["projection"],
                                          distance_source=stored["distanceSource"],
                                          user_height_m=stored["userHeightM"],
                                          camera_location=stored["cameraLocation"],
                                          camera_side=side, object_distance=stored["objectDistance"],
                                          use_horizon=stored["useHorizon"])
    window = None
    gwin = doc.get("gridWindow")
    if gwin:
        window = {**gwin, **doc["window"], "srcW": doc["srcW"], "srcH": doc["srcH"]}
    out = runs.run_dir(run_id)
    with np.load(out / "grids.npz") as z:
        grids, times = z["grids"], z["t"]
    motion = None  # v26.1.0 runs have no motion track
    if (out / "motion.npz").exists():
        with np.load(out / "motion.npz") as z:
            motion = {"t": z["t"], "dx": z["dx"], "dy": z["dy"]}
            if "resid" in z.files:        # analysisVersion 3: residual flow, the stationary-user signal (v26.1.11)
                motion["resid"] = z["resid"]
    depth = None  # runs without a depth model have no depth.npz
    if (out / "depth.npz").exists():
        with np.load(out / "depth.npz") as z:
            units = str(z["units"]) if "units" in z.files else "metric"   # pre-v26.2.x runs are metric
            anchor = str(z["anchor"]) if "anchor" in z.files else ""
            variant = doc["request"].get("depth") or doc.get("depth") or ""
            if anchor in constants.SUPERSEDED_ANCHORS.get(variant, ()):
                anchor = ""
            if anchor not in ("per-frame", "initial", "plane", "none"):  # npz field > variant table > default rule
                anchor = constants.DEPTH_ANCHOR.get(variant)
            if anchor is None:
                anchor = "per-frame" if units == "relative" else "none"
            depth = {"t": z["t"], "depth": z["depth"], "units": units, "anchor": anchor}
    cid = job.cid if job is not None else collisions.allocate(run_id)
    cdir = collisions.collision_dir(run_id, cid)
    try:
        t0 = time.perf_counter()
        extra = {"window": window} if window is not None else {}     # full-frame runs call exactly as before
        sens = recordings.sensors_for(doc["request"]["recording"])      # v26.2.11: GoPro telemetry (None: no gpmd stream = v26.2.10 behaviour)
        if sens is not None:
            extra["sensors"] = sens
        if job is not None:               # only a job reports (a synchronous pass calls exactly as before)
            extra["progress"] = lambda i, n: job.report(0.4 * i / max(n, 1))
        from lab import sounds as lab_sounds                       # the Lab-wide sound profile (v26.1.16): the tone intervals
        hazards, events = collision.run_collision(grids, times, doc["classNames"], config, settings, motion,
                                                  depth=depth, sounds=lab_sounds.profile(), worldmap_config=wcfg, **extra)
        elapsed = round(time.perf_counter() - t0, 3)
        hazards.setdefault("settings", {})["mount"] = stored["mount"]
        cdir.mkdir(parents=True, exist_ok=True)
        util._write_json(cdir / "hazards.json", hazards)
        util._write_json(cdir / "events.json", events)
        evs = events.get("events", [])
        cdoc = {"id": cid, "runId": run_id, "createdAt": util._now(), "collisionVersion": config["version"],
                "worldmapVersion": None, "settings": stored,
                "resolved": {**hazards.get("settings", {}), "distanceSource": hazards.get("distanceSource"),
                             "projection": hazards.get("projection")},
                "overrides": overrides, "label": "", "elapsedSeconds": elapsed, "status": "done", "progress": 1.0, "error": None,
                "counts": {"speech": sum(1 for e in evs if e.get("type") == "speech"),
                           "beeps": sum(1 for e in evs if e.get("type") == "beeps")}}
        if label:
            cdoc["label"] = str(label)[:60]
        if job is not None:               # still running: the map follows; keep the label the row may have got meanwhile
            cdoc.update(status="running", progress=0.4, label=(collisions.read_doc(run_id, cid) or {}).get("label", ""))
        collisions.write_doc(run_id, cid, cdoc)
    except BaseException:
        if job is None:
            import shutil
            shutil.rmtree(cdir, ignore_errors=True)
        raise
    if job is None:
        collisions.register(run_id, cid)
    fields = {"collisionVersion": config["version"]}
    if window is None and doc.get("side") is not None:
        fields["side"] = side          # a full-frame run shows the side its lane offset was last computed for
    runs._update_run(run_id, **fields)
    util._log(f"run {run_id}: collision pass {cid} {elapsed:.2f}s")
    return cdoc


def worldmap_pass(run_id: str, cid: str | None = None, job=None) -> dict:
    """(Re)build worldmap.npz of collision run `cid` (default: the latest) from grids.npz, that collision run's hazards.json (the horizon,
    ego block and calibration the pass stored) and depth.npz, with the config overrides stored in its collision.json. Pure numpy; never
    touches the GPU queue or hazards.json / events.json. Raises FileNotFoundError when grids.npz or hazards.json is missing."""
    import collision
    import worldmap
    from lab import collisions

    out = runs.run_dir(run_id)
    doc = runs.get_run(run_id)
    cid = collisions.resolve(doc, cid)
    cdir = collisions.collision_dir(run_id, cid)
    for name, base in (("grids.npz", out), ("hazards.json", cdir)):
        if not (base / name).exists():
            raise FileNotFoundError(name)
    cdoc = collisions.read_doc(run_id, cid) or {}
    overrides = collisions.validate_overrides(cdoc.get("overrides"))
    with np.load(out / "grids.npz") as z:
        grids, times = z["grids"], z["t"]
    hazards = json.loads((cdir / "hazards.json").read_text())
    depth = None
    if (out / "depth.npz").exists():
        with np.load(out / "depth.npz") as z:
            depth = {"t": z["t"], "depth": z["depth"]}
    cfg = collisions.apply_overrides(worldmap.load_config(), overrides, "worldmap")
    ccfg = collisions.apply_overrides(collision.load_config(), overrides, "collision")
    t0 = time.perf_counter()
    hook = None
    if job is not None:                   # v26.2.10: 0.4-1.0 of the job's progress; raises when cancelled
        total = len(grids)
        hook = lambda i, wm, obs, cls: job.report(0.4 + 0.6 * (i + 1) / max(total, 1))  # noqa: E731
    arrays = worldmap.build(grids, times, doc["classNames"], hazards, ccfg, cfg, depth, hook=hook)
    elapsed = round(time.perf_counter() - t0, 3)
    tmp = cdir / "worldmap.tmp.npz"
    np.savez_compressed(tmp, **arrays)
    os.replace(tmp, cdir / "worldmap.npz")
    if cdoc:
        cdoc["worldmapVersion"] = cfg["version"]
        collisions.write_doc(run_id, cid, cdoc)
    util._log(f"run {run_id}: worldmap pass {cid} {elapsed:.2f}s")
    ms = arrays["ms"]
    return {"version": cfg["version"], "elapsedSeconds": elapsed, "frames": int(len(ms)),
            "msMean": round(float(ms.mean()), 2), "msP95": round(float(np.percentile(ms, 95)), 2)}
