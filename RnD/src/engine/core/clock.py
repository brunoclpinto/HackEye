"""Clock-position and bearing helpers: pixel column -> bearing -> spoken clock quarter, and stereo pan."""

from __future__ import annotations

import math

__all__ = [
    "bearing_deg",
    "clock_from_bearing",
    "clock_quarter",
    "clock_text",
    "pan_from_bearing",
    "quarter_of_hour",
]


def bearing_deg(x_norm: float, hfov_deg: float, projection: str = "rectilinear") -> float:
    """Bearing, positive = right. Rectilinear (pinhole): atan((x - 0.5) * 2 * tan(hfov / 2));
    fisheye (equidistant): (x - 0.5) * hfov."""
    if projection == "fisheye":
        return (x_norm - 0.5) * hfov_deg
    t = math.tan(math.radians(hfov_deg) / 2.0)
    return math.degrees(math.atan((x_norm - 0.5) * 2.0 * t))


def clock_from_bearing(bearing: float) -> int:
    """12 + round(bearing / 30), clamped to +-90 deg, as 9..12 and 1..3."""
    b = max(-90.0, min(90.0, bearing))
    k = int(math.floor(b / 30.0 + 0.5))  # noqa: RUF046
    if k == 0:
        return 12
    return 12 + k if k < 0 else k


def clock_quarter(bearing: float) -> int:
    """Quarter-hour clock index: round(bearing / 7.5), half away from zero, clamped to +-12 (+-90 deg)."""
    v = bearing / 7.5
    q = int(math.floor(abs(v) + 0.5))  # noqa: RUF046
    q = -q if v < 0 else q
    return max(-12, min(12, q))


def clock_text(q: int) -> str:
    """Spoken clock position of quarter index ``q`` (0 = "12", 1 = "12:15", -1 = "11:45", 4 = "1", -12 = "9")."""
    m = (720 + 15 * int(q)) % 720
    hour = m // 60 or 12
    minutes = m % 60
    return f"{hour}" if minutes == 0 else f"{hour}:{minutes:02d}"


def quarter_of_hour(clock: int) -> int:
    """Quarter index of a whole clock hour (12 -> 0, 1 -> 4, 11 -> -4)."""
    return 0 if clock == 12 else 4 * clock if clock <= 3 else 4 * (clock - 12)


def pan_from_bearing(bearing: float) -> float:
    return max(-1.0, min(1.0, math.sin(math.radians(bearing))))
