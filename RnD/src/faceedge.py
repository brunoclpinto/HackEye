"""Face / edge test on the ego-centric fused world map (v26.2.2, phase A: measurement only, nothing judges on it yet).

A corridor cell of a static object family is either
  * an EDGE: it lies within ``edgeBandM`` (+ ``edgeBlurPerM`` x range) of the wall line of its side, and that line runs roughly parallel to
    the walking direction (|angle| <= ``maxLineAngleDeg``): the blurred line of a wall beside the path; or
  * a FACE: it is not an edge and it protrudes past its side's wall line toward the walking axis by >= ``faceProtrusionM``, or the cells
    around it run across the walking direction (principal axis >= ``crossAngleDeg`` from forward, elongation >= ``crossElongation``),
    or its side has no wall line at all (an isolated object such as a pole); else it is NONE (ambiguous, counts for neither).

Coordinates are the ego frame of ``worldmap.Observer``: ``fwd`` metres ahead, ``right`` metres to the right of the body line.
Wall line of a side: ``right = a + b * fwd`` (b = tan of the angle to the walking direction).
"""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

EDGE, FACE, NONE = 0, 1, 2
VERDICT_NAMES = ("edge", "face", "none")

DEFAULTS = {
    "enabled": False,
    "maxAheadM": 12.0,             # family cells considered
    "lineAheadM": 8.0,             # wall line fitted on cells 0..lineAheadM ahead
    "lineMaxSideM": 4.0,           # ...and at most this far to the side
    "lineMinCells": 15,            # inliers needed for a wall line
    "lineMinSpanM": 2.0,           # ...spread over this much forward distance
    "lineTrials": 80,
    "maxLineAngleDeg": 25.0,       # a wall line must run roughly along the walking direction
    "edgeBandM": 0.25,
    "edgeBlurPerM": 0.02,          # range-dependent blur added to the band
    "faceProtrusionM": 0.3,
    "crossRadiusM": 0.5,           # cells within this radius give the local orientation
    "crossAngleDeg": 45.0,
    "crossElongation": 2.0,        # sqrt(l1 / l2) of the local covariance, else no orientation
    "crossMinCells": 6,
    "minFaceCells": 3,             # a candidate is a face when at least this many of its corridor cells are
    "crossSideEdge": True,         # blur across the axis is judged against the other side's wall line
    "seed": 7,
}


