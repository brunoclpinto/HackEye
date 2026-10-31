"""World-map spike metrics (v26.2 step 1): cost, wall straightness, re-observation spread, drift proxy, extrusion.

    python tools/worldmap_metrics.py <runId> [--wall-t0 10 --wall-t1 16] [--lateral-model collision|lens|geometry] [--json out.json]
                                              [--rays 0,1,3,10,...]

``--rays`` (v26.2.7): the ray scan of the stored snapshots at those times: building cells, *gap* rays (a ray from the user whose first face
cell is preceded by unknown cells that follow a surface cell: the seam between a sidewalk and a building) and *through* rays (surface cells
within 30 cells after the first face run: the street seen through a building). Needs a map built by this code (``worldmap.build``).

Rebuilds the map in memory from the run's stored files (it does not write anything into the run).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collision  # noqa: E402
import worldmap  # noqa: E402
from lab import analysis  # noqa: E402

WALL_CLASSES = ("building", "barrier wall")
THIN = ("pole", "traffic-light", "traffic-light pedestrians", "traffic-sign", "sign")


def ray_scan(classes: np.ndarray, face_lut: np.ndarray, kind: np.ndarray, size: int = 200, oc: int = 100, orow: int = 200,
             half_deg: float = 80.0, step_deg: float = 0.5) -> dict:
    """Rays from the user (every ``step_deg`` over +-``half_deg``) over one snapshot: {"gap", "through", "faceCells"} (see the module doc)."""
    gaps = thru = 0
    for a in np.radians(np.arange(-half_deg, half_deg + 1e-9, step_deg)):
        seq: list[tuple[int, int]] = []
        for k in range(1, 300):
            ri, ci = int(orow - k * 0.5 * math.cos(a)), int(oc + k * 0.5 * math.sin(a))
            if ri < 0 or ci < 0 or ci >= size or ri >= size:
                break
            if seq and seq[-1] == (ri, ci):
                continue
            seq.append((ri, ci))
        vals = [int(classes[r, c]) for r, c in seq]
        first = next((j for j, v in enumerate(vals) if v != worldmap.UNKNOWN and face_lut[v]), None)
        if first is None:
            continue
        j, n = first - 1, 0
        while j >= 0 and vals[j] == worldmap.UNKNOWN:
            n += 1
            j -= 1
        if n > 0 and j >= 0 and kind[vals[j]] == worldmap.KIND_SURFACE:
            gaps += 1
        j = first
        while j < len(vals) and vals[j] != worldmap.UNKNOWN and face_lut[vals[j]]:
            j += 1
        if any(v != worldmap.UNKNOWN and kind[v] == worldmap.KIND_SURFACE for v in vals[j:j + 30]):
            thru += 1
    cells = int(((classes != worldmap.UNKNOWN) & face_lut[np.minimum(classes, 255)]).sum())
    return {"gap": gaps, "through": thru, "faceCells": cells}


def tls_rms(pts: np.ndarray) -> tuple[float, float]:
    """Total-least-squares line through (n,2) points: (RMS perpendicular residual m, direction deg)."""
    c = pts - pts.mean(axis=0)
    u, s, vt = np.linalg.svd(c, full_matrices=False)
    res = c @ vt[1]
    return float(math.sqrt(np.mean(res ** 2))), float(math.degrees(math.atan2(vt[0][0], vt[0][1])))


def robust_rms(pts: np.ndarray, keep: float = 0.9) -> float:
    """RMS after dropping the worst (1 - keep) share of the first fit's residuals (the extrusion / outliers)."""
    c = pts - pts.mean(axis=0)
    vt = np.linalg.svd(c, full_matrices=False)[2]
    res = np.abs(c @ vt[1])
    sel = pts[res <= np.quantile(res, keep)]
    return tls_rms(sel)[0] if len(sel) >= 3 else float("nan")


def ego_points(classes: np.ndarray, ids: list[int], cell: float, oc: int, orow: int,
               fwd: tuple[float, float], right: tuple[float, float]) -> np.ndarray:
    rr, cc = np.nonzero(np.isin(classes, ids))
    f, r = (orow - rr) * cell, (cc - oc) * cell
    m = (f >= fwd[0]) & (f <= fwd[1]) & (r >= right[0]) & (r <= right[1])
    return np.stack([r[m], f[m]], axis=1)


