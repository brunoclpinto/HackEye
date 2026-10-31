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

MODES = ("depth", "ground-contact", "ground+depth")
SRC_DEPTH, SRC_GROUND, SRC_FUSED = 0, 1, 2
SRC_NAMES = ("depth", "ground", "fused")


def settings(dist_cfg: dict) -> dict:
    """The ``distance.groundDepth`` block with defaults."""
    g = dict(dist_cfg.get("groundDepth") or {})
    d = {"minRowsBelowHorizon": 4.0, "binEdgesM": [1, 3, 5, 7, 9, 11, 12, 13, 14, 15, 16, 17, 18, 20, 24, 30],
         "minBinSamples": 25, "refGroundM": [2.0, 8.0], "refMinSamples": 80, "emaSeconds": 1.0, "holdSeconds": 2.0,
         "extrapolate": "prior", "priorCurve": [[5.8, 1.0], [12.7, 0.876], [14.4, 0.71], [15.1, 0.58], [16.0, 0.44], [17.6, 0.27]],
         "rhoMin": 0.2, "maxCorrectedM": 45.0, "depthRelErr": 0.12, "rowSigma": 0.5, "sanityFactor": 0.7,
         "fuseMaxM": 40.0, "horizonWindowSeconds": 3.0, "fuse": True, "gate": True}
    d.update(g)
    return d


def resolved_mode(mode: str | None, use_horizon: bool | None) -> str:
    """The effective object distance: with the horizon off there is no ground ray at all."""
    if use_horizon is False:
        return "depth"
    return mode if mode in MODES else "depth"


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


def _prior_interp(d: np.ndarray, cfg: dict) -> np.ndarray:
    p = np.asarray(cfg["priorCurve"], dtype=float)
    return np.interp(np.log(np.maximum(d, 1e-6)), np.log(p[:, 0]), p[:, 1])


def rho_at(d, rep: dict | None, cfg: dict) -> np.ndarray:
    """The range-correction factor at depth ``d`` (m): 1 without a curve, the nearest fitted point's value inside / below it, and beyond
    the farthest fitted point the last value continued by the prior (``extrapolate`` "prior") or held ("last")."""
    d = np.asarray(d, dtype=np.float64)
    curve = None if rep is None else rep.get("curve")
    if not curve:
        return np.ones_like(d)
    c = np.asarray(curve, dtype=np.float64)
    ld = np.log(np.maximum(d, 1e-6))
    rho = np.interp(ld, np.log(c[:, 0]), c[:, 1])
    if cfg["extrapolate"] == "prior":
        far = d > c[-1, 0]
        if far.any():
            p_last = float(_prior_interp(np.array([c[-1, 0]]), cfg)[0])
            ratio = _prior_interp(d, cfg) / max(p_last, 1e-6)
            rho = np.where(far, c[-1, 1] * np.minimum(1.0, ratio), rho)
    return np.maximum(rho, float(cfg["rhoMin"]))


def correct_depth(d, rep: dict | None, cfg: dict):
    """(corrected depth m, rho): ``depth / rho(depth)``, capped at ``maxCorrectedM``."""
    d = np.asarray(d, dtype=np.float64)
    rho = rho_at(d, rep, cfg)
    return np.minimum(d / rho, np.maximum(d, float(cfg["maxCorrectedM"]))), rho


class Geometry:
    """Lens + camera: grid size, HFOV, projection ("fisheye" equidistant or "rectilinear"), camera height (m, without any gait scale)."""

    def __init__(self, gh: int, gw: int, hfov_deg: float, projection: str, cam_h: float):
        self.gh, self.gw, self.hfov, self.fisheye, self.cam_h = gh, gw, float(hfov_deg), projection == "fisheye", float(cam_h)
        self.f_eq = gw / math.radians(self.hfov)
        self.f_pin = (gw / 2.0) / math.tan(math.radians(self.hfov) / 2.0)


def _pitch(geo: Geometry, horizon: float) -> float:
    """The camera pitch (rad, + = looking down) the horizon row implies: the ray of the horizon row on the centre column is level."""
    off = geo.gh / 2.0 - horizon * geo.gh
    return off / geo.f_eq if geo.fisheye else math.atan(off / geo.f_pin)


