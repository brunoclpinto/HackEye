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
