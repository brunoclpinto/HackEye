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

# The GPMF parser lives in engine.egosignals.gpmf (v26.3.0 p2-03); the old names stay as the same objects.
from engine.egosignals.gpmf import _FMT as _FMT  # noqa: E402, F401
from engine.egosignals.gpmf import _STREAMS as _STREAMS  # noqa: E402, F401
from engine.egosignals.gpmf import _klv as _klv  # noqa: E402, F401
from engine.egosignals.gpmf import _numbers as _numbers  # noqa: E402, F401
from engine.egosignals.gpmf import parse_payload as parse_payload  # noqa: E402, F401
from engine.egosignals.gpmf import split_payloads as split_payloads  # noqa: E402, F401
from engine.egosignals.gpmf import _gpmd_stream as _gpmd_stream  # noqa: E402, F401
from engine.egosignals.gpmf import _utc_epoch as _utc_epoch  # noqa: E402, F401
from engine.egosignals.gpmf import build as build  # noqa: E402, F401
from engine.egosignals.gpmf import extract as extract  # noqa: E402, F401
from engine.egosignals.gpmf import hilights as hilights  # noqa: E402, F401
from engine.egosignals.gpmf import concat as concat  # noqa: E402, F401
from engine.egosignals.gpmf import save as save  # noqa: E402, F401
from engine.egosignals.gpmf import load as load  # noqa: E402, F401

# The derived IMU / GPS signals live in engine.egosignals.imu (v26.3.0 p2-02); the old names stay as the same objects.
from engine.egosignals.imu import crop  # noqa: E402, F401
from engine.egosignals.imu import default_imu_cfg  # noqa: E402, F401
from engine.egosignals.imu import estimate_bias  # noqa: E402, F401
from engine.egosignals.imu import gps_course_offset  # noqa: E402, F401
from engine.egosignals.imu import gps_good  # noqa: E402, F401
from engine.egosignals.imu import gps_step_length  # noqa: E402, F401
from engine.egosignals.imu import gps_xy  # noqa: E402, F401
from engine.egosignals.imu import gravity_angles  # noqa: E402, F401
from engine.egosignals.imu import gravity_unit  # noqa: E402, F401
from engine.egosignals.imu import heading_series  # noqa: E402, F401
from engine.egosignals.imu import motion_energy  # noqa: E402, F401
from engine.egosignals.imu import smooth as _smooth  # noqa: E402, F401
from engine.egosignals.imu import spans as _spans  # noqa: E402, F401
from engine.egosignals.imu import vertical_signals  # noqa: E402, F401
from engine.egosignals.imu import wrap_deg as _wrap  # noqa: E402, F401
from engine.egosignals.imu import yaw_rate  # noqa: E402, F401
