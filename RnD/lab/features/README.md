# lab/features -- reviews, notes, issues, sounds profile, display mapping, A/B compare

The small per-feature stores of the Lab and the collision A/B comparison. May import `lab.store` only (`BOUNDARIES.toml`:
`may_import = ["lab.store"]`, `engine = []`). Legacy flat modules (`segmentation`, used by `display`) stay as they are (audit 7.8).

## API

| module | names | legacy |
|---|---|---|
| `reviews.py` | `LAB_DIR`, `ReviewError`, `_RunData`, `_lock`, `_save`, `_load`, `_path`, `create`, `update`, `delete`, `list_annotations`, `recordings_with_reviews`, `count_for_collision`, `export`, `match_key`, the `_check_*` validators and constants | `reviews.*` |
| `notes.py` | `NotesError`, `MAX_CHARS`, `get`, `put` | `notes.*` |
| `issues.py` | `CATALOGUE`, `IssuesError`, `list_issues`, `update`, `reset`, `export_items` | `issues.*` |
| `sounds.py` | `SoundsError`, `FIELDS`, `get`, `put`, `reset`, `profile` | `sounds.*` |
| `display.py` | `DisplayError`, `MAPPING_RE`, `get`, `put`, `reset`, `default_opacity` | `display.*` |
| `compare.py` | `_flatten`, `_settings_diff`, `_events`, `_same`, `match_events`, `compare` | `collisions.*` |

`reviews`, `notes`, `issues`, `sounds`, `display` and `collisions` delete these names and forward each to its home through
`lab/_forward.py`, so `monkeypatch.setattr(issues, "CATALOGUE", path)` rebinds `lab.features.issues.CATALOGUE`.

## Inputs / outputs and invariants

- `reviews` keeps its OWN `LAB_DIR` (initialised from `recordings.LAB_DIR`, independent of `runs.LAB_DIR` and `recordings.LAB_DIR`);
  files are `LAB_DIR/reviews/<recId>.json`. `notes`, `issues`, `sounds`, `display` read `lab.store.recordings.LAB_DIR` at call time.
- `CATALOGUE` is `lab/issues.json` (one level above this package; maintained in git).
- Writes go through `lab.store.util._atomic_write_json`; each module has one `_lock`.
- `reviews` reads runs and collision docs through `lab.store.runs` / `constants` / `collision_docs`.
- `compare.match_events` is pure: greedy, nearest first, each event used once, within `MATCH_WINDOW_S`.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.16 Sound profile  (`lab/features/sounds.py`, `collision.resolve_sounds`; v26.1.16)

The Lab-wide pitch / duration / repeat interval of every notification sound and the speech speed. One profile for all browsers, stored server-side in `LAB_DIR/display/sounds.json` (`{"kinds": {kind: {field: value}}, "speechRate", "updatedAt"}`, **overrides of the defaults only**, no file at the defaults; it survives version wipes like the mask display, §11).
- **Kinds and defaults** (`collision.json` `tones.sounds`): `collision-left` 660 Hz, `collision-center` 880 Hz, `collision-right` 1100 Hz (80 ms; interval 0.5 s), `crosswalk-in` 330 Hz 600 ms (one tone, no interval), `crosswalk-out` 330 Hz 200 ms ×2 with a 120 ms gap, `proximity` 440 Hz soft double chirp (120 ms, period 1.2 s); `speechRate` **1.25** (v26.2.12; was 1.0; it also feeds the predictive-speech `dt`). A stored `speechRate` equal to the default is not an override: `sounds._read` drops it, `PUT` never stores it, and the tuner marks the default "(default)" next to the read-out (`#sndSpeechDef`, from `defaultSpeechRate`). Ranges (`soundRanges`): pitch 150–2000 Hz, duration 20–1500 ms, interval 0.05–5 s, speech 0.5–2.0; values are clamped, not refused.
- **`intervalS` means:** collision kinds — the repeat interval at 5 steps (the far end); the whole `bySteps` table is scaled by `intervalS / 0.5`, the continuous chunk is not. `crosswalk-out` — the gap between its two tones. `proximity` — the repeat period. `crosswalk-in` — unused.
- **Who reads it:** the collision pass (`lab.stages.collision.collision_pass` -> `run_collision(sounds=profile)`) bakes pitch, duration and interval into the tone events; the player re-applies pitch, duration and speech speed live (§9), so only an interval change needs `POST /api/runs/{id}/collision`. A run therefore carries the profile of its last pass in its events; the player's live profile wins for pitch and duration.
- **API:** `GET` / `PUT` / `DELETE /api/sounds` (§8).
