"""Analysis runs for the Lab: segmentation over a time range, stored for
playback, plus the collision pass on top.

Design notes:
- One worker thread owns the GPU and runs jobs FIFO. The model is loaded on
  the first job and released after IDLE_SECONDS without work, so the
  always-on web service holds no VRAM between runs. Only one model is cached
  at a time: segmentation.CLASSES / SAFETY_LEVELS are process-global and get
  reassigned by each SegmentationModel constructor, so two live models with
  different taxonomies would mislabel each other's masks.
- Stored class grids have the letterbox padding cropped off and are resized
  to a fixed-width grid that maps 1:1 onto the original frame (CONTRACTS §1).
  All letterbox math ends here; collision logic and the frontend never see it.
- Frames are addressed by chapter-local frame index (not by timestamp seek
  per frame): seek once, then grab() forward, like src/pipeline.py, so
  skipped frames cost a decode but no colour conversion or inference.
- The collision pass is imported lazily so the Lab still runs inference
  while src/collision.py is absent or broken.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab._forward import install  # noqa: E402

# v26.3.0 p5-02: the names below moved to lab.store (audit 7.4) and stay reachable here as forwards to their home module
# (reads, writes and deletes); code in this module reads them as attributes of the home (`runs._active`), never as a local copy.
install(__name__, {
    **dict.fromkeys(
        ("GRID_W", "NO_DATA", "ANALYSIS_VERSION", "PROFILES", "RESOLUTIONS", "IDLE_SECONDS", "RUN_ID_RE", "DEPTH_MODELS",
         "DEPTH_ANCHOR", "SUPERSEDED_ANCHORS", "DEPTH_W", "DEPTH_H", "DEPTH_MIN_REL", "DEPTH_MIN_M", "DEPTH_MAX_M",
         "DEFAULT_MODEL", "MODEL_DIRS"), "lab.store.constants"),
    **dict.fromkeys(("RunError", "RunConflict", "_Cancelled"), "lab.store.errors"),
    **dict.fromkeys(("_now", "_log", "_write_json"), "lab.store.util"),
    **dict.fromkeys(
        ("LAB_DIR", "run_dir", "_state_lock", "_active", "get_run", "list_runs", "_update_run", "ACTIVE_STATUSES",
         "find_active_for_recording", "_conflict_message", "_remove_partial_outputs", "_PARTIAL_OUTPUTS"), "lab.store.runs"),
    **dict.fromkeys(
        ("_normalise_request", "request_side", "run_window", "DEVICES", "_parse_device", "_cpu_threads", "_run_id"),
        "lab.store.requests"),
    "list_models": "lab.store.models",
    # v26.3.0 p5-03: the run queue and the GPU worker moved to lab.jobs (audit 7.4).
    **dict.fromkeys(
        ("_jobs", "_worker", "_cache", "_cancel_flags", "_busy", "_maintenance", "submit_run", "cancel_run", "_finish_cancelled",
         "cancel_all", "is_idle", "analysis_active", "wait_idle", "release_model", "begin_maintenance", "end_maintenance"),
        "lab.jobs.queue"),
    **dict.fromkeys(("_ensure_worker", "_worker_loop", "_check_cancel", "_finish"), "lab.jobs.worker"),
    # v26.3.0 p5-04: the model cache, frame reader, inference job and the two passes moved to lab.stages (audit 7.4); the job
    # reads the passes as attributes of their stage modules at call time, so a patch through this facade is seen.
    "_ModelCache": "lab.stages.models",
    **dict.fromkeys(("MOTION_W", "MOTION_H", "_FrameReader"), "lab.stages.frames"),
    "_run_job": "lab.stages.inference",
    **dict.fromkeys(("_build_worldmap", "collision_pass"), "lab.stages.collision"),
    "worldmap_pass": "lab.stages.worldmap",
})
