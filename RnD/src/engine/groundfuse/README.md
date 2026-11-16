# engine/groundfuse -- stateful estimators of the ground-fusion model

Per-run state for the distance of a base that stands on a surface (`distance.objectDistance`): the horizon jitter and
the range-correction curve fitted from the walking region. The stateless pieces (ground ray, `resolve`, `rho_at`) live
in `engine.core.groundgeom` / `engine.core.distfuse`; `src/groundfuse.py` is a facade that re-exports all of them.

**Fields written:** none (`Item` / `Track` fields, `engine.core.types.FIELD_WRITERS`).

## API (`estimators.py`, re-exported by the package)

| name | kind | purpose | legacy |
|---|---|---|---|
| `HorizonSigma` | class | `update(t, horizon) -> sigma rows`: std of the horizon track about its straight-line trend over `horizonWindowSeconds`, combined with `rowSigma` | `groundfuse.HorizonSigma` |
| `Corrector` | class | `update(t, region_mask, dmap, scale, horizon, sigma_rows, extra=None) -> dict | None`: fits `ref` and the rho(depth) curve per frame, log-EMA smoothed, held when samples are few | `groundfuse.Corrector` |
| `wmedian` | function | weighted median: first sorted value whose cumulative weight reaches half the total (stable sort) | `groundfuse._wmedian` |

Inputs/outputs: `Corrector.update` returns `{"ref", "sigmaRows", "curve": [[depth m, rho], ...]}` (rounded; plus
`"wallSamples": n` when wall samples joined) or None while there is no `ref`. `extra = (depth m, lens ground z m)` of
wall bases joins the range bins only, each counting `wallSampleWeight` towards `minBinSamples`.

## Config keys read (the `distance.groundDepth` block, via `engine.core.distfuse.settings`)

`horizonWindowSeconds`, `rowSigma` (HorizonSigma); `binEdgesM`, `minRowsBelowHorizon`, `emaSeconds`, `holdSeconds`,
`refGroundM`, `refMinSamples`, `fuseMaxM`, `wallSampleWeight` (optional, default 5), `minBinSamples`, `rhoMin`
(Corrector).

## Invariants

- State (`Corrector.ref`, `.bins`, `.prev_t`; `HorizonSigma.h`) and the `update` signature are pinned by tests and by
  `test_worldmap_v2627`.
- The curve is made monotone (the squash only grows with range) and floored at `rhoMin`.
- Package `__init__` does not export a name equal to a submodule (`estimators`).
- Imports only `engine.core.*`, numpy.

## Changelog (quoted from the `collision.py` docstring and the `groundfuse.py` docstring)

(`collision.py` docstring lines 1-185 have no line about these classes; the lines below are from the `groundfuse.py`
module docstring, kept there unchanged.)

> * ``Corrector``: per frame, the walking-region cells give two things, both in the units of the scaled depth (metres):
>   ``ref`` (q) = median depth / ground ray in the near field (``refGroundM``; ~1 when the camera height and the horizon are right) and the
>   **range correction** rho(d) = (depth / ground ray) / q, binned by depth. rho is ~1 in
>   the near field and falls beyond ~12 m (the squash). ``corrected = depth / rho(depth)``: the near field is unchanged. Bins and q are
>   smoothed in time (log EMA) and held when a frame has too few samples.
> * ``HorizonSigma``: the horizon jitter (rows) measured on the stored horizon track.
>
> The curve travels in the hazards.json frames (``depthCorrection``: ``{"ref", "sigmaRows", "curve": [[depth m, rho], ...]}``, rounded),
> and every consumer works from that rounded dict, so the offline map build reproduces the online one.

v26.2.7: `extra` wall samples join the range bins only (never `ref`), weighted by `wallSampleWeight`; the report gets
`"wallSamples": n` when n > 0.

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.3b Object distance and the horizon switch  (`distance.objectDistance`, `distance.useHorizon`; v26.2.3, `src/engine/groundfuse/`)

