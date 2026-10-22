"""Notification reviews: the user's ground truth about what the Lab should say or beep (§10, §14).

Reviews belong to the *recording*, not to a run: what should be spoken at a
given recording time stays true across re-analysis and new collision
versions. Each verdict snapshots the notification (speech phrase or beeps episode) it judged plus the run and
collision version it came from; `added` annotations are phrases the system
missed. One JSON file per recording (`LAB_DIR/reviews/<recId>.json`), written
atomically. A process-wide lock serialises read-modify-write (the endpoints
run in a threadpool); files are small, so one lock is enough.

Validation raises ReviewError(status, message); server.py maps it to HTTP.
The export joins each annotation with the hazards/events of the run it was
made against (nearest analysed frame, non-"none" items, ego, surface, nearby
speech) so the file can be analysed offline without the run directories.
"""

from __future__ import annotations

import bisect
import json
import secrets
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from lab import analysis
from lab.recordings import LAB_DIR, _atomic_write_json

VERDICTS = ("correct", "incorrect", "remove")
ROLES = ("context", "surface", "feature", "danger", "final", "other")
KINDS = ("verdict", "added")
MAX_NOTE = 2000
MAX_TEXT = 300
NEARBY_SECONDS = 3.0
TYPES = ("speech", "beeps")
_EVENT_KEYS = ("t", "text", "role", "trackId", "urgency", "clock", "type", "tEnd", "label", "minSteps")

_lock = threading.Lock()