def ray_dir(geo: Geometry, row_b, col_c):
    """(xn, yn): the normalised camera ray (x right, y down, z = 1 along the optical axis) of grid position (``row_b`` row coordinate,
    ``col_c`` column coordinate, floats, pixel centres at +0.5): the equidistant fisheye's or the pinhole's. nan where a fisheye ray points
    (almost) sideways or backwards."""
    row_b, col_c = np.broadcast_arrays(np.asarray(row_b, dtype=np.float64), np.asarray(col_c, dtype=np.float64))
    px, py = col_c - geo.gw / 2.0, row_b - geo.gh / 2.0
    if geo.fisheye:
        r = np.hypot(px, py)
        theta = r / geo.f_eq
        ct = np.cos(theta)
        with np.errstate(divide="ignore", invalid="ignore"):
            k = np.where(r > 0, np.tan(theta) / np.maximum(r, 1e-12), 1.0 / geo.f_eq)
        xn, yn = k * px, k * py
        ok = ct > 1e-3
        return np.where(ok, xn, np.nan), np.where(ok, yn, np.nan)
    return px / geo.f_pin, py / geo.f_pin


def ground_z(geo: Geometry, row_b, col_c, horizon: float, cam_h: float | None = None):
    """z-depth (m, along the optical axis) of the ground point seen at grid position (``row_b`` row coordinate, ``col_c`` column coordinate,
    both float, pixel centres at +0.5), for a flat floor ``cam_h`` (default ``geo.cam_h``) below the camera and the horizon at ``horizon``
    (fraction of the height; it fixes the pitch: the ray of the horizon row on the centre column is level). nan above the horizon."""
    xn, yn = ray_dir(geo, row_b, col_c)
    phi = _pitch(geo, horizon)
    h = geo.cam_h if cam_h is None else float(cam_h)
    down = yn * math.cos(phi) + math.sin(phi)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(down > 1e-4, h / down, np.nan)


def ground_point(geo: Geometry, row_b, col_c, horizon: float, cam_h: float | None = None):
    """v26.2.7: the floor point seen at grid position (``row_b``, ``col_c``): (forward m, right m) in the level frame of the camera (the
    horizon's pitch removed; camera axis, no body offset). forward = z (cos phi - yn sin phi), right = xn z. nan above the horizon. This is
    the ONE lens ground geometry of the map's surfaces, the object bases and the items (the collision pass's old pinhole formulas are
    1.2 - 1.8 times off on the 118 deg fisheye)."""
    xn, yn = ray_dir(geo, row_b, col_c)
    z = ground_z(geo, row_b, col_c, horizon, cam_h)
    phi = _pitch(geo, horizon)
    return z * (math.cos(phi) - yn * math.sin(phi)), xn * z


def ground_pixel(geo: Geometry, fwd, right, horizon: float, cam_h: float | None = None):
    """v26.2.7: the exact inverse of ``ground_point``: the float grid position (row coordinate, column coordinate) that sees the floor point
    (``fwd`` m forward, ``right`` m right). nan where the point is not in front of the camera."""
    fwd, right = np.broadcast_arrays(np.asarray(fwd, dtype=np.float64), np.asarray(right, dtype=np.float64))
    phi = _pitch(geo, horizon)
    h = geo.cam_h if cam_h is None else float(cam_h)
    cp, sp = math.cos(phi), math.sin(phi)
    z = fwd * cp + h * sp
    y = h * cp - fwd * sp
    with np.errstate(divide="ignore", invalid="ignore"):
        ok = z > 1e-6
        xn, yn = np.where(ok, right / z, np.nan), np.where(ok, y / z, np.nan)
        if geo.fisheye:
            rho = np.hypot(xn, yn)
            r = np.arctan(rho) * geo.f_eq
            k = np.where(rho > 0, r / np.maximum(rho, 1e-12), geo.f_eq)
            px, py = k * xn, k * yn
        else:
            px, py = xn * geo.f_pin, yn * geo.f_pin
    return py + geo.gh / 2.0, px + geo.gw / 2.0


