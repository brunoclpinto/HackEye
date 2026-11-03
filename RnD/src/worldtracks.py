"""World tracks (v26.2.9, shadow mode): every item of the collision pass tracked in the world with position, velocity and uncertainty.

Nothing computed here feeds a decision of ``collision.run_collision``; it only adds ``worldTracks`` to each hazards frame.

State per track: ``[x, y, vx, vy]`` in the ``_WorldMemory`` frame (x east, y north, m, m/s), a 4 x 4 covariance, a constant-velocity Kalman
filter (white acceleration noise: small for static-like items, large for movers). The measurement is the item's reported (forward, right)
position located with the current dead-reckoned pose; its covariance is built in range / bearing and rotated to the world.
A track without a measurement stays predicted: ``out-of-view`` (outside the field of view, nearer than the bottom image row, behind
the user, or hidden by a building on the map) for ``coastMaxS``, ``missing`` (expected in view, not detected) for ``missDropFrames`` frames.
"""
from __future__ import annotations

import math

import numpy as np

DEFAULTS = {
    "enabled": True,
    "accelStaticMps2": 0.05, "accelMoverMps2": 1.5,
    "rangeSigmaFrac": 0.12, "bearingSigmaDeg": 1.0, "rangeSigmaMinM": 0.1, "nonDepthRangeFactor": 2.0,
    "initSpeedSigmaStaticMps": 0.3, "initSpeedSigmaMoverMps": 2.0,
    "gateChi2": 9.21,
    "fovMarginDeg": 3.0, "coastMaxS": 4.0, "missDropFrames": 3, "maxSigmaM": 3.0, "behindDropM": 2.0, "maxRangeM": 30.0,
    "horizonS": 8.0, "itemRadiusM": 0.3, "maxTracksOut": 40,
    "skipClasses": ["building", "structure bridge", "structure tunnel", "bridge", "tunnel"],
}


