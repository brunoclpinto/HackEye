"""The frame pipeline driver: ``run_collision`` (moved verbatim from collision.py; v26.3.0 p4-02)."""

# ruff: noqa: E501
# mypy: ignore-errors
# (the body is untyped legacy code; p4-06 removes this ignore)
from __future__ import annotations

import math
import time

import numpy as np

from engine.core.clock import (
    bearing_deg,
)
from engine.core.geom import (
    round_opt as _r,
)
from engine.core.geom import (
    steps_to,
)
from engine.core.log import (
    log as _log,
)
from engine.depthscale.scale import (
    DepthScale as _DepthScale,
)
from engine.motion.state import (
    motion_state as _motion_state,
)
from engine.output.hazards import (
    hazard_json as _hazard_json,
)
from engine.output.hazards import (
    lane_polygon as _lane_polygon,
)
from engine.output.hazards import (
    region_rows as _region_rows,
)
from engine.pipeline.glue import (
    LAST_WORLD_TRACKS_MS,
)
from engine.pipeline.glue import (
    bottom_distance as _bottom_distance,
)
from engine.pipeline.glue import (
    hidden_fn as _hidden_fn,
)
from engine.pipeline.glue import (
    predict_velocities as _predict_velocities,
)
from engine.pipeline.stages import (
    depthscale,
    depthscale_report,
    detection,
    egosignals_lookup,
    egostate,
    setup,
    surface_crosswalk,
    surface_horizon,
    surface_region,
    tracking,
    tracking_coast,
    tracking_jump,
    worldmap_step,
)
from engine.pipeline.state import FrameState, RunState
from engine.roles.roles import (
    assign_role as _assign_role,
)
from engine.roles.roles import (
    is_static_like as _is_static_like,
)
from engine.roles.roles import (
    not_approaching as _not_approaching,
)
from engine.roles.roles import (
    sideways_mps as _sideways_mps,
)
from engine.roles.roles import (
    speed_witness as _speed_witness,
)
from engine.sounds.tones import (
    resolve_sounds,
)
from engine.sounds.tones import (
    tone_events as _tone_events,
)
from engine.speech.walls import (
    followed_wall as _followed_wall,
)
from engine.speech.walls import (
    passing_close as _passing_close,
)
from engine.tracking.velocity import (
    cross_velocity as _cross_velocity,
)
from engine.tracking.velocity import (
    lateral_velocity as _lateral_velocity,
)
from engine.worldmap.staticmap import (
    mute_solid as _mute_solid,
)


