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
3. Fusion (``Fusion``): a world-frame vote grid, recentred as the user moves; class = argmax vote when the weight is above a floor.
   v26.2.10 (facts only): ``decay`` "none" (the default): a cell the frame does not SEE (hidden by a person / car, out of view) keeps its
   votes unchanged; a SEEN cell first multiplies the votes of the other classes of the same layer by ``conflictFactor`` and caps its
   layer total at ``voteCap`` (the new observation is confronted with the stored one). ``decay`` "time" keeps the v26.2.9 fusion
   (exponential decay, lazily: votes stored pre-multiplied by exp(lambda t)). ``poseAlign``: the frame's pose is searched a little
   (heading, shift) for the best agreement of the seen surface cells with the stored map before fusing.
4. Snapshot: the fused map resampled into the ego frame, as one class per cell (surface and objects voting together: the
   collision rules read it) and, for the Lab's click readout (v26.2.4), as two separate layers: the winning surface class and the
   winning object class of every cell.
"""
from __future__ import annotations

import math
import sys
import time

import numpy as np

import collision  # noqa: F401  (kept as a module attribute)
import groundfuse
from collision import focal_px, ground_distance_m, lateral_m  # noqa: F401
import engine.worldmap.config as _wcfg
from engine.worldmap.config import (  # noqa: F401  (same objects; the conftest patches ``load_config`` on this module)
    KIND_IGNORE,
    KIND_MOVER,
    KIND_OBJECT,
    KIND_SURFACE,
    UNKNOWN,
    class_kinds,
    load_config,
)
from engine.worldmap.helpers import (  # noqa: F401
    face_contact_samples,
    first_depth_scale,
    frames_from_hazards,
    settings_from_hazards,
)
from engine.worldmap.observer import Observer  # noqa: F401
from engine.worldmap.pose import PoseTracker, integrate_pose  # noqa: F401


def _facade_loader() -> dict:
    return sys.modules[__name__].load_config()


_wcfg.default_config_loader = _facade_loader


class Fusion:
    """World-frame decayed class votes (0.10 m cells, ``windowM`` square, recentred), plus an observation count."""

    def __init__(self, cfg: dict, kind: np.ndarray, present: np.ndarray, start_xy: tuple[float, float]):
        self.cfg = cfg
        self.cell = float(cfg["cellM"])
        self.n = int(round(cfg["windowM"] / self.cell))
        self.decay_mode = str(cfg.get("decay", "time"))                           # v26.2.10: "none" (facts persist) | "time" (v26.2.9)
        self.lam = math.log(2.0) / float(cfg["halfLifeSeconds"]) if self.decay_mode == "time" else 0.0
        self.conflict = float(cfg.get("conflictFactor", 1.0))                      # v26.2.10: other classes of a SEEN cell's layer x this
        self.vote_cap = float(cfg.get("voteCap", 0.0))                             # ...and the layer total is capped (0 = off)
        self.confront = self.conflict < 1.0 or self.vote_cap > 0.0
        self.floor = float(cfg["weightFloor"])
        self.full = float(cfg["confFullWeight"])
        keep = [int(c) for c in present if kind[c] in (KIND_SURFACE, KIND_OBJECT)]
        keep = keep or [0]                       # a run with no surface / object class at all: one empty layer
        self.classes = np.array(keep, dtype=np.uint8)
        self.is_surface = np.array([kind[c] == KIND_SURFACE for c in keep])           # per vote layer: surface class / object class
        self.lut = np.full(256, -1, dtype=np.int16)
        for k, c in enumerate(keep):
            self.lut[c] = k
        self.surf_layers = np.flatnonzero(self.is_surface)
        self.obj_layers = np.flatnonzero(~self.is_surface)
        self.layer_pos = np.zeros(len(keep), dtype=np.int64)                       # position of a layer inside its group
        self.layer_pos[self.surf_layers] = np.arange(self.surf_layers.size)
        self.layer_pos[self.obj_layers] = np.arange(self.obj_layers.size)
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
        if self.lam > 0.0 and t - self.t_base > 20.0:    # keep exp(lambda t) in range
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
        scale = math.exp(self.lam * (t - self.t_base))
        amp = w[row, col] * np.float32(scale)
        if self.confront:
            self._add_confronted(k[ok], ii[ok], jj[ok], amp[ok], scale)
        else:
            self.votes[k[ok], ii[ok], jj[ok]] += amp[ok]
        self.count[ii[ok], jj[ok]] += 1

    def _add_confronted(self, ks: np.ndarray, ia: np.ndarray, ja: np.ndarray, a: np.ndarray, scale: float) -> None:
        """v26.2.10: the new votes ``a`` of class layers ``ks`` at the SEEN world cells (ia, ja) (each cell once): first the votes of every
        other class of the same layer group (surface / object) are multiplied by ``conflictFactor``, then the group's total at the cell is
        capped at ``voteCap`` (x ``scale``: the stored votes are pre-multiplied by exp(lambda t), 1 without decay)."""
        for layers in (self.surf_layers, self.obj_layers):
            if not layers.size:
                continue
            m = np.flatnonzero(np.isin(ks, layers))
            if not m.size:
                continue
            i_, j_, pos, a_ = ia[m], ja[m], self.layer_pos[ks[m]], a[m]
            v = self.votes[layers[:, None], i_[None, :], j_[None, :]]              # (L, M) copy
            cols = np.arange(m.size)
            if self.conflict < 1.0:
                keep_own = v[pos, cols].copy()
                v *= np.float32(self.conflict)
                v[pos, cols] = keep_own
            v[pos, cols] += a_
            if self.vote_cap > 0.0:
                tot = v.sum(axis=0)
                v *= np.minimum(np.float32(1.0), np.float32(self.vote_cap * scale) / np.maximum(tot, np.float32(1e-12)))[None, :]
            self.votes[layers[:, None], i_[None, :], j_[None, :]] = v

    def surface_at(self, pose: tuple[float, float, float], fwd: np.ndarray, right: np.ndarray, t: float, min_votes: float) -> np.ndarray:
        """v26.2.10: the stored winning surface class (UNKNOWN where the map has none with at least ``min_votes``) at ego points seen from ``pose``."""
        iy, ix = self._ego_to_world_idx(fwd, right, pose)
        inside = (iy >= 0) & (iy < self.n) & (ix >= 0) & (ix < self.n)
        iy, ix = np.clip(iy, 0, self.n - 1), np.clip(ix, 0, self.n - 1)
        if not self.surf_layers.size:
            return np.full(fwd.shape, UNKNOWN, dtype=np.uint8)
        v = self.votes[self.surf_layers[:, None], iy[None, :], ix[None, :]]
        known = inside & (v.sum(axis=0) * np.float32(self._decay(t)) > min_votes)
        return np.where(known, self.classes[self.surf_layers][v.argmax(axis=0)], UNKNOWN).astype(np.uint8)

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
        # v26.2.10: the map's own pose = the dead-reckoned one + a correction that the map itself finds (poseAlign)
        self.align_on = bool(self.cfg.get("poseAlign", False))
        self.props: list = []                                # the last proposals of the alignment search (dth, dfwd, dright)
        self.align_th = 0.0                                  # accumulated heading correction (deg)
        self.pos_c = [0.0, 0.0]                              # corrected position (m)
        self.raw_prev: tuple[float, float] | None = None
        self.align_deg = np.zeros(n)
        self.align_m = np.zeros(n)
        self.agree = np.full(n, np.nan)                      # share of seen cells whose snapshot class equals the frame's observation
        self.agree_prior = np.full(n, np.nan)                # share of seen surface cells the map (before this frame) already had right
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

    def _align(self, t: float, pose: tuple, obs: np.ndarray):
        """v26.2.10 (``poseAlign``): confront the pose with the map. Candidates = heading offsets +-``alignDeg`` (``alignStepDeg`` steps), then
        shifts forward / sideways +-``alignShiftM`` (``alignShiftStepM`` steps) of the pose; score = the share of the frame's seen surface
        cells (a subsample, up to ``maxRangeM``) whose stored surface class, where the map has one (>= ``alignMinVotes``), equals the observed
        one. The best candidate is taken only when it beats the unshifted pose by ``alignMinGain`` with at least ``alignMinCells`` cells
        compared (and not by comparing fewer than 90 % of the unshifted pose's cells); the correction accumulates (``align_th``, ``pos_c``), by at
        most ``alignMoveDeg`` (default ``alignStepDeg``) and ``alignShiftStepM`` per frame.
        Returns (pose, the unshifted pose's score or nan)."""
        ob, cfg = self.observer, self.cfg
        stride = max(1, int(cfg.get("alignStride", 3)))
        sub = np.zeros_like(ob.seen)
        sub[::stride, ::stride] = True
        m = sub & ob.seen & (self.kind[obs] == KIND_SURFACE) & (obs != UNKNOWN) & (ob.fwd <= ob.max_range)
        n_all = int(np.count_nonzero(m))
        if n_all == 0:
            return pose, float("nan")
        fwd, right, want = ob.fwd[m], ob.right[m], obs[m]
        min_votes = float(cfg.get("alignMinVotes", 1.0))
        min_cells = float(cfg.get("alignMinCells", 500)) / (stride * stride)

        def score(p):
            cls = self.fusion.surface_at(p, fwd, right, t, min_votes)
            has = cls != UNKNOWN
            n = int(np.count_nonzero(has))
            return (float(np.count_nonzero(cls[has] == want[has])) / n if n else 0.0), n

        base, n0 = score(pose)
        if n0 < min_cells:
            return pose, float("nan")
        if not self.align_on:
            return pose, base
        x, y, th = pose
        best, best_p, best_n = base, pose, n0

        def consider(p):
            nonlocal best, best_p, best_n
            sc, n = score(p)
            if n >= 0.9 * n0 and (sc > best + 1e-9):
                best, best_p, best_n = sc, p, n

        deg, step = float(cfg.get("alignDeg", 2.0)), float(cfg.get("alignStepDeg", 0.5))
        for d in np.arange(-deg, deg + 1e-9, step):
            if abs(d) > 1e-9:
                consider((x, y, th + float(d)))
        sh, sstep = float(cfg.get("alignShiftM", 0.3)), float(cfg.get("alignShiftStepM", 0.1))
        bx, by, bth = best_p
        s_, c_ = math.sin(math.radians(bth)), math.cos(math.radians(bth))
        for kind_, (ux, uy) in (("fwd", (s_, c_)), ("right", (c_, -s_))):
            cx, cy, cth = best_p
            for d in np.arange(-sh, sh + 1e-9, sstep):
                if abs(d) > 1e-9:
                    consider((cx + float(d) * ux, cy + float(d) * uy, cth))
        # a proposal per frame (0 when it does not beat the unshifted pose by ``alignMinGain``); the correction applied is the MEDIAN of the last
        # ``alignWindow`` proposals, at most one step per frame: noise changes sign from frame to frame, a drifting heading does not
        good = best - base >= float(cfg.get("alignMinGain", 0.03))
        dth_p = best_p[2] - th if good else 0.0
        sx, sy = (best_p[0] - x, best_p[1] - y) if good else (0.0, 0.0)
        s_h, c_h = math.sin(math.radians(th)), math.cos(math.radians(th))
        pf, pr = sx * s_h + sy * c_h, sx * c_h - sy * s_h                    # the shift in the user's frame (forward, right)
        self.props.append((dth_p, pf, pr))
        del self.props[:-max(1, int(cfg.get("alignWindow", 6)))]
        med = np.median(np.array(self.props), axis=0)
        move = float(cfg.get("alignMoveDeg", step))
        dth = float(np.clip(med[0], -move, move))
        df, dr_ = (float(np.clip(med[1], -sstep, sstep)), float(np.clip(med[2], -sstep, sstep)))
        if dth == 0.0 and df == 0.0 and dr_ == 0.0:
            return pose, base
        self.props = [(a - dth, b - df, c - dr_) for a, b, c in self.props]    # what is applied is no longer to be proposed
        p2 = (x + df * s_h + dr_ * c_h, y + df * c_h - dr_ * s_h, th + dth)
        self.align_th += dth
        self.pos_c = [p2[0], p2[1]]
        return p2, base

    def step(self, i: int, frame: dict | None = None, dmap=None, layers: bool = False):
        """Frame i: pose + observation + fusion + snapshot. Returns (obs, snapshot classes, conf, ms).
        ``frame`` = {"horizon", "scale", "depthScale", "ego"} (default: the stored one of ``frames``); ``dmap`` the depth map of
        the frame (default: the nearest one of the run's depth). ``layers``: also keep the separate surface / object layers in
        ``self.last_layers`` (surface, object), for the Lab's cell readout; the collision pass does not need them."""
        t0 = time.perf_counter()
        frame = self.resolve_frame(frame if frame is not None else self.frames[i])
        dmap = dmap if dmap is not None else self.depth_map(i)
        t = float(self.times[i])
        raw = self.pose_tracker.advance(t, frame["ego"])
        if self.raw_prev is None:
            self.pos_c = [raw[0], raw[1]]
        else:                     # the dead-reckoned step, turned by the heading correction found so far
            ddx, ddy = raw[0] - self.raw_prev[0], raw[1] - self.raw_prev[1]
            a = math.radians(self.align_th)
            self.pos_c[0] += ddx * math.cos(a) + ddy * math.sin(a)
            self.pos_c[1] += -ddx * math.sin(a) + ddy * math.cos(a)
        self.raw_prev = (raw[0], raw[1])
        pose = (self.pos_c[0], self.pos_c[1], raw[2] + self.align_th)
        obs, w = self.observer.observe(np.asarray(self.grids[i]), frame, dmap)
        pose, prior = self._align(t, pose, obs)
        self.pose[i] = pose
        self.last_pose = pose
        self.align_deg[i] = self.align_th
        self.align_m[i] = math.hypot(self.pos_c[0] - raw[0], self.pos_c[1] - raw[1])
        self.agree_prior[i] = prior
        self.fusion.update(t, pose, obs, w, self.observer)
        if layers:
            classes, conf, surf, objs = self.fusion.snapshot(t, pose, self.observer, True)
            self.last_layers = (surf, objs)
        else:
            classes, conf = self.fusion.snapshot(t, pose, self.observer)
        seen = self.observer.seen
        if seen.any():
            self.agree[i] = float((classes[seen] == obs[seen]).mean())
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
            "ms": ms, "alignDeg": wm.align_deg, "alignM": wm.align_m, "agree": wm.agree, "agreePrior": wm.agree_prior}
