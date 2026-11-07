"""v26.2.12: replay a fixture window through the CURRENT collision code the way the Lab does (``lab/analysis.py collision_pass``):
config overrides applied to in-memory copies, the recording's settings, motion incl. resid, DA2 depth, the recording's device sensors
(``sensors_*`` arrays of the fixture) and the world-map config. Used by fixtures that carry sensors (chest0004_review9 and later)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import collision as col
import worldmap
from lab import collisions

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str):
    """(meta, npz). The npz is opened lazily; keep it referenced while arrays are used."""
    meta = json.load(open(FIXTURES / f"{name}.json"))
    return meta, np.load(FIXTURES / f"{name}.npz")


def fixture_sensors(npz, window: str = "w0") -> dict | None:
    """The ``sensors_*`` arrays of a fixture as the sensors dict ``run_collision`` takes (None without them)."""
    s = {k[len("sensors_"):]: npz[k] for k in npz.files if k.startswith("sensors_")}
    return s or None


def replay(name: str, window: str = "w0", overrides: dict | None = None, use_sensors: bool = True, sounds: dict | None = None,
           predictive: bool = True, sensors: dict | None = None):
    """Run ``collision.run_collision`` on ``window`` of fixture ``name`` with the fixture's own overrides (or ``overrides``), sensors and
    speech rate (``sensors``: replace the fixture's sensors, e.g. with a synthetic GPS). Returns (meta, doc, events dict). ``sounds`` defaults to the speech rate the review was made with and no pitch overrides."""
    meta, z = load_fixture(name)
    ov = meta.get("overrides", {}) if overrides is None else overrides
    config = collisions.apply_overrides(col.load_config(), ov, "collision")
    config["speech"]["predictive"]["enabled"] = predictive
    wcfg = collisions.apply_overrides(worldmap.load_config(), ov, "worldmap")
    s = meta["settings"]
    settings = col.resolve_settings(
        config, s["mount"], s["hfovDeg"], s["cameraHeightM"], s["stepLengthM"], projection=s.get("projection"),
        distance_source=s.get("distanceSource", "ground"), user_height_m=s.get("userHeightM"),
        camera_location=s.get("cameraLocation"), camera_side=s.get("cameraSide"),
        object_distance=s.get("objectDistance"), use_horizon=s.get("useHorizon"))
    motion = {"t": z[f"{window}_mt"], "dx": z[f"{window}_mdx"], "dy": z[f"{window}_mdy"]}
    if f"{window}_mresid" in z.files:
        motion["resid"] = z[f"{window}_mresid"]
    d = meta["depth"]
    depth = {"t": z[f"{window}_t"], "depth": z[f"{window}_depth"], "units": d["units"], "anchor": d["anchor"]}
    if sounds is None:
        sounds = {"kinds": {}, "speechRate": meta.get("speechRate", 1.0)}
    extra = {"sensors": sensors if sensors is not None else fixture_sensors(z, window)} if use_sensors else {}
    doc, ev = col.run_collision(z[f"{window}_grids"], z[f"{window}_t"], meta["classNames"], config, settings, motion, depth=depth,
                                sounds=sounds, worldmap_config=wcfg, **extra)
    return meta, doc, ev
