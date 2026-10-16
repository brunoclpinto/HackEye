"""HackEye Lab web server (REST API of CONTRACTS §8 + static frontend).

Thin layer: discovery and proxies live in recordings.py, segmentation runs
and the GPU queue in analysis.py, collision logic in src/collision.py.
Endpoints are plain `def` (not async) so FastAPI runs them in its threadpool;
none of them block for long except the collision re-run, which is pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from lab import analysis, recordings, reviews  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title="HackEye Lab")


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
    return {"models": analysis.list_models(), "profiles": analysis.PROFILES}


@app.post("/api/runs")
def post_run(body: dict) -> dict:
    try:
        return analysis.submit_run(body)
    except analysis.RunError as exc:
        raise HTTPException(422, str(exc)) from None


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


# --- speech reviews (§10) ----------------------------------------------------

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
