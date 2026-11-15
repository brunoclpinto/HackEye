"""Worldmap observer: one frame's ego-centric observation (surfaces by inverse ground projection, object bases)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt

from engine.core import distfuse, groundgeom
from engine.core.geom import focal_px
from engine.worldmap.config import KIND_OBJECT, KIND_SURFACE, UNKNOWN

__all__ = ["Observer"]


class Observer:
    """One frame's ego-centric observation: (classes uint8 [255 = unknown], weight float32)."""

    ray_clear: npt.NDArray[Any] | None
    ray_hidden: npt.NDArray[Any] | None

    def __init__(
        self,
        cfg: dict[str, Any],
        settings: dict[str, Any],
        kind: npt.NDArray[Any],
        gh: int,
        gw: int,
        gd_cfg: dict[str, Any] | None = None,
        class_names: list[str] | None = None,
    ):
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
        # v26.2.3: the distance of an object base (the collision pass's own setting, stored in hazards.json) and the
        # horizon switch
        self.use_horizon = settings.get("useHorizon", True) is not False
        self.object_mode = distfuse.resolved_mode(settings.get("objectDistance", "depth"), self.use_horizon)
        self.fisheye = settings.get("projection") == "fisheye"
        self.gd = gd_cfg if gd_cfg is not None else distfuse.settings({})
        self.geo = groundgeom.Geometry(gh, gw, self.hfov, "fisheye" if self.fisheye else "rectilinear", self.cam_h)
        self.f_px = focal_px(gw, self.hfov)
        model = cfg.get("lateralModel", "collision")
        self.lens = model == "lens"
        # v26.2.7: "geometry" = the lens ground geometry (groundgeom.ground_point / ground_pixel / lateral_at) for the
        # map's surfaces, the object
        # bases and the laterals; only on a fisheye run with depth distances (on a rectilinear one the collision pass's
        # pinhole formulas are exact
        # and stay; with ground distances the gait scale already absorbs the lens factor, see collision._frame_geometry)
        self.geometry = model == "geometry" and self.fisheye and self.depth_source
        self.range_w = float(cfg["rangeWeightM"])
        self.max_range = float(cfg["maxRangeM"])
        self.min_fwd = float(cfg["minForwardM"])
        rows, cols = np.mgrid[0 : self.size, 0 : self.size]
        self.fwd = ((self.orow - rows) * self.cell).astype(np.float64)  # metres ahead of the user
        self.right = ((cols - self.oc) * self.cell).astype(np.float64)  # metres to the right (body centre line)
        self.weight = (1.0 / (1.0 + (np.maximum(self.fwd, 0.0) / self.range_w) ** 2)).astype(np.float32)
        # v26.2.5: wall faces (image columns -> one continuous line) and the sky (an object base on sky is not a ground
        # contact)
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
        self.thick_m = float(
            cfg.get("hiddenThicknessM", cfg.get("faceThicknessM", 0.3))
        )  # v26.2.10: the occlusion behind a building
        self.face_thick_m = float(cfg.get("faceThicknessM", 0.3))  # ...apart from the cells a face writes
        # v26.2.7: faces at the ground contact of their base row, occluded faces scaled by the ratio, buildings that
        # hide what is behind them
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
        self.hid_nb = int(math.ceil(180.0 / bin_deg))  # noqa: RUF046
        self.cell_range = np.hypot(self.fwd, self.right)
        self.cell_bin = np.clip(
            np.floor((np.degrees(np.arctan2(self.right, self.fwd)) + 90.0) / bin_deg).astype(np.int64),
            0,
            self.hid_nb - 1,
        )
        # v26.2.7: gap closing in the snapshot: the cells k = 1..K along the line to the user / away from the user (flat
        # indices; size*size = off grid)
        self.gap_k = int(round(float(cfg.get("gapCloseM", 0.0)) / self.cell))  # noqa: RUF046
        self.gap_tab = None
        if self.gap_k > 0:
            ri, ci = np.mgrid[0 : self.size, 0 : self.size]
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
            self.gap_tab = tuple(tabs)  # (toward the user, away from the user), each (K, size * size)

    # -- helpers ----------------------------------------------------------------------------------------------
    def _lateral(self, x: npt.NDArray[Any], d: npt.NDArray[Any]) -> Any:
        """Camera-axis lateral (m, + right) of a pixel column at forward distance d; + the body offset is added by the
        caller."""
        if self.lens:
            return d * np.tan(np.radians((x - 0.5) * self.hfov))
        return (x - 0.5) * self.gw * d / self.f_px

    def ground_scale(self, frame: dict[str, Any]) -> float:
        mode = self.cfg.get("groundScale", "auto")
        if mode == "one" or (mode == "auto" and self.depth_source):
            return 1.0
        return float(frame.get("scale") or 1.0)

    def _bases(self, grid: npt.NDArray[Any], kgrid: npt.NDArray[Any]) -> Any:
        """(rows, cols, below_surface mask of the image) of the lowest pixel of every vertical run of an object class
        (not on the sky)."""
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
            base &= ~below_sky  # v26.2.5: an object base standing on the sky is not a ground contact
        rr, cc = np.nonzero(base)
        return rr, cc, below_surface

    def face_contact_samples(
        self, grid: npt.NDArray[Any], dmap: npt.NDArray[Any] | None, depth_scale: float | None, horizon: float
    ) -> Any:
        """v26.2.7: (depth m, lens ground z m) of the face-class bases that stand on a surface: a wall base is a ground
        point seen at the
        wall's own range, a free calibration of the depth where the walking region does not reach. Same base / contact
        rules and the same
        bottom-``faceDepthRows`` median depth as ``object_bases``; the depth is scaled, never range-corrected; the
        ground z is the camera-axis
        depth of the floor point of the base row (``groundgeom.ground_z``, the quantity the depth map holds) for the
        setting's camera height.
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
        g = groundgeom.ground_z(self.geo, rr + 1.0, cc + 0.5, horizon)
        with np.errstate(invalid="ignore"):
            ok = (
                np.isfinite(v)
                & (v > 0)
                & np.isfinite(g)
                & (g > 0)
                & ((rr + 1.0) - horizon * gh >= float(self.gd["minRowsBelowHorizon"]))
                & (g <= float(self.gd["fuseMaxM"]))
            )
        return v[ok], g[ok]

    def object_bases(
        self,
        grid: npt.NDArray[Any],
        frame: dict[str, Any],
        dmap: npt.NDArray[Any] | None,
        kgrid: npt.NDArray[Any] | None = None,
    ) -> Any:
        """The ground base of every vertical run of an object class: (rows, cols, forward distance m, lateral m in body
        coordinates) of the image pixels that are projected into the map. The collision rules (v26.2.1) read the same
        points to
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
        contact = below_surface[rr, cc] & (y_b > horizon + 1e-6) & (rr < gh - 1)  # stands on the ground
        if (
            self.geometry
        ):  # v26.2.7: the ground point of the base row through the lens (forward m); nan above the horizon
            ground = groundgeom.ground_point(self.geo, rr + 1.0, cc + 0.5, horizon, cam_h)[0]
        else:
            ground = cam_h * self.f_px / (np.maximum(y_b - horizon, 1e-6) * gh)
        has_depth = dmap is not None and bool(frame.get("depthScale"))
        if not self.use_horizon and not has_depth:
            return empty  # horizon off: depth is the only distance
        if has_depth:
            dist = float(frame["depthScale"]) * self._run_depth(grid, dmap, rr, cc)
            good = np.isfinite(dist) & (dist > 0)
            rep_ = frame.get("dcorr")
            if self.use_horizon and self.object_mode != "depth" and rep_ is not None and contact.any():
                # v26.2.3: the same fusion the collision pass uses for an item (distfuse.resolve), per base pixel;
                # v26.2.5: only for
                # bases that stand on a surface, the others keep the depth of their run
                g_m, sg_m = groundgeom.ground_m(self.geo, y_b * gh, cc + 0.5, horizon, rep_, float(rep_["sigmaRows"]))
                fused, _ = distfuse.resolve(
                    np.where(good, dist, 1.0), g_m, sg_m, (y_b - horizon) * gh, contact, rep_, self.gd, self.object_mode
                )
                dist = np.where(contact, fused, dist)
            if self.face_ground and self.use_horizon:
                dist = self._face_ground(grid[rr, cc], dist, good, contact, ground, (y_b - horizon) * gh)
        else:  # ground distance of the base row; needs the ground below it
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
            lat_b = groundgeom.lateral_at(self.geo, rr + 1.0, cc + 0.5, dist, horizon) + self.lat_off
        else:
            lat_b = self._lateral((cc + 0.5) / gw, dist) + self.lat_off
        return rr, cc, dist, lat_b

    def _face_ground(
        self,
        cls: npt.NDArray[Any],
        dist: npt.NDArray[Any],
        good: npt.NDArray[Any],
        contact: npt.NDArray[Any],
        ground: npt.NDArray[Any],
        rows_below: npt.NDArray[Any],
    ) -> npt.NDArray[Any]:
        """v26.2.7 (``faceGroundContact``): a face-class base that stands on a surface takes the lens ground distance of
        its base row, the
        geometry the surface projection uses, so that the sidewalk and the building edge meet in one cell. With
        ``faceScaleOccluded`` the
        class's other bases (its facade above a car, a pole, a sign...) follow: ratio = median(ground / depth) over its
        contact bases
        (at least ``faceRatioMinBases``, clamped to ``faceRatioClamp``), applied to their depth."""
        face = self.face_lut[cls]
        if not face.any():
            return dist
        with np.errstate(invalid="ignore"):
            use = (
                face
                & contact
                & good
                & np.isfinite(ground)
                & (rows_below >= float(self.gd["minRowsBelowHorizon"]))
                & (ground >= self.min_fwd)
                & (ground <= self.max_range)
            )
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

    def _run_depth(self, grid: npt.NDArray[Any], dmap: Any, rr: npt.NDArray[Any], cc: npt.NDArray[Any]) -> Any:
        """v26.2.5: the depth of every base = the median of the bottom ``faceDepthRows`` rows of its vertical run (same
        class, same
        column), in depth-map units. One edge pixel mixes the object's depth with what is below or behind it."""
        gh, gw = self.gh, self.gw
        dh, dw = dmap.shape
        cls = grid[rr, cc]
        col_d = np.minimum(dw - 1, ((cc + 0.5) / gw * dw).astype(int))
        vals = np.full((self.depth_rows, rr.size), np.nan)
        alive = np.ones(rr.size, dtype=bool)
        for k in range(self.depth_rows):
            r = rr - k
            alive &= r >= 0
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

    def _smooth_faces(
        self, cls: npt.NDArray[Any], cc: npt.NDArray[Any], dist: npt.NDArray[Any], face: npt.NDArray[Any]
    ) -> Any:
        """v26.2.5: for the face-class bases, a running median of the distance over +-``faceSmoothCols`` image columns
        of the same class; a
        point further than ``faceOutlierFrac`` from it is dropped, the others take the median. Returns (dist, keep
        mask)."""
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
            stack = np.concatenate([table[j : j + self.gw] for j in range(2 * k + 1)], axis=1)  # (gw, (2k+1) * runs)
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                med = np.nanmedian(stack, axis=1)
            m = med[cols]
            bad = np.abs(dist[order] - m) > self.outlier_frac * m
            keep[order[bad]] = False
            out[order] = m
        return out, keep

    def _face_rays(self, cls: npt.NDArray[Any], dist: npt.NDArray[Any], lat_b: npt.NDArray[Any]) -> None:
        """v26.2.5 (optional clearing): the cells on the ray from the user to each face point, from ``minForwardM`` to
        the face distance minus
        ``objectClearMarginM``, are free space even where the ground is not visible (hidden behind a mover). Stored in
        ``self.ray_clear``."""
        if float(self.cfg.get("objectClearRays", 0)) <= 0:
            return
        face = self.face_lut[cls]
        if not face.any():
            return
        margin = float(self.cfg.get("objectClearMarginM", 0.3))
        d, l = dist[face], lat_b[face]  # noqa: E741
        end = d - margin
        ok = end > self.min_fwd
        d, l, end = d[ok], l[ok], end[ok]  # noqa: E741
        if not d.size:
            return
        rng_ = np.hypot(d, l)
        n = int(np.ceil((end / d * rng_).max() / self.cell)) + 1
        k = np.arange(1, n + 1)[None, :] * self.cell  # range along the ray
        frac = k / rng_[:, None]
        valid = (frac * d[:, None] >= self.min_fwd) & (frac * d[:, None] <= end[:, None])
        rows = self.orow - np.rint(frac * d[:, None] / self.cell).astype(np.int64)
        cols = self.oc + np.rint(frac * l[:, None] / self.cell).astype(np.int64)
        m = np.zeros((self.size, self.size), dtype=bool)
        v = valid & (rows >= 0) & (rows < self.size) & (cols >= 0) & (cols < self.size)
        m[rows[v], cols[v]] = True
        a = m.copy()
        a[1:] |= m[:-1]
        a[:-1] |= m[1:]
        b = a.copy()
        b[:, 1:] |= a[:, :-1]
        b[:, :-1] |= a[:, 1:]
        self.ray_clear = b

    def _hidden_cells(
        self, cls: npt.NDArray[Any], dist: npt.NDArray[Any], lat_b: npt.NDArray[Any], obs: npt.NDArray[Any]
    ) -> None:
        """v26.2.7 (``occluderClasses``): a building closes the view: the cells behind an occluder face point, from its
        range +
        ``faceThicknessM`` outwards along its bearing, cannot be seen by this frame. Per ``hiddenBinDeg`` bearing bin
        the nearest occluder
        range (gaps of up to two empty bins between occluder points are bridged: a facade is continuous); the cells this
        frame sees as surface
        itself are not hidden (visible ground wins). Stored in ``self.ray_hidden`` (the fusion cuts the stored surface
        votes there)."""
        if self.hidden_factor >= 1.0:
            return
        occ = self.occ_lut[cls]
        if not occ.any():
            return
        d, l = dist[occ], lat_b[occ]  # noqa: E741
        rng_ = np.hypot(d, l)
        b = np.clip(
            np.floor((np.degrees(np.arctan2(l, d)) + 90.0) / self.hid_bin_deg).astype(np.int64), 0, self.hid_nb - 1
        )
        r: npt.NDArray[Any] = np.full(self.hid_nb, np.inf)
        np.minimum.at(r, b, rng_)
        left, right = r.copy(), r.copy()
        for sft in (1, 2):  # nearest occupied bin within two bins on each side
            left[sft:] = np.where(np.isfinite(left[sft:]), left[sft:], r[:-sft])
            right[:-sft] = np.where(np.isfinite(right[:-sft]), right[:-sft], r[sft:])
        r = np.where(
            np.isfinite(r), r, np.where(np.isfinite(left) & np.isfinite(right), np.maximum(left, right), np.inf)
        )
        hidden = self.cell_range > (r + self.thick_m)[self.cell_bin]
        hidden &= ~((self.kind[obs] == KIND_SURFACE) & (obs != UNKNOWN))
        self.ray_hidden = hidden

    def _face_cells(self, grid: Any, rr: Any, cc: Any, dist: Any, lat_b: Any) -> Any:
        """v26.2.5: cells of the faces: adjacent image columns of the same face class whose distances differ by less
        than ``faceJoinFrac``
        are joined by a straight segment on the map, ``faceThicknessM`` thick, extended away from the user along the
        ray.
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
        n_steps = max(0, int(round(self.face_thick_m / self.cell)))  # noqa: RUF046
        pf = np.stack([dist[seg_a], dist[seg_b]], 1)  # forward (m) of the two ends
        pr = np.stack([lat_b[seg_a], lat_b[seg_b]], 1)  # right (m)
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

    def observe(
        self, grid: npt.NDArray[Any], frame: dict[str, Any], dmap: npt.NDArray[Any] | None
    ) -> tuple[npt.NDArray[Any], npt.NDArray[Any]]:
        gh, gw, size = self.gh, self.gw, self.size  # noqa: F841
        obs = np.full((size, size), UNKNOWN, dtype=np.uint8)
        horizon = float(frame["horizon"])
        self.last_horizon = horizon
        self.geo.roll = math.radians(
            float((frame.get("ego") or {}).get("rollCorrectDeg") or 0.0)
        )  # v26.2.11 (ego.rollCorrect)
        cam_h = self.cam_h * self.ground_scale(frame)
        kgrid = self.kind[grid]
        if not self.use_horizon and dmap is not None and frame.get("depthScale"):
            self._depth_surfaces(obs, grid, kgrid, frame, dmap)  # v26.2.3: surfaces through the depth map, no horizon
        else:
            self._ground_surfaces(obs, grid, kgrid, horizon, cam_h)
        # --- object bases ----------------------------------------------------------------------------------
        self.ray_clear = None
        self.ray_hidden = None
        rr, cc, dist, lat_b = self.object_bases(grid, frame, dmap, kgrid)
        if rr.size:
            col = self.oc + np.rint(lat_b / self.cell).astype(np.int64)
            row = self.orow - np.rint(dist / self.cell).astype(np.int64)
            half = np.minimum(
                4, np.rint(dist / self.f_px / 2.0 / self.cell).astype(np.int64)
            )  # one image column's width
            vals = grid[rr, cc]
            cells_r, cells_c, cells_v, cells_k = [], [], [], []
            for off in range(-4, 5):
                m = half >= abs(off)
                cells_r.append(row[m])
                cells_c.append(col[m] + off)
                cells_v.append(vals[m])
                cells_k.append(dist[m])
            fr_, fc_, fv_, fk_ = self._face_cells(grid, rr, cc, dist, lat_b)  # v26.2.5: the joined, thick wall faces
            cells_r.append(fr_)
            cells_c.append(fc_)
            cells_v.append(fv_)
            cells_k.append(fk_)
            ry, cx, vv, kk = (np.concatenate(x) for x in (cells_r, cells_c, cells_v, cells_k))
            order = np.argsort(-kk, kind="stable")  # nearer points are written last and win
            ry, cx, vv = ry[order], cx[order], vv[order]
            inside = (cx >= 0) & (cx < size) & (ry >= 0) & (ry < size)
            obs[ry[inside], cx[inside]] = vv[inside]
            self._face_rays(grid[rr, cc], dist, lat_b)
            self._hidden_cells(grid[rr, cc], dist, lat_b, obs)
        self.seen = (
            obs != UNKNOWN
        )  # v26.2.10: the cells whose ground (or object base) this frame sees; hidden / out of view = False
        w = np.where(obs != UNKNOWN, self.weight, 0.0).astype(np.float32)
        gain = float(self.cfg.get("objectVoteGain", 1.0))  # an object base is one thin line among many surface cells
        if gain != 1.0:
            w[self.kind[obs] == KIND_OBJECT] *= np.float32(gain)
        return obs, w

    def _ground_surfaces(
        self, obs: npt.NDArray[Any], grid: npt.NDArray[Any], kgrid: npt.NDArray[Any], horizon: float, cam_h: float
    ) -> None:
        """Surfaces: inverse ground-plane sampling (each map cell -> the image pixel that sees it, through the horizon).
        v26.2.7
        (``lateralModel`` "geometry", fisheye): through the lens (``groundgeom.ground_pixel``, the exact inverse of
        ``ground_point``)."""
        gh, gw = self.gh, self.gw
        fwd = self.fwd
        ok = (fwd >= self.min_fwd) & (fwd <= self.max_range)
        d = np.where(ok, fwd, 1.0)
        lat = self.right - self.lat_off
        if self.geometry:
            row_f, col_f = groundgeom.ground_pixel(self.geo, d, lat, horizon, cam_h)
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

    def _depth_surfaces(
        self,
        obs: npt.NDArray[Any],
        grid: npt.NDArray[Any],
        kgrid: npt.NDArray[Any],
        frame: dict[str, Any],
        dmap: npt.NDArray[Any],
    ) -> None:
        """Surfaces through the depth map (horizon off): every surface pixel is back-projected along its lens ray
        (equidistant fisheye or pinhole)
        at its z-depth x the depth scale, forward distance = z cos(pitch) - y sin(pitch) with the plane-fit pitch when
        the run has one, and splatted
        into the cells around it (the footprint of a pixel grows with range); nearer pixels are written last."""
        gh, gw = self.gh, self.gw
        rr, cc = np.nonzero(kgrid == KIND_SURFACE)
        if not rr.size:
            return
        dh, dw = dmap.shape
        z = dmap[
            np.minimum(dh - 1, ((rr + 0.5) / gh * dh).astype(int)),
            np.minimum(dw - 1, ((cc + 0.5) / gw * dw).astype(int)),
        ].astype(np.float64) * float(frame["depthScale"])
        px, py = cc + 0.5 - gw / 2.0, rr + 0.5 - gh / 2.0
        if self.geo.roll:
            cr, sr = math.cos(self.geo.roll), math.sin(self.geo.roll)
            px, py = px * cr - py * sr, px * sr + py * cr
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
        # one image row is F^2 / (H f) metres deep on the ground: the cells between two rows are filled up to 6 cells
        # (0.6 m) either side
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
