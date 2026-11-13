"""v26.2.3: ground ray + depth for the distance of a base that stands on a surface (``distance.objectDistance``).

DA2 metric depth is right in the near field and squashes beyond about 12 m (a building at 30 m reads 6-12 m). The ground ray of a
base row (``H f q / ((y - horizon) gh)``) has no such squashing, but it gets noisy near the horizon. This module holds the pieces
both the collision pass (item distances) and the world map (object bases) use, so that the map reads exactly what the pass used:

* ``ground_z``: the ground ray in the lens's own geometry: the pixel's ray (equidistant fisheye or pinhole), the pitch the horizon row
  implies, the camera height; it returns the z-depth of the ground point, the quantity the depth map holds. (The first build used the
  pinhole formula ``H f / ((y - horizon) gh)``: under the 118 deg fisheye it is 1.45 times off in the near field and wrong towards the
  image sides, which moved distances of off-axis bases by metres.)
* ``Corrector``: per frame, the walking-region cells give two things, both in the units of the scaled depth (metres):
  ``ref`` (q) = median depth / ground ray in the near field (``refGroundM``; ~1 when the camera height and the horizon are right) and the
  **range correction** rho(d) = (depth / ground ray) / q, binned by depth. rho is ~1 in
  the near field and falls beyond ~12 m (the squash). ``corrected = depth / rho(depth)``: the near field is unchanged. Bins and q are
  smoothed in time (log EMA) and held when a frame has too few samples.
* ``HorizonSigma``: the horizon jitter (rows) measured on the stored horizon track.
* ``resolve``: per base, the fused / ground / depth distance (inverse-variance fusion, sanity gate).

The curve travels in the hazards.json frames (``depthCorrection``: ``{"ref", "sigmaRows", "curve": [[depth m, rho], ...]}``, rounded),
and every consumer works from that rounded dict, so the offline map build reproduces the online one.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np
from engine.core.distfuse import (  # noqa: F401
    MODES,
    SRC_DEPTH,
    SRC_FUSED,
    SRC_GROUND,
    SRC_NAMES,
    correct_depth,
    resolve,
    resolved_mode,
    rho_at,
    settings,
)
from engine.core.distfuse import prior_interp as _prior_interp  # noqa: F401
from engine.core.groundgeom import (  # noqa: F401
    Geometry,
    ground_m,
    ground_pixel,
    ground_point,
    ground_z,
    lateral_at,
    ray_dir,
)
from engine.core.groundgeom import pitch as _pitch  # noqa: F401


class HorizonSigma:
    """Jitter of the horizon (rows) over the last ``horizonWindowSeconds``: the std of the track about its straight-line trend,
    combined with the row quantisation (``rowSigma``)."""

    def __init__(self, cfg: dict, gh: int):
        self.gh = gh
        self.win = float(cfg["horizonWindowSeconds"])
        self.row_sigma = float(cfg["rowSigma"])
        self.h: deque = deque()

    def update(self, t: float, horizon: float) -> float:
        self.h.append((t, horizon * self.gh))
        while self.h and t - self.h[0][0] > self.win + 1e-9:
            self.h.popleft()
        if len(self.h) >= 4:
            tt = np.array([x[0] for x in self.h]) - t
            yy = np.array([x[1] for x in self.h])
            res = yy - np.polyval(np.polyfit(tt, yy, 1), tt)
            s = float(np.std(res))
        else:
            s = 0.0
        return math.hypot(s, self.row_sigma)


class Corrector:
    """Per-frame fit of ``ref`` and the range-correction curve from the walking region (see the module doc)."""

    def __init__(self, cfg: dict, geo: Geometry):
        self.cfg = cfg
        self.geo = geo
        self.gh, self.gw = geo.gh, geo.gw
        self.edges = np.asarray(cfg["binEdgesM"], dtype=float)
        self.min_rows = float(cfg["minRowsBelowHorizon"])
        self.tau = float(cfg["emaSeconds"])
        self.hold = float(cfg["holdSeconds"])
        self.ref: tuple[float, float] | None = None                       # (log q, last t)
        self.bins: dict[int, list[float]] = {}                            # bin -> [log depth, log rho, last t]
        self.prev_t: float | None = None

    @staticmethod
    def _ema(old: float, new: float, a: float) -> float:
        return old + a * (new - old)

    def update(self, t: float, region_mask: np.ndarray | None, dmap: np.ndarray | None, scale: float, horizon: float,
               sigma_rows: float, extra: tuple | None = None) -> dict | None:
        """Fit this frame, smooth, and return the report (rounded; None while there is no ``ref``).

        ``extra`` (v26.2.7) = (depth m, lens ground z m) of wall bases that stand on a surface (``worldmap.face_contact_samples``): they join
        the RANGE BINS only (never ``ref``, which stays the walking region's near field), each counting ``wallSampleWeight`` towards
        ``minBinSamples``, with the weighted median in a bin. The curve then reaches the walls' range, past where the walking region ends.
        The report gets ``"wallSamples": n`` when n > 0."""
        cfg = self.cfg
        dt = 0.0 if self.prev_t is None else max(0.0, t - self.prev_t)
        self.prev_t = t
        n_wall = 0
        a = 1.0 if self.tau <= 0 else 1.0 - math.exp(-dt / self.tau)
        if region_mask is not None and dmap is not None and scale and scale > 0:
            rr, cc = np.nonzero(region_mask)
            below = rr + 0.5 - horizon * self.gh
            keep = below >= self.min_rows
            rr, cc = rr[keep], cc[keep]
            if rr.size:
                dh, dw = dmap.shape
                v = dmap[np.minimum(dh - 1, ((rr + 0.5) / self.gh * dh).astype(int)),
                         np.minimum(dw - 1, ((cc + 0.5) / self.gw * dw).astype(int))].astype(np.float64) * float(scale)
                ok = np.isfinite(v) & (v > 0)
                g = ground_z(self.geo, rr + 0.5, cc + 0.5, horizon)[ok]
                v = v[ok]
                good = np.isfinite(g) & (g > 0)
                v, g = v[good], g[good]
                ratio = v / g
                lo, hi = cfg["refGroundM"]
                near = (g >= lo) & (g <= hi)
                q_now = None
                if int(near.sum()) >= int(cfg["refMinSamples"]):
                    q_now = float(np.median(ratio[near]))
                    if self.ref is None or t - self.ref[1] > self.hold or a >= 1.0:
                        self.ref = (math.log(q_now), t)
                    else:
                        self.ref = (self._ema(self.ref[0], math.log(q_now), a), t)
                if q_now is not None:
                    wts = None
                    if extra is not None and len(extra[0]):
                        ev_, eg_ = np.asarray(extra[0], dtype=np.float64), np.asarray(extra[1], dtype=np.float64)
                        okw = np.isfinite(ev_) & (ev_ > 0) & np.isfinite(eg_) & (eg_ > 0) & (eg_ <= float(cfg["fuseMaxM"]))
                        ev_, eg_ = ev_[okw], eg_[okw]
                        n_wall = int(ev_.size)
                        if n_wall:
                            v = np.concatenate([v, ev_])
                            ratio = np.concatenate([ratio, ev_ / eg_])
                            wts = np.concatenate([np.ones(v.size - n_wall), np.full(n_wall, float(cfg.get("wallSampleWeight", 5)))])
                    idx = np.digitize(v, self.edges)
                    for b in np.unique(idx):
                        sel = idx == b
                        if (float(wts[sel].sum()) if wts is not None else int(sel.sum())) < int(cfg["minBinSamples"]):
                            continue
                        if wts is None:
                            m_v, m_r = float(np.median(v[sel])), float(np.median(ratio[sel]))
                        else:
                            m_v, m_r = _wmedian(v[sel], wts[sel]), _wmedian(ratio[sel], wts[sel])
                        ld, lr = math.log(m_v), math.log(max(1e-3, m_r / q_now))
                        old = self.bins.get(int(b))
                        if old is None or t - old[2] > self.hold or a >= 1.0:
                            self.bins[int(b)] = [ld, lr, t]
                        else:
                            self.bins[int(b)] = [self._ema(old[0], ld, a), self._ema(old[1], lr, a), t]
        if self.ref is not None and t - self.ref[1] > self.hold:
            self.ref = None
        self.bins = {b: s for b, s in self.bins.items() if t - s[2] <= self.hold}
        if self.ref is None:
            return None
        pts = sorted((math.exp(s[0]), math.exp(s[1])) for s in self.bins.values())
        curve, lowest = [], float("inf")
        for d, r in pts:                                               # the squash only grows with range
            lowest = min(lowest, r)
            curve.append([round(d, 2), round(max(float(cfg["rhoMin"]), lowest), 3)])
        rep = {"ref": round(math.exp(self.ref[0]), 3), "sigmaRows": round(float(sigma_rows), 2), "curve": curve}
        if n_wall:
            rep["wallSamples"] = n_wall
        return rep


def _wmedian(x: np.ndarray, w: np.ndarray) -> float:
    """The weighted median: the first sorted value whose cumulative weight reaches half of the total."""
    o = np.argsort(x, kind="stable")
    c = np.cumsum(w[o])
    return float(x[o][int(np.searchsorted(c, 0.5 * c[-1]))])
