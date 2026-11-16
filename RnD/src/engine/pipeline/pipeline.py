"""``Pipeline``: ``setup``, the registered stages frame by frame, ``finish``; the timings are explicit ``stats``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.pipeline.stages import STAGES, Stage, finish, setup
from engine.pipeline.state import FrameState

__all__ = ["Pipeline", "PipelineStats"]


@dataclass
class PipelineStats:
    """Timings of the last run (never in the output document): ms per frame of the world-track and map steps."""

    world_tracks_ms: list[float] = field(default_factory=list)
    map_ms: list[float] = field(default_factory=list)


class Pipeline:
    """The frame pipeline: ``run`` has the keywords of ``run_collision``; ``stats`` = timings of the last run."""

    def __init__(self, stages: list[Stage] = STAGES) -> None:
        self.stages = stages
        self.stats = PipelineStats()

    def run(
        self,
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
        """Per-frame hazards and the speech/tone event list (see ``run_collision`` for the arguments)."""
        self.stats = PipelineStats()
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

            for st in self.stages:
                st.fn(s, f)

        result = finish(s)  # fills glue.LAST_WORLD_TRACKS_MS from s.wtracks.ms (the tools read it)
        self.stats.world_tracks_ms = list(s.wtracks.ms)
        self.stats.map_ms = list(s.map_ms)
        return result
