"""Motion states of a mover: the robust ego speed and the approach / recede / still / side hysteresis."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from engine.core.types import Track

__all__ = ["motion_state", "robust_speed"]


def robust_speed(hist: list[tuple[float, float]], t: float, speed: float, window_s: float) -> float:
    """Median of our cadence-based speed over the last ``window_s`` seconds (``hist`` is updated in place), the speed
    the motion
    states are judged against (v26.1.13, review 6, 374.0 s: a momentary spike of the ego speed (2.07 against 1.1 m/s
    two seconds
    later) turned a closing person into a "standing" one). ``window_s`` <= 0: the speed itself."""
    hist.append((t, speed))
    hist[:] = [h for h in hist if h[0] >= t - window_s - 1e-9] or hist[-1:]
    return float(np.median([h[1] for h in hist]))


def motion_state(
    tr: Track, t: float, along: float, side: float, cross: float | None, roles: dict[str, Any], vehicle: bool = False
) -> str | None:
    """Motion state of a mover from its smoothed own speed along the line of sight (v26.1.12, review 5), with
    hysteresis.

    * ``"side"``: clearly moving sideways (``_sideways_mps``).
    * ``"approach"`` / ``"recede"``: ``along`` >= ``approachingMps`` (0.4) towards / away; kept down to
      ``motionLeaveMps`` (0.3).
    * ``"still"``: ``|along|`` < ``standingMps`` (0.3) held for ``standingHoldSeconds`` (1 s) without a break AND no
      sideways
      motion (``|cross|`` < ``standingMaxCrossMps``); kept while ``|along|`` < ``approachingMps`` and no sideways
      motion.
    * ``None``: anything else: in between, too short a measurement, or a possible sideways motion. The caller says
      the plain
      phrase: a wrong state is worse than none (review 5: a person walking left was "standing", a person walking away
      at 0.6 m/s was "standing")."""
    prev = tr.mstate
    enter, leave = roles.get("approachingMps", 0.4), roles.get("motionLeaveMps", 0.3)
    if vehicle and "vehicleApproachingMps" in roles:
        # v26.1.16 (review 8, 52.2 s: a parked car was "approaching"): the along speed of a car is measured from the
        # contact row of a big,
        # fragmenting component and reads 1-3 m/s off for a parked one in a row of cars (1.0 for the one called
        # approaching, 3.0 for its
        # neighbour); a car that really approaches closes at 4+ m/s. Cyclists keep the person levels: their early
        # warning is wanted
        enter = float(roles["vehicleApproachingMps"])
        leave = 0.7 * enter
    still_max, hold = roles.get("standingMps", 0.3), roles.get("standingHoldSeconds", 1.0)
    cross_max = roles.get("standingMaxCrossMps", 0.6)
    sideways = cross is not None and abs(cross) >= cross_max
    if side != 0.0:
        tr.still_t0 = None
        return "side"
    if along >= enter or (prev == "approach" and along >= leave):
        tr.still_t0 = None
        return "approach"
    if along <= -enter or (prev == "recede" and along <= -leave):
        tr.still_t0 = None
        return "recede"
    if sideways or abs(along) >= (enter if prev == "still" else still_max):
        tr.still_t0 = None
        return None
    if tr.still_t0 is None:
        tr.still_t0 = t
    return "still" if (prev == "still" or t - tr.still_t0 >= hold - 1e-9) else None
