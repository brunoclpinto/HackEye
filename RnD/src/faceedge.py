"""Face / edge test on the ego-centric fused world map (v26.2.2, phase A: measurement only, nothing judges on it yet).

A corridor cell of a static object family is either
  * an EDGE: it lies within ``edgeBandM`` (+ ``edgeBlurPerM`` x range) of the wall line of its side, and that line runs roughly parallel to
    the walking direction (|angle| <= ``maxLineAngleDeg``): the blurred line of a wall beside the path; or
  * a FACE: it is not an edge and it protrudes past its side's wall line toward the walking axis by >= ``faceProtrusionM``, or the cells
    around it run across the walking direction (principal axis >= ``crossAngleDeg`` from forward, elongation >= ``crossElongation``),
    or its side has no wall line at all (an isolated object such as a pole); else it is NONE (ambiguous, counts for neither).

Coordinates are the ego frame of ``worldmap.Observer``: ``fwd`` metres ahead, ``right`` metres to the right of the body line.
Wall line of a side: ``right = a + b * fwd`` (b = tan of the angle to the walking direction).
"""
from __future__ import annotations

from engine.worldmap.faceedge import EDGE  # noqa: F401
from engine.worldmap.faceedge import FACE  # noqa: F401
from engine.worldmap.faceedge import NONE  # noqa: F401
from engine.worldmap.faceedge import VERDICT_NAMES  # noqa: F401
from engine.worldmap.faceedge import DEFAULTS  # noqa: F401
from engine.worldmap.faceedge import settings  # noqa: F401
from engine.worldmap.faceedge import fit_line  # noqa: F401
from engine.worldmap.faceedge import fit_wall_lines  # noqa: F401
from engine.worldmap.faceedge import local_orientation  # noqa: F401
from engine.worldmap.faceedge import classify  # noqa: F401
from engine.worldmap.faceedge import summarize  # noqa: F401
from engine.worldmap.faceedge import lines_json  # noqa: F401
