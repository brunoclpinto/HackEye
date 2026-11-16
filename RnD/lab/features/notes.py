"""The Lab-wide notes box (v26.2.4 follow-up): one freeform document for reviews, remarks and fix requests.

`LAB_DIR/notes.json` = {"text", "updatedAt"}. It sits outside runs/ and reviews/, so version wipes leave it alone.
Before each save the
previous file is copied to `notes.prev.json` (one generation). A save carries `baseUpdatedAt`; when it differs from
the stored value the
note was changed elsewhere (another tab, the phone) and the save is refused with 409 unless forced.
"""

from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from lab.store import recordings
from lab.store.util import _atomic_write_json

if TYPE_CHECKING:
    from pathlib import Path

MAX_CHARS = 100_000
_lock = threading.Lock()


class NotesError(Exception):
    def __init__(self, status: int, message: str, current: dict[str, Any] | None = None):
        super().__init__(message)
        self.status, self.message, self.current = status, message, current


def _path() -> Path:
    return recordings.LAB_DIR / "notes.json"  # type: ignore[no-any-return]  # lab.store.recordings is untyped


def _read() -> dict[str, Any]:
    try:
        doc = json.loads(_path().read_text())
    except (OSError, ValueError):
        return {"text": "", "updatedAt": None}
    if not isinstance(doc, dict) or not isinstance(doc.get("text"), str):
        return {"text": "", "updatedAt": None}
    return {"text": doc["text"], "updatedAt": doc.get("updatedAt")}


def get() -> dict[str, Any]:
    with _lock:
        return _read()


def put(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise NotesError(422, 'Body must be {"text": string, "baseUpdatedAt": string|null}')
    text = body.get("text")
    if not isinstance(text, str):
        raise NotesError(422, "text must be a string")
    if len(text) > MAX_CHARS:
        raise NotesError(422, f"text is over the {MAX_CHARS} character limit")
    base = body.get("baseUpdatedAt")
    if base is not None and not isinstance(base, str):
        raise NotesError(422, "baseUpdatedAt must be a string or null")
    with _lock:
        cur = _read()
        if body.get("force") is not True and base != cur["updatedAt"]:
            raise NotesError(409, "The notes were changed elsewhere since you loaded them", cur)
        path = _path()
        if path.exists():
            try:  # noqa: SIM105
                shutil.copyfile(path, path.with_name("notes.prev.json"))
            except OSError:
                pass
        doc = {"text": text, "updatedAt": datetime.now(timezone.utc).isoformat()}  # noqa: UP017
        _atomic_write_json(path, doc)
        return doc
