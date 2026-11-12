from __future__ import annotations

import json
from typing import Any

import numpy as np

# Expected values were produced by running the legacy groundfuse functions in the hackeye-rnd image.

NAMES = [
    "MODES",
    "SRC_DEPTH",
    "SRC_GROUND",
    "SRC_FUSED",
    "SRC_NAMES",
    "settings",
    "resolved_mode",
    "rho_at",
    "correct_depth",
    "resolve",
]

NAN = float("nan")

DEFAULTS: dict[str, Any] = {
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

REAL: dict[str, Any] = {
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
    "wallSampleWeight": 5,
}

VARIANT: dict[str, Any] = {
    "minRowsBelowHorizon": 4.0,
    "binEdgesM": [1, 3, 5, 7, 9, 11, 12, 13, 14, 15, 16, 17, 18, 20, 24, 30],
    "minBinSamples": 25,
    "refGroundM": [2.0, 8.0],
    "refMinSamples": 80,
    "emaSeconds": 1.0,
    "holdSeconds": 2.0,
    "extrapolate": "prior",
    "priorCurve": [[5.8, 1.0], [12.7, 0.876], [14.4, 0.71], [15.1, 0.58], [16.0, 0.44], [17.6, 0.27]],
    "rhoMin": 0.3,
    "maxCorrectedM": 45.0,
    "depthRelErr": 0.12,
    "rowSigma": 0.5,
    "sanityFactor": 0.7,
    "fuseMaxM": 40.0,
    "horizonWindowSeconds": 3.0,
    "fuse": False,
    "gate": True,
}

D = np.array([0.0, 0.5, 3.0, 5.8, 8.0, 12.7, 14.0, 15.5, 17.6, 25.0, 60.0])

REP: dict[str, Any] = {"ref": 1.0, "sigmaRows": 0.5, "curve": [[5.0, 1.0], [9.0, 0.95], [12.0, 0.8]]}
REP2: dict[str, Any] = {"ref": 1.0, "sigmaRows": 0.5, "curve": [[5.0, 1.0], [12.0, 0.8]]}

PRIOR_INTERP = [1.0, 1.0, 1.0, 1.0, 0.9491206752084287, 0.876, 0.7472244411451064, 0.5167751307723224, 0.27, 0.27, 0.27]

# (name, rep, cfg, rho_at(D), correct_depth(D)[0])
RHO_CASES: list[tuple[str, Any, dict[str, Any], list[float], list[float]]] = [
    (
        "none",
        None,
        DEFAULTS,
        [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        [0.0, 0.5, 3.0, 5.8, 8.0, 12.7, 14.0, 15.5, 17.6, 25.0, 60.0],
    ),
    (
        "empty",
        {"curve": []},
        DEFAULTS,
        [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        [0.0, 0.5, 3.0, 5.8, 8.0, 12.7, 14.0, 15.5, 17.6, 25.0, 60.0],
    ),
    (
        "prior",
        REP,
        DEFAULTS,
        [
            1.0,
            1.0,
            1.0,
            0.9873746706091922,
            0.9600191993702338,
            0.7918912068741029,
            0.6754799823107596,
            0.46715717122125194,
            0.24407605691325093,
            0.24407605691325093,
            0.24407605691325093,
        ],
        [
            0.0,
            0.5,
            3.0,
            5.874163245874543,
            8.333166675466435,
            16.037556535236387,
            20.726002793017184,
            33.17941145905901,
            45.0,
            45.0,
            60.0,
        ],
    ),
    (
        "last",
        REP,
        {**DEFAULTS, "extrapolate": "last"},
        [1.0, 1.0, 1.0, 0.9873746706091922, 0.9600191993702338, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8],
        [0.0, 0.5, 3.0, 5.874163245874543, 8.333166675466435, 15.874999999999998, 17.5, 19.375, 22.0, 31.25, 60.0],
    ),
    (
        "p2",
        REP2,
        DEFAULTS,
        [
            1.0,
            1.0,
            1.0,
            0.9660935910591457,
            0.8926281181287367,
            0.7918912068741029,
            0.6754799823107596,
            0.46715717122125194,
            0.24407605691325093,
            0.24407605691325093,
            0.24407605691325093,
        ],
        [
            0.0,
            0.5,
            3.0,
            6.003559130996155,
            8.962298898639695,
            16.037556535236387,
            20.726002793017184,
            33.17941145905901,
            45.0,
            45.0,
            60.0,
        ],
    ),
]

RHO_2D = [[1.0, 0.7640025828072518], [0.24407605691325093, 0.24407605691325093]]

RHO_SCALAR = 0.8950640868442613
CD_SCALAR = 11.172384354350676

DD = [10.5, 16.0, 2.0, 2.0, 20.0, 10.5, 10.5, 30.0, 12.0, 9.0]
GROUND = [10.0, 30.0, 10.0, 10.0, 18.0, 10.0, NAN, 25.0, 60.0, 8.0]
SIGMA = [0.4, 0.9, 0.3, 0.3, 0.5, 0.4, 0.4, 1.2, 2.0, 0.2]
ROWS = [20.0, 3.0, 20.0, 20.0, 12.0, 3.0, 20.0, 10.0, 15.0, 4.0]
CONTACT = [True, False, True, False, True, True, True, True, True, True]

# (mode, rep, cfg, distance, source)
RESOLVE_CASES: list[tuple[str, Any, dict[str, Any], list[float], list[int]]] = [
    ("depth", REP, DEFAULTS, [10.5, 16.0, 2.0, 2.0, 20.0, 10.5, 10.5, 30.0, 12.0, 9.0], [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    (
        "depth",
        None,
        DEFAULTS,
        [10.5, 16.0, 2.0, 2.0, 20.0, 10.5, 10.5, 30.0, 12.0, 9.0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    (
        "ground-contact",
        REP,
        DEFAULTS,
        [10.0, 16.0, 10.0, 2.0, 18.0, 10.5, 10.5, 25.0, 12.0, 8.0],
        [1, 0, 1, 0, 1, 0, 0, 1, 0, 1],
    ),
    (
        "ground-contact",
        None,
        DEFAULTS,
        [10.5, 16.0, 2.0, 2.0, 20.0, 10.5, 10.5, 30.0, 12.0, 9.0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    (
        "ground+depth",
        REP,
        DEFAULTS,
        [
            10.113035509310313,
            40.22591130956929,
            10.0,
            2.0,
            18.014459844476338,
            12.074177400899785,
            12.074177400899785,
            25.061538461538458,
            15.0,
            8.04004486312431,
        ],
        [2, 0, 1, 0, 2, 0, 0, 2, 0, 2],
    ),
    (
        "ground+depth",
        None,
        DEFAULTS,
        [10.5, 16.0, 2.0, 2.0, 20.0, 10.5, 10.5, 30.0, 12.0, 9.0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    (
        "nonsense",
        REP,
        DEFAULTS,
        [
            10.113035509310313,
            40.22591130956929,
            10.0,
            2.0,
            18.014459844476338,
            12.074177400899785,
            12.074177400899785,
            25.061538461538458,
            15.0,
            8.04004486312431,
        ],
        [2, 0, 1, 0, 2, 0, 0, 2, 0, 2],
    ),
    (
        "nonsense",
        None,
        DEFAULTS,
        [10.5, 16.0, 2.0, 2.0, 20.0, 10.5, 10.5, 30.0, 12.0, 9.0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    (
        "ground+depth",
        REP,
        {**DEFAULTS, "fuse": False},
        [
            12.074177400899785,
            40.22591130956929,
            10.0,
            2.0,
            45.0,
            12.074177400899785,
            12.074177400899785,
            45.0,
            15.0,
            9.473684210526317,
        ],
        [0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
    ),
    (
        "ground+depth",
        REP,
        {**DEFAULTS, "gate": False},
        [
            10.113035509310313,
            40.22591130956929,
            5.121951219512195,
            2.0,
            18.014459844476338,
            12.074177400899785,
            12.074177400899785,
            25.061538461538458,
            15.0,
            8.04004486312431,
        ],
        [2, 0, 2, 0, 2, 0, 0, 2, 0, 2],
    ),
    (
        "ground+depth",
        REP,
        {**DEFAULTS, "fuse": False, "gate": False},
        [
            12.074177400899785,
            40.22591130956929,
            2.0,
            2.0,
            45.0,
            12.074177400899785,
            12.074177400899785,
            45.0,
            15.0,
            9.473684210526317,
        ],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
]

RESOLVE_SCALAR = (10.113035509310313, 2)


# resolved_mode(mode, use_horizon) from legacy
MODE_CASES: list[tuple[str | None, bool | None, str]] = [
    ("depth", None, "depth"),
    ("depth", True, "depth"),
    ("depth", False, "depth"),
    ("ground-contact", None, "ground-contact"),
    ("ground-contact", True, "ground-contact"),
    ("ground-contact", False, "depth"),
    ("ground+depth", None, "ground+depth"),
    ("ground+depth", True, "ground+depth"),
    ("ground+depth", False, "depth"),
    ("nonsense", None, "depth"),
    ("nonsense", True, "depth"),
    ("nonsense", False, "depth"),
    (None, None, "depth"),
    (None, True, "depth"),
    (None, False, "depth"),
]


def test_identity_with_groundfuse() -> None:
    import groundfuse
    from engine.core import distfuse

    for name in NAMES:
        assert getattr(groundfuse, name) is getattr(distfuse, name), name
    assert groundfuse._prior_interp is distfuse.prior_interp


def test_constants() -> None:
    from engine.core import distfuse

    assert distfuse.MODES == ("depth", "ground-contact", "ground+depth")
    assert (distfuse.SRC_DEPTH, distfuse.SRC_GROUND, distfuse.SRC_FUSED) == (0, 1, 2)
    assert distfuse.SRC_NAMES == ("depth", "ground", "fused")


def test_settings_defaults() -> None:
    from engine.core import distfuse

    assert distfuse.settings({}) == DEFAULTS
    assert list(distfuse.settings({})) == list(DEFAULTS)
    assert distfuse.settings({"groundDepth": None}) == DEFAULTS


def test_settings_real_config_section() -> None:
    from common_paths import find_common_dir
    from engine.core import distfuse

    cfg = json.loads((find_common_dir() / "config" / "collision.json").read_text())
    assert distfuse.settings(cfg["distance"]) == REAL


def test_settings_override_and_no_mutation() -> None:
    from engine.core import distfuse

    src: dict[str, Any] = {"groundDepth": {"rhoMin": 0.3, "fuse": False}}
    assert distfuse.settings(src) == VARIANT
    assert src == {"groundDepth": {"rhoMin": 0.3, "fuse": False}}


def test_resolved_mode() -> None:
    from engine.core import distfuse

    for mode, horizon, expected in MODE_CASES:
        assert distfuse.resolved_mode(mode, horizon) == expected, (mode, horizon)


def test_prior_interp() -> None:
    from engine.core import distfuse

    np.testing.assert_array_equal(distfuse.prior_interp(D, DEFAULTS), np.array(PRIOR_INTERP))


def test_rho_at_and_correct_depth() -> None:
    from engine.core import distfuse

    for name, rep, cfg, rho, corrected in RHO_CASES:
        np.testing.assert_array_equal(distfuse.rho_at(D, rep, cfg), np.array(rho), err_msg=name)
        got, got_rho = distfuse.correct_depth(D, rep, cfg)
        np.testing.assert_array_equal(got, np.array(corrected), err_msg=name)
        np.testing.assert_array_equal(got_rho, np.array(rho), err_msg=name)


def test_rho_at_2d_and_scalar() -> None:
    from engine.core import distfuse

    got2 = distfuse.rho_at(np.array([[4.0, 13.0], [20.0, 30.0]]), REP, DEFAULTS)
    np.testing.assert_array_equal(got2, np.array(RHO_2D))
    one = distfuse.rho_at(10.0, REP, DEFAULTS)
    assert one.shape == ()
    assert float(one) == RHO_SCALAR
    corrected, rho = distfuse.correct_depth(10.0, REP, DEFAULTS)
    assert (float(corrected), float(rho)) == (CD_SCALAR, RHO_SCALAR)


def test_resolve_modes_and_variants() -> None:
    from engine.core import distfuse

    for mode, rep, cfg, dist, src in RESOLVE_CASES:
        got, got_src = distfuse.resolve(DD, GROUND, SIGMA, ROWS, CONTACT, rep, cfg, mode)
        label = (mode, rep is None, cfg["fuse"], cfg["gate"])
        np.testing.assert_array_equal(got, np.array(dist), err_msg=str(label))
        np.testing.assert_array_equal(got_src, np.array(src), err_msg=str(label))
        assert got.dtype == np.float64 and got_src.dtype == np.int8


def test_resolve_depth_mode_returns_copy() -> None:
    from engine.core import distfuse

    d_dep = np.array(DD)
    got, _ = distfuse.resolve(d_dep, GROUND, SIGMA, ROWS, CONTACT, REP, DEFAULTS, "depth")
    got[0] = -1.0
    assert d_dep[0] == DD[0]


def test_resolve_scalar_input() -> None:
    from engine.core import distfuse

    got, src = distfuse.resolve(10.5, 10.0, 0.4, 20.0, True, REP, DEFAULTS, "ground+depth")
    assert got.shape == () and src.shape == ()
    assert (float(got), int(src)) == RESOLVE_SCALAR
