"""View-only mask display preferences, shared by every browser that opens the Lab.

`LAB_DIR/display/<mapping file name>` holds only the OVERRIDES of the safety mapping's defaults:

    {"classes": {"<id>": {"level": 2, "show": false}},          # level only if != default, show only if false
     "levels":  {"<level>": {"color": [r, g, b], "opacity": 0.5}},  # each key only if != default
     "updatedAt": "2026-10-16T12:00:00Z"}

It only changes how the Lab paints the mask overlay. It never touches common/config/safety_mapping*.json,
collision.json or any collision / audio behaviour. The directory is outside runs/ and reviews/, so version
wipes (versioning.py) leave it alone.
"""

from __future__ import annotations

from lab._forward import install

# v26.3.0 p5-05: the code moved to lab.features.display (audit 7.1); every name stays reachable here as a forward to its home.
install(__name__, dict.fromkeys(
    ("DisplayError", "MAPPING_RE", "_clean_classes", "_clean_levels", "_dir", "_is_num", "_lock",
         "_mapping", "_read", "_write", "default_opacity", "get", "put",
         "reset"),
    "lab.features.display"))