class ReviewError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _log(msg: str) -> None:
    print(f"[reviews] {msg}", file=sys.stderr, flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path(rec_id: str) -> Path:
    return LAB_DIR / "reviews" / f"{rec_id}.json"


def _load(rec_id: str) -> dict:
    try:
        doc = json.loads(_path(rec_id).read_text())
        if isinstance(doc, dict) and isinstance(doc.get("annotations"), list):
            return doc
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        _log(f"{rec_id}: unreadable review file ({exc}); treating as empty")
    return {"recording": rec_id, "annotations": []}


def _save(rec_id: str, doc: dict) -> None:
    if doc["annotations"]:
        _atomic_write_json(_path(rec_id), doc)
    else:
        _path(rec_id).unlink(missing_ok=True)


def _sorted(annotations: list[dict]) -> list[dict]:
    return sorted(annotations, key=lambda a: (a.get("t", 0.0), a.get("createdAt", "")))


def match_key(ann: dict) -> tuple:
    ev = ann["event"]
    return (ann.get("runId"), ann.get("collisionVersion"), round(float(ev["t"]), 3), ev["text"])


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------

def _bad(msg: str) -> ReviewError:
    return ReviewError(422, msg)


def _check_note(v) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise _bad("note must be a string")
    if len(v) > MAX_NOTE:
        raise _bad(f"note must be at most {MAX_NOTE} characters")
    return v


def _check_verdict(v) -> str:
    if v not in VERDICTS:
        raise _bad(f"verdict must be one of {list(VERDICTS)}")
    return v


def _check_role(v) -> str:
    if v not in ROLES:
        raise _bad(f"role must be one of {list(ROLES)}")
    return v


def _check_t(v, duration: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        raise _bad("t must be a number")
    if not 0 <= v <= duration:
        raise _bad(f"t must be within 0..{duration:g} (recording duration)")
    return float(v)


def _check_type(v) -> str:
    if v not in TYPES:
        raise _bad(f"type must be one of {list(TYPES)}")
    return v


def _check_t_end(v, t: float, duration: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        raise _bad("tEnd must be a number")
    if not t < v <= duration:
        raise _bad(f"tEnd must be greater than t and at most {duration:g} (recording duration)")
    return float(v)


def _check_text(v) -> str:
    if not isinstance(v, str) or not v.strip():
        raise _bad("text is required")
    if len(v) > MAX_TEXT:
        raise _bad(f"text must be at most {MAX_TEXT} characters")
    return v.strip()


def _check_run(body: dict) -> dict | None:
    """The run named by body['runId'] (404 if unknown), or None if not given."""
    run_id = body.get("runId")
    if run_id is None:
        return None
    run = analysis.get_run(run_id) if isinstance(run_id, str) and analysis.RUN_ID_RE.match(run_id) else None
    if run is None:
        raise ReviewError(404, f"Unknown run: {run_id}")
    return run


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------

def list_annotations(rec_id: str) -> dict:
    with _lock:
        doc = _load(rec_id)
    return {"recording": rec_id, "annotations": _sorted(doc["annotations"])}


def create(rec_id: str, duration: float, body: dict) -> dict:
    kind = body.get("kind")
    if kind not in KINDS:
        raise _bad(f"kind must be one of {list(KINDS)}")
    run = _check_run(body)
    ann: dict = {"id": secrets.token_hex(4), "kind": kind}

    if kind == "verdict":
        ann["verdict"] = _check_verdict(body.get("verdict"))
        ann["note"] = _check_note(body.get("note"))
        ev = body.get("event")
        if not isinstance(ev, dict):
            raise _bad("event is required for a verdict")
        if run is None:
            raise _bad("runId is required for a verdict")
        ev_t = _check_t(ev.get("t"), duration)
        ev_text = ev.get("text")
        if not isinstance(ev_text, str) or not ev_text:
            raise _bad("event.text is required")
        ann["t"] = ev_t
        ann["event"] = {k: ev[k] for k in _EVENT_KEYS if k in ev}
        ann["event"]["t"] = ev_t
        if "type" in ev:
            _check_type(ev["type"])
        if "tEnd" in ev:
            ann["event"]["tEnd"] = _check_t_end(ev["tEnd"], ev_t, duration)
    else:
        ann["t"] = _check_t(body.get("t"), duration)
        ann["text"] = _check_text(body.get("text"))
        ann["role"] = _check_role(body.get("role", "danger"))
        ann["note"] = _check_note(body.get("note"))
        ann["type"] = _check_type(body.get("type", "speech"))
        if ann["type"] == "beeps":
            ann["tEnd"] = _check_t_end(body.get("tEnd"), ann["t"], duration)
        elif body.get("tEnd") is not None:
            raise _bad("tEnd only applies to type beeps")

    if run is not None:
        ann["runId"] = run["id"]
        ann["collisionVersion"] = body.get("collisionVersion") or run.get("collisionVersion")
        if kind == "verdict":
            ann["analysisVersion"] = run.get("analysisVersion")
            ann["modelName"] = run.get("modelName")
    now = _now()
    ann["createdAt"] = ann["updatedAt"] = now

    with _lock:
        doc = _load(rec_id)
        if kind == "verdict":
            key = match_key(ann)
            for other in doc["annotations"]:
                if other.get("kind") == "verdict" and match_key(other) == key:
                    raise ReviewError(409, f"This event already has a verdict ({other['id']}); update it instead")
        doc["annotations"].append(ann)
        doc["annotations"] = _sorted(doc["annotations"])
        _save(rec_id, doc)
    _log(f"{rec_id}: + {kind} {ann['id']} at t={ann['t']}")
    return ann


def update(rec_id: str, duration: float, ann_id: str, body: dict) -> dict:
    with _lock:
        doc = _load(rec_id)
        ann = next((a for a in doc["annotations"] if a["id"] == ann_id), None)
        if ann is None:
            raise ReviewError(404, f"Unknown annotation: {ann_id}")
        kind = ann["kind"]
        new = dict(ann)
        if "note" in body:
            new["note"] = _check_note(body["note"])
        if "verdict" in body:
            if kind != "verdict":
                raise _bad("verdict only applies to verdict annotations")
            new["verdict"] = _check_verdict(body["verdict"])
        for field in ("t", "text", "role", "tEnd"):
            if field in body:
                if kind != "added":
                    raise _bad(f"{field} can only be changed on added annotations")
                if field == "tEnd":
                    continue
                new[field] = {"t": lambda v: _check_t(v, duration), "text": _check_text, "role": _check_role}[field](body[field])
        if kind == "added":
            if "tEnd" in body and new.get("type", "speech") != "beeps":
                raise _bad("tEnd only applies to type beeps")
            if new.get("type") == "beeps":
                new["tEnd"] = _check_t_end(body.get("tEnd", new.get("tEnd")), new["t"], duration)
        new["updatedAt"] = _now()
        doc["annotations"] = _sorted([new if a["id"] == ann_id else a for a in doc["annotations"]])
        _save(rec_id, doc)
    _log(f"{rec_id}: ~ {ann_id}")
    return new


def delete(rec_id: str, ann_id: str) -> None:
    with _lock:
        doc = _load(rec_id)
        kept = [a for a in doc["annotations"] if a["id"] != ann_id]
        if len(kept) == len(doc["annotations"]):
            raise ReviewError(404, f"Unknown annotation: {ann_id}")
        doc["annotations"] = kept
        _save(rec_id, doc)
    _log(f"{rec_id}: - {ann_id}")


def recordings_with_reviews() -> list[str]:
    d = LAB_DIR / "reviews"
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

class _RunData:
    """hazards.json / events.json of one run, loaded once per export."""

    def __init__(self, run_id: str):
        self.frames: list[dict] = []
        self.frame_ts: list[float] = []
        self.speech: list[dict] = []
        self.beeps: list[dict] = []
        base = analysis.run_dir(run_id)
        try:
            self.frames = json.loads((base / "hazards.json").read_text()).get("frames", [])
            self.frame_ts = [f["t"] for f in self.frames]
            events = json.loads((base / "events.json").read_text()).get("events", [])
            self.speech = [e for e in events if e.get("type") == "speech"]
            self.beeps = [e for e in events if e.get("type") == "beeps"]
        except (OSError, ValueError, KeyError) as exc:
            _log(f"export: run {run_id} data unavailable ({exc})")

    def context(self, t: float) -> dict | None:
        if not self.frames:
            return None
        i = bisect.bisect_left(self.frame_ts, t)
        cands = [j for j in (i - 1, i) if 0 <= j < len(self.frames)]
        f = self.frames[min(cands, key=lambda j: abs(self.frame_ts[j] - t))]
        region = f.get("region")
        return {
            "frameT": f["t"],
            "items": [h for h in f.get("hazards", []) if h.get("role") != "none"],
            "ego": f.get("ego"),
            "surface": (region or {}).get("surface"),
            "surfaceLabel": (region or {}).get("label"),
            "horizonY": f.get("horizonY"),
            "nearbySpeech": [e for e in self.speech if abs(e["t"] - t) <= NEARBY_SECONDS],
            "nearbyBeeps": [e for e in self.beeps if e["t"] - NEARBY_SECONDS <= t <= e.get("tEnd", e["t"]) + NEARBY_SECONDS],
        }


def export(rec_ids: list[str]) -> dict:
    cache: dict[str, _RunData] = {}
    out = []
    for rec_id in rec_ids:
        with _lock:
            anns = _sorted(_load(rec_id)["annotations"])
        summary = {"correct": 0, "incorrect": 0, "remove": 0, "added": 0}
        enriched = []
        for a in anns:
            summary["added" if a["kind"] == "added" else a["verdict"]] += 1
            run_id = a.get("runId")
            ctx = None
            if run_id:
                data = cache.get(run_id) or cache.setdefault(run_id, _RunData(run_id))
                ctx = data.context(a["t"])
            enriched.append({**a, "context": ctx})
        out.append({"recording": rec_id, "summary": summary, "annotations": enriched})
    return {"exportedAt": _now(), "recordings": out}