def run_collision(
    grids,
    times,
    class_names,
    config,
    settings,
    motion=None,
    depth=None,
    window=None,
    sounds=None,
    worldmap_config=None,
    progress=None,
    sensors=None,
) -> tuple[dict, dict]:
    """Per-frame hazards and the speech/tone event list. ``motion`` = {"t","dx","dy"} arrays or None.

    ``sensors`` (v26.2.11): the recording's device telemetry (``sensors.extract``, on the recording's time line) or None; with it the heading
    comes from the gyro (``ego.headingSource``), the cadence / stationary from the accelerometer, and the ego block gains the gravity pitch /
    roll and the GPS fix. Without it the pass is exactly the v26.2.10 one.

    ``sounds`` (v26.1.16): the Lab's sound profile ({"kinds": {...}, "speechRate"}, see ``resolve_sounds``) or None = the defaults of
    ``collision.json`` ``tones``; it sets the pitch, duration and repeat interval of the tone events.

    ``window`` (None = the grids cover the whole frame) = {"c0", "cols", "x0", "y0", "w", "h", "srcW", "srcH"}: the grids
    always span the FULL frame (bearings, focal length, principal point, seed box, horizon stay those of the source lens);
    cells outside the analysed window hold ``NO_DATA`` and the depth maps are NaN there. Only the horizon fit needs to
    know the window edges (they are crops, not path edges), and the output records the window.

    ``depth`` = {"t": (N,), "depth": (N, Dh, Dw), "units": "metric" | "relative",
    optional "anchor": "per-frame" | "initial" | "none"} or None (anchor default: per-frame for relative, none for metric): one depth map per
    analysed frame (nearest ``t``); missing units = metric (metres). Relative depth (scale only, drifting per
    frame) is anchored every frame on the ground under our feet (``_DepthAnchor``) and levelled by walking
    (``_DepthScale``, ground k until its first estimate); with no anchor ``depthM`` is null. It is always reported as ``depthM``; it drives the distances only when
    ``settings.distance_source`` is "depth"."""
    s = RunState()
    setup(
        grids,
        times,
        class_names,
        config,
        settings,
        motion,
        depth,
        window,
        sounds,
        worldmap_config,
        progress,
        sensors,
        s,
    )

    for i in range(s.n):
        f = FrameState()
        f.i = i
        if s.progress is not None:
            s.progress(i, s.n)  # v26.2.10: the Lab's job reports (and may cancel by raising) between frames
        f.t = float(s.times[i])
        f.dt = max(0.0, f.t - s.prev_t)
        s.prev_t = f.t
        f.grid = s.grids[i]

        surface_region(s, f)
        surface_horizon(s, f)
        egosignals_lookup(s, f)
        surface_crosswalk(s, f)
        detection(s, f)
        tracking(s, f)
        depthscale(s, f)
        tracking_jump(s, f)
        egostate(s, f)
        depthscale_report(s, f)
        worldmap_step(s, f)
        tracking_coast(s, f)

        # 6-8. steps, parked vs moving, roles
        f.span = None
        if f.region is not None:
            f.valid = np.flatnonzero(~np.isnan(f.region.left))
            if f.valid.size:
                f.span = (f.valid.min() / s.gh, (f.valid.max() + 1) / s.gh)
        for it in f.items:
            f.tr = s.tracks[it.track_id]
            if it.coasting:
                # v26.2.2: a predicted mover keeps the motion state of its last measurement; only the geometry is new
                it.ego_known, it.ego_settled = f.ego_speed is not None, f.ego_settled
                it.steps = steps_to(it.distance_m, s.step_len)
                _assign_role(it, f.span, s.roles, s.lane_half, s.step_len, f.stationary)
                if f.stationary and not (it.moving is True and it.collision):
                    it.role, it.urgency, it.collision, it.summary_ok, it.proximity = "none", "none", False, False, False
                _mute_solid(it, s.smap)
                continue
            it.moving, it.approaching = (None, False)
            it.ego_known = f.ego_speed is not None
            it.ego_settled = f.ego_settled
            # v26.1.16 (review 8): a rider / vehicle may be called "approaching" on an unsettled ego speed only when it closes faster
            # than we could walk (closing - maxWalkingMps >= approachingMps); else the plain phrase
            it.own_fast = (
                it.fast
                and it.closing is not None
                and it.closing - s.roles.get("maxWalkingMps", 2.0) >= s.roles.get("approachingMps", 0.4)
            )
            if it.clipped:
                f.tr.lhist.clear()
            else:
                f.tr.lhist.append(
                    (
                        f.t,
                        it.lateral_m,
                        it.distance_m,
                        f.heading,
                        bearing_deg((it.bbox[0] + it.bbox[2]) / 2.0, s.settings.hfov_deg, s.projection),
                    )
                )
                f.tr.lhist = [h for h in f.tr.lhist if h[0] >= f.t - s.trk["historySeconds"] - 1e-9]
            it.lat_vel = _lateral_velocity(f.tr.lhist, s.trk["motionMinSeconds"])
            it.cross_mps = _cross_velocity(f.tr.lhist, f.ego_motion, s.roles.get("crossWindowSeconds", 1.0))
            if it.track_motion is not None:  # (source "track") the world track's velocity instead of the image's
                it.lat_vel, it.cross_mps = it.track_motion[1], it.track_motion[2]
            if s.mover.on and it.group == "moving":
                s.mover.observe(it, f.t)
            if it.group == "static" or it.group == "feature":  # noqa: PLR1714
                it.moving = False
            elif it.closing is not None and f.ego_motion is not None:
                # ground velocity: along the line of sight (closing minus our own speed) and, when clearly there, sideways (v26.1.11)
                # v26.1.11: depth closing rates read LOW against the gait (review 4: depthGaitCheck 1.2-1.6, a standing
                # person's closing 0.85 m/s against our 1.4), so a static person looked like one walking away. The
                # witnesses' own level (``gait_check``, the median of walking speed / witness closing rate) puts
                # both on the gait's scale: ``(closing - v / c) * c``; c = 1 without an estimate (cold start, ground source).
                f.c_rate = s.gait_check.value if (s.plane and s.source == "depth" and s.gait_check.value) else 1.0
                f.c_rate = max(0.8, min(2.5, f.c_rate))
                f.along = (it.closing - f.ego_motion / f.c_rate) * f.c_rate
                # v26.1.11: a far person's depth closing swings 1.0 <-> 4.0 m/s from frame to frame (review 4, 87 s: a
                # person walking towards us read "standing"); judged on a smoothed speed (motionSmoothSeconds)
                f.tau = s.roles.get("motionSmoothSeconds", 0.0)
                if it.track_motion is not None:  # (source "track") the world track is a filtered velocity already
                    f.along = f.tr.along_s = it.track_motion[0]
                elif f.tr.along_s is None or f.tau <= 0 or f.t - f.tr.along_t > s.trk["maxMissedSeconds"]:
                    f.tr.along_s = f.along
                else:
                    f.tr.along_s += (1.0 - math.exp(-(f.t - f.tr.along_t) / f.tau)) * (f.along - f.tr.along_s)
                f.tr.along_t = f.t
                f.along = f.tr.along_s
                # v26.1.12 (review 5): three-way with hysteresis, see ``_motion_state``. Standing needs |along| < 0.3 m/s held for 1 s
                # and no sideways motion; approaching / moving away need 0.4 m/s; in between the motion is unknown (None) and the
                # plain phrase is said.
                f.tr.mstate = _motion_state(
                    f.tr, f.t, f.along, _sideways_mps(it, s.roles), it.cross_mps, s.roles, it.class_name == "vehicle"
                )
                it.moving = None if f.tr.mstate is None else f.tr.mstate != "still"
                it.approaching = f.tr.mstate == "approach"
                it.receding = f.tr.mstate == "recede"
            if (
                s.mover.on and it.group == "moving" and it.ego_known
            ):  # v26.2.14: the motion words from the mover's own positions (once our speed has settled)
                s.mover.classify(it, f.t, f.ego_motion if f.ego_motion is not None else f.ego_speed, it.ego_settled)
            f.tr.moving = it.moving
            if s.smap is not None:
                s.smap.snap_solid(it)
            it.steps = steps_to(it.distance_m, s.step_len)
            f.base = s.labels.get(it.class_name, it.class_name.replace("-", " "))
            it.family = f.base
            if it.tree:  # v26.2.12: a trunk in a tree pit: spoken "tree", the family of the vegetation
                f.base = str(s.tree_cfg_run.get("label", "tree"))
                it.family = s.labels.get(s.tree_cfg_run.get("canopyClass", "nature vegetation"), "vegetation")
            it.label = (
                s.parked_labels.get(it.class_name, f.base) if (it.group == "moving" and it.moving is False) else f.base
            )
            if _not_approaching(it, s.ego.speed) and it.group != "moving":
                it.along_path = True
            if it.lane_part and not it.lane_part_weak:
                f.tr.lp_strong_t = f.t
            f.weak_lost = (
                it.lane_part
                and it.lane_part_weak
                and (
                    f.tr.lp_strong_t is None or f.t - f.tr.lp_strong_t > s.roles.get("laneBaseHoldSeconds", 0.0) + 1e-9
                )
            )
            if it.lane_part and (
                f.weak_lost
                or it.closing_raw is None
                or s.ego.speed is None
                or it.closing_raw < s.roles.get("laneBaseMinClosingMps", 0.0)
                or f.t - f.tr.first_t < s.roles.get("laneBaseMinAgeSeconds", 0.0) - 1e-9
            ):
                # v26.1.16 follow-up: a lane part is only believed once it is measured to close on us as we walk (a wall that bends
                # across the camera axis keeps or gains distance: chest0002 51-52 s) and has been tracked for ``laneBaseMinAgeSeconds`` (a
                # burst of a few frames beside a path is segmentation noise: 4929 review 5, 51.0-51.3 s); until then it is no danger
                it.along_path = True
            _assign_role(it, f.span, s.roles, s.lane_half, s.step_len, f.stationary)
            _mute_solid(it, s.smap)
            if it.lane_part and it.role != "danger":
                it.role, it.urgency, it.collision, it.summary_ok = (
                    "none",
                    "none",
                    False,
                    False,
                )  # context is the side wall's job
            if f.stationary and not (it.group == "moving" and it.moving is True and it.collision):
                # v26.1.11: standing still, nothing static is announced and only a mover on a collision course
                # (its own velocity: ours is 0) is a danger
                it.role, it.urgency, it.collision, it.summary_ok, it.proximity = "none", "none", False, False, False
            # v26.1.15 (review 7): no start silence on a prior horizon. Until the horizon has settled (WARMUP_S) it is the
            # mean of the raw estimates, else the mount / body preset; the plain ground-geometry distance serves until the depth
            # anchor has its first plane fit. The 2-frame confirmation stays the minimum.
            if it.role == "feature" and it.lane_hit and not it.along_path:
                f.tr.feature_frames += 1  # it crosses the lane: what a surface change may be backed by
            if (
                it.group == "feature"
                and it.class_name in ("curb", "crosswalk")
                and it.lane_hit
                and it.contact_y * s.gh > s.gh - s.under_rows
                and it.bbox[2] - it.bbox[0] >= s.under_min_w
                and f.tr.feature_frames >= s.policy.confirm
            ):
                # v26.1.11 (review 4, 159.8 s: the wrong "road"): only a curb / crosswalk that crossed the lane for
                # >= confirmFrames frames can go *under* us (a fragment along the path or a flicker cannot); the timing rule
                # of ``_SurfaceTracker`` does the rest
                f.tr.under_last = f.t  # contact in the bottom rows inside the lane: under our feet

        # (v26.2.12) the FINAL distance (after the map / solid snap) jumping is a glitch too: a thin item stays unspoken for ``thinStableS``
        if s.jump_cfg.get("enabled", False):
            for it in f.items:
                if it.coasting or it.ghost:
                    continue
                f.tr = s.tracks[it.track_id]
                f.df, f.df_t = f.tr.df_prev, f.tr.df_prev_t
                f.tr.df_prev, f.tr.df_prev_t = it.distance_m, f.t
                if (
                    f.df is not None
                    and not it.clipped
                    and f.t - f.df_t <= s.jump_cfg.get("maxGapS", 0.4) + 1e-9
                    and min(f.df, it.distance_m) <= float(s.jump_cfg.get("nearM", 1e9))
                    and abs(it.distance_m - f.df)
                    > max(float(s.jump_cfg.get("minM", 1.0)), float(s.jump_cfg.get("frac", 0.4)) * f.df)
                ):
                    f.tr.jump_t = f.t
                it.unstable = (it.thin or it.tree) and f.t - f.tr.jump_t < s.stable_s - 1e-9

        if s.pass_cfg.get("enabled", False) and not f.stationary:
            for it in f.items:
                if _passing_close(it, s.pass_cfg):
                    it.proximity = True

        # confirmation: how many consecutive analysed frames each track has held its role
        f.seen_tracks = set()
        for it in f.items:
            f.tr = s.tracks[it.track_id]
            f.tr.role_run = f.tr.role_run + 1 if f.tr.role == it.role else 1
            f.tr.role = it.role
            f.tr.context_seen = f.tr.context_seen or it.role == "context"
            it.role_run = f.tr.role_run
            f.tr.prox_run = f.tr.prox_run + 1 if it.proximity else 0
            it.prox_run = f.tr.prox_run
            f.seen_tracks.add(it.track_id)
            if it.jumped:
                s.coast.hist.pop(it.track_id, None)  # the glitch is not a position to extrapolate from
            else:
                s.coast.observe(it, f.t, s.world)
        if s.smap is not None:
            for it in f.items:
                if it.group != "static":
                    continue
                f.tr = s.tracks[it.track_id]
                if (
                    s.smap.keeps(it) and it.settled and it.role_run >= s.policy.confirm and not f.stationary
                ):  # a confirmed danger only
                    if it.map_world is None:
                        s.smap.locate(it)
                    f.tr.ghost_src = it
                    f.tr.ghost_t0 = f.t if it.ghost and f.tr.ghost_t0 is None else (f.tr.ghost_t0 if it.ghost else None)
                else:
                    f.tr.ghost_src = f.tr.ghost_t0 = None

        for tid, tr in s.tracks.items():
            if tid not in f.seen_tracks:
                tr.role, tr.role_run, tr.present_run, tr.prox_run = "none", 0, 0, 0
                if tr.under_last is not None and not tr.under_fired and f.t - tr.under_last <= s.under_gone_s + 1e-9:
                    tr.under_fired = True  # a curb / crosswalk edge went under the user and out of view
                    s.surface.note_evidence(f.t)

        # world memory: where are we, and which remembered (announced) object is each item?
        s.world.advance(
            f.t,
            f.dt,
            0.0 if f.stationary else (f.walk_cadence * s.step_len if f.walk_cadence else f.ego_speed),
            f.heading,
            s.smap.pose if (s.one_pose and s.smap is not None) else None,
        )
        s.world.link(f.items, s.tracks, f.t)
        f.wt_out = None
        if s.wtracks.on:
            f._t_wt = time.perf_counter()
            f.wt_out = s.wtracks.step(
                f.t,
                (s.world.x, s.world.y, s.world.theta) if s.world.theta is not None else None,
                [
                    {
                        "tid": it.track_id,
                        "cls": it.class_name,
                        "family": it.family or it.label,
                        "group": it.group,
                        "static": _is_static_like(it),
                        "fwd": it.image_dl[0]
                        if (s.map_mode and it.image_dl)
                        else it.distance_m,  # map mode: the image measurement, not what the track itself placed
                        "right": it.image_dl[1] if (s.map_mode and it.image_dl) else it.lateral_m,
                        "depth": bool(it.from_depth),
                    }
                    for it in f.items
                    if not (it.lane_part or it.ghost or it.coasting)
                ],
                _bottom_distance(
                    s.smap.ob if s.smap is not None else None, s.horizon, s.settings.camera_height_m * f.k, s.gh, s.f
                ),
                _hidden_fn(s.smap.ob if s.smap is not None else None),
            )
            s.wtracks.ms.append((time.perf_counter() - f._t_wt) * 1000.0)
            if s.policy.pred_on and s.world.theta is not None:
                _predict_velocities(f.items, s.wtracks, f.t, math.radians(s.world.theta), s.policy.cfg["predictive"])

        # 9. path change
        f.path_change = f.turned or (
            s.config["pathChange"]["onSurfaceChange"] and f.adopted is not None and f.adopted[0] is not None
        )
        if f.path_change:
            s.policy.clear_context(f.t)
            if s.recalibrate:
                s.anchor.reset()
                if s.plane:
                    s.gait_check = _DepthScale(s.ego_cfg, s.dist_cfg)
                elif s.dscale.freeze:
                    s.dscale = _DepthScale(s.ego_cfg, s.dist_cfg)
                    s.dscale.freeze = True
            _log(f"t={f.t:.1f}s path change ({'turn' if f.turned else 'surface'}); context memory cleared")
        s.policy.observe_context(
            f.t, {it.family or it.label for it in f.items if it.role in ("context", "danger") and _is_static_like(it)}
        )

        # speech
        # context waits for the first surface (up to the old debounce, no longer: the persistence needed
        # to *announce* a surface is longer now, but the scene summary must not wait for it)
        f.surface_known = (
            s.surface.stable is not None or f.t - s.first_t >= s.config["surfaces"]["debounceSeconds"] - 1e-9
        )
        if f.ego_speed is not None:
            s.policy.travel_steps += f.ego_speed * f.dt / s.step_len
        s.policy.stationary = f.stationary
        s.policy.ego_u = f.ego_speed
        if s.wfollow.on:  # v26.2.13: walls the user walks along (no phrase, no new beep episode)
            s.wfollow.advance(f.dt, 0.0 if f.stationary else f.ego_speed)
            s.wfollow.observe(f.t, f.items)
        if (
            s.policy.pred_meas_floor > 0
        ):  # v26.2.12: the speed the static witnesses really close at (over the last measuredWindowS)
            f.w_now = [
                it.closing
                for it in f.items
                if _speed_witness(it) and it.closing is not None and 0.0 <= it.closing <= s.ego_cfg["speedMaxMps"]
            ]
            if f.w_now:
                s.meas_hist.append((f.t, float(np.median(f.w_now))))
            s.meas_hist[:] = [h for h in s.meas_hist if h[0] >= f.t - s.meas_win - 1e-9]
            s.policy.ego_meas = float(np.median([h[1] for h in s.meas_hist])) if len(s.meas_hist) >= 3 else None
        s.policy.observe_movers(f.t, f.items, s.tracks)
        f.speech = s.policy.step(f.t, f.items, s.tracks, f.surface_known)
        if f.speech is None:
            f.speech = s.policy.away_speech(f.t, f.items)  # v26.2.13: a danger that left the lane by its own motion
        if f.speech is None:
            f.speech = s.policy.motion_speech(
                f.t, f.items
            )  # v26.2.14: "cutting in front" / "moving away" ahead, from the person's own velocity
        if f.speech is None and s.policy.quiet_t == f.t:
            s.blk_run = 0
        elif (
            f.speech is None
            and s.blk_cfg.get("enabled", False)
            and s.smap is not None
            and not f.stationary
            and f.ego_speed
            and s.world.theta is not None
        ):
            f.blk = s.smap.blocked_ahead(s.blk_cfg)
            s.blk_run = (
                s.blk_run + 1 if f.blk is not None and f.blk["kind"] == s.blk_kind else (1 if f.blk is not None else 0)
            )  # confirmed as one kind
            s.blk_kind = f.blk["kind"] if f.blk is not None else None
            if f.t - s.blk_seen_t > float(s.blk_cfg.get("clearS", 2.0)):
                s.blk_open = False
            if f.blk is not None:
                s.blk_seen_t = f.t
            if (
                f.blk is not None
                and not s.blk_open
                and f.blk.get("wideOk", True)
                and s.blk_run >= int(s.blk_cfg.get("confirmFrames", 2))
                and f.t - s.blk_last_t >= float(s.blk_cfg.get("cooldownS", 5.0))
                and s.policy._gap_ok(f.t, priority=True)
            ):
                f.th_ = math.radians(s.world.theta)
                f.bx = s.world.x + math.sin(f.th_) * f.blk["cfwd"] + math.cos(f.th_) * f.blk["cright"]
                f.by = s.world.y + math.cos(f.th_) * f.blk["cfwd"] - math.sin(f.th_) * f.blk["cright"]
                if s.blk_pos is None or math.hypot(f.bx - s.blk_pos[0], f.by - s.blk_pos[1]) > float(
                    s.blk_cfg.get("sameSpotM", 3.0)
                ):
                    f.txt = (
                        s.blk_cfg["templates"]["free"].format(
                            label=f.blk["label"], clock=f.blk["blockClock"], free=f.blk["clock"]
                        )
                        if f.blk.get("free")
                        else s.blk_cfg["templates"]["none"].format(label=f.blk["label"], clock=f.blk["blockClock"])
                    )
                    f.speech = s.policy._event(f.t, "feature", f.txt, None)
                    f.speech["blocked"] = {
                        k: f.blk[k]
                        for k in (
                            "kind",
                            "share",
                            "clearM",
                            "bearingDeg",
                            "clock",
                            "blockClock",
                            "endClass",
                            "cfwd",
                            "cright",
                        )
                        if k in f.blk
                    }
                    s.blk_last_t, s.blk_pos, s.blk_open = f.t, (f.bx, f.by), True
        elif f.speech is not None:  # noqa: SIM114
            s.blk_run = 0
        elif s.blk_cfg.get("enabled", False):
            s.blk_run = 0
        if f.speech:
            s.events.append(f.speech)

        f.beeping = [
            it
            for it in f.items
            if it.role == "danger"
            and it.collision
            and it.settled
            and it.role_run >= s.policy.confirm
            and it.steps <= s.config["tones"].get("maxSteps", s.roles["dangerSteps"])
        ]
        if s.wfollow.on:
            for it in f.beeping:  # a wall due a beep, real or quiet, is a wall event (the memory of the quiet rules)
                if it.class_name in s.wfollow.classes and s.wfollow.candidate(f.t, it):
                    s.policy.note_wall(f.t, it)
        if s.follow_cfg.get("enabled", False) and f.beeping:
            f.beeping = [it for it in f.beeping if not _followed_wall(it, f.t, s.follow, s.follow_cfg)]
        if s.wfollow.on and f.beeping:
            f.beeping = [it for it in f.beeping if not s.wfollow.quiet(f.t, it, float(s.follow_cfg.get("gapS", 1.5)))]
        if s.wfollow.on:
            for it in f.beeping:
                if it.class_name in s.wfollow.classes:
                    s.wfollow.beeped(f.t, it)
        # a stream of beeps (>= 2 frames in a row) is danger activity; a single pass-by beep is not (review 8, 6.2 s: the building at 2
        # steps right after the first beep of a passing person was a wanted context phrase)
        s.beep_run = s.beep_run + 1 if f.beeping else 0
        if s.beep_run >= 2:
            s.policy.last_beep_t = f.t
        s.frame_collision.append(
            (min(f.beeping, key=lambda it: it.steps) if f.beeping else None, {it.track_id for it in f.items})
        )
        f.near_soft = [it for it in f.items if it.proximity and it.settled and it.prox_run >= s.policy.confirm]
        s.frame_proximity.append(
            (min(f.near_soft, key=lambda it: it.steps) if f.near_soft else None, {it.track_id for it in f.items})
        )

        f.speed_known = f.ego_speed is not None
        s.frames_out.append(
            {
                "index": i,
                "t": round(f.t, 4),
                "horizonY": round(s.horizon, 4),
                "horizonEstimated": f.raw is not None,
                "region": None
                if f.region is None
                else {"surface": f.region.group, "label": f.region.label, "rows": _region_rows(f.region)},
                "lane": _lane_polygon(f.geo, s.lane_half, s.roles["dangerSteps"] * s.step_len),
                "ego": {
                    "speedMps": _r(f.ego_speed, 2),
                    "cadenceHz": _r(f.cadence, 2),
                    "stepLengthM": round(s.step_len, 2),
                    "headingDeg": _r(f.heading, 1),
                    "stationary": f.stationary,
                    **f.ego_sens,
                    "depthAnchor": _r(f.a_now, 4),
                    "depthAnchorMode": s.anchor_mode,
                    "depthPitchDeg": _r(s.anchor.pitch_deg, 1) if s.plane else None,
                    "depthCameraHeightUnits": _r(s.anchor.height_units, 4) if s.plane else None,
                    "depthGaitCheck": _r(s.gait_check.value, 3) if s.plane else None,
                    "depthScale": f.depth_scale_out,
                    "depthScaleSource": "none" if s.depth_maps is None or f.ds is None else s.depth_scale_source,
                    "depthLevel": None if not s.relative or f.ds is None else _r(f.ds, 4),
                    "depthLevelSource": None if not s.relative or f.ds is None else s.c_source,
                    "scale": round(s.scale.value, 3),
                    "scaleSource": "gait" if s.scale.from_gait else "prior" if s.scale.k is not None else "none",
                    "estimated": {"speed": f.speed_known, "cadence": f.cadence is not None, "stepLength": False},
                },
                "pathChange": bool(f.path_change),
                **({"depthCorrection": f.dc_rep} if f.dc_rep is not None else {}),
                **({"corridor": f.corridor_out} if s.smap is not None else {}),
                **({"faceEdgeLines": s.smap.fe_lines} if s.smap is not None and s.smap.fe_lines else {}),
                **({"worldTracks": f.wt_out} if f.wt_out is not None else {}),
                "hazards": [
                    _hazard_json(it, s.gh, s.gw, s.full_all) for it in sorted(f.items, key=lambda it: it.steps)
                ],
            }
        )

    s.tone_events, s.episodes = _tone_events(
        s.frame_collision,
        s.times,
        s.config["tones"],
        s.frame_proximity,
        s.cw_marks,
        resolve_sounds(s.config["tones"], s.sounds),
    )
    s.events.extend(s.tone_events)
    s.events.extend(s.episodes)
    s.events.sort(key=lambda e: (e["t"], e["type"] != "speech", e["type"] != "beeps"))
    s.version = s.config["version"]
    s.hazards_doc = {
        "version": s.version,
        "projection": s.projection,
        "distanceSource": s.source,
        "settings": {
            "mount": s.settings.mount,
            "hfovDeg": s.settings.hfov_deg,
            "cameraHeightM": s.settings.camera_height_m,
            "laneHalfWidthM": s.lane_half,
            "priorStepLengthM": s.step_len0,
            "stepLengthM": s.step_len0 if s.step_source == "gps" else s.settings.step_length_m,
            "stepLengthSource": s.step_source,
            "gpsStepWindowsS": s.step_windows_s,
            **({"gpsStep": s.step_info} if s.step_info else {}),
            "userHeightM": s.settings.user_height_m,
            "cameraLocation": s.settings.camera_location,
            "cameraSide": s.settings.camera_side,
            "lateralOffsetM": s.lat_off,
            "objectDistance": getattr(s.settings, "object_distance", "depth"),
            "useHorizon": bool(getattr(s.settings, "use_horizon", True)),
        },
        "gridW": s.gw,
        "gridH": s.gh,
        "egoAvailable": s.mser is not None,
        "frames": s.frames_out,
    }
    if s.one_pose and s.smap is not None:
        s.hazards_doc["settings"]["onePose"] = True
    if s.map_mode:
        s.hazards_doc["settings"]["sourceMode"] = "map"
        s.hazards_doc["settings"]["sourceCounts"] = dict(s.src_counts)
    if s.policy.pred_on:
        s.hazards_doc["settings"]["predictive"] = dict(s.policy.pred_stats)
    if s.sser is not None:
        s.hazards_doc["settings"].update(
            {
                "headingSource": s.heading_source,
                "cadenceSource": s.cadence_source,
                "stationarySource": s.stationary_source,
                "horizonSource": s.hz_source,
                "gyroBiasDegPerS": s.sser["info"].get("biasDegPerS"),
                "gyroBiasSource": s.sser["info"].get("biasSource"),
                "gpsUpdates": s.sser["info"].get("gpsUpdates", 0) if s.heading_source == "imu+gps" else 0,
            }
        )
    if s.coast.on:
        for tid in list(s.coast.active):
            s.coast._end(tid, float(s.times[-1]) if s.n else 0.0, "end")
        s.hazards_doc["coast"] = {"episodes": s.coast.episodes}
    if s.wtracks.on:
        s.hazards_doc["worldTracksSettings"] = dict(s.wtracks.cfg)
        LAST_WORLD_TRACKS_MS[:] = s.wtracks.ms
    if s.window is not None:  # absent for full-frame runs (their output is unchanged)
        s.hazards_doc["window"] = dict(s.window)
    return s.hazards_doc, {"version": s.version, "events": s.events}
