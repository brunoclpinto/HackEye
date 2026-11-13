# p2-06 engine.surface

## Moves (collision.py → engine/surface/)
| module | symbols |
|---|---|
| `region.py` | `walking_region`, `_smooth_bounds` |
| `horizon.py` | `estimate_horizon`, `HorizonGravity` |
| `trackers.py` | `_SurfaceTracker`, `_CrosswalkTracker`, `_seed_fraction` |

Engine names are public: `smooth_bounds`, `SurfaceTracker`, `CrosswalkTracker`, `seed_fraction`.

## Risks
- `walking_region` ties are decided by the JSON key order of `surfaces.groups`. Config key order is behaviour, so never sort.
- `_SurfaceTracker` `max(counts, key=...)`: on a tie, the first inserted group wins.
- `HorizonGravity` builds `Geometry`; use `engine.core.groundgeom`.
- Pinned: `_CrosswalkTracker` 7×, `_seed_fraction` 5×.

## Tests (Sonnet): `tests/engine/surface/test_*.py`
- Identity.
- Attribute lists.
- `walking_region` on a fixture's class grids: 5 frames each of `chest0004_review7` and `chest0002_crosswalk`. Pin mask sums, the left/right bound digests and the chosen group.
- `estimate_horizon` on the same frames.
- `HorizonGravity` on synthetic gravity angles and on the real sensor series.
- Tracker sequences over 50 frames of a fixture: pin the state per frame (compact).
- A tie case for the tracker.
