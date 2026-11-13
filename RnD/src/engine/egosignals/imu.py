"""IMU and GPS derived signals: heading (yaw about gravity), pitch / roll, bob / sway, motion energy, GPS course and
step length."""

from __future__ import annotations

import math
from typing import Any, cast

import numpy as np
import numpy.typing as npt

Arr = npt.NDArray[Any]


def smooth(t: Arr, x: Arr, win_s: float) -> Arr:
    """Centred moving average over ``win_s`` seconds of an irregularly stamped (N, C) signal, edges averaged over what
    exists."""
    x = np.asarray(x, dtype=float)
    if len(t) < 2 or win_s <= 0:
        return x.copy()
    lo = np.searchsorted(t, t - win_s / 2.0, side="left")
    hi = np.searchsorted(t, t + win_s / 2.0, side="right")
    cs = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(x, axis=0)])
    return cast("Arr", (cs[hi] - cs[lo]) / np.maximum(hi - lo, 1)[:, None])


def default_imu_cfg() -> dict[str, Any]:
    return {
        "yawSign": -1.0,
        "gravityTauS": 0.5,
        "yawGravityTauS": 1.0,
        "accelUpAxis": 0,
        "accelRightAxis": 1,
        "accelForwardAxis": 2,
        "pitchSign": -1.0,
        "rollSign": -1.0,
        "biasMinStationaryS": 2.0,
        "biasLowFraction": 0.2,
        "timeOffsetS": -0.10,
    }


def gravity_unit(s: dict[str, Any], tau_s: float) -> Arr:
    """Low-passed accelerometer (the gravity direction, reaction convention) per accel sample, unit length."""
    g = smooth(s["accl_t"], s["accl"], tau_s)
    n = np.linalg.norm(g, axis=1, keepdims=True)
    return cast("Arr", g / np.maximum(n, 1e-9))


def yaw_rate(s: dict[str, Any], cfg: dict[str, Any] | None = None) -> tuple[Arr, Arr]:
    """(gyro times, yaw rate rad/s about gravity; + = turning right). Rate = sign x (gyro . gravity unit), the gyro
    channel order equals the accelerometer channel order as stored."""
    c = {**default_imu_cfg(), **(cfg or {})}
    gu = gravity_unit(s, c["yawGravityTauS"])
    gx = np.stack([np.interp(s["gyro_t"], s["accl_t"], gu[:, j]) for j in range(3)], axis=1)
    return s["gyro_t"], float(c["yawSign"]) * (s["gyro"] * gx).sum(axis=1)


def spans(t: Arr, flag: Arr, min_s: float) -> list[tuple[float, float]]:
    out, start = [], None
    for k in range(len(t)):
        if flag[k] and start is None:
            start = t[k]
        if (not flag[k] or k == len(t) - 1) and start is not None:
            end = t[k]
            if end - start >= min_s:
                out.append((float(start), float(end)))
            start = None
    return out


def estimate_bias(
    gt: Arr, rate: Arr, stat_t: Any = None, stat: Any = None, cfg: dict[str, Any] | None = None
) -> tuple[Arr, str]:
    """(bias rad/s per gyro sample, source). Bias = median rate over the stationary spans >= ``biasMinStationaryS``
    (interpolated between the spans, constant outside); without such spans the median rate of the clip's lowest-|rate|
    ``biasLowFraction`` of samples."""
    c = {**default_imu_cfg(), **(cfg or {})}
    if stat_t is not None and stat is not None and len(stat_t) > 1:
        flag = np.asarray(stat, dtype=bool)
        centers, vals = [], []
        for a, b in spans(np.asarray(stat_t, dtype=float), flag, c["biasMinStationaryS"]):
            m = (gt >= a) & (gt <= b)
            if m.sum() > 50:
                centers.append(0.5 * (a + b))
                vals.append(float(np.median(rate[m])))
        if centers:
            return np.interp(gt, centers, vals), "stationary"
    if len(rate) < 100:
        return np.zeros_like(rate), "none"
    order = np.argsort(np.abs(rate))[: max(50, int(len(rate) * c["biasLowFraction"]))]
    return np.full_like(rate, float(np.median(rate[order]))), "lowest"


