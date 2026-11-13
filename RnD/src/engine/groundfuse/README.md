# engine/groundfuse -- stateful estimators of the ground-fusion model

Per-run state for the distance of a base that stands on a surface (`distance.objectDistance`): the horizon jitter and
the range-correction curve fitted from the walking region. The stateless pieces (ground ray, `resolve`, `rho_at`) live
in `engine.core.groundgeom` / `engine.core.distfuse`; `src/groundfuse.py` is a facade that re-exports all of them.

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
