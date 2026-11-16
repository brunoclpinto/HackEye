"""HackEye Lab web server (REST API of CONTRACTS §8 + static frontend).

Thin layer: discovery and proxies live in recordings.py, segmentation runs
and the GPU queue in analysis.py, collision logic in src/collision.py.
Endpoints are plain `def` (not async) so FastAPI runs them in its threadpool;
none of them block for long except the collision re-run, which is pure numpy.
"""

from __future__ import annotations

import sys
from collections import OrderedDict  # noqa: F401  (tests and tools reach `server.OrderedDict`)
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from lab import analysis, recordings, versioning
from lab._forward import install
from lab.api import collisions, config, display, issues, notes, rundata, runs, sounds, system, worldmap
from lab.api import recordings as recordings_api
from lab.api import reviews as reviews_api

STATIC_DIR = system.STATIC_DIR
STATIC_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # CONTRACTS section 11: version policy runs before serving (and before the
    # lazily-started GPU worker can touch runs/).
    system._last_wipe = versioning.apply_version_policy(recordings.LAB_DIR, system.VERSION_FILE)

    def _remember(result: dict) -> None:
        system._last_wipe = result

    watcher = versioning.VersionWatcher(recordings.LAB_DIR, system.VERSION_FILE, analysis, on_result=_remember)
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


# v26.3.0 p5-06: the endpoints live in lab.api.<router>; the routers are included in the order the routes were
# registered here (FastAPI matches in order). `include_router` of this FastAPI version wraps a router in a lazy
# `_IncludedRouter`; `app.routes` must stay the flat list of the routes as before, so the routes are appended
# directly. The caches and helpers moved with their routers and stay reachable (and patchable) on this module.
for _router in (
    system.router,
    recordings_api.router,
    config.router,
    runs.router,
    collisions.router,
    worldmap.router,
    rundata.router,
    sounds.router,
    display.router,
    notes.router,
    issues.router,
    reviews_api.router,
    system.frontend_router,
):
    app.router.routes.extend(_router.routes)

install(
    __name__,
    {
        "VERSION_FILE": "lab.api.system",
        "_last_wipe": "lab.api.system",
        "_collision": "lab.api.deps",
        "_recording": "lab.api.deps",
        "_run": "lab.api.deps",
        "_wm_cache": "lab.api.worldmap",
        "_wm_lock": "lab.api.worldmap",
        "_hz_cache": "lab.api.rundata",
        "_hz_lock": "lab.api.rundata",
        "_grid_cache": "lab.api.rundata",
        "_grid_lock": "lab.api.rundata",
        "_depth_cache": "lab.api.rundata",
        "_depth_lock": "lab.api.rundata",
    },
)


class _RevalidatingStaticFiles(StaticFiles):
    """Static files are revalidated on every load (ETag keeps it cheap): no heuristic caching of stale app.js / js/*.js."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", _RevalidatingStaticFiles(directory=STATIC_DIR), name="static")
