# p3-12 engine.speech: text, context, walls

## Moves (collision.py → engine/speech/)
| module | symbols |
|---|---|
| `text.py` | `class TextMixin`: `_n`, `_join_clocks`, `_steps_txt`, `_fmt`, `_text`, `_plural`, `_kind`, `_entry`, `_words` |
| `context.py` | `class ContextMixin`: `clear_context`, `_key`, `_known`, `_mem`, `_seen_before`, `_register`, `observe_context`, `surface_adopted`, `memory_if_spoken` |
| `walls.py` | `class WallsMixin`: `note_wall`, `_known_wall`; free `_followed_wall` → `followed_wall`, `_passing_close` → `passing_close`, class `_WallFollow` → `WallFollow` |

`SpeechPolicy` stays in `collision.py` in this task and becomes `class SpeechPolicy(TextMixin, ContextMixin, WallsMixin)`, with the moved
methods deleted from its body. Method names keep their underscores (tests call `p._text`, `p._entry`, ...). Static/class methods keep their
decorators.

## Risks
- Mixin rules of p3-00 (bare annotations only, no `__init__`).
- Method resolution: no name is defined in two mixins; assert it in a test.
- `WallFollow.observe` writes `it.followed`.

## Tests (Sonnet): `tests/engine/speech/test_text_context_walls.py`
- `collision.SpeechPolicy._text is engine.speech.text.TextMixin._text` (and one per moved method; use `inspect.getattr_static` for static
  methods); identity of the three free names.
- `SpeechPolicy.__mro__` names in order `SpeechPolicy, TextMixin, ContextMixin, WallsMixin, object` (p3-13 extends it).
- `_text`, `_entry`, `_kind`, `_steps_txt` on ~15 stub items with `SpeechPolicy(CONFIG)`: pin the strings.
- `WallFollow` and `followed_wall` on the sequences of the existing `_WallFollow` tests; `passing_close` table.
