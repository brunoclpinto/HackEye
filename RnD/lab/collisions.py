"""Collision runs (v26.2.8): one collision result of an analysis run, kept next to the others.

`runs/<runId>/collisions/<cid>/` holds hazards.json, events.json, worldmap.npz and collision.json (the settings, the resolved
settings, the config overrides, a label, counts). Ids are `c<n>`, sequential per run, never reused (`collisionSeq` in run.json);
`collisions` in run.json lists them in creation order. The passes themselves live in analysis.py; this module is storage, config
overrides, labels, delete and the A/B comparison. Errors are CollisionError(status, message); server.py maps them to HTTP.
"""

from __future__ import annotations

import json
import re
import shutil
import threading

from engine.core import config as _config
from lab import analysis

CID_RE = re.compile(r"^c[1-9][0-9]{0,5}$")
MAX_LABEL = 60
MATCH_WINDOW_S = 1.0
FILES = ("hazards.json", "events.json", "worldmap.npz", "collision.json")

_lock = threading.RLock()


class CollisionError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def collisions_root(run_id: str):
    return analysis.run_dir(run_id) / "collisions"


def collision_dir(run_id: str, cid: str):
    return collisions_root(run_id) / cid


def ids(run: dict) -> list[str]:
    return list(run.get("collisions") or [])


def latest(run: dict) -> str | None:
    """The newest collision run that is usable (v26.2.10: not one still running, cancelled or failed)."""
    for cid in reversed(ids(run)):
        doc = read_doc(run.get("id", ""), cid)
        if doc is None or doc.get("status", "done") == "done":
            return cid
    return None


def resolve(run: dict, cid: str | None) -> str:
    """`cid` (404 when unknown) or, when none is named, the run's latest collision run (404 when it has none)."""
    if cid is None or cid == "":
        got = latest(run)
        if got is None:
            raise CollisionError(404, "This run has no collision run")
        return got
    if not CID_RE.match(cid) or cid not in ids(run):
        raise CollisionError(404, f"Unknown collision run: {cid}")
    return cid


def read_doc(run_id: str, cid: str) -> dict | None:
    """collision.json with the live job's progress; a `running` doc without a live job (the service died) reads as `error`."""
    try:
        doc = json.loads((collision_dir(run_id, cid) / "collision.json").read_text())
    except (OSError, ValueError):
        return None
    if doc.get("status") == "running":
        job = _job
        if job is not None and job.run_id == run_id and job.cid == cid:
            doc["progress"] = round(job.progress, 4)
        else:
            doc.update(status="error", error="interrupted")
    _add_effective(doc)
    return doc


def _add_effective(doc: dict) -> None:
    """v26.2.11: `objectDistanceEffective` (what the run really used: no ground ray without the horizon) in the doc and its `resolved`."""
    st = doc.get("settings") or {}
    if not st.get("objectDistance"):
        return
    import groundfuse
    eff = groundfuse.resolved_mode(st.get("objectDistance"), st.get("useHorizon", True))
    doc["objectDistanceEffective"] = eff
    if isinstance(doc.get("resolved"), dict):
        doc["resolved"]["objectDistanceEffective"] = eff


def list_docs(run_id: str) -> list[dict]:
    run = analysis.get_run(run_id) or {}
    return [d for d in (read_doc(run_id, c) for c in ids(run)) if d is not None]


def write_doc(run_id: str, cid: str, doc: dict) -> None:
    analysis._write_json(collision_dir(run_id, cid) / "collision.json", doc)


def update_doc(run_id: str, cid: str, **fields) -> dict | None:
    with _lock:
        try:
            doc = json.loads((collision_dir(run_id, cid) / "collision.json").read_text())
        except (OSError, ValueError):
            return None
        doc.update(fields)
        write_doc(run_id, cid, doc)
        return doc


# --------------------------------------------------------------------------
# Re-run job (v26.2.10): one at a time per Lab, in a thread (pure numpy, never the GPU queue)
# --------------------------------------------------------------------------

class Job:
    def __init__(self, run_id: str, cid: str):
        self.run_id, self.cid = run_id, cid
        self.cancel = threading.Event()
        self.progress = 0.0
        self.thread: threading.Thread | None = None

    def report(self, fraction: float) -> None:
        """Called between frames by the passes; raises when the job was cancelled."""
        if self.cancel.is_set():
            raise analysis._Cancelled()
        self.progress = min(max(float(fraction), 0.0), 1.0)


_job: Job | None = None


def job_active() -> bool:
    j = _job
    return j is not None and j.thread is not None and j.thread.is_alive()


