"""Collision runs (v26.2.8): one collision result of an analysis run, kept next to the others.

`runs/<runId>/collisions/<cid>/` holds hazards.json, events.json, worldmap.npz and collision.json (the settings, the resolved
settings, the config overrides, a label, counts). Ids are `c<n>`, sequential per run, never reused (`collisionSeq` in run.json);
`collisions` in run.json lists them in creation order. The passes themselves live in analysis.py; this module is storage, config
overrides, labels, delete and the A/B comparison. Errors are CollisionError(status, message); server.py maps them to HTTP.
"""

from __future__ import annotations

from engine.core import config as _config
from lab._forward import install
from lab.store import errors

# v26.3.0 p5-02: the collision docs moved to lab.store (audit 7.5); every moved name stays reachable here as a forward to its home.
install(__name__, {
    **dict.fromkeys(
        ("CID_RE", "MAX_LABEL", "MATCH_WINDOW_S", "FILES", "_lock", "collisions_root", "collision_dir", "ids", "latest", "resolve",
         "read_doc", "_add_effective", "list_docs", "write_doc", "update_doc", "allocate", "register", "set_label", "delete"),
        "lab.store.collision_docs"),
    "CollisionError": "lab.store.errors",
    # v26.3.0 p5-03: the re-run job moved to lab.jobs.collision (audit 7.5)
    **dict.fromkeys(("Job", "_job", "job_active", "cancel_job", "start_job", "_run_job"), "lab.jobs.collision"),
    # v26.3.0 p5-05: the compare / match functions moved to lab.features.compare (audit 7.5)
    **dict.fromkeys(("_flatten", "_settings_diff", "_events", "_same", "match_events", "compare"), "lab.features.compare"),
})


# --------------------------------------------------------------------------
# Config overrides
# --------------------------------------------------------------------------

_kind = _config.value_kind
PENDING_KEYS = _config.PENDING_KEYS
_pending = _config.is_pending


def validate_overrides(overrides) -> dict:
    """Shape check: {} or {"collision": {key: value}, "worldmap": {key: value}}; returns the normalised dict (empty groups dropped)."""
    try:
        return _config.validate_overrides(overrides)
    except _config.OverrideError as e:
        raise errors.CollisionError(422, str(e)) from e


def apply_overrides(config: dict, overrides: dict, group: str) -> dict:
    """A deep copy of `config` with the `group` overrides applied (dotted keys). Each key must exist and keep its JSON type;
    else CollisionError 422 naming the key. The loaded config is never mutated."""
    try:
        return _config.apply_overrides(config, overrides, group)
    except _config.OverrideError as e:
        raise errors.CollisionError(422, str(e)) from e


def check_overrides(overrides: dict, collision_cfg: dict, worldmap_cfg: dict) -> None:
    """Validate against the loaded configs before any work starts."""
    try:
        _config.check_overrides(overrides, collision_cfg, worldmap_cfg)
    except _config.OverrideError as e:
        raise errors.CollisionError(422, str(e)) from e
