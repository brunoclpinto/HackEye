# engine/depthscale -- metric scale of the relative depth

Puts a depth map on a metric scale and turns it into item distances. `anchors.py` finds the per-frame (or one-shot)
scale of a relative / DA2 depth map from the ground under our feet; `scale.py` holds the gait-calibrated absolute
level of the anchored depth, the per-item depth and the ground+depth distance of an item. Imports only `engine.core`
(`types`, `groundgeom`, `distfuse`), numpy and the stdlib.

Legacy facade (same objects): `collision._DepthAnchor`, `_InitialAnchor`, `_ground_anchor`, `_PlaneFit`, `_plane_fit`,
`_PlaneAnchor`, `_DepthScale`, `_item_depth_m`, `_ground_depth_distance`.

**Fields written** (`engine.core.types.FIELD_WRITERS`): owns `Item.depth_m`, `Item.depth_on`, `Item.depth_raw`, `Item.from_depth`, `Item.dist_source`, `Item.raw_depth_m`, `Item.ground_m`.

## anchors.py

| name | kind | purpose |
|---|---|---|
| `DepthAnchor` | class | per-frame scale, log-space EMA (`anchorEmaSeconds`), held `anchorHoldSeconds`; `update(t, dt, raw, cells)`, `value` |
| `InitialAnchor` | class | one-shot anchor: running median of valid ratios, frozen at `initialAnchorFrames`; `reset()`, `update`, `value` |
| `ground_anchor` | function | `(median of flat-ground z-distance / relative depth, cell count)` over walking-region cells |
| `PlaneFit` | dataclass | `height_units, pitch_deg, inliers, fraction` (field order pinned; tests build it positionally) |
| `plane_fit` | function | ground plane through the walking-region cells (RANSAC + least squares); None = invalid frame |
| `PlaneAnchor` | class | one-shot plane anchor: scale = camera height / fitted height; `update(fit)`, `value`, `pitch_deg`, `height_units` |

## scale.py

| name | kind | purpose |
|---|---|---|
| `DepthScale` | class | level `c` of the anchored depth: witness samples (`sample`), windowed median, log-space blend, slew limit (`update`), `value`, `holding` |
| `item_depth_m` | function | median metric depth under the lowest rows of an item; None without a valid pixel |
| `ground_depth_distance` | function | item distance from its scaled depth and the ground ray of its base (`distfuse.resolve`); sets `raw_depth_m`, `ground_m`, `dist_source` |

## Inputs / outputs

- Anchors take the walking `Region`, the depth map `dmap` (z-depth, any float dtype), the horizon row, grid size and
  focal length; they output a scale (or `PlaneFit`) and a cell count.
- `DepthScale.sample` takes the ego speed and `[(bearing deg, closing rate of the anchored depth)]`.
- `ground_depth_distance` mutates the `Item` (`raw_depth_m`, `ground_m`, `dist_source`) and returns the distance.

## Config keys read

- `distance.*` (`dist_cfg`): `anchorMinCells`, `anchorEmaSeconds`, `anchorHoldSeconds`, `initialAnchorFrames`,
  `initialAnchorMinFrames`, `planeRansacTol`, `planeRansacTrials`, `planeMinInlierFraction`, `planeMaxNormalDeg`,
  `depthLevelMinSamples`, `depthLevelRange`, `depthWitnessMaxBearingDeg`, `depthWitnessMinEgoSpeed`.
- `ego.*` (`ego_cfg`): `calibrationWindowSeconds`, `calibrationMinSamples`, `calibrationEmaMinSeconds`,
  `calibrationEmaSeconds`, `scaleMaxChangePerSecond`.
- `distance.groundDepth` (`cfg` of `ground_depth_distance`): `minRowsBelowHorizon` (the rest is read by
  `engine.core.distfuse.resolve`).

## Invariants

