# p3-09 engine.worldtracks

## Moves (worldtracks.py → engine/worldtracks/tracks.py)
The whole module: `DEFAULTS`, `settings`, `_WT` → `WT`, `_rot` → `rot`, `_eig_radius` → `eig_radius`, `_interval` → `interval`, `WorldTracks`.
`worldtracks.py` becomes a pure facade keeping the old underscored names as aliases. `engine.worldtracks.__init__` exports `WorldTracks`,
`DEFAULTS`, and the module `tracks` (not the function `settings` under the package: submodule-name rule does not apply, but keep `settings`
reachable as `engine.worldtracks.tracks.settings`).

## Risks
- Association is greedy in `items` list order: verbatim.
- `WorldTracks.ms` uses a clock: not pinned.

## Tests (Sonnet): `tests/engine/worldtracks/test_tracks.py`
- Identity of every name; `WorldTracks` attribute list.
- The worldtracks fixture of `tests/test_worldtracks*.py`: a 30-step `step` / `lookup` sequence, pin per-step digests (count, ids, the first
  track's position / velocity / radius with `approx(rel=1e-12)`, `trusted` flags).
