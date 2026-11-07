"""Device sensors of a recording (v26.2.11): the GoPro GPMF telemetry and what the collision pass derives from it.

``extract(media_path)`` copies the ``gpmd`` data stream with ffmpeg, parses the GPMF KLV payloads (nested type 0, ``SCAL``, big-endian
``b B s S l L j J f d``) and returns time-stamped arrays (seconds from the start of the file):

  gyro  (N, 3) rad/s, channel order as stored (z, x, y); ``gyro_t``
  accl  (M, 3) m/s2, channel order as stored (up/down, right/left, forward/back); ``accl_t``
  gps   (K, 5) lat, lon, alt, speed 2D, speed 3D; ``gps_t``, ``gps_fix`` (0 none / 2 2D / 3 3D), ``gps_dop`` (DOP; 9999 = none), ``gps_utc``
  shut / isog  exposure (s) and gain per frame; ``shut_t`` / ``isog_t``

Sample times: the samples of a payload are spread evenly over the payload's packet pts / duration (ffprobe ``-show_packets`` of the
stream). Fix and DOP are per 1 s payload and repeat for its GPS samples. A file without a ``gpmd`` stream gives None.

The rest is pure numpy: ``heading_series`` (yaw rate about gravity, integrated, bias removed), ``gravity_angles`` (pitch / roll),
``accel_cadence`` / ``accel_stationary``, ``gps_course`` helpers. Axis conventions are config (``ego.imu``) and unit tested on a synthetic turn.
"""
from __future__ import annotations

import json
import math
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np

_FMT = {"b": "b", "B": "B", "s": "h", "S": "H", "l": "i", "L": "I", "j": "q", "J": "Q", "f": "f", "d": "d"}
_STREAMS = ("GYRO", "ACCL", "GPS5", "SHUT", "ISOG")


# --------------------------------------------------------------------------------------------------------------------------
# GPMF parsing
# --------------------------------------------------------------------------------------------------------------------------

def _klv(buf: bytes):
    """Yield (key, type char or None for nested, struct size, repeat, body) of one level of KLV entries."""
    i, n = 0, len(buf)
    while i + 8 <= n:
        key = buf[i:i + 4].decode("latin1")
        typ, size, rep = buf[i + 4], buf[i + 5], struct.unpack(">H", buf[i + 6:i + 8])[0]
        ln = size * rep
        yield key, (chr(typ) if typ else None), size, rep, buf[i + 8:i + 8 + ln]
        i += 8 + ((ln + 3) & ~3)


def _numbers(typ: str, size: int, rep: int, body: bytes) -> np.ndarray | None:
    fmt = _FMT.get(typ)
    if fmt is None or size == 0 or rep == 0:
        return None
    w = struct.calcsize(fmt)
    cnt = size // w
    if cnt == 0 or len(body) < rep * size:
        return None
    return np.frombuffer(body[:rep * size], dtype=">" + fmt).astype(float).reshape(rep, cnt)


def parse_payload(buf: bytes) -> dict[str, dict]:
    """One DEVC payload -> {stream key: {"data": (rep, ch) scaled, "fix": int, "dop": float, "utc": str}} (the first device)."""
    out: dict[str, dict] = {}

    def strm(b: bytes) -> None:
        scal = fix = dop = utc = None
        data: dict[str, np.ndarray] = {}
        for key, typ, size, rep, body in _klv(b):
            if typ is None:
                continue
            if key == "SCAL":
                a = _numbers(typ, size, rep, body)
                scal = None if a is None else a.reshape(-1)
            elif key == "GPSF":
                fix = int(_numbers(typ, size, rep, body)[0, 0])
            elif key == "GPSP":
                dop = float(_numbers(typ, size, rep, body)[0, 0]) / 100.0
            elif key == "GPSU":
                utc = body.rstrip(b"\0").decode("latin1")
            elif key in _STREAMS:
                a = _numbers(typ, size, rep, body)
                if a is not None:
                    data[key] = a
        for key, a in data.items():
            if scal is not None and len(scal) in (1, a.shape[1]):
                a = a / scal
            out[key] = {"data": a, "fix": fix, "dop": dop, "utc": utc}

    def walk(b: bytes) -> None:
        for key, typ, size, rep, body in _klv(b):
            if typ is None:
                if key == "STRM":
                    strm(body)
                else:
                    walk(body)

    walk(buf)
    return out


