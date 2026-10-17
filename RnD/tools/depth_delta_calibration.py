"""Offline check (v26.1.10): N-frame "delta" calibration of DA2 Metric Outdoor S against the flat-ground reference.
c0 = median over N frames of (flat-ground z / DA2 z) on the walking region (fixed mount horizon, preset camera height); depth = c0 * DA2 is then held for a minute and compared to the Metric Large run. Run inside the lab container: python3 /rnd/tools/depth_delta_calibration.py (run ids are the 4929 Lab runs)."""
import json, sys, numpy as np
sys.path.insert(0, "/rnd/src"); sys.path.insert(0, "/rnd")
import collision as col
R = "/debug/lab/runs/"
DA2, REF = "ffc2e6f0bd66", "5b1d10dd5b3d"
run = json.load(open(R + DA2 + "/run.json"))
G = np.load(R + DA2 + "/grids.npz")["grids"]; D = np.load(R + DA2 + "/depth.npz")["depth"].astype(np.float32)
L = np.load(R + REF + "/depth.npz")["depth"].astype(np.float32)
config = col.load_config(); ids = col.resolve_class_ids(config, run["classNames"])
st = col.resolve_settings(config, "chest")
n, gh, gw = G.shape; dh, dw = D.shape[1:]
f = col.focal_px(gw, st.hfov_deg); hz = st.horizon_default; H = st.camera_height_m
min_rows = config["tracking"]["motionMinRowsBelowHorizon"]

def frame_k(i):
    reg = col.walking_region(G[i], ids, config)
    if reg is None: return None
    rr, cc = np.nonzero(reg.mask)
    keep = rr + 0.5 - hz * gh >= min_rows
    rr, cc = rr[keep], cc[keep]
    if rr.size < 150: return None
    z = D[i, np.minimum(dh - 1, ((rr + 0.5) / gh * dh).astype(int)), np.minimum(dw - 1, ((cc + 0.5) / gw * dw).astype(int))]
    g = H * f / (rr + 0.5 - hz * gh)
    ok = np.isfinite(z) & (z > 0)
    return float(np.median(g[ok] / z[ok])) if ok.sum() >= 150 else None

def level_vs_ref(i, c):
    a, b = L[i, 34:], D[i, 34:] * c
    m = np.isfinite(a) & np.isfinite(b) & (a < 30) & (a > 0.5)
    return np.median(b[m] / a[m]) if m.sum() > 200 else None

for N in (3, 6):
    c0s, held = [], []
    for start in range(60, n - 400, 360):             # a fresh calibration every minute (6 fps)
        ks = [k for k in (frame_k(i) for i in range(start, start + N)) if k]
        if len(ks) < max(2, N // 2): continue
        c0 = float(np.median(ks)); c0s.append(c0)
        for i in range(start + N, start + 360, 6):      # hold it for the next minute
            r = level_vs_ref(i, c0)
            if r: held.append(np.log(r))
    c0s, held = np.array(c0s), np.array(held)
    lvl = np.median(held)
    print(f"N={N} frames: c0 median {np.median(c0s):.3f} (p10 {np.percentile(c0s,10):.3f}, p90 {np.percentile(c0s,90):.3f}, spread {100*np.median(np.abs(np.log(c0s/np.median(c0s)))):.0f}%) over {len(c0s)} calibrations | "
          f"held 1 min: level vs Large {np.exp(lvl):.2f}, error around level median {100*np.median(np.abs(held-lvl)):.0f}% p90 {100*np.percentile(np.abs(held-lvl),90):.0f}%, within ±25% of Large {100*np.mean(np.abs(held)<np.log(1.25)):.0f}%")
