"""Ground-projection diagnostic (O13): the image next to the single-frame observation of the world map, with the geometry drawn in.

    python tools/ground_diag.py <runId> <out_dir> <t_seconds> [<t_seconds> ...] [--collision cid] [--roll DEG] [--horizon-shift ROWS] [--pitch-shift DEG]

Per frame one PNG: LEFT the camera frame with the class grid blended in, the horizon (white), the ground rows at 1 / 2 / 3 / 5 / 8 / 12 m ahead
(yellow) and the lateral lines at -2 / -1 / 0 / +1 / +2 m (cyan) as the observer's inverse ground sampling projects them; RIGHT the observation
(``Observer.observe``) in class colours with the same range rings and the corridor; below a legend of the classes present (grid / observation
shares). ``--horizon-shift`` (grid rows, + = lower) and ``--roll`` (deg) re-render the observation with a different horizon / camera roll to
see what each would change. Prints the frame's horizon, pitch, roll, depth scale and the class under the user's feet (obs cell 0.5 m ahead).
"""
from __future__ import annotations

import argparse
import colorsys
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab import analysis  # noqa: E402
import worldmap  # noqa: E402
import groundfuse  # noqa: E402,F401


FIXED = {"flat road": (40, 120, 255), "flat sidewalk": (230, 140, 40), "curb": (60, 230, 60), "building": (160, 60, 160),
         "void ground": (120, 120, 120), "nature sky": (255, 220, 160), "nature vegetation": (30, 120, 30), "crosswalk": (255, 255, 255)}   # BGR


