# engine/core -- shared types and pure helpers

Shared types, constants and pure numeric helpers that every model may import. `engine.core` imports nothing from other
models (no `engine.<model>`, no legacy flat modules). Core modules import only the stdlib, numpy/scipy and each other,
as `engine.core.<mod>` (never `from engine.core import X`, so no cycle through the package).

Legacy names are re-exports of the **same objects** (`collision.Item is engine.core.types.Item`). The legacy column
below gives the facade name; a leading `_` is the legacy private alias.

## log.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `WARNED` | set[str] | process-wide warn-once memory | `collision._WARNED` |
| `log` | function | stderr line with the `[collision] ` prefix | `collision._log` |
| `warn_once` | function | `log` a message once per process | `collision._warn_once` |

## clock.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `bearing_deg` | function | pixel column -> bearing deg (+ right); rectilinear or fisheye | `collision.bearing_deg` |
| `clock_from_bearing` | function | bearing -> whole clock hour (9..12..3), clamped to +-90 deg | `collision.clock_from_bearing` |
| `clock_quarter` | function | bearing -> quarter-hour index (-12..12) | `collision.clock_quarter` |
| `clock_text` | function | quarter index -> spoken clock ("12", "12:15", "11:45") | `collision.clock_text` |
| `pan_from_bearing` | function | bearing -> stereo pan in [-1, 1] | `collision._pan_from_bearing` |
| `quarter_of_hour` | function | whole clock hour -> quarter index | `collision._quarter_of_hour` |

## geom.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `Box` | dataclass | top-left origin box (`x1, y1, x2, y2`), `w`, `h`, `area` (matches Box.swift) | `collision.Box`, `geometry.Box` |
| `iou` | function | intersection over union of two `Box` (0 if degenerate) | `geometry.iou`, `collision.iou` |
| `focal_px` | function | focal length in grid pixels, `(W/2) / tan(hfov/2)` | `collision.focal_px` |
| `ground_distance_m` | function | pinhole ground distance from the bottom-edge row (None above horizon) | `collision.ground_distance_m` |
| `lateral_m` | function | pinhole sideways offset `(x - 0.5) * W * d / f` | `collision.lateral_m` |
| `steps_to` | function | `distance / step length` | `collision.steps_to` |
| `round_opt` | function | `round(float(v), nd)`, None passes through | `collision._r` |

## paths.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `find_common_dir` | function | locate `common/`: env `HACKEYE_COMMON_DIR`, else `/common` (container), else the repo's `common/` | `common_paths.find_common_dir` (re-export), `collision.find_common_dir` |

## classes.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `FOUR_CONNECTIVITY` | constant (ndarray) | 4-neighbourhood structuring element | `collision._4_CONNECTIVITY` |
| `ITEM_GROUPS` | constant | `("static", "moving", "feature")` | `collision.ITEM_GROUPS` |
| `NO_DATA` | constant | 255: grid cell outside the analysed window (never a surface or item) | `collision.NO_DATA` |
| `ClassIds` | dataclass | config class names resolved to this model's ids: surface groups, `inside`, item groups, name list, people / fast / thin / landmark sets | `collision.ClassIds` |
| `resolve_class_ids` | function | config + class-name list -> `ClassIds`; unknown names warn once and are skipped | `collision.resolve_class_ids` |

## settings.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `HORIZON_HOLD_S` | constant (3.0) | keep the last good horizon this long when the estimate fails (not in the contract) | `collision.HORIZON_HOLD_S` |
| `WARMUP_S` | constant (1.5) | horizon is the mean of raw estimates until settled | `collision.WARMUP_S` |
| `MIN_TRACK_AGE_S` | constant (0.5) | a track must live this long before it may speak or beep | `collision.MIN_TRACK_AGE_S` |
| `AUTO_FISHEYE_HFOV_DEG` | constant (100.0) | `projection: auto` picks fisheye from this HFOV up | `collision.AUTO_FISHEYE_HFOV_DEG` |
| `DISTANCE_SOURCES` | constant | `("ground", "depth")` | `collision.DISTANCE_SOURCES` |
| `OBJECT_DISTANCES` | constant | `("depth", "ground-contact", "ground+depth")` | `collision.OBJECT_DISTANCES` |
| `SIDE_SIGN` | constant | `left -> -1`, `center -> 0`, `right -> +1` | `collision.SIDE_SIGN` |
| `CollisionSettings` | dataclass | resolved camera, body and distance settings (field order pinned) | `collision.CollisionSettings` |
| `resolve_projection` | function | `rectilinear` / `fisheye` pass through; None or auto -> fisheye from HFOV 100 deg | `collision.resolve_projection` |
| `resolve_settings` | function | config + explicit values -> `CollisionSettings` (mount preset, or body mode when `camera_location` / `user_height_m` is given) | `collision.resolve_settings` |

