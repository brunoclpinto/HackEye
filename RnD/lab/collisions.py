"""Collision runs (v26.2.8): one collision result of an analysis run, kept next to the others.

`runs/<runId>/collisions/<cid>/` holds hazards.json, events.json, worldmap.npz and collision.json (the settings, the resolved
settings, the config overrides, a label, counts). Ids are `c<n>`, sequential per run, never reused (`collisionSeq` in run.json);
`collisions` in run.json lists them in creation order. The passes themselves live in analysis.py; this module is storage, config
overrides, labels, delete and the A/B comparison. Errors are CollisionError(status, message); server.py maps them to HTTP.
"""

from __future__ import annotations

import json
import shutil
import threading

from engine.core import config as _config
from lab import analysis
from lab._forward import install
from lab.store import collision_docs as cdocs
from lab.store import errors

# v26.3.0 p5-02: the collision docs moved to lab.store (audit 7.5); every moved name stays reachable here as a forward to its home.
install(__name__, {
    **dict.fromkeys(
        ("CID_RE", "MAX_LABEL", "MATCH_WINDOW_S", "FILES", "_lock", "collisions_root", "collision_dir", "ids", "latest", "resolve",
         "read_doc", "_add_effective", "list_docs", "write_doc", "update_doc", "allocate", "register", "set_label", "delete"),
        "lab.store.collision_docs"),
    "CollisionError": "lab.store.errors",
})


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
        raise errors.CollisionError(503, f"collision module unavailable ({exc})") from None
    overrides = validate_overrides(overrides)
    check_overrides(overrides, collision.load_config(), worldmap.load_config())
    with cdocs._lock:
        if job_active():
            raise errors.CollisionError(409, f"A collision re-run is already running ({_job.run_id} {_job.cid})")
        if analysis.analysis_active():
            raise errors.CollisionError(409, "An analysis is running; wait for it to finish")
        cid = cdocs.allocate(run_id)
        cdocs.collision_dir(run_id, cid).mkdir(parents=True, exist_ok=True)
        doc = {"id": cid, "runId": run_id, "createdAt": analysis._now(), "collisionVersion": None, "worldmapVersion": None,
               "settings": {}, "resolved": {}, "overrides": overrides, "label": (label or "")[:cdocs.MAX_LABEL],
               "elapsedSeconds": None, "counts": {}, "status": "running", "progress": 0.0, "error": None}
        cdocs.write_doc(run_id, cid, doc)
        cdocs.register(run_id, cid)
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
        cdocs.update_doc(run_id, cid, status="done", progress=1.0, error=None)
    except analysis._Cancelled:
        with cdocs._lock:
            shutil.rmtree(cdocs.collision_dir(run_id, cid), ignore_errors=True)
            run = analysis.get_run(run_id) or {}
            analysis._update_run(run_id, collisions=[c for c in cdocs.ids(run) if c != cid])
        analysis._log(f"run {run_id}: collision {cid} cancelled")
    except BaseException as exc:  # noqa: BLE001
        analysis._log(f"run {run_id}: collision {cid} FAILED: {exc!r}")
        cdocs.update_doc(run_id, cid, status="error", error=getattr(exc, "message", None) or str(exc) or repr(exc))




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
        raise errors.CollisionError(422, str(e)) from e


def apply_overrides(config: dict, overrides: dict, group: str) -> dict:
    """A deep copy of `config` with the `group` overrides applied (dotted keys). Each key must exist and keep its JSON type;
    else CollisionError 422 naming the key. The loaded config is never mutated."""
    try:
        return _config.apply_overrides(config, overrides, group)
    except _config.OverrideError as e:
        raise errors.CollisionError(422, str(e)) from e


def check_overrides(overrides: dict, collision_cfg: dict, worldmap_cfg: dict) -> None:
    """Validate against the loaded configs before any work starts."""
    try:
        _config.check_overrides(overrides, collision_cfg, worldmap_cfg)
    except _config.OverrideError as e:
        raise errors.CollisionError(422, str(e)) from e




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
        raw = json.loads((cdocs.collision_dir(run_id, cid) / "events.json").read_text()).get("events", [])
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
            if x["type"] == y["type"] and dt <= cdocs.MATCH_WINDOW_S:
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
    a, b = cdocs.resolve(run, a), cdocs.resolve(run, b)
    da, db = cdocs.read_doc(run_id, a) or {}, cdocs.read_doc(run_id, b) or {}
    return {"a": a, "b": b, "settings": _settings_diff(da, db),
            "counts": {"a": da.get("counts") or {}, "b": db.get("counts") or {}},
            "events": match_events(_events(run_id, a), _events(run_id, b))}
