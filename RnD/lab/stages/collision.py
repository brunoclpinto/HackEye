"""The collision pass and the world-map step of a run (v26.3.0 p5-04).

`collision` and `worldmap` (src/) are imported lazily by their flat names so the Lab still runs inference while they are
absent; their entry points are read as attributes at call time (tests patch them). `lab.collisions` is imported
lazily (it imports `analysis`).
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from lab import recordings
from lab.stages import worldmap as stage_worldmap
from lab.store import constants, runs, util


def _build_worldmap(run_id: str, cid: str) -> None:
    """v26.2.6: the world map is built with the run, after the collision pass. A failure is logged; the run is done."""
    try:
        stage_worldmap.worldmap_pass(run_id, cid)
    except Exception as exc:
        util._log(f"run {run_id}: worldmap pass failed: {exc!r}")


def collision_pass(
    run_id: str, overrides: dict[str, Any] | None = None, label: str = "", job: Any = None
) -> dict[str, Any] | None:
    """Compute a NEW collision run (v26.2.8: next id c<n>, never reused) from grids.npz using the recording's
    current settings, plus optional config `overrides` ({"collision": {dotted key: value}, "worldmap": {...}},
    validated, applied to in-memory copies).
    Writes runs/<id>/collisions/<cid>/{hazards.json, events.json, collision.json}; the world map is built by
    `worldmap_pass`. Returns the collision.json document, or None when src/collision.py is missing (the run stays
    valid without hazards). Raises lab.collisions.CollisionError (422) for bad overrides.
    v26.2.10: `job` (a lab.collisions.Job) = the id is already allocated and registered, its collision.json is in
    status `running`; the frame loop reports to `job.progress` (0-0.4) and stops when the job is cancelled; the job
    finishes the document after the map."""
    try:
        import collision
        import worldmap
    except ImportError as exc:
        util._log(f"collision module unavailable ({exc}); skipping collision pass")
        return None
    from lab import collisions

    doc = runs.get_run(run_id)
    overrides = collisions.validate_overrides(overrides)
    base_config = collision.load_config()
    base_wcfg = worldmap.load_config()
    collisions.check_overrides(overrides, base_config, base_wcfg)
    config = collisions.apply_overrides(base_config, overrides, "collision")
    wcfg = collisions.apply_overrides(base_wcfg, overrides, "worldmap")
    stored = recordings.get_settings(doc["request"]["recording"], config["defaultMount"])
    # A windowed (portrait) run was cut for the side it was requested with: its collision pass uses that side.
    side = doc["request"].get("side") or stored["cameraSide"]
    settings = collision.resolve_settings(
        config,
        stored["mount"],
        stored["hfovDeg"],
        stored["cameraHeightM"],
        stored["stepLengthM"],
        projection=stored["projection"],
        distance_source=stored["distanceSource"],
        user_height_m=stored["userHeightM"],
        camera_location=stored["cameraLocation"],
        camera_side=side,
        object_distance=stored["objectDistance"],
        use_horizon=stored["useHorizon"],
    )
    window = None
    gwin = doc.get("gridWindow")
    if gwin:
        window = {**gwin, **doc["window"], "srcW": doc["srcW"], "srcH": doc["srcH"]}
    out = runs.run_dir(run_id)
    with np.load(out / "grids.npz") as z:
        grids, times = z["grids"], z["t"]
    motion = None  # v26.1.0 runs have no motion track
    if (out / "motion.npz").exists():
        with np.load(out / "motion.npz") as z:
            motion = {"t": z["t"], "dx": z["dx"], "dy": z["dy"]}
            if "resid" in z.files:  # analysisVersion 3: residual flow, the stationary-user signal (v26.1.11)
                motion["resid"] = z["resid"]
    depth = None  # runs without a depth model have no depth.npz
    if (out / "depth.npz").exists():
        with np.load(out / "depth.npz") as z:
            units = str(z["units"]) if "units" in z.files else "metric"  # pre-v26.2.x runs are metric
            anchor = str(z["anchor"]) if "anchor" in z.files else ""
            variant = doc["request"].get("depth") or doc.get("depth") or ""
            if anchor in constants.SUPERSEDED_ANCHORS.get(variant, ()):
                anchor = ""
            if anchor not in ("per-frame", "initial", "plane", "none"):  # npz field > variant table > default rule
                anchor = constants.DEPTH_ANCHOR.get(variant)
            if anchor is None:
                anchor = "per-frame" if units == "relative" else "none"
            depth = {"t": z["t"], "depth": z["depth"], "units": units, "anchor": anchor}
    cid = job.cid if job is not None else collisions.allocate(run_id)
    cdir = collisions.collision_dir(run_id, cid)
    try:
        t0 = time.perf_counter()
        extra: dict[str, Any] = (
            {"window": window} if window is not None else {}
        )  # full-frame runs call exactly as before
        sens = recordings.sensors_for(
            doc["request"]["recording"]
        )  # v26.2.11: GoPro telemetry (None: no gpmd stream = v26.2.10 behaviour)
        if sens is not None:
            extra["sensors"] = sens
        if job is not None:  # only a job reports (a synchronous pass calls exactly as before)
            extra["progress"] = lambda i, n: job.report(0.4 * i / max(n, 1))
        from lab import sounds as lab_sounds  # the Lab-wide sound profile (v26.1.16): the tone intervals

        hazards, events = collision.run_collision(
            grids,
            times,
            doc["classNames"],
            config,
            settings,
            motion,
            depth=depth,
            sounds=lab_sounds.profile(),
            worldmap_config=wcfg,
            **extra,
        )
        elapsed = round(time.perf_counter() - t0, 3)
        hazards.setdefault("settings", {})["mount"] = stored["mount"]
        cdir.mkdir(parents=True, exist_ok=True)
        util._write_json(cdir / "hazards.json", hazards)
        util._write_json(cdir / "events.json", events)
        evs = events.get("events", [])
        cdoc = {
            "id": cid,
            "runId": run_id,
            "createdAt": util._now(),
            "collisionVersion": config["version"],
            "worldmapVersion": None,
            "settings": stored,
            "resolved": {
                **hazards.get("settings", {}),
                "distanceSource": hazards.get("distanceSource"),
                "projection": hazards.get("projection"),
            },
            "overrides": overrides,
            "label": "",
            "elapsedSeconds": elapsed,
            "status": "done",
            "progress": 1.0,
            "error": None,
            "counts": {
                "speech": sum(1 for e in evs if e.get("type") == "speech"),
                "beeps": sum(1 for e in evs if e.get("type") == "beeps"),
            },
        }
        if label:
            cdoc["label"] = str(label)[:60]
        if job is not None:  # still running: the map follows; keep the label the row may have got meanwhile
            cdoc.update(status="running", progress=0.4, label=(collisions.read_doc(run_id, cid) or {}).get("label", ""))
        collisions.write_doc(run_id, cid, cdoc)
    except BaseException:
        if job is None:
            import shutil

            shutil.rmtree(cdir, ignore_errors=True)
        raise
    if job is None:
        collisions.register(run_id, cid)
    fields = {"collisionVersion": config["version"]}
    if window is None and doc.get("side") is not None:
        fields["side"] = side  # a full-frame run shows the side its lane offset was last computed for
    runs._update_run(run_id, **fields)
    util._log(f"run {run_id}: collision pass {cid} {elapsed:.2f}s")
    return cdoc
