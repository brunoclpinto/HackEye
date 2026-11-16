"""Notification reviews: the user's ground truth about what the Lab should say or beep (§10, §14).

Reviews belong to the *recording*, not to a run: what should be spoken at a
given recording time stays true across re-analysis and new collision
versions. Each verdict snapshots the notification (speech phrase or beeps episode) it judged plus the run,
collision run (`collisionId`, v26.2.8: verdicts are per collision run) and collision version it came from; `added` annotations are phrases the system
missed. One JSON file per recording (`LAB_DIR/reviews/<recId>.json`), written
atomically. A process-wide lock serialises read-modify-write (the endpoints
run in a threadpool); files are small, so one lock is enough.

Validation raises ReviewError(status, message); server.py maps it to HTTP.
The export joins each annotation with the hazards/events of the run it was
made against (nearest analysed frame, non-"none" items, ego, surface, nearby
speech) so the file can be analysed offline without the run directories.
"""

from __future__ import annotations

import secrets  # noqa: F401  (tools/equivalence.py patches `reviews.secrets.token_hex`)

from lab._forward import install

# v26.3.0 p5-05: the code moved to lab.features.reviews (audit 7.1); every name stays reachable here as a forward to its home.
install(__name__, dict.fromkeys(
    ("KINDS", "MAX_NOTE", "MAX_TEXT", "NEARBY_SECONDS", "ROLES", "TYPES",
         "VERDICTS", "_EVENT_KEYS", "ReviewError", "_RunData", "_auto_correct", "_bad",
         "_check_note", "_check_role", "_check_run", "_check_t", "_check_t_end", "_check_text",
         "_check_type", "_check_verdict", "_load", "_lock", "_log", "_now",
         "_path", "_run_notifications", "_save", "_sorted", "count_for_collision", "create",
         "delete", "export", "list_annotations", "match_key", "recordings_with_reviews", "update",
         "LAB_DIR"),
    "lab.features.reviews"))
