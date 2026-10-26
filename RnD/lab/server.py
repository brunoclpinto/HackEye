"""HackEye Lab web server (REST API of CONTRACTS §8 + static frontend).

Thin layer: discovery and proxies live in recordings.py, segmentation runs
and the GPU queue in analysis.py, collision logic in src/collision.py.
Endpoints are plain `def` (not async) so FastAPI runs them in its threadpool;
none of them block for long except the collision re-run, which is pure numpy.
"""

from __future__ import annotations

import bisect
import json
import math
import sys
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from fastapi import FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from lab import analysis, display, recordings, reviews, sounds, versioning  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
_last_wipe: dict = {}


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # CONTRACTS section 11: version policy runs before serving (and before the
    # lazily-started GPU worker can touch runs/).
    global _last_wipe
    _last_wipe = versioning.apply_version_policy(recordings.LAB_DIR, VERSION_FILE)

    def _remember(result: dict) -> None:
        global _last_wipe
        _last_wipe = result

    watcher = versioning.VersionWatcher(recordings.LAB_DIR, VERSION_FILE, analysis, on_result=_remember)
    watcher.start()
    try:
        yield
    finally:
        watcher.stop()


app = FastAPI(title="HackEye Lab", lifespan=_lifespan)


class _SelectiveGZip:
    """GZipMiddleware (CONTRACTS 12.1) for everything except media: the proxy mp4 is served with
    Range requests and PNG masks are already compressed, so those bypass it untouched."""

    def __init__(self, app):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if path.startswith("/media/") or path.endswith(".png"):
            await self.app(scope, receive, send)
        else:
            await self.gzip(scope, receive, send)


app.add_middleware(_SelectiveGZip)


def _collision():
    """The collision module, or a 503 while src/collision.py doesn't exist."""
    try:
        import collision
    except ImportError as exc:
        raise HTTPException(503, f"Collision module unavailable: {exc}") from None
    return collision


def _recording(rec_id: str) -> dict:
    rec = recordings.get_recording(rec_id)
    if rec is None:
        raise HTTPException(404, f"Unknown recording: {rec_id}")
    return rec


def _run(run_id: str) -> dict:
    run = analysis.get_run(run_id) if analysis.RUN_ID_RE.match(run_id) else None
    if run is None:
        raise HTTPException(404, f"Unknown run: {run_id}")
    return run


@app.get("/api/version")
def api_version() -> dict:
    try:
        marker = versioning.read_marker(recordings.LAB_DIR)
    except ValueError:
        marker = None
    return {
        "version": versioning.read_version(VERSION_FILE),
        "since": marker.get("since") if marker else None,
        "lastWipe": _last_wipe,
    }


# --- recordings + proxy ---------------------------------------------------

# Browser diagnostics (CONTRACTS 12.2): the page posts its speech/audio events here so they can be read from the host.
CLIENT_LOG_MAX_BYTES = 5 * 1024 * 1024
CLIENT_LOG_MAX_ENTRIES = 200
CLIENT_LOG_MAX_BODY = 256 * 1024
_client_log_lock = threading.Lock()


def _client_log_path() -> Path:
    return recordings.LAB_DIR / "client-log.jsonl"


