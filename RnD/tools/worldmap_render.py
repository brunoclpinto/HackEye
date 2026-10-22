"""Render world-map snapshots next to the camera frame (Lab proxy video), coloured with the Lab's safety-level palette.

    python tools/worldmap_render.py <runId> <out_dir> <t_seconds> [<t_seconds> ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab import analysis  # noqa: E402


def palette(class_names: list[str]) -> np.ndarray:
    import segmentation
    classes = segmentation._load_mapping(segmentation._CONFIG_DIR / "safety_mapping_hackeye48.json")[0]
    level_color = {0: (70, 70, 70), 1: (0, 140, 0), 2: (255, 140, 0), 3: (255, 0, 0), 4: (60, 60, 200)}
    lut = np.zeros((256, 3), np.uint8)
    for i, n in enumerate(class_names):
        lut[i] = level_color.get(int(classes[i]["safetyLevel"]) if i in classes else 0, (70, 70, 70))
    return lut


def snapshot_image(classes: np.ndarray, conf: np.ndarray, lut: np.ndarray, scale: int = 4, origin=(100, 180)) -> np.ndarray:
    rgb = lut[classes]
    rgb[classes == 255] = (25, 25, 25)
    img = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    oc, orow = origin
    for m in range(0, 19, 5):                                    # range rings every 5 m (ahead)
        y = int((orow - m * 10) * scale)
        cv2.line(img, (0, y), (img.shape[1], y), (200, 200, 200), 1)
    cx, cy = int((oc + 0.5) * scale), int((orow + 0.5) * scale)
    cv2.rectangle(img, (cx - 6 * scale // 2, cy - 60 * scale // 100 * 0 - int(6 * scale)), (cx + 6 * scale // 2, cy), (255, 255, 255), -1)
    cv2.line(img, (int((oc - 6) * scale), 0), (int((oc - 6) * scale), img.shape[0]), (120, 120, 255), 1)   # +-0.6 m corridor
    cv2.line(img, (int((oc + 6) * scale), 0), (int((oc + 6) * scale), img.shape[0]), (120, 120, 255), 1)
    return img


def main() -> None:
    run_id, out_dir, times = sys.argv[1], Path(sys.argv[2]), [float(a) for a in sys.argv[3:]]
    out_dir.mkdir(parents=True, exist_ok=True)
    rd = analysis.run_dir(run_id)
    doc = json.loads((rd / "run.json").read_text())
    with np.load(rd / "worldmap.npz") as z:
        wm = {k: z[k] for k in z.files}
    with np.load(rd / "grids.npz") as z:
        grids, gt = z["grids"], z["t"]
    lut = palette(doc["classNames"])
    cap = cv2.VideoCapture(str(analysis.LAB_DIR / "proxies" / f"{doc['request']['recording']}.mp4"))
    for t in times:
        i = int(np.argmin(np.abs(wm["t"] - t)))
        cap.set(cv2.CAP_PROP_POS_MSEC, float(wm["t"][i]) * 1000.0 + float(doc["request"].get("start", 0.0)) * 1000.0)
        ok, frame = cap.read()
        seg = cv2.resize(lut[grids[i]], (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_NEAREST) if ok else None
        cam = cv2.addWeighted(frame, 0.55, seg, 0.45, 0) if ok else np.zeros((540, 960, 3), np.uint8)
        snap = snapshot_image(wm["classes"][i], wm["conf"][i], lut)
        cam = cv2.resize(cam, (int(cam.shape[1] * snap.shape[0] / cam.shape[0]), snap.shape[0]))
        out = np.hstack([cam, snap])
        cv2.putText(out, f"t={wm['t'][i]:.1f}s  frame {i}", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        path = out_dir / f"wm_{t:05.1f}s.png"
        cv2.imwrite(str(path), out)
        print(path)


if __name__ == "__main__":
    main()
