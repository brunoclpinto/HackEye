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
    # v26.2.11 (each switch off = the v26.2.10 behaviour: [] / 1.0 / 0 / 0 / 0 / false)
    "extendedClasses": ["curb", "crosswalk", "barrier", "barrier fence", "barrier guard-rail", "barrier wall", "divider", "nature vegetation",
                        "vegetation", "terrain", "nature terrain", "fence", "wall", "guard-rail"],
    "headingSigmaDegPerS": 0.5, "poseSigmaMaxS": 4.0,
    "staticVelocityDamping": 0.5, "dampingDirectionalS": 1.0, "dampingDirectionalMinM": 0.15, "dampingDirectionalRatio": 0.6,
    "moverPromoteMps": 0.8, "moverPromoteS": 1.0,
    "missDropS": 1.0, "reviveS": 1.0, "reidOneToOne": True, "classMismatchCost": 2.0,
    "trustMinS": 0.5, "trustMaxSigmaM": 0.5, "trustMaxSpeedSigmaMps": 0.3,
}


def settings(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update(cfg or {})
    return out


class _WT:
    __slots__ = ("id", "cls", "family", "group", "static", "x", "P", "t", "t0", "last_seen", "tid", "images", "state", "miss", "seen_now", "innov", "seen_s", "ivs", "promoted", "prom_t0", "miss_t0", "dead_t")

    def __init__(self, wid, m, x, P, t):
        self.id, self.x, self.P, self.t, self.t0, self.last_seen = wid, x, P, t, t, t
        self.cls, self.family, self.group, self.static = m["cls"], m["family"], m["group"], m["static"]
        self.tid, self.images, self.state, self.miss, self.seen_now, self.innov = m["tid"], [m["tid"]], "seen", 0, True, None
        self.seen_s, self.ivs, self.promoted, self.prom_t0, self.miss_t0, self.dead_t = 0.0, [], False, None, None, None


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
        self.extended = frozenset(self.cfg["extendedClasses"])
        self.dead: dict[int, _WT] = {}            # dropped for being missing, still predicted for ``reviveS`` (re-identification only)
        self._ctx: tuple[np.ndarray, np.ndarray] | None = None
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
        damp = self.cfg["staticVelocityDamping"]
        if damp < 1.0 and tr.static and not tr.promoted and not self._directional(tr, t):
            tr.x[2:4] *= damp ** dt
            tr.P[2:4, :] *= damp ** dt
            tr.P[:, 2:4] *= damp ** dt

    def _directional(self, tr: _WT, t: float) -> bool:
        """The innovations of the last ``dampingDirectionalS`` all point the same way (the item really moves): no damping then."""
        c = self.cfg
        iv = [(ti, v) for ti, v in tr.ivs if t - ti <= c["dampingDirectionalS"] + 1e-9]
        if len(iv) < 3 or iv[-1][0] - iv[0][0] < 0.6 * c["dampingDirectionalS"]:
            return False
        vs = np.array([v for _, v in iv])
        mean_norm = float(np.mean(np.hypot(vs[:, 0], vs[:, 1])))
        net = float(np.hypot(*vs.mean(axis=0)))
        return net >= c["dampingDirectionalMinM"] and net >= c["dampingDirectionalRatio"] * mean_norm

    def _Rx(self, tr: _WT, z: np.ndarray, R: np.ndarray, t: float) -> np.ndarray:
        """R plus the pose uncertainty: the heading may have drifted by ``headingSigmaDegPerS`` x the time since the track was last updated."""
        c = self.cfg
        if c["headingSigmaDegPerS"] <= 0 or self._ctx is None:
            return R
        origin, M = self._ctx
        d = z - origin
        r = math.hypot(d[0], d[1])
        if r < 1e-6:
            return R
        ang = math.radians(c["headingSigmaDegPerS"]) * min(max(t - tr.last_seen, 0.0), c["poseSigmaMaxS"])
        w = np.array([-d[1], d[0]]) / r
        return R + (r * ang) ** 2 * np.outer(w, w)

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
        self._ctx = (origin, M)
        for tr in self.tracks.values():
            self._predict(tr, t)
            tr.seen_now = False
            tr.innov = None
        expired = []
        for tr in list(self.dead.values()):
            if t - tr.dead_t > c["reviveS"]:
                del self.dead[tr.id]
                expired.append(tr)
            else:
                self._predict(tr, t)
        zs = []
        for m in measurements:
            if m["cls"] in self.skip or m["cls"] in self.extended:
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
            elif self._maha(tr, z, self._Rx(tr, z, R, t)) <= c["gateChi2"]:
                self._take(tr, m, z, self._Rx(tr, z, R, t), t)
                claimed.add(tr.id)
            else:                                                 # a jump: a new world track, the old link ends
                self.link.pop(m["tid"], None)
                pending.append((m, z, R))
        cands = [tr for tr in list(self.tracks.values()) + list(self.dead.values()) if tr.id not in claimed and not tr.seen_now and tr.state != "dropped"]
        if c["reidOneToOne"]:
            pairs = []
            for i, (m, z, R) in enumerate(pending):
                for tr in cands:
                    if tr.family != m["family"]:
                        continue
                    d = self._maha(tr, z, self._Rx(tr, z, R, t))
                    if d <= c["gateChi2"]:
                        pairs.append((d + (0.0 if tr.cls == m["cls"] else c["classMismatchCost"]), i, tr.id))
            pairs.sort(key=lambda p: p[0])
            used_m: set[int] = set()
            used_t: set[int] = set()
            assign: dict[int, _WT] = {}
            by_id = {tr.id: tr for tr in cands}
            for _, i, wid in pairs:
                if i in used_m or wid in used_t:
                    continue
                used_m.add(i)
                used_t.add(wid)
                assign[i] = by_id[wid]
        else:
            assign = {}
            taken: set[int] = set()
            for i, (m, z, R) in enumerate(pending):
                best, bd = None, c["gateChi2"]
                for tr in cands:
                    if tr.id in taken or tr.family != m["family"]:
                        continue
                    d = self._maha(tr, z, self._Rx(tr, z, R, t))
                    if d <= bd:
                        best, bd = tr, d
                if best is not None:
                    assign[i] = best
                    taken.add(best.id)
        for i, (m, z, R) in enumerate(pending):
            best = assign.get(i)
            if best is not None:
                if best.id in self.dead:                           # revived
                    del self.dead[best.id]
                    self.tracks[best.id] = best
                    best.dead_t = None
                if best.tid is not None and self.link.get(best.tid) == best.id:
                    del self.link[best.tid]
                self.link[m["tid"]] = best.id
                best.tid = m["tid"]
                best.images.append(m["tid"])
                self._take(best, m, z, self._Rx(best, z, R, t), t)
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
                    tr.state, tr.miss, tr.miss_t0 = "out-of-view", 0, None
                    drop = drop or t - tr.last_seen > c["coastMaxS"]
                else:
                    tr.state = "missing"
                    tr.miss += 1
                    if tr.miss_t0 is None:
                        tr.miss_t0 = t
                    gone = tr.miss >= c["missDropFrames"] and t - tr.miss_t0 >= c["missDropS"] - 1e-9
                    if gone and not drop and c["reviveS"] > 0:     # kept (unseen in the output) for re-identification
                        del self.tracks[tr.id]
                        if tr.tid is not None and self.link.get(tr.tid) == tr.id:
                            del self.link[tr.tid]
                        tr.dead_t = t
                        self.dead[tr.id] = tr
                        continue
                    drop = drop or gone
            else:
                tr.state, tr.miss, tr.miss_t0 = "seen", 0, None
            if drop:
                tr.state = "dropped"
            out.append(self._json(tr, t, fwd, right, M))
            if drop:
                del self.tracks[tr.id]
                if tr.tid is not None and self.link.get(tr.tid) == tr.id:
                    del self.link[tr.tid]
        for tr in expired:                                        # gave up waiting for a re-identification: reported once as dropped
            fwd, right = M.T @ np.array([tr.x[0] - x0, tr.x[1] - y0])
            tr.state = "dropped"
            out.append(self._json(tr, t, float(fwd), float(right), M))
        out.sort(key=lambda d: (d["fwd"] ** 2 + d["right"] ** 2))
        return out[: int(c["maxTracksOut"])]

    def lookup(self, tid: int, t: float) -> dict | None:
        """(v26.2.11, map mode / predictive speech) The world track an image track belongs to, predicted to time ``t`` on its constant
        velocity: {x, y, vx, vy, trusted, state, static, promoted, seenS} or None. ``trusted`` = the output flag as of its last update."""
        wn = self.link.get(tid)
        tr = self.tracks.get(wn) if wn is not None else None
        if tr is None:
            return None
        c = self.cfg
        dt = max(0.0, t - tr.t)
        sig, vsig = _eig_radius(tr.P[:2, :2]), _eig_radius(tr.P[2:4, 2:4])
        trusted = bool(tr.seen_s >= c["trustMinS"] and sig <= c["trustMaxSigmaM"] and vsig <= c["trustMaxSpeedSigmaMps"] and tr.state != "dropped")
        return {"x": float(tr.x[0] + tr.x[2] * dt), "y": float(tr.x[1] + tr.x[3] * dt), "vx": float(tr.x[2]), "vy": float(tr.x[3]),
                "trusted": trusted, "state": tr.state, "static": bool(tr.static), "promoted": bool(tr.promoted), "seenS": float(tr.seen_s),
                "id": f"W{tr.id}"}

    def _take(self, tr: _WT, m: dict, z: np.ndarray, R: np.ndarray, t: float) -> None:
        tr.innov = float(np.hypot(*(z - tr.x[:2])))          # predicted vs measured position (the re-acquisition error after a gap)
        tr.ivs.append((t, z - tr.x[:2]))
        del tr.ivs[:-12]
        self._update(tr, z, R)
        c = self.cfg
        tr.seen_s += min(max(t - tr.last_seen, 0.0), 0.5)
        tr.seen_now, tr.last_seen, tr.miss, tr.state, tr.miss_t0 = True, t, 0, "seen", None
        tr.cls, tr.group = m["cls"], m["group"]
        if c["moverPromoteMps"] > 0 and m["static"] and not tr.promoted and math.hypot(tr.x[2], tr.x[3]) > c["moverPromoteMps"]:
            tr.prom_t0 = t if tr.prom_t0 is None else tr.prom_t0
            if t - tr.prom_t0 >= c["moverPromoteS"]:
                tr.promoted = True
        elif not tr.promoted:
            tr.prom_t0 = None
        tr.static = bool(m["static"]) and not tr.promoted
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
        sig = _eig_radius(tr.P[:2, :2])
        vsig = _eig_radius(tr.P[2:4, 2:4])
        trusted = bool(tr.seen_s >= c["trustMinS"] and sig <= c["trustMaxSigmaM"] and vsig <= c["trustMaxSpeedSigmaMps"] and tr.state != "dropped")
        return {"id": f"W{tr.id}", "class": tr.cls, "family": tr.family, "group": tr.group, "staticLike": bool(tr.static), "state": tr.state,
                "imageTracks": list(tr.images), "trackId": tr.tid if tr.seen_now else None,
                "x": r2(tr.x[0]), "y": r2(tr.x[1]), "vx": r2(tr.x[2]), "vy": r2(tr.x[3]), "fwd": r2(fwd), "right": r2(right),
                "speedMps": r2(speed), "headingDeg": None if head is None else round(head, 1),
                "relHeadingDeg": None if rel_h is None else round(rel_h, 1), "sigmaM": r2(_eig_radius(tr.P[:2, :2])),
                "cpaM": r2(cpa), "cpaS": r2(ts), "onCourse": bool(on), "ttcS": r2(ttc),
                "innovM": r2(tr.innov), "trusted": trusted, "speedSigmaMps": r2(vsig), "seenS": r2(tr.seen_s), "promoted": bool(tr.promoted), "age": r2(t - tr.t0), "unseenS": r2(0.0 if tr.seen_now else t - tr.last_seen)}
