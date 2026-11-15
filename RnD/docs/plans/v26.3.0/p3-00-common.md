# Phase 3 (map and decision): rules shared by every p3 spec

Read this after [README.md](README.md) and [p2-00-common.md](p2-00-common.md). Every Phase 2 rule still applies (verbatim moves, public
engine names, the same objects on the facade, allowed lint-only edits, README per model, characterisation tests, the gate). This file
adds only what is new in Phase 3.

## Legacy facades in this phase
- `worldmap.py`, `faceedge.py` and `worldtracks.py` become **pure facades** by the end of the phase, like `sensors.py` and `groundfuse.py`.
  Their module docstring stays (it is the changelog). Every name listed in audit 6.1 / "Facade requirements" stays reachable as the same object.
- `worldmap.py` must keep binding the names `groundfuse` and `collision` as module attributes (`tools/ground_diag.py` reads
  `worldmap.groundfuse`), and `load_config` as a **plain function attribute** (the conftest monkeypatches it).
- `collision.py` keeps every moved name as a re-export, as before.

## References to other legacy modules inside moved code
Moved code must not import a legacy module (`collision`, `groundfuse`, `worldmap`, `faceedge`, ...). These **named renames** are allowed:
- `groundfuse.<name>` → `groundgeom.<name>` (`Geometry`, `ground_z`, `ground_point`, `ground_pixel`, `lateral_at`, `ground_m`) or
  `distfuse.<name>` (`settings`, `resolved_mode`, `resolve`, `correct_depth`, `rho_at`, `MODES`, `SRC_*`), with
  `from engine.core import distfuse, groundgeom`. These are the same objects as today (checked by the existing facade tests), so the
  call is unchanged.
- `collision.focal_px` / `ground_distance_m` / `lateral_m` (imported by name today) → the same names from `engine.core.geom`.
- `faceedge.<name>` stays textually `faceedge.<name>`, with `from engine.worldmap import faceedge` at the top of the engine module.
- `_WorldMemory` in an annotation → `ObjectMemory` (from `engine.core.types`, added in p2-12).
Nothing else changes.

## The worldmap config loader (plan decision 5)
`engine.worldmap.config` owns `load_config(path=None)` (body verbatim, with `collision.find_common_dir()` →
`engine.core.paths.find_common_dir()`) and a module-level hook:

```python
def _default_loader() -> dict[str, Any]:
    return load_config()

default_config_loader: Callable[[], dict[str, Any]] = _default_loader
```

Engine code that today falls back to `load_config()` (`WorldMap.__init__`: `self.cfg = cfg or load_config()`) calls
`config.default_config_loader()` instead, looked up **on the module at call time** (`from engine.worldmap import config` and
`config.default_config_loader()`, never `from ... import default_config_loader`).

The facade `worldmap.py`:
```python
from engine.worldmap.config import load_config  # noqa: F401   (same object; the conftest patches this attribute)
import engine.worldmap.config as _wcfg

def _facade_loader() -> dict:
    return sys.modules[__name__].load_config()

_wcfg.default_config_loader = _facade_loader
```
So a monkeypatch of `worldmap.load_config` is seen by `WorldMap.__init__` exactly as today. `_StaticMap` keeps its `wmod` argument and calls
`wmod.load_config()`, unchanged (the pipeline passes the `worldmap` facade module).

## Mixins (staticmap, speech)
Classes that tests build with `__new__` and call private methods on (`_StaticMap`, `SpeechPolicy`) are split into **mixins composed on one
class**. Rules:
- The composed class keeps its legacy name on the facade, its `__init__` unchanged, and its MRO lists the mixins in the order the spec gives.
- A mixin has no `__init__` and no class-level values. For mypy it may declare, as bare class-level annotations (`cfg: dict[str, Any]`), the
  instance attributes its methods read; a bare annotation creates no attribute, so `__new__` tests see the same object state.
- Methods are looked up on the class (the `col._StaticMap.update = spy` test replaces a class attribute: `update` must be defined on, or
  inherited by, the facade class and never captured per instance).
- A mixin method calling a method of another mixin goes through `self`, as today.

## Order and parallelism
- Tests for all p3 tasks are written between the Phase 2 checkpoint and the first p3 implementation (red tests break the full suite).
- Implementation order: p3-01 → p3-02 → p3-03 → p3-04 → p3-05 → p3-06 → p3-07 → p3-08 (the worldmap chain), then p3-09 … p3-15.
- `worldmap.py`-only tasks (p3-02, p3-03, p3-04) and `faceedge.py` (p3-05) and `worldtracks.py` (p3-09) are disjoint from the
  `collision.py` tasks (p3-06 … p3-08, p3-10 … p3-15) and may run alongside one `collision.py` task. Two `collision.py` tasks never run at once.
