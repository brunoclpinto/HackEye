"""The blocked-ahead rule of the static map: ``BlockedMixin.blocked_ahead`` (composed into ``StaticMap``)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from engine.core.clock import clock_quarter, clock_text

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["BlockedMixin"]


class BlockedMixin:
    """Mixin of ``StaticMap``: the lane-blocked test and the free-direction search. No ``__init__``; the bare
    annotations below only describe the attributes ``blocked_ahead`` reads from ``self``."""

    classes: Any
    conf: Any
    ob: Any
    lane_half: float
    min_conf: Any
    obs_widths: Any
    obs_min_w_frames: Any
    _names: Any
    _blk: Any
    recent_obstacle_points: Callable[[], tuple[npt.NDArray[Any], npt.NDArray[Any]]]

    def blocked_ahead(self, bcfg: dict[str, Any]) -> dict[str, Any] | None:
        """v26.2.12 (``blocked``, review 9, 21.17 s: "inform of blocking area ahead and towards which direction the
        sidewalk continues"), follow-up (O26): the lane (+-lane half width) ahead is blocked by (A) a wall
        (``wallClasses``, fused map cells, within ``aheadM``) covering >= ``widthFrac`` of its lateral bins, or (B) an
        obstacle on the walkway (``obstacle.classes``: the fused map's cells plus the object-base points of the last
        ``recentS`` s, dead-reckoned to now) within ``obstacle.aheadM`` covering >= ``obstacle.widthFrac``. The free
        direction is the ray (every ``angleStepDeg`` within +-``angleDeg``, not 0) with the smallest |angle| whose
        walkable run reaches past the blockage + 0.5 m (and >= ``minClearM``) with no solid cell / obstacle evidence
        within ``freeHalfWidthM`` of it. Returns {kind, share, free, label, blockClock, clock, bearingDeg, clearM,
        cfwd, cright, ...} or None."""
        if self.classes is None:
            return None
        ob = self.ob
        if "_blk" not in self.__dict__:
            names = self._names
            lut: Callable[[str], npt.NDArray[Any]] = lambda key: np.array(  # noqa: E731
                [n in set(bcfg.get(key, ())) for n in names] + [False] * (256 - len(names))
            )
            self._blk = (
                lut("solidClasses"),
                lut("walkableClasses"),
                lut("wallClasses"),
                np.array(
                    [n in set((bcfg.get("obstacle") or {}).get("classes", ())) for n in names]
                    + [False] * (256 - len(names))
                ),
            )
        solid_lut, walk_lut, wall_lut, obs_lut = self._blk
        lane_half = self.lane_half
        min_ahead = float(bcfg.get("minAheadM", 0.4))
        ocfg = bcfg.get("obstacle") or {}
        conf_ok = self.conf >= self.min_conf
        nb = max(2, int(round(2 * lane_half / 0.1)))  # noqa: RUF046

        def lane_share(f: npt.NDArray[Any], r: npt.NDArray[Any], reach: float) -> tuple[float, npt.NDArray[Any]]:
            m = (f > min_ahead) & (f <= reach) & (np.abs(r) <= lane_half)
            hit = np.zeros(nb, dtype=bool)
            hit[np.clip(((r[m] + lane_half) / (2 * lane_half) * nb).astype(np.int64), 0, nb - 1)] = True
            return float(hit.mean()), m

        kind = None
        wmask = wall_lut[self.classes] & conf_ok
        share, m = lane_share(ob.fwd[wmask], ob.right[wmask], float(bcfg.get("aheadM", 3.0)))
        reach = float(bcfg.get("aheadM", 3.0))
        pf = pr = np.zeros(0)
        omask = None
        if share >= float(bcfg.get("widthFrac", 0.7)):
            kind = "wall"
            ef, er = ob.fwd[wmask], ob.right[wmask]
        else:
            reach = float(ocfg.get("aheadM", 6.5))
            omask = obs_lut[self.classes] & conf_ok
            pf, pr = self.recent_obstacle_points()  # type: ignore[assignment]
            ef, er = np.concatenate([ob.fwd[omask], pf]), np.concatenate([ob.right[omask], pr])
            share, m = lane_share(ef, er, reach)
            if share >= float(ocfg.get("widthFrac", 0.5)):
                kind = "obstacle"
        if kind is None:
            return None
        lf, _lr = ef[m], er[m]  # the evidence inside the lane
        near, far = float(lf.min()), float(lf.max())
        wide = (ef > min_ahead) & (ef <= min(reach, near + 1.5)) & (np.abs(er) <= lane_half + 1.5)
        cf, cr = float(ef[wide].mean()), float(er[wide].mean())
        block_q = clock_quarter(math.degrees(math.atan2(cr, cf)))
        # the label: the walkable class under the user (the lane 0.5-2 m ahead, majority)
        lab = "sidewalk"
        under = (ob.fwd > 0.5) & (ob.fwd <= 2.0) & (np.abs(ob.right) <= lane_half) & walk_lut[self.classes]
        if under.any():
            ids, cnt = np.unique(self.classes[under], return_counts=True)
            lab = (bcfg.get("walkableLabels") or {}).get(self._names[int(ids[int(np.argmax(cnt))])], lab)
        out = {
            "kind": kind,
            "share": round(share, 2),
            "label": lab,
            "cfwd": round(cf, 2),
            "cright": round(cr, 2),
            "blockQ": block_q,
            "blockClock": clock_text(block_q),
        }
        # v26.2.14 (``blocked.obstacle.minWidthM``, review 11, 87.67 s: "not at all, it's a small obstacle"): the
        # obstacle kind is only SAID when one obstacle was seen at least this wide (the lateral extent of the frame's
        # obstacle bases) in >= ``minWidthFrames`` of the recent frames
        min_w = getattr(self, "obs_min_w", 0.0)
        out["wideOk"] = (
            kind != "obstacle"
            or min_w <= 0
            or sum(1 for _, w in self.obs_widths if w >= min_w - 1e-9) >= self.obs_min_w_frames
        )
        # the solid map cells and the obstacle evidence, grown by freeHalfWidthM: what a free ray must not touch
        solid = solid_lut[self.classes] & conf_ok
        if omask is None:
            pf, pr = self.recent_obstacle_points()  # type: ignore[assignment]
        if pf.size:
            rr_ = np.rint(ob.orow - pf / ob.cell).astype(np.int64)
            cc_ = np.rint(ob.oc + pr / ob.cell).astype(np.int64)
            okp = (rr_ >= 0) & (rr_ < ob.size) & (cc_ >= 0) & (cc_ < ob.size)
            solid = solid.copy()
            solid[rr_[okp], cc_[okp]] = True
        g = int(math.ceil(float(bcfg.get("freeHalfWidthM", 0.25)) / ob.cell - 1e-9))  # noqa: RUF046
        if g > 0:
            pad = np.pad(solid, g)
            grown = np.zeros_like(solid)
            n = ob.size
            for dy in range(2 * g + 1):
                for dx in range(2 * g + 1):
                    grown |= pad[dy : dy + n, dx : dx + n]
            solid = grown
        walk = walk_lut[self.classes] & (self.conf >= int(float(bcfg.get("walkMinConf", 0.3)) * 255))
        best = None
        step = float(bcfg.get("angleStepDeg", 7.5))
        max_ang = float(bcfg.get("angleDeg", 60.0))
        min_clear = float(bcfg.get("minClearM", 2.0))
        for ang in np.arange(-max_ang, max_ang + 1e-6, step):
            if abs(ang) < 1e-6:
                continue
            a = math.radians(ang)
            k = np.arange(1, int(8.0 / ob.cell))
            rr = np.rint(ob.orow - math.cos(a) * k).astype(np.int64)
            cc = np.rint(ob.oc + math.sin(a) * k).astype(np.int64)
            ok = (rr >= 0) & (rr < ob.size) & (cc >= 0) & (cc < ob.size)
            if not ok.all():
                k, rr, cc = k[ok], rr[ok], cc[ok]
            blocked = solid[rr, cc]
            first_block = int(np.argmax(blocked)) if blocked.any() else len(k)
            wk = walk[rr, cc]
            # the free run: from 0.5 m out, the walkable cells before the first solid cell (gaps of unknown cells up
            # to 0.3 m allowed)
            run = 0
            gap = 0
            for j in range(int(0.5 / ob.cell), first_block):
                if wk[j]:
                    run, gap = j + 1, 0
                else:
                    gap += 1
                    if gap * ob.cell > 0.3:
                        break
            clear = run * ob.cell
            need = max(min_clear, (far + 0.5) / math.cos(a))
            if clear >= need - 1e-9 and (
                best is None
                or abs(ang) < abs(best[1]) - 1e-9
                or (abs(abs(ang) - abs(best[1])) <= 1e-9 and clear > best[0] + 1e-9)
            ):
                best = (clear, float(ang))
        if best is None:
            return {**out, "free": None}
        clear, ang = best  # type: ignore[assignment]
        a = math.radians(ang)
        cq = clock_quarter(ang)  # type: ignore[arg-type]
        j_end = max(0, int(clear / ob.cell) - 1)
        end_r, end_c = (
            int(np.rint(ob.orow - math.cos(a) * (j_end + 1))),
            int(np.rint(ob.oc + math.sin(a) * (j_end + 1))),
        )
        end_name = (
            self._names[int(self.classes[end_r, end_c])]
            if (0 <= end_r < ob.size and 0 <= end_c < ob.size and int(self.classes[end_r, end_c]) < len(self._names))
            else None
        )
        return {
            **out,
            "free": True,
            "endClass": end_name,
            "clearM": round(clear, 1),
            "bearingDeg": ang,
            "clockQ": cq,
            "clock": clock_text(cq),
            "fwd": round(math.cos(a) * clear, 2),
            "right": round(math.sin(a) * clear, 2),
        }