def class_colors(names: list[str]) -> np.ndarray:
    """Surfaces in fixed, far-apart colours (road orange-red, sidewalk blue, curb green, void grey), the rest by hashed hue."""
    lut = np.zeros((256, 3), np.uint8)
    for i, nm in enumerate(names):
        h = (i * 0.61803) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, 0.65, 0.95)
        lut[i] = FIXED.get(nm, (int(b * 255), int(g * 255), int(r * 255)))
    lut[255] = (30, 30, 30)
    return lut


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("out_dir")
    ap.add_argument("times", nargs="+", type=float)
    ap.add_argument("--collision", default=None)
    ap.add_argument("--roll", type=float, default=None, help="camera roll to undo (deg, + = right side down); default = the frame's rollCorrectDeg")
    ap.add_argument("--horizon-shift", type=float, default=0.0)
    ap.add_argument("--pitch-shift", type=float, default=0.0, help="deg, + = looking up: moves the horizon by f*tan(pitch) rows")
    a = ap.parse_args()
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rd = analysis.run_dir(a.run_id)
    run = json.loads((rd / "run.json").read_text())
    cd = rd / "collisions" / (a.collision or (run.get("collisions") or ["c1"])[-1])
    hz = json.loads((cd / "hazards.json").read_text())
    with np.load(rd / "grids.npz") as z:
        grids, gt = z["grids"], z["t"]
    depth = None
    if (rd / "depth.npz").exists():
        with np.load(rd / "depth.npz") as z:
            depth = {k: z[k] for k in z.files}
    names = run["classNames"]
    lut = class_colors(list(names))
    wcfg = worldmap.load_config()
    frames = worldmap.frames_from_hazards(hz)
    n, gh, gw = grids.shape
    kind = worldmap.class_kinds(wcfg, list(names))
    import groundfuse
    coll_cfg = json.loads((Path(__file__).resolve().parents[2] / "common" / "config" / "collision.json").read_text())
    obsr = worldmap.Observer(wcfg, worldmap.settings_from_hazards(hz), kind, gh, gw, groundfuse.settings(coll_cfg.get("distance", {})), list(names))
    cap = cv2.VideoCapture(str(analysis.LAB_DIR / "proxies" / f"{run['request']['recording']}.mp4"))
    for t in a.times:
        i = int(np.argmin(np.abs(gt - t)))
        fr = dict(frames[i])
        if a.roll is not None:
            fr["ego"] = {**fr["ego"], "rollCorrectDeg": a.roll}
        f_px = obsr.f_px
        if a.horizon_shift or a.pitch_shift:
            fr["horizon"] = fr["horizon"] + a.horizon_shift / gh + (f_px * np.tan(np.radians(a.pitch_shift)) / gh if a.pitch_shift else 0.0)
        dmap = None
        if depth is not None:
            j = int(np.argmin(np.abs(depth["t"] - gt[i])))
            dmap = np.asarray(depth["depth"][j])
        fr = worldmap.WorldMap.resolve_frame(type("S", (), {"last_ds": None, "first_ds": worldmap.first_depth_scale(frames)})(), fr)
        grid = np.asarray(grids[i])
        obs, _ = obsr.observe(grid, fr, dmap)
        cap.set(cv2.CAP_PROP_POS_MSEC, float(gt[i]) * 1000.0 + float(run["request"].get("start", 0.0)) * 1000.0)
        ok, img = cap.read()
        H, W = (img.shape[:2] if ok else (540, 960))
        if not ok:
            img = np.zeros((H, W, 3), np.uint8)
        seg = cv2.resize(lut[grid], (W, H), interpolation=cv2.INTER_NEAREST)
        left = cv2.addWeighted(img, 0.6, seg, 0.4, 0)
        hor = float(fr["horizon"])
        cv2.line(left, (0, int(hor * H)), (W, int(hor * H)), (255, 255, 255), 1)
        cam_h = obsr.cam_h * obsr.ground_scale(fr)
        def px(d: float, lat: float):
            """(x, y) in 0..1 of the ground point (d ahead, lat right): exactly the observer's inverse sampling."""
            if obsr.geometry:
                r_, c_ = worldmap.groundfuse.ground_pixel(obsr.geo, np.array([d]), np.array([lat - obsr.lat_off]), hor, cam_h)
                return float(c_[0]) / gw, float(r_[0]) / gh
            y_ = hor + cam_h * f_px / (d * gh)
            x_ = (0.5 + np.arctan2(lat - obsr.lat_off, d) / np.radians(obsr.hfov)) if obsr.lens else 0.5 + (lat - obsr.lat_off) * f_px / (d * gw)
            return x_, y_
        for d in (1, 2, 3, 5, 8, 12):
            pts = [px(d, lat) for lat in np.linspace(-4, 4, 25)]
            pts = [(int(x * W), int(y * H)) for x, y in pts if np.isfinite(x) and np.isfinite(y) and 0 <= x < 1 and 0 <= y < 1]
            if len(pts) > 1:
                cv2.polylines(left, [np.array(pts)], False, (0, 255, 255), 1)
                cv2.putText(left, f"{d}m", (pts[0][0] + 4, pts[0][1] - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        for lat in (-3, -2, -1, 0, 1, 2, 3):
            pts = [px(d, lat) for d in np.linspace(1.0, 14.0, 30)]
            pts = [(int(x * W), int(y * H)) for x, y in pts if np.isfinite(x) and np.isfinite(y) and 0 <= x < 1 and 0 <= y < 1]
            if len(pts) > 1:
                cv2.polylines(left, [np.array(pts)], False, (255, 255, 0) if lat else (0, 0, 255), 1)
        scale = 3
        right = lut[obs]
        right = cv2.resize(right, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        oc, orow = obsr.oc, obsr.orow
        for m in (1, 2, 3, 5, 8, 12, 16):
            y = int((orow - m / obsr.cell) * scale)
            if 0 <= y < right.shape[0]:
                cv2.line(right, (0, y), (right.shape[1], y), (255, 255, 255), 1)
                cv2.putText(right, f"{m}m", (4, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        for lat in (-2, -1, 0, 1, 2):
            x = int((oc + lat / obsr.cell) * scale)
            cv2.line(right, (x, 0), (x, right.shape[0]), (255, 255, 0) if lat else (0, 0, 255), 1)
        # crop the map to 18 m ahead and +-6 m, scale to the image height
        r0 = max(0, int((orow - 18 / obsr.cell) * scale))
        c0, c1 = int((oc - 6 / obsr.cell) * scale), int((oc + 6 / obsr.cell) * scale)
        right = right[r0:int(orow * scale) + 6, c0:c1]
        right = cv2.resize(right, (int(right.shape[1] * H / right.shape[0]), H), interpolation=cv2.INTER_NEAREST)
        # legend
        cnt_g = np.bincount(grid.ravel(), minlength=256) / grid.size
        known = obs[obs != 255]
        cnt_o = np.bincount(known.ravel(), minlength=256) / max(1, known.size)
        leg = np.zeros((130, W + right.shape[1], 3), np.uint8)
        top = [c for c in np.argsort(-cnt_g)[:8] if cnt_g[c] > 0.005]
        for k, c in enumerate(top):
            x, y = 8 + (k % 4) * 330, 20 + (k // 4) * 24
            cv2.rectangle(leg, (x, y - 12), (x + 14, y + 2), tuple(int(v) for v in lut[c]), -1)
            cv2.putText(leg, f"{names[c][:24]} grid {cnt_g[c]*100:.0f}% obs {cnt_o[c]*100:.0f}%", (x + 20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        e = fr["ego"]
        near = obs[orow - int(round(1.0 / obsr.cell)), oc - 3:oc + 4]
        ahead = [names[c] if c != 255 else "unknown" for c in (obs[orow - int(round(m / obsr.cell)), oc] for m in (1, 2, 3, 5))]
        txt = (f"t={gt[i]:.1f}s horizon={hor:.3f} ({hor*gh:.1f}/{gh} rows) pitch={e.get('pitchDeg')} roll={e.get('rollDeg')} rollCorrect={e.get('rollCorrectDeg')} "
               f"dscale={fr.get('depthScale')}")
        cv2.putText(leg, txt, (8, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 255, 200), 1)
        cv2.putText(leg, "obs on the centre line at 1/2/3/5 m: " + ", ".join(ahead), (8, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 255, 200), 1)
        out = np.vstack([np.hstack([left, right]), leg])
        tag = f"_h{a.horizon_shift:+g}_p{a.pitch_shift:+g}" + (f"_r{a.roll:+g}" if a.roll is not None else "")
        path = out_dir / f"ground_{t:05.1f}s{tag if (a.horizon_shift or a.pitch_shift or a.roll is not None) else ''}.png"
        cv2.imwrite(str(path), out)
        print(path)
        print("  ", txt)
        print("   obs centre line 1/2/3/5 m:", ahead)


if __name__ == "__main__":
    main()
