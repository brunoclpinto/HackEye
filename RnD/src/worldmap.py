"""World map spike (v26.2 step 1): a fused, ego-centric bird's-eye map built only from what a Lab run stores.

Inputs per frame: the class grid, the depth map (when the run has one), the frame's horizon and ego block from
hazards.json. Nothing is inferred again. Per frame:

1. Ego observation (``Observer``): a 200 x 200 heading-up grid of 0.10 m cells (user at col 100 / row 180).
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
4. Snapshot: the fused map resampled into the ego frame.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

import collision
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

    def __init__(self, cfg: dict, settings: dict, kind: np.ndarray, gh: int, gw: int):
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
        self.f_px = focal_px(gw, self.hfov)
        self.lens = cfg.get("lateralModel", "collision") == "lens"
        self.range_w = float(cfg["rangeWeightM"])
        self.max_range = float(cfg["maxRangeM"])
        self.min_fwd = float(cfg["minForwardM"])
        rows, cols = np.mgrid[0:self.size, 0:self.size]
        self.fwd = ((self.orow - rows) * self.cell).astype(np.float64)       # metres ahead of the user
        self.right = ((cols - self.oc) * self.cell).astype(np.float64)       # metres to the right (body centre line)
        self.weight = (1.0 / (1.0 + (np.maximum(self.fwd, 0.0) / self.range_w) ** 2)).astype(np.float32)

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

    def object_bases(self, grid: np.ndarray, frame: dict, dmap: np.ndarray | None, kgrid: np.ndarray | None = None):
        """The ground base of every vertical run of an object class: (rows, cols, forward distance m, lateral m in body
        coordinates) of the image pixels that are projected into the map. The collision rules (v26.2.1) read the same points to
        place an item's footprint on the map."""
        gh, gw = self.gh, self.gw
        cam_h = self.cam_h * self.ground_scale(frame)
        kgrid = self.kind[grid] if kgrid is None else kgrid
        cls = grid
        is_obj = kgrid == KIND_OBJECT
        below_same = np.zeros_like(is_obj)
        below_same[:-1] = cls[1:] == cls[:-1]
        base = is_obj & ~below_same
        below_surface = np.zeros_like(is_obj)
        below_surface[:-1] = kgrid[1:] == KIND_SURFACE
        rr, cc = np.nonzero(base)
        empty = (rr[:0], cc[:0], np.zeros(0), np.zeros(0))
        if not rr.size:
            return empty
        horizon = float(frame["horizon"])
        y_b = (rr + 1.0) / gh
        contact = below_surface[rr, cc] & (y_b > horizon + 1e-6) & (rr < gh - 1)          # stands on the ground
        ground = cam_h * self.f_px / (np.maximum(y_b - horizon, 1e-6) * gh)
        if dmap is not None and frame.get("depthScale"):
            dh, dw = dmap.shape
            up = int(self.cfg.get("objectDepthRowsAbove", 0))                 # read the depth inside the object, not at its edge
            r_d = np.maximum(rr - up, 0)
            r_d = np.where(grid[r_d, cc] == grid[rr, cc], r_d, rr)
            v = dmap[np.minimum(dh - 1, ((r_d + 0.5) / gh * dh).astype(int)),
                     np.minimum(dw - 1, ((cc + 0.5) / gw * dw).astype(int))].astype(np.float64)
            dist = float(frame["depthScale"]) * v
            good = np.isfinite(dist) & (dist > 0)
            if self.cfg.get("objectDistance", "depth") == "ground-contact":    # a base on the ground: the ground ray beats the depth
                dist = np.where(contact, ground, dist)
        else:                                           # ground distance of the base row; needs the ground below it
            good = contact
            dist = np.where(good, ground, 0.0)
        good &= (dist >= self.min_fwd) & (dist <= self.max_range)
        rr, cc, dist = rr[good], cc[good], dist[good]
        if not rr.size:
            return empty
        lat_b = self._lateral((cc + 0.5) / gw, dist) + self.lat_off
        return rr, cc, dist, lat_b

    def observe(self, grid: np.ndarray, frame: dict, dmap: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
        gh, gw, size = self.gh, self.gw, self.size
        obs = np.full((size, size), UNKNOWN, dtype=np.uint8)
        horizon = float(frame["horizon"])
        cam_h = self.cam_h * self.ground_scale(frame)
        kgrid = self.kind[grid]
        # --- surfaces: inverse ground-plane sampling -------------------------------------------------------
        fwd = self.fwd
        ok = (fwd >= self.min_fwd) & (fwd <= self.max_range)
        d = np.where(ok, fwd, 1.0)
        y = horizon + cam_h * self.f_px / (d * gh)
        lat = self.right - self.lat_off
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
        # --- object bases ----------------------------------------------------------------------------------
        rr, cc, dist, lat_b = self.object_bases(grid, frame, dmap, kgrid)
        if rr.size:
            col = self.oc + np.rint(lat_b / self.cell).astype(np.int64)
            row = self.orow - np.rint(dist / self.cell).astype(np.int64)
            half = np.minimum(4, np.rint(dist / self.f_px / 2.0 / self.cell).astype(np.int64))   # one image column's width
            order = np.argsort(-dist)                  # nearer points are written last and win
            rr, cc, col, row, half = rr[order], cc[order], col[order], row[order], half[order]
            vals = grid[rr, cc]
            for off in range(-4, 5):
                m = half >= abs(off)
                cx = col[m] + off
                ry = row[m]
                inside = (cx >= 0) & (cx < size) & (ry >= 0) & (ry < size)
                obs[ry[inside], cx[inside]] = vals[m][inside]
        w = np.where(obs != UNKNOWN, self.weight, 0.0).astype(np.float32)
        gain = float(self.cfg.get("objectVoteGain", 1.0))        # an object base is one thin line among many surface cells
        if gain != 1.0:
            w[self.kind[obs] == KIND_OBJECT] *= np.float32(gain)
        return obs, w


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
        ok &= cls != UNKNOWN
        k = self.lut[cls]
        ok &= k >= 0
        if not ok.any():
            return
        amp = w[row, col] * np.float32(math.exp(self.lam * (t - self.t_base)))
        self.votes[k[ok], ii[ok], jj[ok]] += amp[ok]
        self.count[ii[ok], jj[ok]] += 1

    def _decay(self, t: float) -> float:
        return math.exp(-self.lam * (t - self.t_base))

    def snapshot(self, t: float, pose: tuple[float, float, float], observer: Observer) -> tuple[np.ndarray, np.ndarray]:
        iy, ix = self._ego_to_world_idx(observer.fwd, observer.right, pose)
        inside = (iy >= 0) & (iy < self.n) & (ix >= 0) & (ix < self.n)
        iy, ix = np.clip(iy, 0, self.n - 1), np.clip(ix, 0, self.n - 1)
        v = self.votes[:, iy, ix]                                    # (K, size, size)
        total = v.sum(axis=0) * np.float32(self._decay(t))
        top = v.argmax(axis=0)
        share = np.take_along_axis(v, top[None], 0)[0] / np.maximum(v.sum(axis=0), 1e-12)
        known = inside & (total > self.floor)
        classes = np.where(known, self.classes[top], UNKNOWN).astype(np.uint8)
        conf = np.where(known, 255.0 * np.minimum(1.0, total / self.full) * share, 0.0)
        return classes, conf.astype(np.uint8)

    def world_classes(self, t: float) -> tuple[np.ndarray, np.ndarray]:
        """Whole window: (classes uint8 [255 unknown], decayed total weight); for metrics."""
        total = self.votes.sum(axis=0) * np.float32(self._decay(t))
        cls = np.where(total > self.floor, self.classes[self.votes.argmax(axis=0)], UNKNOWN).astype(np.uint8)
        return cls, total


def frames_from_hazards(hazards: dict) -> list[dict]:
    """The per-frame inputs the observer needs: horizon, scales and the ego block (as stored by the collision pass)."""
    out = []
    for fr in hazards["frames"]:
        e = fr.get("ego") or {}
        out.append({"horizon": fr["horizonY"], "scale": e.get("scale"), "depthScale": e.get("depthScale"), "ego": e})
    return out


def settings_from_hazards(hazards: dict) -> dict:
    s = hazards["settings"]
    return {"hfovDeg": s["hfovDeg"], "cameraHeightM": s["cameraHeightM"], "lateralOffsetM": s.get("lateralOffsetM", 0.0),
            "projection": hazards.get("projection"), "distanceSource": hazards.get("distanceSource", "ground")}


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
        self.observer = Observer(self.cfg, settings, self.kind, gh, gw)
        self.pose_tracker = PoseTracker(coll_cfg)
        self.pose = np.zeros((n, 3))
        present = np.flatnonzero(np.bincount(np.asarray(grids).ravel(), minlength=256))
        self.fusion = Fusion(self.cfg, self.kind, present, (0.0, 0.0))
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

    def step(self, i: int, frame: dict | None = None, dmap=None):
        """Frame i: pose + observation + fusion + snapshot. Returns (obs, snapshot classes, conf, ms).
        ``frame`` = {"horizon", "scale", "depthScale", "ego"} (default: the stored one of ``frames``); ``dmap`` the depth map of
        the frame (default: the nearest one of the run's depth)."""
        t0 = time.perf_counter()
        frame = frame if frame is not None else self.frames[i]
        dmap = dmap if dmap is not None else self.depth_map(i)
        t = float(self.times[i])
        pose = self.pose_tracker.advance(t, frame["ego"])
        self.pose[i] = pose
        self.last_pose = pose
        obs, w = self.observer.observe(np.asarray(self.grids[i]), frame, dmap)
        self.fusion.update(t, pose, obs, w, self.observer)
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
    ms = np.zeros(len(grids))
    for i in range(len(grids)):
        obs, classes[i], conf[i], ms[i] = wm.step(i)
        if hook is not None:
            hook(i, wm, obs, classes[i])
    return {"classes": classes, "conf": conf, "t": wm.times, "pose": wm.pose,
            "cellM": np.float32(wm.cfg["cellM"]), "origin": np.array([wm.observer.oc, wm.observer.orow], dtype=np.int32),
            "ms": ms}
