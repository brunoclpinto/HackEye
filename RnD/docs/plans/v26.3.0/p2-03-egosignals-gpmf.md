# p2-03 engine.egosignals.gpmf (from sensors.py 28–255)

## Moves (sensors.py → engine/egosignals/gpmf.py)
`_FMT`, `_STREAMS`, `_klv`, `_numbers`, `parse_payload`, `split_payloads`, `_gpmd_stream`, `_utc_epoch`, `build`, `extract`, `hilights`, `concat`, `save`, `load`.
- Private names stay private inside gpmf. They are internal to the parser; the tests reach them through the facade, and `sensors._klv is gpmf._klv`.
- `extract()` shells out to ffmpeg/ffprobe through `subprocess`. Add `subprocess` and `json` (stdlib) as needed; BOUNDARIES allows the stdlib.
- After p2-02 and p2-03, `sensors.py` contains only re-exports.

## Risks
- `lab.recordings.sensors_for` calls `sensors.extract`, and a test patches it: grep `monkeypatch.*sensors`. Keep `sensors.extract` patchable. If lab code calls `sensors.extract` through the module attribute, nothing changes. If an engine function calls `extract` internally and a test patches `sensors.extract`, report it.

## Tests (Sonnet): `tests/engine/egosignals/test_gpmf.py`
- Identity.
- `parse_payload` / `split_payloads` / `build` on a tiny hand-made KLV byte payload (construct it the way existing tests do, if any; otherwise build bytes from `_FMT`) and on a real stored stream if a fixture has one.
- `save` / `load` round trip in `tmp_path`.
- `concat` and `hilights` on small inputs.
- `extract` is not run (it needs ffmpeg and a video); only check that it is callable.
