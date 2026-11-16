"""Collision-run A/B comparison (v26.3.0 p5-05): settings diff and greedy event matching, moved from lab/collisions.py.

Pure apart from reading the two collision docs and their events.json through `lab.store`.
"""

from __future__ import annotations

import json
from typing import Any

from lab.store import collision_docs, runs


def _flatten(prefix: str, node: Any, out: dict[str, Any]) -> None:
    if isinstance(node, dict) and node:
        for k, v in node.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    else:
        out[prefix] = node


def _settings_diff(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    fa: dict[str, Any] = {}
    fb: dict[str, Any] = {}
    for name in ("settings", "resolved", "overrides"):
        _flatten(name, a.get(name) or {}, fa)
        _flatten(name, b.get(name) or {}, fb)
    rows = []
    for key in sorted(set(fa) | set(fb)):
        va, vb = fa.get(key), fb.get(key)
        if json.dumps(va, sort_keys=True) != json.dumps(vb, sort_keys=True):
            rows.append({"key": key, "a": va, "b": vb})
    return rows


def _events(run_id: str, cid: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads((collision_docs.collision_dir(run_id, cid) / "events.json").read_text()).get("events", [])
    except (OSError, ValueError):
        return []
    out = []
    for e in raw:
        if e.get("type") not in ("speech", "beeps"):
            continue  # tones are left out (the fixture comparisons do the same)
        item = {"t": e["t"], "type": e["type"], "text": e.get("text", "")}
        if e["type"] == "beeps":
            item["kind"], item["clock"] = e.get("kind"), e.get("clock")
        out.append(item)
    return out


def _same(x: dict[str, Any], y: dict[str, Any]) -> bool:
    if x["type"] == "beeps":
        return x.get("kind") == y.get("kind") and x.get("clock") == y.get("clock")
    return x["text"] == y["text"]  # type: ignore[no-any-return]  # values come from json docs


def match_events(ea: list[dict[str, Any]], eb: list[dict[str, Any]]) -> dict[str, Any]:
    """Greedy, nearest first, each event used once: same type + same text (beeps: kind + clock) within 1 s = same;
    else the same
    type within 1 s with a different text = changed; the rest are only-A / only-B."""
    pairs = []
    for i, x in enumerate(ea):
        for j, y in enumerate(eb):
            dt = abs(x["t"] - y["t"])
            if x["type"] == y["type"] and dt <= collision_docs.MATCH_WINDOW_S:
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
    return {
        "same": same,
        "changed": changed,
        "onlyA": [e for i, e in enumerate(ea) if i not in used_a],
        "onlyB": [e for j, e in enumerate(eb) if j not in used_b],
    }


def compare(run_id: str, a: str, b: str) -> dict[str, Any]:
    run = runs.get_run(run_id) or {}
    a, b = collision_docs.resolve(run, a), collision_docs.resolve(run, b)
    da, db = collision_docs.read_doc(run_id, a) or {}, collision_docs.read_doc(run_id, b) or {}
    return {
        "a": a,
        "b": b,
        "settings": _settings_diff(da, db),
        "counts": {"a": da.get("counts") or {}, "b": db.get("counts") or {}},
        "events": match_events(_events(run_id, a), _events(run_id, b)),
    }
