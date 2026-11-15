"""Characterisation tests for engine.pipeline.run (v26.3.0 p4-02): the verbatim move of ``run_collision``.

The signature parameters and the digest of the short fixture window below were printed by the legacy
``collision.run_collision`` in the hackeye-rnd image before the move (under the test conftest, which patches
``worldmap.load_config``). The engine module is imported inside each test (it does not exist yet).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

import collision
import worldmap
from lab import collisions

if TYPE_CHECKING:
    import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
FIXTURE = "chest0004_review9"
N_FRAMES = 10  # a ~1.7 s window keeps the call fast

SIGNATURE_PARAMS: list[tuple[str, str]] = [
    ("grids", "<empty>"),
    ("times", "<empty>"),
    ("class_names", "<empty>"),
    ("config", "<empty>"),
    ("settings", "<empty>"),
    ("motion", "None"),
    ("depth", "None"),
    ("window", "None"),
    ("sounds", "None"),
    ("worldmap_config", "None"),
    ("progress", "None"),
    ("sensors", "None"),
]
DIGEST: dict[str, Any] = {"nFrames": 10, "hazardCounts": [20, 25, 25, 24, 29, 28, 32, 29, 28, 23], "nEvents": 5}
LEGACY_MODULES = ("collision", "worldmap", "groundfuse", "sensors", "worldtracks", "faceedge")


def _call_args(worldmap_config: dict[str, Any] | None) -> tuple[Any, ...]:
    """Positional args and kwargs of ``run_collision`` for the first N_FRAMES frames of the fixture window."""
    meta = json.loads((FIXTURES / f"{FIXTURE}.json").read_text())
    with np.load(FIXTURES / f"{FIXTURE}.npz") as z:
        grids, times = z["w0_grids"][:N_FRAMES], z["w0_t"][:N_FRAMES]
        motion = {"t": z["w0_mt"], "dx": z["w0_mdx"], "dy": z["w0_mdy"], "resid": z["w0_mresid"]}
        d = meta["depth"]
        depth = {"t": times, "depth": z["w0_depth"][:N_FRAMES], "units": d["units"], "anchor": d["anchor"]}
        sensors = {k[len("sensors_") :]: z[k] for k in z.files if k.startswith("sensors_")}
    ov = meta.get("overrides", {})
    config = collisions.apply_overrides(collision.load_config(), ov, "collision")
    s = meta["settings"]
    settings = collision.resolve_settings(
        config,
        s["mount"],
        s["hfovDeg"],
        s["cameraHeightM"],
        s["stepLengthM"],
        projection=s.get("projection"),
        distance_source=s.get("distanceSource", "ground"),
        user_height_m=s.get("userHeightM"),
        camera_location=s.get("cameraLocation"),
        camera_side=s.get("cameraSide"),
        object_distance=s.get("objectDistance"),
        use_horizon=s.get("useHorizon"),
    )
    sounds = {"kinds": {}, "speechRate": meta.get("speechRate", 1.0)}
    return (grids, times, meta["classNames"], config, settings, motion, depth, sounds, worldmap_config, sensors)


def _run(fn: Any, worldmap_config: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    grids, times, names, config, settings, motion, depth, sounds, wcfg, sensors = _call_args(worldmap_config)
    out: tuple[dict[str, Any], dict[str, Any]] = fn(
        grids, times, names, config, settings, motion, depth=depth, sounds=sounds, worldmap_config=wcfg, sensors=sensors
    )
    return out


def _canon(doc: dict[str, Any]) -> Any:
    """The hazards document the way the equivalence tool compares it: rounded, timing and version keys dropped."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    import equivalence

    def strip(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in equivalence.VOLATILE}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o

    return strip(equivalence.canon(doc))


def test_run_collision_is_the_legacy_name() -> None:
    from engine.pipeline import run

    assert collision.run_collision is run.run_collision


def test_run_collision_signature() -> None:
    import inspect

    from engine.pipeline import run

    sig = inspect.signature(run.run_collision)
    empty = inspect.Parameter.empty
    params = [(p.name, "<empty>" if p.default is empty else repr(p.default)) for p in sig.parameters.values()]
    assert params == SIGNATURE_PARAMS


def test_run_binds_no_legacy_module() -> None:
    from engine.pipeline import run

    bound = [n for n in LEGACY_MODULES if n in vars(run)]
    assert bound == []


def test_default_worldmap_config_comes_from_the_patched_facade_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.pipeline import run

    real: dict[str, Any] = worldmap.load_config()
    calls: list[int] = []

    def spy(path: Any = None) -> dict[str, Any]:
        calls.append(1)
        return real

    monkeypatch.setattr(worldmap, "load_config", spy)
    doc_none, _ev_none = _run(run.run_collision, None)
    assert len(calls) >= 1
    n_calls = len(calls)
    doc_real, _ev_real = _run(run.run_collision, real)
    assert len(calls) == n_calls  # an explicit config never reaches the loader
    assert _canon(doc_none) == _canon(doc_real)


def test_short_window_digest() -> None:
    from engine.pipeline import run

    doc, ev = _run(run.run_collision, worldmap.load_config())
    frames = doc["frames"]
    digest = {
        "nFrames": len(frames),
        "hazardCounts": [len(f["hazards"]) for f in frames],
        "nEvents": len(ev["events"]),
    }
    assert digest == DIGEST
