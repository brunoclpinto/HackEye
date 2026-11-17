"""v26.2.14: build a review fixture (``tests/fixtures/<name>.{json,npz}``, the layout of chest0004_review10) from a Lab run + collision run.

Run it in the container (numpy only), e.g. the review-11 fixture:
  python tools/make_fixture.py --run 5fda5626e808 --collision c1 --name chest0004_review11 --recording Chest-center-0004 \\
      --window 0 240 --motion-end 250 --sensors-end 256 --export tests/fixtures/chest0004_review11_export.json --events-key systemEventsV26_2_13

Arrays per window ``w<i>``: grids, t, index, depth (as stored), motion (``_mt/_mdx/_mdy/_mresid``, from the run start to --motion-end) and the
recording's sensors (``sensors_*``, to --sensors-end). The json carries run settings, the stored c1 events and, with --export, the review's
annotations / notes / summary. The ``source`` text is written by hand afterwards (--source)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--collision", default="c1")
    ap.add_argument("--name", required=True)
    ap.add_argument("--recording", required=True)
    ap.add_argument("--window", nargs=2, type=float, action="append", required=True, metavar=("START", "END"))
    ap.add_argument("--motion-end", type=float, required=True)
    ap.add_argument("--sensors-end", type=float, required=True)
    ap.add_argument("--export", default=None)
    ap.add_argument("--events-key", default="systemEvents")
    ap.add_argument("--source", default="")
    ap.add_argument("--lab", default="/debug/lab")
    a = ap.parse_args()
    lab = Path(a.lab)
    rdir = lab / "runs" / a.run
    run = json.load(open(rdir / "run.json"))
    cdoc = json.load(open(rdir / "collisions" / a.collision / "collision.json"))
    events = json.load(open(rdir / "collisions" / a.collision / "events.json"))["events"]
    out: dict = {}
    wins = []
    with np.load(rdir / "grids.npz") as zg, np.load(rdir / "depth.npz") as zd:
        t = zg["t"]
        for i, (s, e) in enumerate(a.window):
            m = (t >= s) & (t < e)
            out[f"w{i}_grids"], out[f"w{i}_t"], out[f"w{i}_index"] = zg["grids"][m], t[m], zg["index"][m]
            assert np.array_equal(zd["t"][m], t[m])
            out[f"w{i}_depth"] = zd["depth"][m]
            wins.append({"key": f"w{i}", "start": s, "end": e, "motionEnd": a.motion_end, "sensorsEnd": a.sensors_end})
            with np.load(rdir / "motion.npz") as zm:
                mm = zm["t"] <= a.motion_end
                out[f"w{i}_mt"], out[f"w{i}_mdx"], out[f"w{i}_mdy"], out[f"w{i}_mresid"] = zm["t"][mm], zm["dx"][mm], zm["dy"][mm], zm["resid"][mm]
        units = str(zd["units"]); anchor = str(zd["anchor"])
    with np.load(lab / "sensors" / f"{a.recording}.npz") as zs:
        keys = [k for k in zs.files if k != "_src"]
        for k in keys:
            if k.endswith("_t"):
                continue
            tk = zs[(k if k in ("gyro", "accl", "shut", "isog") else "gps") + "_t"]     # gps_fix / gps_dop / gps_utc share gps_t
            out["sensors_" + k] = zs[k][tk <= a.sensors_end]
        for k in ("gyro_t", "accl_t", "gps_t", "shut_t", "isog_t"):
            out["sensors_" + k] = zs[k][zs[k] <= a.sensors_end]
    meta = {"source": a.source, "windows": wins, "classNames": run["classNames"], "gridW": run["gridW"], "gridH": run["gridH"],
            "srcW": run["srcW"], "srcH": run["srcH"], "depth": {"model": run["depth"], "units": units, "shape": list(out["w0_depth"].shape[1:]), "anchor": anchor},
            "settings": cdoc["settings"], "overrides": cdoc.get("overrides", {}), "speechRate": 1.25,
            "sensorsMeta": {"recording": a.recording, "keys": keys},
            a.events_key: [e for e in events if e["t"] < max(w[1] for w in a.window)]}
    if a.export:
        ex = json.load(open(a.export))
        rec = [r for r in ex["recordings"] if r["recording"] == a.recording][0]
        meta.update(annotations=rec["annotations"], notes=ex["notes"].get("text", ""), summary=rec["summary"])
    np.savez_compressed(ROOT / "tests" / "fixtures" / f"{a.name}.npz", **out)
    json.dump(meta, open(ROOT / "tests" / "fixtures" / f"{a.name}.json", "w"))


if __name__ == "__main__":
    main()