## config.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `load_config` | function | read `common/config/collision.json` (or the given path) | `collision.load_config` (plain attribute, see Invariants) |
| `OverrideError` | exception | malformed override or unknown key; the message is shown to the user | none (lab/ uses it through `engine.core.config`) |
| `value_kind` | function | JSON type name of a value: bool, number, string, list, object, null | none |
| `validate_overrides` | function | shape check of `{"collision": {...}, "worldmap": {...}}`; drops empty groups | none |
| `PENDING_KEYS` | constant (dict) | keys the Lab may send before the backend creates them, with their allowed values (v26.2.11) | none |
| `is_pending` | function | value is one of the allowed values of a pending key (type-exact) | none |
| `apply_overrides` | function | deep copy of a config with dotted-key overrides applied; each key must exist and keep its JSON type | none |
| `check_overrides` | function | apply to both configs to reject bad overrides before any work starts | none |

## pose.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `PoseLike` | Protocol | read-only view of a dead-reckoned pose (`x, y, theta, speed, speed_t, hold_s`) | none |
| `DeadReckoner` | class | pose `(x, y, heading)` with a latched walking speed (held `hold_s`); `advance()` integrates, or takes a corrected pose | none |

`DeadReckoner` is not wired into any model yet; only `tests/engine/core/test_pose.py` uses it. Wiring is planned with
the p2 memory / Phase 3 worldmap work.

## distfuse.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `MODES` | constant | `("depth", "ground-contact", "ground+depth")` | `groundfuse.MODES` |
| `SRC_DEPTH`, `SRC_GROUND`, `SRC_FUSED` | constants (0, 1, 2) | source codes of a distance | `groundfuse.SRC_*` |
| `SRC_NAMES` | constant | `("depth", "ground", "fused")` | `groundfuse.SRC_NAMES` |
| `settings` | function | the `distance.groundDepth` block with defaults (not re-exported at package level, see Invariants) | `groundfuse.settings` |
| `resolved_mode` | function | effective object-distance mode (use_horizon off -> `depth`) | `groundfuse.resolved_mode` |
| `prior_interp` | function | interpolate the prior range-correction curve | `groundfuse._prior_interp` |
| `rho_at` | function | range-correction factor at depth d (nearest fitted point; prior-extrapolated or held beyond) | `groundfuse.rho_at` |
| `correct_depth` | function | `depth / rho(depth)`, capped at `maxCorrectedM`; returns (depth, rho) | `groundfuse.correct_depth` |
| `resolve` | function | per-base distance and source code: depth, ground-contact, or ground+depth fusion with the sanity gate | `groundfuse.resolve` |

## groundgeom.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `Geometry` | class | lens and camera: grid size, HFOV, projection, camera height, roll | `groundfuse.Geometry` |
| `pitch` | function | camera pitch (rad) implied by the horizon row | `groundfuse._pitch` |
| `ray_dir` | function | normalised camera ray (x right, y down, z forward) of a grid position; nan for fisheye rays behind | `groundfuse.ray_dir` |
| `ground_z` | function | z-depth of the floor point seen at a grid position for a flat floor | `groundfuse.ground_z` |
| `ground_point` | function | floor point (forward, right) m in the camera's level frame | `groundfuse.ground_point` |
| `ground_pixel` | function | exact inverse of `ground_point`: floor point -> grid position | `groundfuse.ground_pixel` |
| `lateral_at` | function | right offset (m) of a pixel's ray at a forward distance | `groundfuse.lateral_at` |
| `ground_m` | function | ground ray in depth metres (`ref * ground_z`), optional 1-sigma | `groundfuse.ground_m` |
| `FrameGeo` | dataclass | everything derived from the horizon, shared by one frame's items (field order pinned) | `collision._FrameGeo` |
| `frame_geometry` | function | build `FrameGeo`: danger lane, dilated walking region, floor mask, lens geometry for fisheye | `collision._frame_geometry` |
| `walking_axis_offset_m` | function | lateral offset (m) of the walking axis from settings; the one place the lane direction is decided | `collision._walking_axis_offset_m` |
| `ground_dist` | function | forward distance (m) of a bottom-edge pixel; None at or above the horizon | `collision._ground_dist` |
| `lateral_of` | function | camera-axis lateral (m) of a pixel at a forward distance | `collision._lateral_of` |
| `bottom_point` | function | lowest selected pixel; on that row the column nearest the centre | `collision._bottom_point` |
| `ego_frame` | function | world (x, y) -> (forward, right) m of a pose `(x, y, heading deg)` | `collision._ego_frame` |

