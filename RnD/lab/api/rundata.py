"""Run-data router: windowed hazards, frame, run files, masks, class grids, depth maps, run classes, caches."""

from __future__ import annotations

import bisect
import json
import math
import threading
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

import groundfuse
from lab import analysis, collisions, display
from lab.api.deps import _cid, _run

# --- windowed hazards (CONTRACTS 12.1) ----------------------------------------
# A full-length run's hazards.json is ~120 MB: parse it once per run, keep an LRU of 2 runs,
# and serve slices. The cache key includes the file's mtime/size, so a collision re-run
# (which rewrites the file) is picked up on the next request.

MAX_WINDOW_S = 600.0
FRAME_GAP_S = 1.0  # /frame: still "inside the run" up to this long after the last analysed frame
_HZ_CACHE_RUNS = 2
_hz_cache: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()  # (run_id, cid) -> parsed hazards.json
_hz_lock = threading.Lock()

router = APIRouter()


def _hazards_doc(run_id: str, collision: str | None = None) -> dict[str, Any]:
    run = _run(run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"Run is {run['status']}, not done")
    cid = _cid(run, collision)
    key = (run_id, cid)
    path = collisions.collision_dir(run_id, cid) / "hazards.json"
    try:
        st = path.stat()
    except FileNotFoundError:
        raise HTTPException(404, "hazards.json not available (collision pass has not run)") from None
    sig = (st.st_mtime_ns, st.st_size)
    with _hz_lock:  # one parse at a time: concurrent first requests share the work
        ent = _hz_cache.get(key)
        if ent is None or ent["sig"] != sig:
            doc = json.loads(path.read_text())
            frames = doc.pop("frames", [])
            st = doc.get("settings")
            if isinstance(st, dict) and st.get("objectDistance"):  # v26.2.11: what the run really used
                st["objectDistanceEffective"] = groundfuse.resolved_mode(
                    st["objectDistance"], st.get("useHorizon", True)
                )
            ent = {"sig": sig, "head": doc, "frames": frames, "times": [f["t"] for f in frames]}
            _hz_cache[key] = ent
        _hz_cache.move_to_end(key)
        while len(_hz_cache) > _HZ_CACHE_RUNS:
            _hz_cache.popitem(last=False)
        return ent


def _json(obj: dict[str, Any]) -> Response:
    return Response(
        json.dumps(obj, separators=(",", ":")), media_type="application/json", headers={"Cache-Control": "no-cache"}
    )


@router.get("/api/runs/{run_id}/hazards")
def get_hazards_window(
    run_id: str, t_from: float = Query(alias="from"), t_to: float = Query(alias="to"), collision: str | None = None
) -> Response:
    if not (math.isfinite(t_from) and math.isfinite(t_to)) or t_to < t_from:
        raise HTTPException(422, "from and to must be finite numbers with to >= from")
    if t_to - t_from > MAX_WINDOW_S:
        raise HTTPException(422, f"window is at most {MAX_WINDOW_S:g} s")
    ent = _hazards_doc(run_id, collision)
    times = ent["times"]
    lo, hi = bisect.bisect_left(times, t_from), bisect.bisect_right(times, t_to)
    head = ent["head"]
    return _json(
        {
            "version": head.get("version"),
            "settings": head.get("settings"),
            "projection": head.get("projection"),
            "gridW": head.get("gridW"),
            "gridH": head.get("gridH"),
            "egoAvailable": head.get("egoAvailable"),
            **(
                {"worldTracksSettings": head["worldTracksSettings"]} if "worldTracksSettings" in head else {}
            ),  # v26.2.9
            "from": t_from,
            "to": t_to,
            "frames": ent["frames"][lo:hi],
        }
    )


@router.get("/api/runs/{run_id}/frame")
def get_hazards_frame(run_id: str, t: float = Query(), collision: str | None = None) -> Response:
    ent = _hazards_doc(run_id, collision)
    times = ent["times"]
    i = bisect.bisect_right(times, t) - 1 if math.isfinite(t) else -1
    if i < 0 or (i == len(times) - 1 and t > times[i] + FRAME_GAP_S):
        raise HTTPException(404, "No analysed frame at this time (outside the run)")
    return _json({"frame": ent["frames"][i]})


@router.get("/api/runs/{run_id}/{name}.json")
def get_run_file(run_id: str, name: str, collision: str | None = None) -> FileResponse:
    run = _run(run_id)
    if name not in ("hazards", "events"):
        raise HTTPException(404, "Not found")
    path = collisions.collision_dir(run_id, _cid(run, collision)) / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, f"{name}.json not available (collision pass has not run)")
    return FileResponse(path, media_type="application/json", headers={"Cache-Control": "no-cache"})


@router.get("/api/runs/{run_id}/frames/{index}/mask.png")
def get_mask(run_id: str, index: int) -> FileResponse:
    _run(run_id)
    path = analysis.run_dir(run_id) / "masks" / f"{int(index)}.png"
    if index < 0 or not path.exists():
        raise HTTPException(404, "No such frame")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


# --- class grids for client-side mask colouring (view-only) ------------------------------------------
# grids.npz is ~tens of MB for a long run: decompress it once, keep a small LRU keyed by mtime.