@app.post("/api/client-log")
async def post_client_log(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > CLIENT_LOG_MAX_BODY:
        raise HTTPException(413, "client log batch too large")
    try:
        entries = json.loads(raw or b"null")
    except ValueError:
        raise HTTPException(400, "body must be a JSON array") from None
    if not isinstance(entries, list):
        raise HTTPException(400, "body must be a JSON array")
    ua = request.headers.get("user-agent", "")
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"
    lines = "".join(
        json.dumps({"server": stamp, "ua": ua, **(e if isinstance(e, dict) else {"value": e})}, ensure_ascii=False) + "\n"
        for e in entries[:CLIENT_LOG_MAX_ENTRIES])
    path = _client_log_path()
    with _client_log_lock:
        try:
            if path.exists() and path.stat().st_size + len(lines) > CLIENT_LOG_MAX_BYTES:
                path.replace(path.with_name(path.name + ".1"))     # one rotated generation: <= ~10 MB in all
            with path.open("a", encoding="utf-8") as f:
                f.write(lines)
        except OSError as e:
            raise HTTPException(500, f"client log not writable: {e}") from None
    return {"ok": True, "n": min(len(entries), CLIENT_LOG_MAX_ENTRIES)}


@app.get("/api/recordings")
def list_recordings() -> list[dict]:
    return recordings.list_recordings()


@app.post("/api/recordings/{rec_id}/proxy")
def build_proxy(rec_id: str) -> dict:
    return recordings.start_proxy(_recording(rec_id))


@app.api_route("/media/{name}", methods=["GET", "HEAD"])
def get_proxy(name: str) -> FileResponse:
    rec_id = name[:-4] if name.endswith(".mp4") else None
    path = recordings.proxy_path(rec_id) if rec_id and "/" not in rec_id and ".." not in rec_id else None
    # `.part` files never match: only a finished build has the final name.
    if path is None or not path.exists():
        raise HTTPException(404, "Proxy not ready")
    return FileResponse(path, media_type="video/mp4")


# --- settings ---------------------------------------------------------------

def _opt_number(body: dict, key: str, lo: float, hi: float, hi_inclusive: bool = True):
    v = body.get(key)
    if v is None:
        return None
    ok = not isinstance(v, bool) and isinstance(v, (int, float)) and lo <= v and (v <= hi if hi_inclusive else v < hi)
    if not ok:
        bracket = "]" if hi_inclusive else ")"
        raise HTTPException(422, f"{key} must be null or a number in [{lo:g}, {hi:g}{bracket}")
    return v


PROJECTIONS = ("auto", "rectilinear", "fisheye")
DISTANCE_SOURCES = ("ground", "depth")
OBJECT_DISTANCES = ("depth", "ground-contact", "ground+depth")
CAMERA_SIDES = ("left", "center", "right")
ORIENTATIONS = ("landscape", "portrait")


def _location(body: dict, config: dict):
    """cameraLocation: null (legacy mount) or a key of collision.json body.cameraLocations."""
    v = body.get("cameraLocation")
    if v is None:
        return None
    options = list((config.get("body") or {}).get("cameraLocations", {}))
    if v not in options:
        raise HTTPException(422, f"cameraLocation must be null or one of {options}")
    return v


def _choice(body: dict, key: str, options: tuple, default: str) -> str:
    v = body.get(key)
    if v is None:
        return default
    if v not in options:
        raise HTTPException(422, f"{key} must be one of {list(options)}")
    return v


def _bool(body: dict, key: str, default: bool) -> bool:
    v = body.get(key)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise HTTPException(422, f"{key} must be true or false")
    return v


def _validated_settings(body: dict, config: dict) -> dict:
    """Validate a settings body (§4). A legacy `corridor` key is ignored."""
    mount = body.get("mount") or config["defaultMount"]
    if mount not in config["mountPresets"]:
        raise HTTPException(422, f"Unknown mount {mount!r}; expected one of {list(config['mountPresets'])}")
    return {"mount": mount,
            "hfovDeg": _opt_number(body, "hfovDeg", 10, 180, hi_inclusive=False),
            "cameraHeightM": _opt_number(body, "cameraHeightM", 0.5, 2.5),
            "stepLengthM": _opt_number(body, "stepLengthM", 0.3, 2.0),
            "projection": _choice(body, "projection", PROJECTIONS, "auto"),
            "distanceSource": _choice(body, "distanceSource", DISTANCE_SOURCES, "depth"),
            "userHeightM": _opt_number(body, "userHeightM", 1.0, 2.3),
            "cameraLocation": _location(body, config),
            "cameraSide": _choice(body, "cameraSide", CAMERA_SIDES, "center"),
            "orientation": _choice(body, "orientation", ORIENTATIONS, "landscape"),
            "objectDistance": _choice(body, "objectDistance", OBJECT_DISTANCES, config.get("distance", {}).get("objectDistance", "depth")),
            "useHorizon": _bool(body, "useHorizon", bool(config.get("distance", {}).get("useHorizon", True)))}


def _settings_response(rec_id: str) -> dict:
    collision = _collision()
    config = collision.load_config()
    stored = recordings.get_settings(rec_id, config["defaultMount"])
    rs = collision.resolve_settings(
        config, stored["mount"], stored["hfovDeg"], stored["cameraHeightM"], stored["stepLengthM"],
        projection=stored["projection"], distance_source=stored["distanceSource"],
        user_height_m=stored["userHeightM"], camera_location=stored["cameraLocation"],
        camera_side=stored["cameraSide"], object_distance=stored["objectDistance"], use_horizon=stored["useHorizon"])
    resolved = {
        "hfovDeg": rs.hfov_deg,
        "projection": rs.projection,
        "cameraHeightM": rs.camera_height_m,
        "stepLengthM": rs.step_length_m,  # null = auto
        "horizon": rs.horizon_default,
        "userHeightM": rs.user_height_m,
        "cameraLocation": rs.camera_location,
        "cameraSide": rs.camera_side,
        "lateralOffsetM": rs.lateral_offset_m,
        "objectDistance": rs.object_distance,
        "useHorizon": rs.use_horizon,
    }
    return {**stored, "resolved": resolved}


@app.get("/api/recordings/{rec_id}/settings")
def get_settings(rec_id: str) -> dict:
    _recording(rec_id)
    return _settings_response(rec_id)


@app.put("/api/recordings/{rec_id}/settings")
def put_settings(rec_id: str, body: dict) -> dict:
    _recording(rec_id)
    config = _collision().load_config()
    recordings.save_settings(rec_id, _validated_settings(body, config))
    return _settings_response(rec_id)


@app.get("/api/config/collision")
def get_collision_config() -> dict:
    return _collision().load_config()


# --- models + runs ----------------------------------------------------------

@app.get("/api/models")
def get_models() -> dict:
    return {"models": analysis.list_models(), "profiles": analysis.RESOLUTIONS,
            "depthModels": list(analysis.DEPTH_MODELS)}


@app.post("/api/runs")
def post_run(body: dict) -> dict:
    try:
        return analysis.submit_run(body)
    except analysis.RunConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except analysis.RunError as exc:
        raise HTTPException(422, str(exc)) from None


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    if not analysis.RUN_ID_RE.match(run_id):
        raise HTTPException(404, f"Unknown run: {run_id}")
    try:
        doc = analysis.cancel_run(run_id)
    except analysis.RunConflict as exc:
        raise HTTPException(409, str(exc)) from None
    if doc is None:
        raise HTTPException(404, f"Unknown run: {run_id}")
    # A running job stops between frames; give it a moment so the reply shows the end state.
    for _ in range(30):
        if doc["status"] not in analysis.ACTIVE_STATUSES:
            break
        time.sleep(0.1)
        doc = analysis.get_run(run_id) or doc
    return doc


@app.get("/api/runs")
def list_runs(recording: str | None = None) -> list[dict]:
    return analysis.list_runs(recording)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _run(run_id)


@app.post("/api/runs/{run_id}/collision")
def rerun_collision(run_id: str) -> dict:
    run = _run(run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"Run is {run['status']}, not done")
    _collision()
    result = analysis.collision_pass(run_id)
    if (analysis.run_dir(run_id) / "worldmap.npz").exists():     # v26.2.3: a built map would be stale (object distance / horizon switch): rebuild it
        try:
            analysis.worldmap_pass(run_id)
        except Exception as exc:  # noqa: BLE001 - the collision result stands
            analysis._log(f"run {run_id}: worldmap refresh failed: {exc!r}")
    return {"version": result["version"], "elapsedSeconds": result["elapsedSeconds"],
            "hazards": f"/api/runs/{run_id}/hazards.json", "events": f"/api/runs/{run_id}/events.json"}


# --- world map (v26.2 step 1 spike; CONTRACTS 8.1) ---------------------------------------------------------------
# worldmap.npz: classes (N,200,200) uint8 (255 = unknown), conf (N,200,200) uint8, surface / object (N,200,200) uint8 (v26.2.4, the layers
# on their own), t, pose (N,3), cellM, origin, ms.
# Built from stored files only (pure numpy, synchronous like the collision pass; never the GPU queue).

_WM_CACHE_RUNS = 1
_wm_cache: "OrderedDict[str, tuple]" = OrderedDict()      # run_id -> (mtime_ns, arrays)
_wm_lock = threading.Lock()


def _run_worldmap(run_id: str) -> dict:
    run = _run(run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"Run is {run['status']}, not done")
    path = analysis.run_dir(run_id) / "worldmap.npz"
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        raise HTTPException(404, "worldmap.npz not available (POST /api/runs/{id}/worldmap builds it)") from None
    with _wm_lock:
        ent = _wm_cache.get(run_id)
        if ent is None or ent[0] != mtime:
            with np.load(path) as z:
                ent = (mtime, {k: z[k] for k in z.files})
            _wm_cache[run_id] = ent
        _wm_cache.move_to_end(run_id)
        while len(_wm_cache) > _WM_CACHE_RUNS:
            _wm_cache.popitem(last=False)
        return ent[1]


@app.post("/api/runs/{run_id}/worldmap")
def build_worldmap(run_id: str) -> dict:
    run = _run(run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"Run is {run['status']}, not done")
    _collision()
    try:
        result = analysis.worldmap_pass(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"{exc} not available (a worldmap needs grids.npz and hazards.json)") from None
    return {**result, "worldmap": f"/api/runs/{run_id}/worldmap"}


@app.get("/api/runs/{run_id}/worldmap")
def get_worldmap(run_id: str) -> dict:
    _run(run_id)
    path = analysis.run_dir(run_id) / "worldmap.npz"
    if not path.exists():
        return {"exists": False}
    wm = _run_worldmap(run_id)
    n, h, w = wm["classes"].shape
    ms = wm["ms"]
    return {"exists": True, "frames": int(n), "cellM": float(wm["cellM"]), "origin": [int(v) for v in wm["origin"]],
            "width": int(w), "height": int(h), "msMean": round(float(ms.mean()), 2),
            "msP95": round(float(np.percentile(ms, 95)), 2)}


@app.get("/api/runs/{run_id}/worldmap/pose.json")
def get_worldmap_pose(run_id: str) -> dict:
    wm = _run_worldmap(run_id)
    return {"t": [round(float(v), 4) for v in wm["t"]],
            "pose": [[round(float(a), 3) for a in p] for p in wm["pose"]]}


@app.get("/api/runs/{run_id}/worldmap/cell")
def get_worldmap_cell(run_id: str, i: int = Query(), col: int = Query(), row: int = Query()) -> dict:
    """One map cell of snapshot ``i`` (v26.2.4, the Lab's click readout): the surface and the object layer on their own, the combined class
    the collision rules read, their confidences, and the cell's place (metres ahead / right of the user). A layer is ``null`` where nothing was
    observed (255 in the file). Maps built before v26.2.4 have no layers: ``layers`` is false and ``surface`` / ``object`` are null."""
    wm = _run_worldmap(run_id)
    n, h, w = wm["classes"].shape
    if i < 0 or i >= n:
        raise HTTPException(404, "No such frame")
    if not (0 <= row < h and 0 <= col < w):
        raise HTTPException(422, "cell outside the map")
    ox, oy = (int(v) for v in wm["origin"])
    cell = float(wm["cellM"])

    def cls(a):
        v = int(a[i, row, col])
        return None if v == 255 else v

    layers = "surface" in wm and "object" in wm
    return {"i": i, "t": round(float(wm["t"][i]), 4), "col": col, "row": row,
            "aheadM": round((oy - row) * cell, 2), "rightM": round((col - ox) * cell, 2),
            "layers": layers, "combined": cls(wm["classes"]), "conf": int(wm["conf"][i, row, col]),
            "surface": cls(wm["surface"]) if layers else None, "object": cls(wm["object"]) if layers else None}


@app.get("/api/runs/{run_id}/worldmap/{index}.png")
def get_worldmap_png(run_id: str, index: int, alpha: str = "binary") -> Response:
    """Snapshot of frame ``index``. Default: RGBA, R = G = B = class id (as classes.png, read the red channel), alpha 255
    where the cell is known and 0 where unknown. ``alpha=conf``: alpha = confidence (0..255; browsers premultiply, so
    the class id is only exact where alpha is 255). ``alpha=gray``: single-channel classes (255 = unknown)."""
    wm = _run_worldmap(run_id)
    if index < 0 or index >= len(wm["classes"]):
        raise HTTPException(404, "No such frame")
    cls = np.ascontiguousarray(wm["classes"][index], dtype=np.uint8)
    if alpha == "gray":
        img = cls
    else:
        a = np.ascontiguousarray(wm["conf"][index], dtype=np.uint8) if alpha == "conf" else np.where(cls != 255, 255, 0).astype(np.uint8)
        img = cv2.merge([cls, cls, cls, a])                 # cv2 writes BGRA; B = G = R = class id
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise HTTPException(500, "PNG encode failed")
    return Response(buf.tobytes(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})


# --- windowed hazards (CONTRACTS 12.1) ----------------------------------------
# A full-length run's hazards.json is ~120 MB: parse it once per run, keep an LRU of 2 runs,
# and serve slices. The cache key includes the file's mtime/size, so a collision re-run
# (which rewrites the file) is picked up on the next request.

MAX_WINDOW_S = 600.0
FRAME_GAP_S = 1.0       # /frame: still "inside the run" up to this long after the last analysed frame
_HZ_CACHE_RUNS = 2
_hz_cache: "OrderedDict[str, dict]" = OrderedDict()
_hz_lock = threading.Lock()


def _hazards_doc(run_id: str) -> dict:
    run = _run(run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"Run is {run['status']}, not done")
    path = analysis.run_dir(run_id) / "hazards.json"
    try:
        st = path.stat()
    except FileNotFoundError:
        raise HTTPException(404, "hazards.json not available (collision pass has not run)") from None
    sig = (st.st_mtime_ns, st.st_size)
    with _hz_lock:  # one parse at a time: concurrent first requests share the work
        ent = _hz_cache.get(run_id)
        if ent is None or ent["sig"] != sig:
            doc = json.loads(path.read_text())
            frames = doc.pop("frames", [])
            ent = {"sig": sig, "head": doc, "frames": frames, "times": [f["t"] for f in frames]}
            _hz_cache[run_id] = ent
        _hz_cache.move_to_end(run_id)
        while len(_hz_cache) > _HZ_CACHE_RUNS:
            _hz_cache.popitem(last=False)
        return ent


def _json(obj: dict) -> Response:
    return Response(json.dumps(obj, separators=(",", ":")), media_type="application/json",
                    headers={"Cache-Control": "no-cache"})


@app.get("/api/runs/{run_id}/hazards")
def get_hazards_window(run_id: str, t_from: float = Query(alias="from"), t_to: float = Query(alias="to")) -> Response:
    if not (math.isfinite(t_from) and math.isfinite(t_to)) or t_to < t_from:
        raise HTTPException(422, "from and to must be finite numbers with to >= from")
    if t_to - t_from > MAX_WINDOW_S:
        raise HTTPException(422, f"window is at most {MAX_WINDOW_S:g} s")
    ent = _hazards_doc(run_id)
    times = ent["times"]
    lo, hi = bisect.bisect_left(times, t_from), bisect.bisect_right(times, t_to)
    head = ent["head"]
    return _json({"version": head.get("version"), "settings": head.get("settings"),
                  "gridW": head.get("gridW"), "gridH": head.get("gridH"),
                  "egoAvailable": head.get("egoAvailable"),
                  "from": t_from, "to": t_to, "frames": ent["frames"][lo:hi]})


@app.get("/api/runs/{run_id}/frame")
def get_hazards_frame(run_id: str, t: float = Query()) -> Response:
    ent = _hazards_doc(run_id)
    times = ent["times"]
    i = bisect.bisect_right(times, t) - 1 if math.isfinite(t) else -1
    if i < 0 or (i == len(times) - 1 and t > times[i] + FRAME_GAP_S):
        raise HTTPException(404, "No analysed frame at this time (outside the run)")
    return _json({"frame": ent["frames"][i]})


@app.get("/api/runs/{run_id}/{name}.json")
def get_run_file(run_id: str, name: str) -> FileResponse:
    _run(run_id)
    if name not in ("hazards", "events"):
        raise HTTPException(404, "Not found")
    path = analysis.run_dir(run_id) / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, f"{name}.json not available (collision pass has not run)")
    return FileResponse(path, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.get("/api/runs/{run_id}/frames/{index}/mask.png")
def get_mask(run_id: str, index: int) -> FileResponse:
    _run(run_id)
    path = analysis.run_dir(run_id) / "masks" / f"{int(index)}.png"
    if index < 0 or not path.exists():
        raise HTTPException(404, "No such frame")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


# --- class grids for client-side mask colouring (view-only) ------------------------------------------
# grids.npz is ~tens of MB for a long run: decompress it once, keep a small LRU keyed by mtime.

_GRID_CACHE_RUNS = 2
_grid_cache: "OrderedDict[str, tuple]" = OrderedDict()   # run_id -> (mtime_ns, grids uint8 (N,H,W), index int32 (N,))
_grid_lock = threading.Lock()


def _run_grids(run_id: str):
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


@app.get("/api/runs/{run_id}/frames/{index}/classes.png")
def get_classes_png(run_id: str, index: int) -> Response:
    _, grids, _index = _run_grids(run_id)
    if index < 0 or index >= len(grids):
        raise HTTPException(404, "No such frame")
    ok, buf = cv2.imencode(".png", np.ascontiguousarray(grids[index], dtype=np.uint8))
    if not ok:
        raise HTTPException(500, "PNG encode failed")
    return Response(buf.tobytes(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})


# --- depth maps (view-only) --------------------------------------------------------------------
# depth.npz holds (N,68,120) float16 (metres for old runs, `units` = "relative" for DA3 Small/Base); one small LRU like the class grids.

DEPTH_VIS_MIN_M, DEPTH_VIS_MAX_M = 0.5, 30.0
_DEPTH_CACHE_RUNS = 2
_depth_cache: "OrderedDict[str, tuple]" = OrderedDict()   # run_id -> (mtime_ns, depth (N,H,W) float16)
_depth_lock = threading.Lock()


def _run_depth(run_id: str) -> tuple[np.ndarray, str]:
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


def depth_to_png(depth: np.ndarray, units: str = "metric") -> bytes:
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
    norm = (np.log(d) - lo) / (hi - lo)                       # 0 = near, 1 = far
    idx = np.round((1.0 - norm) * 255).astype(np.uint8)       # turbo: 255 = red, 0 = blue
    ok, buf = cv2.imencode(".png", cv2.applyColorMap(idx, cv2.COLORMAP_TURBO))
    if not ok:
        raise HTTPException(500, "PNG encode failed")
    return buf.tobytes()


@app.get("/api/runs/{run_id}/depth/{index}.png")
def get_depth_png(run_id: str, index: int) -> Response:
    depth, units = _run_depth(run_id)
    if index < 0 or index >= len(depth):
        raise HTTPException(404, "No such frame")
    return Response(depth_to_png(depth[index], units), media_type="image/png",
                    headers={"Cache-Control": "max-age=86400"})


@app.get("/api/runs/{run_id}/classes")
def get_run_classes(run_id: str) -> dict:
    run = _run(run_id)
    names = run.get("classNames")
    if not names:
        raise HTTPException(404, "Run has no class names")
    try:
        import segmentation  # pure mapping lookup; no model / GPU is loaded
        path, classes, levels = segmentation.find_mapping(names)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    return {"mapping": path.name,
            "classes": [{"id": i, "name": classes[i]["name"], "level": int(classes[i]["safetyLevel"])} for i in sorted(classes)],
            "levels": [{"level": k, "label": v["label"], "color": list(v["color"]), "opacity": display.default_opacity(k)}
                       for k, v in sorted(levels.items())]}


# --- sound profile (v26.1.16; shared across browsers, survives version wipes) -------------------------------

def _sounds_call(fn, *args):
    try:
        return fn(*args)
    except sounds.SoundsError as exc:
        raise HTTPException(exc.status, exc.message) from None


@app.get("/api/sounds")
def get_sounds() -> dict:
    _collision()
    return _sounds_call(sounds.get)


@app.put("/api/sounds")
def put_sounds(body: dict) -> dict:
    _collision()
    return _sounds_call(sounds.put, body)


@app.delete("/api/sounds")
def delete_sounds() -> dict:
    _collision()
    return _sounds_call(sounds.reset)


# --- saved mask display (view-only; shared across browsers) ---------------------------------------------

def _display_call(fn, *args):
    try:
        return fn(*args)
    except display.DisplayError as exc:
        raise HTTPException(exc.status, exc.message) from None


@app.get("/api/display/{mapping}")
def get_display(mapping: str) -> dict:
    return _display_call(display.get, mapping)


@app.put("/api/display/{mapping}/{section}")
def put_display(mapping: str, section: str, body: dict) -> dict:
    if section not in ("classes", "levels"):
        raise HTTPException(404, "Not found")
    return _display_call(display.put, mapping, section, body)


@app.delete("/api/display/{mapping}/{section}")
def delete_display(mapping: str, section: str) -> dict:
    if section not in ("classes", "levels"):
        raise HTTPException(404, "Not found")
    return _display_call(display.reset, mapping, section)


# --- notification (speech + beeps) reviews (§10, §14) ----------------------------------------------------

def _review_call(fn, *args):
    try:
        return fn(*args)
    except reviews.ReviewError as exc:
        raise HTTPException(exc.status, exc.message) from None


# (declared before the {name}.json run route; no path clash, kept with its peers)
@app.get("/api/reviews/export")
def export_reviews(recording: str | None = None) -> dict:
    if recording is not None:
        _recording(recording)
        ids = [recording]
    else:
        ids = reviews.recordings_with_reviews()
    return reviews.export(ids)


@app.get("/api/recordings/{rec_id}/reviews")
def list_reviews(rec_id: str) -> dict:
    _recording(rec_id)
    return reviews.list_annotations(rec_id)


@app.post("/api/recordings/{rec_id}/reviews", status_code=201)
def post_review(rec_id: str, body: dict) -> dict:
    rec = _recording(rec_id)
    return _review_call(reviews.create, rec_id, rec["duration"], body)


@app.put("/api/recordings/{rec_id}/reviews/{ann_id}")
def put_review(rec_id: str, ann_id: str, body: dict) -> dict:
    rec = _recording(rec_id)
    return _review_call(reviews.update, rec_id, rec["duration"], ann_id, body)


@app.delete("/api/recordings/{rec_id}/reviews/{ann_id}", status_code=204)
def delete_review(rec_id: str, ann_id: str) -> Response:
    _recording(rec_id)
    _review_call(reviews.delete, rec_id, ann_id)
    return Response(status_code=204)


# --- frontend ---------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    page = STATIC_DIR / "index.html"
    if not page.exists():
        raise HTTPException(404, "Frontend not installed")
    return FileResponse(page, headers={"Cache-Control": "no-cache"})


class _RevalidatingStaticFiles(StaticFiles):
    """Static files are revalidated on every load (ETag keeps it cheap): no heuristic caching of stale app.js / js/*.js."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", _RevalidatingStaticFiles(directory=STATIC_DIR), name="static")
