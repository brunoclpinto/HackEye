# p1-04 engine.core.settings

## Moves (collision.py -> engine.core.settings, same names)
- `CollisionSettings`, `resolve_projection`, `resolve_settings`, `AUTO_FISHEYE_HFOV_DEG`, `DISTANCE_SOURCES`, `OBJECT_DISTANCES`, `SIDE_SIGN`.
- `WARMUP_S`, `HORIZON_HOLD_S`, `MIN_TRACK_AGE_S`.
- `resolve_settings` may call `warn_once` / `log`: import them from `engine.core.log` (p1-01).
- `CollisionSettings` keeps its field order exactly. Tests construct it positionally; check with `grep -rn "CollisionSettings(" tests tools lab`.
- `resolve_settings` stays a module attribute of collision, because tests monkeypatch `collision.resolve_settings`. Code inside `collision.py` keeps calling it unqualified.

## Tests (Sonnet): `tests/engine/core/test_settings.py`
- Identity of every moved name through `collision`.
- `CollisionSettings` field names and order: `[f.name for f in dataclasses.fields(...)]` equals the legacy list (literal).
- `resolve_projection` for (None, 100), (None, 140), ("rectilinear", 140), ("fisheye", 60), and every other branch: legacy literals.
- `resolve_settings` with the real config `collision.load_config()` × mount {None, "left", "center", "right"} × hfov {None, 100.0, 140.0}: compare `dataclasses.asdict(...)` to legacy literals. Generate them with a script, keep them compact (a dict per case), and floats with `pytest.approx`.
- One case each for invalid or edge inputs that legacy handles: an unknown mount, a missing config section.

## Implementation (Sonnet)
- Pure move.

## Done
- `check.sh` green with `--related` (39 `resolve_settings` call sites).
