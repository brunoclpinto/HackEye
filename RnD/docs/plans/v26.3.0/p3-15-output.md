# p3-15 engine.output

## Moves (collision.py → engine/output/)
| module | symbols |
|---|---|
| `outline.py` | `OUTLINE_EPS_PX`, `OUTLINE_MAX_POINTS`, `_DIRS` → `DIRS`, `trace_outline`, `_dp_open` → `dp_open`, `simplify_polygon`, `item_outline`, `item_full` |
| `hazards.py` | `_lane_polygon` → `lane_polygon`, `_region_rows` → `region_rows`, `_hazard_json` → `hazard_json`, `_hazard_dict` → `hazard_dict` |

## Risks
- `hazard_dict` key order is the hazards.json order: verbatim.
- `hazard_json(it, gh, gw, full_all)` pinned by `test_collision_v26214`.

## Tests (Sonnet): `tests/engine/output/test_output.py`
- Identity of every name.
- `trace_outline` / `simplify_polygon` on 4 synthetic masks (square, L, ring, single pixel): pin point lists.
- `hazard_dict` / `hazard_json` on 3 stub items (minimal, full, with outline): pin the dicts **including key order** (`list(d.keys())`).
- `lane_polygon` on a `_frame_geometry` from the existing tests; `region_rows` on a small Region.