def settings(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update(cfg or {})
    return out


class _WT:
    __slots__ = ("id", "cls", "family", "group", "static", "x", "P", "t", "t0", "last_seen", "tid", "images", "state", "miss", "seen_now", "innov")

    def __init__(self, wid, m, x, P, t):
        self.id, self.x, self.P, self.t, self.t0, self.last_seen = wid, x, P, t, t, t
        self.cls, self.family, self.group, self.static = m["cls"], m["family"], m["group"], m["static"]
        self.tid, self.images, self.state, self.miss, self.seen_now, self.innov = m["tid"], [m["tid"]], "seen", 0, True, None


def _rot(theta_deg: float) -> np.ndarray:
    """(fwd, right) -> (dx, dy)."""
    th = math.radians(theta_deg)
    s, c = math.sin(th), math.cos(th)
    return np.array([[s, c], [c, -s]])


def _eig_radius(P: np.ndarray) -> float:
    a, b, d = P[0, 0], P[0, 1], P[1, 1]
    return math.sqrt(max(0.5 * (a + d) + math.sqrt(max(0.25 * (a - d) ** 2 + b * b, 0.0)), 0.0))


def _interval(lo_a: float, hi_a: float, p: float, v: float, lo: float, hi: float) -> tuple[float, float] | None:
    """The t in [lo_a, hi_a] where lo <= p + v t <= hi, or None."""
    if abs(v) < 1e-9:
        return (lo_a, hi_a) if lo <= p <= hi else None
    t1, t2 = (lo - p) / v, (hi - p) / v
    a, b = max(lo_a, min(t1, t2)), min(hi_a, max(t1, t2))
    return (a, b) if a <= b else None


class WorldTracks:
    def __init__(self, cfg: dict | None, lane_half_m: float, hfov_deg: float):
        self.cfg = settings(cfg)
        self.on = bool(self.cfg["enabled"])
        self.half = float(lane_half_m) + float(self.cfg["itemRadiusM"])
        self.hfov = float(hfov_deg)
        self.skip = frozenset(self.cfg["skipClasses"])
        self.tracks: dict[int, _WT] = {}          # world id number -> track
        self.link: dict[int, int] = {}            # image track id -> world id number
        self.next = 1
        self.prev_pose: tuple[float, float, float] | None = None
        self.prev_t: float | None = None
        self.ego_speed = 0.0
        self.ms: list[float] = []

    # ------------------------------------------------------------------ helpers
    def _R(self, fwd: float, right: float, depth: bool, M: np.ndarray) -> np.ndarray:
        c = self.cfg
        r = max(math.hypot(fwd, right), 1e-3)
        sr = max(c["rangeSigmaFrac"] * r * (1.0 if depth else c["nonDepthRangeFactor"]), c["rangeSigmaMinM"])
        st = r * math.radians(c["bearingSigmaDeg"])
        u = np.array([fwd, right]) / r
        w = np.array([-u[1], u[0]])
        E = sr * sr * np.outer(u, u) + st * st * np.outer(w, w)
        return M @ E @ M.T

    def _predict(self, tr: _WT, t: float) -> None:
        dt = t - tr.t
        if dt <= 0:
            return
        q = (self.cfg["accelStaticMps2"] if tr.static else self.cfg["accelMoverMps2"]) ** 2
        F = np.eye(4)
        F[0, 2] = F[1, 3] = dt
        Q = np.zeros((4, 4))
        a, b, d = dt ** 3 / 3.0, dt * dt / 2.0, dt
        for k in (0, 1):
            Q[k, k], Q[k, k + 2], Q[k + 2, k], Q[k + 2, k + 2] = a, b, b, d
        tr.x = F @ tr.x
        tr.P = F @ tr.P @ F.T + q * Q
        tr.t = t

    @staticmethod
    def _maha(tr: _WT, z: np.ndarray, R: np.ndarray) -> float:
        S = tr.P[:2, :2] + R
        r = z - tr.x[:2]
        try:
            return float(r @ np.linalg.solve(S, r))
        except np.linalg.LinAlgError:
            return math.inf

    @staticmethod
    def _update(tr: _WT, z: np.ndarray, R: np.ndarray) -> None:
        S = tr.P[:2, :2] + R
        K = tr.P[:, :2] @ np.linalg.inv(S)
        tr.x = tr.x + K @ (z - tr.x[:2])
        I_KH = np.eye(4)
        I_KH[:, :2] -= K
        tr.P = I_KH @ tr.P @ I_KH.T + K @ R @ K.T

    def _new(self, m: dict, z: np.ndarray, R: np.ndarray, t: float) -> _WT:
        c = self.cfg
        sv = c["initSpeedSigmaStaticMps"] if m["static"] else c["initSpeedSigmaMoverMps"]
        P = np.zeros((4, 4))
        P[:2, :2] = R
        P[2, 2] = P[3, 3] = sv * sv
        tr = _WT(self.next, m, np.array([z[0], z[1], 0.0, 0.0]), P, t)
        self.tracks[self.next] = tr
        self.link[m["tid"]] = self.next
        self.next += 1
        return tr

    # ------------------------------------------------------------------ one analysed frame
    def step(self, t: float, pose: tuple[float, float, float] | None, measurements: list[dict], d_bottom: float = 0.0,
             hidden=None) -> list[dict]:
        """``measurements``: dicts {tid, cls, family, group, static, fwd, right, depth}. ``hidden(fwd, right)`` -> bool (the map's hidden cells).
        Returns this frame's ``worldTracks`` list."""
        if not self.on or pose is None:
            return []
        c = self.cfg
        x0, y0, th = pose
        if self.prev_pose is not None and self.prev_t is not None and t - self.prev_t > 1e-9:
            self.ego_speed = math.hypot(x0 - self.prev_pose[0], y0 - self.prev_pose[1]) / (t - self.prev_t)
        self.prev_pose, self.prev_t = pose, t
        M = _rot(th)
        origin = np.array([x0, y0])
        for tr in self.tracks.values():
            self._predict(tr, t)
            tr.seen_now = False
            tr.innov = None
        zs = []
        for m in measurements:
            if m["cls"] in self.skip:
                continue
            z = origin + M @ np.array([m["fwd"], m["right"]])
            zs.append((m, z, self._R(m["fwd"], m["right"], m["depth"], M)))
        claimed: set[int] = set()
        pending = []
        for m, z, R in zs:                                        # already linked image tracks first
            wn = self.link.get(m["tid"])
            tr = self.tracks.get(wn) if wn is not None else None
            if tr is None:
                self.link.pop(m["tid"], None)
                pending.append((m, z, R))
            elif self._maha(tr, z, R) <= c["gateChi2"]:
                self._take(tr, m, z, R, t)
                claimed.add(tr.id)
            else:                                                 # a jump: a new world track, the old link ends
                self.link.pop(m["tid"], None)
                pending.append((m, z, R))
        for m, z, R in pending:
            best, bd = None, c["gateChi2"]
            for tr in self.tracks.values():                       # re-identification through a gap
                if tr.id in claimed or tr.seen_now or tr.state == "dropped" or tr.family != m["family"]:
                    continue
                d = self._maha(tr, z, R)
                if d <= bd:
                    best, bd = tr, d
            if best is not None:
                if best.tid is not None and self.link.get(best.tid) == best.id:
                    del self.link[best.tid]
                self.link[m["tid"]] = best.id
                best.tid = m["tid"]
                best.images.append(m["tid"])
                self._take(best, m, z, R, t)
                claimed.add(best.id)
            else:
                tr = self._new(m, z, R, t)
                tr.seen_now = True
                claimed.add(tr.id)
        # unseen tracks
        out: list[dict] = []
        half_fov = self.hfov / 2.0 - c["fovMarginDeg"]
        for tr in list(self.tracks.values()):
            dx, dy = tr.x[0] - x0, tr.x[1] - y0
            fwd, right = M.T @ np.array([dx, dy])
            fwd, right = float(fwd), float(right)
            rng = math.hypot(fwd, right)
            drop = rng > c["maxRangeM"] or fwd < -c["behindDropM"] or _eig_radius(tr.P[:2, :2]) > c["maxSigmaM"]
            if not tr.seen_now:
                bearing = math.degrees(math.atan2(right, fwd)) if rng > 1e-6 else 0.0
                oov = fwd < 0 or abs(bearing) > half_fov or fwd < d_bottom or (hidden is not None and bool(hidden(fwd, right)))
                if oov:
                    tr.state, tr.miss = "out-of-view", 0
                    drop = drop or t - tr.last_seen > c["coastMaxS"]
                else:
                    tr.state = "missing"
                    tr.miss += 1
                    drop = drop or tr.miss >= c["missDropFrames"]
            else:
                tr.state, tr.miss = "seen", 0
            if drop:
                tr.state = "dropped"
            out.append(self._json(tr, t, fwd, right, M))
            if drop:
                del self.tracks[tr.id]
                if tr.tid is not None and self.link.get(tr.tid) == tr.id:
                    del self.link[tr.tid]
        out.sort(key=lambda d: (d["fwd"] ** 2 + d["right"] ** 2))
        return out[: int(c["maxTracksOut"])]

    def _take(self, tr: _WT, m: dict, z: np.ndarray, R: np.ndarray, t: float) -> None:
        tr.innov = float(np.hypot(*(z - tr.x[:2])))          # predicted vs measured position (the re-acquisition error after a gap)
        self._update(tr, z, R)
        tr.seen_now, tr.last_seen, tr.miss, tr.state = True, t, 0, "seen"
        tr.cls, tr.group, tr.static = m["cls"], m["group"], m["static"]
        tr.tid = m["tid"]
        if m["tid"] not in tr.images:
            tr.images.append(m["tid"])

    # ------------------------------------------------------------------ path test and output
    def _json(self, tr: _WT, t: float, fwd: float, right: float, M: np.ndarray) -> dict:
        c = self.cfg
        v_ego = M.T @ tr.x[2:4]                                   # world velocity in the ego frame (fwd, right)
        vf, vr = float(v_ego[0]) - self.ego_speed, float(v_ego[1])
        speed = math.hypot(tr.x[2], tr.x[3])
        vv = vf * vf + vr * vr
        ts = 0.0 if vv < 1e-9 else min(max(-(fwd * vf + right * vr) / vv, 0.0), c["horizonS"])
        cpa = math.hypot(fwd + vf * ts, right + vr * ts)
        on = cpa <= self.half and ts > 0
        ttc = None
        if on:
            ri = c["itemRadiusM"]
            a = _interval(0.0, c["horizonS"], fwd, vf, -ri, ri)
            if a is not None:
                b = _interval(a[0], a[1], right, vr, -self.half, self.half)
                if b is not None:
                    ttc = b[0]
        rel_h = None if math.sqrt(vv) < 0.05 else math.degrees(math.atan2(vr, vf))
        head = None if speed < 0.05 else math.degrees(math.atan2(tr.x[2], tr.x[3]))
        r2 = lambda v: None if v is None else round(float(v), 2)
        return {"id": f"W{tr.id}", "class": tr.cls, "family": tr.family, "group": tr.group, "staticLike": bool(tr.static), "state": tr.state,
                "imageTracks": list(tr.images), "trackId": tr.tid if tr.seen_now else None,
                "x": r2(tr.x[0]), "y": r2(tr.x[1]), "vx": r2(tr.x[2]), "vy": r2(tr.x[3]), "fwd": r2(fwd), "right": r2(right),
                "speedMps": r2(speed), "headingDeg": None if head is None else round(head, 1),
                "relHeadingDeg": None if rel_h is None else round(rel_h, 1), "sigmaM": r2(_eig_radius(tr.P[:2, :2])),
                "cpaM": r2(cpa), "cpaS": r2(ts), "onCourse": bool(on), "ttcS": r2(ttc),
                "innovM": r2(tr.innov), "age": r2(t - tr.t0), "unseenS": r2(0.0 if tr.seen_now else t - tr.last_seen)}
