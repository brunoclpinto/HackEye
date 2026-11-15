"""Worldmap fusion: the world-frame vote grid (decayed class votes, recentred as the user moves)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from engine.core import groundgeom
from engine.worldmap.config import KIND_OBJECT, KIND_SURFACE, UNKNOWN

if TYPE_CHECKING:
    from engine.worldmap.observer import Observer

__all__ = ["Fusion"]


class Fusion:
    """World-frame decayed class votes (0.10 m cells, ``windowM`` square, recentred), plus an observation count."""

    def __init__(
        self, cfg: dict[str, Any], kind: npt.NDArray[Any], present: npt.NDArray[Any], start_xy: tuple[float, float]
    ):
        self.cfg = cfg
        self.cell = float(cfg["cellM"])
        self.n = int(round(cfg["windowM"] / self.cell))  # noqa: RUF046
        self.decay_mode = str(cfg.get("decay", "time"))  # v26.2.10: "none" (facts persist) | "time" (v26.2.9)
        self.lam = math.log(2.0) / float(cfg["halfLifeSeconds"]) if self.decay_mode == "time" else 0.0
        self.conflict = float(cfg.get("conflictFactor", 1.0))  # v26.2.10: other classes of a SEEN cell's layer x this
        self.vote_cap = float(cfg.get("voteCap", 0.0))  # ...and the layer total is capped (0 = off)
        self.confront = self.conflict < 1.0 or self.vote_cap > 0.0
        self.floor = float(cfg["weightFloor"])
        self.full = float(cfg["confFullWeight"])
        keep = [int(c) for c in present if kind[c] in (KIND_SURFACE, KIND_OBJECT)]
        keep = keep or [0]  # a run with no surface / object class at all: one empty layer
        self.classes = np.array(keep, dtype=np.uint8)
        self.is_surface = np.array(
            [kind[c] == KIND_SURFACE for c in keep]
        )  # per vote layer: surface class / object class
        self.lut = np.full(256, -1, dtype=np.int16)
        for k, c in enumerate(keep):
            self.lut[c] = k
        self.surf_layers = np.flatnonzero(self.is_surface)
        self.obj_layers = np.flatnonzero(~self.is_surface)
        self.layer_pos = np.zeros(len(keep), dtype=np.int64)  # position of a layer inside its group
        self.layer_pos[self.surf_layers] = np.arange(self.surf_layers.size)
        self.layer_pos[self.obj_layers] = np.arange(self.obj_layers.size)
        self.votes = np.zeros((max(1, len(keep)), self.n, self.n), dtype=np.float32)
        self.count = np.zeros((self.n, self.n), dtype=np.uint16)
        self.x0 = start_xy[0] - self.n * self.cell / 2.0  # world coordinates of the window's corner (cell 0,0)
        self.y0 = start_xy[1] - self.n * self.cell / 2.0
        self.t_base = 0.0

    def _recentre(self, x: float, y: float, margin_m: float = 22.0) -> None:
        half = self.n * self.cell / 2.0
        cx, cy = self.x0 + half, self.y0 + half
        if abs(x - cx) <= half - margin_m and abs(y - cy) <= half - margin_m:
            return
        sx = int(round((x - cx) / self.cell))  # noqa: RUF046
        sy = int(round((y - cy) / self.cell))  # noqa: RUF046
        n = self.n
        new_v = np.zeros_like(self.votes)
        new_c = np.zeros_like(self.count)
        # new cell (i, j) holds old cell (i + sy, j + sx)
        i0, i1 = max(0, -sy), min(n, n - sy)
        j0, j1 = max(0, -sx), min(n, n - sx)
        if i1 > i0 and j1 > j0:
            new_v[:, i0:i1, j0:j1] = self.votes[:, i0 + sy : i1 + sy, j0 + sx : j1 + sx]
            new_c[i0:i1, j0:j1] = self.count[i0 + sy : i1 + sy, j0 + sx : j1 + sx]
        self.votes, self.count = new_v, new_c
        self.x0 += sx * self.cell
        self.y0 += sy * self.cell

    def _ego_to_world_idx(
        self, fwd: npt.NDArray[Any], right: npt.NDArray[Any], pose: tuple[float, float, float]
    ) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
        x, y, th = pose[0], pose[1], math.radians(pose[2])
        s, c = math.sin(th), math.cos(th)
        wx = x + s * fwd + c * right
        wy = y + c * fwd - s * right
        return (
            np.floor((wy - self.y0) / self.cell).astype(np.int64),
            np.floor((wx - self.x0) / self.cell).astype(np.int64),
        )

    def update(
        self, t: float, pose: tuple[float, float, float], obs: npt.NDArray[Any], w: npt.NDArray[Any], observer: Observer
    ) -> None:
        """Inverse mapping: every world cell of the ego window's bounding box looks up the observation cell it falls
        in."""
        self._recentre(pose[0], pose[1])
        if self.lam > 0.0 and t - self.t_base > 20.0:  # keep exp(lambda t) in range
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
        j0 = max(0, int(math.floor((min(wxs) - self.x0) / cell)))  # noqa: RUF046
        j1 = min(self.n, int(math.ceil((max(wxs) - self.x0) / cell)))  # noqa: RUF046
        i0 = max(0, int(math.floor((min(wys) - self.y0) / cell)))  # noqa: RUF046
        i1 = min(self.n, int(math.ceil((max(wys) - self.y0) / cell)))  # noqa: RUF046
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
        self._clear_stale_objects(obs, observer, row, col, ii, jj, inb, getattr(observer, "last_horizon", None))
        self._cut_hidden_surfaces(observer, row, col, ii, jj, inb)
        k = self.lut[cls]
        ok &= k >= 0
        if not ok.any():
            return
        scale = math.exp(self.lam * (t - self.t_base))
        amp = w[row, col] * np.float32(scale)
        if self.confront:
            self._add_confronted(k[ok], ii[ok], jj[ok], amp[ok], scale)
        else:
            self.votes[k[ok], ii[ok], jj[ok]] += amp[ok]
        self.count[ii[ok], jj[ok]] += 1

    def _add_confronted(
        self, ks: npt.NDArray[Any], ia: npt.NDArray[Any], ja: npt.NDArray[Any], a: npt.NDArray[Any], scale: float
    ) -> None:
        """v26.2.10: the new votes ``a`` of class layers ``ks`` at the SEEN world cells (ia, ja) (each cell once): first
        the votes of every other class of the same layer group (surface / object) are multiplied by ``conflictFactor``,
        then the group's total at the cell is capped at ``voteCap`` (x ``scale``: the stored votes are pre-multiplied by
        exp(lambda t), 1 without decay)."""
        for layers in (self.surf_layers, self.obj_layers):
            if not layers.size:
                continue
            m = np.flatnonzero(np.isin(ks, layers))
            if not m.size:
                continue
            i_, j_, pos, a_ = ia[m], ja[m], self.layer_pos[ks[m]], a[m]
            v = self.votes[layers[:, None], i_[None, :], j_[None, :]]  # (L, M) copy
            cols = np.arange(m.size)
            if self.conflict < 1.0:
                keep_own = v[pos, cols].copy()
                v *= np.float32(self.conflict)
                v[pos, cols] = keep_own
            v[pos, cols] += a_
            if self.vote_cap > 0.0:
                tot = v.sum(axis=0)
                v *= np.minimum(
                    np.float32(1.0), np.float32(self.vote_cap * scale) / np.maximum(tot, np.float32(1e-12))
                )[None, :]
            self.votes[layers[:, None], i_[None, :], j_[None, :]] = v

    def surface_at(
        self,
        pose: tuple[float, float, float],
        fwd: npt.NDArray[Any],
        right: npt.NDArray[Any],
        t: float,
        min_votes: float,
    ) -> npt.NDArray[Any]:
        """v26.2.10: the stored winning surface class (UNKNOWN where the map has none with at least ``min_votes``) at
        ego points seen from ``pose``."""
        iy, ix = self._ego_to_world_idx(fwd, right, pose)
        inside = (iy >= 0) & (iy < self.n) & (ix >= 0) & (ix < self.n)
        iy, ix = np.clip(iy, 0, self.n - 1), np.clip(ix, 0, self.n - 1)
        if not self.surf_layers.size:
            return np.full(fwd.shape, UNKNOWN, dtype=np.uint8)
        v = self.votes[self.surf_layers[:, None], iy[None, :], ix[None, :]]
        known = inside & (v.sum(axis=0) * np.float32(self._decay(t)) > min_votes)
        return np.where(known, self.classes[self.surf_layers][v.argmax(axis=0)], UNKNOWN).astype(np.uint8)

    def _clear_stale_objects(
        self,
        obs: npt.NDArray[Any],
        observer: Observer,
        row: npt.NDArray[Any],
        col: npt.NDArray[Any],
        ii: npt.NDArray[Any],
        jj: npt.NDArray[Any],
        ok: npt.NDArray[Any],
        frame_horizon: float | None = None,
    ) -> None:
        """v26.2.5 negative evidence: a world cell that the current frame sees as a surface (visible ground) loses ``1 -
        objectClearFactor`` of its object votes, except within ``objectClearMarginM`` of a cell the frame writes as an
        object (the horizon-projected ground and the depth-placed wall disagree by a few tenths). Surface votes are
        untouched; the stored (pre-multiplied) votes scale linearly."""
        f = float(self.cfg.get("objectClearFactor", 1.0))
        obj_layers = np.flatnonzero(~self.is_surface)
        if f >= 1.0 or not obj_layers.size:
            return
        kgrid = observer.kind[obs]
        is_obj = (kgrid == KIND_OBJECT) & (obs != UNKNOWN)
        near = is_obj.copy()
        m = int(round(float(self.cfg.get("objectClearMarginM", 0.3)) / self.cell))  # noqa: RUF046
        for _ in range(m):  # square dilation by the margin
            a = near.copy()
            a[1:] |= near[:-1]
            a[:-1] |= near[1:]
            b = a.copy()
            b[:, 1:] |= a[:, :-1]
            b[:, :-1] |= a[:, 1:]
            near = b
        clear = (kgrid == KIND_SURFACE) & (obs != UNKNOWN)
        if getattr(observer, "ray_clear", None) is not None:
            clear |= observer.ray_clear
        clear &= ~near
        # an object whose base left the bottom of the image stands just nearer than the nearest visible ground: keep a
        # band at the bottom edge
        if frame_horizon is None:
            d_bottom = 0.0
        elif (
            observer.geometry
        ):  # v26.2.7: the forward distance of the last image row on the centre column, through the lens
            d_bottom = float(
                groundgeom.ground_point(
                    observer.geo, float(observer.gh), observer.gw / 2.0, float(frame_horizon), observer.cam_h
                )[0]
            )
            d_bottom = d_bottom if math.isfinite(d_bottom) else 0.0
        else:
            d_bottom = float(observer.cam_h) * observer.f_px / (max(1.0 - float(frame_horizon), 1e-6) * observer.gh)
        clear &= observer.fwd >= d_bottom + float(self.cfg.get("objectClearBottomM", 0.5))
        sel = ok & clear[row, col]
        if sel.any():
            for k in obj_layers:
                self.votes[k, ii[sel], jj[sel]] *= np.float32(f)

    def _cut_hidden_surfaces(
        self,
        observer: Observer,
        row: npt.NDArray[Any],
        col: npt.NDArray[Any],
        ii: npt.NDArray[Any],
        jj: npt.NDArray[Any],
        ok: npt.NDArray[Any],
    ) -> None:
        """v26.2.7: a world cell that maps to an ego cell hidden behind a building (``Observer.ray_hidden``) loses ``1 -
        surfaceHiddenFactor`` of its stored SURFACE votes (a street cannot be seen through a facade); object votes are
        untouched. Mirrors ``_clear_stale_objects``."""
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

    def snapshot(
        self, t: float, pose: tuple[float, float, float], observer: Observer, layers: bool = False
    ) -> tuple[Any, ...]:
        """The fused map in the ego frame: (classes, conf), or with ``layers`` (classes, conf, surface, object): the
        winning surface class and the winning object class of every cell on their own (255 = none), so that an object
        does not hide the surface under it."""
        iy, ix = self._ego_to_world_idx(observer.fwd, observer.right, pose)
        inside = (iy >= 0) & (iy < self.n) & (ix >= 0) & (ix < self.n)
        iy, ix = np.clip(iy, 0, self.n - 1), np.clip(ix, 0, self.n - 1)
        v = self.votes[:, iy, ix]  # (K, size, size)
        decay = np.float32(self._decay(t))
        total = v.sum(axis=0) * decay
        top = v.argmax(axis=0)
        share = np.take_along_axis(v, top[None], 0)[0] / np.maximum(v.sum(axis=0), 1e-12)
        known = inside & (total > self.floor)
        classes = np.where(known, self.classes[top], UNKNOWN).astype(np.uint8)
        conf = np.where(known, 255.0 * np.minimum(1.0, total / self.full) * share, 0.0)
        # v26.2.5: a thin wall line is not hidden by the big surface area projected through it: a cell is the winning
        # object class when the object layers hold at least ``objectWinShare`` of its (decayed) weight, above the
        # floor
        win = float(self.cfg.get("objectWinShare", 0.0))
        if win > 0.0 and (~self.is_surface).any() and self.is_surface.any():
            vo = v[~self.is_surface]
            o_raw = vo.sum(axis=0)
            o_dec = o_raw * decay
            o_win = (
                inside & (o_dec > self.floor) & (o_raw >= win * np.maximum(v.sum(axis=0), 1e-12)) & self.is_surface[top]
            )
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
            out[1].ravel()[gap[0]] = gap[1]  # the closed gap is a face in the object layer too
        return classes, conf.astype(np.uint8), out[0], out[1]

    @staticmethod
    def close_gaps(
        classes: npt.NDArray[Any], conf: npt.NDArray[Any], observer: Observer
    ) -> tuple[npt.NDArray[Any], npt.NDArray[Any], npt.NDArray[Any]] | None:
        """v26.2.7 (``gapCloseM``): an unknown cell whose line toward the user meets a surface cell, and whose line away
        from the user meets a face-class cell, both within ``gapCloseM``, is a seam between a sidewalk and a building: a
        ground and a wall do not have a gap between them. Returns (flat cell indices, face classes, face confs) of the
        cells that take the nearest face cell's class and conf, or None."""
        toward, away = observer.gap_tab  # type: ignore[misc]  # set by Observer when gapCloseM > 0, as before
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
        src = away[is_face.argmax(axis=0), cand]  # flat index of the nearest face cell
        return cand, flat[src], np.append(np.asarray(conf).ravel(), 0)[src]

    def world_classes(self, t: float) -> tuple[npt.NDArray[Any], npt.NDArray[Any]]:
        """Whole window: (classes uint8 [255 unknown], decayed total weight); for metrics."""
        total = self.votes.sum(axis=0) * np.float32(self._decay(t))
        cls = np.where(total > self.floor, self.classes[self.votes.argmax(axis=0)], UNKNOWN).astype(np.uint8)
        return cls, total
