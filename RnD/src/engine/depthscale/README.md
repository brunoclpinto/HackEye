# engine/depthscale -- metric scale of the relative depth

Puts a depth map on a metric scale and turns it into item distances. `anchors.py` finds the per-frame (or one-shot)
scale of a relative / DA2 depth map from the ground under our feet; `scale.py` holds the gait-calibrated absolute
level of the anchored depth, the per-item depth and the ground+depth distance of an item. Imports only `engine.core`
(`types`, `groundgeom`, `distfuse`), numpy and the stdlib.

Legacy facade (same objects): `collision._DepthAnchor`, `_InitialAnchor`, `_ground_anchor`, `_PlaneFit`, `_plane_fit`,
`_PlaneAnchor`, `_DepthScale`, `_item_depth_m`, `_ground_depth_distance`.

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
