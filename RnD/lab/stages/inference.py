"""The inference job (v26.3.0 p5-04): segmentation (and depth) over the window, then the collision pass and map.

`_run_job(run_id, cache, ctx)` takes the `JobContext` the worker built (`ctx.check_cancel()`, `ctx.finish(**fields)`).
The two passes are read as attributes of `lab.stages.collision` at call time, so a test patch is seen. The flat model
modules and `profiles` are imported lazily inside the job.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from lab import recordings
from lab.stages import collision as stage_collision
from lab.stages.frames import _FrameReader
from lab.store import constants, runs, util
from lab.store import requests as store_requests
from lab.store.jobctx import JobContext

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from lab.stages.models import _ModelCache


def _default_context(run_id: str) -> JobContext:
    """The context of a caller that has none: the worker's cancel flag and finish, read from the `analysis` facade."""
    from lab import analysis

    def is_cancelled() -> bool:
        flag = analysis._cancel_flags.get(run_id)
        return flag is not None and flag.is_set()

    return JobContext(run_id, is_cancelled=is_cancelled, finish=analysis._finish)


def _run_job(run_id: str, cache: _ModelCache, ctx: JobContext | None = None) -> None:
    import profiles
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
    if ctx is None:  # direct callers (tests) pass no context: cancel flags and finish come through the facade
        ctx = _default_context(run_id)
    ctx.check_cancel()
    runs._update_run(run_id, status="running", progress=0.0)

    model = cache.get(req["model"], device)
    src_w, src_h = rec["width"], rec["height"]
    profile = None if req["profile"] == "default" else req["profile"]
    # The analysed window of the frame (CONTRACTS section 1a): the full frame, or a portrait window of it. The stored
    # grids, masks and depth maps always span the whole source frame at the same cell size; cells outside the window
    # hold NO_DATA.
    win = store_requests.run_window(rec, req)
    windowed = not profiles.is_full_window(win, src_w, src_h)
    spec = resolve_input_spec(win["w"], win["h"], profile, None, None)
    grid_h = round(constants.GRID_W * src_h / src_w)
    g0, gcols = profiles.grid_columns(win, src_w, constants.GRID_W) if windowed else (0, constants.GRID_W)
    d0, d1 = (
        round(g0 * constants.DEPTH_W / constants.GRID_W),
        round((g0 + gcols) * constants.DEPTH_W / constants.GRID_W),
    )

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
    runs._update_run(
        run_id,
        gridW=constants.GRID_W,
        gridH=grid_h,
        srcW=src_w,
        srcH=src_h,
        inputSpec={"w": spec.dst_w, "h": spec.dst_h, "description": spec.description},
        classNames=cache.class_names,
        window=win,
        gridWindow={"c0": g0, "cols": gcols} if windowed else None,
    )

    depth_model = None
    if req.get("depth", "none") != "none":
        depth_model = cache.get_depth(req["depth"], device)
        util._log(f"run {run_id}: depth {req['depth']}")
    depth_units = None
    depth_maps: list[NDArray[Any]] = []
    depth_seconds = 0.0

    reader = _FrameReader(rec, motion_end=end)
    grids: list[NDArray[Any]] = []
    times: list[float] = []
    t_start = time.perf_counter()
    try:
        for k in range(n_target):
            ctx.check_cancel()
            got = reader.read(start + k / fps)
            if got is None:
                break
            frame_t, bgr = got
            if windowed:
                bgr = np.ascontiguousarray(bgr[win["y0"] : win["y0"] + win["h"], win["x0"] : win["x0"] + win["w"]])
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            if depth_model is not None:
                td = time.perf_counter()
                raw, depth_units = depth_model.predict(rgb)
                small_d = cv2.resize(
                    raw,
                    (d1 - d0, constants.DEPTH_H) if windowed else (constants.DEPTH_W, constants.DEPTH_H),
                    interpolation=cv2.INTER_AREA,
                )
                small_d[~np.isfinite(small_d) | (small_d <= 0)] = np.nan
                if windowed:  # full-frame depth map: NaN outside the window
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
                small[:, g0 : g0 + gcols] = cv2.resize(crop, (gcols, grid_h), interpolation=cv2.INTER_NEAREST)
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
        ctx.check_cancel()
        reader.finish_motion()
    finally:
        reader.close()

    if not grids:
        raise RuntimeError("No frames could be read from the requested range")
    elapsed = time.perf_counter() - t_start
    np.savez_compressed(
        out / "grids.npz",
        grids=np.stack(grids),
        t=np.array(times, np.float64),
        index=np.arange(len(grids), dtype=np.int32),
    )
    if depth_model is not None:
        np.savez_compressed(
            out / "depth.npz",
            depth=np.stack(depth_maps),
            t=np.array(times, np.float64),
            units=np.array(depth_units),
            anchor=np.array(constants.DEPTH_ANCHOR.get(req["depth"], "")),
        )
        runs._update_run(
            run_id,
            depth=req["depth"],
            depthUnits=depth_units,
            depthMsPerFrame=round(depth_seconds * 1000 / len(depth_maps), 1),
        )
    motion = reader.motion_track()
    np.savez_compressed(out / "motion.npz", **motion)  # type: ignore[arg-type]
    n_motion = len(motion["t"])
    util._log(
        f"run {run_id}: motion {n_motion} source frames, {reader.motion_seconds * 1000 / max(n_motion, 1):.2f} ms/frame"
    )
    runs._update_run(
        run_id,
        analysisVersion=constants.ANALYSIS_VERSION,
        motionFrames=n_motion,
        frameCount=len(grids),
        msPerFrame=round(elapsed * 1000 / len(grids), 1),
        seekSeconds=round(reader.seek_seconds, 3),
        progress=1.0,
    )
    util._log(f"run {run_id}: {len(grids)} frames in {elapsed:.1f}s")

    ctx.check_cancel()
    cdoc = None
    try:
        cdoc = stage_collision.collision_pass(run_id)
    except Exception as exc:
        util._log(f"run {run_id}: collision pass failed: {exc!r}")
    if cdoc is not None:
        stage_collision._build_worldmap(run_id, cdoc["id"])
    ctx.finish(status="done", progress=1.0)
