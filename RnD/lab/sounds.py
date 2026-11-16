"""The Lab-wide sound profile (v26.1.16): pitch, duration and repeat interval of every notification sound, and the speech speed.

`LAB_DIR/display/sounds.json` holds only the OVERRIDES of the defaults in ``collision.json`` ``tones.sounds`` / ``tones.speechRate``:

    {"kinds": {"collision-left": {"pitchHz": 700}, "crosswalk-out": {"intervalS": 0.2}}, "speechRate": 1.25, "updatedAt": "..."}

Same pattern as ``lab/display.py``: a small JSON file outside runs/ and reviews/, so version wipes (``versioning.py``) leave it alone;
every browser that opens the Lab shares it. Pitch, duration and speech speed are applied by the browser live; the intervals shape the
tone schedule, so the collision pass (``analysis.collision_pass``) reads the profile and a re-run applies them.
"""

from __future__ import annotations

from lab._forward import install

# v26.3.0 p5-05: the code moved to lab.features.sounds (audit 7.1); every name stays reachable here as a forward to its home.
install(__name__, dict.fromkeys(
    ("FIELDS", "SoundsError", "_col", "_is_num", "_lock", "_overrides",
         "_path", "_read", "_view", "get", "profile", "put",
         "reset"),
    "lab.features.sounds"))
