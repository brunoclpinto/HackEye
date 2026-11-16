# features/hazards

Windowed hazards loader: holds the frames around the playhead and hands them to the panels.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 9 Frontend — windowed hazards

**Windowed hazards:** the page never loads the whole `hazards.json`. It holds the frames within ±90 s of the playhead, prefetches the next stretch when the playhead is within 30 s of the window's end, and refetches on a seek outside the window (failed fetches back off 3 s). Overlay, HUD and frame stepping use the window; the timeline and review panel use `events.json` (small).
