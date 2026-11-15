"""World tracks (v26.2.9, shadow mode): every item of the collision pass tracked in the world with position, velocity and uncertainty.

Nothing computed here feeds a decision of ``collision.run_collision``; it only adds ``worldTracks`` to each hazards frame.

State per track: ``[x, y, vx, vy]`` in the ``_WorldMemory`` frame (x east, y north, m, m/s), a 4 x 4 covariance, a constant-velocity Kalman
filter (white acceleration noise: small for static-like items, large for movers). The measurement is the item's reported (forward, right)
position located with the current dead-reckoned pose; its covariance is built in range / bearing and rotated to the world.
A track without a measurement stays predicted: ``out-of-view`` (outside the field of view, nearer than the bottom image row, behind
the user, or hidden by a building on the map) for ``coastMaxS``, ``missing`` (expected in view, not detected) for ``missDropFrames`` frames.
"""
from __future__ import annotations

from engine.worldtracks.tracks import DEFAULTS, WorldTracks, settings  # noqa: F401
from engine.worldtracks.tracks import WT as _WT  # noqa: F401
from engine.worldtracks.tracks import eig_radius as _eig_radius  # noqa: F401
from engine.worldtracks.tracks import interval as _interval  # noqa: F401
from engine.worldtracks.tracks import rot as _rot  # noqa: F401
