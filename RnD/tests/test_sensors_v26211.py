"""v26.2.11 device sensors (src/sensors.py) and their use in the collision pass: GPMF parsing, heading sign / bias, gravity angles, GPS course
correction, the gravity horizon, one pose, and that a pass without sensors is the v26.2.10 one."""
from __future__ import annotations

import copy
import os
import struct
from pathlib import Path

import numpy as np
import pytest

import collision as col
import sensors
from tests import worldtracks_fixtures as wf


# --------------------------------------------------------------------------------------------------------------------------
# GPMF parser on a synthetic blob
# --------------------------------------------------------------------------------------------------------------------------

def _klv(key: bytes, typ: bytes, size: int, rep: int, body: bytes) -> bytes:
    pad = (-len(body)) % 4
    return key + typ + bytes([size]) + struct.pack(">H", rep) + body + b"\0" * pad


def _devc(gyro_rows, accl_rows, fix=3, dop=150) -> bytes:
    g = b"".join(struct.pack(">hhh", *r) for r in gyro_rows)
    a = b"".join(struct.pack(">hhh", *r) for r in accl_rows)
    gps = b"".join(struct.pack(">lllll", *r) for r in [(413628997, -87580331, 58243, 1500, 160)] * 3)
    strm_g = _klv(b"SCAL", b"s", 2, 1, struct.pack(">h", 100)) + _klv(b"GYRO", b"s", 6, len(gyro_rows), g)
    strm_a = _klv(b"SCAL", b"s", 2, 1, struct.pack(">h", 10)) + _klv(b"ACCL", b"s", 6, len(accl_rows), a)
    strm_p = (_klv(b"SCAL", b"l", 4, 5, struct.pack(">lllll", 10000000, 10000000, 1000, 1000, 100)) + _klv(b"GPSF", b"L", 4, 1, struct.pack(">L", fix))
              + _klv(b"GPSP", b"S", 2, 1, struct.pack(">H", dop)) + _klv(b"GPSU", b"c", 16, 1, b"261104091522.000")
              + _klv(b"GPS5", b"l", 20, 3, gps))
    body = b"".join(b"STRM" + b"\0" + bytes([1]) + struct.pack(">H", len(s)) + s for s in (strm_g, strm_a, strm_p))
    return b"DEVC" + b"\0" + bytes([1]) + struct.pack(">H", len(body)) + body


def test_parser_scales_and_orders_channels():
    p = _devc([(100, 200, -300), (50, 0, 0)], [(98, -3, 7), (98, 0, 0), (98, 0, 0), (98, 0, 0)])
    got = sensors.parse_payload(p)
    assert np.allclose(got["GYRO"]["data"], [[1.0, 2.0, -3.0], [0.5, 0.0, 0.0]])
    assert got["ACCL"]["data"].shape == (4, 3) and np.isclose(got["ACCL"]["data"][0, 0], 9.8)
    g5 = got["GPS5"]
    assert g5["fix"] == 3 and g5["dop"] == 1.5 and np.allclose(g5["data"][0], [41.3628997, -8.7580331, 58.243, 1.5, 1.6])
    assert g5["utc"].startswith("261104091522")


def test_build_spreads_samples_over_the_payload_and_splits_payloads():
    p1 = _devc([(0, 0, 0)] * 4, [(98, 0, 0)] * 2)
    p2 = _devc([(0, 0, 0)] * 4, [(98, 0, 0)] * 2, fix=0, dop=9999)
    raw = p1 + p2
    parts = sensors.split_payloads(raw)
    assert parts == [p1, p2]
    out = sensors.build(parts, [(0.0, 1.0), (1.0, 1.0)])
    assert np.allclose(out["gyro_t"][:4], [0.125, 0.375, 0.625, 0.875]) and len(out["gyro"]) == 8
    assert out["gps_fix"].tolist() == [3, 3, 3, 0, 0, 0] and np.isclose(out["gps_dop"][-1], 99.99)
    assert np.isclose(out["gps_utc"][0] - out["gps_utc"][0], 0.0) and np.isfinite(out["gps_utc"][0])


