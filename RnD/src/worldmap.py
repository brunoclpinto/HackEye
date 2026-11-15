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
from engine.worldmap.fusion import Fusion  # noqa: F401
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
