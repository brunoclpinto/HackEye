# engine/detection -- items from a class grid

Turns one semantic class grid plus the frame geometry into `Item`s (one per connected component of an item class, with
contact point, distance, bearing and clock). Imports only the stdlib, numpy, scipy and `engine.core`; no other model.

## items.py (v26.3.0 p2-07, moved from `collision.py`)

| name | kind | purpose | legacy |
|---|---|---|---|
| `detect_items` | function | components per class (4-connected, below the horizon) with contact geometry; ordered `ITEM_GROUPS` x class id x component label x pieces; a lane part follows its main item directly | `collision.detect_items` |
| `split_people` | function | cut a wide person / rider component into one piece per head (height-profile valleys, depth jumps); `None` when nothing is cut | `collision._split_people` |
| `tree_trunk` | function | does a `pole` component's top meet a vegetation canopy (a tree trunk, not a pole) | `collision._tree_trunk` |
| `lane_part_item` | function | extra item for the part of a wall / building that stands in the lane (`replace()` of the main item) | `collision._lane_part_item` |

Legacy names are re-exports of the same objects. The package `__init__` re-exports all four.

### Inputs / outputs
- `detect_items(grid, ids, geo, config, dmap=None) -> list[Item]`: `grid` int class ids, `ids` is `ClassIds`, `geo` is
  `FrameGeo`, `config` the collision config, `dmap` optional metric depth (m).
- `split_people(comp, r0, c0, geo, cfg, dmap, min_pixels, full=None)` -> `[(rows, cols, mask, col0, row0), ...]` or None.
- `tree_trunk(grid, veg_id, full_ref, cfg) -> bool`; `lane_part_item(main, rr, cc, geo, config) -> Item | None`.

### Config keys read
- `detect_items`: `minComponentFraction`, `geometry.maxRangeM`, `roles.laneBaseClasses`, `roles.staticSource`
  (`map` drops the lane part), `roles.alongPathRatio`, `personSplit.{enabled, classes}`,
  `tree.{enabled, poleClass, canopyClass}`.
- `split_people` (`personSplit`): `personWidthM` (0.55), `splitWidthFactor` (1.4), `minPieceM` (0.25), `valleyRows` (2),
  `valleyFrac` (0.08), `splitDepthJumpM` (0.0 = off; required when the depth jump is used).
- `tree_trunk` (`tree`): `gapRows` (2), `minOverlap` (0.5).
- `lane_part_item`: `roles.{laneBaseMinColumns, laneBaseMinRowColumns, laneBaseMinConcentration}`, `geometry.maxRangeM`.

### Invariants
- Item order drives everything downstream; do not reorder loops or pieces.
- `lane_part_item` uses `dataclasses.replace`, a shallow copy: arrays are shared with the main item. Keep it.
- `split_people` imports `scipy.signal.find_peaks` inside the function; keep the local scope.
- `detect_items`' local `k` (component label) is unrelated to `run_collision`'s `k`.
- Numerics are bit-identical to the pre-move code.
- No package-level `items` name: `engine.detection.items` stays the submodule.

### Known defect (latent, audit 5.8)
`split_people` reads `hgt` only assigned in the `full is not None` branch; with `full=None` the call raises
`NameError`. `detect_items` always passes `full`, so it is latent. Kept verbatim; `tests/engine/detection/test_items.py`
documents it with `pytest.raises(NameError)`.

### Changelog (from the `collision.py` docstring)
- "Things that run along the path (a wall's or median's base spans a long stretch of ..." -- items judged on where they stand on the floor.
- "A rider's position is the middle of its lowest row."
- "**Riders and vehicles approaching on or near the path are announced as early as possible** (``_fast_warning``: ..."
- "a pole under a canopy is a **tree** (``tree``)"; "hazards carry ``bboxFull`` / ``outlineFull`` (the whole component above the horizon too)." (v26.2.12)
- "a danger needs ``roles.minObstacleAreaM2`` (a 15 px blip is not an obstacle)."
- v26.2.10 `personSplit`: a person / rider component much wider than one person at its distance is cut into one piece per head
  (from the `detect_items` docstring, kept in the code).
- v26.1.16 follow-up: the part of a wall / building that stands in the lane (`lane_part_item` docstring).
