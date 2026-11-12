# p1-08 engine.core.groundgeom (lens + per-frame ground geometry)

Goal: one home for the camera/ground geometry used by detection, depthscale, worldmap and surface.

## Moves
| from | legacy name | engine.core.groundgeom name |
|---|---|---|
| groundfuse.py | `Geometry`, `ray_dir`, `ground_z`, `ground_point`, `ground_pixel`, `lateral_at`, `ground_m` | same |
| groundfuse.py | `_pitch` | `pitch` (groundfuse alias `_pitch`) |
| collision.py | `_FrameGeo` | `FrameGeo` |
| collision.py | `_walking_axis_offset_m`, `_frame_geometry`, `_ground_dist`, `_lateral_of`, `_bottom_point`, `_ego_frame` | same without the leading underscore |

- `Geometry.roll` is mutated per frame by `run_collision`. It stays a plain mutable attribute; field and attribute names stay unchanged.
- Allowed lint-only edits (Opus pre-lint): in `ground_z` the unused unpacked `xn` becomes `_xn` (RUF059). Annotate the untyped parameters (`row_b`, `col_c`, `fwd`, `right`) as `float | npt.NDArray[np.float64]` and the returns accordingly.
- Do **not** unify the inline world↔ego rotations elsewhere (worldmap, blocked, pipeline). That's the later tasks, and only where the float order is byte-identical (audit 1.1 `_ego_frame` note).
- `_frame_geometry` reads `CollisionSettings` (p1-04). It may import `engine.core.settings`.

## Tests (Sonnet): `tests/engine/core/test_groundgeom.py`
- Identity of all moved names through `groundfuse` / `collision`, aliases included.
- `Geometry` built like the legacy tests do (tests/test_collision_v2623.py, tests/test_worldmap_v2627.py); fisheye and rectilinear; `roll` 0 and non-zero.
- For each projection, run `pitch`, `ray_dir`, `ground_z`, `ground_point`, `ground_pixel`, `lateral_at` and `ground_m` on scalar and small-array inputs, including rays above the horizon (nan) and a fisheye ray beyond 90°. Compare to the legacy function outputs with `np.testing.assert_array_equal` (`equal_nan=True`).
- `frame_geometry(...)` with arguments taken from a real `run_collision` call: find the call site, and build the inputs from the real config + `resolve_settings` + a fixture's grid size. The resulting `FrameGeo` must equal the legacy one field by field.
- `ground_dist`, `lateral_of`, `bottom_point` (tie: lowest row, then the column nearest the centre; include a tie case), `ego_frame`, `walking_axis_offset_m`: legacy literals.

## Implementation (Sonnet)
- `groundfuse.py` and `collision.py` re-export.
- Code in `groundfuse.py` that stays (Corrector etc.) keeps calling the names unqualified via the re-export import.

## Done
- `check.sh` green with `--related`.
