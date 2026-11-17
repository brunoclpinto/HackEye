"""World-map agreement (v26.2.10, plan A.7): how well the map shows what the camera sees right now.

    python tools/worldmap_agreement.py <runId> [--collision c1] [--t0 0 --t1 454] [--variants old,new,no-persist,...] [--json out.json]

Per frame, ``worldmap.WorldMap`` records
  * ``agree``      = the share of the frame's SEEN cells (any class, up to maxRangeM) where the fused snapshot's class equals the frame's own
                     observation (after the frame is fused), and
  * ``agreePrior`` = the share of the frame's seen SURFACE cells the map already had right BEFORE the frame was fused (only cells where the
                     map had a surface class with >= alignMinVotes; nan when fewer than alignMinCells were compared): the predictive one,
                     which a map that merely copies the present cannot raise.
This tool rebuilds the map offline from the run's stored files with config variants and prints mean / p10 of both, and ms per frame.
Variants (config overrides on top of the shipped worldmap.json): ``old`` = the v26.2.9 fusion (time decay, no confrontation, no pose
alignment, gap closing 0.5, face thickness 0.3); ``new`` = the shipped defaults; ``no-persist`` / ``no-confront`` / ``no-facts`` /
``no-align`` = ``new`` with plan A.2 / A.3 / A.5 / A.6 switched back to the old behaviour. Nothing is written into the run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collision  # noqa: E402
import worldmap  # noqa: E402
from lab import analysis  # noqa: E402

OLD = {"decay": "time", "conflictFactor": 1.0, "voteCap": 0.0, "poseAlign": False, "gapCloseM": 0.5, "faceThicknessM": 0.3}
VARIANTS = {
    "old": OLD,
    "new": {},
    "no-persist": {"decay": "time"},
    "no-confront": {"conflictFactor": 1.0, "voteCap": 0.0},
    "no-facts": {"gapCloseM": 0.5, "faceThicknessM": 0.3},
    "no-align": {"poseAlign": False},
}


def load_run(run_id: str, cid: str | None):
    rd = analysis.run_dir(run_id)
    doc = json.loads((rd / "run.json").read_text())
    cid = cid or (doc.get("collisions") or ["c1"])[-1]
    with np.load(rd / "grids.npz") as z:
        grids, times = z["grids"], z["t"]
    hazards = json.loads((rd / "collisions" / cid / "hazards.json").read_text())
    depth = None
    if (rd / "depth.npz").exists():
        with np.load(rd / "depth.npz") as z:
            depth = {"t": z["t"], "depth": z["depth"]}
    return doc, grids, times, hazards, depth


def stats(v: np.ndarray) -> dict:
    v = v[np.isfinite(v)]
    return {"mean": round(float(v.mean()), 4), "p10": round(float(np.percentile(v, 10)), 4), "n": int(v.size)} if v.size else {}


def run_variant(name: str, over: dict, doc, grids, times, hazards, depth, sel) -> tuple[dict, dict]:
    cfg = {**worldmap.load_config(), **over}
    out = worldmap.build(grids[sel], times[sel], doc["classNames"], {**hazards, "frames": [f for f, s in zip(hazards["frames"], sel) if s]},
                         collision.load_config(), cfg, None if depth is None else depth)
    ms = out["ms"]
    res = {"agree": stats(out["agree"]), "agreePrior": stats(out["agreePrior"]),
           "msMean": round(float(ms.mean()), 2), "msP95": round(float(np.percentile(ms, 95)), 2),
           "alignDegEnd": round(float(out["alignDeg"][-1]), 2), "alignMEnd": round(float(out["alignM"][-1]), 2)}
    return res, out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--collision", default=None)
    ap.add_argument("--t0", type=float, default=0.0)
    ap.add_argument("--t1", type=float, default=1e9)
    ap.add_argument("--variants", default="old,new,no-persist,no-confront,no-facts,no-align")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    doc, grids, times, hazards, depth = load_run(a.run_id, a.collision)
    sel = (times >= a.t0) & (times <= a.t1)
    if not sel.all():     # build() wants hazards frames aligned with the grids; the window keeps the run's own start (pose starts there)
        pass
    result = {}
    for name in a.variants.split(","):
        res, _ = run_variant(name, VARIANTS[name], doc, grids, times, hazards, depth, sel)
        result[name] = res
        print(f"{name:12s} agree mean {res['agree'].get('mean')} p10 {res['agree'].get('p10')} | prior mean {res['agreePrior'].get('mean')} "
              f"p10 {res['agreePrior'].get('p10')} | {res['msMean']} ms/frame (p95 {res['msP95']}) | align end {res['alignDegEnd']} deg "
              f"{res['alignMEnd']} m", flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
