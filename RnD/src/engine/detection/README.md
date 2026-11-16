# engine/detection -- items from a class grid

Turns one semantic class grid plus the frame geometry into `Item`s (one per connected component of an item class, with
contact point, distance, bearing and clock). Imports only the stdlib, numpy, scipy and `engine.core`; no other model.

**Fields written** (`engine.core.types.FIELD_WRITERS`): owns `Item.group`, `Item.class_name`, `Item.bbox`, `Item.contact_y`, `Item.distance_m`, `Item.lateral_m`, `Item.bearing`, `Item.clock`, `Item.pan`, `Item.area_frac`, `Item.clipped`, `Item.touches`, `Item.lane_hit`, `Item.along_path`, `Item.lane_cover`, `Item.contact_y_raw`, `Item.area_m2`, `Item.landmark`, `Item.people`, `Item.fast`, `Item.thin`, `Item.shape`, `Item.clock_q`, `Item.clock_text`, `Item.depth_cells`, `Item.lane_part_weak`, `Item.lane_part`, `Item.base_row`, `Item.base_col`, `Item.tree`, `Item.full_ref`.

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

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.4 Items — items from the class grid

- 4-connected components of **each class** (not each group) of the `static`, `moving` and `feature` groups, only over rows whose bottom edge is below the horizon, with ≥ `minComponentFraction × grid area` pixels. A pole against a wall is two items.
- **People that touch are separate items (v26.2.10, `personSplit`; `collision._split_people`):** a semantic model has no instances, so several people standing together are one `person` / `rider` component. When the component is wider than `splitWidthFactor` (1.4) × the image width of a `personWidthM` (0.55 m) person at the distance of its lowest pixel, it is cut into column pieces, each an item of its own (own bbox, outline `shape`, distance, lateral, track). Cut candidates: the valleys between heads of the component's column height profile (the top edge per column of the whole component, including the part above the horizon; no smoothing, a head is 2-3 columns wide; a head peak needs a prominence of `max(valleyRows (2), valleyFrac (0.08) × height)` rows), and, with a metric depth map (`detect_items(..., dmap)`; not with a relative one), the depth jumps between neighbouring column groups of more than `splitDepthJumpM` (0.6 m, median depth per column). Pieces narrower than `minPieceM` (0.25 m, and at least 3 grid columns: a component under 8 columns is never cut, far people stay one item) are merged into their narrower neighbour; a piece keeps its largest 4-connected part and is dropped under the component pixel minimum. `personSplit.enabled: false` restores one item per component.
- **Contact point:** static/moving = the component's lowest pixel (on that row, the column nearest the image centre); feature = its lowest pixel *inside the danger lane* if any, else the lowest pixel. Compute `distanceM`, `lateralM`, `bearingDeg`, `clock`, `clockQ`/`clockText` (quarters), `pan` (`sin(bearing)`, clamped) there. Drop items with `distanceM > maxRangeM` or no distance.
- **Danger lane:** half-width at a row = `laneHalfWidthM` in metres projected to pixels at that row's distance. `lane_hit` for static/moving = the component's lowest row itself touches the lane inside the (dilated) walking region (a car beside the path whose roof intrudes does not count); for features = any pixel in the lane. `lane_cover` = share of the lane's width at the contact row that the feature covers.
- `touches` = any pixel in the walking region dilated by `boundaryMarginPx`. `clipped` = the component touches the bottom image edge (its distance is only a lower bound).
- **Runs along the path:** look at the component's *base* pixels (those with walking region directly below them). If the base's near/far distance ratio is < `alongPathRatio` (0.5), the item spans a long stretch of path (a wall, median or curb alongside): it is boundary, never danger and never a lane-crossing feature. Also, a static/feature item whose raw closing speed is < 30 % of the raw ego speed (when that is ≥ 0.5 m/s) is treated as running along the path.
- **Lane part** (v26.1.16 follow-up, review 8 10.9 s): a wall/building whose side runs along the path and whose face juts into the lane is ONE component measured at its lowest pixel (the side wall's base: context). For static items of `laneBaseClasses` whose main item is not a lane hit (or runs along the path) an **extra item** is emitted: its *ground base* = component pixels with walking region directly below (`floor_below`) that lie in the lane inside the walking region (pixels above such a base never count; "any pixel over a lane cell" made every wall along a sidewalk beep). With ≥ `laneBaseMinColumns` columns of it the item has contact at the lowest base cell (on that row the column nearest the lane centre), `lane_hit` true, `along_path` false, `lane_cover` on that row, area / outline / bbox of the whole component, `lane_part` true. It has its own track (own id range from `1000000`, so ordinary track ids do not shift; never matched with the side wall's track) and its depth is read under the base cells. It is a danger (§7.9) only if: the base is flat (`laneBaseMinRowColumns` / `laneBaseMinConcentration`; a non-flat base continues a flat one for `laneBaseHoldSeconds`), the track is ≥ `laneBaseMinAgeSeconds` old, the ego speed is known and its raw closing ≥ `laneBaseMinClosingMps`; otherwise role `none` (context stays the side wall's). Not a speed witness (`_pole_like`).
- `area_m2` = pixel count × (distance/f)².
- Distance, lateral and steps are read from a per-track **smoothed contact row** (`contactEma`); a clipped item has no smoothing.

### 7.11d v26.2.12 collision rules — trees

- **Trees** (`tree`: `enabled`, `poleClass`, `canopyClass`, `gapRows` 2, `minOverlap` 0.5, `label` `tree`): a `pole` component whose top (full component, rows above the horizon included) has vegetation in the `gapRows` rows above it over >= `minOverlap` of its columns is a trunk: `item.tree`, label `tree`, family vegetation, not thin.