MEDIA = Path(os.environ.get("HACKEYE_MEDIA_DIR", "/media")) / "Chest-center-0004.MP4"


@pytest.mark.skipif(not MEDIA.exists(), reason="media not mounted")
def test_real_stream_rates_and_gravity():
    s = sensors.extract(str(MEDIA))
    assert s is not None
    dur = s["gyro_t"][-1]
    assert 380 < len(s["gyro"]) / dur < 410 and 190 < len(s["accl"]) / dur < 205 and dur > 450
    assert abs(np.linalg.norm(s["accl"], axis=1).mean() - 9.8) < 0.5          # m/s2: gravity
    assert np.unique(s["gps_fix"]).tolist() == [0, 2, 3]
    assert sensors.hilights(str(MEDIA)) == []


# --------------------------------------------------------------------------------------------------------------------------
# heading, bias, gravity angles
# --------------------------------------------------------------------------------------------------------------------------

def _synthetic(rate_deg_s, bias_deg_s=0.0, seconds=20.0, hz=200.0, pitch_deg=0.0, roll_deg=0.0):
    """Camera upright (gravity on accel channel 0), turning with ``rate_deg_s`` (+ = right turn); gyro channel 0 = rotation about up, ccw +."""
    t = np.arange(0, seconds, 1.0 / hz)
    r = np.radians(rate_deg_s) * np.ones_like(t) if np.isscalar(rate_deg_s) else np.radians(rate_deg_s(t))
    gyro = np.zeros((len(t), 3))
    gyro[:, 0] = -r + np.radians(bias_deg_s)             # the sensor's bias adds to the stored channel
    g = 9.81
    up = g * np.cos(np.radians(pitch_deg)) * np.cos(np.radians(roll_deg))
    acc = np.tile([up, -g * np.sin(np.radians(roll_deg)), -g * np.sin(np.radians(pitch_deg))], (len(t), 1))      # channel 1 reads -g sin(roll) when the right side is down (rollSign -1)
    return {"gyro_t": t, "gyro": gyro, "accl_t": t, "accl": acc}


def test_heading_sign_right_turn_is_positive_and_magnitude():
    """3 s standing (the bias reference), then a 10 deg/s turn: right = positive, ~ 10 deg/s x elapsed turn time."""
    st_t = np.arange(0, 3.0, 0.1)
    s = _synthetic(lambda t: np.where(t > 3.0, 10.0, 0.0), seconds=10.0)
    h, info = sensors.heading_series(s, [0.0, 8.0, 9.9], st_t, np.ones(len(st_t), bool))
    assert h[0] == 0.0 and 49.0 < h[1] < 51.0 and 68.0 < h[2] < 70.5
    s = _synthetic(lambda t: np.where(t > 3.0, -10.0, 0.0), seconds=10.0)
    assert sensors.heading_series(s, [0.0, 9.9], st_t, np.ones(len(st_t), bool))[0][1] < -68.0       # left turn: negative, as the flow heading


def test_bias_removed_from_stationary_spans():
    s = _synthetic(0.0, bias_deg_s=0.5, seconds=30.0)
    t = s["gyro_t"]
    # rate 0.5 deg/s apparent (the sign of the bias term in _synthetic is irrelevant: the estimate removes whatever the quiet span reads)
    naive = np.degrees(np.cumsum(sensors.yaw_rate(s)[1]) * (t[1] - t[0]))[-1]
    assert abs(naive) > 10.0                                     # uncorrected the bias integrates to 15 deg
    stat_t = np.arange(0, 30, 0.1)
    h, info = sensors.heading_series(s, [0.0, 29.9], stat_t, np.ones(len(stat_t), bool))
    assert info["biasSource"] == "stationary" and abs(h[1]) < 0.5
    # no stationary spans: the lowest-|rate| fifth of the clip gives the bias (a turn in the middle is kept)
    s2 = _synthetic(lambda t: np.where((t > 10) & (t < 15), 20.0, 0.0), bias_deg_s=0.5, seconds=30.0)
    h2, info2 = sensors.heading_series(s2, [0.0, 29.9])
    assert info2["biasSource"] == "lowest" and 95.0 < abs(h2[1]) < 105.0


