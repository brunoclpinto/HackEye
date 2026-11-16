# p5-07 tools on engine names

`RnD/tools/*.py` reach engine code through the facades (`import collision as col`, `col.LAST_WORLD_TRACKS_MS`, `worldmap.groundfuse`,
...). Switch each tool to the engine homes where the name is a plain function / class (`from engine.pipeline.glue import
LAST_WORLD_TRACKS_MS`, ...), keeping every facade name the tests rely on. Tools that call patched entry points in tests (`replay`,
`collision_score`, `worldtracks_fixtures` callers of `collision.load_config`: the conftest's caller-name logic, audit 6.3) keep calling
`collision.load_config` / `collision.run_collision` through the facade. `tools/ground_diag.py` keeps `worldmap.groundfuse`.

## Tests (Haiku): `tests/test_tools_imports.py`
- Each tool module imports cleanly; the names each tool reads exist and are the engine objects.
