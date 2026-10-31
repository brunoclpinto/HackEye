"""Collision runs (v26.2.8): one collision result of an analysis run, kept next to the others.

`runs/<runId>/collisions/<cid>/` holds hazards.json, events.json, worldmap.npz and collision.json (the settings, the resolved
settings, the config overrides, a label, counts). Ids are `c<n>`, sequential per run, never reused (`collisionSeq` in run.json);
`collisions` in run.json lists them in creation order. The passes themselves live in analysis.py; this module is storage, config
overrides, labels, delete and the A/B comparison. Errors are CollisionError(status, message); server.py maps them to HTTP.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import threading

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
    got = ids(run)
    return got[-1] if got else None


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
    try:
        return json.loads((collision_dir(run_id, cid) / "collision.json").read_text())
    except (OSError, ValueError):
        return None


def list_docs(run_id: str) -> list[dict]:
    run = analysis.get_run(run_id) or {}
    return [d for d in (read_doc(run_id, c) for c in ids(run)) if d is not None]


def write_doc(run_id: str, cid: str, doc: dict) -> None:
    analysis._write_json(collision_dir(run_id, cid) / "collision.json", doc)


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

def _kind(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return "null"


def validate_overrides(overrides) -> dict:
    """Shape check: {} or {"collision": {key: value}, "worldmap": {key: value}}; returns the normalised dict (empty groups dropped)."""
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise CollisionError(422, "overrides must be an object")
    out: dict = {}
    for group, items in overrides.items():
        if group not in ("collision", "worldmap"):
            raise CollisionError(422, f"overrides: unknown config {group!r} (expected collision or worldmap)")
        if not isinstance(items, dict):
            raise CollisionError(422, f"overrides.{group} must be an object of dotted keys")
        if items:
            out[group] = dict(items)
    return out


def apply_overrides(config: dict, overrides: dict, group: str) -> dict:
    """A deep copy of `config` with the `group` overrides applied (dotted keys). Each key must exist and keep its JSON type;
    else CollisionError 422 naming the key. The loaded config is never mutated."""
    out = copy.deepcopy(config)
    for key, value in (overrides.get(group) or {}).items():
        if not isinstance(key, str) or not key:
            raise CollisionError(422, f"overrides.{group}: bad key {key!r}")
        parts = key.split(".")
        node = out
        for p in parts[:-1]:
            if not isinstance(node, dict) or p not in node:
                raise CollisionError(422, f"overrides.{group}: unknown key {key!r}")
            node = node[p]
        if not isinstance(node, dict) or parts[-1] not in node:
            raise CollisionError(422, f"overrides.{group}: unknown key {key!r}")
        old = node[parts[-1]]
        if _kind(old) == "object":
            raise CollisionError(422, f"overrides.{group}: {key!r} is a section; name a value inside it")
        if old is not None and _kind(value) != _kind(old):
            raise CollisionError(422, f"overrides.{group}: {key!r} must be a {_kind(old)}, not a {_kind(value)}")
        node[parts[-1]] = value
    return out


def check_overrides(overrides: dict, collision_cfg: dict, worldmap_cfg: dict) -> None:
    """Validate against the loaded configs before any work starts."""
    apply_overrides(collision_cfg, overrides, "collision")
    apply_overrides(worldmap_cfg, overrides, "worldmap")


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
        if len(got) <= 1:
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
