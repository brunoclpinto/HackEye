# p5-06 lab.api routers

## Moves
The endpoints of `lab/server.py` (audit 7.7) → `lab/api/<router>.py` as FastAPI `APIRouter`s: `system`, `recordings`, `config`, `runs`,
`collisions`, `worldmap`, `rundata`, `sounds`, `display`, `notes`, `issues`, `reviews`. Handler bodies verbatim. The caches
(`_wm_cache`, `_hz_cache`, `_grid_cache`, `_depth_cache` + locks and sizes) move with their router module and are forwarded from
`server` (tests patch `server._*_cache`). `server.py` stays the composition root: `app = FastAPI(...)`, lifespan, `_SelectiveGZip`, the
static mount, `include_router` in today's route order (route order matters for FastAPI matching), and the helpers `_collision`,
`_recording`, `_run` move to `lab/api/deps.py`. Only `lab.server` imports `lab.api`.

## Tests (Sonnet): `tests/lab/test_api.py`
- `[(r.path, sorted(r.methods)) for r in app.routes]` equals today's list, in order (print it from the legacy app).
- A `TestClient` smoke call per router on a tmp `LAB_DIR` fixture (the Lab API snapshots of the equivalence corpus cover bodies).
- `monkeypatch.setattr(server, "_hz_cache", ...)` is seen by the hazards handler.
