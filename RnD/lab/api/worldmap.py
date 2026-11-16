"""World-map router: build, read, pose, cell and snapshot PNGs, with the world-map cache."""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from lab import analysis, collisions
from lab.api.deps import _cid, _collision, _run

# --- world map (v26.2 step 1 spike; CONTRACTS 8.1) ---------------------------------------------------------------
# worldmap.npz: classes (N,200,200) uint8 (255 = unknown), conf (N,200,200) uint8, surface / object (N,200,200) uint8
# (v26.2.4, the layers on their own), t, pose (N,3), cellM, origin, ms;
# v26.2.10: alignDeg / alignM / agree / agreePrior (N,).
# Built from stored files only (pure numpy, synchronous like the collision pass; never the GPU queue).

_WM_CACHE_RUNS = 1
_wm_cache: OrderedDict[tuple[Any, ...], tuple[Any, ...]] = OrderedDict()  # (run_id, cid) -> (mtime_ns, arrays)
_wm_lock = threading.Lock()


router = APIRouter()


def _run_worldmap(run_id: str, collision: str | None = None) -> dict[str, Any]:
    run = _run(run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"Run is {run['status']}, not done")
    cid = _cid(run, collision)
    key = (run_id, cid)
    path = collisions.collision_dir(run_id, cid) / "worldmap.npz"
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        raise HTTPException(404, "worldmap.npz not available (POST /api/runs/{id}/worldmap builds it)") from None
    with _wm_lock:
        ent = _wm_cache.get(key)
        if ent is None or ent[0] != mtime:
            with np.load(path) as z:
                ent = (mtime, {k: z[k] for k in z.files})
            _wm_cache[key] = ent
        _wm_cache.move_to_end(key)
        while len(_wm_cache) > _WM_CACHE_RUNS:
            _wm_cache.popitem(last=False)
        return ent[1]  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.post("/api/runs/{run_id}/worldmap")
def build_worldmap(run_id: str, collision: str | None = None) -> dict[str, Any]:
    run = _run(run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"Run is {run['status']}, not done")
    _collision()
    cid = _cid(run, collision)
    try:
        result = analysis.worldmap_pass(run_id, cid)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"{exc} not available (a worldmap needs grids.npz and hazards.json)") from None
    return {**result, "worldmap": f"/api/runs/{run_id}/worldmap?collision={cid}"}


@router.get("/api/runs/{run_id}/worldmap")
def get_worldmap(run_id: str, collision: str | None = None) -> dict[str, Any]:
    run = _run(run_id)
    if not collisions.ids(run):
        return {"exists": False}
    cid = _cid(run, collision)
    path = collisions.collision_dir(run_id, cid) / "worldmap.npz"
    if not path.exists():
        return {"exists": False}
    wm = _run_worldmap(run_id, cid)
    n, h, w = wm["classes"].shape
    ms = wm["ms"]
    # v26.2.7: the class ids of the wall faces and of the surfaces, for the Lab's wall line
    # (the border between a face and a surface cell)
    import worldmap

    names = list(_run(run_id).get("classNames") or [])
    wcfg = collisions.apply_overrides(
        worldmap.load_config(), (collisions.read_doc(run_id, cid) or {}).get("overrides") or {}, "worldmap"
    )
    kinds = worldmap.class_kinds(wcfg, names)
    face_ids = [i for i, n_ in enumerate(names) if n_ in wcfg.get("faceClasses", ())]
    surface_ids = [i for i in range(len(names)) if kinds[i] == worldmap.KIND_SURFACE]
    return {
        "exists": True,
        "collision": cid,
        "frames": int(n),
        "cellM": float(wm["cellM"]),
        "origin": [int(v) for v in wm["origin"]],
        "width": int(w),
        "height": int(h),
        "msMean": round(float(ms.mean()), 2),
        "msP95": round(float(np.percentile(ms, 95)), 2),
        "faceClassIds": face_ids,
        "surfaceClassIds": surface_ids,
        "builtAt": str(path.stat().st_mtime_ns),
    }  # v26.2.7: the Lab adds it as ?v= to the cached PNG / pose URLs


