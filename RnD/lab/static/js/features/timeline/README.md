# features/timeline

Event timeline strip. Unchanged by p6-04 except how it is wired: `app/bootstrap.js` constructs it with `(t) => emit("seek", t)`.

**Bus emitted (from the callback in bootstrap):** `seek`.
Panel calls made on it by other features go through `state.timeline` (`set`, `setPlayhead`, `setRoles`).
