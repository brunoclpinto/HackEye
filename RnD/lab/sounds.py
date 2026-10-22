"""The Lab-wide sound profile (v26.1.16): pitch, duration and repeat interval of every notification sound, and the speech speed.

`LAB_DIR/display/sounds.json` holds only the OVERRIDES of the defaults in ``collision.json`` ``tones.sounds`` / ``tones.speechRate``:

    {"kinds": {"collision-left": {"pitchHz": 700}, "crosswalk-out": {"intervalS": 0.2}}, "speechRate": 1.25, "updatedAt": "..."}

Same pattern as ``lab/display.py``: a small JSON file outside runs/ and reviews/, so version wipes (``versioning.py``) leave it alone;
every browser that opens the Lab shares it. Pitch, duration and speech speed are applied by the browser live; the intervals shape the
tone schedule, so the collision pass (``analysis.collision_pass``) reads the profile and a re-run applies them.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from lab import recordings

_lock = threading.Lock()


def _col():
    """src/collision.py, imported lazily (the Lab runs without it)."""
    import collision
    return collision

FIELDS = ("pitchHz", "durationMs", "intervalS")


class SoundsError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _path() -> Path:
    return recordings.LAB_DIR / "display" / "sounds.json"


def _read() -> dict:
    try:
        doc = json.loads(_path().read_text())
    except (OSError, ValueError):
        doc = {}
    return doc if isinstance(doc, dict) else {}


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _overrides(body: dict, tones: dict) -> dict:
    """The validated, clamped difference between ``body`` and the defaults."""
    if not isinstance(body, dict):
        raise SoundsError(422, 'Body must be {"kinds": {...}, "speechRate": number}')
    kinds_in = body.get("kinds", {})
    if not isinstance(kinds_in, dict):
        raise SoundsError(422, "kinds must be an object {kind: {pitchHz, durationMs, intervalS}}")
    defaults = tones["sounds"]
    resolved = _col().resolve_sounds(tones, {"kinds": kinds_in, "speechRate": body.get("speechRate")})
    out_kinds = {}
    for kind, ent in kinds_in.items():
        if kind not in defaults:
            raise SoundsError(422, f"Unknown sound kind: {kind!r}")
        if not isinstance(ent, dict):
            raise SoundsError(422, f"{kind}: expected an object")
        mine = {}
        for f in FIELDS:
            if f not in ent or ent[f] is None:
                continue
            if not _is_num(ent[f]):
                raise SoundsError(422, f"{kind}.{f} must be a number")
            if defaults[kind].get(f) is None:
                continue                                     # unused for this kind (crosswalk-in has no interval)
            v = resolved["kinds"][kind][f]
            if abs(v - defaults[kind][f]) > 1e-9:
                mine[f] = round(v, 4)
        if mine:
            out_kinds[kind] = mine
    out = {"kinds": out_kinds}
    if "speechRate" in body and body["speechRate"] is not None:
        if not _is_num(body["speechRate"]):
            raise SoundsError(422, "speechRate must be a number")
        if abs(resolved["speechRate"] - float(tones.get("speechRate", 1.0))) > 1e-9:
            out["speechRate"] = round(resolved["speechRate"], 3)
    return out


def _view(saved: dict) -> dict:
    tones = _col().load_config()["tones"]
    prof = _col().resolve_sounds(tones, saved)
    return {"kinds": [{"kind": k, "label": tones["sounds"][k].get("label", k), **{f: v.get(f) for f in FIELDS},
                       "default": {f: tones["sounds"][k].get(f) for f in FIELDS}} for k, v in prof["kinds"].items()],
            "speechRate": prof["speechRate"], "defaultSpeechRate": float(tones.get("speechRate", 1.0)),
            "ranges": tones["soundRanges"], "updatedAt": saved.get("updatedAt")}


def profile() -> dict:
    """What ``collision.run_collision(sounds=...)`` takes: the saved overrides ({"kinds", "speechRate"}), possibly empty."""
    with _lock:
        saved = _read()
    return {"kinds": saved.get("kinds") if isinstance(saved.get("kinds"), dict) else {}, "speechRate": saved.get("speechRate")}


def get() -> dict:
    """Defaults merged with the saved overrides, plus the ranges and the defaults (for the tuner UI)."""
    with _lock:
        saved = _read()
    return _view(saved)


def put(body: dict) -> dict:
    """Replace the saved profile with ``body`` (values equal to the defaults are not stored; none left: no file)."""
    tones = _col().load_config()["tones"]
    clean = _overrides(body, tones)
    with _lock:
        if not clean["kinds"] and "speechRate" not in clean:
            _path().unlink(missing_ok=True)
            return _view({})
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        clean["updatedAt"] = stamp
        recordings._atomic_write_json(_path(), clean)
    return _view(clean)


def reset() -> dict:
    with _lock:
        _path().unlink(missing_ok=True)
    return _view({})
