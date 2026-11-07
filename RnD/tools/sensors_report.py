"""Device-sensor report (v26.2.11): what the GoPro telemetry of a clip holds, and how the pass's heading / speed compare with the GPS.

    python tools/sensors_report.py <recording> [--run <runId> [--collision cN]] [--t0 0 --t1 180] [--json out.json]
    python tools/sensors_report.py --all [--json out.json]

Per recording (needs ffmpeg / the media; run it inside the Lab container): duration, stream rates (gyro / accel Hz, GPS Hz), GPS quality (share of
3D fix, DOP median / p90, share usable at DOP <= maxDop), shutter / ISO range, HiLight (HMMT) tags.

With ``--run`` (an analysis run of that recording; ``--collision`` default: the latest): the heading and speed comparisons against the GPS, in the
windows where the GPS is usable (3D fix, DOP <= maxDop) and the user covered >= 6 m in 8 s (course):
  * heading: the offset (GPS course - heading) is constant up to the unknown north, so its SPREAD is the drift: MAD, p90 of |offset - circular
    mean|, and the trend in deg per 100 s, for ``flow`` (motion.npz dx, the v26.2.10 heading), ``gyro`` (bias from the stationary spans),
    ``gyro-nobias`` and ``gyro+gps`` (the slow GPS correction), and the heading the collision pass stored (``stored``);
  * speed: the Lab's ego speed (stored) against the GPS 2D speed: median, ratio, correlation, and the cadence x step speeds of the image
    cadence and of the accelerometer cadence; the GPS speed while the Lab says stationary.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
import sensors  # noqa: E402


def _q(v, p):
    return round(float(np.percentile(v, p)), 3) if len(v) else None


def clip_table(s: dict, path: str, cfg: dict) -> dict:
    """The per-clip survey row."""
    dur = float(max(s["gyro_t"][-1], s["accl_t"][-1]))
    out = {"durationS": round(dur, 1), "gyroHz": round(len(s["gyro_t"]) / dur, 1), "acclHz": round(len(s["accl_t"]) / dur, 1)}
    if "gps" in s and len(s["gps_t"]):
        fix, dop = s["gps_fix"], s["gps_dop"]
        out.update({"gpsHz": round(len(s["gps_t"]) / dur, 1), "fix3dShare": round(float((fix >= 3).mean()), 3),
                    "dopMedian": _q(dop[fix >= 2], 50), "dopP90": _q(dop[fix >= 2], 90),
                    "usableShare": round(float(sensors.gps_good(s, int(cfg.get("minFix", 3)), float(cfg.get("maxDop", 2.5))).mean()), 3)})
    if "shut" in s:
        out["shutterMs"] = [round(float(np.percentile(s["shut"], 5)) * 1000, 2), round(float(np.percentile(s["shut"], 95)) * 1000, 2)]
        out["isoGain"] = [round(float(np.percentile(s["isog"], 5)), 2), round(float(np.percentile(s["isog"], 95)), 2)]
    out["hilights"] = sensors.hilights(path)
    out["gpsStep"] = gps_step_row(s, cfg)
    return out


def gps_step_row(s: dict, gcfg: dict) -> dict | None:
    """v26.2.12 (O18): the GPS step length of the clip as the collision pass computes it (``sensors.gps_step_length`` on the accelerometer
    cadence and the IMU stationary flags, whole clip), or None without a good fix long enough."""
    import collision
    if "gps" not in s or len(s.get("gps_t", ())) < 10:
        return None
    dur = float(min(s["gyro_t"][-1], s["accl_t"][-1]))
    mt = np.arange(0.0, dur, 1.0 / 24.0)
    ecfg = collision.load_config()["ego"]
    sser = collision._sensor_series(s, None, mt, ecfg, 118.0)
    if sser is None:
        return None
    r = sensors.gps_step_length(sser["s"], sser["mt"], sser["cad"], sser["stat_imu"], {**gcfg, **(ecfg.get("stepLength") or {})})
    return None if r is None else {k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()}


def _wrap(d):
    return (np.asarray(d) + 180.0) % 360.0 - 180.0


def course_offsets(s: dict, series: dict, cfg: dict, t0: float, t1: float, w: float = 8.0, step: float = 2.0, min_travel: float = 6.0) -> dict:
    """For each heading series ({name: (times, degrees)}): the spread of (GPS course - heading) over the windows with a usable course."""
    good = sensors.gps_good(s, int(cfg.get("minFix", 3)), float(cfg.get("maxDop", 2.5)))
    gt = s["gps_t"]
    x, y = sensors.gps_xy(s)
    res: dict[str, list] = {k: [] for k in series}
    n = 0
    for a in np.arange(max(t0, gt[0]) + 1.0, min(t1, float(gt[-1])) - w, step):
        m = good & (gt >= a) & (gt < a + w)
        if m.sum() < w * 18 * 0.5:
            continue
        idx = np.flatnonzero(m)
        dx, dy = x[idx[-1]] - x[idx[0]], y[idx[-1]] - y[idx[0]]
        if math.hypot(dx, dy) < min_travel:
            continue
        n += 1
        course = math.degrees(math.atan2(dx, dy))
        for name, (tt, hh) in series.items():
            ok = np.isfinite(hh)
            res[name].append((float(_wrap(course - float(np.interp(a + w / 2, tt[ok], hh[ok])))), a + w / 2))
    out = {"windows": n}
    for name, v in res.items():
        if len(v) < 5:
            out[name] = None
            continue
        off = np.array([o for o, _ in v])
        tt = np.array([t for _, t in v])
        c = math.degrees(np.angle(np.mean(np.exp(1j * np.radians(off)))))
        dev = _wrap(off - c)
        out[name] = {"madDeg": round(float(np.median(np.abs(dev))), 1), "p90Deg": round(float(np.percentile(np.abs(dev), 90)), 1),
                     "trendDegPer100s": round(float(np.polyfit(tt, np.degrees(np.unwrap(np.radians(off))), 1)[0] * 100.0), 1)}
    return out


def speed_compare(s: dict, t: np.ndarray, lab_speed: np.ndarray, stationary: np.ndarray, cfg: dict, cad_img, cad_imu, step_len: float) -> dict:
    good = sensors.gps_good(s, int(cfg.get("minFix", 3)), float(cfg.get("maxDop", 2.5)))
    if good.sum() < 20:
        return {}
    gps = np.interp(t, s["gps_t"][good], s["gps"][good, 3])
    near = np.array([good[np.clip(np.searchsorted(s["gps_t"], tt), 0, len(good) - 1)] for tt in t])
    mov = ~stationary & np.isfinite(lab_speed) & near & (gps > 0.3)
    out: dict = {"gpsUsableFrames": int(near.sum())}
    if mov.sum() > 10:
        out["gpsMedian"] = round(float(np.median(gps[mov])), 2)
        for name, v in (("labSpeed", lab_speed), ("imageCadenceXStep", cad_img * step_len), ("accelCadenceXStep", cad_imu * step_len)):
            ok = mov & np.isfinite(v)
            if ok.sum() > 10:
                out[name] = {"median": round(float(np.median(v[ok])), 2), "ratioToGps": round(float(np.median(v[ok] / gps[ok])), 2),
                             "corr": round(float(np.corrcoef(v[ok], gps[ok])[0, 1]), 2), "frames": int(ok.sum())}
    st = stationary & near
    if st.sum() > 10:
        out["gpsWhenLabStationary"] = {"median": round(float(np.median(gps[st])), 2), "p90": _q(gps[st], 90)}
    return out


def run_report(s: dict, rec_id: str, run_id: str, cid: str | None, t0: float, t1: float) -> dict:
    import collision
    from lab import analysis, collisions

    cfg_all = collision.load_config()
    ego_cfg = cfg_all["ego"]
    gcfg = ego_cfg.get("gps") or {}
    doc = analysis.get_run(run_id)
    cid = collisions.resolve(doc, cid)
    hz = json.loads((collisions.collision_dir(run_id, cid) / "hazards.json").read_text())
    fr = hz["frames"]
    t = np.array([f["t"] for f in fr])
    egos = [f.get("ego") or {} for f in fr]
    nan = lambda v: np.nan if v is None else float(v)       # noqa: E731
    stored = np.array([nan(e.get("headingDeg")) for e in egos])
    stat = np.array([bool(e.get("stationary")) for e in egos])
    lab_speed = np.array([nan(e.get("speedMps")) for e in egos])
    with np.load(analysis.run_dir(run_id) / "motion.npz") as z:
        mt, dx = z["t"], np.nan_to_num(z["dx"])
    hfov = hz["settings"]["hfovDeg"]
    flow = np.cumsum(-dx * hfov)
    ss = sensors.crop(s, float(mt[0]) - 6, float(mt[-1]) + 6)
    sig = {"flow": (mt, flow)}
    # the stationary series the bias is taken from: the pass's own (stored) one
    st_t = t
    g, info = sensors.heading_series(ss, mt, st_t, stat, ego_cfg.get("imu"))
    g0, _ = sensors.heading_series(ss, mt, None, None, ego_cfg.get("imu"))
    off, ginfo = sensors.gps_course_offset(ss, mt, g, gcfg)
    sig.update({"gyro": (mt, g), "gyro-nobias(lowest20%)": (mt, g0), "gyro+gps": (mt, g + off), "stored": (t, stored)})
    out = {"collision": cid, "bias": info, "gpsUpdates": ginfo["updates"],
           "heading": course_offsets(s, sig, gcfg, t0, t1)}
    # cadence x step
    step_len = hz["settings"].get("priorStepLengthM") or 0.74
    cad_img = np.array([nan(e.get("cadenceHz")) for e in egos])
    vt, vert, side = sensors.vertical_signals(ss)
    cad_u = collision.estimate_cadence(vt, vert, ego_cfg["cadenceWindowSeconds"], ego_cfg["cadenceBandHz"], ego_cfg["cadenceMinPeakRatio"],
                                       dx=side, min_step_hz=ego_cfg.get("minStepHz", 1.4), harmonic_ratio=ego_cfg.get("harmonicMinRatio", 0.25))
    cad_imu = cad_u[np.clip(np.searchsorted(vt, t), 0, len(vt) - 1)]
    out["speed"] = speed_compare(s, t, lab_speed, stat, gcfg, cad_img, cad_imu, step_len)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--run")
    ap.add_argument("--collision")
    ap.add_argument("--t0", type=float, default=0.0)
    ap.add_argument("--t1", type=float, default=1e9)
    ap.add_argument("--json")
    a = ap.parse_args()
    from lab import recordings
    import collision
    gcfg = collision.load_config()["ego"].get("gps") or {}
    recs = [r["id"] for r in recordings.list_recordings()] if a.all else [a.recording]
    result: dict = {}
    for rid in recs:
        rec = recordings.get_recording(rid)
        s = recordings.sensors_for(rid)
        if s is None:
            result[rid] = {"sensors": None}
            print(rid, "no telemetry")
            continue
        row = clip_table(s, rec["chapters"][0]["file"], gcfg)
        result[rid] = row
        print(rid, json.dumps(row))
        if a.run and not a.all:
            row["vsGps"] = run_report(s, rid, a.run, a.collision, a.t0, a.t1)
            print(json.dumps(row["vsGps"], indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
