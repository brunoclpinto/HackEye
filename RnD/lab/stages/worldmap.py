"""The world-map pass (v26.3.0 p5-04): rebuilds worldmap.npz of a collision run (pure numpy, never the GPU queue)."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import numpy as np

from lab.store import runs, util


def worldmap_pass(run_id: str, cid: str | None = None, job: Any = None) -> dict[str, Any]:
    """(Re)build worldmap.npz of collision run `cid` (default: the latest) from grids.npz, that collision run's
    hazards.json (the horizon, ego block and calibration the pass stored) and depth.npz, with the config overrides
    stored in its collision.json. Pure numpy; never touches the GPU queue or hazards.json / events.json. Raises
    FileNotFoundError when grids.npz or hazards.json is missing."""
    import collision
    import worldmap
    from lab import collisions

    out = runs.run_dir(run_id)
    doc = runs.get_run(run_id)
    cid = collisions.resolve(doc, cid)
    cdir = collisions.collision_dir(run_id, cid)
    for name, base in (("grids.npz", out), ("hazards.json", cdir)):
        if not (base / name).exists():
            raise FileNotFoundError(name)
    cdoc = collisions.read_doc(run_id, cid) or {}
    overrides = collisions.validate_overrides(cdoc.get("overrides"))
    with np.load(out / "grids.npz") as z:
        grids, times = z["grids"], z["t"]
    hazards = json.loads((cdir / "hazards.json").read_text())
    depth = None
    if (out / "depth.npz").exists():
        with np.load(out / "depth.npz") as z:
            depth = {"t": z["t"], "depth": z["depth"]}
    cfg = collisions.apply_overrides(worldmap.load_config(), overrides, "worldmap")
    ccfg = collisions.apply_overrides(collision.load_config(), overrides, "collision")
    t0 = time.perf_counter()
    hook = None
    if job is not None:  # v26.2.10: 0.4-1.0 of the job's progress; raises when cancelled
        total = len(grids)
        hook = lambda i, wm, obs, cls: job.report(0.4 + 0.6 * (i + 1) / max(total, 1))  # noqa: E731
    arrays = worldmap.build(grids, times, doc["classNames"], hazards, ccfg, cfg, depth, hook=hook)
    elapsed = round(time.perf_counter() - t0, 3)
    tmp = cdir / "worldmap.tmp.npz"
    np.savez_compressed(tmp, **arrays)
    os.replace(tmp, cdir / "worldmap.npz")
    if cdoc:
        cdoc["worldmapVersion"] = cfg["version"]
        collisions.write_doc(run_id, cid, cdoc)
    util._log(f"run {run_id}: worldmap pass {cid} {elapsed:.2f}s")
    ms = arrays["ms"]
    return {
        "version": cfg["version"],
        "elapsedSeconds": elapsed,
        "frames": int(len(ms)),  # noqa: RUF046
        "msMean": round(float(ms.mean()), 2),
        "msP95": round(float(np.percentile(ms, 95)), 2),
    }
