"""Role assignment: what each item is to the wearer (danger / context / feature / none), with the predicates behind
it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from engine.core.types import POINT_ASPECT

if TYPE_CHECKING:
    from engine.core.types import Item

__all__ = [
    "assign_role",
    "course",
    "fast_warning",
    "is_static_like",
    "not_approaching",
    "on_collision_course",
    "pole_like",
    "sideways_mps",
    "speed_witness",
]


def speed_witness(it: Item) -> bool:
    """Can this item tell us our own speed? Only something that stands on the ground at a point:
    a pole, sign or lamp (tall and thin). The contact row of a wall, hedge or building is where the
    segmentation happens to end, so its "closing" is mostly zero or random and would drag the median."""
    return it.closing_raw is not None and pole_like(it)


def pole_like(it: Item) -> bool:
    """Static, tall and thin, not clipped, not running along the path (also the depth-scale witnesses)."""
    if it.group != "static" or it.clipped or it.along_path or it.lane_part:
        return False
    w, h = it.bbox[2] - it.bbox[0], it.bbox[3] - it.bbox[1]
    return h >= POINT_ASPECT * w


def is_static_like(it: Item) -> bool:
    """Static things, and vehicles of unknown or measured-stationary motion ("unknown movers count as
    static": they never become "approaching"). People/riders/animals are movers, never
    "stationary" (v26.1.6). Their motion is hard to
    measure from a bobbing chest camera (people waiting at a crossing read as "stationary" at 48 s of the
    review footage while they walked on) and they are the ones that step into the path, so their measured
    motion only decides "approaching" / "receding"."""
    if it.group == "static":
        return True
    if it.group == "moving":
        return False if it.people else it.moving is not True
    return False


def not_approaching(it: Item, ego_speed_raw: float | None) -> bool:
    """A ground object we walk towards closes at our speed. One whose contact row stays put while we
    move is the end of a line running along the path (a median cut into pieces), not an obstacle.
    Both speeds are raw (uncalibrated) model metres per second."""
    return (
        it.closing_raw is not None
        and ego_speed_raw is not None
        and ego_speed_raw >= 0.5
        and it.closing_raw < 0.3 * ego_speed_raw
    )


def sideways_mps(it: Item, roles: dict[str, Any]) -> float:
    """The item's sideways velocity if it is clearly there, else 0 (v26.1.11).

    The lateral-position derivative is a weak measurement here: on review 4 a STANDING pole or building reads
    |v| 0.5 m/s median and 1.4-2.4 m/s at the 90th percentile (contact row and depth noise times the bearing, the chest
    sway), turn-corrected or not. Only a velocity above ``lateralVelDeadbandMps`` (2) counts, so a vehicle crossing the
    crosswalk (5-8 m/s) is seen as the mover it is and a person walking across (1-1.5 m/s) is not guessed at: for them
    the lane rule on the current lateral position applies, as before."""
    v = it.lat_vel
    if v is None or abs(v) < roles.get("lateralVelDeadbandMps", 2.0):
        return 0.0
    cap: float = roles.get("lateralVelMaxMps", 8.0)
    return max(-cap, min(cap, v))


def course(it: Item, roles: dict[str, Any]) -> tuple[float, float] | None:
    """(time to meet, lateral position at the meeting) of a measured mover that is closing, else None (v26.1.11, review
    4).

        ``closing`` is the rate at which the gap shrinks (it already contains our own speed), so we meet at
        ``T = distance / closing``; by then the mover has moved sideways by ``lat_vel * T``. Not closing at
        ``courseMinClosingMps`` (a mover that keeps its distance or walks away) has no meeting. An unmeasured sideways
        velocity
        counts as 0 (see ``sideways_mps``)."""
    c = it.closing
    if c is None or c < roles.get("courseMinClosingMps", 0.2):
        return None
    t_meet = it.distance_m / c
    return t_meet, it.lateral_m + sideways_mps(it, roles) * t_meet


def on_collision_course(it: Item, roles: dict[str, Any]) -> bool:
    """Will this measured mover be in our way when we get there? (v26.1.11; v26.1.13: ``beepLateralM`` is the body
    width)

        Collision course iff the lateral position at the meeting is within ``beepLateralM`` (0.9 m: lane half-width 0.6
        plus the body) and the meeting is not further off than ``courseMaxSeconds`` (a far, slow closing would
        extrapolate a noisy velocity over a long time)."""
    m = course(it, roles)
    return m is not None and m[0] <= roles.get("courseMaxSeconds", 8.0) and abs(m[1]) <= roles.get("beepLateralM", 0.9)


def fast_warning(it: Item, roles: dict[str, Any]) -> bool:
    """A rider / vehicle measured approaching on or near our path is announced as early as possible (v26.1.13, review
    6, 191.5 and
        445.3 s: "warn as soon as possible, the 10-step rule does not apply to cyclists or vehicles on or close to a
        collision course").

        No step limit: it is about to reach us within ``fastWarnSeconds`` (distance / closing) and be inside the walking
        zone (``movingLaneHalfWidthM``) at that moment, up to ``fastWarnMaxM``. A cyclist passing at arm's length
        (1.9 m) counts as near; whether it also beeps is ``on_collision_course``."""
    m = course(it, roles)
    return (
        m is not None
        and not it.receding
        and it.distance_m <= roles.get("fastWarnMaxM", 30.0)
        and m[0] <= roles.get("fastWarnSeconds", 6.0)
        and abs(m[1]) <= roles.get("movingLaneHalfWidthM", 3.0)
    )


def assign_role(
    it: Item,
    span: tuple[float, float] | None,
    roles: dict[str, Any],
    lane_half_m: float,
    step_length_m: float,
    stationary: bool = False,
) -> None:
    danger_steps, final_steps = roles["dangerSteps"], roles["finalSteps"]
    it.role, it.urgency, it.collision, it.summary_ok, it.proximity = "none", "none", False, False, False
    big_enough = it.area_m2 >= roles.get("minObstacleAreaM2", 0.0)  # a 15 px blip 4 m away is segmentation noise
    if is_static_like(it):
        # v26.1.11 (review 4, 39.0 s): a vehicle whose motion is not measured yet (a new track: a moving car
        # re-detected in
        # fragments has no closing speed for ~0.75 s) is no static danger while we CAN measure motion; it waits
        unmeasured_mover = it.group == "moving" and it.moving is None and it.ego_known
        in_lane = it.map_cells > 0 if it.map_judged else (it.lane_hit and not it.along_path) or it.map_cells > 0
        if big_enough and in_lane and it.steps <= danger_steps and not unmeasured_mover:
            it.role, it.collision = "danger", True
        elif (
            it.touches
            and it.distance_m <= roles["contextMaxDistanceM"]
            and it.area_frac >= roles.get("contextMinAreaFraction", 0.0)
            and it.distance_m <= roles.get("contextMaxSteps", 1e9) * step_length_m
        ):
            # v26.1.6: only what is near; things far to the side stay silent, except in the very first
            # scene summary of a run, which names the whole view (the user ticked "building at 2" there)
            # v26.1.13 (review 6, 132.3 / 179.5 s: "not on a collision course"): lateral limit lowered from 3.0 to 2.5
            # m;
            # right under us (``contextNearSteps``) the older 3.0 m still counts (the 59.2 s obstacle at 2.9 m, 2.6
            # steps)
            lat_ok = abs(it.lateral_m) <= roles.get("contextMaxLateralM", 1e9) or (
                it.steps <= roles.get("contextNearSteps", 0.0)
                and abs(it.lateral_m) <= roles.get("contextNearLateralM", 0.0)
            )
            if lat_ok:
                it.role = "context"
            else:
                it.summary_ok = True
    elif it.group == "moving":
        in_span = (
            span is not None and span[0] <= it.contact_y <= span[1] + 1e-9
        ) or it.coasting  # a predicted mover has no image row
        lat = abs(it.lateral_m)
        if it.people:
            in_span = in_span or span is None  # on a crosswalk there is no surface seed, hence no region
        # (as before: only what is near the path NOW; a car crossing in the distance has cleared it by the time we get
        # there)
        now_reach = roles.get("movingLaneHalfWidthM", lane_half_m + 1.0) if it.people else lane_half_m + 1.0
        if it.fast and it.moving is True and in_span and big_enough and lat <= now_reach and fast_warning(it, roles):
            # v26.1.13 (review 6, 191.5 / 445.3 s): a rider / vehicle approaching on or near the path is announced as
            # early as
            # possible, with no step limit; it beeps only on a real collision course
            it.role, it.collision = "danger", on_collision_course(it, roles)
        elif it.people:
            # v26.1.13 (review 6): people are spoken once at ``peopleSpeakMinSteps``..``movingDangerSteps`` (5-10
            # steps), whatever
            # their direction, inside the people zone (``peopleSpeakLateralM``), with the distance; under 5 steps they
            # only
            # beep, and only on a real collision course: |lateral| (standing / unknown) or the predicted |lateral| at
            # the
            # meeting (moving) within ``beepLateralM``. Unknown motion or a measured approach at arm's length no longer
            # beeps.
            if it.moving is True:
                course = (
                    on_collision_course(it, roles) and not it.receding
                ) or it.near_pass  # v26.2.14: or it passes within nearPassM by its own motion
            else:
                course = lat <= roles.get("beepLateralM", lane_half_m)
            near_steps = it.steps < roles.get("peopleSpeakMinSteps", 0.0)
            if big_enough and in_span and it.steps <= roles.get("movingDangerSteps", danger_steps):
                if not near_steps and lat <= roles.get("peopleSpeakLateralM", lane_half_m):
                    it.role, it.collision = "danger", course
                elif near_steps and course:
                    it.role, it.collision, it.speak = (
                        "danger",
                        True,
                        it.near_pass,
                    )  # (a near-pass mover is said as it closes, see SpeechPolicy.step)
            # v26.1.13 follow-up (the user chose "a softer sound for an approaching person nearby"): a person / animal
            # measured
            # approaching, within ``proximitySteps`` and ``proximityLateralM``, not on a collision course: the soft
            # proximity
            # sound. Not a role (speech and context are untouched); riders and vehicles are spoken early and beep on a
            # course.
            if (
                not it.fast
                and big_enough
                and in_span
                and it.moving is True
                and it.approaching
                and not it.receding
                and not course
                and it.steps <= roles.get("proximitySteps", 0.0)
                and lat <= roles.get("proximityLateralM", 0.0)
            ):
                it.proximity = True
    elif it.group == "feature":
        if it.landmark:
            # a landmark (crosswalk) anywhere in or touching the walking region, once, with direction and steps
            if it.touches and not it.clipped and it.steps <= roles.get("landmarkSteps", roles["featureSteps"]):
                it.role = "feature"
        # a feature must cross the lane; a curb or median running along the path is boundary.
        # One already under our feet (touching the bottom edge) is not "ahead".
        elif (
            it.lane_hit
            and not it.along_path
            and not it.clipped
            and it.lane_cover >= roles["featureMinLaneCover"]
            and it.steps <= roles["featureSteps"]
        ):
            it.role = "feature"
    if it.role == "danger":
        # the final call is for a collision course; a person merely beside the path is a plain danger
        it.urgency = "final" if (it.collision and it.steps <= final_steps) else "danger"
