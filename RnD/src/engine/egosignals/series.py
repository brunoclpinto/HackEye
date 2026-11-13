"""Per-run ego signal series: motion-track cadence / heading, device-sensor series, GPS state, stationary source."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from engine.egosignals import imu
from engine.egosignals.cadence import estimate_cadence, estimate_stationary

Arr = npt.NDArray[Any]


def motion_series(
    motion: dict[str, Any] | None, hfov_deg: float, ego_cfg: dict[str, Any]
) -> tuple[Arr, Arr, Arr, Arr | None] | None:
    """(t, cadence per sample, cumulative heading degrees per sample, stationary flag per sample or None) or None."""
    if motion is None:
        return None
    mt = np.asarray(motion["t"], dtype=float)
    if len(mt) < 2:
        return None
    dx = np.nan_to_num(np.asarray(motion["dx"], dtype=float))
    dy = np.nan_to_num(np.asarray(motion["dy"], dtype=float))
    cad = estimate_cadence(
        mt,
        dy,
        ego_cfg["cadenceWindowSeconds"],
        ego_cfg["cadenceBandHz"],
        ego_cfg["cadenceMinPeakRatio"],
        dx=dx,
        min_step_hz=ego_cfg.get("minStepHz", 1.4),
        harmonic_ratio=ego_cfg.get("harmonicMinRatio", 0.25),
    )
    stat = None
    if motion.get("resid") is not None and len(motion["resid"]) == len(mt):
        # v26.1.11; old runs: never stationary
        stat = estimate_stationary(mt, motion["resid"], ego_cfg.get("stationary", {}))
    return mt, cad, np.cumsum(-dx * hfov_deg), stat


IMU_STATIONARY_DEFAULT = {
    "medianSeconds": 0.3,
    "enterPx": 0.5,
    "leavePx": 0.8,
    "enterSeconds": 1.5,
    "leaveSeconds": 1.0,
}


def nearest(tu: Arr, t: Arr) -> Arr:
    """Index in the sorted ``tu`` of the sample at or just before each ``t`` (clipped)."""
    return np.clip(np.searchsorted(tu, t + 1e-9, side="right") - 1, 0, len(tu) - 1)


def sensor_series(
    sens: dict[str, Any] | None,
    mser: tuple[Arr, ...] | None,
    times: Arr,
    ego_cfg: dict[str, Any],
    hfov_deg: float,
) -> dict[str, Any] | None:
    """v26.2.11: everything the device sensors (GoPro GPMF, ``sensors.py``) give the pass, on the motion track's time
    base ``mt`` (the motion track's own times; the analysed frame times when the run has none). None without usable
    sensors.

    Keys: mt; cad (accelerometer step cadence, Hz or nan); stat_imu (accel + gyro quiet); heading_imu (gyro heading,
    deg, 0 at the start);
    heading_gps (the same pulled toward the GPS course); info {biasDegPerS, biasSource, gps updates}.
    ``stationary`` for the bias is the final stationary series (computed by the caller through
    ``select_stationary``)."""
    if not sens or "gyro" not in sens or "accl" not in sens:
        return None
    mt = np.asarray(mser[0] if mser is not None else times, dtype=float)
    if len(mt) < 2:
        return None
    s = imu.crop(sens, float(mt[0]) - 6.0, float(mt[-1]) + 6.0)
    if len(s.get("gyro_t", ())) < 200 or len(s.get("accl_t", ())) < 100:
        return None
    icfg = ego_cfg.get("imu") or {}
    out: dict[str, Any] = {"mt": mt, "s": s}
    # stationary: accelerometer + gyro activity, on a 10 Hz grid
    et, en = imu.motion_energy(s, float(icfg.get("activityWindowS", 1.0)))
    tu = np.arange(mt[0], mt[-1] + 0.05, 0.1)
    st_cfg = {**IMU_STATIONARY_DEFAULT, **(icfg.get("stationary") or {})}
    out["stat_imu"] = estimate_stationary(tu, np.interp(tu, et, en), st_cfg)[nearest(tu, mt)]
    # cadence from the vertical acceleration (same estimator, band and window as the image cadence)
    vt, vert, side = imu.vertical_signals(s, float(icfg.get("cadenceRateHz", 60.0)))
    cad = estimate_cadence(
        vt,
        vert,
        ego_cfg["cadenceWindowSeconds"],
        ego_cfg["cadenceBandHz"],
        ego_cfg["cadenceMinPeakRatio"],
        dx=side,
        min_step_hz=ego_cfg.get("minStepHz", 1.4),
        harmonic_ratio=ego_cfg.get("harmonicMinRatio", 0.25),
    )
    out["cad"] = cad[nearest(vt, mt)]
    pt, pitch, roll = imu.gravity_angles(s, {**icfg, "gravityTauS": ego_cfg.get("gravityTauS", 0.5)})
    out["pitch"], out["roll"] = pitch[nearest(pt, mt)], roll[nearest(pt, mt)]
    return out


def gps_at(s: dict[str, Any], t: float, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """The GPS state at time ``t`` for the ego block: {lat, lon, speedMps, dop, fix, good} (the sample at or just
    before ``t``) or None."""
    if "gps_t" not in s or len(s["gps_t"]) == 0:
        return None
    k = int(np.clip(np.searchsorted(s["gps_t"], t + 1e-9, side="right") - 1, 0, len(s["gps_t"]) - 1))
    if abs(s["gps_t"][k] - t) > 1.5:
        return None
    fix, dop = int(s["gps_fix"][k]), float(s["gps_dop"][k])
    good = fix >= int(cfg.get("minFix", 3)) and dop <= float(cfg.get("maxDop", 2.5)) and bool(cfg.get("enabled", True))
    has = fix >= 2
    return {
        "lat": round(float(s["gps"][k, 0]), 7) if has else None,
        "lon": round(float(s["gps"][k, 1]), 7) if has else None,
        "speedMps": round(float(s["gps"][k, 3]), 2),
        "dop": round(dop, 2),
        "fix": fix,
        "good": good,
    }


def auto_stationary(flow_stat: Arr, imu_stat: Arr) -> tuple[Arr, str]:
    """``ego.stationarySource`` "auto": see the DECISIONS entry of v26.2.11 for the measurement behind the choice."""
    return imu_stat, "imu"


def sensor_heading(sser: dict[str, Any], stat: Arr | None, ego_cfg: dict[str, Any]) -> None:
    """Fill ``sser`` with the gyro heading (bias from the stationary spans of ``stat``) and its GPS-corrected twin."""
    icfg = ego_cfg.get("imu") or {}
    mt = sser["mt"]
    h, info = imu.heading_series(sser["s"], mt, mt if stat is not None else None, stat, icfg)
    sser["heading_imu"], sser["info"] = h, info
    g = ego_cfg.get("gps") or {}
    sser["heading_gps"] = h
    if g.get("enabled", True) and "gps" in sser["s"]:
        off, ginfo = imu.gps_course_offset(sser["s"], mt, h, g)
        sser["heading_gps"] = h + off
        info["gpsUpdates"] = ginfo["updates"]