def split_payloads(raw: bytes) -> list[bytes]:
    """The top-level DEVC entries of the raw stream copy (one per packet)."""
    out, i = [], 0
    while i + 8 <= len(raw):
        ln = raw[i + 5] * struct.unpack(">H", raw[i + 6:i + 8])[0]
        if raw[i:i + 4] != b"DEVC":
            break
        out.append(raw[i:i + 8 + ln])
        i += 8 + ((ln + 3) & ~3)
    return out


def _gpmd_stream(media_path: str) -> tuple[int, list[tuple[float, float]]] | None:
    """(stream index, [(pts, duration)] of its packets) or None."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_tag_string", "-of", "json", str(media_path)],
                           capture_output=True, text=True, timeout=60)
        idx = next((s["index"] for s in json.loads(r.stdout or "{}").get("streams", []) if s.get("codec_tag_string") == "gpmd"), None)
        if idx is None:
            return None
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", str(idx), "-show_entries", "packet=pts_time,duration_time",
                            "-of", "csv=p=0", str(media_path)], capture_output=True, text=True, timeout=120)
        pk = []
        for line in r.stdout.splitlines():
            a = line.split(",")
            if len(a) >= 2 and a[0] and a[1]:
                pk.append((float(a[0]), float(a[1])))
        return idx, pk
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _utc_epoch(s: str | None) -> float:
    """GPSU 'yymmddhhmmss.sss' -> epoch seconds (nan when absent)."""
    if not s or len(s) < 12:
        return float("nan")
    try:
        import calendar
        yy, mo, dd, hh, mi = int(s[0:2]), int(s[2:4]), int(s[4:6]), int(s[6:8]), int(s[8:10])
        return calendar.timegm((2000 + yy, mo, dd, hh, mi, 0)) + float(s[10:])
    except ValueError:
        return float("nan")


def build(payloads: list[bytes], packets: list[tuple[float, float]]) -> dict[str, np.ndarray]:
    """Time-stamped arrays from the payloads (payload i spans packets[i])."""
    acc: dict[str, list] = {k: [] for k in ("gyro", "accl", "gps", "shut", "isog")}
    tt: dict[str, list] = {k: [] for k in acc}
    gps_fix, gps_dop, gps_utc = [], [], []
    for p, (pts, dur) in zip(payloads, packets):
        for key, v in parse_payload(p).items():
            name = {"GYRO": "gyro", "ACCL": "accl", "GPS5": "gps", "SHUT": "shut", "ISOG": "isog"}[key]
            a = v["data"]
            n = len(a)
            tt[name].append(pts + dur * (np.arange(n) + 0.5) / n)
            acc[name].append(a)
            if name == "gps":
                gps_fix.append(np.full(n, -1 if v["fix"] is None else v["fix"]))
                gps_dop.append(np.full(n, 9999.0 if v["dop"] is None else v["dop"]))
                gps_utc.append(np.full(n, _utc_epoch(v["utc"])))
    out: dict[str, np.ndarray] = {}
    for name in acc:
        if acc[name]:
            out[name] = np.concatenate(acc[name])
            out[name + "_t"] = np.concatenate(tt[name])
    if gps_fix:
        out["gps_fix"], out["gps_dop"], out["gps_utc"] = np.concatenate(gps_fix), np.concatenate(gps_dop), np.concatenate(gps_utc)
    for k in ("shut", "isog"):                     # per-frame scalars: keep one column
        if k in out and out[k].ndim == 2:
            out[k] = out[k][:, 0]
    return out


def extract(media_path: str) -> dict[str, np.ndarray] | None:
    """The telemetry of one media file, or None when it has no GPMF stream (or ffmpeg is missing)."""
    found = _gpmd_stream(str(media_path))
    if found is None or not found[1]:
        return None
    idx, packets = found
    with tempfile.TemporaryDirectory() as td:
        raw_path = Path(td) / "gpmd.bin"
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(media_path), "-map", f"0:{idx}", "-codec", "copy", "-f", "rawvideo",
                            str(raw_path)], check=True, capture_output=True, timeout=300)
            raw = raw_path.read_bytes()
        except (OSError, subprocess.SubprocessError):
            return None
    payloads = split_payloads(raw)
    if not payloads:
        return None
    n = min(len(payloads), len(packets))
    out = build(payloads[:n], packets[:n])
    return out if "gyro" in out and "accl" in out else None


def hilights(media_path: str) -> list[float]:
    """HiLight tags (udta ``HMMT``: u32 count, then count x u32 milliseconds), seconds. Empty when none."""
    try:
        with open(media_path, "rb") as f:
            size = Path(media_path).stat().st_size

            def atoms(off: int, end: int, path: str):
                while off + 8 <= end:
                    f.seek(off)
                    size_, typ = struct.unpack(">I4s", f.read(8))
                    hdr = 8
                    if size_ == 1:
                        size_, hdr = struct.unpack(">Q", f.read(8))[0], 16
                    elif size_ == 0:
                        size_ = end - off
                    typ = typ.decode("latin1")
                    if size_ < hdr:
                        return None
                    if typ in ("moov", "udta") and path in ("", "moov"):
                        r = atoms(off + hdr, off + size_, "moov" if typ == "moov" else "udta")
                        if r is not None:
                            return r
                    elif typ == "HMMT" and path == "udta":
                        f.seek(off + hdr)
                        body = f.read(size_ - hdr)
                        cnt = struct.unpack(">I", body[:4])[0] if len(body) >= 4 else 0
                        cnt = min(cnt, (len(body) - 4) // 4)
                        return [struct.unpack(">I", body[4 + 4 * k:8 + 4 * k])[0] / 1000.0 for k in range(cnt)]
                    off += size_
                return None
            return atoms(0, size, "") or []
    except (OSError, struct.error):
        return []


def concat(parts: list[tuple[float, dict[str, np.ndarray]]]) -> dict[str, np.ndarray] | None:
    """Join chapters: (start offset s, extract() result) -> one dict on the recording's timeline."""
    parts = [(o, d) for o, d in parts if d]
    if not parts:
        return None
    out: dict[str, np.ndarray] = {}
    for k in parts[0][1]:
        if k.endswith("_t"):
            out[k] = np.concatenate([d[k] + o for o, d in parts if k in d])
        else:
            out[k] = np.concatenate([d[k] for o, d in parts if k in d])
    return out


