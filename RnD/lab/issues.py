"""Open-issues panel (v26.2.4 follow-up): the catalogue in lab/issues.json (maintained in git, read at request time) plus the user's
close / reopen / comment state in `LAB_DIR/issues-state.json` = {id: {status, closedAt, note, noteUpdatedAt}} (outside the version wipe)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from lab import recordings

MAX_NOTE = 4000
CATALOGUE = Path(__file__).resolve().parent / "issues.json"
_lock = threading.Lock()


class IssuesError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _catalogue() -> dict:
    try:
        doc = json.loads(CATALOGUE.read_text())
    except (OSError, ValueError):
        doc = {}
    return doc if isinstance(doc, dict) else {}


def _state_path() -> Path:
    return recordings.LAB_DIR / "issues-state.json"


def _state() -> dict:
    try:
        doc = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _item(base: dict, st: dict | None) -> dict:
    st = st if isinstance(st, dict) else {}
    ustatus = st.get("status") if st.get("status") in ("open", "closed") else None
    status = ustatus or base.get("status") or "open"
    closed_at = (st.get("closedAt") if ustatus else None) or base.get("closedAt") if status == "closed" else None
    note = st.get("note") if isinstance(st.get("note"), str) else ""
    return {**base, "status": status, "closedAt": closed_at, "note": note,
            "noteUpdatedAt": st.get("noteUpdatedAt") if note else None,
            "userChanged": bool(ustatus or note.strip())}


def _items() -> tuple[dict, list[dict]]:
    cat = _catalogue()
    state = _state()
    items = [_item(b, state.get(b["id"])) for b in cat.get("items", []) if isinstance(b, dict) and "id" in b]
    return cat, items


def list_issues() -> dict:
    with _lock:
        cat, items = _items()
    groups = [g for g in cat.get("groups", []) if isinstance(g, dict) and "id" in g]
    ids = {g["id"] for g in groups}
    first_open = next((g["id"] for g in groups if g["id"] != "closed"), None)
    out = []
    for g in groups:
        if g["id"] == "closed":
            mine = [i for i in items if i["status"] == "closed"]
        else:
            # an item of an unknown group (or a reopened one from "closed") is shown in the first open group
            mine = [i for i in items if i["status"] == "open"
                    and (i.get("group") == g["id"] or (g["id"] == first_open and i.get("group") not in ids - {"closed"}))]
        out.append({"id": g["id"], "title": g.get("title", g["id"]), "items": mine,
                    "openCount": sum(1 for i in mine if i["status"] == "open")})
    return {"updatedAt": cat.get("updatedAt"), "groups": out}


def update(issue_id: str, body: dict) -> dict:
    if not isinstance(body, dict):
        raise IssuesError(422, 'Body must be {"status"?: "open"|"closed", "note"?: string}')
    status, note = body.get("status"), body.get("note")
    if status is not None and status not in ("open", "closed"):
        raise IssuesError(422, 'status must be "open" or "closed"')
    if note is not None:
        if not isinstance(note, str):
            raise IssuesError(422, "note must be a string")
        if len(note) > MAX_NOTE:
            raise IssuesError(422, f"note is over the {MAX_NOTE} character limit")
    with _lock:
        base = next((b for b in _catalogue().get("items", []) if isinstance(b, dict) and b.get("id") == issue_id), None)
        if base is None:
            raise IssuesError(404, f"Unknown issue {issue_id}")
        state = _state()
        st = dict(state.get(issue_id) or {})
        now = datetime.now(timezone.utc).isoformat()
        if status is not None:
            st["status"] = status
            st["closedAt"] = now if status == "closed" else None
        if note is not None:
            st["note"] = note
            st["noteUpdatedAt"] = now
        state[issue_id] = st
        recordings._atomic_write_json(_state_path(), state)
        return _item(base, st)


def reset(issue_id: str) -> dict:
    """Drop the user's state for one issue: it shows as the catalogue says again (used by the E2E cleanup)."""
    with _lock:
        base = next((b for b in _catalogue().get("items", []) if isinstance(b, dict) and b.get("id") == issue_id), None)
        if base is None:
            raise IssuesError(404, f"Unknown issue {issue_id}")
        state = _state()
        if state.pop(issue_id, None) is not None:
            recordings._atomic_write_json(_state_path(), state)
        return _item(base, None)


def export_items() -> list[dict]:
    with _lock:
        _, items = _items()
    return [i for i in items if i["userChanged"]]