- `plane_fit` creates `np.random.RandomState(12345)` on every call: deterministic, never shared or reseeded.
- `PlaneFit` field order is pinned (`height_units, pitch_deg, inliers, fraction`).
- Instance attribute order of the four classes is pinned by `tests/engine/depthscale/test_depthscale.py`.
- The package re-exports every public name; no name equals a submodule name (`anchors`, `scale`).
- `collision.py` keeps calling the old private names unqualified (tests monkeypatch them).

## Changelog (quoted from the `collision.py` module docstring)

Only these docstring lines touch this model (the docstring itself is unchanged):

- v26.1.6: "**Gait-calibrated scale k.** The pinhole metres assume a camera height and field of view that are only
  roughly right (real footage: 2-4x too small). Walking gives a ruler: the median cadence times a prior step length
  (0.70 m) is the ego speed in real metres, the median of the witness-based raw ego speed is the same speed in model
  metres, and their ratio is k. All distances/laterals/areas are multiplied by k [...]; the raw closing speeds used for
  it stay uncalibrated, so there is no feedback loop. k is held while the user stands still and is 1 until the first
  estimate."
- "**Ego speed** is held when the cadence drops out (no witness guess), the cadence refine cannot leave its band,
  depth closing rates are put on the gait's scale [...]"

## Contract rules moved from `lab/CONTRACTS.md` (v26.3.0 Phase 7)

The rules below used to be sections of the Lab contract. Section references (`§n`) point to `lab/CONTRACTS.md`; `§7.x`, `§8.1` and `§9.x` live in the README that the index of `lab/CONTRACTS.md` names. Text is verbatim apart from file paths; legacy names (`collision._X`, `src/x.py`) are facades of the engine names.

### 7.3a Distance source  (`distanceSource`; experiment)

