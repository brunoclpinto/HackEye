"""View-only mask display preferences, shared by every browser that opens the Lab.

`LAB_DIR/display/<mapping file name>` holds only the OVERRIDES of the safety mapping's defaults:

    {"classes": {"<id>": {"level": 2, "show": false}},          # level only if != default, show only if false
     "levels":  {"<level>": {"color": [r, g, b], "opacity": 0.5}},  # each key only if != default
     "updatedAt": "2026-10-16T12:00:00Z"}

It only changes how the Lab paints the mask overlay. It never touches common/config/safety_mapping*.json,
collision.json or any collision / audio behaviour. The directory is outside runs/ and reviews/, so version
wipes (versioning.py) leave it alone.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import segmentation
from lab import recordings

MAPPING_RE = re.compile(r"^safety_mapping[A-Za-z0-9_.-]*\.json$")
_lock = threading.Lock()


class DisplayError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def default_opacity(level: int) -> float:
    """Level 0 ("ignored") is invisible unless the user opts in; every other level is fully opaque."""
    return 0.0 if level == 0 else 1.0


def _dir() -> Path:
    return recordings.LAB_DIR / "display"


def _mapping(name: str) -> tuple[dict, dict]:
    """(classes, levels) of a mapping file in common/config, or 404."""
    if not MAPPING_RE.match(name) or not (segmentation._CONFIG_DIR / name).is_file():
        raise DisplayError(404, f"Unknown mapping: {name}")
    return segmentation._load_mapping(segmentation._CONFIG_DIR / name)


def _read(name: str) -> dict:
    try:
        doc = json.loads((_dir() / name).read_text())
    except (OSError, ValueError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    return {"classes": doc.get("classes") if isinstance(doc.get("classes"), dict) else {},
            "levels": doc.get("levels") if isinstance(doc.get("levels"), dict) else {},
            "updatedAt": doc.get("updatedAt")}


def _write(name: str, classes: dict, levels: dict) -> None:
    path = _dir() / name
    if not classes and not levels:      # back to the defaults: no file at all
        path.unlink(missing_ok=True)
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recordings._atomic_write_json(path, {"classes": classes, "levels": levels, "updatedAt": stamp})


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _clean_classes(raw, classes: dict, levels: dict) -> dict:
    if not isinstance(raw, dict):
        raise DisplayError(422, "classes must be an object {id: {level, show}}")
    out = {}
    for key, ent in raw.items():
        try:
            cid = int(key)
        except (TypeError, ValueError):
            raise DisplayError(422, f"Bad class id: {key!r}") from None
        if cid not in classes or str(cid) != str(key):
            raise DisplayError(422, f"Unknown class id: {key!r}")
        if not isinstance(ent, dict):
            raise DisplayError(422, f"Class {key}: expected an object")
        clean = {}
        if "level" in ent:
            lv = ent["level"]
            if isinstance(lv, bool) or not isinstance(lv, int) or lv not in levels:
                raise DisplayError(422, f"Class {key}: unknown level {lv!r}")
            if lv != classes[cid]["safetyLevel"]:
                clean["level"] = lv
        if "show" in ent:
            if not isinstance(ent["show"], bool):
                raise DisplayError(422, f"Class {key}: show must be true or false")
            if not ent["show"]:
                clean["show"] = False
        if clean:
            out[str(cid)] = clean
    return out


def _clean_levels(raw, levels: dict) -> dict:
    if not isinstance(raw, dict):
        raise DisplayError(422, "levels must be an object {level: {color, opacity}}")
    out = {}
    for key, ent in raw.items():
        try:
            lv = int(key)
        except (TypeError, ValueError):
            raise DisplayError(422, f"Bad level: {key!r}") from None
        if lv not in levels or str(lv) != str(key):
            raise DisplayError(422, f"Unknown level: {key!r}")
        if not isinstance(ent, dict):
            raise DisplayError(422, f"Level {key}: expected an object")
        clean = {}
        if "color" in ent:
            c = ent["color"]
            if not (isinstance(c, list) and len(c) == 3 and all(_is_num(v) and 0 <= v <= 255 for v in c)):
                raise DisplayError(422, f"Level {key}: color must be [r, g, b] with each 0-255")
            c = [int(round(v)) for v in c]
            if c != list(levels[lv]["color"]):
                clean["color"] = c
        if "opacity" in ent:
            o = ent["opacity"]
            if not (_is_num(o) and 0 <= o <= 1):
                raise DisplayError(422, f"Level {key}: opacity must be a number in [0, 1]")
            if abs(o - default_opacity(lv)) > 1e-9:
                clean["opacity"] = float(o)
        if clean:
            out[str(lv)] = clean
    return out


def get(name: str) -> dict:
    """Defaults merged with the saved overrides, plus the raw overrides (`saved`)."""
    classes, levels = _mapping(name)
    with _lock:
        saved = _read(name)
    sc, sl = saved["classes"], saved["levels"]
    return {
        "mapping": name,
        "classes": [{"id": i, "name": c["name"],
                     "level": sc.get(str(i), {}).get("level", c["safetyLevel"]),
                     "show": sc.get(str(i), {}).get("show", True)} for i, c in sorted(classes.items())],
        "levels": [{"level": k, "label": v["label"],
                    "color": sl.get(str(k), {}).get("color", list(v["color"])),
                    "opacity": sl.get(str(k), {}).get("opacity", default_opacity(k))} for k, v in sorted(levels.items())],
        "saved": {"classes": sc, "levels": sl, "updatedAt": saved["updatedAt"]},
    }


def put(name: str, section: str, body: dict) -> dict:
    """Replace one section ("classes" or "levels") with the overrides in `body[section]`."""
    classes, levels = _mapping(name)
    if not isinstance(body, dict) or section not in body:
        raise DisplayError(422, f'Body must be {{"{section}": {{...}}}}')
    clean = _clean_classes(body[section], classes, levels) if section == "classes" else _clean_levels(body[section], levels)
    with _lock:
        saved = _read(name)
        saved[section] = clean
        _write(name, saved["classes"], saved["levels"])
    return get(name)


def reset(name: str, section: str) -> dict:
    _mapping(name)
    with _lock:
        saved = _read(name)
        saved[section] = {}
        _write(name, saved["classes"], saved["levels"])
    return get(name)