def save(path: str | Path, s: dict[str, np.ndarray]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez_compressed(tmp, **s)
    tmp.replace(p)


def load(path: str | Path) -> dict[str, np.ndarray] | None:
    try:
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------------------------------------------------------
# Derived signals
# --------------------------------------------------------------------------------------------------------------------------

def _smooth(t: np.ndarray, x: np.ndarray, win_s: float) -> np.ndarray:
    """Centred moving average over ``win_s`` seconds of an irregularly stamped (N, C) signal, edges averaged over what exists."""
    x = np.asarray(x, dtype=float)
    if len(t) < 2 or win_s <= 0:
        return x.copy()
    lo = np.searchsorted(t, t - win_s / 2.0, side="left")
    hi = np.searchsorted(t, t + win_s / 2.0, side="right")
    cs = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(x, axis=0)])
    return (cs[hi] - cs[lo]) / np.maximum(hi - lo, 1)[:, None]


def default_imu_cfg() -> dict:
    return {"yawSign": -1.0, "gravityTauS": 0.5, "yawGravityTauS": 1.0, "accelUpAxis": 0, "accelRightAxis": 1, "accelForwardAxis": 2,
            "pitchSign": -1.0, "rollSign": -1.0, "biasMinStationaryS": 2.0, "biasLowFraction": 0.2, "timeOffsetS": -0.10}


