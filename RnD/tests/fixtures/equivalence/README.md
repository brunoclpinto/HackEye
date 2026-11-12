# Equivalence oracle corpus (v26.3.0)

What the Lab computed at v26.2.14 (before the modular refactor), recorded by `tools/equivalence.py capture`. Any later checkout is
compared against it with `tools/equivalence.py compare` (quick tier: `tests/test_equivalence_quick.py`, full tier:
`tests/test_equivalence_full.py`, comparator unit tests: `tests/test_equivalence_compare.py`).

```
cd RnD
docker compose run --rm --entrypoint python rnd tools/equivalence.py compare --quick           # ~1 min
docker compose run --rm --entrypoint python rnd tools/equivalence.py compare --report /tmp/drift   # full, ~5-6 min, writes drift.json + drift.txt
docker compose run --rm --entrypoint python rnd tools/equivalence.py compare --only crosswalk/w2    # cases whose key contains the text
docker compose run --rm --entrypoint python rnd tools/equivalence.py capture --out tests/fixtures/equivalence   # re-record (intended change only)
```

Only re-capture in the commit that intentionally changes behaviour, and say so in DECISIONS.md.

## Layout
- `manifest.json`: every case (frames, bytes), the skipped cases with the reason, the VOLATILE and geometry key lists.
- `cases/<fixture>__<window>__<mode>.json.xz`: hazards doc (+ world tracks, events, tones), canonical (floats rounded to 3 decimals).
  `*.wm.npz`: sampled world-map arrays (class grid; conf for the default mode; pose / align arrays).
- `labapi.json.xz`: the Lab API session snapshot.

## Cases
Every `tests/fixtures/*.npz` window x mode, with the real `collision.json` / `worldmap.json` (workers are spawned processes: the
pytest conftest patches never apply), CPU only, single-threaded, fixed seeds. Modes: `default`, `image` (source.mode), `depth`,
`ground` (ground-contact), `ground+depth`, `nopred` (speech.predictive off), `onepose_on` / `onepose_off`, `nosensors`, and the
worldtracks-fixture modes `wt_depth`, `wt_ground+depth` (v26.2.9 map settings, person split off).
Skipped (recorded in the manifest): depth modes on fixtures without depth maps, `nosensors` on fixtures without sensors, and every
non-default mode on windows longer than 40 s (run time). Non-default modes store the decision fields only (track id / label /
role / urgency / distance / bearing / ..., ego, a few world-track fields); events and tones are always complete. Bulky polygons
(`outline`, `outlineFull`, `faceEdge`, `faceEdgeLines`, `lane`, `rows`, `corridor`) are stored as digests everywhere.
The Lab API session builds a temporary LAB_DIR from chest0004_review9/w0 (a stub recording, no media), runs two collision runs via
the API (c1 default, c2 with an override), reviews, notes, and snapshots the GET answers (PNG bodies as length + sha256).

## Rules (violations make `compare` exit non-zero)
- speech / beeps: text, order, role, label exact; event types and counts exact; times (`t`, `tEnd`) within +-1 analysed frame.
- hazards: the same (track id, label, role) set in every frame; numbers within max(1e-3, 1e-4 * |v|).
- world map (sampled frames): class grid >= 99.9% identical cells per sampled frame; conf (/255, on cells with equal class) within 1e-3
  (i.e. exact); pose / align arrays as numbers. `ms` timing is never stored.
- Lab API: identical JSON (exact numbers) except the VOLATILE keys (timestamps, timings, paths, version strings).
- Not recorded at all: `collision.LAST_WORLD_TRACKS_MS`, worldmap `ms`, `version` / `collisionVersion` strings (a version bump is not drift).
The report lists, per case, the maximum drift per field (path with indices as `[]`) and every violation with its path.
