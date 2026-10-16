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
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from lab import analysis, recordings  # noqa: E402

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

_CORRIDOR_KEYS = ("horizon", "bottomY", "topWidth", "bottomWidth", "centerX")


def _validated_settings(body: dict, config: dict) -> dict:
    mount = body.get("mount") or config["defaultMount"]
    if mount not in config["mountPresets"]:
        raise HTTPException(422, f"Unknown mount {mount!r}; expected one of {list(config['mountPresets'])}")
    hfov = body.get("hfovDeg")
    if hfov is not None:
        if isinstance(hfov, bool) or not isinstance(hfov, (int, float)) or not 10 <= hfov < 180:
            raise HTTPException(422, "hfovDeg must be null or a number in [10, 180)")
    corridor = body.get("corridor")
    if corridor is not None:
        if not isinstance(corridor, dict) or set(corridor) != set(_CORRIDOR_KEYS):
            raise HTTPException(422, f"corridor must be null or an object with keys {list(_CORRIDOR_KEYS)}")
        for k, v in corridor.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
                raise HTTPException(422, f"corridor.{k} must be a number in [0, 1]")
        if corridor["bottomY"] <= corridor["horizon"]:
            raise HTTPException(422, "corridor.bottomY must be greater than corridor.horizon")
    return {"mount": mount, "hfovDeg": hfov, "corridor": corridor}


def _settings_response(rec_id: str) -> dict:
    collision = _collision()
    config = collision.load_config()
    stored = recordings.get_settings(rec_id, config["defaultMount"])
    resolved = collision.resolve_settings(config, stored["mount"], stored["hfovDeg"], stored["corridor"])
    return {**stored, "resolved": {"corridor": _corridor_json(resolved.corridor), "hfovDeg": resolved.hfov_deg}}


def _corridor_json(c) -> dict:
    return {"horizon": c.horizon, "bottomY": c.bottom_y, "topWidth": c.top_width,
            "bottomWidth": c.bottom_width, "centerX": c.center_x}


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
    return {"version": result["version"],
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


# --- frontend ---------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    page = STATIC_DIR / "index.html"
    if not page.exists():
        raise HTTPException(404, "Frontend not installed")
    return FileResponse(page)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