@router.get("/api/runs/{run_id}/worldmap/pose.json")
def get_worldmap_pose(run_id: str, collision: str | None = None) -> dict[str, Any]:
    wm = _run_worldmap(run_id, collision)
    out = {"t": [round(float(v), 4) for v in wm["t"]], "pose": [[round(float(a), 3) for a in p] for p in wm["pose"]]}
    # v26.2.10: the pose the map found for itself (poseAlign): the accumulated heading correction (deg) and
    # position correction (m), and the share of the frame's seen cells whose snapshot class equals the frame's own
    # observation (null: no seen cell / a map built before v26.2.10)
    for key in ("alignDeg", "alignM", "agree"):
        if key in wm:
            out[key] = [None if not math.isfinite(float(v)) else round(float(v), 4) for v in wm[key]]
    return out


@router.get("/api/runs/{run_id}/worldmap/cell")
def get_worldmap_cell(
    run_id: str, i: int = Query(), col: int = Query(), row: int = Query(), collision: str | None = None
) -> dict[str, Any]:
    """One map cell of snapshot ``i`` (v26.2.4, the Lab's click readout): the surface and the object layer on their own, the combined class
    the collision rules read, their confidences, and the cell's place (metres ahead / right of the user). A layer is ``null`` where nothing was
    observed (255 in the file). Maps built before v26.2.4 have no layers: ``layers`` is false and ``surface`` / ``object`` are null."""  # noqa: E501
    wm = _run_worldmap(run_id, collision)
    n, h, w = wm["classes"].shape
    if i < 0 or i >= n:
        raise HTTPException(404, "No such frame")
    if not (0 <= row < h and 0 <= col < w):
        raise HTTPException(422, "cell outside the map")
    ox, oy = (int(v) for v in wm["origin"])
    cell = float(wm["cellM"])

    def cls(a: Any) -> int | None:
        v = int(a[i, row, col])
        return None if v == 255 else v

    layers = "surface" in wm and "object" in wm
    return {
        "i": i,
        "t": round(float(wm["t"][i]), 4),
        "col": col,
        "row": row,
        "aheadM": round((oy - row) * cell, 2),
        "rightM": round((col - ox) * cell, 2),
        "layers": layers,
        "combined": cls(wm["classes"]),
        "conf": int(wm["conf"][i, row, col]),
        "surface": cls(wm["surface"]) if layers else None,
        "object": cls(wm["object"]) if layers else None,
    }


@router.get("/api/runs/{run_id}/worldmap/{index}.png")
def get_worldmap_png(run_id: str, index: int, alpha: str = "binary", collision: str | None = None) -> Response:
    """Snapshot of frame ``index``. Default: RGBA, R = G = B = class id (as classes.png, read the red channel), alpha 255
    where the cell is known and 0 where unknown. ``alpha=conf``: alpha = confidence (0..255; browsers premultiply, so
    the class id is only exact where alpha is 255). ``alpha=gray``: single-channel classes (255 = unknown)."""  # noqa: E501
    wm = _run_worldmap(run_id, collision)
    if index < 0 or index >= len(wm["classes"]):
        raise HTTPException(404, "No such frame")
    cls = np.ascontiguousarray(wm["classes"][index], dtype=np.uint8)
    if alpha == "gray":
        img = cls
    else:
        a = (
            np.ascontiguousarray(wm["conf"][index], dtype=np.uint8)
            if alpha == "conf"
            else np.where(cls != 255, 255, 0).astype(np.uint8)
        )
        img = cv2.merge(  # type: ignore[assignment]  # wider ndarray dtype than the grey branch
            [cls, cls, cls, a]
        )  # cv2 writes BGRA; B = G = R = class id
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise HTTPException(500, "PNG encode failed")
    return Response(buf.tobytes(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})
