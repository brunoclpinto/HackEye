"""Loads common/config/pipeline_defaults.json so a value changed there
actually changes RnD behavior — not just a Python default that happens to
match it. See common/README.md for the current Stage 1 status (the Swift
side doesn't read this yet).
"""

import json

from common_paths import find_common_dir

_PATH = find_common_dir() / "config" / "pipeline_defaults.json"

with open(_PATH) as _f:
    _DATA = json.load(_f)

DETECTOR = _DATA["detector"]
TRACKER = _DATA["tracker"]
SEGMENTATION = _DATA["segmentation"]