def test_gravity_pitch_and_roll_signs():
    for pitch, roll in ((0, 0), (10, 0), (-10, 0), (0, 6), (0, -6)):
        s = _synthetic(0.0, pitch_deg=pitch, roll_deg=roll, seconds=2.0)
        _, p, r = sensors.gravity_angles(s)
        assert abs(p[-1] - pitch) < 0.3 and abs(r[-1] - roll) < 0.3       # + pitch = looking up: accel channel 2 then reads -g sin(pitch) (+ when the lens looks down)


def test_horizon_from_gravity_moves_with_pitch_and_keeps_the_image_level():
    hg = col.HorizonGravity({"levelTauS": 30.0, "gravityWeight": 0.5}, 135, 240, 118.0, "fisheye")
    assert abs(hg.update(0.0, 4.0, 0.46, "gravity") - 0.46) < 1e-9            # the first sample sets the level
    up = hg.update(0.2, 9.0, 0.46, "gravity")                                  # looking 5 deg higher: the horizon is lower in the image
    assert up > 0.46 + 0.02
    fused = hg.update(0.4, 9.0, 0.46, "fused")                                 # the image says 0.46, gravity says lower: in between
    assert 0.46 < fused < hg.update(0.6, 9.0, 0.46, "gravity")


def test_gps_course_correction_removes_a_heading_drift():
    t = np.arange(0, 120, 1.0 / 18.0)
    n = len(t)
    east = np.cumsum(np.ones(n) * 1.4 / 18.0)                                   # walking due east: course 90 deg
    lat0, lon0 = 41.0, -8.0
    s = {"gps": np.column_stack([np.full(n, lat0), lon0 + east / (111320 * np.cos(np.radians(lat0))), np.zeros(n), np.full(n, 1.4), np.full(n, 1.4)]),
         "gps_t": t, "gps_fix": np.full(n, 3), "gps_dop": np.full(n, 1.0), "gps_utc": np.zeros(n)}
    ht = np.arange(0, 120, 0.1)
    heading = 0.3 * ht                                                         # the gyro drifts 0.3 deg/s while walking straight
    off, info = sensors.gps_course_offset(s, ht, heading, {"courseTauS": 20.0})
    fixed = heading + off
    assert info["updates"] > 30
    assert np.ptp(fixed[ht > 60]) < 0.5 * np.ptp(heading[ht > 60])              # the trend is cut by more than half
    # a bad DOP gives no correction at all
    s["gps_dop"] = np.full(n, 6.0)
    assert not np.any(sensors.gps_course_offset(s, ht, heading, {})[0])


# --------------------------------------------------------------------------------------------------------------------------
# the pass
# --------------------------------------------------------------------------------------------------------------------------

def _fixture_inputs(name="chest0004_review8"):
    import json
    meta = json.load(open(wf.FIXTURES / f"{name}.json"))
    npz = np.load(wf.FIXTURES / f"{name}.npz")
    return meta, npz


def _synthetic_sensors(seconds: float, turn_deg_s: float = 0.0):
    s = _synthetic(turn_deg_s, seconds=seconds, hz=100.0)
    t = s["accl_t"]
    # a 2 Hz step bob on the vertical axis
    s["accl"] = s["accl"] + np.column_stack([np.sin(2 * np.pi * 2.0 * t) * 3.0, np.zeros_like(t), np.zeros_like(t)])
    return s


