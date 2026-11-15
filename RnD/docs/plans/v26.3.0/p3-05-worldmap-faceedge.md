# p3-05 engine.worldmap.faceedge (fold, plan decision 1)

## Moves (faceedge.py → engine/worldmap/faceedge.py)
The whole module: `EDGE`, `FACE`, `NONE`, `VERDICT_NAMES` (dead, moved verbatim and logged, decision 12), `DEFAULTS`, `settings`, `fit_line`,
`fit_wall_lines`, `local_orientation`, `classify`, `summarize`, `lines_json`. `faceedge.py` becomes a pure facade.

`engine.worldmap.__init__` must not re-export a function named `settings` (it would shadow nothing today, but keep the rule: export the
faceedge API as the submodule `faceedge`, not its functions).

## Risks
- `DEFAULTS["seed"]` seeds `np.random.default_rng` per `fit_wall_lines` call: pin results, never reseed.
- `_StaticMap` (still in `collision.py` until p3-06) calls `faceedge.<name>` on the legacy module: unchanged, the names are the same objects.

## Tests (Haiku): `tests/engine/worldmap/test_faceedge.py`
- Identity of every name.
- `fit_wall_lines`, `classify`, `summarize`, `lines_json` on the synthetic input of the existing `tests/test_faceedge*.py`: pin outputs from
  the legacy module.
