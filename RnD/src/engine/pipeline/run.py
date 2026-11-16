"""The frame pipeline entry point: ``run_collision`` (moved from collision.py in p4-02)."""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from engine.pipeline.stages import STAGES, finish, setup
from engine.pipeline.state import FrameState


def run_collision(
    grids: Any,
    times: Any,
    class_names: Any,
    config: Any,
    settings: Any,
    motion: Any = None,
    depth: Any = None,
    window: Any = None,
    sounds: Any = None,
    worldmap_config: Any = None,
    progress: Any = None,
    sensors: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    s = setup(
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

        for st in STAGES:
            st.fn(s, f)

    return finish(s)
