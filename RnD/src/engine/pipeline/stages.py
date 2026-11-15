"""The stage functions of the frame loop: ``setup`` (everything before the loop) and stages 1-12 (v26.3.0 p4-04).

Each stage is the verbatim block of ``run_collision`` between two boundaries of audit 3.2, as a function
``(s: RunState, f: FrameState) -> None``; ``STAGES`` lists them in execution order with the ``RunState`` /
``FrameState`` attributes each one reads and writes (derived from its AST; a test keeps the two in step).
"""

# ruff: noqa: E501
# mypy: ignore-errors
# (the bodies are untyped legacy code; p4-06 removes this ignore)
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from engine import worldmap as wmap
from engine.core import distfuse, groundgeom
from engine.core.classes import (
    resolve_class_ids,
)
from engine.core.geom import (
    Box,
    focal_px,
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
    robust_speed as _robust_speed,
)
from engine.pipeline.state import FrameState, RunState
from engine.roles.roles import (
    pole_like as _pole_like,
)
from engine.roles.roles import (
    speed_witness as _speed_witness,
)
from engine.sounds.tones import (
    resolve_sounds,
)
from engine.speech.policy import (
    SpeechPolicy,
)
from engine.speech.walls import (
    WallFollow as _WallFollow,
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
    depth_closing as _depth_closing,
)
from engine.worldmap import config as wm_config
from engine.worldmap.source import (
    map_source as _map_source,
)
from engine.worldmap.staticmap import (
    StaticMap as _StaticMap,
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
    s: RunState | None = None,
) -> RunState:
    """The setup block of ``run_collision`` (everything before the frame loop): fills and returns the run state ``s``.

    ``s`` is the ``RunState`` the caller built (``s = RunState()``); None builds a fresh one."""
    if s is None:
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
]
