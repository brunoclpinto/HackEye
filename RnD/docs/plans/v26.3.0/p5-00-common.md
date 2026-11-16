# Phase 5 (Lab backend + engine.infer): rules shared by every p5 spec

Read this after [README.md](README.md) and the p2/p3/p4 common files. The Lab backend (`lab/*.py`, 3,806 lines; audit section 7) is
split into the packages `lab/store`, `lab/jobs`, `lab/stages`, `lab/features`, `lab/api` (BOUNDARIES.toml `[lab.packages.*]`), and the
flat model modules (`segmentation`, `letterbox`, `models`, `depth`, `egoflow`) move to `engine.infer`. The flat `lab/*.py` modules stay
as facades: every name tests, tools and the server reach today stays reachable on them (audit 6.2, 6.5, 7.2).

## Decisions (Opus, 2026-11-16)
1. **Forwarding facades for patched module globals** (plan decision 6, the fallback). Tests rebind module globals on the flat modules
   (`analysis._jobs`, `_active`, `_busy`, `_cancel_flags`, `_maintenance`, `_ensure_worker`, `LAB_DIR`, `list_models`, ...;
   `collisions._job`, `read_doc`, `collision_dir`; `server._*_cache`; `issues.CATALOGUE`; audit 6.2). A moved name is **deleted** from the
   flat module and forwarded to its one new home by a module subclass:
   ```python
   # lab/_forward.py (a flat helper, not a package)
   def install(module_name: str, forwards: dict[str, str]) -> None:
       """forwards: legacy name -> 'lab.pkg.module'. Reads and writes of those names on the flat module go to the home module."""
   ```
   implemented with `sys.modules[module_name].__class__ = <ModuleType subclass>` whose `__getattr__` / `__setattr__` / `__delattr__`
   forward the listed names (`monkeypatch.setattr` and its undo then rebind the home module's global). A name keeps its **legacy
   spelling** in its new home (no renames in Phase 5), so the facade maps name → module only.
   Code in the new packages that must see a patch reads the name **as a module attribute of its home** at call time
   (`queue._jobs.put(...)`, never `from lab.jobs.queue import _jobs`).
   The three `LAB_DIR` names stay independent, as today: `analysis.LAB_DIR` → `lab.store.runs.LAB_DIR`,
   `recordings.LAB_DIR` → `lab.store.recordings.LAB_DIR`, `reviews.LAB_DIR` → `lab.features.reviews.LAB_DIR` (each its own global,
   initialised from the same path as today).
2. **`lab.stages` calls the patched engine entry points through the legacy facades** (revises plan decision 7): `collision.run_collision`,
   `collision.resolve_settings`, `collision.load_config`, `worldmap.load_config`, `worldmap.build`, looked up on the facade module at call time
   (tests patch these attributes; audit 6.2/6.3). The boundary scanner restricts only imports between the declared lab packages, so this is
   allowed. The model wrappers are imported lazily by their flat names `models`, `depth`, `segmentation`, `egoflow` (tests replace
   `sys.modules["models"]` / `["depth"]`), which are facades of `engine.infer.*` after p5-01.
3. **`JobContext` lives in `lab.store.jobctx`** (plan decision 8): `check_cancel()`, `progress(p)`, `finish(**fields)`; the worker builds one
   per job and passes it to the stage; `Cancelled` is a store type.
4. **No behaviour changes**: HTTP routes, status codes, JSON bodies, file layout under `LAB_DIR`, thread model and lock order stay as they
   are. The Lab API snapshots of the equivalence corpus and the staging E2E guard it.

## Order
p5-01 (engine.infer) is independent of the lab tasks. Then p5-02 store → p5-03 jobs → p5-04 stages → p5-05 features → p5-06 api,
p5-07 tools, p5-08 the remaining skips. Lab tasks touch `analysis.py` / `collisions.py` / `server.py`: one at a time.
