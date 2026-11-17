"""Shared by tests/test_worldtracks.py and tools/worldtracks_metrics.py: every window of every real-footage fixture, run with the default config
in the ``depth`` and ``ground+depth`` object-distance modes (fixtures without depth maps: one run, the ground distance)."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

import collision as col

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NAMES = ["4929_review1", "4929_review2", "4929_review3", "4929_review4", "chest0002_crosswalk", "chest0004_review7", "chest0004_review8"]
NEW_KEYS = ("worldTracks", "worldTracksSettings")


def v2629_configs() -> tuple[dict, dict]:
    """(collision config, worldmap config) that restore the v26.2.9 behaviour: the time-decayed add-up fusion with inferred seams and no pose
    alignment, and one item per person component (v26.2.10 ships facts only + ``personSplit``)."""
    import worldmap
    cfg = copy.deepcopy(col.load_config())
    cfg["personSplit"]["enabled"] = False
    wcfg = {**worldmap.load_config(), "decay": "time", "conflictFactor": 1.0, "voteCap": 0.0, "poseAlign": False, "gapCloseM": 0.5, "faceThicknessM": 0.3}
    return cfg, wcfg


def run_window(name: str, i: int, mode: str | None, config: dict | None = None, worldmap_config: dict | None = None):
    """(meta, hazards doc, events doc) of window ``i`` of a fixture; ``mode`` = the object distance ("depth" | "ground+depth"), None = default."""
    config = config or col.load_config()
    meta = json.load(open(FIXTURES / f"{name}.json"))
    s = meta["settings"]
    kw = {} if mode is None else {"object_distance": mode}
    settings = col.resolve_settings(config, s["mount"], s["hfovDeg"], s["cameraHeightM"], s["stepLengthM"], projection=s.get("projection"),
                                    distance_source=s.get("distanceSource", "ground"), user_height_m=s.get("userHeightM"),
                                    camera_location=s.get("cameraLocation"), camera_side=s.get("cameraSide"), **kw)
    npz = np.load(FIXTURES / f"{name}.npz")
    motion = {"t": npz[f"w{i}_mt"], "dx": npz[f"w{i}_mdx"], "dy": npz[f"w{i}_mdy"]}
    if f"w{i}_mresid" in npz.files:
        motion["resid"] = npz[f"w{i}_mresid"]
    depth = None
    if f"w{i}_depth" in npz.files:
        dm = meta["depth"]
        depth = {"t": npz[f"w{i}_t"], "depth": npz[f"w{i}_depth"], "units": dm["units"], "anchor": dm["anchor"]}
    doc, ev = col.run_collision(npz[f"w{i}_grids"], npz[f"w{i}_t"], meta["classNames"], config, settings, motion, depth, worldmap_config=worldmap_config)
    return meta, doc, ev


def all_runs(config: dict | None = None, worldmap_config: dict | None = None):
    """Yield (label, meta, hazards doc, events doc) for every fixture window and mode."""
    for name in NAMES:
        meta = json.load(open(FIXTURES / f"{name}.json"))
        npz = np.load(FIXTURES / f"{name}.npz")
        for i, w in enumerate(meta["windows"]):
            modes = ("depth", "ground+depth") if f"w{i}_depth" in npz.files else (None,)
            for mode in modes:
                m, doc, ev = run_window(name, i, mode, config, worldmap_config)
                yield f"{name}/{w['key']}/{mode or 'ground'}", m, doc, ev


def events_hash(ev: dict) -> str:
    return hashlib.sha256(json.dumps(ev["events"], sort_keys=True).encode()).hexdigest()


def hazards_hash(doc: dict) -> str:
    """The hazards doc without the world tracks keys and its version: what v26.2.8 produced."""
    d = copy.deepcopy(doc)
    for k in NEW_KEYS:
        d.pop(k, None)
    for f in d["frames"]:
        f.pop("worldTracks", None)
        for h in f["hazards"]:                       # v26.2.12: the whole component of an item incl. the rows above the horizon (the Lab's selection)
            h.pop("bboxFull", None)
            h.pop("outlineFull", None)
    for k in ("stepLengthSource", "gpsStepWindowsS", "gpsStep"):      # v26.2.12: where the step length came from
        d["settings"].pop(k, None)
    d["version"] = "X"
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
