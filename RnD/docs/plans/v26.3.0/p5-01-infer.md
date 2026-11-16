# p5-01 engine.infer (segmentation, letterbox, models, depth, egoflow)

## Moves
| from | to | notes |
|---|---|---|
| `src/letterbox.py`, `geometry.LetterboxMeta` / `letterbox_params` | `engine/infer/segmentation/letterbox.py` | `geometry.py` keeps `expand_box`, `_clamp_box` (bus only) and re-exports the moved names |
| `src/segmentation.py` | `engine/infer/segmentation/mapping.py` (mapping, `CLASSES`, `SAFETY_LEVELS`, `NUM_CLASSES`, `SKY_CLASS_ID`, `find_mapping`, `select_mapping`) and `grid.py` (`SegmentationGrid`, `_mask_padding_and_finish`, `parse_grid` (dead, moved verbatim, decision 12), `grid_from_semantic_mask`, `extract_objects`, `_convex_hull`) | decision 9: `NUM_CLASSES` / `SKY_CLASS_ID` / `CLASSES` / `SAFETY_LEVELS` stay module globals of `mapping.py` (rebound there with `global` by `select_mapping`); the facade `segmentation.py` forwards them with a module `__getattr__`, never a by-value copy |
| `src/models.py` | `engine/infer/segmentation/model.py` | `torch`, `ultralytics` imports stay where they are today (module level or lazy: verbatim) |
| `src/depth.py` | `engine/infer/depth/model.py` | `DepthModel` must stay constructible with `__new__` (tests) |
| `src/egoflow.py` | `engine/infer/egoflow/flow.py` | |

The flat modules become pure facades (docstring + re-exports, plus segmentation's `__getattr__`). `sys.modules["models"]` /
`sys.modules["depth"]` replacements in tests keep working because the Lab imports the flat names lazily (unchanged).

## Risks
- `overlay.py` binds `segmentation.CLASSES` at import time (audit 5.4): with the facade's `__getattr__`, `from segmentation import CLASSES`
  still returns the current object (it reads the attribute at import), unchanged behaviour.
- GPU tests (`test_depth_gpu`, `test_channel_order`) cover the model wrappers: run them with `HACKEYE_GPU_TESTS=1` at the Phase 5
  checkpoint (live Lab idle).

## Tests (Sonnet): `tests/engine/infer/test_*.py`
- Identity of every moved name through the facades; `segmentation.NUM_CLASSES` follows a `select_mapping` rebinding (call it with a
  second mapping's class names, compare, restore).
- `letterbox_with_meta` / `letterbox_params` / `parse_grid` / `grid_from_semantic_mask` / `extract_objects` on small synthetic arrays:
  pin results from the legacy functions.
- `residual_flow` / `ResidualFlowTrack` on synthetic frames; `DepthModel.__new__` attribute access as `tests/test_depth.py` does.