def track_world_positions(hazards: dict, pose: np.ndarray) -> dict[int, dict]:
    tracks: dict[int, dict] = {}
    for i, fr in enumerate(hazards["frames"]):
        x, y, th = pose[i][0], pose[i][1], math.radians(pose[i][2])
        for hz in fr["hazards"]:
            if hz.get("group") != "static" or hz.get("moving") or hz.get("distanceM") is None or hz.get("lateralM") is None:
                continue
            d, lat = hz["distanceM"], hz["lateralM"]
            wx = x + math.sin(th) * d + math.cos(th) * lat
            wy = y + math.cos(th) * d - math.sin(th) * lat
            tr = tracks.setdefault(hz["trackId"], {"cls": hz["className"], "t": [], "xy": [], "d": []})
            tr["t"].append(fr["t"]); tr["xy"].append((wx, wy)); tr["d"].append(d)
    return tracks


def spread_stats(tracks: dict[int, dict], classes: tuple | None, min_life: float = 3.0, max_life: float = 1e9) -> dict:
    full, short, drift, first_d, n = [], [], [], [], 0
    for tr in tracks.values():
        if classes is not None and tr["cls"] not in classes:
            continue
        t, xy = np.array(tr["t"]), np.array(tr["xy"])
        if not (min_life <= t[-1] - t[0] < max_life) or len(t) < 6:
            continue
        n += 1
        full.append(math.sqrt(float(xy[:, 0].var() + xy[:, 1].var())))
        win = np.floor((t - t[0]) / 1.0).astype(int)                       # measurement noise: std inside 1 s windows
        w = [math.sqrt(float(xy[win == k, 0].var() + xy[win == k, 1].var())) for k in np.unique(win) if (win == k).sum() >= 3]
        if w:
            short.append(float(np.mean(w)))
        k = max(3, len(t) // 5)                                              # first / last fifth of the life (medians)
        drift.append(float(np.hypot(*(np.median(xy[:k], axis=0) - np.median(xy[-k:], axis=0)))))
        first_d.append(float(np.median(tr["d"][:k])))
    q = lambda v, p: round(float(np.percentile(v, p)), 3) if v else None
    return {"tracks": n, "spreadMedianM": q(full, 50), "spreadP90M": q(full, 90), "short1sMedianM": q(short, 50),
            "firstVsLastMedianM": q(drift, 50), "firstVsLastP90M": q(drift, 90), "firstSeenDistanceMedianM": q(first_d, 50)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--wall-t0", type=float, default=10.0)
    ap.add_argument("--wall-t1", type=float, default=16.0)
    ap.add_argument("--lateral-model", default=None)
    ap.add_argument("--rays", default=None, help="comma-separated times (s): the ray scan of the stored snapshots there")
    ap.add_argument("--set", action="append", default=[], help="config override key=value (json value)")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    rd = analysis.run_dir(a.run_id)
    doc = json.loads((rd / "run.json").read_text())
    names = doc["classNames"]
    with np.load(rd / "grids.npz") as z:
        grids, times = z["grids"], z["t"]
    hazards = json.loads((rd / "hazards.json").read_text())
    depth = None
    if (rd / "depth.npz").exists():
        with np.load(rd / "depth.npz") as z:
            depth = {"t": z["t"], "depth": z["depth"]}
    cfg = worldmap.load_config()
    if a.lateral_model:
        cfg["lateralModel"] = a.lateral_model
    for kv in a.set:
        k, v = kv.split("=", 1)
        cfg[k] = json.loads(v)
    cell, (oc, orow) = cfg["cellM"], (cfg["snapshot"]["originCol"], cfg["snapshot"]["originRow"])
    wall_ids = [names.index(n) for n in WALL_CLASSES if n in names]
    win = (times >= a.wall_t0) & (times <= a.wall_t1)
    per_frame: list[float] = []
    pooled: dict[int, np.ndarray] = {}                # frame -> its wall points in the world frame (pose of that frame)
    disagree: list[float] = []
    kinds = worldmap.class_kinds(cfg, names)

    def hook(i, wm, obs, snap):
        if win[i]:
            p = ego_points(obs, wall_ids, cell, oc, orow, (0.0, 8.0), (1.0, 8.0))
            if len(p) >= 30:
                per_frame.append(tls_rms(p)[0])
                x, y, th = wm.pose[i][0], wm.pose[i][1], math.radians(wm.pose[i][2])
                pooled[i] = np.stack([x + math.sin(th) * p[:, 1] + math.cos(th) * p[:, 0],
                                      y + math.cos(th) * p[:, 1] - math.sin(th) * p[:, 0]], axis=1)
        if i % 6 == 0 and times[i] > 3.0:
            both = (obs != worldmap.UNKNOWN) & (snap != worldmap.UNKNOWN) & (kinds[obs] == worldmap.KIND_SURFACE)
            if both.sum():
                disagree.append(float((obs[both] != snap[both]).mean()))

    out = worldmap.build(grids, times, names, hazards, collision.load_config(), cfg, depth, hook=hook)
    ms, pose = out["ms"], out["pose"]
    res: dict = {"run": a.run_id, "lateralModel": cfg["lateralModel"], "frames": int(len(ms)),
                 "costMs": {"mean": round(float(ms.mean()), 2), "p95": round(float(np.percentile(ms, 95)), 2), "max": round(float(ms.max()), 2)}}
    i1 = int(np.argmin(np.abs(times - a.wall_t1)))
    pts = ego_points(out["classes"][i1], wall_ids, cell, oc, orow, (0.0, 8.0), (1.0, 8.0))
    res["wall"] = {"window": [a.wall_t0, a.wall_t1], "fusedCells": int(len(pts)),
                   "fusedRmsM": round(tls_rms(pts)[0], 3) if len(pts) >= 30 else None,
                   "fusedRobustRmsM": round(robust_rms(pts), 3) if len(pts) >= 30 else None,
                   "perFrameRmsMeanM": round(float(np.mean(per_frame)), 3) if per_frame else None,
                   "perFrameRmsP90M": round(float(np.percentile(per_frame, 90)), 3) if per_frame else None,
                   "perFrameN": len(per_frame)}
    # pose sensitivity: the same wall points pooled over the last w seconds before wall-t1 in the world frame (w -> 0 = one frame)
    pooled_rms = {}
    for w in (0.2, 1.0, 2.0, 3.0, 6.0):
        sel = [pooled[i] for i in pooled if times[i] >= a.wall_t1 - w - 1e-6]
        if sel:
            P = np.concatenate(sel)
            pooled_rms[f"{w:g}s"] = round(robust_rms(P, 0.9), 3)
    res["wall"]["pooledWorldRobustRmsM"] = pooled_rms
    ext = {}
    for sec in range(int(a.wall_t0) + 1, int(a.wall_t1) + 1):
        i = int(np.argmin(np.abs(times - sec)))
        p = ego_points(out["classes"][i], wall_ids, cell, oc, orow, (0.0, 8.0), (-0.6, 0.6))
        ext[str(sec)] = {"cells": int(len(p)), "nearestM": round(float(p[:, 1].min()), 2) if len(p) else None}
    res["extrusion"] = ext
    tracks = track_world_positions(hazards, pose)
    res["poles"] = spread_stats(tracks, THIN)
    res["polesByLife"] = {f"{lo:g}-{hi:g}s": spread_stats(tracks, THIN, lo, hi) for lo, hi in ((3, 5), (5, 8), (8, 1e9))}
    res["staticAll"] = spread_stats(tracks, None)
    res["consistency"] = {"surfaceFusedVsFrameDisagreement": round(float(np.mean(disagree)), 4) if disagree else None}
    step = np.hypot(np.diff(pose[:, 0]), np.diff(pose[:, 1]))
    res["pose"] = {"pathLengthM": round(float(step.sum()), 1), "endXY": [round(float(pose[-1, 0]), 1), round(float(pose[-1, 1]), 1)],
                   "maxStepM": round(float(step.max()), 2), "maxSpeedMps": round(float((step / np.maximum(np.diff(times), 1e-6)).max()), 2)}
    if a.rays:
        face_lut = np.zeros(256, dtype=bool)
        for cid, n_ in enumerate(names):
            if n_ in cfg.get("faceClasses", ()):
                face_lut[cid] = True
        res["rays"] = {}
        for tt in (float(x) for x in a.rays.split(",")):
            i = int(np.argmin(np.abs(times - tt)))
            res["rays"][f"{tt:g}"] = ray_scan(out["classes"][i], face_lut, kinds, cfg["snapshot"]["size"], oc, orow)
    print(json.dumps(res, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
