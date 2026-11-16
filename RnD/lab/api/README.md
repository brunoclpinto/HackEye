# lab.api

The REST endpoints of the Lab as FastAPI `APIRouter`s (v26.3.0 p5-06). Handler bodies are the ones that lived in `lab/server.py`;
`server.py` stays the composition root (`app`, lifespan, `_SelectiveGZip`, the static mount, the router registration).

## Modules
| module | endpoints / contents |
|---|---|
| `deps` | `_collision()` (503 while `collision` cannot import), `_recording()`, `_run()` (404), `_coll_call`, `_cid` |
| `system` | `GET /api/version`, `POST /api/client-log`; `frontend_router`: `GET /`; `STATIC_DIR`, `VERSION_FILE`, `_last_wipe` |
| `recordings` | list, proxy build, `/media/{name}`, per-recording settings (+ validators) |
| `config` | `GET /api/config/collision`, `GET /api/models` |
| `runs` | submit, cancel, list, get |
| `collisions` | collision re-runs: start, cancel, list, compare, label, delete |
| `worldmap` | build, read, pose, cell, snapshot PNGs; `_wm_cache` / `_wm_lock` |
| `rundata` | windowed hazards, frame, `{name}.json`, mask / class-grid / depth PNGs, run classes; `_hz_*`, `_grid_*`, `_depth_*` caches |
| `sounds`, `display`, `notes`, `issues`, `reviews` | the feature endpoints (`lab.features`) |

## Invariants
- Route order equals the order the routes were registered in `server.py` (FastAPI matches in order): `server` appends each router's
  `routes` to `app.router.routes` in that order, with `GET /` last, before the `/static` mount. `include_router` is not used: this
  FastAPI wraps included routers in a lazy `_IncludedRouter`, which would change `app.routes`.
- Caches live in their router module and are read there as module globals; `server` forwards `_wm_*`, `_hz_*`, `_grid_*`, `_depth_*`,
  `_collision`, `_recording`, `_run`, `VERSION_FILE`, `_last_wipe` (`lab/_forward.py`), so `monkeypatch.setattr(server, "_hz_cache", ...)`
  rebinds the router's global. Code that must see a patch reads it as a module attribute (`rundata._hz_cache`).
- May import `lab.jobs`, `lab.stages`, `lab.store`, `lab.features` and the flat legacy modules (BOUNDARIES.toml); nothing imports `lab.api` but `lab.server`.
- HTTP behaviour (paths, status codes, bodies) is unchanged.
