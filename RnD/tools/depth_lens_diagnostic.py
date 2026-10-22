"""Ground-truth-free diagnostic: on flat walking-region ground, geometric z (camera height, pitch, equidistant fisheye)
vs model z, binned by geometric distance and by image column. A constant ratio = linear bias (one scale fixes it);
a trend = range- or position-dependent bias (fisheye vs pinhole-trained models)."""
import json, sys, math, numpy as np
sys.path.insert(0, "/rnd/src"); sys.path.insert(0, "/rnd")
import collision as col
R = "/debug/lab/runs/"; END = 300.0
runs = {"DA2": "ffc2e6f0bd66", "Large": "5b1d10dd5b3d"}
run = json.load(open(R + runs["DA2"] + "/run.json"))
G = np.load(R + runs["DA2"] + "/grids.npz"); n = int(np.searchsorted(G["t"], END))
D = {k: np.load(R + v + "/depth.npz")["depth"][:n].astype(np.float32) for k, v in runs.items()}
config = col.load_config(); ids = col.resolve_class_ids(config, run["classNames"])
gh, gw = G["grids"].shape[1:]; dh, dw = D["DA2"].shape[1:]
H_CAM = 1.2816; HFOV = math.radians(118.0)
def geo_z(pitch_deg, model):
    u = (np.arange(dw) + 0.5) / dw; v = (np.arange(dh) + 0.5) / dh
    x = (u[None, :] - 0.5) * dw; y = (v[:, None] - 0.5) * dh * np.ones((1, dw))
    x = np.broadcast_to(x, (dh, dw))
    if model == "fisheye":
        f = dw / HFOV; r = np.hypot(x, y); th = r / f; ph = np.arctan2(y, x)
        d = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1)
    else:
        f = (dw / 2) / math.tan(HFOV / 2)
        d = np.stack([x / f, y / f, np.ones_like(x)], -1); d /= np.linalg.norm(d, axis=-1, keepdims=True)
    p = math.radians(pitch_deg); g = np.array([0.0, math.cos(p), math.sin(p)])
    dg = d @ g
    t = np.where(dg > 1e-3, H_CAM / np.maximum(dg, 1e-3), np.nan)
    return t * d[..., 2]
zbins = [1, 2, 3, 5, 8, 12, 20]
for model in ("fisheye", "rectilinear"):
    for pitch in (2.9,):
        Z = geo_z(pitch, model)
        acc = {k: {"z": [[] for _ in zbins[:-1]], "c": [[], [], []]} for k in D}
        for i in range(0, n, 6):
            reg = col.walking_region(G["grids"][i], ids, config)
            if reg is None: continue
            m = reg.mask[np.minimum(gh - 1, ((np.arange(dh) + 0.5) / dh * gh).astype(int))][:, np.minimum(gw - 1, ((np.arange(dw) + 0.5) / dw * gw).astype(int))]
            for k in D:
                ok = m & np.isfinite(Z) & np.isfinite(D[k][i]) & (D[k][i] > 0)
                rr = Z[ok] / D[k][i][ok]; zz = Z[ok]; cc = np.nonzero(ok)[1] / dw
                for b in range(len(zbins) - 1):
                    s = (zz >= zbins[b]) & (zz < zbins[b + 1]) & (np.abs(cc - 0.5) < 0.17)
                    if s.sum(): acc[k]["z"][b].append(np.median(rr[s]))
                for j, (lo, hi) in enumerate(((0, 0.33), (0.33, 0.67), (0.67, 1.0))):
                    s = (cc >= lo) & (cc < hi) & (zz >= 2) & (zz < 5)
                    if s.sum(): acc[k]["c"][j].append(np.median(rr[s]))
        print(f"== geometry: {model}, pitch {pitch}°  (ratio = geometric z / model z; centre third of columns)")
        for k in D:
            zs = "  ".join(f"{zbins[b]}-{zbins[b+1]}m:{np.median(acc[k]['z'][b]):.3f}" if acc[k]['z'][b] else f"{zbins[b]}-{zbins[b+1]}m: -" for b in range(len(zbins) - 1))
            cs = "  ".join(f"{nm}:{np.median(acc[k]['c'][j]):.3f}" for j, nm in enumerate(("left", "centre", "right")) if acc[k]['c'][j])
            print(f"   {k:6s} by distance: {zs}\n          by column (2-5 m): {cs}")
