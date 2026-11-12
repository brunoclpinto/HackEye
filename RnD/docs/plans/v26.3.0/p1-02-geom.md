# p1-02 engine.core.geom

Goal: move the pinhole helpers, `Box`/`iou` and the small numeric helpers into `engine.core.geom`.

## Moves
| legacy | engine.core.geom name |
|---|---|
| `collision.focal_px`, `collision.ground_distance_m`, `collision.lateral_m`, `collision.steps_to` | same names |
| `geometry.Box`, `geometry.iou` | same names (`collision.Box` is re-exported today too: keep it the same class) |
| `collision._r` | `round_opt` |

- `geometry.py` keeps `LetterboxMeta`, `letterbox_params`, `expand_box` and `_clamp_box` (bus CLI / infer later) and re-exports `Box` and `iou`.
- `collision.py` re-exports `focal_px`, `ground_distance_m`, `lateral_m`, `steps_to`, `Box`, `iou` (if it imports them today) and `_r = round_opt`.

## Tests (Haiku): `tests/engine/core/test_geom.py`
- Identity: `geometry.Box is geom.Box`, `collision.Box is geom.Box`, `geometry.iou is geom.iou`, `collision.focal_px is geom.focal_px`, and the same for the other moved names; `collision._r is geom.round_opt`.
- `focal_px(grid_w, hfov)` for (160, 100), (160, 140), (320, 60); `ground_distance_m` for 4 cases including the horizon-at-or-below-row case (find its guard in the source); `lateral_m` for 3 cases; `steps_to(d, step)` for d in {0, 0.7, 5.0} × step {0.7, 0.75}: all legacy literals.
- `Box`: construction, every property/method it has (read the class), equality/hash if it is frozen. `iou` for identical, disjoint, partial overlap and contained boxes.
- `round_opt(None, 2) is None`; `round_opt(1.23456, 2)` and `round_opt(-0.0049, 2)`: legacy literals.

## Implementation (Sonnet)
- Pure move.

## Done
- `check.sh` green with `--related` (the many `geometry`/`Box` users).
