# p2-07 engine.detection

## Moves (collision.py → engine/detection/items.py)
`_split_people`, `detect_items`, `_tree_trunk`, `_lane_part_item` (public names without the underscore).

## Risks
- Item order (`ITEM_GROUPS` × class id × component label order × pieces; a lane part follows its main item directly) drives everything downstream.
- `replace()` aliasing in `_lane_part_item`: shallow copy, so arrays are shared with the main item. Keep it.
- `_split_people` has a latent `NameError` on `hgt` when `full is None`. Keep it verbatim, and add a test that documents the current behaviour (`pytest.raises(NameError)`), marked with a comment "latent defect, audit 5.8".
- The function-local `from scipy.signal import find_peaks` keeps its scope.
- `detect_items`' local `k` is not `run_collision`'s `k`.

## Tests (Sonnet): `tests/engine/detection/test_items.py`
- Identity.
- `detect_items` on 6 frames of 3 fixtures (`chest0004_review7`, `4929_review4`, `chest0002_crosswalk`). Build the arguments the way `run_collision` does: real config, `resolve_settings`, `frame_geometry`, class ids. Pin for each frame the ordered `(group, class_name, track-free label fields)` list, `distance_m` / `lateral_m` / `bearing` rounded with approx, and the count.
- `tree_trunk` and `lane_part_item` cases from the old tests (4 uses).
