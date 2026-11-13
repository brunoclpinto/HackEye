# p2-08 engine.depthscale

## Moves (collision.py → engine/depthscale/)
| module | symbols |
|---|---|
| `anchors.py` | `_DepthAnchor`, `_InitialAnchor`, `_ground_anchor`, `_PlaneFit`, `_plane_fit`, `_PlaneAnchor` |
| `scale.py` | `_DepthScale`, `_item_depth_m`, `_ground_depth_distance` |

Engine names are public.

## Risks
- `_plane_fit` uses `RandomState(12345)` re-created per call: keep it.
- `_PlaneFit` is constructed positionally in tests: keep the field order.
- `_ground_depth_distance` writes `it.raw_depth_m`, `ground_m` and `dist_source`, and uses `engine.core.distfuse` / `groundgeom`.
- Pinned 8×.

## Tests (Sonnet): `tests/engine/depthscale/test_*.py`
- Identity.
- Field and attribute lists.
- Anchor update sequences on a fixture with depth maps (find one in the manifest of `tests/fixtures/equivalence`: the cases with depth modes). Pin the scale per frame.
- `plane_fit` on a synthetic plane with outliers: pin the result, and run it twice to show determinism.
- `item_depth_m` and `ground_depth_distance` on items from that fixture: pin the written fields.
