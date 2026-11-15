"""Tests for engine.pipeline.pipeline (v26.3.0 p4-06): ``Pipeline``, its stats, the facade-only ``collision.py``.

The fixture window and call arguments are those of ``test_run.py`` (first ``N_FRAMES`` frames of
``chest0004_review9``). ``WORLD_TRACK_FRAMES`` was printed by the legacy ``collision.run_collision``
(``len(collision.LAST_WORLD_TRACKS_MS)`` after the call, which is ``len(wtracks.ms)``). The engine modules are
imported inside each test (they do not exist yet).
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

import collision
import worldmap
from lab import collisions

SRC = Path(__file__).resolve().parents[3] / "src"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
FIXTURE = "chest0004_review9"
N_FRAMES = 10  # a ~1.7 s window keeps the call fast
WORLD_TRACK_FRAMES = 10


def _call(worldmap_config: dict[str, Any] | None) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """(positional args, keywords) of ``run_collision`` for the first N_FRAMES frames of the fixture window."""
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
    args = (grids, times, meta["classNames"], config, settings)
    kw = {"motion": motion, "depth": depth, "sounds": sounds, "worldmap_config": worldmap_config, "sensors": sensors}
    return args, kw


def _canon(doc: dict[str, Any]) -> Any:
    """The document the way the equivalence tool compares it: rounded, timing and version keys dropped."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    import equivalence

    def strip(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in equivalence.VOLATILE}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o

    return strip(equivalence.canon(doc))


def test_pipeline_run_equals_run_collision() -> None:
    from engine.pipeline.pipeline import Pipeline

    wcfg = worldmap.load_config()
    args, kw = _call(wcfg)
    doc_old, ev_old = collision.run_collision(*args, **kw)
    args, kw = _call(wcfg)
    doc_new, ev_new = Pipeline().run(*args, **kw)
    assert _canon(doc_new) == _canon(doc_old)
    assert _canon(ev_new) == _canon(ev_old)


def test_pipeline_stats_count_one_entry_per_world_track_frame() -> None:
    from engine.pipeline.pipeline import Pipeline
    from engine.pipeline.stages import STAGES

    pipe = Pipeline(STAGES)
    assert pipe.stats.world_tracks_ms == []
    args, kw = _call(worldmap.load_config())
    pipe.run(*args, **kw)
    assert len(pipe.stats.world_tracks_ms) == WORLD_TRACK_FRAMES
    assert all(isinstance(v, float) and v >= 0.0 for v in pipe.stats.world_tracks_ms)
    assert isinstance(pipe.stats.map_ms, list)
    assert list(collision.LAST_WORLD_TRACKS_MS) == pipe.stats.world_tracks_ms


def test_run_collision_still_fills_last_world_tracks_ms() -> None:
    args, kw = _call(worldmap.load_config())
    collision.LAST_WORLD_TRACKS_MS[:] = []
    collision.run_collision(*args, **kw)
    assert len(collision.LAST_WORLD_TRACKS_MS) == WORLD_TRACK_FRAMES


def test_collision_py_is_docstring_future_imports_and_all_only() -> None:
    tree = ast.parse((SRC / "collision.py").read_text())
    body = tree.body
    doc = body[0]
    assert isinstance(doc, ast.Expr)
    assert isinstance(doc.value, ast.Constant)
    assert isinstance(doc.value.value, str)
    for node in body[1:]:
        if isinstance(node, ast.ImportFrom | ast.Import):
            continue
        if isinstance(node, ast.Assign) and [t.id for t in node.targets if isinstance(t, ast.Name)] == ["__all__"]:
            continue
        raise AssertionError(f"collision.py line {node.lineno}: {type(node).__name__} is not allowed in a facade")
