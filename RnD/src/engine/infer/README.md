# engine/infer -- GPU model wrappers

Inference wrappers moved out of the flat `segmentation.py`, `letterbox.py`, `models.py`, `depth.py`, `egoflow.py` and the
letterbox part of `geometry.py` (v26.3.0 p5-01). May import numpy, scipy, cv2, torch, ultralytics and the depth-model
packages (`BOUNDARIES.toml [models.infer]`) plus `engine.core`. The flat modules are pure facades.

**Fields written:** none.

## API

| module | names | legacy |
|---|---|---|
| `segmentation/letterbox.py` | `LetterboxMeta`, `letterbox_params` (pure math), `letterbox_with_meta` (cv2 resize) | `geometry.LetterboxMeta` / `geometry.letterbox_params`, `letterbox.letterbox_with_meta` |
| `segmentation/mapping.py` | `CLASSES`, `SAFETY_LEVELS`, `NUM_CLASSES`, `SKY_CLASS_ID`, `find_mapping`, `select_mapping`, `_load_mapping`, `_CONFIG_DIR`, `_CONFIG_PATH` | `segmentation.*` |
| `segmentation/grid.py` | `SegmentationGrid`, `_mask_padding_and_finish`, `parse_grid` (dead, kept verbatim), `grid_from_semantic_mask`, `extract_objects`, `_convex_hull`, `_4_CONNECTIVITY` | `segmentation.*` |
| `segmentation/model.py` | `SegmentationModel`, `load_detector`, `to_ultralytics` (torch / ultralytics at module level) | `models.*` |
| `depth/model.py` | `DepthModel`, `VARIANTS`, `VARIANT_DIRS`, `PROCESS_RES`, `DEFAULT_MODEL_ROOT` (torch at module level, variant packages lazy) | `depth.*` |
| `egoflow/flow.py` | `residual_flow`, `ResidualFlowTrack`, `LAG_FRAMES`, `GRAD_MIN`, `MIN_TEXTURED` | `egoflow.*` |

`segmentation/__init__.py` re-exports letterbox, mapping and grid names; `model` and `depth.model` are not re-exported
(they import torch): import them by module path.

## Invariants

- `NUM_CLASSES` / `SKY_CLASS_ID` are module globals of `mapping.py`, rebound by `select_mapping`. `grid.py` reads them as
  `mapping.<NAME>` at call time; the facade `segmentation.py` forwards them with a module `__getattr__` (never a copy).
  `CLASSES` / `SAFETY_LEVELS` are updated in place (`overlay.py` binds them at import time).
- `DepthModel` stays constructible with `__new__` (tests set attributes by hand).
- `models.py` / `depth.py` still import torch / ultralytics where they did before (module level); depth variant packages
  stay lazy inside the loaders. Tests replace `sys.modules["models"]` / `["depth"]`; the Lab imports those names lazily.
- Weights live under `~/models`, mounted at `/base-models`.
