"""The collision pass's online static map: ``StaticMap`` (the fused world map as the static rules read it) and the two
item helpers."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from engine.core.clock import clock_from_bearing, clock_quarter, clock_text, pan_from_bearing
from engine.worldmap import faceedge
from engine.worldmap.blocked import BlockedMixin

if TYPE_CHECKING:
    from engine.core.types import Item, Track

__all__ = ["StaticMap", "mute_solid", "set_position"]


def mute_solid(it: Item, smap: StaticMap | None) -> None:
    """``insideSolid.mode`` "suppress" (the v26.2.2 first design, kept for A/B): an item inside / behind a wall
    face gets no role, speech, beeps or proximity sound. The shipped mode "snap" corrects its position instead
    (``StaticMap.snap_solid``)."""
    if smap is None or smap.solid_mode != "suppress" or not it.inside_solid:
        return
    it.role, it.urgency, it.collision, it.summary_ok, it.proximity, it.speak = (
        "none",
        "none",
        False,
        False,
        False,
        False,
    )


def set_position(it: Item, fwd: float, right: float) -> None:
    """Move an item to (forward, right) metres: bearing, clock and pan follow; the image measurement is kept in
    ``image_dl`` (first call)."""
    bearing = math.degrees(math.atan2(right, fwd))
    if it.image_dl is None:
        it.image_dl = (it.distance_m, it.lateral_m, it.bearing, it.clock, it.clock_q, it.clock_text, it.pan)
    it.distance_m, it.lateral_m, it.bearing = fwd, right, bearing
    it.clock = clock_from_bearing(bearing)
    it.clock_q = clock_quarter(bearing)
    it.clock_text = clock_text(it.clock_q)
    it.pan = pan_from_bearing(bearing)


class StaticMap(BlockedMixin):
    """The collision pass's online world map (``worldmap.WorldMap``, causal: this frame and the past) and what
    the static rules read from it.  Per static item: its footprint = the map cells of its own ground-base
    pixels (the pixels the map projects: the lowest pixel of each vertical run of the item, at its depth),
    grown by ``mapFootprintRadiusM``. The item's cells are the fused map's object cells of its family (spoken
    label) on that footprint with a fused confidence >= ``mapMinConf`` (a cell seen in two frames, not a
    one-frame blip). Those inside the walking corridor (|lateral| <= laneHalfWidthM, ahead > 0) make it a
    danger; the nearest one is the item's distance, lateral, bearing and clock. A static danger that is
    clipped / leaves the bottom of the image is followed on in the map (``ghost``): its cells are looked up
    again at the dead-reckoned position until they are passed or decayed."""

    classes: Any
    conf: Any
    solid: Any
    solid_ghost: Any
    wall_solid: Any

    def __init__(
        self,
        wmod: Any,
        grids: Any,
        times: Any,
        class_names: Any,
        config: dict[str, Any],
        settings: Any,
        lat_off: float,
        projection: str,
        source: str,
        lane_half: float,
        step_len: float,
        obj_mode: str = "depth",
        wcfg: dict[str, Any] | None = None,
    ) -> None:
        roles = config["roles"]
        wcfg = wcfg if wcfg is not None else wmod.load_config()
        wsettings = {
            "hfovDeg": settings.hfov_deg,
            "cameraHeightM": settings.camera_height_m,
            "lateralOffsetM": lat_off,
            "projection": projection,
            "distanceSource": source,
            "objectDistance": obj_mode,
            "useHorizon": bool(getattr(settings, "use_horizon", True)),
        }
        self.wm = wmod.WorldMap(grids, times, class_names, None, wsettings, config, wcfg, None)
        self.ob = self.wm.observer
        self.object_kind = wmod.KIND_OBJECT
        ob = self.ob
        self.cell = ob.cell
        self.step_len = step_len
        # the corridor the map judges
        self.corr_full = (ob.fwd > 0.0) & (np.abs(ob.right) <= lane_half + float(roles.get("mapCorridorMarginM", 0.0)))
        self.lane_half = lane_half
        self.min_conf = int(math.ceil(float(roles.get("mapMinConf", 0.7)) * 255.0 - 1e-9))  # noqa: RUF046
        # the image already confirmed the item
        self.ghost_conf = int(math.ceil(float(roles.get("mapGhostMinConf", 0.3)) * 255.0 - 1e-9))  # noqa: RUF046
        self.rad = max(0, int(round(float(roles.get("mapFootprintRadiusM", 0.3)) / ob.cell)))  # noqa: RUF046
        yy, xx = np.mgrid[-self.rad : self.rad + 1, -self.rad : self.rad + 1]
        self.disk = (yy * yy + xx * xx) <= self.rad * self.rad + 0.5
        self.image_fallback = bool(roles.get("mapImageFallback", True))
        # wall-like classes the map judges (face / edge test)
        self.judged = frozenset(roles.get("mapJudgedClasses", ()))
        isd = roles.get("insideSolid") or {}
        self.solid_mode = str(isd.get("mode", "off"))  # "snap" | "suppress" | "off"
        self.solid_on = self.solid_mode in ("snap", "suppress")
        self.solid_depth = float(isd.get("solidDepthM", 0.5))
        self.solid_rays = max(1, int(isd.get("minRayCells", 2)))
        self.wall_lut = np.zeros(256, dtype=bool)
        for cid, name in enumerate(class_names):
            if name in self.judged:
                self.wall_lut[cid] = True
        self.wall_solid = None
        self.ghost_s = float(roles.get("mapGhostSeconds", 2.0))
        self.ghost_near_m = float(roles.get("mapGhostNearM", 2.0))
        labels = config.get("spokenLabels", {})
        self.labels = labels
        self.fam: dict[str, npt.NDArray[Any]] = {}
        for cid, name in enumerate(class_names):
            if self.wm.kind[cid] == self.object_kind:
                self.fam.setdefault(labels.get(name, name.replace("-", " ")), np.zeros(256, dtype=bool))[cid] = True
        self._names = list(class_names)
        # v26.2.12 follow-up (O26): obstacle-class base points of the last recentS s
        bk = config.get("blocked") or {}
        ocfg = bk.get("obstacle") or {}
        self.obs_lut = np.zeros(256, dtype=bool)
        for cid, name in enumerate(class_names):
            if name in set(ocfg.get("classes", ())):
                self.obs_lut[cid] = True
        self.obs_recent_s = float(ocfg.get("recentS", 0.7))
        self.obs_on = bool(bk.get("enabled", False)) and bool(self.obs_lut.any())
        self.obs_hist: list[
            tuple[float, npt.NDArray[Any], npt.NDArray[Any]]
        ] = []  # (t, world x, world y) of the base points
        # v26.2.14: the obstacle kind needs one obstacle this wide ...
        self.obs_min_w = float(ocfg.get("minWidthM", 0.0))
        # ... seen in this many of the recent frames
        self.obs_min_w_frames = int(ocfg.get("minWidthFrames", 2))
        # (t, lateral extent m of the frame's obstacle-class bases within reach)
        self.obs_widths: list[tuple[float, float]] = []
        self.obs_reach = float(ocfg.get("aheadM", 6.5))
        self.times = times
        fe = roles.get("faceEdge") or {}
        # v26.2.2 phase A: diagnostics only, default off
        self.fe_cfg = faceedge.settings(fe) if fe.get("enabled") else None
        self.fe_lines: dict[str, Any] | None = None
        self.stationary = False
        self.fe_res: dict[Any, Any] = {}
        self._fe_cache: dict[Any, Any] = {}
        self.ms = 0.0
        self.classes = self.conf = self.solid = None
        self.pose = (0.0, 0.0, 0.0)
        self.b_rr = self.b_cc = self.b_row = self.b_col = np.zeros(0, dtype=np.int64)

    def update(self, i: int, frame: dict[str, Any], dmap: Any, grid: npt.NDArray[Any]) -> None:
        """Fuse frame i (pose, observation, votes, snapshot) and index the object-base points of its image."""
        frame = self.wm.resolve_frame(frame)  # v26.2.5: no depth scale yet -> the last known one
        _, self.classes, self.conf, self.ms = self.wm.step(i, frame, dmap)
        self.frame_i = i
        self.stationary = bool((frame.get("ego") or {}).get("stationary"))
        self.fe_lines, self.fe_res, self._fe_cache = None, {}, {}
        self.pose = self.wm.last_pose
        is_obj = self.wm.kind[self.classes] == self.object_kind
        self.solid = is_obj & (self.conf >= self.min_conf)
        self.solid_ghost = is_obj & (self.conf >= self.ghost_conf)
        # solid = fused wall-like cells
        self.wall_solid = self.wall_lut[self.classes] & (self.conf >= self.min_conf) if self.solid_on else None
        ob = self.ob
        rr, cc, dist, lat = ob.object_bases(grid, frame, dmap)
        row = ob.orow - np.rint(dist / ob.cell).astype(np.int64)
        col = ob.oc + np.rint(lat / ob.cell).astype(np.int64)
        ok = (row >= 0) & (row < ob.size) & (col >= 0) & (col < ob.size)
        self.b_rr, self.b_cc, self.b_row, self.b_col = rr[ok], cc[ok], row[ok], col[ok]
        # v26.2.12 follow-up (O26): keep the obstacle-class bases in world coordinates for a short while
        if self.obs_on:
            t = float(self.times[i])
            cls = grid[self.b_rr, self.b_cc]
            m = self.obs_lut[np.minimum(cls, 255)]
            fwd = (ob.orow - self.b_row[m]) * ob.cell
            right = (self.b_col[m] - ob.oc) * ob.cell
            x, y, th = self.pose
            s_, c_ = math.sin(math.radians(th)), math.cos(math.radians(th))
            self.obs_hist.append((t, x + s_ * fwd + c_ * right, y + c_ * fwd - s_ * right))
            self.obs_hist = [h for h in self.obs_hist if h[0] >= t - self.obs_recent_s - 1e-9]
            near = (fwd > 0.0) & (fwd <= self.obs_reach) & (np.abs(right) <= self.lane_half + 1.0)
            self.obs_widths.append((t, float(right[near].max() - right[near].min()) if near.sum() >= 2 else 0.0))
            self.obs_widths = [w for w in self.obs_widths if w[0] >= t - self.obs_recent_s - 1e-9]

    def recent_obstacle_points(self) -> tuple[npt.NDArray[Any], npt.NDArray[Any]]:
        """The obstacle-class base points of the last ``recentS`` s in the current ego frame (forward m, right m): the
        world points, seen from the pose now."""
        if not getattr(self, "obs_hist", None):
            return np.zeros(0), np.zeros(0)
        x, y, th = self.pose
        s_, c_ = math.sin(math.radians(th)), math.cos(math.radians(th))
        wx = np.concatenate([h[1] for h in self.obs_hist]) - x
        wy = np.concatenate([h[2] for h in self.obs_hist]) - y
        return wx * s_ + wy * c_, wx * c_ - wy * s_

    # -- solid areas (v26.2.2) -----------------------------------------------------------------------------
    def solid_border(self, fwd: float, right: float) -> tuple[float, float] | None:
        """If the map point lies inside solid cells of the wall-like classes (or behind a confirmed face: >=
        ``minRayCells`` consecutive solid cells on the ray from us) by more than ``solidDepthM`` along its own
        bearing, the point where that ray first enters the solid: the near border (forward m, right m). None when the
        point is not inside / behind a solid area."""
        if self.wall_solid is None or fwd <= 0.0:
            return None
        ob = self.ob
        dist = math.hypot(fwd, right)
        n = int(dist / ob.cell)
        if n < 4 + self.solid_rays:
            return None
        k = np.arange(4, n + 1)
        rr = np.rint(ob.orow - fwd / dist * k).astype(np.int64)
        cc = np.rint(ob.oc + right / dist * k).astype(np.int64)
        ok = (rr >= 0) & (rr < ob.size) & (cc >= 0) & (cc < ob.size)
        hit = np.zeros(k.size, dtype=bool)
        hit[ok] = self.wall_solid[rr[ok], cc[ok]]
        if self.solid_rays > 1:
            run = (
                np.convolve(hit.astype(np.int8), np.ones(self.solid_rays, dtype=np.int8), mode="valid")
                >= self.solid_rays
            )
            idx = np.flatnonzero(run)
        else:
            idx = np.flatnonzero(hit)
        if not idx.size:
            return None
        k0 = int(k[idx[0]])
        if dist - k0 * ob.cell <= self.solid_depth:
            return None
        return fwd / dist * k0 * ob.cell, right / dist * k0 * ob.cell

    def point_in_solid(self, fwd: float, right: float) -> bool:
        return self.solid_border(fwd, right) is not None

    def snap_solid(self, it: Item) -> None:
        """v26.2.2 (user decision): an item whose map position is inside / behind a wall face is a depth error, not an
        impossible warning: it is moved along its own bearing to the near border of the solid area and every later
        rule (steps, clock, role, speech, beeps) sees the corrected point. Wall-like items are measured at their own
        face and never count against it."""
        if not self.solid_on or it.ghost or it.class_name in self.judged:
            return
        b = self.solid_border(it.distance_m, it.lateral_m)
        if b is None:
            return
        it.inside_solid = True
        if self.solid_mode == "snap":
            it.raw_distance_m = it.distance_m
            fwd, right = b
            bearing = math.degrees(math.atan2(right, fwd))
            it.distance_m, it.lateral_m, it.bearing = fwd, right, bearing
            it.clock, it.clock_q = clock_from_bearing(bearing), clock_quarter(bearing)
            it.clock_text = clock_text(it.clock_q)
            it.pan = pan_from_bearing(bearing)
            it.solid_corrected = True

    # -- measurement ---------------------------------------------------------------------------------------
    def _lut(self, it: Item) -> npt.NDArray[Any] | None:
        return self.fam.get(self.labels.get(it.class_name, it.class_name.replace("-", " ")))

    # full: the ghost's search (whole corridor, lower confidence)
    def _corridor_cells(
        self, patch: Any, lut: npt.NDArray[Any], r0: int, c0: int, full: bool = False
    ) -> tuple[Any, Any, int, int]:
        """(forward m, right m, corridor count, family count) of the nearest corridor cell of the family inside the
        boolean ``patch`` (offset r0, c0); the position is None when no cell of the family is in the corridor."""
        sl = (slice(r0, r0 + patch.shape[0]), slice(c0, c0 + patch.shape[1]))
        fam = patch & (self.solid_ghost if full else self.solid)[sl] & lut[self.classes[sl]]
        nf = int(np.count_nonzero(fam))
        inc = fam & self.corr_full[sl]
        n = int(np.count_nonzero(inc))
        if not n:
            return None, None, 0, nf
        fwd, right = self.ob.fwd[sl][inc], self.ob.right[sl][inc]
        k = int(np.argmin(fwd + 1e-3 * np.abs(right)))
        return float(fwd[k]), float(right[k]), n, nf

    def _apply(self, it: Item, fwd: float, right: float, n: int) -> None:
        set_position(it, fwd, right)
        it.map_cells = n
        x, y, th = self.pose
        s_, c_ = math.sin(math.radians(th)), math.cos(math.radians(th))
        it.map_world = (x + s_ * fwd + c_ * right, y + c_ * fwd - s_ * right)
        x, y, th = self.pose
        s_, c_ = math.sin(math.radians(th)), math.cos(math.radians(th))
        it.map_world = (x + s_ * fwd + c_ * right, y + c_ * fwd - s_ * right)

    def _footprint(self, it: Item, lut: Any) -> Any:
        """(footprint mask, row0, col0) of a static item's ground-base pixels on the map, grown by the footprint radius;
        None if it has none."""
        if lut is None or it.shape is None or not self.b_rr.size:
            return None
        mask, c0, r0 = it.shape
        rb, cb = self.b_rr - r0, self.b_cc - c0
        ok = (rb >= 0) & (rb < mask.shape[0]) & (cb >= 0) & (cb < mask.shape[1])
        ok[ok] = mask[rb[ok], cb[ok]]
        if not ok.any():
            return None
        row, col = self.b_row[ok], self.b_col[ok]
        R, size = self.rad, self.ob.size
        pr0, pr1 = max(0, int(row.min()) - R), min(size, int(row.max()) + R + 1)
        pc0, pc1 = max(0, int(col.min()) - R), min(size, int(col.max()) + R + 1)
        fp = np.zeros((pr1 - pr0, pc1 - pc0), dtype=bool)
        fp[row - pr0, col - pc0] = True
        if R:
            fp = ndimage.binary_dilation(fp, structure=self.disk)
        return fp, pr0, pc0

    def faceedge(self, it: Item) -> None:
        """The face / edge test (``roles.faceEdge``) on the corridor cells (the full +-laneHalfWidthM corridor, fused
        confidence >= ``mapMinConf``) of a static item's family on its footprint. Sets ``it.face_edge`` (the verdict
        and its numbers, the wall lines, the free-space contradictions, the image rule's inputs; it goes into
        hazards.json) and ``self.fe_res[track_id]`` (per-cell results). ``measure`` judges on it."""
        it.face_edge = None
        if self.fe_cfg is None or it.group != "static":
            return
        lut = self._lut(it)
        fpr = self._footprint(it, lut)
        if fpr is None:
            return
        fp, pr0, pc0 = fpr
        sl = (slice(pr0, pr0 + fp.shape[0]), slice(pc0, pc0 + fp.shape[1]))
        fam_full = self.solid & lut[self.classes]  # type: ignore[index]
        cand = np.zeros_like(fam_full)
        cand[sl] = fp & fam_full[sl] & self.corr_full[sl]
        if not cand.any():
            return
        cfg = self.fe_cfg
        key = id(lut)
        if key not in self._fe_cache:
            fam = fam_full & (self.ob.fwd <= cfg["maxAheadM"])
            orient, _ = faceedge.local_orientation(fam, self.cell, cfg)
            self._fe_cache[key] = (fam, faceedge.fit_wall_lines(fam, self.ob.fwd, self.ob.right, cfg), orient)
        fam, lines, orient = self._fe_cache[key]
        res = faceedge.classify(cand, fam, self.ob.fwd, self.ob.right, self.cell, cfg, lines, orient)
        out = faceedge.summarize(res, cfg)
        out["lines"] = faceedge.lines_json(lines)
        # for the Lab's wall-line view (capped)
        for name, code in (("faceCells", faceedge.FACE), ("edgeCells", faceedge.EDGE)):
            k = np.flatnonzero(res["verdict"] == code)[:60]
            if k.size:
                out[name] = [[round(float(res["fwd"][j]), 2), round(float(res["right"][j]), 2)] for j in k]
        out["stationary"] = self.stationary
        out["imageLaneHit"] = bool(it.lane_hit)
        out["imageAlongPath"] = bool(it.along_path)
        it.face_edge = out
        self.fe_res[it.track_id] = res
        self.fe_lines = out["lines"]

    def measure(self, it: Item) -> None:
        """A static item of a wall-like class (``roles.mapJudgedClasses``: building, wall, fence, barrier, guard-rail,
        hedge vegetation) is judged on the map alone (v26.2.2): the face / edge test (``faceedge``) on the corridor
        cells of its family on its footprint; at least ``faceEdge.minFaceCells`` face cells make it a lane danger,
        measured at the nearest face cell (distance, lateral, clock, steps). A wall beside the path (edge cells), a
        user standing still, or an item with no footprint on the map is no lane danger. Other static items keep the
        image rule (their ``map_source`` stays "image")."""
        if it.group != "static":
            return
        it.map_source = "image"
        self.faceedge(it)
        if it.class_name not in self.judged or self.fe_cfg is None:
            return
        fe = it.face_edge
        if fe is None and self.image_fallback:
            # the map has no cells of this item in the corridor to judge: the image rule decides
            return
        it.map_judged = True
        if fe is None:
            return
        it.map_source = "map"
        if self.stationary or fe["verdict"] != "face":
            return
        self._apply(it, fe["nearestFaceM"], fe["nearestFaceRightM"], fe["face"])

    def region(self, it: Item, pad_m: float, min_cells: int) -> Any:
        """(v26.2.11, source.mode "map") The 8-connected region of fused object cells of the item's family
        (confidence >= ``mapMinConf``) that its footprint touches, searched in a patch grown by ``pad_m``:
        (forward m, right m of its nearest cell, cells in the walking corridor, cells, width across the line
        of sight m), or None (no footprint / fewer than ``min_cells`` cells: the image measurement stays)."""
        lut = self._lut(it)
        fpr = self._footprint(it, lut)
        if fpr is None:
            return None
        fp, pr0, pc0 = fpr
        size = self.ob.size
        P = int(round(pad_m / self.cell))  # noqa: RUF046
        r0, c0 = max(0, pr0 - P), max(0, pc0 - P)
        r1, c1 = min(size, pr0 + fp.shape[0] + P), min(size, pc0 + fp.shape[1] + P)
        sl = (slice(r0, r1), slice(c0, c1))
        fam = self.solid[sl] & lut[self.classes[sl]]  # type: ignore[index]
        if not fam.any():
            return None
        lab, _ = ndimage.label(fam, structure=np.ones((3, 3), dtype=bool))
        hit = np.zeros(fam.shape, dtype=bool)
        hit[pr0 - r0 : pr0 - r0 + fp.shape[0], pc0 - c0 : pc0 - c0 + fp.shape[1]] = fp
        ids = np.unique(lab[hit & fam])
        ids = ids[ids > 0]
        if not ids.size:
            return None
        m = np.isin(lab, ids)
        n = int(np.count_nonzero(m))
        if n < min_cells:
            return None
        fwd, right = self.ob.fwd[sl][m], self.ob.right[sl][m]
        k = int(np.argmin(fwd + 1e-3 * np.abs(right)))
        b = math.atan2(right[k], fwd[k])
        across = -math.sin(b) * fwd + math.cos(b) * right
        width = float(across.max() - across.min()) + self.cell
        n_corr = int(np.count_nonzero(m & self.corr_full[sl]))
        return float(fwd[k]), float(right[k]), n_corr, n, width

    def locate(self, it: Item) -> None:
        """World position of the item's image measurement (a ghost is followed from it when the map did not place
        it)."""
        x, y, th = self.pose
        s_, c_ = math.sin(math.radians(th)), math.cos(math.radians(th))
        it.map_world = (x + s_ * it.distance_m + c_ * it.lateral_m, y + c_ * it.distance_m - s_ * it.lateral_m)

    def ghost(self, tr: Track, t: float) -> Item | None:
        """A static danger that left the image keeps its place in the map: the item again, measured from the cells near
        where it was."""
        src = tr.ghost_src
        if src is None or src.map_world is None:
            return None
        if tr.ghost_t0 is not None and t - tr.ghost_t0 > self.ghost_s + 1e-9:
            return None
        lut = self._lut(src)
        if lut is None:
            return None
        x, y, th = self.pose
        s_, c_ = math.sin(math.radians(th)), math.cos(math.radians(th))
        dx, dy = src.map_world[0] - x, src.map_world[1] - y
        fwd, right = dx * s_ + dy * c_, dx * c_ - dy * s_
        if fwd <= 0.0:
            return None  # passed
        size, ob = self.ob.size, self.ob
        row, col = ob.orow - int(round(fwd / ob.cell)), ob.oc + int(round(right / ob.cell))  # noqa: RUF046
        R = self.rad + 3  # the dead reckoning drifts a little
        pr0, pr1 = max(0, row - R), min(size, row + R + 1)
        pc0, pc1 = max(0, col - R), min(size, col + R + 1)
        if pr1 <= pr0 or pc1 <= pc0:
            return None
        fwd, right, n, _ = self._corridor_cells(np.ones((pr1 - pr0, pc1 - pc0), dtype=bool), lut, pr0, pc0, full=True)
        if n < 1:
            return None
        g = replace(src, ghost=True, shape=None, full_ref=None, clipped=True, map_source="map")
        self._apply(g, fwd, right, n)
        return g

    def keeps(self, it: Item) -> bool:
        """May this item's track be followed as a ghost once the image loses it?"""
        return (
            it.group == "static"
            and it.role == "danger"
            and it.collision
            and (it.clipped or it.distance_m <= self.ghost_near_m)
        )

    def corridor(self) -> dict[str, Any] | None:
        """The nearest object cell of any class in the walking corridor (Lab readout)."""
        m = self.solid & self.corr_full
        if not m.any():
            return None
        fwd = np.where(m, self.ob.fwd, np.inf)
        k = np.unravel_index(int(np.argmin(fwd)), fwd.shape)
        d = float(fwd[k])
        return {
            "nearestM": round(d, 2),
            "nearestSteps": round(d / self.step_len, 1),
            "className": self.classes_name(int(self.classes[k])),
        }

    def classes_name(self, cid: int) -> str:
        return self._names[cid] if cid < len(self._names) else str(cid)
