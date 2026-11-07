"""Per fixture window: speech / beeps counts and the user's ticks matched, per named variant of the config (v26.2.11: source image|map x predictive;
v26.2.12: the new rules one at a time, see ``variants()``).

    python tools/collision_score.py [variant ...] [--rows] [--json out.json]      (run it in the Lab container: cd /rnd && python tools/collision_score.py)

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
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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


ALL_NAMES = sorted(p.stem for p in FIXTURES.glob("*.json") if (FIXTURES / (p.stem + ".npz")).exists())


# --- v26.2.12: named variants (dotted config overrides on the shipped defaults), all fixtures incl. the sensors of chest0004_review9 -------------------
NEW_OFF = {"speech.minVoiceSteps": 0, "speech.thinStableS": 0, "speech.colocatedM": 0, "speech.zoneOnly.enabled": False,
           "speech.reannounce.enabled": False, "speech.predictive.maxAdvanceM": 0, "speech.predictive.clockHoldQuarters": 0,
           "speech.predictive.measuredFloor": 0, "distance.jump.enabled": False, "tree.enabled": False, "beeps.follow.enabled": False,
           "blocked.enabled": False}
V26211 = {**NEW_OFF, "source.mode": "image", "tones.speechRate": 1.0}      # what v26.2.11 shipped (c2 sensor choices only matter with sensors)
LEAVE_ONE_OUT = {k: {n: v for n, v in {"tree": "tree.enabled", "jump": "distance.jump.enabled", "voice": "speech.minVoiceSteps",
                                        "zone": "speech.zoneOnly.enabled", "stable": "speech.thinStableS", "coloc": "speech.colocatedM",
                                        "reann": "speech.reannounce.enabled", "cap": "speech.predictive.maxAdvanceM",
                                        "hold": "speech.predictive.clockHoldQuarters", "meas": "speech.predictive.measuredFloor",
                                        "follow": "beeps.follow.enabled", "blocked": "blocked.enabled"}.items() if n == k}
                 for k in ("tree", "jump", "voice", "zone", "stable", "coloc", "reann", "cap", "hold", "meas", "follow", "blocked")}


def variants() -> dict[str, dict]:
    out = {"v26.2.11": V26211, "new": {}, "new@1.0": {"tones.speechRate": 1.0}, "mapOnly": {**NEW_OFF, "tones.speechRate": 1.0}}
    for k, d in LEAVE_ONE_OUT.items():
        key = next(iter(d.values()))
        out[f"new-{k}"] = {key: NEW_OFF[key]}
    return out


def run_variant(overrides: dict, names=None):
    """Rows per window: dict(name, key, sp, bp, ex, lb, n, bad, blocked, ms) with the variant's dotted overrides on the default config."""
    from lab import collisions
    import worldmap
    from tests.replay import fixture_sensors
    rows = []
    for name in (names or ALL_NAMES):
        meta = json.load(open(FIXTURES / f"{name}.json"))
        npz = np.load(FIXTURES / f"{name}.npz")
        s = meta["settings"]
        ticks = [a for a in meta.get("annotations", []) if a.get("verdict") == "correct" and a.get("event", {}).get("type", "speech") in ("speech", "beeps")]
        bads = [a for a in meta.get("annotations", []) if a.get("verdict") in ("remove", "incorrect") and a.get("event", {}).get("type", "speech") in ("speech", "beeps")]
        for i, w in enumerate(meta["windows"]):
            cfg = collisions.apply_overrides(col.load_config(), {"collision": overrides}, "collision")
            wcfg = worldmap.load_config()
            st = col.resolve_settings(cfg, s["mount"], s["hfovDeg"], s["cameraHeightM"], s["stepLengthM"], projection=s.get("projection"),
                                      distance_source=s.get("distanceSource", "ground"), user_height_m=s.get("userHeightM"),
                                      camera_location=s.get("cameraLocation"), camera_side=s.get("cameraSide"),
                                      object_distance=s.get("objectDistance"), use_horizon=s.get("useHorizon"))
            motion = {"t": npz[f"w{i}_mt"], "dx": npz[f"w{i}_mdx"], "dy": npz[f"w{i}_mdy"]}
            if f"w{i}_mresid" in npz.files:
                motion["resid"] = npz[f"w{i}_mresid"]
            depth = None
            if f"w{i}_depth" in npz.files:
                dm = meta["depth"]
                depth = {"t": npz[f"w{i}_t"], "depth": npz[f"w{i}_depth"], "units": dm["units"], "anchor": dm["anchor"]}
            sens = fixture_sensors(npz) if any(k.startswith("sensors_") for k in npz.files) else None
            t0 = time.perf_counter()
            doc, ev = col.run_collision(npz[f"w{i}_grids"], npz[f"w{i}_t"], meta["classNames"], cfg, st, motion, depth, worldmap_config=wcfg,
                                        sensors=sens)
            ms = (time.perf_counter() - t0) * 1000.0 / max(1, len(npz[f"w{i}_t"]))
            evs = ev["events"]
            lo, hi = doc["frames"][0]["t"], doc["frames"][-1]["t"]
            sp = [e for e in evs if e["type"] == "speech" and e["text"]]
            bp = [e for e in evs if e["type"] == "beeps" and str(e.get("kind", "")).startswith("collision")]
            r = dict(name=name, key=w["key"], sp=len(sp), bp=len(bp), ex=0, lb=0, n=0, bad=0, nbad=0, ms=ms,
                     blocked=sum(1 for e in sp if "blocked" in e), tones=sum(1 for e in evs if e["type"] == "tone"))
            for a in ticks:
                if lo <= a["t"] <= hi:
                    ty = a.get("event", {}).get("type", "speech")
                    txt = a["event"].get("text", "")
                    cand = [e for e in evs if e["type"] == ty and abs(e["t"] - a["t"]) <= 0.7]
                    r["n"] += 1
                    r["ex"] += any(e.get("text") == txt for e in cand)
                    r["lb"] += any(norm(e.get("text")) == norm(txt) for e in cand)
            for a in bads:
                if lo <= a["t"] <= hi:
                    ty = a.get("event", {}).get("type", "speech")
                    txt = a["event"].get("text", "")
                    r["nbad"] += 1
                    r["bad"] += any(e.get("text") == txt for e in evs if e["type"] == ty and abs(e["t"] - a["t"]) <= 0.7)
            rows.append(r)
    return rows