def gravity_unit(s: dict, tau_s: float) -> np.ndarray:
    """Low-passed accelerometer (the gravity direction, reaction convention) per accel sample, unit length."""
    g = _smooth(s["accl_t"], s["accl"], tau_s)
    n = np.linalg.norm(g, axis=1, keepdims=True)
    return g / np.maximum(n, 1e-9)


def yaw_rate(s: dict, cfg: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(gyro times, yaw rate rad/s about gravity; + = turning right). Rate = sign x (gyro . gravity unit), the gyro channel order equals the
    accelerometer channel order as stored."""
    c = {**default_imu_cfg(), **(cfg or {})}
    gu = gravity_unit(s, c["yawGravityTauS"])
    gx = np.stack([np.interp(s["gyro_t"], s["accl_t"], gu[:, j]) for j in range(3)], axis=1)
    return s["gyro_t"], float(c["yawSign"]) * (s["gyro"] * gx).sum(axis=1)


def _spans(t: np.ndarray, flag: np.ndarray, min_s: float) -> list[tuple[float, float]]:
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


def estimate_bias(gt: np.ndarray, rate: np.ndarray, stat_t=None, stat=None, cfg: dict | None = None) -> tuple[np.ndarray, str]:
    """(bias rad/s per gyro sample, source). Bias = median rate over the stationary spans >= ``biasMinStationaryS`` (interpolated between the
    spans, constant outside); without such spans the median rate of the clip's lowest-|rate| ``biasLowFraction`` of samples."""
    c = {**default_imu_cfg(), **(cfg or {})}
    if stat_t is not None and stat is not None and len(stat_t) > 1:
        flag = np.asarray(stat, dtype=bool)
        centers, vals = [], []
        for a, b in _spans(np.asarray(stat_t, dtype=float), flag, c["biasMinStationaryS"]):
            m = (gt >= a) & (gt <= b)
            if m.sum() > 50:
                centers.append(0.5 * (a + b))
                vals.append(float(np.median(rate[m])))
        if centers:
            return np.interp(gt, centers, vals), "stationary"
    if len(rate) < 100:
        return np.zeros_like(rate), "none"
    order = np.argsort(np.abs(rate))[:max(50, int(len(rate) * c["biasLowFraction"]))]
    return np.full_like(rate, float(np.median(rate[order]))), "lowest"


def heading_series(s: dict, times, stat_t=None, stat=None, cfg: dict | None = None) -> tuple[np.ndarray, dict]:
    """Heading in degrees at ``times`` (0 at the first time; + = right turn, same sign as the flow heading) and an info dict
    {"biasDegPerS", "biasSource"}."""
    gt, rate = yaw_rate(s, cfg)
    bias, src = estimate_bias(gt, rate, stat_t, stat, cfg)
    dt = np.diff(gt, prepend=gt[0])
    dt[0] = 0.0
    cum = np.degrees(np.cumsum((rate - bias) * dt))
    times = np.asarray(times, dtype=float)
    off = float((cfg or {}).get("timeOffsetS", 0.0))          # the video frame at t shows what the gyro felt at t + off (video lags: off < 0)
    h = np.interp(times + off, gt, cum)
    return h - h[0] if len(h) else h, {"biasDegPerS": round(float(np.degrees(np.median(bias))), 4), "biasSource": src}


def gravity_angles(s: dict, cfg: dict | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(accel times, pitch deg, roll deg) from the low-passed accelerometer. pitch + = looking up, roll + = right side down; the mount offset is
    in the values (the pass calibrates against the image horizon at the start)."""
    c = {**default_imu_cfg(), **(cfg or {})}
    g = gravity_unit(s, c["gravityTauS"])
    up, right, fwd = g[:, c["accelUpAxis"]], g[:, c["accelRightAxis"]], g[:, c["accelForwardAxis"]]
    pitch = np.degrees(np.arctan2(fwd, np.hypot(up, right))) * float(c["pitchSign"])
    roll = np.degrees(np.arctan2(right, up)) * float(c["rollSign"])
    return s["accl_t"], pitch, roll


def vertical_signals(s: dict, rate_hz: float = 60.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(uniform times, acceleration along gravity, sideways acceleration) resampled at ``rate_hz``: the bob and the sway of the gait, the
    inputs of the same cadence estimator the image flow uses (``collision.estimate_cadence``)."""
    t, a = s["accl_t"], s["accl"]
    gu = gravity_unit(s, 1.0)
    vert = (a * gu).sum(axis=1)
    side = a[:, 1] - gu[:, 1] * vert
    tu = np.arange(t[0], t[-1], 1.0 / rate_hz)
    return tu, np.interp(tu, t, vert), np.interp(tu, t, side)


def motion_energy(s: dict, win_s: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """(times of accel samples, accel + gyro activity): the std over ``win_s`` of the accelerometer norm (m/s2) and of the gyro norm
    (rad/s) combined as accel_std + 2 x gyro_std (a stationary camera is quiet in both)."""
    t = s["accl_t"]
    an = np.linalg.norm(s["accl"], axis=1)[:, None]
    m1 = _smooth(t, an, win_s)[:, 0]
    m2 = _smooth(t, an * an, win_s)[:, 0]
    a_std = np.sqrt(np.maximum(m2 - m1 * m1, 0.0))
    gn = np.linalg.norm(s["gyro"], axis=1)[:, None]
    g_t = s["gyro_t"]
    g1 = _smooth(g_t, gn, win_s)[:, 0]
    g2 = _smooth(g_t, gn * gn, win_s)[:, 0]
    g_std = np.sqrt(np.maximum(g2 - g1 * g1, 0.0))
    return t, a_std + 2.0 * np.interp(t, g_t, g_std)


# --------------------------------------------------------------------------------------------------------------------------
# GPS
# --------------------------------------------------------------------------------------------------------------------------

def gps_good(s: dict, min_fix: int, max_dop: float) -> np.ndarray:
    return (s["gps_fix"] >= min_fix) & (s["gps_dop"] <= max_dop)


def gps_xy(s: dict) -> tuple[np.ndarray, np.ndarray]:
    """Local east / north metres of every GPS sample (origin = the first fixed sample)."""
    lat, lon = s["gps"][:, 0], s["gps"][:, 1]
    ok = s["gps_fix"] >= 2
    i0 = int(np.flatnonzero(ok)[0]) if ok.any() else 0
    return ((lon - lon[i0]) * 111320.0 * math.cos(math.radians(lat[i0])), (lat - lat[i0]) * 110540.0)


def crop(s: dict, t0: float, t1: float) -> dict:
    """The sensors restricted to [t0, t1] (each stream by its own ``*_t``)."""
    groups = {"gyro": ("gyro", "gyro_t"), "accl": ("accl", "accl_t"), "gps": ("gps", "gps_t", "gps_fix", "gps_dop", "gps_utc"),
              "shut": ("shut", "shut_t"), "isog": ("isog", "isog_t")}
    out: dict[str, np.ndarray] = {}
    for g, keys in groups.items():
        if keys[1] not in s:
            continue
        m = (s[keys[1]] >= t0) & (s[keys[1]] <= t1)
        for k in keys:
            if k in s:
                out[k] = s[k][m]
    return out


def _wrap(d):
    return (np.asarray(d) + 180.0) % 360.0 - 180.0


def gps_course_offset(s: dict, ht, heading, cfg: dict) -> tuple[np.ndarray, dict]:
    """Slow GPS correction of a heading series (v26.2.11, ``ego.gps``). Course = the direction of the chord over the last ``courseWindowS``
    of good fixes (fix >= ``minFix``, DOP <= ``maxDop``) when the user covered >= ``courseMinTravelM`` at >= ``courseMinSpeedMps`` and the
    heading turned < ``courseMaxTurnDeg`` meanwhile; the residual course - heading goes through an exponential average (time constant
    ``courseTauS``, residuals more than ``courseRejectDeg`` off the average are ignored). The heading is "0 = the initial direction", so only the
    CHANGE of the average since its first value (the median of the first ``courseInitN`` residuals) is applied. Causal.
    Returns (offset degrees per ``ht``, info {"updates", "applied"})."""
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
    ups_t, ups_r = [], []
    e = e0 = None
    last_t = None
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
        if abs(_wrap(hw[2] - hw[0])) > max_turn:
            continue
        r = float(_wrap(math.degrees(math.atan2(dx, dy)) - hw[1]))
        if e0 is None:
            ups_r.append(r)
            if len(ups_r) >= init_n:
                spread = np.abs(_wrap(np.array(ups_r) - np.median(ups_r)))
                if np.median(spread) < 30.0:
                    e = e0 = float(np.median(ups_r))
                    last_t = T
                else:
                    ups_r.pop(0)
            continue
        if abs(_wrap(r - e)) > reject:
            continue
        a = 1.0 - math.exp(-(T - last_t) / tau)
        e += a * float(_wrap(r - e))
        last_t = T
        ev_t.append(T)
        ev_v.append(float(_wrap(e - e0)))
        info["updates"] += 1
    if not ev_t:
        return zero, info
    # hold the last update (causal), no look-ahead
    k = np.searchsorted(ev_t, ht, side="right") - 1
    out = np.where(k >= 0, np.asarray(ev_v)[np.maximum(k, 0)], 0.0)
    info["meanOffsetDeg"] = round(float(np.mean(out)), 2)
    return out, info


def gps_step_length(s: dict, mt, cadence, stationary, cfg: dict) -> dict | None:
    """v26.2.12 (O18, ``ego.stepLength``): the user's step length from the GPS: the median of (GPS 2D speed / step cadence) over the samples with a
    good fix (fix >= ``minFix``, DOP <= ``maxDop``), a known cadence >= ``minCadenceHz`` (``mt`` / ``cadence`` / ``stationary``: the pass's
    time base, step cadence and stationary flags) and a speed >= ``minSpeedMps`` (a moving user), clamped to ``rangeM``. Needs ``minS`` seconds of
    such samples (GPS sample time summed). Returns {"stepM", "windowsS", "samples", "p10", "p90", "raw"} or None (no GPS / not enough)."""
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
    ok &= np.isfinite(cad) & (cad >= float(cfg.get("minCadenceHz", 1.0))) & ~stat & (spd >= float(cfg.get("minSpeedMps", 0.5)))
    if not ok.any():
        return None
    dt = float(np.median(np.diff(gt))) if len(gt) > 1 else 0.055
    windows_s = float(ok.sum()) * dt
    if windows_s < float(cfg.get("minS", 10.0)):
        return None
    ratio = spd[ok] / cad[ok]
    lo, hi = (float(v) for v in cfg.get("rangeM", [0.5, 1.1]))
    raw = float(np.median(ratio))
    return {"stepM": min(hi, max(lo, raw)), "raw": raw, "windowsS": windows_s, "samples": int(ok.sum()),
            "p10": float(np.percentile(ratio, 10)), "p90": float(np.percentile(ratio, 90))}
