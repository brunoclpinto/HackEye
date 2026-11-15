# p3-01 engine.worldmap: config, pose, map helpers

## Moves (worldmap.py → engine/worldmap/)
| module | symbols |
|---|---|
| `config.py` | `load_config`, `class_kinds`, `UNKNOWN`, `KIND_IGNORE`, `KIND_SURFACE`, `KIND_OBJECT`, `KIND_MOVER`, the `default_config_loader` hook (p3-00) |
| `pose.py` | `PoseTracker`, `integrate_pose` |
| `helpers.py` | `face_contact_samples`, `frames_from_hazards`, `first_depth_scale`, `settings_from_hazards` |

`face_contact_samples` takes an `Observer` (annotation only): annotate it with a local `Protocol` or `Any` until p3-02.

## The one sanctioned non-verbatim edit: PoseTracker
`PoseTracker` composes `engine.core.pose.DeadReckoner` instead of `collision._WorldMemory`:
`self.wm = DeadReckoner(float(coll_cfg.get("memory", {}).get("speedHoldSeconds", 5.0)))`: `DeadReckoner(hold_s)` takes the hold
directly, and this is the exact expression `_WorldMemory.__init__` uses for `hold_s`. `advance` keeps calling
`self.wm.advance(float(t), dt, speed, h)` and returns `(self.wm.x, self.wm.y, h)`. `DeadReckoner.advance` is the verbatim pose part of
`_WorldMemory.advance` (same float order). The pruning part of `_WorldMemory.advance` never ran for `PoseTracker` (no entries), so the
pose is identical.
This removes the load-time import of `collision` from the worldmap code path.

## Facade
`worldmap.py` re-exports every moved name as the same object and installs the loader hook (p3-00). It still binds `collision` and
`groundfuse` as module attributes (keep the `import collision`, `import groundfuse` lines).

## Risks
- `load_config` is monkeypatched on the facade (conftest `_v2629_map_settings`). `WorldMap.__init__` (still in `worldmap.py` until p3-04)
  calls the unqualified `load_config()`; that keeps resolving to the facade's module attribute, so nothing changes for it in this task.
- `class_kinds` returns `max(len(class_names), 256)` entries: pin it.

## Tests (Haiku): `tests/engine/worldmap/test_config_pose.py`
- Identity of every moved name (`worldmap.X is engine.worldmap.<module>.X`).
- `class_kinds` on the real `worldmap.json` and the Chest-0004 class names (see `tests/test_worldmap.py`): length, the indices of each kind.
- `load_config()` keys; the hook: `engine.worldmap.config.default_config_loader()` returns the patched dict when `worldmap.load_config` is
  monkeypatched (proves the facade hook looks the attribute up at call time).
- `integrate_pose` on a 20-frame synthetic ego list (speed, heading changes, a stationary frame, a None heading): pin the (N, 3) array
  computed with the legacy `worldmap.integrate_pose` (exact equality).
- `frames_from_hazards`, `first_depth_scale`, `settings_from_hazards` on a small hazards dict (take one from `tests/fixtures`).
