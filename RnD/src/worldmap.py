"""World map spike (v26.2 step 1): a fused, ego-centric bird's-eye map built only from what a Lab run stores.

Inputs per frame: the class grid, the depth map (when the run has one), the frame's horizon and ego block from
hazards.json. Nothing is inferred again. Per frame:

1. Ego observation (``Observer``): a 200 x 200 heading-up grid of 0.10 m cells (v26.2.4: forward only, the user stands on the
   bottom edge, col 100 / row 200: 20 m ahead, +-10 m to the sides, nothing behind).
   * surface classes: inverse ground-plane projection (each map cell -> the image pixel that sees it, using the
     collision pass's own geometry: ``focal_px`` / ``ground_distance_m`` / ``lateral_m`` inverted, the camera height
     and the lateral offset of the body calibration), so the map has no holes;
   * object classes (walls, poles, vegetation...): ONLY their ground base (the lowest pixel of each vertical run),
     placed at the depth under that pixel x the frame's depth scale when the run's distance source is depth (the same
     metres the collision pass reports as ``distanceM``), else at the ground distance of its row; upper pixels are not
     projected;
   * movers (person, rider, animal, vehicle): never burned into the map (the hazards list carries them).
2. Pose: ``collision._WorldMemory.advance`` (cadence speed x dt along the optical-flow heading, 0 when stationary).
3. Fusion (``Fusion``): a world-frame vote grid, recentred as the user moves; class = argmax vote when the weight is above a floor.
   v26.2.10 (facts only): ``decay`` "none" (the default): a cell the frame does not SEE (hidden by a person / car, out of view) keeps its
   votes unchanged; a SEEN cell first multiplies the votes of the other classes of the same layer by ``conflictFactor`` and caps its
   layer total at ``voteCap`` (the new observation is confronted with the stored one). ``decay`` "time" keeps the v26.2.9 fusion
   (exponential decay, lazily: votes stored pre-multiplied by exp(lambda t)). ``poseAlign``: the frame's pose is searched a little
   (heading, shift) for the best agreement of the seen surface cells with the stored map before fusing.
4. Snapshot: the fused map resampled into the ego frame, as one class per cell (surface and objects voting together: the
   collision rules read it) and, for the Lab's click readout (v26.2.4), as two separate layers: the winning surface class and the
   winning object class of every cell.
"""
from __future__ import annotations

import sys

import collision  # noqa: F401  (kept as a module attribute)
import engine.worldmap.config as _wcfg
import groundfuse  # noqa: F401  (kept as a module attribute: tools/ground_diag.py reads ``worldmap.groundfuse``)
from engine.worldmap.config import (  # noqa: F401  (same objects; the conftest patches ``load_config`` on this module)
    KIND_IGNORE,
    KIND_MOVER,
    KIND_OBJECT,
    KIND_SURFACE,
    UNKNOWN,
    class_kinds,
    load_config,
)
from engine.worldmap.fusion import Fusion  # noqa: F401
from engine.worldmap.helpers import (  # noqa: F401
    face_contact_samples,
    first_depth_scale,
    frames_from_hazards,
    settings_from_hazards,
)
from engine.worldmap.map import WorldMap, build  # noqa: F401
from engine.worldmap.observer import Observer  # noqa: F401
from engine.worldmap.pose import PoseTracker, integrate_pose  # noqa: F401


def _facade_loader() -> dict:
    return sys.modules[__name__].load_config()


_wcfg.default_config_loader = _facade_loader
