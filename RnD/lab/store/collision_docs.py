"""Collision-run docs on disk (moved verbatim from lab/collisions.py, v26.2.8).

`runs/<runId>/collisions/<cid>/` holds hazards.json, events.json, worldmap.npz and collision.json (the settings, the
resolved settings, the config overrides, a label, counts). Ids are `c<n>`, sequential per run, never reused
(`collisionSeq` in run.json); `collisions` in run.json lists them in creation order. Errors are
CollisionError(status, message); server.py maps them to HTTP.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from typing import TYPE_CHECKING, Any

from lab.store import runs
from lab.store.errors import CollisionError
from lab.store.util import _write_json

if TYPE_CHECKING:
    from pathlib import Path

CID_RE = re.compile(r"^c[1-9][0-9]{0,5}$")
MAX_LABEL = 60
MATCH_WINDOW_S = 1.0
FILES = ("hazards.json", "events.json", "worldmap.npz", "collision.json")

_lock = threading.RLock()


def collisions_root(run_id: str) -> Path:
    return runs.run_dir(run_id) / "collisions"


def collision_dir(run_id: str, cid: str) -> Path:
    return collisions_root(run_id) / cid


def ids(run: dict[str, Any]) -> list[str]:
    return list(run.get("collisions") or [])


def latest(run: dict[str, Any]) -> str | None:
    """The newest collision run that is usable (v26.2.10: not one still running, cancelled or failed)."""
    for cid in reversed(ids(run)):
        doc = read_doc(run.get("id", ""), cid)
        if doc is None or doc.get("status", "done") == "done":
            return cid
    return None


def resolve(run: dict[str, Any], cid: str | None) -> str:
    """`cid` (404 when unknown) or, when none is named, the run's latest collision run (404 when it has none)."""
    if cid is None or cid == "":
        got = latest(run)
        if got is None:
            raise CollisionError(404, "This run has no collision run")
        return got
    if not CID_RE.match(cid) or cid not in ids(run):
        raise CollisionError(404, f"Unknown collision run: {cid}")
    return cid


def read_doc(run_id: str, cid: str) -> dict[str, Any] | None:
    """collision.json with the live job's progress; a `running` doc without a live job (the service died) reads as
    `error`."""
    try:
        doc: dict[str, Any] = json.loads((collision_dir(run_id, cid) / "collision.json").read_text())
    except (OSError, ValueError):
        return None
    if doc.get("status") == "running":
        from lab import collisions  # the live job is a global of the flat module until p5-03 moves it to lab.jobs

        job = collisions._job
        if job is not None and job.run_id == run_id and job.cid == cid:
            doc["progress"] = round(job.progress, 4)
        else:
            doc.update(status="error", error="interrupted")
    _add_effective(doc)
    return doc


def _add_effective(doc: dict[str, Any]) -> None:
    """v26.2.11: `objectDistanceEffective` (what the run really used: no ground ray without the horizon) in the doc and
    its `resolved`."""
    st = doc.get("settings") or {}
    if not st.get("objectDistance"):
        return
    import groundfuse

    eff = groundfuse.resolved_mode(st.get("objectDistance"), st.get("useHorizon", True))
    doc["objectDistanceEffective"] = eff
    if isinstance(doc.get("resolved"), dict):
        doc["resolved"]["objectDistanceEffective"] = eff


def list_docs(run_id: str) -> list[dict[str, Any]]:
    run = runs.get_run(run_id) or {}
    return [d for d in (read_doc(run_id, c) for c in ids(run)) if d is not None]


def write_doc(run_id: str, cid: str, doc: dict[str, Any]) -> None:
    _write_json(collision_dir(run_id, cid) / "collision.json", doc)


def update_doc(run_id: str, cid: str, **fields: Any) -> dict[str, Any] | None:
    with _lock:
        try:
            doc: dict[str, Any] = json.loads((collision_dir(run_id, cid) / "collision.json").read_text())
        except (OSError, ValueError):
            return None
        doc.update(fields)
        write_doc(run_id, cid, doc)
        return doc


# --------------------------------------------------------------------------
# Ids
# --------------------------------------------------------------------------


def allocate(run_id: str) -> str:
    """The next id; burnt at once (`collisionSeq`), so a failed or deleted one is never handed out again."""
    with _lock:
        run = runs.get_run(run_id) or {}
        seq = max(int(run.get("collisionSeq") or 0), len(ids(run)))
        for c in ids(run):  # defensive: never below an existing id
            seq = max(seq, int(c[1:]))
        seq += 1
        runs._update_run(run_id, collisionSeq=seq)
        return f"c{seq}"


def register(run_id: str, cid: str) -> None:
    with _lock:
        run = runs.get_run(run_id) or {}
        got = ids(run)
        if cid not in got:
            got.append(cid)
        runs._update_run(run_id, collisions=got)


# --------------------------------------------------------------------------
# Label, delete
# --------------------------------------------------------------------------


def set_label(run_id: str, cid: str, label: object) -> dict[str, Any]:
    if not isinstance(label, str):
        raise CollisionError(422, "label must be a string")
    label = label.strip()
    if len(label) > MAX_LABEL:
        raise CollisionError(422, f"label must be at most {MAX_LABEL} characters")
    with _lock:
        doc = read_doc(run_id, cid)
        if doc is None:
            raise CollisionError(404, f"Unknown collision run: {cid}")
        doc["label"] = label
        write_doc(run_id, cid, doc)
    return doc


def delete(run_id: str, cid: str, review_count: int) -> None:
    with _lock:
        run = runs.get_run(run_id) or {}
        got = ids(run)
        if cid not in got:
            raise CollisionError(404, f"Unknown collision run: {cid}")
        doc = read_doc(run_id, cid) or {}
        if doc.get("status") == "running":
            raise CollisionError(409, f"{cid} is still running; cancel it first")
        if len(got) <= 1 and doc.get("status") != "error":
            raise CollisionError(409, f"{cid} is the only collision run of this run; it cannot be deleted")
        if review_count:
            raise CollisionError(
                409,
                f"{cid} has {review_count} review{'s' if review_count != 1 else ''} (verdicts / notes); "
                "delete them first",
            )
        shutil.rmtree(collision_dir(run_id, cid), ignore_errors=True)
        runs._update_run(run_id, collisions=[c for c in got if c != cid])
