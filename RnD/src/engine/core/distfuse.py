"""Stateless distance fusion: range-correction curve (rho), corrected depth, per-base distance."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

__all__ = [
    "MODES",
    "SRC_DEPTH",
    "SRC_FUSED",
    "SRC_GROUND",
    "SRC_NAMES",
    "correct_depth",
    "prior_interp",
    "resolve",
    "resolved_mode",
    "rho_at",
    "settings",
]

MODES = ("depth", "ground-contact", "ground+depth")
SRC_DEPTH, SRC_GROUND, SRC_FUSED = 0, 1, 2
SRC_NAMES = ("depth", "ground", "fused")


def settings(dist_cfg: dict[str, Any]) -> dict[str, Any]:
    """The ``distance.groundDepth`` block with defaults."""
    g = dict(dist_cfg.get("groundDepth") or {})
    d = {
        "minRowsBelowHorizon": 4.0,
        "binEdgesM": [1, 3, 5, 7, 9, 11, 12, 13, 14, 15, 16, 17, 18, 20, 24, 30],
        "minBinSamples": 25,
        "refGroundM": [2.0, 8.0],
        "refMinSamples": 80,
        "emaSeconds": 1.0,
        "holdSeconds": 2.0,
        "extrapolate": "prior",
        "priorCurve": [[5.8, 1.0], [12.7, 0.876], [14.4, 0.71], [15.1, 0.58], [16.0, 0.44], [17.6, 0.27]],
        "rhoMin": 0.2,
        "maxCorrectedM": 45.0,
        "depthRelErr": 0.12,
        "rowSigma": 0.5,
        "sanityFactor": 0.7,
        "fuseMaxM": 40.0,
        "horizonWindowSeconds": 3.0,
        "fuse": True,
        "gate": True,
    }
    d.update(g)
    return d


def resolved_mode(mode: str | None, use_horizon: bool | None) -> str:
    """The effective object distance: with the horizon off there is no ground ray at all."""
    if use_horizon is False:
        return "depth"
    return mode if mode in MODES else "depth"


def prior_interp(d: npt.NDArray[np.float64], cfg: dict[str, Any]) -> npt.NDArray[np.float64]:
    p = np.asarray(cfg["priorCurve"], dtype=float)
    return np.interp(np.log(np.maximum(d, 1e-6)), np.log(p[:, 0]), p[:, 1])  # type: ignore[no-any-return]  # numpy stub returns Any


def rho_at(d: Any, rep: dict[str, Any] | None, cfg: dict[str, Any]) -> npt.NDArray[np.float64]:
    """The range-correction factor at depth ``d`` (m): 1 without a curve, the nearest fitted point's value inside /
    below it, and beyond the farthest fitted point the last value continued by the prior (``extrapolate``
    "prior") or held ("last")."""
    d = np.asarray(d, dtype=np.float64)
    curve = None if rep is None else rep.get("curve")
    if not curve:
        return np.ones_like(d)
    c = np.asarray(curve, dtype=np.float64)
    ld = np.log(np.maximum(d, 1e-6))
    rho = np.interp(ld, np.log(c[:, 0]), c[:, 1])
    if cfg["extrapolate"] == "prior":
        far = d > c[-1, 0]
        if far.any():
            p_last = float(prior_interp(np.array([c[-1, 0]]), cfg)[0])
            ratio = prior_interp(d, cfg) / max(p_last, 1e-6)
            rho = np.where(far, c[-1, 1] * np.minimum(1.0, ratio), rho)
    return np.maximum(rho, float(cfg["rhoMin"]))  # type: ignore[no-any-return]  # numpy stub returns Any


def correct_depth(
    d: Any, rep: dict[str, Any] | None, cfg: dict[str, Any]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """(corrected depth m, rho): ``depth / rho(depth)``, capped at ``maxCorrectedM``."""
    d = np.asarray(d, dtype=np.float64)
    rho = rho_at(d, rep, cfg)
    return np.minimum(d / rho, np.maximum(d, float(cfg["maxCorrectedM"]))), rho


def resolve(
    d_dep: Any,
    ground: Any,
    sigma_g: Any,
    rows_below: Any,
    contact: Any,
    rep: dict[str, Any] | None,
    cfg: dict[str, Any],
    mode: str,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.int8]]:
    """Distance of each base: ``d_dep`` the scaled depth (m), ``ground`` its ground ray in depth metres and
    ``sigma_g`` its 1-sigma (m, from the horizon jitter and row quantisation),
    ``rows_below`` the base row's distance under the horizon (grid rows), ``contact`` the base stands on a surface.
    Returns (distance m, source code array).

    * ``depth``: the depth. ``ground-contact``: the ground ray for a base in contact inside the band (else the depth).
    * ``ground+depth``: the depth is range-corrected; a base in contact inside the band (rows_below >=
      minRowsBelowHorizon, ground ray <= fuseMaxM) is fused with the ground ray by inverse variance (ground:
      ``sigma_g``, depth: depthRelErr / rho of its distance); finally a base in contact cannot be nearer than
      ``sanityFactor`` x the ground ray: the ground ray wins."""
    d_dep = np.asarray(d_dep, dtype=np.float64)
    src = np.full(d_dep.shape, SRC_DEPTH, dtype=np.int8)
    if rep is None or mode == "depth":
        return d_dep.copy(), src
    rb = np.asarray(rows_below, dtype=np.float64)
    G = np.asarray(ground, dtype=np.float64)
    band = (
        np.asarray(contact, dtype=bool)
        & np.isfinite(G)
        & (rb >= float(cfg["minRowsBelowHorizon"]))
        & (G <= float(cfg["fuseMaxM"]))  # noqa: SIM300
    )
    if mode == "ground-contact":
        return np.where(band, G, d_dep), np.where(band, SRC_GROUND, SRC_DEPTH).astype(np.int8)
    d_cor, rho = correct_depth(d_dep, rep, cfg)
    with np.errstate(divide="ignore", invalid="ignore"):
        sg = np.maximum(np.asarray(sigma_g, dtype=np.float64), 1e-3)
        sd = d_cor * float(cfg["depthRelErr"]) / np.maximum(rho, 0.25)
        wg, wd = 1.0 / (sg * sg), 1.0 / (sd * sd)
        fused = (G * wg + d_cor * wd) / (wg + wd)
    if not cfg.get("fuse", True):  # variants: the range correction alone (and the gate)
        band = band & False
    dist = np.where(band, fused, d_cor)
    src = np.where(band, SRC_FUSED, SRC_DEPTH).astype(np.int8)
    gate = (
        (
            np.asarray(contact, dtype=bool)
            & np.isfinite(G)
            & (rb >= float(cfg["minRowsBelowHorizon"]))
            & (G <= float(cfg["fuseMaxM"]))  # noqa: SIM300
            & (dist < float(cfg["sanityFactor"]) * G)
        )
        if cfg.get("gate", True)
        else np.zeros(dist.shape, dtype=bool)
    )
    dist = np.where(gate, G, dist)
    src = np.where(gate, SRC_GROUND, src).astype(np.int8)
    return dist, src
