"""Worldmap driver: ``WorldMap`` runs the passes frame by frame; ``build`` runs it over a whole run."""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from engine.core import distfuse
from engine.worldmap import config
from engine.worldmap.config import KIND_SURFACE, UNKNOWN, class_kinds
from engine.worldmap.fusion import Fusion
from engine.worldmap.helpers import first_depth_scale, frames_from_hazards, settings_from_hazards
from engine.worldmap.observer import Observer
from engine.worldmap.pose import PoseTracker

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["WorldMap", "build"]


class WorldMap:
    """Drives the passes frame by frame (``step``); ``build`` runs it over a whole run, and the collision pass (v26.2.1)
    runs it online (``frames=None``: each ``step`` gets the frame's horizon / scales / ego block)."""

    def __init__(
        self,
        grids: npt.NDArray[Any],
        times: Any,
        class_names: Any,
        frames: Any,
        settings: dict[str, Any],
        coll_cfg: dict[str, Any],
        cfg: dict[str, Any] | None = None,
        depth: dict[str, Any] | None = None,
    ):
        self.cfg = cfg or config.default_config_loader()
        self.grids = grids
        self.times = np.asarray(times, dtype=float)
        self.frames = frames
        self.kind = class_kinds(self.cfg, list(class_names))
        n, gh, gw = grids.shape
        self.n, self.gh, self.gw = n, gh, gw
        self.observer = Observer(
            self.cfg,
            settings,
            self.kind,
            gh,
            gw,
            distfuse.settings((coll_cfg or {}).get("distance", {})),
            list(class_names),
        )
        self.pose_tracker = PoseTracker(coll_cfg)
        self.pose = np.zeros((n, 3))
        # v26.2.10: the map's own pose = the dead-reckoned one + a correction that the map itself finds (poseAlign)
        self.align_on = bool(self.cfg.get("poseAlign", False))
        self.props: list[
            tuple[float, float, float]
        ] = []  # the last proposals of the alignment search (dth, dfwd, dright)
        self.align_th = 0.0  # accumulated heading correction (deg)
        self.pos_c = [0.0, 0.0]  # corrected position (m)
        self.raw_prev: tuple[float, float] | None = None
        self.align_deg = np.zeros(n)
        self.align_m = np.zeros(n)
        self.agree = np.full(n, np.nan)  # share of seen cells whose snapshot class equals the frame's observation
        self.agree_prior = np.full(
            n, np.nan
        )  # share of seen surface cells the map (before this frame) already had right
        present = np.flatnonzero(np.bincount(np.asarray(grids).ravel(), minlength=256))
        self.fusion = Fusion(self.cfg, self.kind, present, (0.0, 0.0))
        self.last_ds: float | None = None
        self.first_ds = first_depth_scale(frames)
        self.depth_t: npt.NDArray[Any] | None = None
        self.depth: Any = None
        if depth is not None:
            self.depth_t, self.depth = np.asarray(depth["t"], dtype=float), depth["depth"]

    def depth_map(self, i: int) -> npt.NDArray[Any] | None:
        if self.depth is None or self.depth_t is None:
            return None
        t = self.times[i]
        j = int(np.clip(np.searchsorted(self.depth_t, t), 0, len(self.depth_t) - 1))
        if j > 0 and abs(self.depth_t[j - 1] - t) < abs(self.depth_t[j] - t):
            j -= 1
        return np.asarray(self.depth[j])

    def resolve_frame(self, frame: dict[str, Any]) -> dict[str, Any]:
        """v26.2.5: a frame without a depth scale (the plane anchor needs a few frames) uses the nearest known scale
        of the run: the last known one, or, before any (offline, the whole run is known), the first known one of the
        run."""
        ds = frame.get("depthScale")
        if ds:
            self.last_ds = float(ds)
            return frame
        ds = self.last_ds if self.last_ds is not None else self.first_ds
        return frame if not ds else {**frame, "depthScale": ds}

    def _align(
        self, t: float, pose: tuple[float, float, float], obs: npt.NDArray[Any]
    ) -> tuple[tuple[float, float, float], float]:
        """v26.2.10 (``poseAlign``): confront the pose with the map. Candidates = heading offsets +-``alignDeg``
        (``alignStepDeg`` steps), then shifts forward / sideways +-``alignShiftM`` (``alignShiftStepM`` steps) of the
        pose; score = the share of the frame's seen surface cells (a subsample, up to ``maxRangeM``) whose stored
        surface class, where the map has one (>= ``alignMinVotes``), equals the observed one. The best candidate is
        taken only when it beats the unshifted pose by ``alignMinGain`` with at least ``alignMinCells`` cells compared
        (and not by comparing fewer than 90 % of the unshifted pose's cells); the correction accumulates
        (``align_th``, ``pos_c``), by at most ``alignMoveDeg`` (default ``alignStepDeg``) and ``alignShiftStepM`` per
        frame.
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

        def score(p: tuple[float, float, float]) -> tuple[float, int]:
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

        def consider(p: tuple[float, float, float]) -> None:
            nonlocal best, best_p, best_n
            sc, n = score(p)
            if n >= 0.9 * n0 and (sc > best + 1e-9):
                best, best_p, best_n = sc, p, n

        deg, step = float(cfg.get("alignDeg", 2.0)), float(cfg.get("alignStepDeg", 0.5))
        for d in np.arange(-deg, deg + 1e-9, step):
            if abs(d) > 1e-9:
                consider((x, y, th + float(d)))
        sh, sstep = float(cfg.get("alignShiftM", 0.3)), float(cfg.get("alignShiftStepM", 0.1))
        _bx, _by, bth = best_p
        s_, c_ = math.sin(math.radians(bth)), math.cos(math.radians(bth))
        for _kind, (ux, uy) in (("fwd", (s_, c_)), ("right", (c_, -s_))):
            cx, cy, cth = best_p
            for d in np.arange(-sh, sh + 1e-9, sstep):
                if abs(d) > 1e-9:
                    consider((cx + float(d) * ux, cy + float(d) * uy, cth))
        # a proposal per frame (0 when it does not beat the unshifted pose by ``alignMinGain``); the correction applied
        # is the MEDIAN of the last ``alignWindow`` proposals, at most one step per frame: noise changes sign from
        # frame to frame, a drifting heading does not
        good = best - base >= float(cfg.get("alignMinGain", 0.03))
        dth_p = best_p[2] - th if good else 0.0
        sx, sy = (best_p[0] - x, best_p[1] - y) if good else (0.0, 0.0)
        s_h, c_h = math.sin(math.radians(th)), math.cos(math.radians(th))
        pf, pr = sx * s_h + sy * c_h, sx * c_h - sy * s_h  # the shift in the user's frame (forward, right)
        self.props.append((dth_p, pf, pr))
        del self.props[: -max(1, int(cfg.get("alignWindow", 6)))]
        med = np.median(np.array(self.props), axis=0)
        move = float(cfg.get("alignMoveDeg", step))
        dth = float(np.clip(med[0], -move, move))
        df, dr_ = (float(np.clip(med[1], -sstep, sstep)), float(np.clip(med[2], -sstep, sstep)))
        if dth == 0.0 and df == 0.0 and dr_ == 0.0:
            return pose, base
        self.props = [
            (a - dth, b - df, c - dr_) for a, b, c in self.props
        ]  # what is applied is no longer to be proposed
        p2 = (x + df * s_h + dr_ * c_h, y + df * c_h - dr_ * s_h, th + dth)
        self.align_th += dth
        self.pos_c = [p2[0], p2[1]]
        return p2, base

    def step(
        self, i: int, frame: dict[str, Any] | None = None, dmap: Any = None, layers: bool = False
    ) -> tuple[npt.NDArray[Any], npt.NDArray[Any], npt.NDArray[Any], float]:
        """Frame i: pose + observation + fusion + snapshot. Returns (obs, snapshot classes, conf, ms).
        ``frame`` = {"horizon", "scale", "depthScale", "ego"} (default: the stored one of ``frames``); ``dmap`` the
        depth map of the frame (default: the nearest one of the run's depth). ``layers``: also keep the separate
        surface / object layers in ``self.last_layers`` (surface, object), for the Lab's cell readout; the collision
        pass does not need them."""
        t0 = time.perf_counter()
        frame = self.resolve_frame(frame if frame is not None else self.frames[i])
        dmap = dmap if dmap is not None else self.depth_map(i)
        t = float(self.times[i])
        raw = self.pose_tracker.advance(t, frame["ego"])
        if self.raw_prev is None:
            self.pos_c = [raw[0], raw[1]]
        else:  # the dead-reckoned step, turned by the heading correction found so far
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


def build(
    grids: npt.NDArray[Any],
    times: Any,
    class_names: Any,
    hazards: dict[str, Any],
    coll_cfg: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    depth: dict[str, Any] | None = None,
    hook: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """The whole run -> the arrays of worldmap.npz. ``hook(i, wm, obs, classes[i])`` is called after each frame
    (metrics)."""
    frames = frames_from_hazards(hazards)
    if len(frames) != len(grids):
        raise ValueError(f"hazards.json has {len(frames)} frames, grids.npz {len(grids)}")
    wm = WorldMap(grids, times, class_names, frames, settings_from_hazards(hazards), coll_cfg, cfg, depth)
    size = wm.observer.size
    classes = np.full((len(grids), size, size), UNKNOWN, dtype=np.uint8)
    conf = np.zeros((len(grids), size, size), dtype=np.uint8)
    surface = np.full(
        (len(grids), size, size), UNKNOWN, dtype=np.uint8
    )  # v26.2.4: the surface and the object layer on their own
    objects = np.full((len(grids), size, size), UNKNOWN, dtype=np.uint8)
    ms = np.zeros(len(grids))
    for i in range(len(grids)):
        obs, classes[i], conf[i], ms[i] = wm.step(i, layers=True)
        surface[i], objects[i] = wm.last_layers
        if hook is not None:
            hook(i, wm, obs, classes[i])
    return {
        "classes": classes,
        "conf": conf,
        "surface": surface,
        "object": objects,
        "t": wm.times,
        "pose": wm.pose,
        "cellM": np.float32(wm.cfg["cellM"]),
        "origin": np.array([wm.observer.oc, wm.observer.orow], dtype=np.int32),
        "ms": ms,
        "alignDeg": wm.align_deg,
        "alignM": wm.align_m,
        "agree": wm.agree,
        "agreePrior": wm.agree_prior,
    }
