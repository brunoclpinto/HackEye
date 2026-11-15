# p3-02 engine.worldmap.observer

## Moves (worldmap.py → engine/worldmap/observer.py)
`Observer` (whole class, all methods, the comment blocks above it).

Named renames per p3-00: `groundfuse.*` → `groundgeom.*` / `distfuse.*`; `focal_px`, `ground_distance_m`, `lateral_m` from `engine.core.geom`.
`helpers.face_contact_samples` (p3-01) now annotates `observer: Observer`.

## Risks
- Pinned by 5 test files; ctor `Observer(cfg, settings, kind, gh, gw, gd_cfg, class_names)` positional.
- Float order of the inverse ground projection: move verbatim, no algebra.
- `ob.geo`, `ob.gh`, `ob.gw`, `ob.cam_h`, `ob.ray_hidden`, `ob.orow`, `ob.oc`, `ob.cell`, `ob.fwd`, `ob.right`, `ob.size` are read from outside
  (collision `_bottom_distance`, `_hidden_fn`, `_StaticMap`): attribute names frozen.

## Tests (Sonnet): `tests/engine/worldmap/test_observer.py`
- Identity; the attribute list after `__init__` (sorted `vars()` keys) for the real config.
- `observe(...)` on one frame of a fixture (see how `tests/test_worldmap.py` / `test_worldmap_v2627.py` build an Observer from a fixture
  grid): pin digests of the returned arrays (shape, dtype, per-class cell counts, sum of the float layers with `approx(rel=1e-12)`).
- `object_bases` and `face_contact_samples` on the same frame: pin counts and the first/last sample.