- **Bearings** (clock, pan) use the resolved `projection`; lane, lateral and ground distance stay the pinhole model.
- **Side offset:** an item's lateral relative to the body = camera lateral + `lateralOffsetM` (right-mounted +). The body lateral drives the lane mask, the drawn lane, lane hits, world memory and `lateralM`; bearings, clock and pan stay camera-based (the effect is under a quarter beyond ~1.3 m). The lane's offset is decided in one place (`_walking_axis_offset_m`), so that eye and head mounts — whose camera turns with the head — can later switch to a body (IMU) heading.
- **Anchor mode** (`lab.store.constants.DEPTH_ANCHOR` per variant, stored as `anchor` in `depth.npz`; precedence npz > variant > units default — `per-frame` for relative, `none` for metric):
  - `per-frame`: the ground anchor below, re-measured every frame.
  - `plane` (`_PlaneAnchor`, **DA2 default**): per frame, the walking-region cells (below the anchor horizon + `motionMinRowsBelowHorizon`) are back-projected with the depth z and the pixel ray. Rays follow `distance.depthRayModel`: `"lens"` (default: the resolved projection; fisheye equidistant `f = W / hfov_rad`) or `"pinhole"` (`f = (W/2)/tan(HFOV/2)`, as depth models are trained on pinhole images; measured worse on 4929). The real lens still drives bearings, clock and pan., and a plane `Y/Z = c/Z + a·X/Z + b` is fitted (deterministic RANSAC start, then least squares with 2.5× MAD rejection; valid: ≥ `anchorMinCells` inliers, inlier fraction ≥ 0.6, normal within 35° of down, plane below the camera). Camera height in depth units `h_d = c/√(1+a²+b²)`, pitch `asin(−b/√(1+a²+b²))` (+ = looking down). Scale `s = cameraHeightM / h_d`: running median from 3 valid frames, frozen at 6 (`recalibrateOnPathChange` resets). **No gait level** (`levelModeByAnchor.plane = none`); the gait estimator runs as a check only (`depthGaitCheck`: ≈ 1 when camera height and walking agree).
  - `initial` (`_InitialAnchor`, older DA2 runs' stored mode, superseded by `plane` for DA2 via `lab.store.constants.SUPERSEDED_ANCHORS`): the same per-frame ground ratio is collected over the first valid frames; usable as the running median from `distance.initialAnchorMinFrames` (3) valid frames, **frozen** at `distance.initialAnchorFrames` (6). Before 3 valid frames depth is unusable (ground fallback). `distance.recalibrateOnPathChange` (default false) restarts the collection after a path change.
  - `none`: metric metres as given (UniDepth, old Metric Large runs): `c × a = 1`.
- **Depth → metres** = `c × a × z` (single-image relative depth is right *within* a frame up to one scale — ~4 % vs Metric Large on 4929 — but that scale drifts frame to frame, median 7 %, p90 ~20 % per 1.7 s, so it is re-anchored every frame):
  - **Per-frame ground anchor `a_t`** (class `_DepthAnchor`): over walking-region cells ≥ `motionMinRowsBelowHorizon` rows below the anchor horizon, `a_t = median(g / rel)`, with `g = H·f / (row − horizon·gh)` the flat-ground z-distance at the **uncalibrated** camera height; needs ≥ `distance.anchorMinCells` (150) cells; log-EMA `distance.anchorEmaSeconds` (0.4 s ≈ 2–3 frames); held `anchorHoldSeconds` (2 s) when a frame has none, then depth is unusable (`depthM` null, depth mode falls back to ground). **Anchor horizon** `distance.anchorHorizon`: `"fixed"` (default: the mount preset's horizon row, no estimation jitter; it is only wrong while turning/pitching, which is accepted), `"estimated"` (the frame's smoothed horizon) or a row fraction.
  - **Level `c`** (class `_DepthScale`, dimensionless, gait-calibrated): depth witnesses are the pole-like static items of the ground speed witnesses (bbox height ≥ 3× width, not clipped, not along the path) within ±`distance.depthWitnessMaxBearingDeg` (40°). A static object's **z-depth** falls at exactly our speed `v = cadence × step length` (v ≥ 0.5 m/s) whatever its bearing, so each frame's sample is the median of `v / r`, `r` = the negative slope of the witness's *anchored* depth history (same ≥ 3 points / ≥ `motionMinSeconds` / latest-point rule). Estimator as `_Scale` (median over `calibrationWindowSeconds`, ≥ `distance.depthLevelMinSamples` (30), first estimate at once, log-EMA, slew ≤ `scaleMaxChangePerSecond`), clamped to `distance.depthLevelRange` [0.3, 5]. Before its first estimate `c` = the applied ground scale `k`, so depth is usable from the start.
  - Track depth histories hold anchored depth; `c` is applied at use (no feedback through `c`). Metric depth (older runs) uses `c × a_t = 1`. The ground scale and its witnesses never see depth.
  - ego: `depthAnchor` (`a`, the frozen one in `initial`/`plane` mode, or null), `depthAnchorMode`, `depthPitchDeg`, `depthCameraHeightUnits`, `depthGaitCheck` (plane mode; null otherwise), `depthLevel` / `depthLevelSource` (`prior | ground | gait | frozen`; the `initial` anchor freezes `c` at its first estimate, `distance.depthLevelPrior` default `ground`, no camera prior), `depthScale` (`c × a`, metres per depth unit, or null), `depthScaleSource` ∈ `gait | ground | prior | plane | metric | none`.
- With depth, each item gets `depthM` = `s ×` median depth over its component pixels in the lowest `distance.depthLowestRowsFrac` (0.25) of its rows, mapped onto the 120×68 grid (null if none). It is reported in every mode.
- `ground`: §7.3 unchanged; output equals no-depth output apart from `depthM`.
- `depth` (**Lab default**): distance = `depthM` (metres via `s`: the ground scale `k` is **not** applied); lateral = the ground lateral × depth/ground; steps = depth / step length. Items without `depthM` fall back to ground.
- Tracking and the ground gate still match on ground distances; depth is substituted after matching. There is no mixing: every item takes its distance from the selected source (ground, or depth with a ground fallback when it has no depth pixels). When an item's distance came from depth, its closing speed is the negative slope of the track's own depth history (same ≥ 3 points / ≥ `motionMinSeconds` / latest-point rule). The raw closing speeds that feed the gait calibration stay ground-based.
