"""System router: version, browser diagnostics log, the frontend index page."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from lab import recordings, versioning

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"
_last_wipe: dict[str, Any] = {}

router = APIRouter()


frontend_router = APIRouter()


@router.get("/api/version")
def api_version() -> dict[str, Any]:
    try:
        marker = versioning.read_marker(recordings.LAB_DIR)
    except ValueError:
        marker = None
    return {
        "version": versioning.read_version(VERSION_FILE),
        "since": marker.get("since") if marker else None,
        "lastWipe": _last_wipe,
    }


# Browser diagnostics (CONTRACTS 12.2): the page posts its speech/audio events here so they can be read from the host.
CLIENT_LOG_MAX_BYTES = 5 * 1024 * 1024
CLIENT_LOG_MAX_ENTRIES = 200
CLIENT_LOG_MAX_BODY = 256 * 1024
_client_log_lock = threading.Lock()


def _client_log_path() -> Path:
    return recordings.LAB_DIR / "client-log.jsonl"  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.post("/api/client-log")
async def post_client_log(request: Request) -> dict[str, Any]:
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
        json.dumps({"server": stamp, "ua": ua, **(e if isinstance(e, dict) else {"value": e})}, ensure_ascii=False)
        + "\n"
        for e in entries[:CLIENT_LOG_MAX_ENTRIES]
    )
    path = _client_log_path()
    with _client_log_lock:
        try:
            if path.exists() and path.stat().st_size + len(lines) > CLIENT_LOG_MAX_BYTES:
                path.replace(path.with_name(path.name + ".1"))  # one rotated generation: <= ~10 MB in all
            with path.open("a", encoding="utf-8") as f:
                f.write(lines)
        except OSError as e:
            raise HTTPException(500, f"client log not writable: {e}") from None
    return {"ok": True, "n": min(len(entries), CLIENT_LOG_MAX_ENTRIES)}


@frontend_router.get("/")
def index() -> FileResponse:
    page = STATIC_DIR / "index.html"
    if not page.exists():
        raise HTTPException(404, "Frontend not installed")
    return FileResponse(page, headers={"Cache-Control": "no-cache"})
