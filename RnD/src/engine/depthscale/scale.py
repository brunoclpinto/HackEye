"""Depth scale: the gait-calibrated level of the anchored depth, per-item depth and the ground+depth distance."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import numpy.typing as npt

from engine.core import distfuse, groundgeom

if TYPE_CHECKING:
    from engine.core.groundgeom import Geometry
    from engine.core.types import Item, Track

__all__ = ["DepthScale", "ground_depth_distance", "item_depth_m"]


def item_depth_m(it: Item, dmap: npt.NDArray[Any], gh: int, gw: int, lowest_frac: float) -> float | None:
    """Median metric depth under the lowest ``lowest_frac`` of the item's rows (component pixels, mapped by
    normalised coordinates onto the depth grid); None without a valid pixel."""
    # a lane part stands where its base is, not where the whole building's lowest rows are
    if it.depth_cells is not None:
        rr, cc = it.depth_cells
    else:
        mask, c0, r0 = cast("tuple[Any, Any, Any]", it.shape)
        rr, cc = np.nonzero(mask)
        rr = rr + r0
        cc = cc + c0
    if rr.size == 0:
        return None
    h = int(rr.max() - rr.min() + 1)
    keep = rr >= rr.max() + 1 - max(1, int(math.ceil(lowest_frac * h)))  # noqa: RUF046
    dh, dw = dmap.shape
    dr = np.minimum(dh - 1, ((rr[keep] + 0.5) / gh * dh).astype(int))
    dc = np.minimum(dw - 1, ((cc[keep] + 0.5) / gw * dw).astype(int))
    v = dmap[dr, dc].astype(float)
    v = v[np.isfinite(v) & (v > 0.0)]
    return None if v.size == 0 else float(np.median(v))


def ground_depth_distance(
    it: Item,
    tr: Track,
    grid: npt.NDArray[Any],
    surf_lut: npt.NDArray[Any],
    horizon: float,
    geo: Geometry,
    gh: int,
    rep: dict[str, Any],
    cfg: dict[str, Any],
    mode: str,
) -> float:
    """v26.2.3: the distance of an item from its scaled depth and the ground ray of its base (``distfuse.resolve``);
    sets ``raw_depth_m`` / ``ground_m`` / ``dist_source``. A base is in contact when it is not clipped and the pixel
    below it is a surface class."""
    contact = (
        (not it.clipped)
        and 0 <= it.base_row < gh - 1
        and it.base_col >= 0
        and bool(surf_lut[grid[it.base_row + 1, it.base_col]])
    )
    y = tr.contact_s if tr.contact_s is not None else it.contact_y
    rows_below = (y - horizon) * gh
    col_c = (it.base_col if it.base_col >= 0 else geo.gw // 2) + 0.5
    g_arr, sg_arr = groundgeom.ground_m(
        geo, np.array([y * gh]), np.array([col_c]), horizon, rep, float(rep["sigmaRows"])
    )
    g = float(g_arr[0]) if rows_below > 0 else float("nan")
    d, src = distfuse.resolve([it.depth_m], [g], sg_arr, [rows_below], [contact], rep, cfg, mode)
    it.raw_depth_m = it.depth_m
    it.ground_m = g if (contact and math.isfinite(g) and rows_below >= cfg["minRowsBelowHorizon"]) else None
    it.dist_source = distfuse.SRC_NAMES[int(src[0])]
    return float(d[0])


class DepthScale:
    """Absolute level ``c`` of the anchored depth (``a_t * rel``, ground-metre units): a dimensionless
    correction, gait calibrated.

    Depth maps are z-depth (planar, along the optical axis), so walking along the axis a static witness's
    anchored depth falls at ``v / c`` with ``v = cadence * step length`` whatever its bearing (no cosine
    factor); one sample is ``v / r`` with ``r`` the closing rate of the witness's anchored depth (without
    ``c``, so no feedback). The bearing gate only limits the effect of a heading off the optical axis.
    Per frame the median over the witnesses is one sample; the estimate is the median of the samples of the
    last ``calibrationWindowSeconds`` (first one at once, later ones blended in log space with the
    ``_Scale`` time constant) and the applied level slews at <= ``scaleMaxChangePerSecond``.
    ``value`` is None until the first estimate (the caller then uses the ground scale k).
    Never uses the ground closing speeds.
    """

    def __init__(self, ego_cfg: dict[str, Any], dist_cfg: dict[str, Any]):
        self.window_s = float(ego_cfg.get("calibrationWindowSeconds", 20.0))
        self.min_samples = int(dist_cfg.get("depthLevelMinSamples", ego_cfg.get("calibrationMinSamples", 12)))
        self.tau_min_s = float(ego_cfg.get("calibrationEmaMinSeconds", 3.0))
        self.tau_s = float(ego_cfg.get("calibrationEmaSeconds", 40.0))
        self.max_rate = float(ego_cfg.get("scaleMaxChangePerSecond", 0.25))
        self.lo, self.hi = dist_cfg.get("depthLevelRange", [0.3, 5.0])
        self.max_bearing = float(dist_cfg.get("depthWitnessMaxBearingDeg", 40.0))
        self.min_speed = float(dist_cfg.get("depthWitnessMinEgoSpeed", 0.5))
        self.freeze = False  # "freeze" level mode: first estimate is held for the run
        self.age_s = 0.0
        self.samples: list[tuple[float, float]] = []
        self.target: float | None = None
        self.applied: float | None = None

    def sample(self, ego_speed: float | None, witnesses: list[tuple[float, float]]) -> float | None:
        """witnesses = [(bearing deg, closing rate of the anchored depth)]; the frame's level sample or None."""
        if ego_speed is None or ego_speed < self.min_speed:
            return None
        vals = [ego_speed / r for b, r in witnesses if r > 0 and abs(b) <= self.max_bearing]
        return float(np.median(vals)) if vals else None

    def update(self, t: float, sample: float | None, dt: float, start: float | None = None) -> None:
        """``start`` (freeze mode): the level in use before the first estimate; ``applied`` then ramps from it
        to the frozen target at the slew limit and the target never changes again."""
        if self.freeze and self.target is not None:
            sample = None  # frozen: no further estimates
        if sample is not None and math.isfinite(sample) and sample > 0:
            self.samples.append((t, sample))
        self.samples = [x for x in self.samples if x[0] >= t - self.window_s - 1e-9]
        if len(self.samples) >= self.min_samples and not (self.freeze and self.target is not None):
            inst = min(self.hi, max(self.lo, float(np.median([x[1] for x in self.samples]))))
            if self.target is None:
                self.target = inst
                self.applied = start if (self.freeze and start is not None and start > 0) else inst
            else:
                self.age_s += max(dt, 0.0)
                tau = min(self.tau_s, max(self.tau_min_s, self.age_s))
                a = 1.0 - math.exp(-max(dt, 0.0) / tau)
                self.target = math.exp(math.log(self.target) + a * (math.log(inst) - math.log(self.target)))
        if self.target is not None and self.applied != self.target:
            lim = self.max_rate * max(dt, 0.0)
            self.applied = math.exp(
                math.log(cast("float", self.applied))
                + max(-lim, min(lim, math.log(self.target) - math.log(cast("float", self.applied))))
            )

    @property
    def value(self) -> float | None:
        return self.applied

    @property
    def holding(self) -> bool:
        """Freeze mode and the ramp to the frozen level is done."""
        return (
            self.freeze
            and self.target is not None
            and math.isclose(cast("float", self.applied), self.target, rel_tol=1e-9)
        )