def heading_series(
    s: dict[str, Any], times: Any, stat_t: Any = None, stat: Any = None, cfg: dict[str, Any] | None = None
) -> tuple[Arr, dict[str, Any]]:
    """Heading in degrees at ``times`` (0 at the first time; + = right turn, same sign as the flow heading) and an info
    dict {"biasDegPerS", "biasSource"}."""
    gt, rate = yaw_rate(s, cfg)
    bias, src = estimate_bias(gt, rate, stat_t, stat, cfg)
    dt = np.diff(gt, prepend=gt[0])
    dt[0] = 0.0
    cum = np.degrees(np.cumsum((rate - bias) * dt))
    times = np.asarray(times, dtype=float)
    off = float(
        (cfg or {}).get("timeOffsetS", 0.0)
    )  # the video frame at t shows what the gyro felt at t + off (video lags: off < 0)
    h = np.interp(times + off, gt, cum)
    return h - h[0] if len(h) else h, {"biasDegPerS": round(float(np.degrees(np.median(bias))), 4), "biasSource": src}


def gravity_angles(s: dict[str, Any], cfg: dict[str, Any] | None = None) -> tuple[Arr, Arr, Arr]:
    """(accel times, pitch deg, roll deg) from the low-passed accelerometer. pitch + = looking up, roll + = right side
    down; the mount offset is in the values (the pass calibrates against the image horizon at the start)."""
    c = {**default_imu_cfg(), **(cfg or {})}
    g = gravity_unit(s, c["gravityTauS"])
    up, right, fwd = g[:, c["accelUpAxis"]], g[:, c["accelRightAxis"]], g[:, c["accelForwardAxis"]]
    pitch = np.degrees(np.arctan2(fwd, np.hypot(up, right))) * float(c["pitchSign"])
    roll = np.degrees(np.arctan2(right, up)) * float(c["rollSign"])
    return s["accl_t"], pitch, roll


def vertical_signals(s: dict[str, Any], rate_hz: float = 60.0) -> tuple[Arr, Arr, Arr]:
    """(uniform times, acceleration along gravity, sideways acceleration) resampled at ``rate_hz``: the bob and the sway
    of the gait, the inputs of the same cadence estimator the image flow uses (``collision.estimate_cadence``)."""
    t, a = s["accl_t"], s["accl"]
    gu = gravity_unit(s, 1.0)
    vert = (a * gu).sum(axis=1)
    side = a[:, 1] - gu[:, 1] * vert
    tu = np.arange(t[0], t[-1], 1.0 / rate_hz)
    return tu, np.interp(tu, t, vert), np.interp(tu, t, side)


def motion_energy(s: dict[str, Any], win_s: float = 1.0) -> tuple[Arr, Arr]:
    """(times of accel samples, accel + gyro activity): the std over ``win_s`` of the accelerometer norm (m/s2) and of
    the gyro norm (rad/s) combined as accel_std + 2 x gyro_std (a stationary camera is quiet in both)."""
    t = s["accl_t"]
    an = np.linalg.norm(s["accl"], axis=1)[:, None]
    m1 = smooth(t, an, win_s)[:, 0]
    m2 = smooth(t, an * an, win_s)[:, 0]
    a_std = np.sqrt(np.maximum(m2 - m1 * m1, 0.0))
    gn = np.linalg.norm(s["gyro"], axis=1)[:, None]
    g_t = s["gyro_t"]
    g1 = smooth(g_t, gn, win_s)[:, 0]
    g2 = smooth(g_t, gn * gn, win_s)[:, 0]
    g_std = np.sqrt(np.maximum(g2 - g1 * g1, 0.0))
    return t, a_std + 2.0 * np.interp(t, g_t, g_std)


# -------------------------------------------------------------------------------------------------------------------
# GPS
# -------------------------------------------------------------------------------------------------------------------


def gps_good(s: dict[str, Any], min_fix: int, max_dop: float) -> Arr:
    return cast("Arr", (s["gps_fix"] >= min_fix) & (s["gps_dop"] <= max_dop))


