"""World map spike (v26.2 step 1): a fused, ego-centric bird's-eye map built only from what a Lab run stores.

Inputs per frame: the class grid, the depth map (when the run has one), the frame's horizon and ego block from
hazards.json. Nothing is inferred again. Per frame:

1. Ego observation (``Observer``): a 200 x 200 heading-up grid of 0.10 m cells (v26.2.4: forward only, the user stands on the
   bottom edge, col 100 / row 200: 20 m ahead, +-10 m to the sides, nothing behind).
   * surface classes: inverse ground-plane projection (each map cell -> the image pixel that sees it, using the
     collision pass's own geometry: ``focal_px`` / ``ground_distance_m`` / ``lateral_m`` inverted, the camera height
     and the lateral offset of the body calibration), so the map has no holes;
   * object classes (walls, poles, vegetation...): ONLY their ground base (the lowest pixel of each vertical run),
     placed at the depth under that pixel x the frame's depth scale when the run's distance source is depth (the same
     metres the collision pass reports as ``distanceM``), else at the ground distance of its row; upper pixels are not
     projected;
   * movers (person, rider, animal, vehicle): never burned into the map (the hazards list carries them).
2. Pose: ``collision._WorldMemory.advance`` (cadence speed x dt along the optical-flow heading, 0 when stationary).
3. Fusion (``Fusion``): a world-frame vote grid, exponentially decayed (lazily: votes are stored pre-multiplied by
   exp(lambda t), so a frame costs nothing for the decay), recentred as the user moves; class = argmax vote when the
   decayed weight is above a floor.
4. Snapshot: the fused map resampled into the ego frame, as one class per cell (surface and objects voting together: the
   collision rules read it) and, for the Lab's click readout (v26.2.4), as two separate layers: the winning surface class and the
   winning object class of every cell.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

import collision
import groundfuse
from collision import _WorldMemory, focal_px, ground_distance_m, lateral_m

UNKNOWN = 255
KIND_IGNORE, KIND_SURFACE, KIND_OBJECT, KIND_MOVER = 0, 1, 2, 3


def load_config(path: Path | None = None) -> dict:
    import json
    path = path or (collision.find_common_dir() / "config" / "worldmap.json")
    with open(path) as f:
        return json.load(f)


def class_kinds(cfg: dict, class_names: list[str]) -> np.ndarray:
    """(n_classes,) uint8 lookup: ignore / surface / object / mover."""
    kind = np.zeros(max(len(class_names), 256), dtype=np.uint8)
    index = {n: i for i, n in enumerate(class_names)}
    for k, key in ((KIND_SURFACE, "surface"), (KIND_OBJECT, "object"), (KIND_MOVER, "mover")):
        for name in cfg["classes"][key]:
            if name in index:
                kind[index[name]] = k
    return kind


class PoseTracker:
    """The user's pose, frame by frame: exactly what the collision pass's world memory integrates (speed x dt along the mean
    heading; stationary = 0). The offline ``build`` and the collision pass feed it the same (rounded) ego values."""

    def __init__(self, coll_cfg: dict):
        self.wm = _WorldMemory(coll_cfg.get("memory", {}))
        self.prev_t: float | None = None
        self.last_heading = 0.0

    def advance(self, t: float, ego: dict) -> tuple[float, float, float]:
        dt = 0.0 if self.prev_t is None else float(t - self.prev_t)
        self.prev_t = float(t)
        h = ego.get("headingDeg")
        h = self.last_heading if h is None else float(h)
        self.last_heading = h
        speed = 0.0 if ego.get("stationary") else ego.get("speedMps")
        self.wm.advance(float(t), dt, speed, h)
        return (self.wm.x, self.wm.y, h)


def integrate_pose(times: np.ndarray, egos: list[dict], coll_cfg: dict) -> np.ndarray:
    """(N, 3) x east, y north (m), heading deg (0 = initial direction, + = right turn) over a whole run."""
    pt = PoseTracker(coll_cfg)
    out = np.zeros((len(times), 3))
    for i, (t, e) in enumerate(zip(times, egos)):
        out[i] = pt.advance(float(t), e)
    return out


class Observer:
    """One frame's ego-centric observation: (classes uint8 [255 = unknown], weight float32)."""

    def __init__(self, cfg: dict, settings: dict, kind: np.ndarray, gh: int, gw: int, gd_cfg: dict | None = None,
                 class_names: list[str] | None = None):
        snap = cfg["snapshot"]
        self.size = int(snap["size"])
        self.oc, self.orow = int(snap["originCol"]), int(snap["originRow"])
        self.cell = float(cfg["cellM"])
        self.cfg = cfg
        self.kind = kind
        self.gh, self.gw = gh, gw
        self.hfov = float(settings["hfovDeg"])
        self.cam_h = float(settings["cameraHeightM"])
        self.lat_off = float(settings.get("lateralOffsetM", 0.0))
        self.depth_source = settings.get("distanceSource") == "depth"
        # v26.2.3: the distance of an object base (the collision pass's own setting, stored in hazards.json) and the horizon switch
        self.use_horizon = settings.get("useHorizon", True) is not False
        self.object_mode = groundfuse.resolved_mode(settings.get("objectDistance", "depth"), self.use_horizon)
        self.fisheye = settings.get("projection") == "fisheye"
        self.gd = gd_cfg if gd_cfg is not None else groundfuse.settings({})
        self.geo = groundfuse.Geometry(gh, gw, self.hfov, "fisheye" if self.fisheye else "rectilinear", self.cam_h)
        self.f_px = focal_px(gw, self.hfov)
        model = cfg.get("lateralModel", "collision")
        self.lens = model == "lens"
        # v26.2.7: "geometry" = the lens ground geometry (groundfuse.ground_point / ground_pixel / lateral_at) for the map's surfaces, the object
        # bases and the laterals; only on a fisheye run with depth distances (on a rectilinear one the collision pass's pinhole formulas are exact
        # and stay; with ground distances the gait scale already absorbs the lens factor, see collision._frame_geometry)
        self.geometry = model == "geometry" and self.fisheye and self.depth_source
        self.range_w = float(cfg["rangeWeightM"])
        self.max_range = float(cfg["maxRangeM"])
        self.min_fwd = float(cfg["minForwardM"])
        rows, cols = np.mgrid[0:self.size, 0:self.size]
        self.fwd = ((self.orow - rows) * self.cell).astype(np.float64)       # metres ahead of the user
        self.right = ((cols - self.oc) * self.cell).astype(np.float64)       # metres to the right (body centre line)
        self.weight = (1.0 / (1.0 + (np.maximum(self.fwd, 0.0) / self.range_w) ** 2)).astype(np.float32)
        # v26.2.5: wall faces (image columns -> one continuous line) and the sky (an object base on sky is not a ground contact)
        self.face_lut = np.zeros(256, dtype=bool)
        self.sky_id = -1
        for cid, name in enumerate(class_names or []):
            if cid < 256 and name in cfg.get("faceClasses", ()):
                self.face_lut[cid] = True
            if name in ("nature sky", "sky"):
                self.sky_id = cid
        self.depth_rows = max(1, int(cfg.get("faceDepthRows", 6)))
        self.smooth_cols = max(0, int(cfg.get("faceSmoothCols", 3)))
        self.outlier_frac = float(cfg.get("faceOutlierFrac", 0.25))
        self.join_frac = float(cfg.get("faceJoinFrac", 0.2))
        self.join_cols = max(1, int(cfg.get("faceJoinCols", 2)))
        self.thick_m = float(cfg.get("faceThicknessM", 0.3))
        # v26.2.7: faces at the ground contact of their base row, occluded faces scaled by the ratio, buildings that hide what is behind them
        self.face_ground = self.geometry and bool(cfg.get("faceGroundContact", False))
        self.face_scale_occ = bool(cfg.get("faceScaleOccluded", False))
        self.ratio_min = int(cfg.get("faceRatioMinBases", 10))
        self.ratio_clamp = tuple(float(x) for x in cfg.get("faceRatioClamp", (0.6, 1.5)))
        self.occ_lut = np.zeros(256, dtype=bool)
        for cid, name in enumerate(class_names or []):
            if cid < 256 and name in cfg.get("occluderClasses", ()):
                self.occ_lut[cid] = True
        self.hidden_factor = float(cfg.get("surfaceHiddenFactor", 1.0))
        self.ray_hidden = None
        bin_deg = float(cfg.get("hiddenBinDeg", 0.5))
        self.hid_bin_deg = bin_deg
        self.hid_nb = int(math.ceil(180.0 / bin_deg))
        self.cell_range = np.hypot(self.fwd, self.right)
        self.cell_bin = np.clip(np.floor((np.degrees(np.arctan2(self.right, self.fwd)) + 90.0) / bin_deg).astype(np.int64), 0, self.hid_nb - 1)
        # v26.2.7: gap closing in the snapshot: the cells k = 1..K along the line to the user / away from the user (flat indices; size*size = off grid)
        self.gap_k = int(round(float(cfg.get("gapCloseM", 0.0)) / self.cell))
        self.gap_tab = None
        if self.gap_k > 0:
            ri, ci = np.mgrid[0:self.size, 0:self.size]
            vr, vc = (self.orow - ri).astype(np.float64), (self.oc - ci).astype(np.float64)
            nrm = np.maximum(np.hypot(vr, vc), 1e-9)
            tabs = []
            for sign in (1.0, -1.0):
                idx = []
                for k in range(1, self.gap_k + 1):
                    r2 = np.rint(ri + sign * k * vr / nrm).astype(np.int64)
                    c2 = np.rint(ci + sign * k * vc / nrm).astype(np.int64)
                    inside = (r2 >= 0) & (r2 < self.size) & (c2 >= 0) & (c2 < self.size)
                    idx.append(np.where(inside, r2 * self.size + c2, self.size * self.size).ravel())
                tabs.append(np.stack(idx))
            self.gap_tab = tuple(tabs)                       # (toward the user, away from the user), each (K, size * size)

    # -- helpers ----------------------------------------------------------------------------------------------
    def _lateral(self, x: np.ndarray, d: np.ndarray) -> np.ndarray:
        """Camera-axis lateral (m, + right) of a pixel column at forward distance d; + the body offset is added by the caller."""
        if self.lens:
            return d * np.tan(np.radians((x - 0.5) * self.hfov))
        return (x - 0.5) * self.gw * d / self.f_px

    def ground_scale(self, frame: dict) -> float:
        mode = self.cfg.get("groundScale", "auto")
        if mode == "one" or (mode == "auto" and self.depth_source):
            return 1.0
        return float(frame.get("scale") or 1.0)

    def _bases(self, grid: np.ndarray, kgrid: np.ndarray):
        """(rows, cols, below_surface mask of the image) of the lowest pixel of every vertical run of an object class (not on the sky)."""
        cls = grid
        is_obj = kgrid == KIND_OBJECT
        below_same = np.zeros_like(is_obj)
        below_same[:-1] = cls[1:] == cls[:-1]
        base = is_obj & ~below_same
        below_surface = np.zeros_like(is_obj)
        below_surface[:-1] = kgrid[1:] == KIND_SURFACE
        if self.sky_id >= 0:
            below_sky = np.zeros_like(is_obj)
            below_sky[:-1] = cls[1:] == self.sky_id
            base &= ~below_sky                         # v26.2.5: an object base standing on the sky is not a ground contact
        rr, cc = np.nonzero(base)
        return rr, cc, below_surface

    def face_contact_samples(self, grid: np.ndarray, dmap: np.ndarray | None, depth_scale: float | None, horizon: float):
        """v26.2.7: (depth m, lens ground z m) of the face-class bases that stand on a surface: a wall base is a ground point seen at the
        wall's own range, a free calibration of the depth where the walking region does not reach. Same base / contact rules and the same
        bottom-``faceDepthRows`` median depth as ``object_bases``; the depth is scaled, never range-corrected; the ground z is the camera-axis
        depth of the floor point of the base row (``groundfuse.ground_z``, the quantity the depth map holds) for the setting's camera height.
        Only bases at least ``minRowsBelowHorizon`` rows below the horizon and with a ground z up to ``fuseMaxM``."""
        z = np.zeros(0)
        if dmap is None or not depth_scale or not self.face_lut.any():
            return z, z
        kgrid = self.kind[grid]
        rr, cc, below_surface = self._bases(grid, kgrid)
        if not rr.size:
            return z, z
        gh = self.gh
        keep = self.face_lut[grid[rr, cc]] & below_surface[rr, cc] & (rr < gh - 1) & ((rr + 1.0) / gh > horizon + 1e-6)
        rr, cc = rr[keep], cc[keep]
        if not rr.size:
            return z, z
        v = float(depth_scale) * self._run_depth(grid, dmap, rr, cc)
        g = groundfuse.ground_z(self.geo, rr + 1.0, cc + 0.5, horizon)
        with np.errstate(invalid="ignore"):
            ok = (np.isfinite(v) & (v > 0) & np.isfinite(g) & (g > 0) & ((rr + 1.0) - horizon * gh >= float(self.gd["minRowsBelowHorizon"]))
                  & (g <= float(self.gd["fuseMaxM"])))
        return v[ok], g[ok]

    def object_bases(self, grid: np.ndarray, frame: dict, dmap: np.ndarray | None, kgrid: np.ndarray | None = None):
        """The ground base of every vertical run of an object class: (rows, cols, forward distance m, lateral m in body
        coordinates) of the image pixels that are projected into the map. The collision rules (v26.2.1) read the same points to
        place an item's footprint on the map."""
        gh, gw = self.gh, self.gw
        cam_h = self.cam_h * self.ground_scale(frame)
        kgrid = self.kind[grid] if kgrid is None else kgrid
        rr, cc, below_surface = self._bases(grid, kgrid)
        empty = (rr[:0], cc[:0], np.zeros(0), np.zeros(0))
        if not rr.size:
            return empty
        horizon = float(frame["horizon"])
        y_b = (rr + 1.0) / gh
        contact = below_surface[rr, cc] & (y_b > horizon + 1e-6) & (rr < gh - 1)          # stands on the ground
        if self.geometry:        # v26.2.7: the ground point of the base row through the lens (forward m); nan above the horizon
            ground = groundfuse.ground_point(self.geo, rr + 1.0, cc + 0.5, horizon, cam_h)[0]
        else:
            ground = cam_h * self.f_px / (np.maximum(y_b - horizon, 1e-6) * gh)
        has_depth = dmap is not None and bool(frame.get("depthScale"))
        if not self.use_horizon and not has_depth:
            return empty                                # horizon off: depth is the only distance
        if has_depth:
            dist = float(frame["depthScale"]) * self._run_depth(grid, dmap, rr, cc)
            good = np.isfinite(dist) & (dist > 0)
            rep_ = frame.get("dcorr")
            if self.use_horizon and self.object_mode != "depth" and rep_ is not None and contact.any():
                # v26.2.3: the same fusion the collision pass uses for an item (groundfuse.resolve), per base pixel; v26.2.5: only for
                # bases that stand on a surface, the others keep the depth of their run
                g_m, sg_m = groundfuse.ground_m(self.geo, y_b * gh, cc + 0.5, horizon, rep_, float(rep_["sigmaRows"]))
                fused, _ = groundfuse.resolve(np.where(good, dist, 1.0), g_m, sg_m, (y_b - horizon) * gh, contact, rep_, self.gd, self.object_mode)
                dist = np.where(contact, fused, dist)
            if self.face_ground and self.use_horizon:
                dist = self._face_ground(grid[rr, cc], dist, good, contact, ground, (y_b - horizon) * gh)
        else:                                           # ground distance of the base row; needs the ground below it
            good = contact
            dist = np.where(good, ground, 0.0)
        good &= (dist >= self.min_fwd) & (dist <= self.max_range)
        rr, cc, dist = rr[good], cc[good], dist[good]
        if not rr.size:
            return empty
        face = self.face_lut[grid[rr, cc]]
        if face.any():
            dist, keep = self._smooth_faces(grid[rr, cc], cc, dist, face)
            rr, cc, dist = rr[keep], cc[keep], dist[keep]
            if not rr.size:
                return empty
        if self.geometry:
            lat_b = groundfuse.lateral_at(self.geo, rr + 1.0, cc + 0.5, dist, horizon) + self.lat_off
        else:
            lat_b = self._lateral((cc + 0.5) / gw, dist) + self.lat_off
        return rr, cc, dist, lat_b

    def _face_ground(self, cls: np.ndarray, dist: np.ndarray, good: np.ndarray, contact: np.ndarray, ground: np.ndarray,
                     rows_below: np.ndarray) -> np.ndarray:
        """v26.2.7 (``faceGroundContact``): a face-class base that stands on a surface takes the lens ground distance of its base row, the
        geometry the surface projection uses, so that the sidewalk and the building edge meet in one cell. With ``faceScaleOccluded`` the
        class's other bases (its facade above a car, a pole, a sign...) follow: ratio = median(ground / depth) over its contact bases
        (at least ``faceRatioMinBases``, clamped to ``faceRatioClamp``), applied to their depth."""
        face = self.face_lut[cls]
        if not face.any():
            return dist
        with np.errstate(invalid="ignore"):
            use = (face & contact & good & np.isfinite(ground) & (rows_below >= float(self.gd["minRowsBelowHorizon"]))
                   & (ground >= self.min_fwd) & (ground <= self.max_range))
        out = dist.copy()
        if self.face_scale_occ:
            for c in np.unique(cls[face]):
                sel = face & (cls == c)
                own = sel & use
                if int(own.sum()) >= self.ratio_min:
                    ratio = float(np.clip(np.median(ground[own] / dist[own]), self.ratio_clamp[0], self.ratio_clamp[1]))
                    other = sel & ~use & good
                    out[other] = dist[other] * ratio
        out[use] = ground[use]
        return out

    def _run_depth(self, grid: np.ndarray, dmap: np.ndarray, rr: np.ndarray, cc: np.ndarray) -> np.ndarray:
        """v26.2.5: the depth of every base = the median of the bottom ``faceDepthRows`` rows of its vertical run (same class, same
        column), in depth-map units. One edge pixel mixes the object's depth with what is below or behind it."""
        gh, gw = self.gh, self.gw
        dh, dw = dmap.shape
        cls = grid[rr, cc]
        col_d = np.minimum(dw - 1, ((cc + 0.5) / gw * dw).astype(int))
        vals = np.full((self.depth_rows, rr.size), np.nan)
        alive = np.ones(rr.size, dtype=bool)
        for k in range(self.depth_rows):
            r = rr - k
            alive &= (r >= 0)
            alive &= grid[np.maximum(r, 0), cc] == cls
            row_d = np.minimum(dh - 1, ((np.maximum(r, 0) + 0.5) / gh * dh).astype(int))
            vals[k] = np.where(alive, dmap[row_d, col_d], np.nan)
        vals[~np.isfinite(vals) | (vals <= 0)] = np.nan
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                med = np.nanmedian(vals, axis=0)
        return med.astype(np.float64)

    def _smooth_faces(self, cls: np.ndarray, cc: np.ndarray, dist: np.ndarray, face: np.ndarray):
        """v26.2.5: for the face-class bases, a running median of the distance over +-``faceSmoothCols`` image columns of the same class; a
        point further than ``faceOutlierFrac`` from it is dropped, the others take the median. Returns (dist, keep mask)."""
        out = dist.copy()
        keep = np.ones(dist.size, dtype=bool)
        k = self.smooth_cols
        for c in np.unique(cls[face]):
            idx = np.flatnonzero(face & (cls == c))
            order = idx[np.argsort(cc[idx], kind="stable")]
            cols = cc[order]
            # rank of every point inside its column -> a dense (columns, runs) table
            first = np.searchsorted(cols, cols, side="left")
            rank = np.arange(cols.size) - first
            nrank = int(rank.max()) + 1
            table = np.full((self.gw + 2 * k, nrank), np.nan)
            table[cols + k, rank] = dist[order]
            stack = np.concatenate([table[j:j + self.gw] for j in range(2 * k + 1)], axis=1)       # (gw, (2k+1) * runs)
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                med = np.nanmedian(stack, axis=1)
            m = med[cols]
            bad = np.abs(dist[order] - m) > self.outlier_frac * m
            keep[order[bad]] = False
            out[order] = m
        return out, keep

    def _face_rays(self, cls: np.ndarray, dist: np.ndarray, lat_b: np.ndarray) -> None:
        """v26.2.5 (optional clearing): the cells on the ray from the user to each face point, from ``minForwardM`` to the face distance minus
        ``objectClearMarginM``, are free space even where the ground is not visible (hidden behind a mover). Stored in ``self.ray_clear``."""
        if float(self.cfg.get("objectClearRays", 0)) <= 0:
            return
        face = self.face_lut[cls]
        if not face.any():
            return
        margin = float(self.cfg.get("objectClearMarginM", 0.3))
        d, l = dist[face], lat_b[face]
        end = d - margin
        ok = end > self.min_fwd
        d, l, end = d[ok], l[ok], end[ok]
        if not d.size:
            return
        rng_ = np.hypot(d, l)
        n = int(np.ceil((end / d * rng_).max() / self.cell)) + 1
        k = np.arange(1, n + 1)[None, :] * self.cell                         # range along the ray
        frac = k / rng_[:, None]
        valid = (frac * d[:, None] >= self.min_fwd) & (frac * d[:, None] <= end[:, None])
        rows = self.orow - np.rint(frac * d[:, None] / self.cell).astype(np.int64)
        cols = self.oc + np.rint(frac * l[:, None] / self.cell).astype(np.int64)
        m = np.zeros((self.size, self.size), dtype=bool)
        v = valid & (rows >= 0) & (rows < self.size) & (cols >= 0) & (cols < self.size)
        m[rows[v], cols[v]] = True
        a = m.copy(); a[1:] |= m[:-1]; a[:-1] |= m[1:]
        b = a.copy(); b[:, 1:] |= a[:, :-1]; b[:, :-1] |= a[:, 1:]
        self.ray_clear = b

    def _hidden_cells(self, cls: np.ndarray, dist: np.ndarray, lat_b: np.ndarray, obs: np.ndarray) -> None:
        """v26.2.7 (``occluderClasses``): a building closes the view: the cells behind an occluder face point, from its range +
        ``faceThicknessM`` outwards along its bearing, cannot be seen by this frame. Per ``hiddenBinDeg`` bearing bin the nearest occluder
        range (gaps of up to two empty bins between occluder points are bridged: a facade is continuous); the cells this frame sees as surface
        itself are not hidden (visible ground wins). Stored in ``self.ray_hidden`` (the fusion cuts the stored surface votes there)."""
        if self.hidden_factor >= 1.0:
            return
        occ = self.occ_lut[cls]
        if not occ.any():
            return
        d, l = dist[occ], lat_b[occ]
        rng_ = np.hypot(d, l)
        b = np.clip(np.floor((np.degrees(np.arctan2(l, d)) + 90.0) / self.hid_bin_deg).astype(np.int64), 0, self.hid_nb - 1)
        r = np.full(self.hid_nb, np.inf)
        np.minimum.at(r, b, rng_)
        left, right = r.copy(), r.copy()
        for sft in (1, 2):                                   # nearest occupied bin within two bins on each side
            left[sft:] = np.where(np.isfinite(left[sft:]), left[sft:], r[:-sft])
            right[:-sft] = np.where(np.isfinite(right[:-sft]), right[:-sft], r[sft:])
        r = np.where(np.isfinite(r), r, np.where(np.isfinite(left) & np.isfinite(right), np.maximum(left, right), np.inf))
        hidden = self.cell_range > (r + self.thick_m)[self.cell_bin]
        hidden &= ~((self.kind[obs] == KIND_SURFACE) & (obs != UNKNOWN))
        self.ray_hidden = hidden

    def _face_cells(self, grid, rr, cc, dist, lat_b):
        """v26.2.5: cells of the faces: adjacent image columns of the same face class whose distances differ by less than ``faceJoinFrac``
        are joined by a straight segment on the map, ``faceThicknessM`` thick, extended away from the user along the ray.
        Returns (rows, cols, class values, distance keys) of the cells to write."""
        cls = grid[rr, cc]
        face = np.flatnonzero(self.face_lut[cls])
        empty = (np.zeros(0, np.int64),) * 2 + (np.zeros(0, np.uint8), np.zeros(0))
        if not face.size:
            return empty
        order = face[np.lexsort((cc[face], cls[face]))]
        a, b = order[:-1], order[1:]
        same = (cls[a] == cls[b]) & (cc[b] - cc[a] >= 1) & (cc[b] - cc[a] <= self.join_cols)
        same &= np.abs(dist[a] - dist[b]) <= self.join_frac * np.maximum(dist[a], dist[b])
        # one segment per point (a point with no joined neighbour is a degenerate segment: thickness only)
        seg_a = np.concatenate([order, a[same]])
        seg_b = np.concatenate([order, b[same]])
        n_steps = max(1, int(round(self.thick_m / self.cell)))
        pf = np.stack([dist[seg_a], dist[seg_b]], 1)                 # forward (m) of the two ends
        pr = np.stack([lat_b[seg_a], lat_b[seg_b]], 1)               # right (m)
        n_s = 4
        t = np.linspace(0.0, 1.0, n_s)
        f_s = (pf[:, :1] * (1 - t) + pf[:, 1:] * t).ravel()
        r_s = (pr[:, :1] * (1 - t) + pr[:, 1:] * t).ravel()
        rng_ = np.maximum(np.hypot(f_s, r_s), 1e-6)
        rows, cols, vals, keys = [], [], [], []
        v = np.repeat(cls[seg_a], n_s)
        for s_ in range(n_steps + 1):
            off = s_ * self.cell
            f2, r2 = f_s * (1 + off / rng_), r_s * (1 + off / rng_)
            rows.append(self.orow - np.rint(f2 / self.cell).astype(np.int64))
            cols.append(self.oc + np.rint(r2 / self.cell).astype(np.int64))
            vals.append(v)
            keys.append(f_s)
        return np.concatenate(rows), np.concatenate(cols), np.concatenate(vals), np.concatenate(keys)

    def observe(self, grid: np.ndarray, frame: dict, dmap: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
        gh, gw, size = self.gh, self.gw, self.size
        obs = np.full((size, size), UNKNOWN, dtype=np.uint8)
        horizon = float(frame["horizon"])
        self.last_horizon = horizon
        cam_h = self.cam_h * self.ground_scale(frame)
        kgrid = self.kind[grid]
        if not self.use_horizon and dmap is not None and frame.get("depthScale"):
            self._depth_surfaces(obs, grid, kgrid, frame, dmap)           # v26.2.3: surfaces through the depth map, no horizon
        else:
            self._ground_surfaces(obs, grid, kgrid, horizon, cam_h)
        # --- object bases ----------------------------------------------------------------------------------
        self.ray_clear = None
        self.ray_hidden = None
        rr, cc, dist, lat_b = self.object_bases(grid, frame, dmap, kgrid)
        if rr.size:
            col = self.oc + np.rint(lat_b / self.cell).astype(np.int64)
            row = self.orow - np.rint(dist / self.cell).astype(np.int64)
            half = np.minimum(4, np.rint(dist / self.f_px / 2.0 / self.cell).astype(np.int64))   # one image column's width
            vals = grid[rr, cc]
            cells_r, cells_c, cells_v, cells_k = [], [], [], []
            for off in range(-4, 5):
                m = half >= abs(off)
                cells_r.append(row[m])
                cells_c.append(col[m] + off)
                cells_v.append(vals[m])
                cells_k.append(dist[m])
            fr_, fc_, fv_, fk_ = self._face_cells(grid, rr, cc, dist, lat_b)       # v26.2.5: the joined, thick wall faces
            cells_r.append(fr_); cells_c.append(fc_); cells_v.append(fv_); cells_k.append(fk_)
            ry, cx, vv, kk = (np.concatenate(x) for x in (cells_r, cells_c, cells_v, cells_k))
            order = np.argsort(-kk, kind="stable")        # nearer points are written last and win
            ry, cx, vv = ry[order], cx[order], vv[order]
            inside = (cx >= 0) & (cx < size) & (ry >= 0) & (ry < size)
            obs[ry[inside], cx[inside]] = vv[inside]
            self._face_rays(grid[rr, cc], dist, lat_b)
            self._hidden_cells(grid[rr, cc], dist, lat_b, obs)
        w = np.where(obs != UNKNOWN, self.weight, 0.0).astype(np.float32)
        gain = float(self.cfg.get("objectVoteGain", 1.0))        # an object base is one thin line among many surface cells
        if gain != 1.0:
            w[self.kind[obs] == KIND_OBJECT] *= np.float32(gain)
        return obs, w

    def _ground_surfaces(self, obs: np.ndarray, grid: np.ndarray, kgrid: np.ndarray, horizon: float, cam_h: float) -> None:
        """Surfaces: inverse ground-plane sampling (each map cell -> the image pixel that sees it, through the horizon). v26.2.7
        (``lateralModel`` "geometry", fisheye): through the lens (``groundfuse.ground_pixel``, the exact inverse of ``ground_point``)."""
        gh, gw = self.gh, self.gw
        fwd = self.fwd
        ok = (fwd >= self.min_fwd) & (fwd <= self.max_range)
        d = np.where(ok, fwd, 1.0)
        lat = self.right - self.lat_off
        if self.geometry:
            row_f, col_f = groundfuse.ground_pixel(self.geo, d, lat, horizon, cam_h)
            ok &= np.isfinite(row_f) & np.isfinite(col_f)
            ri = np.floor(np.where(ok, row_f, -1.0)).astype(np.int64)
            ci = np.floor(np.where(ok, col_f, -1.0)).astype(np.int64)
        else:
            y = horizon + cam_h * self.f_px / (d * gh)
            if self.lens:
                x = 0.5 + np.arctan2(lat, d) / math.radians(self.hfov)
            else:
                x = 0.5 + lat * self.f_px / (d * gw)
            ri = np.floor(y * gh).astype(np.int64)
            ci = np.floor(x * gw).astype(np.int64)
        ok &= (ri >= 0) & (ri < gh) & (ci >= 0) & (ci < gw)
        ri = np.clip(ri, 0, gh - 1)
        ci = np.clip(ci, 0, gw - 1)
        surf = ok & (kgrid[ri, ci] == KIND_SURFACE)
        obs[surf] = grid[ri, ci][surf]

    def _depth_surfaces(self, obs: np.ndarray, grid: np.ndarray, kgrid: np.ndarray, frame: dict, dmap: np.ndarray) -> None:
        """Surfaces through the depth map (horizon off): every surface pixel is back-projected along its lens ray (equidistant fisheye or pinhole)
        at its z-depth x the depth scale, forward distance = z cos(pitch) - y sin(pitch) with the plane-fit pitch when the run has one, and splatted
        into the cells around it (the footprint of a pixel grows with range); nearer pixels are written last."""
        gh, gw = self.gh, self.gw
        rr, cc = np.nonzero(kgrid == KIND_SURFACE)
        if not rr.size:
            return
        dh, dw = dmap.shape
        z = dmap[np.minimum(dh - 1, ((rr + 0.5) / gh * dh).astype(int)),
                 np.minimum(dw - 1, ((cc + 0.5) / gw * dw).astype(int))].astype(np.float64) * float(frame["depthScale"])
        px, py = cc + 0.5 - gw / 2.0, rr + 0.5 - gh / 2.0
        if self.fisheye:
            r = np.hypot(px, py)
            theta = r / (gw / math.radians(self.hfov))
            c_t = np.cos(theta)
            with np.errstate(divide="ignore", invalid="ignore"):
                k = np.where(r > 0, np.sin(theta) / np.maximum(r, 1e-12), 0.0) / c_t
            xn, yn = k * px, k * py
            good = c_t > 1e-3
        else:
            xn, yn = px / self.f_px, py / self.f_px
            good = np.ones(rr.size, dtype=bool)
        pitch = math.radians(float((frame.get("ego") or {}).get("depthPitchDeg") or 0.0))
        fwd = z * (math.cos(pitch) - yn * math.sin(pitch))
        right = xn * z + self.lat_off
        good &= np.isfinite(z) & (z > 0) & np.isfinite(fwd) & (fwd >= self.min_fwd) & (fwd <= self.max_range)
        rr, cc, fwd, right = rr[good], cc[good], fwd[good], right[good]
        if not rr.size:
            return
        col = self.oc + np.rint(right / self.cell).astype(np.int64)
        row = self.orow - np.rint(fwd / self.cell).astype(np.int64)
        half_x = np.minimum(2, np.rint(fwd / self.f_px / 2.0 / self.cell).astype(np.int64))
        # one image row is F^2 / (H f) metres deep on the ground: the cells between two rows are filled up to 6 cells (0.6 m) either side
        half_y = np.minimum(6, np.rint(fwd * fwd / (self.cam_h * self.f_px) / 2.0 / self.cell).astype(np.int64))
        order = np.argsort(-fwd)
        rr, cc, col, row, half_x, half_y = rr[order], cc[order], col[order], row[order], half_x[order], half_y[order]
        vals = grid[rr, cc]
        size = self.size
        for dy in range(-6, 7):
            for dx in range(-2, 3):
                m = (half_y >= abs(dy)) & (half_x >= abs(dx))
                if not m.any():
                    continue
                cx, ry = col[m] + dx, row[m] + dy
                inside = (cx >= 0) & (cx < size) & (ry >= 0) & (ry < size)
                obs[ry[inside], cx[inside]] = vals[m][inside]


class Fusion:
    """World-frame decayed class votes (0.10 m cells, ``windowM`` square, recentred), plus an observation count."""

    def __init__(self, cfg: dict, kind: np.ndarray, present: np.ndarray, start_xy: tuple[float, float]):
        self.cfg = cfg
        self.cell = float(cfg["cellM"])
        self.n = int(round(cfg["windowM"] / self.cell))
        self.lam = math.log(2.0) / float(cfg["halfLifeSeconds"])
        self.floor = float(cfg["weightFloor"])
        self.full = float(cfg["confFullWeight"])
        keep = [int(c) for c in present if kind[c] in (KIND_SURFACE, KIND_OBJECT)]
        keep = keep or [0]                       # a run with no surface / object class at all: one empty layer
        self.classes = np.array(keep, dtype=np.uint8)
        self.is_surface = np.array([kind[c] == KIND_SURFACE for c in keep])           # per vote layer: surface class / object class
        self.lut = np.full(256, -1, dtype=np.int16)
        for k, c in enumerate(keep):
            self.lut[c] = k
        self.votes = np.zeros((max(1, len(keep)), self.n, self.n), dtype=np.float32)
        self.count = np.zeros((self.n, self.n), dtype=np.uint16)
        self.x0 = start_xy[0] - self.n * self.cell / 2.0          # world coordinates of the window's corner (cell 0,0)
        self.y0 = start_xy[1] - self.n * self.cell / 2.0
        self.t_base = 0.0

    def _recentre(self, x: float, y: float, margin_m: float = 22.0) -> None:
        half = self.n * self.cell / 2.0
        cx, cy = self.x0 + half, self.y0 + half
        if abs(x - cx) <= half - margin_m and abs(y - cy) <= half - margin_m:
            return
        sx = int(round((x - cx) / self.cell))
        sy = int(round((y - cy) / self.cell))
        n = self.n
        new_v = np.zeros_like(self.votes)
        new_c = np.zeros_like(self.count)
        # new cell (i, j) holds old cell (i + sy, j + sx)
        i0, i1 = max(0, -sy), min(n, n - sy)
        j0, j1 = max(0, -sx), min(n, n - sx)
        if i1 > i0 and j1 > j0:
            new_v[:, i0:i1, j0:j1] = self.votes[:, i0 + sy:i1 + sy, j0 + sx:j1 + sx]
            new_c[i0:i1, j0:j1] = self.count[i0 + sy:i1 + sy, j0 + sx:j1 + sx]
        self.votes, self.count = new_v, new_c
        self.x0 += sx * self.cell
        self.y0 += sy * self.cell

    def _ego_to_world_idx(self, fwd: np.ndarray, right: np.ndarray, pose: tuple[float, float, float]):
        x, y, th = pose[0], pose[1], math.radians(pose[2])
        s, c = math.sin(th), math.cos(th)
        wx = x + s * fwd + c * right
        wy = y + c * fwd - s * right
        return (np.floor((wy - self.y0) / self.cell).astype(np.int64),
                np.floor((wx - self.x0) / self.cell).astype(np.int64))

    def update(self, t: float, pose: tuple[float, float, float], obs: np.ndarray, w: np.ndarray, observer: Observer) -> None:
        """Inverse mapping: every world cell of the ego window's bounding box looks up the observation cell it falls in."""
        self._recentre(pose[0], pose[1])
        if t - self.t_base > 20.0:                       # keep exp(lambda t) in range
            self.votes *= np.float32(math.exp(-self.lam * (t - self.t_base)))
            self.t_base = t
        x, y, th = pose[0], pose[1], math.radians(pose[2])
        s, c = math.sin(th), math.cos(th)
        size, cell = observer.size, self.cell
        f_lo, f_hi = (observer.orow - size) * cell, observer.orow * cell
        r_lo, r_hi = -observer.oc * cell, (size - observer.oc) * cell
        corners = [(f, r) for f in (f_lo, f_hi) for r in (r_lo, r_hi)]
        wxs = [x + s * f + c * r for f, r in corners]
        wys = [y + c * f - s * r for f, r in corners]
        j0 = max(0, int(math.floor((min(wxs) - self.x0) / cell)))
        j1 = min(self.n, int(math.ceil((max(wxs) - self.x0) / cell)))
        i0 = max(0, int(math.floor((min(wys) - self.y0) / cell)))
        i1 = min(self.n, int(math.ceil((max(wys) - self.y0) / cell)))
        if i1 <= i0 or j1 <= j0:
            return
        ii, jj = np.mgrid[i0:i1, j0:j1]
        dx = self.x0 + (jj + 0.5) * cell - x
        dy = self.y0 + (ii + 0.5) * cell - y
        fwd = dx * s + dy * c
        right = dx * c - dy * s
        col = np.floor(observer.oc + right / cell + 0.5).astype(np.int64)
        row = np.floor(observer.orow - fwd / cell + 0.5).astype(np.int64)
        ok = (col >= 0) & (col < size) & (row >= 0) & (row < size)
        col, row = np.clip(col, 0, size - 1), np.clip(row, 0, size - 1)
        cls = obs[row, col]
        inb = ok.copy()
        ok &= cls != UNKNOWN
        self._clear_stale_objects(obs, observer, row, col, ii, jj, inb, getattr(observer, 'last_horizon', None))
        self._cut_hidden_surfaces(observer, row, col, ii, jj, inb)
        k = self.lut[cls]
        ok &= k >= 0
        if not ok.any():
            return
        amp = w[row, col] * np.float32(math.exp(self.lam * (t - self.t_base)))
        self.votes[k[ok], ii[ok], jj[ok]] += amp[ok]
        self.count[ii[ok], jj[ok]] += 1

    def _clear_stale_objects(self, obs, observer, row, col, ii, jj, ok, frame_horizon=None) -> None:
        """v26.2.5 negative evidence: a world cell that the current frame sees as a surface (visible ground) loses ``1 - objectClearFactor``
        of its object votes, except within ``objectClearMarginM`` of a cell the frame writes as an object (the horizon-projected ground and
        the depth-placed wall disagree by a few tenths). Surface votes are untouched; the stored (pre-multiplied) votes scale linearly."""
        f = float(self.cfg.get("objectClearFactor", 1.0))
        obj_layers = np.flatnonzero(~self.is_surface)
        if f >= 1.0 or not obj_layers.size:
            return
        kgrid = observer.kind[obs]
        is_obj = (kgrid == KIND_OBJECT) & (obs != UNKNOWN)
        near = is_obj.copy()
        m = int(round(float(self.cfg.get("objectClearMarginM", 0.3)) / self.cell))
        for _ in range(m):                                   # square dilation by the margin
            a = near.copy()
            a[1:] |= near[:-1]; a[:-1] |= near[1:]
            b = a.copy()
            b[:, 1:] |= a[:, :-1]; b[:, :-1] |= a[:, 1:]
            near = b
        clear = (kgrid == KIND_SURFACE) & (obs != UNKNOWN)
        if getattr(observer, "ray_clear", None) is not None:
            clear |= observer.ray_clear
        clear &= ~near
        # an object whose base left the bottom of the image stands just nearer than the nearest visible ground: keep a band at the bottom edge
        if frame_horizon is None:
            d_bottom = 0.0
        elif observer.geometry:           # v26.2.7: the forward distance of the last image row on the centre column, through the lens
            d_bottom = float(groundfuse.ground_point(observer.geo, float(observer.gh), observer.gw / 2.0, float(frame_horizon), observer.cam_h)[0])
            d_bottom = d_bottom if math.isfinite(d_bottom) else 0.0
        else:
            d_bottom = float(observer.cam_h) * observer.f_px / (max(1.0 - float(frame_horizon), 1e-6) * observer.gh)
        clear &= observer.fwd >= d_bottom + float(self.cfg.get("objectClearBottomM", 0.5))
        sel = ok & clear[row, col]
        if sel.any():
            for k in obj_layers:
                self.votes[k, ii[sel], jj[sel]] *= np.float32(f)

    def _cut_hidden_surfaces(self, observer, row, col, ii, jj, ok) -> None:
        """v26.2.7: a world cell that maps to an ego cell hidden behind a building (``Observer.ray_hidden``) loses ``1 - surfaceHiddenFactor`` of
        its stored SURFACE votes (a street cannot be seen through a facade); object votes are untouched. Mirrors ``_clear_stale_objects``."""
        hid = getattr(observer, "ray_hidden", None)
        f = float(self.cfg.get("surfaceHiddenFactor", 1.0))
        if hid is None or f >= 1.0:
            return
        sel = ok & hid[row, col]
        if sel.any():
            for k in np.flatnonzero(self.is_surface):
                self.votes[k, ii[sel], jj[sel]] *= np.float32(f)

    def _decay(self, t: float) -> float:
        return math.exp(-self.lam * (t - self.t_base))

    def snapshot(self, t: float, pose: tuple[float, float, float], observer: Observer, layers: bool = False):
        """The fused map in the ego frame: (classes, conf), or with ``layers`` (classes, conf, surface, object): the winning surface class and
        the winning object class of every cell on their own (255 = none), so that an object does not hide the surface under it."""
        iy, ix = self._ego_to_world_idx(observer.fwd, observer.right, pose)
        inside = (iy >= 0) & (iy < self.n) & (ix >= 0) & (ix < self.n)
        iy, ix = np.clip(iy, 0, self.n - 1), np.clip(ix, 0, self.n - 1)
        v = self.votes[:, iy, ix]                                    # (K, size, size)
        decay = np.float32(self._decay(t))
        total = v.sum(axis=0) * decay
        top = v.argmax(axis=0)
        share = np.take_along_axis(v, top[None], 0)[0] / np.maximum(v.sum(axis=0), 1e-12)
        known = inside & (total > self.floor)
        classes = np.where(known, self.classes[top], UNKNOWN).astype(np.uint8)
        conf = np.where(known, 255.0 * np.minimum(1.0, total / self.full) * share, 0.0)
        # v26.2.5: a thin wall line is not hidden by the big surface area projected through it: a cell is the winning object class
        # when the object layers hold at least ``objectWinShare`` of its (decayed) weight, above the floor
        win = float(self.cfg.get("objectWinShare", 0.0))
        if win > 0.0 and (~self.is_surface).any() and self.is_surface.any():
            vo = v[~self.is_surface]
            o_raw = vo.sum(axis=0)
            o_dec = o_raw * decay
            o_win = inside & (o_dec > self.floor) & (o_raw >= win * np.maximum(v.sum(axis=0), 1e-12)) & self.is_surface[top]
            if o_win.any():
                o_top = vo.argmax(axis=0)
                o_share = np.take_along_axis(vo, o_top[None], 0)[0] / np.maximum(o_raw, 1e-12)
                classes = np.where(o_win, self.classes[~self.is_surface][o_top], classes).astype(np.uint8)
                conf = np.where(o_win, 255.0 * np.minimum(1.0, o_dec / self.full) * o_share, conf)
        gap = self.close_gaps(classes, conf, observer) if observer.gap_tab is not None else None
        if gap is not None:
            classes, conf = classes.copy(), np.asarray(conf, dtype=np.float64).copy()
            classes.ravel()[gap[0]] = gap[1]
            conf.ravel()[gap[0]] = gap[2]
        if not layers:
            return classes, conf.astype(np.uint8)
        out = []
        for sel in (self.is_surface, ~self.is_surface):
            if not sel.any():
                out.append(np.full(classes.shape, UNKNOWN, dtype=np.uint8))
                continue
            sub = v[sel]
            ok = inside & (sub.sum(axis=0) * decay > self.floor)
            out.append(np.where(ok, self.classes[sel][sub.argmax(axis=0)], UNKNOWN).astype(np.uint8))
        if gap is not None:
            out[1].ravel()[gap[0]] = gap[1]                               # the closed gap is a face in the object layer too
        return classes, conf.astype(np.uint8), out[0], out[1]

    @staticmethod
    def close_gaps(classes: np.ndarray, conf: np.ndarray, observer: Observer):
        """v26.2.7 (``gapCloseM``): an unknown cell whose line toward the user meets a surface cell, and whose line away from the user meets a
        face-class cell, both within ``gapCloseM``, is a seam between a sidewalk and a building: a ground and a wall do not have a gap between
        them. Returns (flat cell indices, face classes, face confs) of the cells that take the nearest face cell's class and conf, or None."""
        toward, away = observer.gap_tab
        n = classes.size
        flat = np.append(classes.ravel(), np.uint8(UNKNOWN))
        cand = np.flatnonzero(flat[:n] == UNKNOWN)
        if not cand.size:
            return None
        surf = (observer.kind[flat[toward[:, cand]]] == KIND_SURFACE).any(axis=0)
        cand = cand[surf]
        if not cand.size:
            return None
        is_face = observer.face_lut[flat[away[:, cand]]]
        ok = is_face.any(axis=0)
        if not ok.any():
            return None
        cand, is_face = cand[ok], is_face[:, ok]
        src = away[is_face.argmax(axis=0), cand]                          # flat index of the nearest face cell
        return cand, flat[src], np.append(np.asarray(conf).ravel(), 0)[src]

    def world_classes(self, t: float) -> tuple[np.ndarray, np.ndarray]:
        """Whole window: (classes uint8 [255 unknown], decayed total weight); for metrics."""
        total = self.votes.sum(axis=0) * np.float32(self._decay(t))
        cls = np.where(total > self.floor, self.classes[self.votes.argmax(axis=0)], UNKNOWN).astype(np.uint8)
        return cls, total


def face_contact_samples(observer: Observer, grid: np.ndarray, dmap, depth_scale, horizon: float):
    """v26.2.7: (depth m, lens ground z m) of the face-class bases that stand on a surface (see ``Observer.face_contact_samples``)."""
    return observer.face_contact_samples(grid, dmap, depth_scale, horizon)


def frames_from_hazards(hazards: dict) -> list[dict]:
    """The per-frame inputs the observer needs: horizon, scales and the ego block (as stored by the collision pass)."""
    out = []
    for fr in hazards["frames"]:
        e = fr.get("ego") or {}
        out.append({"horizon": fr["horizonY"], "scale": e.get("scale"), "depthScale": e.get("depthScale"), "ego": e,
                    "dcorr": fr.get("depthCorrection")})
    return out


def first_depth_scale(frames: list[dict] | None) -> float | None:
    """The first known depth scale of a run (None when it has none)."""
    for f in frames or ():
        if f.get("depthScale"):
            return float(f["depthScale"])
    return None


def settings_from_hazards(hazards: dict) -> dict:
    s = hazards["settings"]
    return {"hfovDeg": s["hfovDeg"], "cameraHeightM": s["cameraHeightM"], "lateralOffsetM": s.get("lateralOffsetM", 0.0),
            "projection": hazards.get("projection"), "distanceSource": hazards.get("distanceSource", "ground"),
            "objectDistance": s.get("objectDistance", "depth"), "useHorizon": s.get("useHorizon", True)}


class WorldMap:
    """Drives the passes frame by frame (``step``); ``build`` runs it over a whole run, and the collision pass (v26.2.1)
    runs it online (``frames=None``: each ``step`` gets the frame's horizon / scales / ego block)."""

    def __init__(self, grids, times, class_names, frames, settings, coll_cfg, cfg=None, depth=None):
        self.cfg = cfg or load_config()
        self.grids = grids
        self.times = np.asarray(times, dtype=float)
        self.frames = frames
        self.kind = class_kinds(self.cfg, list(class_names))
        n, gh, gw = grids.shape
        self.n, self.gh, self.gw = n, gh, gw
        self.observer = Observer(self.cfg, settings, self.kind, gh, gw, groundfuse.settings((coll_cfg or {}).get("distance", {})), list(class_names))
        self.pose_tracker = PoseTracker(coll_cfg)
        self.pose = np.zeros((n, 3))
        present = np.flatnonzero(np.bincount(np.asarray(grids).ravel(), minlength=256))
        self.fusion = Fusion(self.cfg, self.kind, present, (0.0, 0.0))
        self.last_ds: float | None = None
        self.first_ds = first_depth_scale(frames)
        self.depth_t = self.depth = None
        if depth is not None:
            self.depth_t, self.depth = np.asarray(depth["t"], dtype=float), depth["depth"]

    def depth_map(self, i: int):
        if self.depth is None:
            return None
        t = self.times[i]
        j = int(np.clip(np.searchsorted(self.depth_t, t), 0, len(self.depth_t) - 1))
        if j > 0 and abs(self.depth_t[j - 1] - t) < abs(self.depth_t[j] - t):
            j -= 1
        return np.asarray(self.depth[j])

    def resolve_frame(self, frame: dict) -> dict:
        """v26.2.5: a frame without a depth scale (the plane anchor needs a few frames) uses the nearest known scale of the run: the last
        known one, or, before any (offline, the whole run is known), the first known one of the run."""
        ds = frame.get("depthScale")
        if ds:
            self.last_ds = float(ds)
            return frame
        ds = self.last_ds if self.last_ds is not None else self.first_ds
        return frame if not ds else {**frame, "depthScale": ds}

    def step(self, i: int, frame: dict | None = None, dmap=None, layers: bool = False):
        """Frame i: pose + observation + fusion + snapshot. Returns (obs, snapshot classes, conf, ms).
        ``frame`` = {"horizon", "scale", "depthScale", "ego"} (default: the stored one of ``frames``); ``dmap`` the depth map of
        the frame (default: the nearest one of the run's depth). ``layers``: also keep the separate surface / object layers in
        ``self.last_layers`` (surface, object), for the Lab's cell readout; the collision pass does not need them."""
        t0 = time.perf_counter()
        frame = self.resolve_frame(frame if frame is not None else self.frames[i])
        dmap = dmap if dmap is not None else self.depth_map(i)
        t = float(self.times[i])
        pose = self.pose_tracker.advance(t, frame["ego"])
        self.pose[i] = pose
        self.last_pose = pose
        obs, w = self.observer.observe(np.asarray(self.grids[i]), frame, dmap)
        self.fusion.update(t, pose, obs, w, self.observer)
        if layers:
            classes, conf, surf, objs = self.fusion.snapshot(t, pose, self.observer, True)
            self.last_layers = (surf, objs)
        else:
            classes, conf = self.fusion.snapshot(t, pose, self.observer)
        self.last_frame, self.last_dmap = frame, dmap
        return obs, classes, conf, (time.perf_counter() - t0) * 1000.0


def build(grids, times, class_names, hazards, coll_cfg, cfg=None, depth=None, hook=None) -> dict:
    """The whole run -> the arrays of worldmap.npz. ``hook(i, wm, obs, classes[i])`` is called after each frame (metrics)."""
    frames = frames_from_hazards(hazards)
    if len(frames) != len(grids):
        raise ValueError(f"hazards.json has {len(frames)} frames, grids.npz {len(grids)}")
    wm = WorldMap(grids, times, class_names, frames, settings_from_hazards(hazards), coll_cfg, cfg, depth)
    size = wm.observer.size
    classes = np.full((len(grids), size, size), UNKNOWN, dtype=np.uint8)
    conf = np.zeros((len(grids), size, size), dtype=np.uint8)
    surface = np.full((len(grids), size, size), UNKNOWN, dtype=np.uint8)       # v26.2.4: the surface and the object layer on their own
    objects = np.full((len(grids), size, size), UNKNOWN, dtype=np.uint8)
    ms = np.zeros(len(grids))
    for i in range(len(grids)):
        obs, classes[i], conf[i], ms[i] = wm.step(i, layers=True)
        surface[i], objects[i] = wm.last_layers
        if hook is not None:
            hook(i, wm, obs, classes[i])
    return {"classes": classes, "conf": conf, "surface": surface, "object": objects, "t": wm.times, "pose": wm.pose,
            "cellM": np.float32(wm.cfg["cellM"]), "origin": np.array([wm.observer.oc, wm.observer.orow], dtype=np.int32),
            "ms": ms}
