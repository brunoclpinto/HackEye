"""Per fixture window: speech / beeps counts and the user's ticks matched, for collision source image|map x predictive off|on (v26.2.11).

    python tools/collision_score.py [--dump DIR]

A tick = an annotation with verdict "correct" (speech or beeps); matched when an event of the same type within 0.7 s has the same text
("exact") or the same words without the numbers ("label": steps / clock may differ)."""
from __future__ import annotations

import copy
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import numpy as np  # noqa: E402

import collision as col  # noqa: E402
from worldtracks_fixtures import NAMES, FIXTURES  # noqa: E402


def norm(t):
    return re.sub(r"[\d:]+", "#", t or "").replace("step", "").strip()


def runs(cfg, name):
    meta = json.load(open(FIXTURES / f"{name}.json"))
    s = meta["settings"]
    st = col.resolve_settings(cfg, s["mount"], s["hfovDeg"], s["cameraHeightM"], s["stepLengthM"], projection=s.get("projection"),
                              distance_source=s.get("distanceSource", "ground"), user_height_m=s.get("userHeightM"),
                              camera_location=s.get("cameraLocation"), camera_side=s.get("cameraSide"))
    npz = np.load(FIXTURES / f"{name}.npz")
    for i, w in enumerate(meta["windows"]):
        motion = {"t": npz[f"w{i}_mt"], "dx": npz[f"w{i}_mdx"], "dy": npz[f"w{i}_mdy"]}
        if f"w{i}_mresid" in npz.files:
            motion["resid"] = npz[f"w{i}_mresid"]
        depth = None
        if f"w{i}_depth" in npz.files:
            dm = meta["depth"]
            depth = {"t": npz[f"w{i}_t"], "depth": npz[f"w{i}_depth"], "units": dm["units"], "anchor": dm["anchor"]}
        t0 = time.perf_counter()
        doc, ev = col.run_collision(npz[f"w{i}_grids"], npz[f"w{i}_t"], meta["classNames"], cfg, st, motion, depth)
        yield meta, w, doc, ev["events"], (time.perf_counter() - t0) * 1000.0 / max(1, len(npz[f"w{i}_t"]))


def main():
    base = col.load_config()
    combos = [("image", False), ("image", True), ("map", False), ("map", True)]
    tot = {c: dict(sp=0, bp=0, ex=0, lb=0, n=0, ms=0.0, win=0) for c in combos}
    dump = {}
    for name in NAMES:
        meta0 = json.load(open(FIXTURES / f"{name}.json"))
        ticks = [a for a in meta0.get("annotations", []) if a.get("verdict") == "correct" and a.get("event", {}).get("type", "speech") in ("speech", "beeps")]
        for c in combos:
            cfg = copy.deepcopy(base)
            cfg["source"]["mode"], cfg["speech"]["predictive"]["enabled"] = c[0], c[1]
            for meta, w, doc, evs, ms in runs(cfg, name):
                key = f"{name}/{w['key']}"
                lo, hi = doc["frames"][0]["t"], doc["frames"][-1]["t"]
                dump.setdefault(key, {})[f"{c[0]}-{'pred' if c[1] else 'off'}"] = [e for e in evs if e["type"] in ("speech", "beeps")]
                T = tot[c]
                T["win"] += 1
                T["ms"] += ms
                sp = [e for e in evs if e["type"] == "speech" and e["text"]]
                bp = [e for e in evs if e["type"] == "beeps" and str(e.get("kind", "")).startswith("collision")]
                T["sp"] += len(sp)
                T["bp"] += len(bp)
                for a in ticks:
                    if not (lo <= a["t"] <= hi):
                        continue
                    ty = a.get("event", {}).get("type", "speech")
                    txt = a["event"].get("text", "")
                    cand = [e for e in evs if e["type"] == ty and abs(e["t"] - a["t"]) <= 0.7]
                    T["n"] += 1
                    T["ex"] += any(e.get("text") == txt for e in cand)
                    T["lb"] += any(norm(e.get("text")) == norm(txt) for e in cand)
    print("source  predictive  windows speech beeps ticks exact label  ms/frame")
    for c, T in tot.items():
        print(f"{c[0]:6} {str(c[1]):10} {T['win']:7} {T['sp']:6} {T['bp']:5} {T['n']:5} {T['ex']:5} {T['lb']:5}  {T['ms']/T['win']:.1f}")
    if "--dump" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--dump") + 1])
        json.dump(dump, open(out, "w"))


if __name__ == "__main__":
    main()
