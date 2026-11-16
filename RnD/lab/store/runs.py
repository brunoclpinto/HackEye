"""Run docs on disk (`LAB_DIR/runs/<id>/run.json`) and the in-flight registry (moved verbatim from lab/analysis.py).

`LAB_DIR` is this module's own global (`analysis.LAB_DIR` forwards to it). `_active` / `_state_lock` are the registry of
queued and running runs and the lock that guards it and the job queue state.
"""

from __future__ import annotations

import json
import shutil
import threading
from typing import TYPE_CHECKING, Any

from lab.store import constants, recordings
from lab.store.util import _write_json

if TYPE_CHECKING:
    from pathlib import Path

LAB_DIR = recordings.LAB_DIR

ACTIVE_STATUSES = ("queued", "running")


def run_dir(run_id: str) -> Path:
    return LAB_DIR / "runs" / run_id


_state_lock = threading.Lock()
_active: dict[str, dict[str, Any]] = {}  # run_id -> live run.json (queued/running)


def get_run(run_id: str) -> dict[str, Any] | None:
    with _state_lock:
        if run_id in _active:
            return dict(_active[run_id])
    try:
        doc: dict[str, Any] = json.loads((run_dir(run_id) / "run.json").read_text())
        return doc
    except (OSError, ValueError):
        return None


def list_runs(recording: str | None) -> list[dict[str, Any]]:
    runs = []
    root = LAB_DIR / "runs"
    if root.is_dir():
        for d in root.iterdir():
            if constants.RUN_ID_RE.match(d.name):
                doc = get_run(d.name)
                if doc and (recording is None or doc["request"]["recording"] == recording):
                    runs.append(doc)
    runs.sort(key=lambda r: r["createdAt"], reverse=True)
    return runs


def _update_run(run_id: str, persist: bool = True, **fields: Any) -> dict[str, Any]:
    with _state_lock:
        doc = _active.get(run_id)
        if doc is None:
            doc = json.loads((run_dir(run_id) / "run.json").read_text())
        doc.update(fields)
        if run_id in _active:
            _active[run_id] = doc
        snapshot = dict(doc)
    if persist:
        _write_json(run_dir(run_id) / "run.json", snapshot)
    return snapshot


def find_active_for_recording(active: dict[str, dict[str, Any]], rec_id: str) -> dict[str, Any] | None:
    """The queued/running run doc of `rec_id` among `active`, if any (CONTRACTS 11a)."""
    for doc in active.values():
        if doc["request"]["recording"] == rec_id and doc["status"] in ACTIVE_STATUSES:
            return doc
    return None


def _conflict_message(doc: dict[str, Any]) -> str:
    return (
        f"Analysis already running for {doc['request']['recording']} "
        f"(run {doc['id']}, {round((doc.get('progress') or 0) * 100)}%)"
    )


_PARTIAL_OUTPUTS = ("grids.npz", "motion.npz", "depth.npz")


def _remove_partial_outputs(run_id: str) -> None:
    out = run_dir(run_id)
    shutil.rmtree(out / "masks", ignore_errors=True)
    shutil.rmtree(out / "collisions", ignore_errors=True)
    for name in _PARTIAL_OUTPUTS:
        try:  # noqa: SIM105
            (out / name).unlink()
        except FileNotFoundError:
            pass