def cancel_job(run_id: str | None = None, cid: str | None = None) -> bool:
    """Ask the running job to stop (between frames); True when there was one (and it is the named one)."""
    j = _job
    if not job_active() or (run_id is not None and (j.run_id, j.cid) != (run_id, cid)):
        return False
    j.cancel.set()
    return True


def start_job(run_id: str, overrides, label: str) -> dict:
    """Allocate the next id, write its collision.json as `running`, register it and run the passes in a thread.
    409 when a collision job or an analysis is running. Returns the new document."""
    global _job
    try:
        import collision
        import worldmap
    except ImportError as exc:
        raise CollisionError(503, f"collision module unavailable ({exc})") from None
    overrides = validate_overrides(overrides)
    check_overrides(overrides, collision.load_config(), worldmap.load_config())
    with _lock:
        if job_active():
            raise CollisionError(409, f"A collision re-run is already running ({_job.run_id} {_job.cid})")
        if analysis.analysis_active():
            raise CollisionError(409, "An analysis is running; wait for it to finish")
        cid = allocate(run_id)
        collision_dir(run_id, cid).mkdir(parents=True, exist_ok=True)
        doc = {"id": cid, "runId": run_id, "createdAt": analysis._now(), "collisionVersion": None, "worldmapVersion": None,
               "settings": {}, "resolved": {}, "overrides": overrides, "label": (label or "")[:MAX_LABEL],
               "elapsedSeconds": None, "counts": {}, "status": "running", "progress": 0.0, "error": None}
        write_doc(run_id, cid, doc)
        register(run_id, cid)
        job = Job(run_id, cid)
        job.thread = threading.Thread(target=_run_job, args=(job, overrides, label), name=f"collision-{run_id}-{cid}", daemon=True)
        _job = job
        job.thread.start()
    return doc


def _run_job(job: Job, overrides: dict, label: str) -> None:
    run_id, cid = job.run_id, job.cid
    try:
        analysis.collision_pass(run_id, overrides, label, job=job)
        try:      # v26.2.6: the map is always rebuilt after a collision re-run (object distance / horizon switch change it)
            analysis.worldmap_pass(run_id, cid, job=job)
        except analysis._Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - the collision result stands
            analysis._log(f"run {run_id}: worldmap refresh failed: {exc!r}")
        update_doc(run_id, cid, status="done", progress=1.0, error=None)
    except analysis._Cancelled:
        with _lock:
            shutil.rmtree(collision_dir(run_id, cid), ignore_errors=True)
            run = analysis.get_run(run_id) or {}
            analysis._update_run(run_id, collisions=[c for c in ids(run) if c != cid])
        analysis._log(f"run {run_id}: collision {cid} cancelled")
    except BaseException as exc:  # noqa: BLE001
        analysis._log(f"run {run_id}: collision {cid} FAILED: {exc!r}")
        update_doc(run_id, cid, status="error", error=getattr(exc, "message", None) or str(exc) or repr(exc))


# --------------------------------------------------------------------------
# Ids
# --------------------------------------------------------------------------

def allocate(run_id: str) -> str:
    """The next id; burnt at once (`collisionSeq`), so a failed or deleted one is never handed out again."""
    with _lock:
        run = analysis.get_run(run_id) or {}
        seq = max(int(run.get("collisionSeq") or 0), len(ids(run)))
        for c in ids(run):          # defensive: never below an existing id
            seq = max(seq, int(c[1:]))
        seq += 1
        analysis._update_run(run_id, collisionSeq=seq)
        return f"c{seq}"


def register(run_id: str, cid: str) -> None:
    with _lock:
        run = analysis.get_run(run_id) or {}
        got = ids(run)
        if cid not in got:
            got.append(cid)
        analysis._update_run(run_id, collisions=got)


# --------------------------------------------------------------------------
# Config overrides
# --------------------------------------------------------------------------

_kind = _config.value_kind
PENDING_KEYS = _config.PENDING_KEYS
_pending = _config.is_pending


def validate_overrides(overrides) -> dict:
    """Shape check: {} or {"collision": {key: value}, "worldmap": {key: value}}; returns the normalised dict (empty groups dropped)."""
    try:
        return _config.validate_overrides(overrides)
    except _config.OverrideError as e:
        raise CollisionError(422, str(e)) from e


def apply_overrides(config: dict, overrides: dict, group: str) -> dict:
    """A deep copy of `config` with the `group` overrides applied (dotted keys). Each key must exist and keep its JSON type;
    else CollisionError 422 naming the key. The loaded config is never mutated."""
    try:
        return _config.apply_overrides(config, overrides, group)
    except _config.OverrideError as e:
        raise CollisionError(422, str(e)) from e


