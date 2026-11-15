"""The stage functions of the frame loop: ``setup`` (everything before the loop), stages 1-24 and ``finish`` (v26.3.0 p4-04, p4-05).

Each stage is the verbatim block of ``run_collision`` between two boundaries of audit 3.2, as a function
``(s: RunState, f: FrameState) -> None``; ``STAGES`` lists them in execution order with the ``RunState`` /
``FrameState`` attributes each one reads and writes (derived from its AST; a test keeps the two in step).
"""

# ruff: noqa: E501
# mypy: ignore-errors
# (the bodies are untyped legacy code; p4-06 removes this ignore)
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from engine import worldmap as wmap
from engine.core import distfuse, groundgeom
from engine.core.classes import (
    resolve_class_ids,
)
from engine.core.clock import (
    bearing_deg,
)
from engine.core.geom import (
    Box,
    focal_px,
    steps_to,
)
from engine.core.geom import (
    round_opt as _r,
)
from engine.core.groundgeom import (
    frame_geometry as _frame_geometry,
)
from engine.core.groundgeom import (
    ground_dist as _ground_dist,
)
from engine.core.groundgeom import (
    walking_axis_offset_m as _walking_axis_offset_m,
)
from engine.core.log import (
    log as _log,
)
from engine.core.settings import (
    HORIZON_HOLD_S,
    MIN_TRACK_AGE_S,
    WARMUP_S,
)
from engine.core.types import (
    LANE_PART_ID_BASE,
)
from engine.core.types import (
    Item as _Item,
)
from engine.core.types import (
    Track as _Track,
)
from engine.core.types import (
    trusted_track as _trusted_track,
)
from engine.depthscale.anchors import (
    DepthAnchor as _DepthAnchor,
)
from engine.depthscale.anchors import (
    InitialAnchor as _InitialAnchor,
)
from engine.depthscale.anchors import (
    PlaneAnchor as _PlaneAnchor,
)
from engine.depthscale.anchors import (
    ground_anchor as _ground_anchor,
)
from engine.depthscale.anchors import (
    plane_fit as _plane_fit,
)
from engine.depthscale.scale import (
    DepthScale as _DepthScale,
)
from engine.depthscale.scale import (
    ground_depth_distance as _ground_depth_distance,
)
from engine.depthscale.scale import (
    item_depth_m as _item_depth_m,
)
from engine.detection.items import (
    detect_items,
)
from engine.egosignals import imu
from engine.egosignals.series import (
    auto_stationary as _auto_stationary,
)
from engine.egosignals.series import (
    gps_at as _gps_at,
)
from engine.egosignals.series import (
    motion_series as _motion_series,
)
from engine.egosignals.series import (
    sensor_heading as _sensor_heading,
)
from engine.egosignals.series import (
    sensor_series as _sensor_series,
)
from engine.egostate.ego import (
    Ego as _Ego,
)
from engine.gait.scale import (
    GpsSpeedScale,
)
from engine.gait.scale import (
    Scale as _Scale,
)
from engine.groundfuse import Corrector, HorizonSigma
from engine.memory.world import (
    WorldMemory as _WorldMemory,
)
from engine.motion.own import (
    OwnMotion as _OwnMotion,
)
from engine.motion.state import (
    motion_state as _motion_state,
)
from engine.motion.state import (
    robust_speed as _robust_speed,
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
    pole_like as _pole_like,
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
from engine.speech.policy import (
    SpeechPolicy,
)
from engine.speech.walls import (
    WallFollow as _WallFollow,
)
from engine.speech.walls import (
    followed_wall as _followed_wall,
)
from engine.speech.walls import (
    passing_close as _passing_close,
)
from engine.surface.horizon import (
    HorizonGravity,
    estimate_horizon,
)
from engine.surface.region import (
    smooth_bounds as _smooth_bounds,
)
from engine.surface.region import (
    walking_region,
)
from engine.surface.trackers import (
    CrosswalkTracker as _CrosswalkTracker,
)
from engine.surface.trackers import (
    SurfaceTracker as _SurfaceTracker,
)
from engine.surface.trackers import (
    seed_fraction as _seed_fraction,
)
from engine.tracking.coast import (
    Coast as _Coast,
)
from engine.tracking.match import (
    match as _match,
)
from engine.tracking.velocity import (
    closing_mps as _closing_mps,
)
from engine.tracking.velocity import (
    cross_velocity as _cross_velocity,
)
from engine.tracking.velocity import (
    depth_closing as _depth_closing,
)
from engine.tracking.velocity import (
    lateral_velocity as _lateral_velocity,
)
from engine.worldmap import config as wm_config
from engine.worldmap.source import (
    map_source as _map_source,
)
from engine.worldmap.staticmap import (
    StaticMap as _StaticMap,
)
from engine.worldmap.staticmap import (
    mute_solid as _mute_solid,
)
from engine.worldtracks import tracks as wt_mod

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class Stage:
    """One registered stage: its name, the state attributes it reads / writes, its config section and its function."""

    name: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    config_section: str | None
    fn: Callable[[RunState, FrameState], None]


def setup(
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
) -> RunState:
    """The setup block of ``run_collision`` (everything before the frame loop): builds, fills and returns the run state ``s``."""
    s = RunState()
    s.grids = grids
    s.times = times
    s.class_names = class_names
    s.config = config
    s.settings = settings
    s.motion = motion
    s.depth = depth
    s.window = window
    s.sounds = sounds
    s.worldmap_config = worldmap_config
    s.progress = progress
    s.sensors = sensors
    if s.worldmap_config is None:
        s.worldmap_config = wm_config.default_config_loader()
    s.grids = np.asarray(s.grids)
    s.times = np.asarray(s.times, dtype=float)
    s.n, s.gh, s.gw = s.grids.shape
    s.ids = resolve_class_ids(s.config, s.class_names)
    s.f = focal_px(s.gw, s.settings.hfov_deg)
    s.geo_cfg, s.roles, s.trk = s.config["geometry"], s.config["roles"], s.config["tracking"]
    s.lane_half = s.geo_cfg["laneHalfWidthM"]
    s.labels = s.config.get("spokenLabels", {})
    s.parked_labels = s.config.get("parkedLabels", {})
    s.default_step = s.geo_cfg["defaultStepLengthM"]
    s.lat_off = _walking_axis_offset_m(s.settings)
    s.ego_cfg = s.config["ego"]
    # steps and the gait calibration use this step length: the per-recording value overrides the prior
    s.step_len = (
        s.settings.step_length_m
        if s.settings.step_length_m is not None
        else float(s.ego_cfg.get("priorStepLengthM", s.default_step))
    )
    s.step_len0 = s.step_len
    s.sl_cfg = s.ego_cfg.get("stepLength") or {}
    s.step_source = "user" if getattr(s.settings, "step_length_user", False) else "prior"
    s.step_windows_s = 0.0
    s.step_info = None
    s.gps_cfg = s.ego_cfg.get("gps") or {}
    s.gps_scale = (
        GpsSpeedScale(s.gps_cfg)
        if (
            s.sensors is not None
            and s.ego_cfg.get("sensors", True)
            and s.gps_cfg.get("enabled", True)
            and s.gps_cfg.get("speedScale", False)
        )
        else None
    )

    s.dist_cfg = s.config.get("distance", {})
    # anchor horizon: "estimated" (the frame's smoothed horizon), "fixed" (the mount preset's), or a row fraction
    s._ah = s.dist_cfg.get("anchorHorizon", "estimated")
    s.anchor_horizon = (
        s.settings.horizon_default if s._ah == "fixed" else float(s._ah) if isinstance(s._ah, (int, float)) else None
    )
    s.depth_rows_frac = float(s.dist_cfg.get("depthLowestRowsFrac", 0.25))
    s.source = getattr(s.settings, "distance_source", "ground")
    s.projection = getattr(s.settings, "projection", "rectilinear")
    # Rays for back-projecting depth-model output in the plane fit: "lens" (default, the resolved projection) or
    # "pinhole". Depth models are trained on pinhole images; on 4929 pinhole rays nevertheless fitted worse (level
    # further from the reference, gait check 1.87 vs 1.40), so "lens" stays the default -- see DECISIONS v26.1.10 f-up 5.
    s.depth_rays = "rectilinear" if s.dist_cfg.get("depthRayModel", "lens") == "pinhole" else s.projection
    s.depth_t = s.depth_maps = None
    s.anchor_mode = None
    if s.depth is not None:
        s.anchor_mode = s.depth.get("anchor") or (
            "per-frame" if s.depth.get("units", "metric") == "relative" else "none"
        )
        if s.anchor_mode not in ("per-frame", "initial", "plane", "none"):
            s.anchor_mode = "none"
    s.relative = s.anchor_mode in ("per-frame", "initial", "plane")  # anchored on the ground (else plain metric metres)
    s.plane = s.anchor_mode == "plane"  # scale from the ground plane + camera height; no gait level (gait is a check)
    s.dscale = _DepthScale(s.ego_cfg, s.dist_cfg) if s.relative else None
    s.gait_check = _DepthScale(s.ego_cfg, s.dist_cfg) if s.plane else None
    s.anchor = (
        (
            _PlaneAnchor(s.dist_cfg, s.settings.camera_height_m)
            if s.plane
            else _InitialAnchor(s.dist_cfg)
            if s.anchor_mode == "initial"
            else _DepthAnchor(s.dist_cfg)
        )
        if s.relative
        else None
    )
    # level c (``_DepthScale``): mode "continuous" | "freeze", and the prior used before its first estimate.
    # The prior (number | "ground") only applies to the initial anchor; per-frame depth borrows the ground k.
    s.level_mode = s.dist_cfg.get("depthLevelMode") or s.dist_cfg.get("levelModeByAnchor", {}).get(
        s.anchor_mode, "freeze" if s.anchor_mode == "initial" else "continuous"
    )
    s.level_prior = "ground"
    if s.anchor_mode == "initial":
        s.level_prior = (
            s.settings.depth_level_prior
            if getattr(s.settings, "depth_level_prior", None) is not None
            else s.dist_cfg.get("depthLevelPrior", "ground")
        )
    if s.dscale is not None:
        s.dscale.freeze = s.level_mode == "freeze"
    s.recalibrate = s.anchor_mode in ("initial", "plane") and bool(s.dist_cfg.get("recalibrateOnPathChange", False))
    s.anchor_rows = float(s.trk["motionMinRowsBelowHorizon"])
    # v26.2.3: ground ray + depth (distance.objectDistance / useHorizon); active for depth distances with the horizon on
    s.gd_cfg = distfuse.settings(s.dist_cfg)
    # v26.2.7 (distance.itemLens): "depth" (default) = an item with a depth distance takes its lateral from the lens ray at that distance (the
    # ground-distance fallback, tuned with the gait scale k on the pinhole formulas, stays as it was); "all" = also the ground distance of every
    # contact row through the lens (then k must not absorb the lens factor any more: experiment); "off" = pinhole laterals
    s.item_lens_mode = str(s.dist_cfg.get("itemLens", "depth"))
    s.lens_all = s.item_lens_mode == "all" and s.source == "depth"
    s.item_lens = (
        groundgeom.Geometry(s.gh, s.gw, s.settings.hfov_deg, s.projection, s.settings.camera_height_m)
        if s.projection == "fisheye" and s.item_lens_mode in ("depth", "all")
        else None
    )
    s.obj_mode = distfuse.resolved_mode(
        getattr(s.settings, "object_distance", "depth"), getattr(s.settings, "use_horizon", True)
    )
    s.gd_on = s.source == "depth" and s.depth is not None and s.obj_mode != "depth"
    s.corrector = s.hsig = s.surf_lut = None
    if s.gd_on:
        s.gd_geo = groundgeom.Geometry(s.gh, s.gw, s.settings.hfov_deg, s.projection, s.settings.camera_height_m)
        s.corrector = Corrector(s.gd_cfg, s.gd_geo)
        s.hsig = HorizonSigma(s.gd_cfg, s.gh)
        s.surf_lut = (
            wmap.class_kinds(
                s.worldmap_config if s.worldmap_config is not None else wmap.load_config(), list(s.class_names)
            )
            == wmap.KIND_SURFACE
        )
    if s.depth is not None and len(s.depth["t"]):
        s.depth_t = np.asarray(s.depth["t"], dtype=float)
        s.depth_maps = s.depth["depth"]

    s.win_bounds = (0.0, 1.0)
    if s.window is not None:
        s.win_bounds = (s.window["c0"] / s.gw, (s.window["c0"] + s.window["cols"]) / s.gw)
    s.mser = _motion_series(s.motion, s.settings.hfov_deg, s.ego_cfg)
    s.flow_hcum = None if s.mser is None else s.mser[2]
    s.sser = (
        _sensor_series(s.sensors, s.mser, s.times, s.ego_cfg, s.settings.hfov_deg)
        if (s.sensors is not None and s.ego_cfg.get("sensors", True))
        else None
    )
    s.heading_source = "flow"
    s.cadence_source = "image"
    s.stationary_source = "image"
    if s.sser is not None:
        s.mt_s = s.sser["mt"]
        s.c_src, s.st_src, s.h_src = (
            s.ego_cfg.get(k, "auto") for k in ("cadenceSource", "stationarySource", "headingSource")
        )
        s.flow_stat = None if s.mser is None else s.mser[3]
        s.cad_s = s.sser["cad"] if (s.c_src in ("auto", "imu") or s.mser is None) else s.mser[1]
        s.cadence_source = "imu" if s.cad_s is s.sser["cad"] else "image"
        if s.flow_stat is None or s.st_src == "imu":
            s.stat_s, s.stationary_source = s.sser["stat_imu"], "imu"
        elif s.st_src == "image":
            s.stat_s = s.flow_stat
        elif s.st_src == "both":
            s.stat_s, s.stationary_source = s.flow_stat & s.sser["stat_imu"], "both"
        elif s.st_src == "either":
            s.stat_s, s.stationary_source = s.flow_stat | s.sser["stat_imu"], "either"
        else:  # auto
            s.stat_s, s.stationary_source = _auto_stationary(s.flow_stat, s.sser["stat_imu"])
        _sensor_heading(s.sser, s.stat_s, s.ego_cfg)
        if s.h_src in ("auto", "imu", "gyro"):
            # v26.2.12: "auto" and "imu" are the gyro heading WITH the slow GPS course correction (ego.gps.course) -- the resolved label says
            # "imu+gps" when at least one GPS update was applied; "gyro" is the pure gyro heading (label "imu")
            s.use_gps = (
                s.h_src != "gyro"
                and bool((s.ego_cfg.get("gps") or {}).get("course", True))
                and bool((s.ego_cfg.get("gps") or {}).get("enabled", True))
            )
            s.hcum_s = s.sser["heading_gps"] if s.use_gps else s.sser["heading_imu"]
            s.heading_source = "imu+gps" if s.use_gps and s.sser["info"].get("gpsUpdates") else "imu"
        else:
            s.hcum_s = s.flow_hcum if s.flow_hcum is not None else s.sser["heading_imu"]
        s.mser = (s.mt_s, s.cad_s, s.hcum_s, s.stat_s)
        # v26.2.12 (O18): the step length from the GPS (median of GPS speed / step cadence over the moving, good-fix samples); a typed one wins
        if s.sl_cfg.get("source", "auto") == "auto" and not getattr(s.settings, "step_length_user", False):
            s.gst = imu.gps_step_length(
                s.sser["s"], s.mt_s, s.cad_s, s.stat_s, {**(s.ego_cfg.get("gps") or {}), **s.sl_cfg}
            )
            if s.gst is not None:
                s.step_len = s.step_len0 = s.gst["stepM"]
                s.gps_scale = None  # the slow GPS speed scale would count the same correction twice
                s.step_source, s.step_windows_s = "gps", round(s.gst["windowsS"], 1)
                s.step_info = {k: round(v, 3) if isinstance(v, float) else v for k, v in s.gst.items()}
    s.ego = _Ego()
    s.surface = _SurfaceTracker(s.config["surfaces"])
    s.crosswalk = _CrosswalkTracker(s.config["crosswalk"])
    s.cw_name = s.config["crosswalk"].get("class", "crosswalk")
    s.cw_class = list(s.class_names).index(s.cw_name) if s.cw_name in s.class_names else None
    s.cw_marks: list[tuple[float, str]] = []
    s.scale = _Scale(s.ego_cfg, s.step_len)
    s.policy = SpeechPolicy(s.config)
    s.world = _WorldMemory(s.config.get("memory", {}), enabled=s.mser is not None)
    s.policy.world = s.world
    s.coast = _Coast(s.config.get("coast", {}))
    s.wtracks = wt_mod.WorldTracks(
        s.config.get("worldTracks"), s.lane_half, s.settings.hfov_deg
    )  # v26.2.9: shadow mode, feeds no decision
    s._op = s.ego_cfg.get(
        "onePose", "auto"
    )  # v26.2.11: the world memory and the world tracks use the online map's corrected pose
    s.one_pose = bool(s.sser is not None) if s._op == "auto" else s._op in ("on", True)
    s.smap = None  # v26.2.1: the online world map the static rules read (roles.staticSource "map")
    if s.roles.get("staticSource", "image") == "map" and s.n:
        s.smap = _StaticMap(
            wmap,
            s.grids,
            s.times,
            s.class_names,
            s.config,
            s.settings,
            s.lat_off,
            s.projection,
            s.source,
            s.lane_half,
            s.step_len,
            s.obj_mode,
            wcfg=s.worldmap_config,
        )
    s.map_ms: list[float] = []
    s.jump_cfg = s.config.get("distance", {}).get("jump") or {}
    s.stable_s = float(s.config["speech"].get("thinStableS", 0.0))
    s.follow_cfg = s.config.get("beeps") or {}
    s.follow: dict = {}  # (family, side) -> {"t": last activity, "t_real": last real beep, "lat": the episode's lateral}
    s.follow_cfg = {**s.follow_cfg, **(s.follow_cfg.get("follow") or {})}
    s.wfollow = _WallFollow(s.follow_cfg)  # v26.2.13: the ratio rule (the distance closes less than the walking speed)
    s.pass_cfg = s.follow_cfg.get("passing") or {}  # v26.2.13: soft beeps for a person passing close
    s.full_all = bool((s.config.get("output") or {}).get("fullAllItems", False))
    s.mover = _OwnMotion(s.config.get("motion") or {})  # v26.2.14: the own velocity of the movers
    s.policy.motion_on = s.mover.on
    s.blk_cfg = s.config.get("blocked") or {}
    s.blk_run, s.blk_last_t, s.blk_pos, s.blk_kind = 0, -math.inf, None, None
    s.blk_seen_t, s.blk_open = (
        -math.inf,
        False,
    )  # follow-up (O26): one phrase per blockage; it ends after clearS s without one
    s.meas_hist: list[tuple[float, float]] = []
    s.meas_win = float((s.config["speech"].get("predictive") or {}).get("measuredWindowS", 1.5))
    s.reset_classes = frozenset(s.jump_cfg.get("resetClasses", ("vehicle", "rider")))
    s.tree_cfg_run = s.config.get("tree") or {}
    s.src_cfg = s.config.get("source") or {}  # v26.2.11: where the items' positions come from
    s.map_mode = str(s.src_cfg.get("mode", "image")) == "map" and s.smap is not None
    s.src_counts = {"map": 0, "track": 0, "image": 0}
    s.policy.speech_rate = resolve_sounds(s.config["tones"], s.sounds)["speechRate"]
    s.under_rows = int(s.config["surfaces"].get("passUnderRows", 6))
    s.under_gone_s = float(s.config["surfaces"].get("passUnderGoneSeconds", 1.5))
    s.under_min_w = float(s.config["surfaces"].get("passUnderMinWidth", 0.15))
    s.tracks: dict[int, _Track] = {}
    s.next_id = 1
    s.next_lane_part_id = (
        LANE_PART_ID_BASE  # lane parts have their own id range: they do not shift the ids of the ordinary tracks
    )
    s.prev_group: str | None = None
    s.prev_left = s.prev_right = None
    s.horizon = s.settings.horizon_default
    s.h_state = s.horizon  # the image horizon estimate's own state (the gravity horizon never feeds back into it)
    s.hz_cfg = s.config.get("horizon") or {}
    s.hz_source = str(s.hz_cfg.get("source", "image")) if s.sser is not None else "image"
    s.hz_off = (
        HorizonGravity(
            {**s.hz_cfg, "horizonValidRange": s.geo_cfg["horizonValidRange"]},
            s.gh,
            s.gw,
            s.settings.hfov_deg,
            s.projection,
        )
        if s.hz_source != "image"
        else None
    )
    s.raws: list[float] = []
    s.last_estimate_t = -math.inf
    s.first_t: float | None = None
    s.frames_out: list[dict] = []
    s.frame_collision: list[tuple[_Item | None, set]] = []
    s.frame_proximity: list[tuple[_Item | None, set]] = []
    s.events: list[dict] = []
    s.prev_t = float(s.times[0]) if s.n else 0.0
    s.beep_run = 0  # consecutive frames with a collision beep driver
    s.people_classes = frozenset(s.config["classes"].get("people", []))
    s.last_hard_pan_t = -math.inf  # the last frame with a hard camera pan (see ``_match`` / ``roles.panSettleSeconds``)
    s.prev_heading: float | None = (
        None  # camera heading of the previous frame: the scene's pan since then moves the tracks' boxes
    )
    s.held_speed: float | None = None  # last cadence-based ego speed and when (v26.1.11, item 7)
    s.held_t = -math.inf
    s.ego_hist: list[
        tuple[float, float]
    ] = []  # recent ego speeds for the robust (median) speed of the motion states (v26.1.13)
    s.ego_hist_t0: float | None = None  # when the current continuous history began (v26.1.15: the window must be full)
    return s


def surface_region(s: RunState, f: FrameState) -> None:
    # 1. walking region (+ debounced surface)
    f.region = walking_region(f.grid, s.ids, s.config)
    f.group = None if f.region is None else f.region.group
    f.adopted = s.surface.update(f.t, f.group)
    if f.adopted is not None:
        s.policy.surface_adopted(f.adopted[0], f.adopted[1], s.config["surfaces"], f.adopted[2])
    if f.group != s.prev_group:
        s.prev_left = s.prev_right = None  # smoothing restarts with a new surface
    s.prev_group = f.group


def surface_horizon(s: RunState, f: FrameState) -> None:
    # 2. horizon, fitted on the raw bounds: averaging a clamped row (0.0) with an
    #    unclamped one would fake an edge and tilt the line
    f.raw = None if f.region is None else estimate_horizon(f.region.left, f.region.right, s.config, s.win_bounds)
    if f.region is not None:
        f.region.left = s.prev_left = _smooth_bounds(s.prev_left, f.region.left)
        f.region.right = s.prev_right = _smooth_bounds(s.prev_right, f.region.right)
    s.first_t = f.t if s.first_t is None else s.first_t
    f.warm = f.t - s.first_t >= WARMUP_S - 1e-9  # until then: the mean of the raw estimates so far
    if f.raw is not None:
        s.raws.append(f.raw)
        s.last_estimate_t = f.t
    s.horizon = s.h_state
    if not f.warm:
        s.horizon = float(np.mean(s.raws)) if s.raws else s.settings.horizon_default
    elif f.raw is None and f.t - s.last_estimate_t <= HORIZON_HOLD_S:
        pass  # a brief failed estimate keeps the last good horizon
    else:
        f.target = s.settings.horizon_default if f.raw is None else f.raw
        f.step = s.geo_cfg["horizonEma"] * (f.target - s.horizon)
        s.horizon += max(-s.geo_cfg["horizonMaxStep"], min(s.geo_cfg["horizonMaxStep"], f.step))
    s.h_state = s.horizon


def egosignals_lookup(s: RunState, f: FrameState) -> None:
    f.cadence = f.heading = f.flow_heading = None
    f.stationary = False
    f.ego_sens: dict = {}
    if s.mser is not None:
        f.mt, f.cad, f.hcum, f.stat = s.mser
        f.j = int(np.clip(np.searchsorted(f.mt, f.t), 0, len(f.mt) - 1))
        if f.j > 0 and abs(f.mt[f.j - 1] - f.t) < abs(f.mt[f.j] - f.t):
            f.j -= 1
        f.cadence = None if np.isnan(f.cad[f.j]) else float(f.cad[f.j])
        f.heading = f.flow_heading = float(np.interp(f.t, f.mt, f.hcum))
        if s.sser is not None and s.flow_hcum is not None:
            f.flow_heading = float(np.interp(f.t, f.mt, s.flow_hcum))  # the image shift the track matching needs
        f.stationary = f.stat is not None and bool(f.stat[f.j])
        if s.sser is not None:
            f.pitch_now, f.roll_now = (
                float(np.interp(f.t, f.mt, s.sser["pitch"])),
                float(np.interp(f.t, f.mt, s.sser["roll"])),
            )
            f.ego_sens = {
                "pitchDeg": _r(f.pitch_now, 2),
                "rollDeg": _r(f.roll_now, 2),
                "gps": _gps_at(s.sser["s"], f.t, s.ego_cfg.get("gps") or {}),
            }
            if s.ego_cfg.get("rollCorrect", False):
                f.ego_sens["rollCorrectDeg"] = _r(
                    f.roll_now, 2
                )  # the roll the ground geometry undoes (items here, the map in worldmap.Observer)
            if s.hz_off is not None:
                s.horizon = s.hz_off.update(f.t, f.pitch_now, s.h_state, s.hz_source)
                f.ego_sens["horizonImageY"] = round(s.h_state, 4)
    f.walk_cadence = None if f.stationary else f.cadence  # a standing user's bob is not a gait
    if s.sser is not None and s.ego_cfg.get("rollCorrect", False):
        f._roll = math.radians(f.ego_sens.get("rollCorrectDeg") or 0.0)
        for _g in (s.item_lens, s.gd_geo if s.gd_on else None):
            if _g is not None:
                _g.roll = f._roll
    if s.gps_scale is not None and s.sser is not None:
        f.g_now = f.ego_sens.get("gps")
        s.step_len = s.step_len0 * s.gps_scale.update(
            f.t,
            f.g_now["speedMps"] if f.g_now and f.g_now["good"] else None,
            f.walk_cadence * s.step_len0 if f.walk_cadence else None,
        )


def surface_crosswalk(s: RunState, f: FrameState) -> None:
    # v26.1.14: stepping onto / off a crosswalk (the crosswalk share under the feet)
    f.cw_change = s.crosswalk.update(
        f.t, _seed_fraction(f.grid, s.cw_class, s.config["surfaces"]["seedBox"]), f.stationary
    )
    if f.cw_change:
        s.cw_marks.append((f.t, f.cw_change))


def detection(s: RunState, f: FrameState) -> None:
    # 3. items
    f.k = s.scale.value  # gait scale from the frames so far: metres are real-world
    f.geo = _frame_geometry(
        s.gh,
        s.gw,
        s.horizon,
        s.settings.camera_height_m * f.k,
        s.f,
        s.settings.hfov_deg,
        s.lane_half,
        f.region,
        s.roles["boundaryMarginPx"],
        s.projection,
        s.lat_off,
        s.lens_all,
    )
    f.dmap = None
    if s.depth_maps is not None:
        f.j = int(np.clip(np.searchsorted(s.depth_t, f.t), 0, len(s.depth_t) - 1))
        if f.j > 0 and abs(s.depth_t[f.j - 1] - f.t) < abs(s.depth_t[f.j] - f.t):
            f.j -= 1
        f.dmap = np.asarray(s.depth_maps[f.j])
    f.items = detect_items(
        f.grid, s.ids, f.geo, s.config, None if s.relative else f.dmap
    )  # v26.2.10: the people split reads metric depth only
    if f.dmap is not None:
        if s.relative:
            f.a_hz = s.anchor_horizon if s.anchor_horizon is not None else s.horizon  # fixed: no horizon jitter
            if s.plane:
                s.anchor.update(
                    _plane_fit(
                        f.region,
                        f.dmap,
                        f.a_hz,
                        s.gh,
                        s.gw,
                        s.f,
                        s.anchor_rows,
                        s.settings.hfov_deg,
                        s.depth_rays,
                        s.dist_cfg,
                    )
                )
            else:
                f.a_raw, f.a_cells = _ground_anchor(
                    f.region, f.dmap, f.a_hz, s.settings.camera_height_m, s.gh, s.gw, s.f, s.anchor_rows
                )
                s.anchor.update(f.t, f.dt, f.a_raw, f.a_cells)
        for it in f.items:
            it.depth_on = True
            it.depth_raw = _item_depth_m(it, f.dmap, s.gh, s.gw, s.depth_rows_frac)


def tracking(s: RunState, f: FrameState) -> None:
    # 4. tracking
    s.tracks = {k: v for k, v in s.tracks.items() if f.t - v.last_t <= s.trk["maxMissedSeconds"]}
    f.pan_shift = 0.0
    if f.flow_heading is not None and s.prev_heading is not None and s.settings.hfov_deg > 0:
        f.pan_shift = max(-0.25, min(0.25, -(f.flow_heading - s.prev_heading) / s.settings.hfov_deg))
    s.prev_heading = f.flow_heading
    if abs(f.pan_shift) >= s.trk.get("panMatchMinShift", math.inf):
        s.last_hard_pan_t = f.t
    f.matches = _match(s.tracks, f.items, f.t, s.trk, f.pan_shift, s.people_classes)
    for ii, it in enumerate(f.items):
        f.tid = f.matches.get(ii)
        if f.tid is None:
            if it.lane_part:
                f.tid, s.next_lane_part_id = s.next_lane_part_id, s.next_lane_part_id + 1
            else:
                f.tid, s.next_id = s.next_id, s.next_id + 1
            s.tracks[f.tid] = _Track(
                f.tid,
                it.group,
                it.class_name,
                Box(*it.bbox),
                f.t,
                f.t,
                it.distance_m,
                it.lateral_m,
                lane_part=it.lane_part,
            )
        f.tr = s.tracks[f.tid]
        f.tr.box, f.tr.last_t, f.tr.last_distance, f.tr.last_lateral = (
            Box(*it.bbox),
            f.t,
            it.distance_m,
            it.lateral_m,
        )
        if it.clipped:  # distance is only a lower bound: no closing from it
            f.tr.history.clear()
        else:
            f.tr.history.append((f.t, it.contact_y_raw))
            f.tr.history = [h for h in f.tr.history if h[0] >= f.t - s.trk["historySeconds"] - 1e-9]
        # v26.1.12 (review 5, 90.8 s): a person's motion is available after ~0.5 s (a person who steps into view close by
        # has no 0.75 s to wait); everything else keeps motionMinSeconds
        f.min_span = (
            s.trk.get("peopleMotionMinSeconds", s.trk["motionMinSeconds"]) if it.people else s.trk["motionMinSeconds"]
        )
        f.raw_closing = _closing_mps(
            f.tr.history,
            s.horizon,
            s.settings.camera_height_m,
            s.gh,
            s.f,
            s.trk["motionMinRowsBelowHorizon"],
            f.min_span,
        )
        f.tr.closing = None if f.raw_closing is None else f.raw_closing * f.k  # same units as the distances
        f.tr.present_run += 1
        # the contact row jumps by a row or two with segmentation noise (up to 20-50 percent of a near
        # item's steps): the distance, lateral and steps are read from a per-track smoothed row
        if it.clipped:
            f.tr.contact_s = None
        else:
            f.a_c = s.trk.get("contactEma", 0.5)
            f.tr.contact_s = (
                it.contact_y if f.tr.contact_s is None else f.a_c * it.contact_y + (1 - f.a_c) * f.tr.contact_s
            )
            f.d_s = _ground_dist(f.geo, f.tr.contact_s, it.base_col)
            if f.d_s is not None and it.distance_m > 0:
                it.lateral_m = (it.lateral_m - s.lat_off) * (f.d_s / it.distance_m) + s.lat_off
                it.distance_m = f.d_s
        if s.relative:  # anchored ground metres (before the level c)
            f.a_t = s.anchor.value
            it.depth_raw = None if (f.a_t is None or it.depth_raw is None) else f.a_t * it.depth_raw
        if it.depth_raw is not None:
            f.tr.dhist.append((f.t, it.depth_raw))  # relative: anchored metres, the level c applies at use
            f.tr.dhist = [h for h in f.tr.dhist if h[0] >= f.t - s.trk["historySeconds"] - 1e-9]
        it.track_id, it.closing_raw, it.closing = f.tid, f.raw_closing, f.tr.closing
        it.present_run = f.tr.present_run
        # v26.1.15 (review 7): during the start warm-up the 2-frame confirmation (roles.confirmFrames) is the only gate
        it.settled = (not f.warm) or f.t - f.tr.first_t >= MIN_TRACK_AGE_S - 1e-9


def depthscale(s: RunState, f: FrameState) -> None:
    # 4b. depth in metres: metric maps as they are; relative maps anchored per frame, levelled by gait
    if s.relative:
        f.wit = []
        for it in f.items:
            if it.depth_raw is not None and _pole_like(it):
                f.r = _depth_closing(s.tracks[it.track_id].dhist, f.t, s.trk["motionMinSeconds"])
                if f.r is not None:
                    f.wit.append((it.bearing, f.r))
        f.prior_c = s.level_prior if isinstance(s.level_prior, (int, float)) else s.scale.value
        if s.plane:
            # the plane scale is final; the gait only checks it (~1 = camera height and walking agree)
            s.gait_check.update(
                f.t, s.gait_check.sample(f.walk_cadence * s.step_len if f.walk_cadence else None, f.wit), f.dt
            )
            f.level, s.c_source, s.depth_scale_source = 1.0, "plane", "plane"
        else:
            s.dscale.update(
                f.t,
                s.dscale.sample(f.walk_cadence * s.step_len if f.walk_cadence else None, f.wit),
                f.dt,
                start=f.prior_c,
            )
            f.level = s.dscale.value
        if s.plane:
            pass
        elif f.level is not None:
            s.c_source = "frozen" if s.dscale.holding else "gait"
            s.depth_scale_source = "gait"
        else:
            f.level = f.prior_c
            s.c_source = "prior" if isinstance(s.level_prior, (int, float)) else "ground"
            s.depth_scale_source = "ground" if s.c_source == "ground" else "prior"
        f.a_now = s.anchor.value
        f.ds = None if f.a_now is None else f.level
    else:
        f.ds, f.a_now, s.c_source, s.depth_scale_source, f.level = 1.0, None, "metric", "metric", None
    f.dc_rep = None
    if s.gd_on:
        f.sig_rows = s.hsig.update(f.t, s.horizon)
        f.sc_total = None if (f.dmap is None or f.ds is None) else (f.ds * f.a_now if s.relative else f.ds)
        # v26.2.7: the walls' bases that stand on a surface calibrate the depth curve where the walking region does not reach
        f.walls = None
        if s.smap is not None and f.dmap is not None and f.sc_total and float(s.gd_cfg.get("wallSampleWeight", 0)) > 0:
            f.walls = wmap.face_contact_samples(s.smap.ob, f.grid, f.dmap, f.sc_total, s.horizon)
        f.dc_rep = s.corrector.update(
            f.t,
            None if f.region is None else f.region.mask,
            f.dmap,
            f.sc_total or 0.0,
            s.horizon,
            f.sig_rows,
            extra=f.walls,
        )
    for it in f.items:
        if it.depth_raw is None or f.ds is None:
            continue
        f.tr = s.tracks[it.track_id]
        it.depth_m = f.ds * it.depth_raw  # metric: ds = 1; relative: depth_raw is anchored, ds the level c
        if s.source == "depth":
            f.d_use = it.depth_m
            if f.dc_rep is not None:  # v26.2.3: range-corrected depth fused with the ground ray of a base on a surface
                f.d_use = _ground_depth_distance(
                    it, f.tr, f.grid, s.surf_lut, s.horizon, s.gd_geo, s.gh, f.dc_rep, s.gd_cfg, s.obj_mode
                )
            # metric now: no ground scale. Lateral keeps its bearing at the new distance.
            if (
                s.item_lens is not None and it.base_col >= 0
            ):  # v26.2.7: the lens ray of the base pixel at the new distance
                f.y_l = f.tr.contact_s if f.tr.contact_s is not None else it.contact_y
                it.lateral_m = (
                    float(groundgeom.lateral_at(s.item_lens, f.y_l * s.gh, it.base_col + 0.5, f.d_use, s.horizon))
                    + s.lat_off
                )
            elif it.distance_m > 0:
                it.lateral_m = (it.lateral_m - s.lat_off) * (f.d_use / it.distance_m) + s.lat_off
            it.distance_m, it.from_depth = f.d_use, True
            f.raw_c = _depth_closing(
                f.tr.dhist,
                f.t,
                s.trk.get("peopleMotionMinSeconds", s.trk["motionMinSeconds"])
                if it.people
                else s.trk["motionMinSeconds"],
            )
            f.tr.closing = None if f.raw_c is None else f.ds * f.raw_c
            it.closing = f.tr.closing


def tracking_jump(s: RunState, f: FrameState) -> None:
    # 4c. (v26.2.12) a distance that jumps between consecutive frames (review 9, 24.5 s: the top of a skip read 5.6 -> 2.65 -> 2.17 -> 0.96 m
    # with a frozen box) is a measurement glitch: no closing speed from the history across it, no coasting from it, and a thin item stays
    # unspoken for ``speech.thinStableS``
    if s.jump_cfg.get("enabled", False):
        for it in f.items:
            f.tr = s.tracks[it.track_id]
            f.d_before, f.d_before_t = f.tr.d_prev, f.tr.d_prev_t
            f.tr.d_prev, f.tr.d_prev_t = it.distance_m, f.t
            if (
                f.d_before is not None
                and not it.clipped
                and f.t - f.d_before_t <= s.jump_cfg.get("maxGapS", 0.4) + 1e-9
                and min(f.d_before, it.distance_m) <= float(s.jump_cfg.get("nearM", 1e9))
                and abs(it.distance_m - f.d_before)
                > max(float(s.jump_cfg.get("minM", 1.0)), float(s.jump_cfg.get("frac", 0.4)) * f.d_before)
            ):
                f.tr.jump_t = f.t
                if it.class_name in s.reset_classes:  # a vehicle / rider: no speed from a history across the glitch
                    it.jumped = True
                    f.tr.history.clear()
                    f.tr.dhist.clear()
                    f.tr.lhist.clear()
                    f.tr.along_s, f.tr.mstate, f.tr.still_t0 = None, None, None
                    it.closing = it.closing_raw = None
                    f.tr.closing = None


def egostate(s: RunState, f: FrameState) -> None:
    # 5. ego
    s.ego.cadence = f.cadence
    s.ego.update_speed(
        [it.closing_raw for it in f.items if _speed_witness(it) and 0.0 <= it.closing_raw <= s.ego_cfg["speedMaxMps"]],
        f.t,
        s.ego_cfg,
    )
    s.scale.update(f.t, f.walk_cadence, s.ego.speed, f.dt)
    # ego speed in the units of the (calibrated) distances: walking cadence times the step length once
    # the scale is known (always, with metric depth distances). v26.1.11 (review 4): when the cadence drops out the
    # last cadence-based speed is held for ``cadenceWindowSeconds`` and then the speed is unknown; the pole-witness
    # speed is only the cold-start guess before any gait scale exists (it read 0.59 m/s while walking at 1.4, so a
    # standing person "approached"). A user measured standing still has speed 0.
    f.depth_distances = (
        s.source == "depth" and s.depth_maps is not None and (not s.relative or f.a_now is not None)
    )  # metres from depth now
    if f.stationary:
        f.ego_speed = 0.0
    elif f.walk_cadence and (s.scale.k is not None or f.depth_distances):
        f.ego_speed = s.held_speed = f.walk_cadence * s.step_len
        s.held_t = f.t
    elif s.held_speed is not None and f.t - s.held_t <= s.ego_cfg["cadenceWindowSeconds"] + 1e-9:
        f.ego_speed = s.held_speed
    elif s.held_speed is None and s.scale.k is None and s.ego.speed is not None:
        f.ego_speed = s.ego.speed * s.scale.value
    else:
        f.ego_speed = None
    # v26.1.13 (review 6, 374.0 s): motion states are judged against a robust ego speed, the median of the last
    # ``egoMedianSeconds`` of the cadence-based speed, so that a momentary spike does not turn "approaching" into "standing"
    # v26.1.15 (review 7, 2.0 / 3.2 s): while the history is shorter than the window the median is still ramping
    # (0.59 at 2.0 s, 1.28 at 3.2 s: a standing person read "approaching"), so the motion words and the people motion wait wait for
    # a full window. A user measured standing still has a known speed 0 at once.
    f.ego_win = s.roles.get("egoMedianSeconds", 0.0)
    if f.ego_speed is None or f.stationary:
        s.ego_hist.clear()
        s.ego_hist_t0 = None
        f.ego_motion = f.ego_speed
        f.ego_settled = f.ego_speed is not None
    else:
        if not s.ego_hist:
            s.ego_hist_t0 = f.t
        f.ego_motion = _robust_speed(s.ego_hist, f.t, f.ego_speed, f.ego_win)
        f.ego_settled = f.ego_win <= 0 or f.t - s.ego_hist_t0 >= f.ego_win - 1e-9
    # v26.1.16 (review 8, 27.3 s): a hard head turn throws the cadence / ego speed off (2.09 against 1.2 m/s in the two seconds around
    # it), so a person's motion state read "standing" while they crossed: no motion words for ``panSettleSeconds`` after a hard pan
    if f.t - s.last_hard_pan_t < s.roles.get("panSettleSeconds", 0.0) - 1e-9:
        f.ego_settled = False
    f.turned = s.ego.update_heading(f.heading, f.t, s.config["pathChange"], f.dt)
    if s.mover.on:
        s.mover.advance(f.t, f.dt, 0.0 if f.stationary else f.ego_speed, f.heading)


def depthscale_report(s: RunState, f: FrameState) -> None:
    f.depth_scale_out = None if s.depth_maps is None or f.ds is None else _r(f.ds * f.a_now, 4) if s.relative else f.ds
    if (
        f.depth_scale_out is None
        and s.depth_maps is not None
        and s.plane
        and s.anchor.fit is not None
        and s.anchor.fit.height_units > 0
    ):
        # v26.2.5: the plane anchor is usable from ``initialAnchorMinFrames`` valid fits; until then the frame's own fit seeds the scale
        # the world map reads (frames 0-1 had none, so the map placed the first facade by the horizon alone). Nothing else reads it.
        f.depth_scale_out = _r(s.settings.camera_height_m / s.anchor.fit.height_units * f.level, 4) if f.level else None


def worldmap_step(s: RunState, f: FrameState) -> None:
    f.corridor_out = None
    if s.smap is not None:
        # v26.2.1: the map of this frame (causal), fed with the same ego values the hazards.json stores, so that the offline
        # ``worldmap.build`` reproduces it; static items are then judged on it; a static danger that left the image is a ghost
        f.frame_in = {
            "horizon": round(s.horizon, 4),
            "scale": round(s.scale.value, 3),
            "depthScale": f.depth_scale_out,
            "dcorr": f.dc_rep,
            "ego": {
                "speedMps": _r(f.ego_speed, 2),
                "headingDeg": _r(f.heading, 1),
                "stationary": f.stationary,
                "depthPitchDeg": _r(s.anchor.pitch_deg, 1) if s.plane else None,
                **f.ego_sens,
            },
        }
        s.smap.update(f.i, f.frame_in, f.dmap, f.grid)
        s.map_ms.append(s.smap.ms)
        for it in f.items:
            s.smap.measure(it)
        if s.map_mode:
            _map_source(
                f.items,
                s.tracks,
                s.smap,
                s.wtracks,
                s.src_cfg,
                f.t,
                s.step_len,
                f.ego_motion if f.ego_motion is not None else f.ego_speed,
                s.src_counts,
            )
        f.seen_now = {it.track_id for it in f.items}
        for tid, tr in s.tracks.items():
            if tid in f.seen_now or tr.ghost_src is None:
                continue
            f.g = s.smap.ghost(tr, f.t)
            if f.g is None:
                tr.ghost_src = tr.ghost_t0 = None
                continue
            tr.ghost_t0 = f.t if tr.ghost_t0 is None else tr.ghost_t0
            tr.last_t = f.t
            tr.present_run += 1
            f.g.present_run = tr.present_run
            f.items.append(f.g)
        f.corridor_out = s.smap.corridor()


def tracking_coast(s: RunState, f: FrameState) -> None:
    if s.coast.on:
        f.real = {it.track_id: it for it in f.items}
        f.items.extend(
            s.coast.items(
                f.t,
                f.real,
                s.world,
                s.tracks,
                s.step_len,
                s.smap.point_in_solid if s.smap is not None and s.smap.solid_on else None,
                (lambda tid: _trusted_track(s.wtracks, tid, f.t))
                if (s.map_mode and s.src_cfg.get("coastFromTracks", True) and s.wtracks.on)
                else None,
            )
        )


def motion_roles(s: RunState, f: FrameState) -> None:
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
            and (f.tr.lp_strong_t is None or f.t - f.tr.lp_strong_t > s.roles.get("laneBaseHoldSeconds", 0.0) + 1e-9)
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


def tracking_jump_final(s: RunState, f: FrameState) -> None:
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


def speech_passing(s: RunState, f: FrameState) -> None:
    if s.pass_cfg.get("enabled", False) and not f.stationary:
        for it in f.items:
            if _passing_close(it, s.pass_cfg):
                it.proximity = True


def tracking_confirm(s: RunState, f: FrameState) -> None:
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


def worldmap_keeps(s: RunState, f: FrameState) -> None:
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


def tracking_unseen(s: RunState, f: FrameState) -> None:
    for tid, tr in s.tracks.items():
        if tid not in f.seen_tracks:
            tr.role, tr.role_run, tr.present_run, tr.prox_run = "none", 0, 0, 0
            if tr.under_last is not None and not tr.under_fired and f.t - tr.under_last <= s.under_gone_s + 1e-9:
                tr.under_fired = True  # a curb / crosswalk edge went under the user and out of view
                s.surface.note_evidence(f.t)


def memory(s: RunState, f: FrameState) -> None:
    # world memory: where are we, and which remembered (announced) object is each item?
    s.world.advance(
        f.t,
        f.dt,
        0.0 if f.stationary else (f.walk_cadence * s.step_len if f.walk_cadence else f.ego_speed),
        f.heading,
        s.smap.pose if (s.one_pose and s.smap is not None) else None,
    )
    s.world.link(f.items, s.tracks, f.t)


def worldtracks(s: RunState, f: FrameState) -> None:
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


def egostate_pathchange(s: RunState, f: FrameState) -> None:
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


def speech(s: RunState, f: FrameState) -> None:
    # speech
    # context waits for the first surface (up to the old debounce, no longer: the persistence needed
    # to *announce* a surface is longer now, but the scene summary must not wait for it)
    f.surface_known = s.surface.stable is not None or f.t - s.first_t >= s.config["surfaces"]["debounceSeconds"] - 1e-9
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


def sounds_beeps(s: RunState, f: FrameState) -> None:
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


def output_frame(s: RunState, f: FrameState) -> None:
    f.speed_known = f.ego_speed is not None
    s.frames_out.append(
        {
            "index": f.i,
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
            "hazards": [_hazard_json(it, s.gh, s.gw, s.full_all) for it in sorted(f.items, key=lambda it: it.steps)],
        }
    )


def finish(s: RunState) -> tuple[dict, dict]:
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


STAGES: list[Stage] = [
    Stage(
        "surface_region",
        ("adopted", "config", "grid", "group", "ids", "policy", "prev_group", "region", "surface", "t"),
        ("adopted", "group", "prev_group", "prev_left", "prev_right", "region"),
        "surfaces",
        surface_region,
    ),
    Stage(
        "surface_horizon",
        (
            "config",
            "first_t",
            "geo_cfg",
            "h_state",
            "horizon",
            "last_estimate_t",
            "prev_left",
            "prev_right",
            "raw",
            "raws",
            "region",
            "settings",
            "step",
            "t",
            "target",
            "warm",
            "win_bounds",
        ),
        (
            "first_t",
            "h_state",
            "horizon",
            "last_estimate_t",
            "prev_left",
            "prev_right",
            "raw",
            "step",
            "target",
            "warm",
        ),
        "geometry",
        surface_horizon,
    ),
    Stage(
        "egosignals_lookup",
        (
            "_roll",
            "cad",
            "cadence",
            "ego_cfg",
            "ego_sens",
            "flow_hcum",
            "g_now",
            "gd_geo",
            "gd_on",
            "gps_scale",
            "h_state",
            "hcum",
            "hz_off",
            "hz_source",
            "item_lens",
            "j",
            "mser",
            "mt",
            "pitch_now",
            "roll_now",
            "sser",
            "stat",
            "stationary",
            "step_len0",
            "t",
            "walk_cadence",
        ),
        (
            "_roll",
            "cad",
            "cadence",
            "ego_sens",
            "flow_heading",
            "g_now",
            "hcum",
            "heading",
            "horizon",
            "j",
            "mt",
            "pitch_now",
            "roll_now",
            "stat",
            "stationary",
            "step_len",
            "walk_cadence",
        ),
        "ego",
        egosignals_lookup,
    ),
    Stage(
        "surface_crosswalk",
        ("config", "crosswalk", "cw_change", "cw_class", "cw_marks", "grid", "stationary", "t"),
        ("cw_change",),
        "surfaces",
        surface_crosswalk,
    ),
    Stage(
        "detection",
        (
            "a_cells",
            "a_hz",
            "a_raw",
            "anchor",
            "anchor_horizon",
            "anchor_rows",
            "config",
            "depth_maps",
            "depth_rays",
            "depth_rows_frac",
            "depth_t",
            "dist_cfg",
            "dmap",
            "dt",
            "f",
            "geo",
            "gh",
            "grid",
            "gw",
            "horizon",
            "ids",
            "items",
            "j",
            "k",
            "lane_half",
            "lat_off",
            "lens_all",
            "plane",
            "projection",
            "region",
            "relative",
            "roles",
            "scale",
            "settings",
            "t",
        ),
        ("a_cells", "a_hz", "a_raw", "dmap", "geo", "items", "j", "k"),
        "geometry",
        detection,
    ),
    Stage(
        "tracking",
        (
            "a_c",
            "a_t",
            "anchor",
            "d_s",
            "f",
            "flow_heading",
            "geo",
            "gh",
            "horizon",
            "items",
            "k",
            "lat_off",
            "matches",
            "min_span",
            "next_id",
            "next_lane_part_id",
            "pan_shift",
            "people_classes",
            "prev_heading",
            "raw_closing",
            "relative",
            "settings",
            "t",
            "tid",
            "tr",
            "tracks",
            "trk",
            "warm",
        ),
        (
            "a_c",
            "a_t",
            "d_s",
            "last_hard_pan_t",
            "matches",
            "min_span",
            "next_id",
            "next_lane_part_id",
            "pan_shift",
            "prev_heading",
            "raw_closing",
            "tid",
            "tr",
            "tracks",
        ),
        "tracking",
        tracking,
    ),
    Stage(
        "depthscale",
        (
            "a_now",
            "anchor",
            "c_source",
            "corrector",
            "d_use",
            "dc_rep",
            "dmap",
            "ds",
            "dscale",
            "dt",
            "gait_check",
            "gd_cfg",
            "gd_geo",
            "gd_on",
            "gh",
            "grid",
            "horizon",
            "hsig",
            "item_lens",
            "items",
            "lat_off",
            "level",
            "level_prior",
            "obj_mode",
            "plane",
            "prior_c",
            "r",
            "raw_c",
            "region",
            "relative",
            "sc_total",
            "scale",
            "sig_rows",
            "smap",
            "source",
            "step_len",
            "surf_lut",
            "t",
            "tr",
            "tracks",
            "trk",
            "walk_cadence",
            "walls",
            "wit",
            "y_l",
        ),
        (
            "a_now",
            "c_source",
            "d_use",
            "dc_rep",
            "depth_scale_source",
            "ds",
            "level",
            "prior_c",
            "r",
            "raw_c",
            "sc_total",
            "sig_rows",
            "tr",
            "walls",
            "wit",
            "y_l",
        ),
        "distance",
        depthscale,
    ),
    Stage(
        "tracking_jump",
        ("d_before", "d_before_t", "items", "jump_cfg", "reset_classes", "t", "tr", "tracks"),
        ("d_before", "d_before_t", "tr"),
        "distance",
        tracking_jump,
    ),
    Stage(
        "egostate",
        (
            "a_now",
            "cadence",
            "config",
            "depth_distances",
            "depth_maps",
            "dt",
            "ego",
            "ego_cfg",
            "ego_hist",
            "ego_hist_t0",
            "ego_speed",
            "ego_win",
            "heading",
            "held_speed",
            "held_t",
            "items",
            "last_hard_pan_t",
            "mover",
            "relative",
            "roles",
            "scale",
            "source",
            "stationary",
            "step_len",
            "t",
            "walk_cadence",
        ),
        (
            "depth_distances",
            "ego_hist_t0",
            "ego_motion",
            "ego_settled",
            "ego_speed",
            "ego_win",
            "held_speed",
            "held_t",
            "turned",
        ),
        "ego",
        egostate,
    ),
    Stage(
        "depthscale_report",
        ("a_now", "anchor", "depth_maps", "depth_scale_out", "ds", "level", "plane", "relative", "settings"),
        ("depth_scale_out",),
        None,
        depthscale_report,
    ),
    Stage(
        "worldmap_step",
        (
            "anchor",
            "dc_rep",
            "depth_scale_out",
            "dmap",
            "ego_motion",
            "ego_sens",
            "ego_speed",
            "frame_in",
            "g",
            "grid",
            "heading",
            "horizon",
            "i",
            "items",
            "map_mode",
            "map_ms",
            "plane",
            "scale",
            "seen_now",
            "smap",
            "src_cfg",
            "src_counts",
            "stationary",
            "step_len",
            "t",
            "tracks",
            "wtracks",
        ),
        ("corridor_out", "frame_in", "g", "seen_now"),
        "source",
        worldmap_step,
    ),
    Stage(
        "tracking_coast",
        ("coast", "items", "map_mode", "real", "smap", "src_cfg", "step_len", "t", "tracks", "world", "wtracks"),
        ("real",),
        "coast",
        tracking_coast,
    ),
    Stage(
        "motion_roles",
        (
            "along",
            "base",
            "c_rate",
            "ego",
            "ego_motion",
            "ego_settled",
            "ego_speed",
            "gait_check",
            "gh",
            "heading",
            "items",
            "labels",
            "lane_half",
            "mover",
            "parked_labels",
            "plane",
            "policy",
            "projection",
            "region",
            "roles",
            "settings",
            "smap",
            "source",
            "span",
            "stationary",
            "step_len",
            "t",
            "tau",
            "tr",
            "tracks",
            "tree_cfg_run",
            "trk",
            "under_min_w",
            "under_rows",
            "valid",
            "weak_lost",
        ),
        ("along", "base", "c_rate", "span", "tau", "tr", "valid", "weak_lost"),
        "roles",
        motion_roles,
    ),
    Stage(
        "tracking_jump_final",
        ("df", "df_t", "items", "jump_cfg", "stable_s", "t", "tr", "tracks"),
        ("df", "df_t", "tr"),
        "distance",
        tracking_jump_final,
    ),
    Stage(
        "speech_passing",
        ("items", "pass_cfg", "stationary"),
        (),
        "beeps",
        speech_passing,
    ),
    Stage(
        "tracking_confirm",
        ("coast", "items", "seen_tracks", "t", "tr", "tracks", "world"),
        ("seen_tracks", "tr"),
        None,
        tracking_confirm,
    ),
    Stage(
        "worldmap_keeps",
        ("items", "policy", "smap", "stationary", "t", "tr", "tracks"),
        ("tr",),
        None,
        worldmap_keeps,
    ),
    Stage(
        "tracking_unseen",
        ("seen_tracks", "surface", "t", "tracks", "under_gone_s"),
        (),
        "surfaces",
        tracking_unseen,
    ),
    Stage(
        "memory",
        (
            "dt",
            "ego_speed",
            "heading",
            "items",
            "one_pose",
            "smap",
            "stationary",
            "step_len",
            "t",
            "tracks",
            "walk_cadence",
            "world",
        ),
        (),
        "memory",
        memory,
    ),
    Stage(
        "worldtracks",
        (
            "_t_wt",
            "f",
            "gh",
            "horizon",
            "items",
            "k",
            "map_mode",
            "policy",
            "settings",
            "smap",
            "t",
            "world",
            "wtracks",
        ),
        ("_t_wt", "wt_out"),
        "worldTracks",
        worldtracks,
    ),
    Stage(
        "egostate_pathchange",
        (
            "adopted",
            "anchor",
            "config",
            "dist_cfg",
            "dscale",
            "ego_cfg",
            "items",
            "path_change",
            "plane",
            "policy",
            "recalibrate",
            "t",
            "turned",
        ),
        ("dscale", "gait_check", "path_change"),
        "pathChange",
        egostate_pathchange,
    ),
    Stage(
        "speech",
        (
            "blk",
            "blk_cfg",
            "blk_kind",
            "blk_last_t",
            "blk_open",
            "blk_pos",
            "blk_run",
            "blk_seen_t",
            "bx",
            "by",
            "config",
            "dt",
            "ego_cfg",
            "ego_speed",
            "events",
            "first_t",
            "items",
            "meas_hist",
            "meas_win",
            "policy",
            "smap",
            "speech",
            "stationary",
            "step_len",
            "surface",
            "surface_known",
            "t",
            "th_",
            "tracks",
            "txt",
            "w_now",
            "wfollow",
            "world",
        ),
        (
            "blk",
            "blk_kind",
            "blk_last_t",
            "blk_open",
            "blk_pos",
            "blk_run",
            "blk_seen_t",
            "bx",
            "by",
            "speech",
            "surface_known",
            "th_",
            "txt",
            "w_now",
        ),
        "speech",
        speech,
    ),
    Stage(
        "sounds_beeps",
        (
            "beep_run",
            "beeping",
            "config",
            "follow",
            "follow_cfg",
            "frame_collision",
            "frame_proximity",
            "items",
            "near_soft",
            "policy",
            "roles",
            "t",
            "wfollow",
        ),
        ("beep_run", "beeping", "near_soft"),
        "tones",
        sounds_beeps,
    ),
    Stage(
        "output_frame",
        (
            "a_now",
            "anchor",
            "anchor_mode",
            "c_source",
            "cadence",
            "corridor_out",
            "dc_rep",
            "depth_maps",
            "depth_scale_out",
            "depth_scale_source",
            "ds",
            "ego_sens",
            "ego_speed",
            "frames_out",
            "full_all",
            "gait_check",
            "geo",
            "gh",
            "gw",
            "heading",
            "horizon",
            "i",
            "items",
            "lane_half",
            "path_change",
            "plane",
            "raw",
            "region",
            "relative",
            "roles",
            "scale",
            "smap",
            "speed_known",
            "stationary",
            "step_len",
            "t",
            "wt_out",
        ),
        ("speed_known",),
        None,
        output_frame,
    ),
]
