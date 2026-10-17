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
from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from lab import analysis, display, recordings, reviews, versioning  # noqa: E402

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


def _validated_settings(body: dict, config: dict) -> dict:
    """Validate a settings body (§4). A legacy `corridor` key is ignored."""
    mount = body.get("mount") or config["defaultMount"]
    if mount not in config["mountPresets"]:
        raise HTTPException(422, f"Unknown mount {mount!r}; expected one of {list(config['mountPresets'])}")
    return {"mount": mount,
            "hfovDeg": _opt_number(body, "hfovDeg", 10, 180, hi_inclusive=False),
            "cameraHeightM": _opt_number(body, "cameraHeightM", 0.5, 2.5),
            "stepLengthM": _opt_number(body, "stepLengthM", 0.3, 2.0)}


def _settings_response(rec_id: str) -> dict:
    collision = _collision()
    config = collision.load_config()
    stored = recordings.get_settings(rec_id, config["defaultMount"])
    preset = config["mountPresets"][stored["mount"]]
    resolved = {
        "hfovDeg": stored["hfovDeg"] if stored["hfovDeg"] is not None else config["defaultHfovDeg"],
        "cameraHeightM": stored["cameraHeightM"] if stored["cameraHeightM"] is not None else preset.get("cameraHeightM"),
        "stepLengthM": stored["stepLengthM"],  # null = auto
        "horizon": preset.get("horizon"),
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
    return {"models": analysis.list_models(), "profiles": analysis.RESOLUTIONS}


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
    return {"version": result["version"], "elapsedSeconds": result["elapsedSeconds"],
            "hazards": f"/api/runs/{run_id}/hazards.json", "events": f"/api/runs/{run_id}/events.json"}


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
    return FileResponse(page)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