def lateral_at(geo: Geometry, row_b, col_c, fwd, horizon: float):
    """v26.2.7: the right offset (m, camera axis) of the pixel's ray at the forward distance ``fwd``: xn fwd / (cos phi - yn sin phi)."""
    xn, yn = ray_dir(geo, row_b, col_c)
    phi = _pitch(geo, horizon)
    with np.errstate(divide="ignore", invalid="ignore"):
        return xn * np.asarray(fwd, dtype=np.float64) / (math.cos(phi) - yn * math.sin(phi))


def ground_m(geo: Geometry, row_b, col_c, horizon: float, rep: dict | None, sigma_rows: float | None = None):
    """The ground ray in depth metres, ``ref x ground_z`` (nan without ``ref``). With ``sigma_rows``: also its 1-sigma (m) from a base-row error."""
    z = ground_z(geo, row_b, col_c, horizon)
    if rep is None:
        return np.full_like(z, np.nan), np.full_like(z, np.nan)
    q = float(rep["ref"])
    if sigma_rows is None:
        return q * z, None
    hi, lo = ground_z(geo, np.asarray(row_b) - sigma_rows, col_c, horizon), ground_z(geo, np.asarray(row_b) + sigma_rows, col_c, horizon)
    with np.errstate(invalid="ignore"):
        sg = np.where(np.isnan(hi), np.abs(q * z - q * lo), np.abs(hi - lo) / 2.0 * q)
    return q * z, sg


def resolve(d_dep, ground, sigma_g, rows_below, contact, rep: dict | None, cfg: dict, mode: str):
    """Distance of each base: ``d_dep`` the scaled depth (m), ``ground`` its ground ray in depth metres and ``sigma_g`` its 1-sigma (m, from the
    horizon jitter and row quantisation), ``rows_below`` the base row's distance under the horizon (grid rows), ``contact`` the base stands on a surface. Returns (distance m, source code array).

    * ``depth``: the depth. ``ground-contact``: the ground ray for a base in contact inside the band (else the depth).
    * ``ground+depth``: the depth is range-corrected; a base in contact inside the band (rows_below >= minRowsBelowHorizon, ground ray <=
      fuseMaxM) is fused with the ground ray by inverse variance (ground: ``sigma_g``, depth: depthRelErr / rho of its distance); finally a base in contact cannot be nearer than ``sanityFactor`` x the ground ray: the ground ray wins."""
    d_dep = np.asarray(d_dep, dtype=np.float64)
    src = np.full(d_dep.shape, SRC_DEPTH, dtype=np.int8)
    if rep is None or mode == "depth":
        return d_dep.copy(), src
    rb = np.asarray(rows_below, dtype=np.float64)
    G = np.asarray(ground, dtype=np.float64)
    band = np.asarray(contact, dtype=bool) & np.isfinite(G) & (rb >= float(cfg["minRowsBelowHorizon"])) & (G <= float(cfg["fuseMaxM"]))
    if mode == "ground-contact":
        return np.where(band, G, d_dep), np.where(band, SRC_GROUND, SRC_DEPTH).astype(np.int8)
    d_cor, rho = correct_depth(d_dep, rep, cfg)
    with np.errstate(divide="ignore", invalid="ignore"):
        sg = np.maximum(np.asarray(sigma_g, dtype=np.float64), 1e-3)
        sd = d_cor * float(cfg["depthRelErr"]) / np.maximum(rho, 0.25)
        wg, wd = 1.0 / (sg * sg), 1.0 / (sd * sd)
        fused = (G * wg + d_cor * wd) / (wg + wd)
    if not cfg.get("fuse", True):                      # variants: the range correction alone (and the gate)
        band = band & False
    dist = np.where(band, fused, d_cor)
    src = np.where(band, SRC_FUSED, SRC_DEPTH).astype(np.int8)
    gate = (np.asarray(contact, dtype=bool) & np.isfinite(G) & (rb >= float(cfg["minRowsBelowHorizon"])) & (G <= float(cfg["fuseMaxM"]))
            & (dist < float(cfg["sanityFactor"]) * G)) if cfg.get("gate", True) else np.zeros(dist.shape, dtype=bool)
    dist = np.where(gate, G, dist)
    src = np.where(gate, SRC_GROUND, src).astype(np.int8)
    return dist, src
