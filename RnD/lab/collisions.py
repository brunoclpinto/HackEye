"""Collision runs (v26.2.8): one collision result of an analysis run, kept next to the others.

`runs/<runId>/collisions/<cid>/` holds hazards.json, events.json, worldmap.npz and collision.json (the settings, the resolved
settings, the config overrides, a label, counts). Ids are `c<n>`, sequential per run, never reused (`collisionSeq` in run.json);
`collisions` in run.json lists them in creation order. The passes themselves live in analysis.py; this module is storage, config
overrides, labels, delete and the A/B comparison. Errors are CollisionError(status, message); server.py maps them to HTTP.
"""

from __future__ import annotations

import json

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
    # v26.3.0 p5-03: the re-run job moved to lab.jobs.collision (audit 7.5)
    **dict.fromkeys(("Job", "_job", "job_active", "cancel_job", "start_job", "_run_job"), "lab.jobs.collision"),
})


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
