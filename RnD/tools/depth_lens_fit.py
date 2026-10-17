"""Fit a one-parameter lens family r = (f/k)·tan(k·θ) (k=1 pinhole, k=0.5 stereographic, k->0 equidistant), HFOV fixed,
plus pitch, so flat-ground geometric z agrees with BOTH models' relative depth over 1–12 m. Then the near-ground level
it implies for the plane anchor, and the walking check that level would give."""
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
masks = []
for i in range(0, n, 6):
    reg = col.walking_region(G["grids"][i], ids, config)
    if reg is not None:
        masks.append((i, reg.mask[np.minimum(gh - 1, ((np.arange(dh) + 0.5) / dh * gh).astype(int))][:, np.minimum(gw - 1, ((np.arange(dw) + 0.5) / dw * gw).astype(int))]))
u = (np.arange(dw) + 0.5) / dw; v = (np.arange(dh) + 0.5) / dh
X = np.broadcast_to((u[None, :] - 0.5) * dw, (dh, dw)); Y = np.broadcast_to((v[:, None] - 0.5) * dh, (dh, dw))
Rr = np.hypot(X, Y); PH = np.arctan2(Y, X)
def geo_z(k, pitch_deg):
    f = (dw / 2) * k / math.tan(k * HFOV / 2)                       # edge of the width at HFOV/2
    th = np.arctan(Rr * k / f) / k
    d = np.stack([np.sin(th) * np.cos(PH), np.sin(th) * np.sin(PH), np.cos(th)], -1)
    p = math.radians(pitch_deg); g = np.array([0.0, math.cos(p), math.sin(p)]); dg = d @ g
    return np.where(dg > 1e-3, H_CAM / np.maximum(dg, 1e-3), np.nan) * d[..., 2]
bins = [1, 2, 3, 5, 8, 12]
def profile(Z, key):
    per = [[] for _ in bins[:-1]]
    for i, m in masks[::2]:
        ok = m & np.isfinite(Z) & np.isfinite(D[key][i]) & (D[key][i] > 0)
        rr = Z[ok] / D[key][i][ok]; zz = Z[ok]
        for b in range(len(bins) - 1):
            s = (zz >= bins[b]) & (zz < bins[b + 1])
            if s.sum() > 5: per[b].append(np.median(rr[s]))
    return np.array([np.median(p) if p else np.nan for p in per])
best = []
for k in np.arange(0.55, 1.001, 0.05):
    for pitch in np.arange(-9, 4.1, 0.5):
        Z = geo_z(k, pitch)
        sd = [np.nanstd(np.log(profile(Z, key))) for key in D]
        best.append((sum(sd), k, pitch, sd))
best.sort()
print("lens k (0=equidistant .5=stereographic 1=pinhole), pitch: flatness (std log ratio over 1-12 m) DA2 / Large")
for s, k, p, sd in best[:6]:
    print(f"  k={k:4.2f} pitch={p:4.1f}°  flatness DA2 {sd[0]:.3f}  Large {sd[1]:.3f}")
s, k, p, _ = best[0]
Z = geo_z(k, p); pd = profile(Z, "DA2"); Z0 = geo_z(0.05, 2.9); p0 = profile(Z0, "DA2")
print(f"best lens k={k}, pitch {p}°: DA2 ratio by 1-2/2-3/3-5/5-8/8-12 m = {np.round(pd,3)}")
print(f"current (equidistant, 2.9°):              = {np.round(p0,3)}")
near_new, near_old = np.nanmedian(pd[:3]), np.nanmedian(p0[:3])
print(f"near-ground level change new/old = {near_new/near_old:.2f}  ->  walking check would be {1.40*near_old/near_new:.2f} (was 1.40)")