def gps_xy(s: dict[str, Any]) -> tuple[Arr, Arr]:
    """Local east / north metres of every GPS sample (origin = the first fixed sample)."""
    lat, lon = s["gps"][:, 0], s["gps"][:, 1]
    ok = s["gps_fix"] >= 2
    i0 = int(np.flatnonzero(ok)[0]) if ok.any() else 0
    return ((lon - lon[i0]) * 111320.0 * math.cos(math.radians(lat[i0])), (lat - lat[i0]) * 110540.0)


def crop(s: dict[str, Any], t0: float, t1: float) -> dict[str, Any]:
    """The sensors restricted to [t0, t1] (each stream by its own ``*_t``)."""
    groups = {
        "gyro": ("gyro", "gyro_t"),
        "accl": ("accl", "accl_t"),
        "gps": ("gps", "gps_t", "gps_fix", "gps_dop", "gps_utc"),
        "shut": ("shut", "shut_t"),
        "isog": ("isog", "isog_t"),
    }
    out: dict[str, Arr] = {}
    for _g, keys in groups.items():
        if keys[1] not in s:
            continue
        m = (s[keys[1]] >= t0) & (s[keys[1]] <= t1)
        for k in keys:
            if k in s:
                out[k] = s[k][m]
    return out


def wrap_deg(d: Any) -> Arr:
    return (np.asarray(d) + 180.0) % 360.0 - 180.0


def gps_course_offset(s: dict[str, Any], ht: Any, heading: Any, cfg: dict[str, Any]) -> tuple[Arr, dict[str, Any]]:
    """Slow GPS correction of a heading series (v26.2.11, ``ego.gps``). Course = the direction of the chord over the
    last ``courseWindowS`` of good fixes (fix >= ``minFix``, DOP <= ``maxDop``) when the user covered >=
    ``courseMinTravelM`` at >= ``courseMinSpeedMps`` and the heading turned < ``courseMaxTurnDeg`` meanwhile; the
    residual course - heading goes through an exponential average (time constant ``courseTauS``, residuals more than
    ``courseRejectDeg`` off the average are ignored). The heading is "0 = the initial direction", so only the CHANGE of
    the average since its first value (the median of the first ``courseInitN`` residuals) is applied. Causal. Returns
    (offset degrees per ``ht``, info {"updates", "applied"})."""
    ht = np.asarray(ht, dtype=float)
    heading = np.asarray(heading, dtype=float)
    info = {"updates": 0, "meanOffsetDeg": 0.0}
    zero = np.zeros(len(ht))
    if "gps" not in s or len(s["gps_t"]) < 10 or not len(ht):
        return zero, info
    good = gps_good(s, int(cfg.get("minFix", 3)), float(cfg.get("maxDop", 2.5)))
    if good.sum() < 20:
        return zero, info
    gt = s["gps_t"]
    x, y = gps_xy(s)
    w = float(cfg.get("courseWindowS", 8.0))
    min_tr, min_sp = float(cfg.get("courseMinTravelM", 6.0)), float(cfg.get("courseMinSpeedMps", 0.6))
    max_turn, reject = float(cfg.get("courseMaxTurnDeg", 25.0)), float(cfg.get("courseRejectDeg", 60.0))
    tau, init_n = float(cfg.get("courseTauS", 30.0)), int(cfg.get("courseInitN", 5))
    _ups_t: list[float] = []
    ups_r: list[float] = []
    e: Any = None
    e0: Any = None
    last_t: Any = None
    ev_t, ev_v = [], []
    for T in np.arange(max(gt[0], ht[0]) + w, min(gt[-1], ht[-1]), 1.0):
        m = good & (gt > T - w) & (gt <= T)
        if m.sum() < 0.5 * w * 18 * 0.5:
            continue
        idx = np.flatnonzero(m)
        dx, dy = x[idx[-1]] - x[idx[0]], y[idx[-1]] - y[idx[0]]
        dist = math.hypot(dx, dy)
        span = gt[idx[-1]] - gt[idx[0]]
        if dist < min_tr or span <= 0 or dist / span < min_sp:
            continue
        hw = np.interp([T - w, T - w / 2.0, T], ht, heading)
        if abs(wrap_deg(hw[2] - hw[0])) > max_turn:
            continue
        r = float(wrap_deg(math.degrees(math.atan2(dx, dy)) - hw[1]))
        if e0 is None:
            ups_r.append(r)
            if len(ups_r) >= init_n:
                spread = np.abs(wrap_deg(np.array(ups_r) - np.median(ups_r)))
                if np.median(spread) < 30.0:
                    e = e0 = float(np.median(ups_r))
                    last_t = T
                else:
                    ups_r.pop(0)
            continue
        if abs(wrap_deg(r - e)) > reject:
            continue
        a = 1.0 - math.exp(-(T - last_t) / tau)
        e += a * float(wrap_deg(r - e))
        last_t = T
        ev_t.append(T)
        ev_v.append(float(wrap_deg(e - e0)))
        info["updates"] += 1
    if not ev_t:
        return zero, info
    # hold the last update (causal), no look-ahead
    k = np.searchsorted(ev_t, ht, side="right") - 1
    out = np.where(k >= 0, np.asarray(ev_v)[np.maximum(k, 0)], 0.0)
    info["meanOffsetDeg"] = round(float(np.mean(out)), 2)
    return out, info


