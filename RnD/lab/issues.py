"""Open-issues panel (v26.2.4 follow-up): the catalogue in lab/issues.json (maintained in git, read at request time) plus the user's
close / reopen / comment state in `LAB_DIR/issues-state.json` = {id: {status, closedAt, note, noteUpdatedAt}} (outside the version wipe)."""

from __future__ import annotations

from lab._forward import install

# v26.3.0 p5-05: the code moved to lab.features.issues (audit 7.1); every name stays reachable here as a forward to its home.
install(__name__, dict.fromkeys(
    ("IssuesError", "MAX_NOTE", "_catalogue", "_item", "_items", "_lock",
         "_state", "_state_path", "export_items", "list_issues", "reset", "update",
         "CATALOGUE"),
    "lab.features.issues"))
