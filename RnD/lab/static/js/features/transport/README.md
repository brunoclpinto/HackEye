# features/transport

Playhead and player controls: seek, step, speed, play/pause, mute, the default range inputs, role chips, plus the player-side wiring
(video events, audio controls, overlay layer toggles, keyboard shortcuts).

Exports: `wire`, `seekTo`, `updateTime` (used by `app/bootstrap.js`).

**Bus handled:** `seek`, `sync-default-range`.
**Bus emitted:** `write-hash`, `audio-events-changed`.
**State read/written:** `S.pendingSeek`, `S.seekGen`, `S.rangeTouched`, `S.rec`, `S.roles`; `video`, `overlay`, `hazards`, `audio`, `worldmap`, `selection`, `timeline`, `reviews`.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 9 Frontend — transport

**Transport:** play/pause (Space), previous/next **analysed** frame (← / →; falls back to one video frame without a run), speed 0.25–2× (`[` / `]`), seek bar, `m` mutes all. Keyboard shortcuts are ignored while typing in an input, select or textarea.