def gps_step_length(
    s: dict[str, Any], mt: Any, cadence: Any, stationary: Any, cfg: dict[str, Any]
) -> dict[str, Any] | None:
    """v26.2.12 (O18, ``ego.stepLength``): the user's step length from the GPS: the median of (GPS 2D speed / step
    cadence) over the samples with a good fix (fix >= ``minFix``, DOP <= ``maxDop``), a known cadence >=
    ``minCadenceHz`` (``mt`` / ``cadence`` / ``stationary``: the pass's time base, step cadence and stationary flags)
    and a speed >= ``minSpeedMps`` (a moving user), clamped to ``rangeM``. Needs ``minS`` seconds of such samples (GPS
    sample time summed). Returns {"stepM", "windowsS", "samples", "p10", "p90", "raw"} or None (no GPS / not enough)."""
    if not s or "gps" not in s or len(s.get("gps_t", ())) < 10:
        return None
    mt = np.asarray(mt, dtype=float)
    cadence = np.asarray(cadence, dtype=float)
    gt = np.asarray(s["gps_t"], dtype=float)
    good = gps_good(s, int(cfg.get("minFix", 3)), float(cfg.get("maxDop", 2.5)))
    if not good.any() or len(mt) < 2:
        return None
    k = np.clip(np.searchsorted(mt, gt), 1, len(mt) - 1)
    k = np.where(np.abs(mt[k - 1] - gt) <= np.abs(mt[k] - gt), k - 1, k)
    ok = good & (np.abs(mt[k] - gt) <= 0.25) & (gt >= mt[0]) & (gt <= mt[-1])
    cad = cadence[k]
    spd = np.asarray(s["gps"][:, 3], dtype=float)
    stat = np.zeros(len(gt), dtype=bool) if stationary is None else np.asarray(stationary, dtype=bool)[k]
    ok &= (
        np.isfinite(cad)
        & (cad >= float(cfg.get("minCadenceHz", 1.0)))
        & ~stat
        & (spd >= float(cfg.get("minSpeedMps", 0.5)))
    )
    if not ok.any():
        return None
    dt = float(np.median(np.diff(gt))) if len(gt) > 1 else 0.055
    windows_s = float(ok.sum()) * dt
    if windows_s < float(cfg.get("minS", 10.0)):
        return None
    ratio = spd[ok] / cad[ok]
    lo, hi = (float(v) for v in cfg.get("rangeM", [0.5, 1.1]))
    raw = float(np.median(ratio))
    return {
        "stepM": min(hi, max(lo, raw)),
        "raw": raw,
        "windowsS": windows_s,
        "samples": int(ok.sum()),
        "p10": float(np.percentile(ratio, 10)),
        "p90": float(np.percentile(ratio, 90)),
    }