## types.py

| name | kind | purpose | legacy |
|---|---|---|---|
| `LANE_PART_ID_BASE` | constant (1_000_000) | first track id of lane parts of walls and buildings | `collision.LANE_PART_ID_BASE` |
| `POINT_ASPECT` | constant (3.0) | bbox height / width of a pole-like item | `collision.POINT_ASPECT` |
| `Region` | dataclass | walking region: `group`, `label`, `mask`, per-row `left` / `right` edges | `collision.Region` |
| `Item` | dataclass | one connected component of an item class in one frame (field order pinned; `__post_init__` fills clock fields) | `collision._Item` |
| `Track` | dataclass | an item followed across frames (field order pinned) | `collision._Track` |
| `trusted_track` | function | world-track lookup, returns the entry only if trusted | `collision._trusted_track` |

## Config keys read

Only the functions below read config. Paths are relative to the config dict passed in.

- `classes.py` (`resolve_class_ids`): `surfaces.groups.<g>.classes`, `surfaces.inside` (required);
  `classes.<static|moving|feature>`, `classes.people|fast|thin|landmark` (optional).
- `settings.py` (`resolve_settings`): `defaultMount`, `mountPresets.<m>.{cameraHeightM, horizon, depthLevelPrior?}`,
  `defaultHfovDeg`, `body.{defaultCameraLocation?, defaultUserHeightM, stepLengthRatio,
  cameraLocations.<loc>.{heightRatio, heightOffsetM?, horizon, sideOffsetM?}}`, `distance.objectDistance`,
  `distance.useHorizon`.
- `distfuse.py`: `settings(dist_cfg)` reads `groundDepth` (defaults in the function); `prior_interp`, `rho_at`,
  `correct_depth`, `resolve` read `priorCurve`, `extrapolate`, `rhoMin`, `maxCorrectedM`, `minRowsBelowHorizon`,
  `fuseMaxM`, `depthRelErr`, `sanityFactor` (`fuse`, `gate` optional, default true).
- `config.py`: `load_config` reads `common/config/collision.json` unless given a path; the override functions take the
  groups `collision` and `worldmap`.
- `paths.py`: env `HACKEYE_COMMON_DIR`. The other modules read no config.

## Invariants

- **Same objects.** Legacy facades re-export the core objects; they never copy them. Tests monkeypatch `collision.X`, so
  code that stays in `collision` calls these names unqualified.
- **Field order pinned.** The field order of `Item`, `Track` and `Region` (`tests/engine/core/test_types.py`),
  `FrameGeo` (`test_groundgeom.py`) and `CollisionSettings` (`test_settings.py`) is asserted via `dataclasses.fields()`.
  Legacy tests also build `collision._Item` / `_Track` positionally and with `__new__` (`src/engine/README.md`). Do not
  reorder, rename or insert fields.
- **`collision.load_config` stays a plain module attribute** (`src/collision.py`, re-exported from `engine.core.config`).
  `tests/conftest.py` replaces it in `pytest_configure` and reads the caller's module name. A call through another name
  bypasses the patch and changes pinned outputs. `worldmap.load_config` is a separate loader (`src/worldmap.py`), also
  patched by conftest.
- **Package re-export.** `engine/core/__init__.py` re-exports every public name from the modules' `__all__`, except
  `log` and `settings`. Both would shadow the submodules `engine.core.log` / `engine.core.settings` as package attributes
  (`mod.log` would become the function). Import them from the submodule. No name is exported by two core modules.
- **Import side effect.** Importing any `engine.core.*` module runs the package `__init__`, which imports `classes`
  (numpy) and `groundgeom` (scipy). Core therefore always loads numpy and scipy.
- **No cycles.** Internal edges: `classes -> log`, `settings -> log`, `config -> paths`, `groundgeom -> geom` (and
  `settings` under TYPE_CHECKING), `types -> clock` (and `geom` under TYPE_CHECKING). `log`, `clock`, `geom`, `paths`,
  `pose`, `distfuse` import no core module.
