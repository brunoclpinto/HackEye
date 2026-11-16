# features/transport

Playhead and player controls: seek, step, speed, play/pause, mute, the default range inputs, role chips, plus the player-side wiring
(video events, audio controls, overlay layer toggles, keyboard shortcuts).

Exports: `wire`, `seekTo`, `updateTime` (used by `app/bootstrap.js`).

**Bus handled:** `seek`, `sync-default-range`.
**Bus emitted:** `write-hash`, `audio-events-changed`.
**State read/written:** `S.pendingSeek`, `S.seekGen`, `S.rangeTouched`, `S.rec`, `S.roles`; `video`, `overlay`, `hazards`, `audio`, `worldmap`, `selection`, `timeline`, `reviews`.
