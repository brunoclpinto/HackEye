"""Characterisation tests for engine.groundfuse.estimators (v26.3.0 p2-09).

Every expected literal was produced by running the legacy code (groundfuse.py) in the hackeye-rnd image on the
pre-move code, not computed by hand. The engine module is imported inside each test function: it does not exist yet.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

import groundfuse
from common_paths import find_common_dir

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "chest0004_review7.npz"
GH, GW, HFOV, CAM_H, HORIZON = 135, 240, 118.0, 1.3, 0.45


def _cfg() -> dict[str, Any]:
    cfg = json.loads((find_common_dir() / "config" / "collision.json").read_text())
    return dict(groundfuse.settings(cfg["distance"]))


def _scene() -> tuple[Any, npt.NDArray[np.bool_], npt.NDArray[np.float16]]:
    """Geometry, a walking-region mask from the ground ray (central columns, 1.5..22 m), 30 depth frames."""
    geo = groundfuse.Geometry(GH, GW, HFOV, "fisheye", CAM_H)
    rows, cols = np.mgrid[0:GH, 0:GW]
    z = groundfuse.ground_z(geo, rows + 0.5, cols + 0.5, HORIZON)
    mask = np.isfinite(z) & (z <= 22.0) & (z >= 1.5) & (cols > 50) & (cols < 190)
    npz = np.load(FIXTURE)
    return geo, mask, npz["w0_depth"][:30]


REP0: dict[str, Any] = {
    "curve": [
        [6.02, 1.138],
        [7.88, 0.981],
        [9.83, 0.902],
        [11.44, 0.828],
        [12.47, 0.811],
        [13.34, 0.768],
        [14.37, 0.71],
        [15.41, 0.674],
        [16.34, 0.652],
        [17.31, 0.615],
        [18.75, 0.556],
        [20.97, 0.51],
    ],
    "ref": 2.349,
    "sigmaRows": 0.5,
}


EXPECTED_HS = [
    0.5,
    0.5,
    0.5,
    0.8453022506579546,
    0.8152146372704253,
    0.8186323609314071,
    0.805703868518866,
    0.7757104166709247,
    0.769399730058112,
    0.8955473747324426,
    0.8730941175000086,
    0.8678279749036938,
    0.8656720817273926,
    0.8723397628983701,
    0.8537361900628239,
    0.838522183948178,
    0.8256328663890697,
    0.8571830390577136,
    0.8572471143301206,
    0.8674263774358976,
    0.8263646886067766,
    0.8635245654955004,
    0.8635697507434927,
    0.855902699120908,
]


def _horizon(k: int) -> float:
    return HORIZON + 0.004 * math.sin(k * 0.9)


def _walls(k: int) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]] | None:
    if k % 3 != 0:
        return None
    n = 12 + k
    return np.linspace(8.0, 18.0, n).astype(np.float64), np.linspace(9.0, 24.0, n).astype(np.float64)


def run_corrector(
    corrector: Any, frames: npt.NDArray[np.float16], mask: npt.NDArray[np.bool_], with_walls: bool
) -> list[Any]:
    out = []
    for k in range(len(frames)):
        sc = 1.0 + 0.01 * (k % 5)
        rep = corrector.update(
            k / 6.0, mask, frames[k], sc, _horizon(k), 0.6 + 0.01 * k, extra=_walls(k) if with_walls else None
        )
        out.append(rep)
    return out


def _digest(reps: list[Any]) -> str:
    return hashlib.sha256(json.dumps(reps, sort_keys=True).encode()).hexdigest()


def test_identity() -> None:
    import engine.groundfuse as pkg
    from engine.groundfuse import estimators as est

    assert groundfuse.HorizonSigma is est.HorizonSigma
    assert groundfuse.Corrector is est.Corrector
    assert pkg.HorizonSigma is est.HorizonSigma
    assert pkg.Corrector is est.Corrector
    assert est.wmedian is not None
    assert {"HorizonSigma", "Corrector"} <= set(pkg.__all__)


def test_attribute_lists_and_signatures() -> None:
    from engine.groundfuse import estimators as est

    cfg = _cfg()
    geo, _, _ = _scene()
    hs = est.HorizonSigma(cfg, GH)
    assert sorted(vars(hs)) == ["gh", "h", "row_sigma", "win"]
    cor = est.Corrector(cfg, geo)
    assert sorted(vars(cor)) == ["bins", "cfg", "edges", "geo", "gh", "gw", "hold", "min_rows", "prev_t", "ref", "tau"]
    params = list(inspect.signature(est.Corrector.update).parameters)
    assert params == ["self", "t", "region_mask", "dmap", "scale", "horizon", "sigma_rows", "extra"]
    assert list(inspect.signature(est.HorizonSigma.update).parameters) == ["self", "t", "horizon"]
    assert list(inspect.signature(est.wmedian).parameters) == ["x", "w"]
    assert cor._ema(1.0, 3.0, 0.25) == 1.5


def test_horizon_sigma_sequence() -> None:
    from engine.groundfuse import estimators as est

    hs = est.HorizonSigma(_cfg(), GH)
    got = [hs.update(k / 6.0, _horizon(k) + (0.01 if k % 4 == 1 else 0.0)) for k in range(24)]
    assert got == pytest.approx(EXPECTED_HS, rel=1e-12, abs=1e-12)
    assert len(hs.h) == 19
    hs2 = est.HorizonSigma(_cfg(), GH)
    assert [hs2.update(k / 6.0, 0.45) for k in range(3)] == pytest.approx([0.5, 0.5, 0.5], rel=1e-12, abs=1e-12)


def test_wmedian_cases() -> None:
    from engine.groundfuse import estimators as est

    cases = [
        ([3.0, 1.0, 2.0], [1.0, 1.0, 1.0]),
        ([3.0, 1.0, 2.0, 4.0], [1.0, 1.0, 1.0, 1.0]),
        ([5.0, 1.0, 2.0], [5.0, 1.0, 1.0]),
        ([5.0, 1.0, 2.0], [1.0, 1.0, 5.0]),
        ([2.0, 2.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]),
        ([7.0], [3.0]),
        ([0.5, 0.25, 0.75, 1.5, 1.25], [5.0, 5.0, 5.0, 1.0, 1.0]),
    ]
    got = [est.wmedian(np.array(x), np.array(w)) for x, w in cases]
    assert got == [2.0, 2.0, 5.0, 2.0, 1.0, 7.0, 0.5]
    assert all(type(g) is float for g in got)


def test_corrector_plain_30_frames() -> None:
    from engine.groundfuse import estimators as est

    geo, mask, frames = _scene()
    cor = est.Corrector(_cfg(), geo)
    reps = run_corrector(cor, frames, mask, False)
    assert [r is None for r in reps] == [False] * 30
    assert [None if r is None else (r["ref"], r["sigmaRows"], len(r["curve"])) for r in reps] == (
        [
            (2.349, 0.6, 12),
            (2.368, 0.61, 13),
            (2.395, 0.62, 14),
            (2.412, 0.63, 14),
            (2.432, 0.64, 14),
            (2.443, 0.65, 15),
            (2.459, 0.66, 15),
            (2.472, 0.67, 15),
            (2.489, 0.68, 15),
            (2.508, 0.69, 15),
            (2.493, 0.7, 15),
            (2.483, 0.71, 15),
            (2.495, 0.72, 15),
            (2.515, 0.73, 15),
            (2.537, 0.74, 15),
            (2.565, 0.75, 15),
            (2.59, 0.76, 15),
            (2.601, 0.77, 15),
            (2.611, 0.78, 15),
            (2.636, 0.79, 15),
            (2.62, 0.8, 15),
            (2.629, 0.81, 14),
            (2.652, 0.82, 14),
            (2.662, 0.83, 14),
            (2.662, 0.84, 14),
            (2.651, 0.85, 14),
            (2.662, 0.86, 14),
            (2.669, 0.87, 14),
            (2.683, 0.88, 14),
            (2.697, 0.89, 14),
        ]
    )
    assert [r["curve"] for r in (reps[0], reps[-1])] == (
        [
            [
                [6.02, 1.138],
                [7.88, 0.981],
                [9.83, 0.902],
                [11.44, 0.828],
                [12.47, 0.811],
                [13.34, 0.768],
                [14.37, 0.71],
                [15.41, 0.674],
                [16.34, 0.652],
                [17.31, 0.615],
                [18.75, 0.556],
                [20.97, 0.51],
            ],
            [
                [6.3, 1.121],
                [7.81, 1.026],
                [9.84, 0.972],
                [11.47, 0.939],
                [12.47, 0.918],
                [13.47, 0.902],
                [14.47, 0.881],
                [15.52, 0.836],
                [16.51, 0.807],
                [17.48, 0.792],
                [18.95, 0.792],
                [21.63, 0.773],
                [26.53, 0.738],
                [32.57, 0.713],
            ],
        ]
    )
    assert _digest(reps) == "feffcbe3070f593f2342c9ccfd58319eebd0218aa998da919ba9f08aca5ddc89"
    assert cor.prev_t == 4.833333333333333
    assert sorted(cor.bins) == list(range(3, 17))
    assert cor.ref == pytest.approx((0.9919559868764279, 4.833333333333333), rel=1e-12, abs=1e-12)


def test_corrector_with_walls_30_frames() -> None:
    from engine.groundfuse import estimators as est

    geo, mask, frames = _scene()
    cor = est.Corrector(_cfg(), geo)
    reps = run_corrector(cor, frames, mask, True)
    assert [None if r is None else (r["ref"], r.get("wallSamples"), len(r["curve"])) for r in reps] == (
        [
            (2.349, 12, 12),
            (2.368, None, 13),
            (2.395, None, 14),
            (2.412, 15, 14),
            (2.432, None, 14),
            (2.443, None, 15),
            (2.459, 18, 15),
            (2.472, None, 15),
            (2.489, None, 15),
            (2.508, 21, 15),
            (2.493, None, 15),
            (2.483, None, 15),
            (2.495, 24, 15),
            (2.515, None, 15),
            (2.537, None, 15),
            (2.565, 27, 15),
            (2.59, None, 15),
            (2.601, None, 15),
            (2.611, 30, 15),
            (2.636, None, 15),
            (2.62, None, 15),
            (2.629, 33, 14),
            (2.652, None, 14),
            (2.662, None, 14),
            (2.662, 36, 14),
            (2.651, None, 14),
            (2.662, None, 14),
            (2.669, 39, 14),
            (2.683, None, 14),
            (2.697, None, 14),
        ]
    )
    assert [r["curve"] for r in (reps[0], reps[-1])] == (
        [
            [
                [6.02, 1.138],
                [7.88, 0.98],
                [9.82, 0.901],
                [11.44, 0.826],
                [12.47, 0.81],
                [13.37, 0.767],
                [14.36, 0.707],
                [15.41, 0.671],
                [16.31, 0.648],
                [17.31, 0.592],
                [18.69, 0.552],
                [20.94, 0.51],
            ],
            [
                [6.3, 1.121],
                [7.81, 1.026],
                [9.84, 0.971],
                [11.47, 0.938],
                [12.47, 0.916],
                [13.47, 0.901],
                [14.47, 0.88],
                [15.52, 0.832],
                [16.51, 0.803],
                [17.48, 0.786],
                [18.93, 0.786],
                [21.63, 0.773],
                [26.53, 0.738],
                [32.57, 0.713],
            ],
        ]
    )
    assert _digest(reps) == "3374607c2ab623fe3c91c5c09696da3b3b3fcc47f3f4e19a5a84295717f1e4b4"
    assert sorted(cor.bins) == list(range(3, 17))


def test_corrector_hold_and_drop() -> None:
    from engine.groundfuse import estimators as est

    geo, mask, frames = _scene()
    cor = est.Corrector(_cfg(), geo)
    r0 = cor.update(0.0, mask, frames[0], 1.0, HORIZON, 0.5)
    held = cor.update(1.5, None, None, 1.0, HORIZON, 0.5)
    dropped = cor.update(2.6, None, None, 1.0, HORIZON, 0.5)
    assert (r0, held, dropped) == (REP0, REP0, None)
