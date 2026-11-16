# features/classes

The Classes & safety levels panel (view-only).

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 9.3 Classes & safety levels panel  (`js/features/classes/classes.js`; view-only)

Collapsible panel under the Overlay panel. It changes **only how the mask is painted**. The shared safety mapping and the collision behaviour are untouched.
- **Levels table:** each safety level (0 ignored, 1 safe, 2 safe-ish, 3 danger, 4 death) with a colour picker and an opacity slider (0–1).
- **Classes table:** every class of the run's model (48), each with a show checkbox, its current level's colour swatch, and a level dropdown. Above it: a text filter, "Show all", "Show none" and "Reset to defaults" (with confirm; it calls the DELETE endpoints).
- **Saving:** edits preview instantly and are kept as an unsaved draft in localStorage (`hackeye.lab.classes.<mapping>`; only sections differing from the server).
  - **"Save class levels"** and **"Save level colours"** PUT their section to the Lab server (`display/<mapping file>.json`), so every device shows the same view.
  - Each button is enabled only with unsaved changes in its section. An "unsaved changes" marker and a Discard link show until it is saved.
  - On load, the server-saved view wins over defaults, and a differing local draft wins over the server (marked unsaved).
