"""v26.2.3: ground ray + depth for the distance of a base that stands on a surface (``distance.objectDistance``).

DA2 metric depth is right in the near field and squashes beyond about 12 m (a building at 30 m reads 6-12 m). The ground ray of a
base row (``H f q / ((y - horizon) gh)``) has no such squashing, but it gets noisy near the horizon. This module holds the pieces
both the collision pass (item distances) and the world map (object bases) use, so that the map reads exactly what the pass used:

* ``ground_z``: the ground ray in the lens's own geometry: the pixel's ray (equidistant fisheye or pinhole), the pitch the horizon row
  implies, the camera height; it returns the z-depth of the ground point, the quantity the depth map holds. (The first build used the
  pinhole formula ``H f / ((y - horizon) gh)``: under the 118 deg fisheye it is 1.45 times off in the near field and wrong towards the
  image sides, which moved distances of off-axis bases by metres.)
* ``Corrector``: per frame, the walking-region cells give two things, both in the units of the scaled depth (metres):
  ``ref`` (q) = median depth / ground ray in the near field (``refGroundM``; ~1 when the camera height and the horizon are right) and the
  **range correction** rho(d) = (depth / ground ray) / q, binned by depth. rho is ~1 in
  the near field and falls beyond ~12 m (the squash). ``corrected = depth / rho(depth)``: the near field is unchanged. Bins and q are
  smoothed in time (log EMA) and held when a frame has too few samples.
* ``HorizonSigma``: the horizon jitter (rows) measured on the stored horizon track.
* ``resolve``: per base, the fused / ground / depth distance (inverse-variance fusion, sanity gate).

The curve travels in the hazards.json frames (``depthCorrection``: ``{"ref", "sigmaRows", "curve": [[depth m, rho], ...]}``, rounded),
and every consumer works from that rounded dict, so the offline map build reproduces the online one.
"""
from __future__ import annotations

from engine.core.distfuse import (  # noqa: F401
    MODES,
    SRC_DEPTH,
    SRC_FUSED,
    SRC_GROUND,
    SRC_NAMES,
    correct_depth,
    resolve,
    resolved_mode,
    rho_at,
    settings,
)
from engine.core.distfuse import prior_interp as _prior_interp  # noqa: F401
from engine.core.groundgeom import (  # noqa: F401
    Geometry,
    ground_m,
    ground_pixel,
    ground_point,
    ground_z,
    lateral_at,
    ray_dir,
)
from engine.core.groundgeom import pitch as _pitch  # noqa: F401
from engine.groundfuse import Corrector, HorizonSigma  # noqa: F401
from engine.groundfuse import wmedian as _wmedian  # noqa: F401