def test_sensors_off_switch_equals_no_sensors():
    meta, npz = _fixture_inputs()
    keep = npz["w0_t"] <= 45.0                                     # the first 45 s keep the test short
    keep_m = npz["w0_mt"] <= 45.0
    t = npz["w0_t"][keep]
    s = _synthetic_sensors(float(t[-1]) + 10.0)
    cfg = copy.deepcopy(col.load_config())
    sett = meta["settings"]
    settings = col.resolve_settings(cfg, sett["mount"], sett["hfovDeg"], sett["cameraHeightM"], sett["stepLengthM"], projection=sett.get("projection"),
                                    distance_source=sett.get("distanceSource", "ground"), user_height_m=sett.get("userHeightM"),
                                    camera_location=sett.get("cameraLocation"), camera_side=sett.get("cameraSide"), object_distance="depth")
    motion = {"t": npz["w0_mt"][keep_m], "dx": npz["w0_mdx"][keep_m], "dy": npz["w0_mdy"][keep_m]}
    if "w0_mresid" in npz.files:
        motion["resid"] = npz["w0_mresid"][keep_m]
    dm = meta["depth"]
    depth = {"t": t, "depth": npz["w0_depth"][keep], "units": dm["units"], "anchor": dm["anchor"]}
    args = (npz["w0_grids"][keep], t, meta["classNames"])
    base = col.run_collision(*args, cfg, settings, motion, depth)
    cfg2 = copy.deepcopy(cfg)
    cfg2["ego"]["sensors"] = False
    off = col.run_collision(*args, cfg2, settings, motion, depth, sensors=s)
    assert wf.events_hash(base[1]) == wf.events_hash(off[1]) and wf.hazards_hash(base[0]) == wf.hazards_hash(off[0])
    on = col.run_collision(*args, cfg, settings, motion, depth, sensors=s)
    h = on[0]
    assert h["settings"]["headingSource"] in ("imu", "imu+gps") and h["settings"]["cadenceSource"] == "imu"
    e = h["frames"][5]["ego"]
    assert "pitchDeg" in e and "rollDeg" in e and "gps" in e
    assert all(abs(f["ego"]["headingDeg"]) < 1.0 for f in h["frames"] if f["ego"]["headingDeg"] is not None)      # straight synthetic walk: gyro heading flat


def test_one_pose_world_memory_takes_the_map_pose():
    wm = col._WorldMemory({"enabled": True})
    wm.advance(0.0, 0.0, 1.4, 0.0)
    wm.advance(0.2, 0.2, 1.4, 10.0)
    assert (wm.x, wm.y) != (0.0, 0.0)
    wm.advance(0.4, 0.2, 1.4, 12.0, (5.0, 6.0, 33.0))
    assert (wm.x, wm.y, wm.theta) == (5.0, 6.0, 33.0)
    it = col._Item.__new__(col._Item)
    it.distance_m, it.lateral_m = 10.0, 0.0
    x, y = wm.locate(it)
    assert abs(x - (5.0 + 10.0 * np.sin(np.radians(33.0)))) < 1e-9 and abs(y - (6.0 + 10.0 * np.cos(np.radians(33.0)))) < 1e-9


def test_gps_speed_scale_follows_gps_after_enough_good_moving_frames():
    g = col.GpsSpeedScale({"speedMinS": 20.0, "speedTauS": 5.0})
    ks = [g.update(0.2 * i, 1.7, 1.5) for i in range(300)]
    assert ks[50] == 1.0                                       # < 20 s of samples: no change yet
    assert abs(ks[-1] - 1.7 / 1.5) < 0.02
    g2 = col.GpsSpeedScale({"speedMinS": 20.0, "speedTauS": 5.0})
    assert all(g2.update(0.2 * i, None, 1.5) == 1.0 for i in range(300))     # no good fix: never


def test_roll_is_undone_by_the_ground_geometry_and_the_inverse_agrees():
    import groundfuse as gf
    geo = gf.Geometry(135, 240, 118.0, "fisheye", 1.3)
    f0, r0 = gf.ground_point(geo, 100.0, 120.0, 0.46)
    assert abs(r0) < 1e-6                                       # centre column: straight ahead
    geo.roll = np.radians(5.0)                                  # right side down: the level camera sees this pixel off to one side
    f1, r1 = gf.ground_point(geo, 100.0, 120.0, 0.46)
    assert r1 < -0.05 and abs(f1 - f0) < 0.1 * f0
    row, colm = gf.ground_pixel(geo, f1, r1, 0.46)
    assert abs(row - 100.0) < 1e-6 and abs(colm - 120.0) < 1e-6                 # exact inverse
    geo.roll = 0.0
    assert gf.ground_point(geo, 100.0, 120.0, 0.46)[0] == f0