Per-run settings (§4, the Lab's Collision settings next to Camera side), `CollisionSettings.object_distance` / `use_horizon`, recorded in `hazards.json` `settings`. They apply to depth distances (`distanceSource` depth with a depth map). **One setting for the pass and the map:** the world map's object bases (§8.1) read `settings.objectDistance` / `useHorizon` and each frame's `depthCorrection` from `hazards.json`, so the map uses exactly what the pass used. A hazards file without the keys (older runs) means `depth` / `true`.
- `depth`: v26.2.2 (byte for byte; the golden hash of `chest0004_review7` is unchanged apart from the version and the two settings keys).
- `ground-contact`: a base that stands on a surface (not clipped, the pixel below it is a `worldmap.json` surface class) and is inside the band (>= `groundDepth.minRowsBelowHorizon` (4) grid rows below the horizon, ground ray <= `fuseMaxM`) takes the ground ray; else the depth.
- `ground+depth` (measured worse than `depth`, not the default): (1) **range correction**: the **ground ray** is the lens geometry (`groundfuse.ground_z`: the pixel's ray, equidistant fisheye or pinhole, the pitch the horizon row implies, the camera height `H` without any gait scale; it returns the z-depth of the ground point, the quantity the depth map holds). Per frame the walking-region cells (>= `minRowsBelowHorizon` rows below the horizon) give `ref` (q) = median(scaled depth / ground ray) over ground rays `refGroundM` (2-8 m) (~1 when camera height and horizon are right; 0.8 on the legacy-mount Chest-center-0004 settings) and the curve rho(d) = (depth / ground ray) / q binned by depth (`binEdgesM`, >= `minBinSamples` cells per bin, medians). The curve is log-EMA smoothed (`emaSeconds` 1 s), held `holdSeconds` (2 s) when a frame has too few samples, forced non-increasing and >= `rhoMin`; beyond the farthest fitted point `extrapolate` "prior" continues it with `priorCurve` (the measured DA2 squash) or "last" holds it. `corrected = depth / rho(depth)` (capped at `maxCorrectedM`); the near field is unchanged. Applied to every depth reading of items, movers included. (2) **fusion** of a base in contact inside the band: inverse-variance weights of the ground ray ( sigmaRows = sqrt(horizon jitter std over `horizonWindowSeconds` about its trend, `rowSigma` 0.5 row quantisation), turned into metres by the ground ray at row +- sigmaRows) and the corrected depth (sigma/D = `depthRelErr` (0.12) / max(rho, 0.25)); without contact or outside the band the corrected depth alone. (3) **sanity gate** (`groundDepth.gate`; `groundDepth.fuse` false = correction without fusion, for A/B): a base in contact (inside the band) is never nearer than `sanityFactor` (0.7) x its ground ray, else the ground ray wins; a base not on a surface is exempt (occlusion makes the ground ray an upper bound). Track depth histories (closing speed) stay on the raw depth.
- `useHorizon: false`: object distances use `depthScale x depth` only (no ground ray, no correction, no fusion); the world map's object bases use the depth and its surfaces are projected through the depth map (lens ray model, forward = z cos(pitch) - y sin(pitch) with the plane-fit pitch, pixel footprint splatted). **Kept on the horizon** (listed in DECISIONS v26.2.3): the horizon estimate itself, the pixel danger lane and the below-horizon / 30 m pre-filter of item detection, the ground-based tracking, items and bases with no depth (their ground fallback; map bases are dropped), the depth scale calibration (plane fit / gait anchors). `distanceSource` ground runs are unaffected.
- **Lens ground for items (v26.2.7, `distance.itemLens`):** `"depth"` (default): on a fisheye run an item with a depth distance takes its lateral from the lens ray of its base pixel at that distance (`groundfuse.lateral_at`, §8.1; the pinhole lateral was ~45 % too wide a quarter of the width off centre), where it used to rescale the pinhole lateral. The ground-distance fallback (no depth yet, clipped items) and ground-distance runs keep the pinhole `ground_distance_m` / `lateral_m` with the gait scale k (k is fitted on pinhole closings and already absorbs the lens factor; correcting both would apply it twice). `"all"`: also the ground distance of every contact row (detect_items, the lane part, the smoothed contact row) through the lens, on depth runs only (experiment). `"off"`: pinhole laterals as before. Rectilinear runs are unchanged in every mode (pinned by tests). The role caps in metres (`contextMaxLateralM` 2.5, `proximityLateralM` 2.6, `peopleSpeakLateralM` 2.75, `thinNoticeLateralM` 2.5, `beepLateralM` 0.9) were tuned on the pinhole lateral and are not retuned yet (DECISIONS v26.2.7). **Walls calibrate the depth:** `Corrector.update(extra=(depth, ground z))` takes the face-class bases that stand on a surface (`worldmap.face_contact_samples`) into the range bins (weight `groundDepth.wallSampleWeight` 5 each, never into `ref`), see §8.1.
- hazards: per item `distanceSource` (`depth | ground | fused`), `rawDepthM` (scaled depth before the correction), `groundM` (ground ray in depth metres, null outside contact / band) when the mode is not `depth`; per frame `depthCorrection` `{"ref", "sigmaRows", "curve": [[depth m, rho], ...], "wallSamples": n}` (rounded; absent when there is no `ref`; `wallSamples` (v26.2.7) only when wall bases joined the curve).