def main():
    """``python tools/collision_score.py [variant ...] [--rows] [--json out.json]``: per variant and fixture (``variants()``): speech / beeps / blocked phrases,
    ticks (verdict correct) still there as the same text ("exact") or the same words ("label"), and the wrong ones (remove / incorrect) still said."""
    argv = sys.argv[1:]
    js = argv.index("--json") if "--json" in argv else -1
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and i != js + 1 or (js < 0 and not a.startswith("--"))]
    out = {}
    allv = variants()
    for v in (args or list(allv)):
        rows = run_variant(allv[v])
        out[v] = rows
        if "--rows" in argv:
            for r in rows:
                print(f"  {v:10} {r['name']}/{r['key']:3} speech {r['sp']:3} beeps {r['bp']:3} blocked {r['blocked']} ticks {r['n']:3} exact {r['ex']:3} label {r['lb']:3} "
                      f"wrong {r['nbad']:2} still-said {r['bad']}", flush=True)
        tot = {k: sum(r[k] for r in rows) for k in ("sp", "bp", "blocked", "n", "ex", "lb", "nbad", "bad", "tones")}
        print(f"{v:12} speech {tot['sp']:4} beeps {tot['bp']:4} blocked {tot['blocked']:2} ticks {tot['n']:3} exact {tot['ex']:3} label {tot['lb']:3} "
              f"wrong {tot['nbad']:3} still-said {tot['bad']:3} tones {tot['tones']:4}  ms/frame {sum(r['ms'] for r in rows) / len(rows):.1f}", flush=True)
    if js >= 0:
        json.dump(out, open(argv[js + 1], "w"), indent=1)


if __name__ == "__main__":
    main()
