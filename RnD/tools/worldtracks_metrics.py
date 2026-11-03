"""World-track metrics (v26.2.9, shadow mode): does the tracking in the world hold up? Reads the ``worldTracks`` of hazards.json.

    python tools/worldtracks_metrics.py --fixtures [--mode depth|ground+depth] [--json out.json]
    python tools/worldtracks_metrics.py <runId> [--collision cid] [--json out.json]
    python tools/worldtracks_metrics.py --dir <collision dir holding hazards.json>

Five groups: (1) pose-drift proxy: static-like tracks seen >= 2 s, their world speed (median per track after the first second; ~0 is good) and
the spread of their (filtered) world positions; (2) continuity: image tracks per world track, re-identifications (gap, prediction error at the
re-acquisition = ``innovM``); (3) agreement of the pass's role ``danger`` with the track's ``onCourse`` (movers and statics apart);
(4) ``missing`` states and the tracks dropped for it; (5) cost: ms per frame of the world-track step (``--fixtures`` only: the run is not
stored with it). Fixtures mode runs every window of the golden fixtures (default config, depth and ground+depth modes) and pools them.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


POINT_LIKE = ("pole", "sign", "traffic-light", "traffic-light pedestrians", "traffic-sign", "sidewalk-obstacle", "vehicle")   # vehicle: only static-like (parked)


def _q(v, p):
    return round(float(np.percentile(v, p)), 3) if len(v) else None


class Acc:
    def __init__(self):
        self.drift_speed, self.drift_spread, self.drift_n = [], [], 0
        self.pt_speed, self.pt_spread = [], []                           # the point-like subset (poles, signs, obstacles, parked vehicles)
        self.cls_speed: dict[str, list[float]] = {}
        self.n_world, self.images_per, self.reid_gap, self.reid_err, self.reid_n = 0, [], [], [], 0
        self.agree = {"mover": Counter(), "static": Counter()}
        self.no_track_danger = 0
        self.state_frames, self.missing_cls = Counter(), Counter()
        self.dropped_missing = self.dropped_other = 0
        self.ms: list[float] = []
        self.frames = 0

    def add_doc(self, doc: dict) -> None:
        recs: dict[str, list[tuple]] = {}
        last_seen: dict[str, float] = {}
        n_img: dict[str, int] = {}
        prev_state: dict[str, str] = {}
        for fr in doc["frames"]:
            t = fr["t"]
            self.frames += 1
            wts = fr.get("worldTracks") or []
            by_tid = {w["trackId"]: w for w in wts if w["trackId"] is not None}
            for w in wts:
                i = w["id"]
                self.state_frames[w["state"]] += 1
                if w["state"] == "missing":
                    self.missing_cls[w["class"]] += 1
                if w["state"] == "dropped":
                    if prev_state.get(i) == "missing":
                        self.dropped_missing += 1
                    else:
                        self.dropped_other += 1
                prev_state[i] = w["state"]
                if w["state"] == "seen":
                    recs.setdefault(i, []).append((t, w))
                    if i in last_seen and len(w["imageTracks"]) > n_img.get(i, 1) and w["innovM"] is not None:
                        self.reid_n += 1
                        self.reid_gap.append(t - last_seen[i])
                        self.reid_err.append(w["innovM"])
                    last_seen[i] = t
                n_img[i] = len(w["imageTracks"])
            for h in fr["hazards"]:
                if h.get("role") != "danger" or h.get("lanePart") or h.get("ghost") or h.get("coasting"):
                    continue
                w = by_tid.get(h["trackId"])
                if w is None:
                    self.no_track_danger += 1
                    continue
                self.agree["static" if w["staticLike"] else "mover"][(True, bool(w["onCourse"]))] += 1
            # frames where the pass has a non-danger item whose track is on course are the other half
            for w in wts:
                if w["state"] == "seen" and w["trackId"] is not None and w["onCourse"]:
                    hz = next((h for h in fr["hazards"] if h["trackId"] == w["trackId"]), None)
                    if hz is not None and hz.get("role") != "danger":
                        self.agree["static" if w["staticLike"] else "mover"][(False, True)] += 1
                elif w["state"] == "seen" and w["trackId"] is not None:
                    hz = next((h for h in fr["hazards"] if h["trackId"] == w["trackId"]), None)
                    if hz is not None and hz.get("role") != "danger":
                        self.agree["static" if w["staticLike"] else "mover"][(False, False)] += 1
        for i, rs in recs.items():
            self.n_world += 1
            self.images_per.append(len(rs[-1][1]["imageTracks"]))
            if rs[0][1]["staticLike"] and rs[-1][0] - rs[0][0] >= 2.0:
                late = [w for t, w in rs if t - rs[0][0] >= 1.0] or [rs[-1][1]]
                self.drift_n += 1
                self.drift_speed.append(float(np.median([w["speedMps"] for w in late])))
                xy = np.array([[w["x"], w["y"]] for w in late])
                self.drift_spread.append(float(np.median(np.hypot(*(xy - np.median(xy, axis=0)).T))))
                cls = rs[-1][1]["class"]
                self.cls_speed.setdefault(cls, []).append(self.drift_speed[-1])
                if cls in POINT_LIKE:
                    self.pt_speed.append(self.drift_speed[-1])
                    self.pt_spread.append(self.drift_spread[-1])

    def summary(self) -> dict:
        def ag(c: Counter) -> dict:
            tot = sum(c.values())
            return {"dangerOnCourse": c[(True, True)], "dangerNotOnCourse": c[(True, False)], "notDangerOnCourse": c[(False, True)],
                    "notDangerNotOnCourse": c[(False, False)],
                    "agreementShare": round((c[(True, True)] + c[(False, False)]) / tot, 3) if tot else None,
                    "dangerWithOnCourseShare": round(c[(True, True)] / max(1, c[(True, True)] + c[(True, False)]), 3)}
        tot = sum(self.state_frames.values())
        return {
            "frames": self.frames, "worldTracksSeen": self.n_world,
            "1_poseDriftProxy": {"pointLike": {"tracks": len(self.pt_speed), "speedMedianMps": _q(self.pt_speed, 50), "speedP90Mps": _q(self.pt_speed, 90),
                                                  "positionSpreadMedianM": _q(self.pt_spread, 50), "positionSpreadP90M": _q(self.pt_spread, 90)},
                                 "speedMedianByClass": {c: [len(v), _q(v, 50)] for c, v in sorted(self.cls_speed.items(), key=lambda kv: -len(kv[1]))[:8]},
                                 "allStaticLike": {"tracks": self.drift_n, "speedMedianMps": _q(self.drift_speed, 50), "speedP90Mps": _q(self.drift_speed, 90),
                                 "positionSpreadMedianM": _q(self.drift_spread, 50), "positionSpreadP90M": _q(self.drift_spread, 90)}},
            "2_continuity": {"imageTracksPerWorldTrackMean": round(float(np.mean(self.images_per)), 3) if self.images_per else None,
                             "worldTracksWithReid": int(sum(1 for n in self.images_per if n > 1)), "reidentifications": self.reid_n,
                             "gapMedianS": _q(self.reid_gap, 50), "gapP90S": _q(self.reid_gap, 90),
                             "predictionErrorMedianM": _q(self.reid_err, 50), "predictionErrorP90M": _q(self.reid_err, 90)},
            "3_agreementWithDanger": {"movers": ag(self.agree["mover"]), "statics": ag(self.agree["static"]), "dangerWithoutTrack": self.no_track_danger},
            "4_missing": {"trackFrames": tot, "missingFrames": self.state_frames["missing"],
                          "missingShare": round(self.state_frames["missing"] / tot, 4) if tot else None,
                          "outOfViewFrames": self.state_frames["out-of-view"], "byClass": dict(self.missing_cls.most_common(10)),
                          "droppedAfterMissing": self.dropped_missing, "droppedOther": self.dropped_other},
            "5_costMsPerFrame": {"mean": round(float(np.mean(self.ms)), 3) if self.ms else None, "p95": _q(self.ms, 95),
                                 "frames": len(self.ms)},
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id", nargs="?")
    ap.add_argument("--collision", default=None)
    ap.add_argument("--dir", default=None, help="a collision directory holding hazards.json")
    ap.add_argument("--fixtures", action="store_true")
    ap.add_argument("--mode", default=None, choices=["depth", "ground+depth"])
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    acc = Acc()
    if a.fixtures:
        import collision as col
        from tests import worldtracks_fixtures as wf
        for label, meta, doc, ev in wf.all_runs():
            if a.mode and not label.endswith("/" + a.mode):
                continue
            acc.add_doc(doc)
            acc.ms.extend(col.LAST_WORLD_TRACKS_MS)
            print(f"  {label}: {len(doc['frames'])} frames", file=sys.stderr)
    else:
        if a.dir:
            d = Path(a.dir)
        elif a.run_id:
            from lab import analysis
            base = analysis.run_dir(a.run_id) / "collisions"
            if a.collision:
                d = base / a.collision
            else:
                subs = sorted((p for p in base.iterdir() if (p / "hazards.json").exists()), key=lambda p: p.stat().st_mtime)
                if not subs:
                    sys.exit(f"no collision run in {base}")
                d = subs[-1]
        else:
            ap.error("give a run id, --dir or --fixtures")
        doc = json.loads((d / "hazards.json").read_text())
        if "worldTracksSettings" not in doc:
            sys.exit(f"{d}: no worldTracks in this hazards.json (made before v26.2.9)")
        acc.add_doc(doc)
        print(f"source: {d}", file=sys.stderr)
    out = acc.summary()
    print(json.dumps(out, indent=2))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
