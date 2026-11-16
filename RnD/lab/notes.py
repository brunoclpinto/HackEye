"""The Lab-wide notes box (v26.2.4 follow-up): one freeform document for reviews, remarks and fix requests.

`LAB_DIR/notes.json` = {"text", "updatedAt"}. It sits outside runs/ and reviews/, so version wipes leave it alone. Before each save the
previous file is copied to `notes.prev.json` (one generation). A save carries `baseUpdatedAt`; when it differs from the stored value the
note was changed elsewhere (another tab, the phone) and the save is refused with 409 unless forced.
"""

from __future__ import annotations

from lab._forward import install

# v26.3.0 p5-05: the code moved to lab.features.notes (audit 7.1); every name stays reachable here as a forward to its home.
install(__name__, dict.fromkeys(
    ("MAX_CHARS", "NotesError", "_lock", "_path", "_read", "get",
         "put"),
    "lab.features.notes"))
