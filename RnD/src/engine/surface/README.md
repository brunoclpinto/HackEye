# engine.surface

Surface model: the walking region (the surface group under the feet), the horizon estimated from it or from gravity,
and the trackers that decide surface changes and crosswalk enter / exit. Modules `region.py`, `horizon.py`,
`trackers.py`; imports only numpy, scipy, the stdlib and `engine.core` (`ClassIds`, `FOUR_CONNECTIVITY`, `Region`,
`Geometry`).

## Public API (legacy name in brackets)
- `walking_region(grid, ids, config) -> Region | None` (`collision.walking_region`).
- `smooth_bounds(prev, cur, alpha=0.5)` (`collision._smooth_bounds`): per-row EMA of region bounds.
- `estimate_horizon(left, right, config, bounds=(0, 1)) -> float | None` (`collision.estimate_horizon`).
- `HorizonGravity(cfg, gh, gw, hfov_deg, projection)` (`collision.HorizonGravity`): `update(t, pitch_deg, h_img, source)`.
- `SurfaceTracker(cfg)` (`collision._SurfaceTracker`): `note_evidence(t)`, `update(t, group)`.
- `CrosswalkTracker(cfg)` (`collision._CrosswalkTracker`): `update(t, fraction, stationary)`.
- `seed_fraction(grid, class_id, seed_box) -> float` (`collision._seed_fraction`).

## Inputs / outputs
- `walking_region`: class grid (rows x cols, class ids), `ClassIds`, config. Output: `Region` (group, label, bool mask,
  per-row `left` / `right` in 0..1, NaN on empty rows) or None when no surface class is in the seed box.
- `estimate_horizon`: the region bounds; output the horizon as a fraction of the frame height, or None when the fit is
  not credible (too few rows, lines do not converge upward, outside the valid range).
- `HorizonGravity.update`: gravity pitch and the image horizon; returns the horizon row fraction ("gravity" or "fused").
- `SurfaceTracker.update` returns `(old, new, announce)` when a new group is adopted, else None.
- `CrosswalkTracker.update` returns "enter" / "exit" on the deciding frame, else None.

## Config keys read
- `walking_region`: `surfaces.seedBox`, `surfaces.groups.<g>.label`.
- `estimate_horizon`: `geometry.minRegionRows`, `geometry.horizonValidRange`.
- `HorizonGravity` (`horizon` block): `levelTauS` (30), `gravityWeight` (0.5), `horizonValidRange` ([0.25, 0.75]).
- `SurfaceTracker` (`surfaces`): `windowSeconds` (10), `majority` (0.7), `minPersistSeconds` (8),
  `requireCrossingEvidence` (true), `announceFirstSurface` (false), `evidenceLookbackSeconds` (window), `evidenceLeadSeconds` (1e9).
- `CrosswalkTracker` (`crosswalk`): `enterFraction`, `enterSeconds`, `exitFraction`, `exitSeconds`.

## Invariants
- **Config key order is behaviour.** `walking_region` iterates `ids.surface_groups` (the JSON order of `surfaces.groups`)
  and keeps the first group on a tie of (max class count, group count); never sort the groups.
- `SurfaceTracker` picks `max(counts, key=...)` over an insertion-ordered dict: on a tie the first inserted group wins.
- A surface change needs the majority, the uninterrupted run and (unless disabled) a curb / crosswalk passed under the
  user; the first surface needs only the majority.
- Legacy names are the same objects; the Lab pipeline in `collision.py` calls them through the old names.

## Changelog lines from the `collision.py` docstring (quoted)
- Model: "**Walking region.** The surface under the feet is the largest hint about where the user can really go. We take the
  majority surface class in a small box at the bottom centre (the "seed"), flood-fill the 4-connected region of that
  surface group (plus markings, curbs, covers inside it) and call it the walking region. Per grid row its left/right
  bounds are the boundary."
- Model: "**Horizon from the region.** Parallel path edges converge at the horizon, so lines fitted to the region's left
  and right bounds intersect on the true horizon row. That removes the tilt/mount guess; the preset is only a fallback
  when the region is not a converging shape."
- v26.1.1: "A surface change needs persistence plus a curb/crosswalk crossing."
- v26.1.6 (stricter surface evidence): "A surface change is announced only when a curb or crosswalk really passed *under* the
  user (``_SurfaceTracker``, ``surfaces.passUnderRows``) and the new surface holds >= 70 percent of a sliding 10 s window;
  otherwise the old surface is kept silently (the region still follows the model)."
- "a surface change needs a lane-crossing curb / crosswalk that belongs to the change (``_SurfaceTracker``)."
- v26.1.14: "**Crosswalk enter / exit tones.** ``_CrosswalkTracker`` follows the crosswalk-class fraction of the surface seed
  box (bottom centre, under the user's feet): >= ``enterFraction`` for ``enterSeconds`` while walking = in, <=
  ``exitFraction`` for ``exitSeconds`` = out. Tone kinds ``crosswalk-enter`` (one deep, long tone) and
  ``crosswalk-exit`` (two deep short tones), ``tones.crosswalk``; the speech phrases are unchanged."
- v26.2.11 (`HorizonGravity`, `horizon.source` "gravity" | "fused"): the horizon row from the camera pitch of the gravity
  vector; the level is the slow average of (image horizon - gravity horizon); "fused" pulls the image horizon toward it
  by `gravityWeight`.
- "``WARMUP_S`` ... the horizon is the mean of the raw estimates so far (else the mount / body preset); the last good
  horizon is held ``HORIZON_HOLD_S`` when an estimate fails" (in `engine.core.settings`).
