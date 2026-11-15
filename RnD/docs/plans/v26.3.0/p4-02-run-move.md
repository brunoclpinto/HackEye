# p4-02 engine.pipeline.run (verbatim move of run_collision)

## Moves (collision.py → engine/pipeline/run.py)
`run_collision` → `run_collision` (same name, same signature, same defaults). `collision.run_collision is
engine.pipeline.run.run_collision`.

## Allowed edits
- **Imports:** every free name of the function (Opus scan, 2026-11-15) is imported from its engine home under the name the body uses
  (`from engine.tracking.velocity import closing_mps as _closing_mps`, ...), so the body text stays unchanged.
  - `groundfuse.<x>` → `groundgeom.<x>` / `distfuse.<x>` (core), or `engine.groundfuse` for `Corrector` / `HorizonSigma`: named renames.
  - `sensor_lib.<x>` → `imu.<x>` (`from engine.egosignals import imu`).
  - `worldtracks.<x>` → the same names from `engine.worldtracks.tracks` (`tracks.<x>` or an alias; say which).
  - The two function-local `import worldmap` statements are deleted; the body's `worldmap.<x>` resolves to
    `from engine import worldmap` at module level. Check that `engine.worldmap` exports every name the body reads (`class_kinds`,
    `KIND_SURFACE`, `KIND_OBJECT`, `face_contact_samples`, `WorldMap`, `load_config`) and that `StaticMap` reads only these from `wmod`.
  - `LAST_WORLD_TRACKS_MS`, `_bottom_distance`, `_hidden_fn`, `_predict_velocities` from `engine.pipeline.glue` (p4-01).
- **The one sanctioned line**, the first statement of the body:
  `if worldmap_config is None: worldmap_config = wm_config.default_config_loader()`, with
  `from engine.worldmap import config as wm_config`. Today both fallbacks (`... else worldmap.load_config()` for `surf_lut`, and
  `_StaticMap(..., wcfg=worldmap_config)` → `wmod.load_config()`) call the patched facade loader. With the hook they get the same dict,
  and engine code never reads the unpatched engine `load_config`. The two `else worldmap.load_config()` fallbacks stay verbatim (now dead
  when called with None).
- Annotations, lint-only edits per p2-00. `run.py` gets a file-level `# ruff: noqa: E501` (the body is long verbatim lines), but no
  code reformatting beyond `ruff format`.

## Risks
- `test_collision_v2621` replaces `col._StaticMap.update` on the class: `run.py` must instantiate `StaticMap` looked up at call time
  (the module-level imported class object is the same one, which is fine).
- About 30 tests call `run_collision` without `worldmap_config` and rely on the conftest's patched `worldmap.load_config`: the hook
  covers them (a test below checks it directly).
- `progress(i, n)` may raise (Lab cancel): unchanged.

## Tests (Sonnet): `tests/engine/pipeline/test_run.py`
- Identity (`collision.run_collision is run.run_collision`); `inspect.signature` pinned as a string.
- `engine.pipeline.run` binds no legacy module (`collision`, `worldmap`, `groundfuse`, `sensors`, `worldtracks`, `faceedge`) as a
  module attribute.
- Hook: with `monkeypatch.setattr(worldmap, "load_config", spy)` (spy returns the real config and records calls), one short
  `run_collision` call on a fixture window with `worldmap_config=None` calls the spy, and the hazards equal those of a call with the
  real config passed explicitly (exclude `ms`/version keys as the equivalence tool does: reuse `tools/equivalence.py` helpers if they
  are importable).
