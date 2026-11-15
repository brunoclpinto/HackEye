# engine/output -- what a frame hands to the viewer

The per-item `hazards.json` dict (with its optional outline), the walking-lane polygon and the walking-region rows, plus
the outline tracing and Douglas-Peucker simplification behind them. Imports only the stdlib, numpy and `engine.core`
(`Item`, `Region`, `FrameGeo`, `round_opt`).

## API (re-exported by `__init__.py`)

`outline.py`:

| name | purpose | legacy |
|---|---|---|
| `OUTLINE_EPS_PX`, `OUTLINE_MAX_POINTS` | Douglas-Peucker tolerance (grid px) and the point cap | `collision.OUTLINE_EPS_PX`, `collision.OUTLINE_MAX_POINTS` |
| `DIRS` | east, south, west, north steps of the contour walk | `collision._DIRS` |
| `trace_outline(mask)` | outer boundary of a 4-connected component as pixel-corner vertices | `collision.trace_outline` |
| `dp_open(pts, eps)` | Douglas-Peucker on an open polyline: kept indices | `collision._dp_open` |
| `simplify_polygon(pts, eps, max_points)` | closed-polygon simplification; `eps` grows x1.25 until the cap fits | `collision.simplify_polygon` |
| `item_outline(it, gh, gw)` | normalised outline of the item's component, or None | `collision.item_outline` |
| `item_full(it, gh, gw)` | `(bboxFull, outlineFull)` of the whole component, rows above the horizon included | `collision.item_full` |

`hazards.py`:

| name | purpose | legacy |
|---|---|---|
| `hazard_dict(it)` | the hazards.json entry of one item (key order is the file's order) | `collision._hazard_dict` |
| `hazard_json(it, gh, gw, full_all)` | `hazard_dict` plus `outline`, `bboxFull`, `outlineFull` | `collision._hazard_json` |
| `lane_polygon(geo, lane_half_m, far_distance_m)` | walking-lane trapezoid in image coordinates | `collision._lane_polygon` |
| `region_rows(region, step)` | `[y, left, right]` rows of the walking region, bottom up | `collision._region_rows` |

## Inputs / outputs

- Pure functions of an `Item` (and the grid size); nothing is mutated. Outlines and boxes are normalised to 0..1 and
  rounded to 4 decimals.
- `hazard_json` adds `outline` only for items with a role, and `bboxFull` / `outlineFull` for every item with a shape
  when `full_all` is set (`output.fullAllItems`).

## Config keys read

None; the callers pass `lane_half_m`, `far_distance_m` and `full_all`.

## Invariants

- The twelve names are the same objects as the `collision` ones; the private names (`_DIRS`, `_dp_open`,
  `_lane_polygon`, `_region_rows`, `_hazard_json`, `_hazard_dict`) stay on `collision`.
- The key order of `hazard_dict` is pinned by the tests and by `hazards.json` consumers.