_GRID_CACHE_RUNS = 2
_grid_cache: OrderedDict[str, tuple[Any, ...]] = (
    OrderedDict()
)  # run_id -> (mtime_ns, grids uint8 (N,H,W), index int32 (N,))
_grid_lock = threading.Lock()


def _run_grids(run_id: str) -> tuple[Any, ...]:
    run = _run(run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"Run is {run['status']}, not done")
    path = analysis.run_dir(run_id) / "grids.npz"
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        raise HTTPException(404, "grids.npz not available") from None
    with _grid_lock:
        ent = _grid_cache.get(run_id)
        if ent is None or ent[0] != mtime:
            with np.load(path) as z:
                grids = z["grids"]
                index = z["index"] if "index" in z.files else np.arange(len(grids), dtype=np.int32)
            ent = (mtime, grids, index)
            _grid_cache[run_id] = ent
        _grid_cache.move_to_end(run_id)
        while len(_grid_cache) > _GRID_CACHE_RUNS:
            _grid_cache.popitem(last=False)
        return ent


@router.get("/api/runs/{run_id}/frames/{index}/classes.png")
def get_classes_png(run_id: str, index: int) -> Response:
    _, grids, _index = _run_grids(run_id)
    if index < 0 or index >= len(grids):
        raise HTTPException(404, "No such frame")
    ok, buf = cv2.imencode(".png", np.ascontiguousarray(grids[index], dtype=np.uint8))
    if not ok:
        raise HTTPException(500, "PNG encode failed")
    return Response(buf.tobytes(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})


# --- depth maps (view-only) --------------------------------------------------------------------
# depth.npz holds (N,68,120) float16 (metres for old runs, `units` = "relative" for DA3 Small/Base);
# one small LRU like the class grids.

DEPTH_VIS_MIN_M, DEPTH_VIS_MAX_M = 0.5, 30.0
_DEPTH_CACHE_RUNS = 2
_depth_cache: OrderedDict[str, tuple[Any, ...]] = OrderedDict()  # run_id -> (mtime_ns, depth (N,H,W) float16)
_depth_lock = threading.Lock()


def _run_depth(run_id: str) -> tuple[np.ndarray[Any, Any], str]:
    _run(run_id)
    path = analysis.run_dir(run_id) / "depth.npz"
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        raise HTTPException(404, "Run has no depth") from None
    with _depth_lock:
        ent = _depth_cache.get(run_id)
        if ent is None or ent[0] != mtime:
            with np.load(path) as z:
                ent = (mtime, z["depth"], str(z["units"]) if "units" in z.files else "metric")
            _depth_cache[run_id] = ent
        _depth_cache.move_to_end(run_id)
        while len(_depth_cache) > _DEPTH_CACHE_RUNS:
            _depth_cache.popitem(last=False)
        return ent[1], ent[2]


def depth_to_png(depth: np.ndarray[Any, Any], units: str = "metric") -> bytes:
    """8-bit turbo PNG of a depth map, log scale, near = warm (red), far = cool (blue).
    Metric: fixed 0.5-30 m. Relative: this frame's 2nd-98th percentile (the scale is arbitrary)."""
    d = depth.astype(np.float32)
    if units == "relative":
        good = d[np.isfinite(d) & (d > 0)]
        if good.size:
            vmin, vmax = (float(v) for v in np.percentile(good, (2, 98)))
        else:
            vmin = vmax = 1.0
        vmax = max(vmax, vmin * 1.01)
        vmin = max(vmin, 1e-6)
    else:
        vmin, vmax = DEPTH_VIS_MIN_M, DEPTH_VIS_MAX_M
    lo, hi = math.log(vmin), math.log(vmax)
    d = np.clip(np.nan_to_num(d, nan=vmax, posinf=vmax, neginf=vmin), vmin, vmax)
    norm = (np.log(d) - lo) / (hi - lo)  # 0 = near, 1 = far
    idx = np.round((1.0 - norm) * 255).astype(np.uint8)  # turbo: 255 = red, 0 = blue
    ok, buf = cv2.imencode(".png", cv2.applyColorMap(idx, cv2.COLORMAP_TURBO))
    if not ok:
        raise HTTPException(500, "PNG encode failed")
    return buf.tobytes()


@router.get("/api/runs/{run_id}/depth/{index}.png")
def get_depth_png(run_id: str, index: int) -> Response:
    depth, units = _run_depth(run_id)
    if index < 0 or index >= len(depth):
        raise HTTPException(404, "No such frame")
    return Response(
        depth_to_png(depth[index], units), media_type="image/png", headers={"Cache-Control": "max-age=86400"}
    )


@router.get("/api/runs/{run_id}/classes")
def get_run_classes(run_id: str) -> dict[str, Any]:
    run = _run(run_id)
    names = run.get("classNames")
    if not names:
        raise HTTPException(404, "Run has no class names")
    try:
        import segmentation  # pure mapping lookup; no model / GPU is loaded

        path, classes, levels = segmentation.find_mapping(names)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    return {
        "mapping": path.name,
        "classes": [
            {"id": i, "name": classes[i]["name"], "level": int(classes[i]["safetyLevel"])} for i in sorted(classes)
        ],
        "levels": [
            {"level": k, "label": v["label"], "color": list(v["color"]), "opacity": display.default_opacity(k)}
            for k, v in sorted(levels.items())
        ],
    }
