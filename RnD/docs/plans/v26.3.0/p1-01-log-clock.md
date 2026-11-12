# p1-01 engine.core.log + engine.core.clock

Goal: move logging and clock/bearing helpers out of `collision.py` into `engine.core`. No behaviour change.

## Moves (collision.py -> engine)
| legacy name | engine | public name |
|---|---|---|
| `_WARNED` (set) | `engine.core.log` | `WARNED` (the SAME set object) |
| `_log` | `engine.core.log` | `log` |
| `_warn_once` | `engine.core.log` | `warn_once` |
| `bearing_deg`, `clock_from_bearing`, `clock_quarter`, `clock_text` | `engine.core.clock` | same names |
| `_quarter_of_hour` | `engine.core.clock` | `quarter_of_hour` |
| `_pan_from_bearing` | `engine.core.clock` | `pan_from_bearing` |
| `_side_of_clock` | delete | dead code (audit 1.1: no references); confirm with grep first |

- stderr output keeps the `[collision] ` prefix exactly.
- `collision.py` keeps every old name as a re-export alias of the same object. Code inside collision keeps calling the old names.
- Find `_WARNED` with `grep -n "_WARNED" src/collision.py` (the audit marks it as module state, section 5.4).

## Tests (Haiku): `tests/engine/core/test_log_clock.py`
- `log` writes `"[collision] <msg>"` + newline to stderr (capsys).
- `warn_once` prints once for a repeated message, and adds it to `WARNED`.
- Facade identity: `collision._WARNED is engine.core.log.WARNED`, `collision._log is log`, `collision._warn_once is warn_once`, `collision.clock_text is clock_text`, `collision._quarter_of_hour is quarter_of_hour`, `collision._pan_from_bearing is pan_from_bearing`, and likewise for `bearing_deg`, `clock_from_bearing` and `clock_quarter`.
- `bearing_deg` for x_norm in {0.0, 0.25, 0.5, 0.9, 1.0} × hfov {100.0, 140.0} × projection {"rectilinear", "fisheye"}: literals from legacy `collision.bearing_deg`.
- `clock_from_bearing` and `clock_quarter` for bearings {-180, -95, -60, -15, 0, 7.4, 7.6, 15, 44.9, 45, 90, 179.9}: legacy literals.
- `clock_text(q)` for q in 1..48 (every quarter value the legacy code accepts; check its docstring) and `quarter_of_hour(c)` for c in 1..12: legacy literals.
- `pan_from_bearing` for {-120, -30, 0, 30, 120}: legacy literals.

## Implementation (Sonnet)
- Allowed edits: imports; types; docstrings; the renames above; `int(math.floor(x))` may stay as is.
- `engine/core/__init__.py` re-exports nothing from these yet; use submodule imports, `from engine.core.clock import ...`.

## Done
- `check.sh --files src/collision.py src/engine/core/log.py src/engine/core/clock.py src/engine/core/__init__.py --tests tests/engine/core/test_log_clock.py --related` is green.