def settings(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update(cfg or {})
    return out


def fit_line(fwd: np.ndarray, right: np.ndarray, cfg: dict, rng: np.random.Generator) -> dict | None:
    """Dominant near-parallel line ``right = a + b fwd`` of the cells: RANSAC (2-point hypotheses within the angle limit), then a
    least-squares refit on the inliers. Returns {"a", "b", "angleDeg", "n", "spanM", "rms"} or None."""
    n = fwd.size
    if n < cfg["lineMinCells"]:
        return None
    bmax = math.tan(math.radians(cfg["maxLineAngleDeg"]))
    band = cfg["edgeBandM"]
    blur = cfg["edgeBlurPerM"]
    tol = band + blur * fwd
    m = min(n, 600)
    sel = np.arange(n) if n <= m else rng.choice(n, m, replace=False)
    f, r, tl = fwd[sel], right[sel], tol[sel]
    i1 = rng.integers(0, len(sel), cfg["lineTrials"])
    i2 = rng.integers(0, len(sel), cfg["lineTrials"])
    df = f[i2] - f[i1]
    ok = np.abs(df) > 0.5
    if not ok.any():
        return None
    i1, i2, df = i1[ok], i2[ok], df[ok]
    b = (r[i2] - r[i1]) / df
    good = np.abs(b) <= bmax
    if not good.any():
        return None
    i1, b = i1[good], b[good]
    a = r[i1] - b * f[i1]
    res = np.abs(r[None, :] - (a[:, None] + b[:, None] * f[None, :]))
    cnt = (res <= tl[None, :]).sum(axis=1)
    k = int(np.argmax(cnt))
    a0, b0 = float(a[k]), float(b[k])
    inl = np.abs(right - (a0 + b0 * fwd)) <= tol
    for _ in range(2):                                   # least squares on the inliers, then re-select
        if inl.sum() < 2 or np.ptp(fwd[inl]) < 1e-6:
            break
        b0, a0 = (float(v) for v in np.polyfit(fwd[inl], right[inl], 1))
        b0 = max(-bmax, min(bmax, b0))
        a0 = float(np.mean(right[inl] - b0 * fwd[inl]))
        inl = np.abs(right - (a0 + b0 * fwd)) <= tol
    ni = int(inl.sum())
    span = float(np.ptp(fwd[inl])) if ni else 0.0
    if ni < cfg["lineMinCells"] or span < cfg["lineMinSpanM"]:
        return None
    rms = float(np.sqrt(np.mean((right[inl] - (a0 + b0 * fwd[inl])) ** 2)))
    return {"a": a0, "b": b0, "angleDeg": math.degrees(math.atan(b0)), "n": ni, "spanM": span, "rms": rms}


def fit_wall_lines(fam: np.ndarray, fwd: np.ndarray, right: np.ndarray, cfg: dict) -> dict:
    """Wall line per side ("left" / "right" of the walking axis) of the family cells ``fam`` (bool map)."""
    rng = np.random.default_rng(int(cfg["seed"]))
    out = {"left": None, "right": None}
    base = fam & (fwd > 0.0) & (fwd <= cfg["lineAheadM"]) & (np.abs(right) <= cfg["lineMaxSideM"])
    for side, sel in (("left", base & (right < 0)), ("right", base & (right >= 0))):
        out[side] = fit_line(fwd[sel], right[sel], cfg, rng)
    return out


def local_orientation(fam: np.ndarray, cell: float, cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """Per cell: (angle deg of the principal axis of the family cells within ``crossRadiusM`` from the forward direction, 0..90;
    -1 where the cells are too few or too round to give an orientation). Moments by box filters."""
    rad = max(1, int(round(cfg["crossRadiusM"] / cell)))
    size = 2 * rad + 1
    m = fam.astype(np.float64)
    rows, cols = np.mgrid[0:fam.shape[0], 0:fam.shape[1]]
    f = -rows.astype(np.float64) * cell                  # forward = up the map
    r = cols.astype(np.float64) * cell
    u = lambda x: ndimage.uniform_filter(x, size=size, mode="constant") * size * size
    n = u(m)
    safe = np.maximum(n, 1.0)
    mf, mr = u(m * f) / safe, u(m * r) / safe
    vff = np.maximum(u(m * f * f) / safe - mf * mf, 0.0)
    vrr = np.maximum(u(m * r * r) / safe - mr * mr, 0.0)
    vfr = u(m * f * r) / safe - mf * mr
    tr = vff + vrr
    det = np.sqrt(np.maximum(((vff - vrr) / 2.0) ** 2 + vfr ** 2, 0.0))
    l1, l2 = tr / 2.0 + det, np.maximum(tr / 2.0 - det, 1e-9)
    ang = 0.5 * np.degrees(np.arctan2(2.0 * vfr, vff - vrr))      # principal axis from the f axis, -90..90 (f up, r right)
    ang = np.abs(ang)
    valid = (n >= cfg["crossMinCells"]) & (np.sqrt(l1 / l2) >= cfg["crossElongation"])
    return np.where(valid, ang, -1.0), n


def classify(cand: np.ndarray, fam: np.ndarray, fwd: np.ndarray, right: np.ndarray, cell: float, cfg: dict,
             lines: dict | None = None, orient: np.ndarray | None = None) -> dict:
    """Face / edge / none for the cells of ``cand`` (bool map, a subset of the family cells ``fam`` in the corridor).
    Returns {"rows", "cols", "verdict" (EDGE/FACE/NONE per cell), "protrusionM", "lineDistM", "angleDeg", "reason", "lines"}."""
    cfg = settings(cfg)
    if lines is None:
        lines = fit_wall_lines(fam, fwd, right, cfg)
    if orient is None:
        orient, _ = local_orientation(fam, cell, cfg)
    rr, cc = np.nonzero(cand)
    f, r = fwd[rr, cc], right[rr, cc]
    n = rr.size
    prot = np.full(n, np.nan)
    ldist = np.full(n, np.nan)
    edge = np.zeros(n, dtype=bool)
    has_line = np.zeros(n, dtype=bool)
    for side, sign in (("left", -1.0), ("right", 1.0)):
        L = lines[side]
        if L is None:
            continue
        mine = (r < 0) if side == "left" else (r >= 0)
        lr = L["a"] + L["b"] * f
        d = np.abs(r - lr)
        pro = np.where(mine, sign * (lr - r), np.nan)             # + = past the line toward the axis
        ldist = np.where(mine, d, ldist)
        prot = np.where(mine, pro, prot)
        has_line |= mine
        edge |= mine & (d <= cfg["edgeBandM"] + cfg["edgeBlurPerM"] * f)
    # a cell on a side without a wall line, while the other side has one: it is blur that crossed the walking axis (edge when it lies in the
    # band of that line), else ambiguous (none) unless it runs across the path; only when there is no wall line at all is a cell a face by itself
    other = np.zeros(n, dtype=bool)
    if cfg.get("crossSideEdge", True):
        for side in ("left", "right"):
            L = lines[side]
            if L is None:
                continue
            mine = (r < 0) if side == "right" else (r >= 0)          # cells of the OTHER side
            if lines["left" if side == "right" else "right"] is not None:
                continue
            d = np.abs(r - (L["a"] + L["b"] * f))
            other |= mine
            edge |= mine & (d <= cfg["edgeBandM"] + cfg["edgeBlurPerM"] * f)
            ldist = np.where(mine, d, ldist)
        has_line |= other
    ang = orient[rr, cc]
    cross = ang >= cfg["crossAngleDeg"]
    protr = np.nan_to_num(prot, nan=-1e9) >= cfg["faceProtrusionM"]
    verdict = np.full(n, NONE, dtype=np.int8)
    reason = np.full(n, "", dtype=object)
    face = ~edge & (protr | cross | ~has_line)
    verdict[edge] = EDGE
    verdict[face] = FACE
    reason[edge] = "edge"
    reason[face & ~protr & ~cross] = "noline"
    reason[face & cross] = "cross"
    reason[face & protr] = "protrusion"
    return {"rows": rr, "cols": cc, "fwd": f, "right": r, "verdict": verdict, "protrusionM": prot, "lineDistM": ldist,
            "angleDeg": ang, "reason": reason, "lines": lines}


def summarize(res: dict, cfg: dict) -> dict:
    """The candidate's numbers: verdict, counts and the nearest face cell."""
    cfg = settings(cfg)
    v = res["verdict"]
    n_face, n_edge = int((v == FACE).sum()), int((v == EDGE).sum())
    out = {"verdict": "face" if n_face >= cfg["minFaceCells"] else "edge" if n_edge > 0 and n_face == 0 else "unsure",
           "cells": int(v.size), "face": n_face, "edge": n_edge, "none": int((v == NONE).sum())}
    if n_face:
        k = np.flatnonzero(v == FACE)
        j = k[int(np.argmin(res["fwd"][k] + 1e-3 * np.abs(res["right"][k]))) ]
        out["nearestFaceM"] = round(float(res["fwd"][j]), 2)
        out["nearestFaceRightM"] = round(float(res["right"][j]), 2)
        pr = res["protrusionM"][k]
        out["maxProtrusionM"] = None if np.all(np.isnan(pr)) else round(float(np.nanmax(pr)), 2)
        ag = res["angleDeg"][k]
        out["maxCrossAngleDeg"] = None if ag.max() < 0 else round(float(ag.max()), 1)
        out["reasons"] = sorted({str(x) for x in res["reason"][k]})
    ld = res["lineDistM"]
    out["minLineDistM"] = None if np.all(np.isnan(ld)) else round(float(np.nanmin(ld)), 2)
    pr = res["protrusionM"]
    out["maxProtrusionAllM"] = None if np.all(np.isnan(pr)) else round(float(np.nanmax(pr)), 2)
    return out


def lines_json(lines: dict) -> dict:
    return {s: (None if L is None else {"a": round(L["a"], 3), "b": round(L["b"], 4), "angleDeg": round(L["angleDeg"], 1),
                                         "n": L["n"], "spanM": round(L["spanM"], 1), "rms": round(L["rms"], 3)})
            for s, L in lines.items()}
