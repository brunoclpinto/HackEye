"""Depth anchors: per-frame or one-shot metric scale of a relative depth map from the ground under our feet."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from engine.core.types import Region

__all__ = [
    "DepthAnchor",
    "InitialAnchor",
    "PlaneAnchor",
    "PlaneFit",
    "ground_anchor",
    "plane_fit",
]


class DepthAnchor:
    """Per-frame scale of a RELATIVE depth map from the ground under our feet.

    The relative maps match the metric ones up to ONE scale per frame, but that scale drifts from frame to
    frame. Walking-region pixels at least ``motionMinRowsBelowHorizon`` rows below the horizon have a flat-
    ground z-distance ``g`` (uncalibrated camera height, k = 1); ``a_t = median(g / rel)`` maps relative units
    onto that ground metre. Smoothed lightly in log space (``anchorEmaSeconds``); a frame without enough
    cells (``anchorMinCells``) holds the last anchor for ``anchorHoldSeconds``, then there is none.
    """

    def __init__(self, dist_cfg: dict[str, Any]):
        self.min_cells = int(dist_cfg.get("anchorMinCells", 150))
        self.tau_s = float(dist_cfg.get("anchorEmaSeconds", 0.5))
        self.hold_s = float(dist_cfg.get("anchorHoldSeconds", 2.0))
        self.log_a: float | None = None
        self.last_t = -math.inf

    def update(self, t: float, dt: float, raw: float | None, cells: int) -> None:
        if raw is not None and cells >= self.min_cells and math.isfinite(raw) and raw > 0:
            x = math.log(raw)
            if self.log_a is None or t - self.last_t > self.hold_s or self.tau_s <= 0:
                self.log_a = x  # tau 0 = no smoothing
            else:
                self.log_a += (1.0 - math.exp(-max(dt, 0.0) / self.tau_s)) * (x - self.log_a)
            self.last_t = t
        elif self.log_a is not None and t - self.last_t > self.hold_s:
            self.log_a = None

    @property
    def value(self) -> float | None:
        return None if self.log_a is None else math.exp(self.log_a)


class InitialAnchor:
    """One-shot depth anchor (``anchor: "initial"``, DA2 metric): a stable but biased absolute level.

    Collects the per-frame ground ratios (as ``DepthAnchor`` would use) of valid frames (>= ``anchorMinCells``
    cells; invalid frames do not count). The running median is usable from ``initialAnchorMinFrames`` (3) valid
    ratios; at ``initialAnchorFrames`` (6) it is frozen and held for the rest of the run. ``reset()`` starts a
    new collection (path change, only when ``recalibrateOnPathChange``). Same interface as ``DepthAnchor``.
    """

    def __init__(self, dist_cfg: dict[str, Any]):
        self.min_cells = int(dist_cfg.get("anchorMinCells", 150))
        self.n_freeze = int(dist_cfg.get("initialAnchorFrames", 6))
        self.n_min = min(int(dist_cfg.get("initialAnchorMinFrames", 3)), self.n_freeze)
        self.reset()

    def reset(self) -> None:
        self.ratios: list[float] = []
        self.frozen: float | None = None
        self._run: float | None = None

    def update(self, t: float, dt: float, raw: float | None, cells: int) -> None:
        if self.frozen is not None:
            return
        if raw is not None and cells >= self.min_cells and math.isfinite(raw) and raw > 0:
            self.ratios.append(float(raw))
            self._run = float(np.median(self.ratios)) if len(self.ratios) >= self.n_min else None
            if len(self.ratios) >= self.n_freeze:
                self.frozen = self._run

    @property
    def value(self) -> float | None:
        return self.frozen if self.frozen is not None else self._run


def ground_anchor(
    region: Region | None,
    dmap: npt.NDArray[Any],
    horizon: float,
    camera_height_m: float,
    gh: int,
    gw: int,
    f: float,
    min_rows: float,
) -> tuple[float | None, int]:
    """(median of flat-ground z-distance / relative depth, cell count) over walking-region cells."""
    if region is None:
        return None, 0
    rr, cc = np.nonzero(region.mask)
    keep = rr + 0.5 - horizon * gh >= min_rows
    rr, cc = rr[keep], cc[keep]
    if rr.size == 0:
        return None, 0
    dh, dw = dmap.shape
    rel = dmap[
        np.minimum(dh - 1, ((rr + 0.5) / gh * dh).astype(int)), np.minimum(dw - 1, ((cc + 0.5) / gw * dw).astype(int))
    ].astype(float)
    ok = np.isfinite(rel) & (rel > 0.0)
    if not ok.any():
        return None, 0
    g = camera_height_m * f / (rr[ok] + 0.5 - horizon * gh)
    return float(np.median(g / rel[ok])), int(ok.sum())


@dataclass
class PlaneFit:
    height_units: float  # camera height above the fitted plane, in depth units
    pitch_deg: float  # + = looking down
    inliers: int
    fraction: float


def plane_fit(
    region: Region | None,
    dmap: npt.NDArray[Any],
    horizon: float,
    gh: int,
    gw: int,
    f: float,
    min_rows: float,
    hfov_deg: float,
    projection: str,
    dist_cfg: dict[str, Any],
) -> PlaneFit | None:
    """Ground plane through the walking-region cells, from the z-depth map and the pixel rays (None = invalid frame).

    Cells: region cells >= ``min_rows`` below the anchor horizon with finite depth > 0, back-projected to camera
    coordinates (X right, Y down, Z forward): rectilinear X = (u-0.5)W/f z, Y = (v-0.5)H/f z; fisheye (equidistant,
    f = W / hfov rad) ray = (sin t cos p, sin t sin p, cos t), t = r/f, scaled so its Z equals z.
    Fit in normalised form ``Y/Z = c/Z + a X/Z + b`` (plane Y = c + aX + bZ; linear, residuals are image-like and
    independent of range): deterministic RANSAC (3-point, fixed seed) for a clutter-proof start, then least
    squares on the inliers with 3 rounds rejecting residuals > 2.5x the median absolute residual.
    Valid: >= ``anchorMinCells`` inliers, inlier fraction >= ``planeMinInlierFraction`` (0.6), normal within
    ``planeMaxNormalDeg`` (35) of the camera's down axis and the plane below the camera.
    Height h = c / sqrt(1+a^2+b^2); pitch = asin(-b / sqrt(1+a^2+b^2)) (+ = looking down)."""
    if region is None:
        return None
    rr, cc = np.nonzero(region.mask)
    keep = rr + 0.5 - horizon * gh >= min_rows
    rr, cc = rr[keep], cc[keep]
    if rr.size == 0:
        return None
    dh, dw = dmap.shape
    z = dmap[
        np.minimum(dh - 1, ((rr + 0.5) / gh * dh).astype(int)), np.minimum(dw - 1, ((cc + 0.5) / gw * dw).astype(int))
    ].astype(float)
    ok = np.isfinite(z) & (z > 0.0)
    min_cells = int(dist_cfg.get("anchorMinCells", 150))
    if ok.sum() < min_cells:
        return None
    z, px, py = z[ok], cc[ok] + 0.5 - gw / 2.0, rr[ok] + 0.5 - gh / 2.0
    if projection == "fisheye":
        f_eq = gw / math.radians(hfov_deg)
        r = np.hypot(px, py)
        theta = r / f_eq
        c_t = np.cos(theta)
        if np.any(c_t <= 1e-3):
            m = c_t > 1e-3
            z, px, py, r, theta, c_t = z[m], px[m], py[m], r[m], theta[m], c_t[m]
        sin_over_r = np.where(r > 0, np.sin(theta) / np.maximum(r, 1e-12), 0.0)
        xn = sin_over_r * px / c_t  # X/Z, Y/Z of the ray
        yn = sin_over_r * py / c_t
    else:
        xn, yn = px / f, py / f
    n = z.size
    if n < min_cells:
        return None
    w = 1.0 / z
    A = np.stack([w, xn, np.ones(n)], axis=1)  # y_n = c w + a x_n + b
    # --- RANSAC start (deterministic)
    rng = np.random.RandomState(12345)
    tau = float(dist_cfg.get("planeRansacTol", 0.02))
    best, best_cnt = None, -1
    for _ in range(int(dist_cfg.get("planeRansacTrials", 60))):
        idx = rng.choice(n, 3, replace=False)
        try:
            sol = np.linalg.solve(A[idx], yn[idx])
        except np.linalg.LinAlgError:
            continue
        cnt = int(np.count_nonzero(np.abs(A @ sol - yn) <= tau))
        if cnt > best_cnt:
            best, best_cnt = sol, cnt
    if best is None:
        return None
    inl = np.abs(A @ best - yn) <= tau
    sol = best
    for _ in range(3):
        if inl.sum() < 3:
            return None
        sol = np.linalg.lstsq(A[inl], yn[inl], rcond=None)[0]
        res = np.abs(A @ sol - yn)
        thr = max(2.5 * float(np.median(res[inl])), 1e-3)
        new = res <= thr
        if np.array_equal(new, inl):
            break
        inl = new
    n_in = int(inl.sum())
    if n_in < min_cells or n_in / n < float(dist_cfg.get("planeMinInlierFraction", 0.6)):
        return None
    c, a, b = (float(v) for v in sol)
    norm = math.sqrt(1.0 + a * a + b * b)
    if c <= 0 or math.degrees(math.atan(math.hypot(a, b))) > float(dist_cfg.get("planeMaxNormalDeg", 35.0)):
        return None
    return PlaneFit(c / norm, math.degrees(math.asin(max(-1.0, min(1.0, -b / norm)))), n_in, n_in / n)


class PlaneAnchor:
    """One-shot plane anchor (``anchor: "plane"``, DA2 metric): scale = camera height / fitted camera height.

    Each valid plane fit gives s_t = camera_height_m / h_d. The running median is usable from
    ``initialAnchorMinFrames`` (3) valid frames and frozen at ``initialAnchorFrames`` (6); invalid frames do not
    count. ``reset()`` restarts the collection. Also keeps the median pitch and camera height (depth units)."""

    def __init__(self, dist_cfg: dict[str, Any], camera_height_m: float):
        self.camera_height_m = float(camera_height_m)
        self.n_freeze = int(dist_cfg.get("initialAnchorFrames", 6))
        self.n_min = min(int(dist_cfg.get("initialAnchorMinFrames", 3)), self.n_freeze)
        self.reset()

    def reset(self) -> None:
        self.scales: list[float] = []
        self.pitches: list[float] = []
        self.heights: list[float] = []
        self.frozen = False
        self.fit: PlaneFit | None = None

    def update(self, fit: PlaneFit | None) -> None:
        self.fit = fit
        if self.frozen or fit is None or not fit.height_units > 0:
            return
        self.scales.append(self.camera_height_m / fit.height_units)
        self.pitches.append(fit.pitch_deg)
        self.heights.append(fit.height_units)
        self.frozen = len(self.scales) >= self.n_freeze

    def _med(self, v: list[float]) -> float | None:
        return float(np.median(v)) if len(v) >= self.n_min else None

    @property
    def value(self) -> float | None:
        return self._med(self.scales)

    @property
    def pitch_deg(self) -> float | None:
        return self._med(self.pitches)

    @property
    def height_units(self) -> float | None:
        return self._med(self.heights)
