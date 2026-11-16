# features/timeline

Event timeline strip. Unchanged by p6-04 except how it is wired: `app/bootstrap.js` constructs it with `(t) => emit("seek", t)`.

**Bus emitted (from the callback in bootstrap):** `seek`.
Panel calls made on it by other features go through `state.timeline` (`set`, `setPlayhead`, `setRoles`).

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 9 Frontend — timeline

**Timeline:** speech ticks coloured by role (click near a tick snaps to it; click/drag seeks), beep episodes as bars coloured by role (older runs without `beeps` events show a tone-density heat row instead), the playhead. The role chips (context, surface, feature, danger, final; all on by default) filter the timeline and the review panel.