def check_overrides(overrides: dict, collision_cfg: dict, worldmap_cfg: dict) -> None:
    """Validate against the loaded configs before any work starts."""
    try:
        _config.check_overrides(overrides, collision_cfg, worldmap_cfg)
    except _config.OverrideError as e:
        raise CollisionError(422, str(e)) from e


# --------------------------------------------------------------------------
# Label, delete
# --------------------------------------------------------------------------

def set_label(run_id: str, cid: str, label) -> dict:
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
        run = analysis.get_run(run_id) or {}
        got = ids(run)
        if cid not in got:
            raise CollisionError(404, f"Unknown collision run: {cid}")
        doc = read_doc(run_id, cid) or {}
        if doc.get("status") == "running":
            raise CollisionError(409, f"{cid} is still running; cancel it first")
        if len(got) <= 1 and doc.get("status") != "error":
            raise CollisionError(409, f"{cid} is the only collision run of this run; it cannot be deleted")
        if review_count:
            raise CollisionError(409, f"{cid} has {review_count} review{'s' if review_count != 1 else ''} (verdicts / notes); "
                                      "delete them first")
        shutil.rmtree(collision_dir(run_id, cid), ignore_errors=True)
        analysis._update_run(run_id, collisions=[c for c in got if c != cid])


# --------------------------------------------------------------------------
# Compare A / B
# --------------------------------------------------------------------------

def _flatten(prefix: str, node, out: dict) -> None:
    if isinstance(node, dict) and node:
        for k, v in node.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    else:
        out[prefix] = node


def _settings_diff(a: dict, b: dict) -> list[dict]:
    fa: dict = {}
    fb: dict = {}
    for name in ("settings", "resolved", "overrides"):
        _flatten(name, a.get(name) or {}, fa)
        _flatten(name, b.get(name) or {}, fb)
    rows = []
    for key in sorted(set(fa) | set(fb)):
        va, vb = fa.get(key), fb.get(key)
        if json.dumps(va, sort_keys=True) != json.dumps(vb, sort_keys=True):
            rows.append({"key": key, "a": va, "b": vb})
    return rows


def _events(run_id: str, cid: str) -> list[dict]:
    try:
        raw = json.loads((collision_dir(run_id, cid) / "events.json").read_text()).get("events", [])
    except (OSError, ValueError):
        return []
    out = []
    for e in raw:
        if e.get("type") not in ("speech", "beeps"):
            continue              # tones are left out (the fixture comparisons do the same)
        item = {"t": e["t"], "type": e["type"], "text": e.get("text", "")}
        if e["type"] == "beeps":
            item["kind"], item["clock"] = e.get("kind"), e.get("clock")
        out.append(item)
    return out


def _same(x: dict, y: dict) -> bool:
    if x["type"] == "beeps":
        return x.get("kind") == y.get("kind") and x.get("clock") == y.get("clock")
    return x["text"] == y["text"]


def match_events(ea: list[dict], eb: list[dict]) -> dict:
    """Greedy, nearest first, each event used once: same type + same text (beeps: kind + clock) within 1 s = same; else the same
    type within 1 s with a different text = changed; the rest are only-A / only-B."""
    pairs = []
    for i, x in enumerate(ea):
        for j, y in enumerate(eb):
            dt = abs(x["t"] - y["t"])
            if x["type"] == y["type"] and dt <= MATCH_WINDOW_S:
                pairs.append((0 if _same(x, y) else 1, dt, i, j))
    pairs.sort()
    used_a: set[int] = set()
    used_b: set[int] = set()
    same = 0
    changed = []
    for cls, _dt, i, j in pairs:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        if cls == 0:
            same += 1
        else:
            changed.append({"t": ea[i]["t"], "type": ea[i]["type"], "a": ea[i], "b": eb[j]})
    changed.sort(key=lambda c: c["t"])
    return {"same": same, "changed": changed,
            "onlyA": [e for i, e in enumerate(ea) if i not in used_a],
            "onlyB": [e for j, e in enumerate(eb) if j not in used_b]}


def compare(run_id: str, a: str, b: str) -> dict:
    run = analysis.get_run(run_id) or {}
    a, b = resolve(run, a), resolve(run, b)
    da, db = read_doc(run_id, a) or {}, read_doc(run_id, b) or {}
    return {"a": a, "b": b, "settings": _settings_diff(da, db),
            "counts": {"a": da.get("counts") or {}, "b": db.get("counts") or {}},
            "events": match_events(_events(run_id, a), _events(run_id, b))}
