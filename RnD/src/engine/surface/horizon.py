"""Horizon: line-fit estimate from the region bounds, and the gravity-pitch horizon."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt

from engine.core.groundgeom import Geometry


def estimate_horizon(
    left: npt.NDArray[np.float64],
    right: npt.NDArray[np.float64],
    config: dict[str, Any],
    bounds: tuple[float, float] = (0.0, 1.0),
) -> float | None:
    """Intersection of lines fitted to the left/right bounds, or None when not credible.

    Each line uses the lowest 70 percent of that side's rows where the bound is
    a real path edge. Rows where a bound is clamped to the image border are
    dropped first: a clamped bound is a crop (the path is wider than the
    picture), not an edge, and would flatten the line. ``bounds`` are the left and right edge of the analysed
    window (a portrait window of the frame: its edges are crops too).
    """
    geo = config["geometry"]
    gh = len(left)
    fits = []
    for bound, clamped in ((left, left <= bounds[0] + 1e-6), (right, right >= bounds[1] - 1e-6)):
        rows = np.flatnonzero(~np.isnan(bound) & ~clamped)
        if rows.size < geo["minRegionRows"]:
            return None
        rows = rows[rows.size - int(math.ceil(0.7 * rows.size)) :]  # noqa: RUF046
        if rows.size < geo["minRegionRows"]:
            return None
        fits.append(np.polyfit((rows + 0.5) / gh, bound[rows], 1))
    (a_l, b_l), (a_r, b_r) = fits
    if not (a_l < -0.02 and a_r > 0.02):  # must converge upward
        return None
    hy = (b_r - b_l) / (a_l - a_r)
    lo, hi = geo["horizonValidRange"]
    return float(hy) if lo <= hy <= hi else None


class HorizonGravity:
    """v26.2.11 (``horizon.source`` "gravity" | "fused"): the horizon row from the camera pitch of the gravity vector.
    The pitch changes
    the horizon by ``f`` rows per radian (the lens's centre slope); the LEVEL (the mount angle) is the slow average of
    (image horizon - gravity
    horizon), a running mean at the start, then a ``levelTauS`` average: gravity gives the fast part, the image the
    slow one.
    "gravity" = that sum; "fused" = the image horizon pulled toward it by ``gravityWeight``."""

    def __init__(self, cfg: dict[str, Any], gh: int, gw: int, hfov_deg: float, projection: str):
        geo = Geometry(gh, gw, hfov_deg, projection, 1.0)
        self.rows_per_deg = (geo.f_eq if geo.fisheye else geo.f_pin) * math.pi / 180.0 / gh
        self.tau = float(cfg.get("levelTauS", 30.0))
        self.weight = float(cfg.get("gravityWeight", 0.5))
        self.lo, self.hi = (float(v) for v in cfg.get("horizonValidRange", [0.25, 0.75]))
        self.level: float | None = None
        self.n = 0
        self.prev_t: float | None = None

    def update(self, t: float, pitch_deg: float, h_img: float, source: str) -> float:
        raw = pitch_deg * self.rows_per_deg  # pitch + = looking up: the horizon moves down
        dt = 0.0 if self.prev_t is None else max(0.0, t - self.prev_t)
        self.prev_t = t
        d = h_img - raw
        self.n += 1
        if self.level is None:
            self.level = d
        else:
            self.level += max(1.0 / self.n, min(1.0, dt / self.tau if self.tau > 0 else 1.0)) * (d - self.level)
        hg = min(self.hi, max(self.lo, self.level + raw))
        return hg if source == "gravity" else h_img + self.weight * (hg - h_img)
