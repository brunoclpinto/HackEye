"""Characterisation tests for engine.worldtracks (v26.3.0 p3-09): the whole of the legacy ``worldtracks`` module.

Every literal below was printed by the legacy ``worldtracks`` module (``WorldTracks.step`` / ``lookup``,
``settings``, ``_rot``, ``_eig_radius``, ``_interval``) in the hackeye-rnd image before the move, by running the
30-step scenario built by ``_scenario`` (no random numbers: the noise is a fixed sinusoid). The engine modules are
imported inside each test (they are not written yet).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

import worldtracks as legacy

DT = 1.0 / 6.0
LOOKUP_KEYS = ["x", "y", "vx", "vy", "trusted", "state", "id"]
N_STEPS = 30

WT_SLOTS: list[str] = [
    "id", "cls", "family", "group", "static", "x", "P", "t", "t0", "last_seen", "tid", "images", "state", "miss",
    "seen_now", "innov", "seen_s", "ivs", "promoted", "prom_t0", "miss_t0", "dead_t",
]  # fmt: skip

WORLDTRACKS_ATTRS: list[str] = [
    "cfg", "on", "half", "hfov", "skip", "extended", "dead", "_ctx", "tracks", "link", "next", "prev_pose", "prev_t",
    "ego_speed", "ms",
]  # fmt: skip

HALF = 0.8999999999999999
DEFAULT_KEYS: list[str] = [
    "enabled",
    "accelStaticMps2",
    "accelMoverMps2",
    "rangeSigmaFrac",
    "bearingSigmaDeg",
    "rangeSigmaMinM",
    "nonDepthRangeFactor",
    "initSpeedSigmaStaticMps",
    "initSpeedSigmaMoverMps",
    "gateChi2",
    "fovMarginDeg",
    "coastMaxS",
    "missDropFrames",
    "maxSigmaM",
    "behindDropM",
    "maxRangeM",
    "horizonS",
    "itemRadiusM",
    "maxTracksOut",
    "skipClasses",
    "extendedClasses",
    "headingSigmaDegPerS",
    "poseSigmaMaxS",
    "staticVelocityDamping",
    "dampingDirectionalS",
    "dampingDirectionalMinM",
    "dampingDirectionalRatio",
    "moverPromoteMps",
    "moverPromoteS",
    "missDropS",
    "reviveS",
    "reidOneToOne",
    "classMismatchCost",
    "trustMinS",
    "trustMaxSigmaM",
    "trustMaxSpeedSigmaMps",
]
ROT: dict[float, list[list[float]]] = {
    0.0: [[0.0, 1.0], [1.0, -0.0]],
    30.0: [[0.49999999999999994, 0.8660254037844387], [0.8660254037844387, -0.49999999999999994]],
    90.0: [[1.0, 6.123233995736766e-17], [6.123233995736766e-17, -1.0]],
    -45.0: [[-0.7071067811865475, 0.7071067811865476], [0.7071067811865476, 0.7071067811865475]],
}
EIG = 2.1010029896154587
INTERVAL: list[tuple[tuple[float, ...], tuple[float, float] | None]] = [
    ((0.0, 8.0, 5.0, -1.0, -0.3, 0.3), (4.7, 5.3)),
    ((0.0, 8.0, 5.0, 1.0, -0.3, 0.3), None),
    ((0.0, 8.0, 0.0, 0.0, -1.0, 1.0), (0.0, 8.0)),
    ((0.0, 8.0, 5.0, 0.0, -1.0, 1.0), None),
    ((1.0, 2.0, 5.0, -1.0, -0.3, 0.3), None),
    ((0.0, 8.0, -2.0, 1.0, -0.3, 0.3), (1.7, 2.3)),
]
DIGESTS: list[dict[str, Any]] = [
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-3.95, 9.0, 0.0, 0.0, 1.18],
        "lookup": {
            1: [2.0, 20.05, 0.0, 0.0, False, "seen", "W1"],
            2: [-3.95, 9.0, 0.0, 0.0, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-3.83, 9.04, 0.54, 0.23, 0.84],
        "lookup": {
            1: [
                2.019201007970084,
                20.021768811207874,
                0.002296001959117631,
                -0.00028928562470779745,
                False,
                "seen",
                "W1",
            ],
            2: [-3.806376847878944, 9.050745413192551, 0.5446840908488289, 0.2334884308677805, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-3.69, 9.03, 0.67, 0.21, 0.73],
        "lookup": {
            1: [
                1.9942647344981879,
                19.995400206484682,
                -0.0034982163636322517,
                0.00012806365778436098,
                False,
                "seen",
                "W1",
            ],
            2: [-3.6564895352459375, 9.03839950332685, 0.6711424342781573, 0.2068732198177048, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-3.44, 9.05, 1.08, 0.27, 0.7],
        "lookup": {
            1: [
                2.003754186925417,
                19.999647005529845,
                0.00037729446740038817,
                -0.00018056916710653014,
                False,
                "seen",
                "W1",
            ],
            2: [-3.3818984367662135, 9.061682297404843, 1.0820994841923497, 0.2709747529414591, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-3.19, 9.06, 1.25, 0.23, 0.69],
        "lookup": {
            1: [
                2.0054071753277456,
                20.008639413299267,
                0.0006514411777036977,
                -6.97486999904744e-05,
                False,
                "seen",
                "W1",
            ],
            2: [-3.1298729287361935, 9.066560325514384, 1.2497101866061782, 0.23010505201877596, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-3.03, 9.03, 1.07, 0.1, 0.67],
        "lookup": {
            1: [
                1.9940678114937274,
                20.003840495056043,
                -0.004496885441769636,
                0.00034748842637376764,
                False,
                "seen",
                "W1",
            ],
            2: [-2.974549461588464, 9.03227802959321, 1.072986338609978, 0.09553417249755217, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-2.84, 9.05, 1.11, 0.1, 0.65],
        "lookup": {
            1: [
                2.005695079708304,
                19.994949659306123,
                0.0020615315192855175,
                -0.0004563578634692335,
                False,
                "seen",
                "W1",
            ],
            2: [-2.784325210437578, 9.050879470195675, 1.1053139762534332, 0.10412508202221507, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-2.6, 9.03, 1.27, 0.08, 0.62],
        "lookup": {
            1: [
                2.000234879533372,
                20.000893444834325,
                -0.0009559732154632693,
                -8.948011138228845e-07,
                False,
                "seen",
                "W1",
            ],
            2: [-2.5328646386192197, 9.033560329815977, 1.2709847216167467, 0.08123049065506258, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-2.38, 9.01, 1.26, 0.04, 0.59],
        "lookup": {
            1: [
                1.9953436959968156,
                20.003882312611957,
                -0.002905165618798661,
                0.00027183651745445896,
                False,
                "seen",
                "W1",
            ],
            2: [-2.320687802393226, 9.01614921095639, 1.2556109888408458, 0.035308480203722514, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-2.22, 9.03, 1.1, 0.02, 0.57],
        "lookup": {
            1: [
                2.005658760222832,
                19.996109764654808,
                0.0017529086968591586,
                -0.00037863268669390015,
                False,
                "seen",
                "W1",
            ],
            2: [-2.168094987859142, 9.032158225023112, 1.1019871154782093, 0.022592255605580962, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-2.03, 9.0, 1.12, -0.02, 0.54],
        "lookup": {
            1: [
                1.9971522307773777,
                19.996586071555548,
                -0.0014860752688250177,
                -2.2221734787195393e-05,
                False,
                "seen",
                "W1",
            ],
            2: [-1.9711782704558303, 9.000384093998472, 1.1211925040523774, -0.023463384884145917, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, False],
        "first": [-1.77, 8.99, 1.36, 0.01, 0.52],
        "lookup": {
            1: [
                1.998348602111121,
                20.001534916723017,
                -0.0010196741829744506,
                7.646321499459666e-05,
                False,
                "seen",
                "W1",
            ],
            2: [-1.7025603046606521, 8.995183837846989, 1.3611605974426928, 0.008726592302898965, False, "seen", "W2"],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["missing", "seen"],
        "trusted": [False, False],
        "first": [-1.54, 9.0, 1.36, 0.01, 0.66],
        "lookup": {
            1: [
                2.003645500406287,
                20.000114464253517,
                0.0007073769406633665,
                -0.0001305952560237956,
                False,
                "seen",
                "W1",
            ],
            2: [
                -1.4757002050868702,
                8.996638269897472,
                1.3611605974426928,
                0.008726592302898965,
                False,
                "missing",
                "W2",
            ],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["missing", "seen"],
        "trusted": [False, False],
        "first": [-1.32, 9.0, 1.36, 0.01, 0.84],
        "lookup": {
            1: [
                1.9954406092288453,
                19.995952689552446,
                -0.0014730310696984374,
                -6.807917672890332e-06,
                False,
                "seen",
                "W1",
            ],
            2: [
                -1.2488401055130882,
                8.998092701947956,
                1.3611605974426928,
                0.008726592302898965,
                False,
                "missing",
                "W2",
            ],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["missing", "seen"],
        "trusted": [False, False],
        "first": [-1.09, 9.0, 1.36, 0.01, 1.05],
        "lookup": {
            1: [
                2.0012041920094736,
                19.99675559895854,
                0.00014141522952738168,
                -0.00013555062716545308,
                False,
                "seen",
                "W1",
            ],
            2: [
                -1.0219800059393063,
                8.999547133998439,
                1.3611605974426928,
                0.008726592302898965,
                False,
                "missing",
                "W2",
            ],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["missing", "seen"],
        "trusted": [False, False],
        "first": [-0.86, 9.0, 1.36, 0.01, 1.27],
        "lookup": {
            1: [
                2.001073111805292,
                20.000762733555128,
                3.0945348090922022e-06,
                -1.1185071624951706e-05,
                False,
                "seen",
                "W1",
            ],
            2: [
                -0.7951199063655239,
                9.001001566048922,
                1.3611605974426928,
                0.008726592302898965,
                False,
                "missing",
                "W2",
            ],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["missing", "seen"],
        "trusted": [False, False],
        "first": [-0.64, 9.0, 1.36, 0.01, 1.52],
        "lookup": {
            1: [
                1.99569986264409,
                19.99995423514469,
                -0.0011339551566297908,
                9.038481792996798e-05,
                False,
                "seen",
                "W1",
            ],
            2: [
                -0.5682598067917419,
                9.002455998099405,
                1.3611605974426928,
                0.008726592302898965,
                False,
                "missing",
                "W2",
            ],
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["missing", "seen"],
        "trusted": [False, False],
        "first": [-0.41, 9.0, 1.36, 0.01, 1.78],
        "lookup": {
            1: [
                2.0027985346180284,
                19.993612453970506,
                0.0005955625635392504,
                -0.00023325537108599622,
                False,
                "seen",
                "W1",
            ],
            2: [-0.34139970721796, 9.003910430149888, 1.3611605974426928, 0.008726592302898965, False, "missing", "W2"],
            3: None,
        },
    },
    {
        "n": 1,
        "ids": ["W1"],
        "states": ["seen"],
        "trusted": [False],
        "first": [2.0, 20.0, -0.0, -0.0, 0.51],
        "lookup": {
            1: [
                1.9988793526977169,
                19.997635373149063,
                -0.0003282531004548386,
                -2.675895334670352e-05,
                False,
                "seen",
                "W1",
            ],
            2: None,
            3: None,
        },
    },
    {
        "n": 1,
        "ids": ["W1"],
        "states": ["seen"],
        "trusted": [True],
        "first": [2.0, 20.0, -0.0, 0.0, 0.49],
        "lookup": {
            1: [
                1.9970058384275444,
                20.000314645363133,
                -0.0006850001906312394,
                7.568033752949187e-05,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: None,
        },
    },
    {
        "n": 1,
        "ids": ["W1"],
        "states": ["seen"],
        "trusted": [True],
        "first": [2.0, 20.0, 0.0, -0.0, 0.48],
        "lookup": {
            1: [
                2.0029895042815324,
                19.996303687023115,
                0.0005840482320357263,
                -0.00014699010493629511,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: None,
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, True],
        "first": [0.18, 8.96, 1.1, -0.04, 0.48],
        "lookup": {
            1: [
                1.9973892782245244,
                19.995614875536145,
                -0.0004995206598511792,
                -2.9704630715887353e-05,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: [0.2351093016873381, 8.955520846089355, 1.1047961060184477, -0.03595644755696724, False, "seen", "W2"],
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, True],
        "first": [0.43, 8.97, 1.45, -0.03, 0.36],
        "lookup": {
            1: [
                1.9990420813548253,
                19.99842817170912,
                -0.00018489725935563273,
                -1.8128104912805338e-06,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: [0.5076040822137405, 8.969159753362277, 1.4522628978242162, -0.03256166537809152, False, "seen", "W2"],
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, True],
        "first": [0.62, 9.01, 1.16, 0.11, 0.32],
        "lookup": {
            1: [
                2.0016127342868155,
                19.997804324125784,
                0.0003164985745976803,
                -6.847923563219913e-05,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: [0.6743036944645869, 9.018504905655547, 1.1578287941202858, 0.1149168188544919, False, "seen", "W2"],
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, True],
        "first": [0.77, 9.0, 0.98, 0.07, 0.31],
        "lookup": {
            1: [
                1.9966673465758693,
                19.99673487806257,
                -0.0006067573085173671,
                2.2868778300357727e-05,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: [0.8162625902197617, 8.99989585298146, 0.9826191432395166, 0.07497061932994943, False, "seen", "W2"],
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, True],
        "first": [0.98, 9.01, 1.23, 0.02, 0.3],
        "lookup": {
            1: [
                2.001068554263443,
                19.99538353828515,
                0.00031618207712481785,
                -0.00010478486317302898,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: [1.0463279150456917, 9.010461212837619, 1.2292741151385251, 0.021992471633572173, False, "seen", "W2"],
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, True],
        "first": [1.24, 8.98, 1.46, -0.1, 0.28],
        "lookup": {
            1: [
                2.0000655284505497,
                19.998670223683533,
                1.547206381679624e-05,
                -3.152113700063009e-06,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: [1.3082928791804715, 8.978671839704633, 1.4581329520902055, -0.09845260415534593, False, "seen", "W2"],
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, True],
        "first": [1.41, 8.99, 1.12, 0.05, 0.27],
        "lookup": {
            1: [
                1.9966589656165425,
                19.998295677855342,
                -0.0006307393030305084,
                6.841267937420326e-05,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: [1.4633140276999772, 8.994307742163288, 1.1162783410661292, 0.053806354619697794, False, "seen", "W2"],
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, True],
        "first": [1.56, 9.05, 0.93, 0.23, 0.26],
        "lookup": {
            1: [
                2.0022352235533654,
                19.99324709707462,
                0.0006625152234797005,
                -0.00017635288440420653,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: [1.6106153178985114, 9.060932327797959, 0.9333904693277334, 0.2335129158185517, False, "seen", "W2"],
        },
    },
    {
        "n": 2,
        "ids": ["W2", "W1"],
        "states": ["seen", "seen"],
        "trusted": [False, True],
        "first": [1.78, 8.94, 1.35, -0.33, 0.25],
        "lookup": {
            1: [
                1.9985684602006957,
                19.996957116221832,
                -0.0002528984063806454,
                1.1760397892215198e-05,
                True,
                "seen",
                "W1",
            ],
            2: None,
            3: [1.8449401758558492, 8.92150784323581, 1.349281760928379, -0.32762012596139756, False, "seen", "W2"],
        },
    },
]


def _meas(
    tid: int, wx: float, wy: float, pose: tuple[float, float, float], cls: str, group: str, static: bool
) -> dict[str, Any]:
    x, y, th = pose
    s, c = math.sin(math.radians(th)), math.cos(math.radians(th))
    dx, dy = wx - x, wy - y
    return {
        "tid": tid, "cls": cls, "family": cls, "group": group, "static": static,
        "fwd": dx * s + dy * c, "right": dx * c - dy * s, "depth": True,
    }  # fmt: skip


def _scenario(wt: Any) -> list[dict[str, Any]]:
    """The user walks north with a slow turn; a pole (tid 1), a crossing person (tid 2, then 3 after a gap), a wall."""
    digests: list[dict[str, Any]] = []
    for k in range(N_STEPS):
        t = k * DT
        pose = (0.1 * math.sin(k), 1.4 * t, 0.5 * k * DT)
        n1, n2 = 0.05 * math.sin(2.3 * k), 0.05 * math.cos(1.7 * k)
        ms = [_meas(1, 2.0 + n1, 20.0 + n2, pose, "pole", "static", True)]
        if not 12 <= k < 21:
            tid = 2 if k < 12 else 3
            ms.append(_meas(tid, -4.0 + 1.2 * t + n2, 9.0 + n1, pose, "person", "moving", False))
        ms.append(_meas(9, -3.0, 12.0 + n1, pose, "wall", "static", True))
        out = wt.step(t, pose, ms, 0.0, None)
        lk = {tid: wt.lookup(tid, t + 0.05) for tid in (1, 2, 3)}
        first = out[0] if out else None
        digests.append({
            "n": len(out),
            "ids": [o["id"] for o in out],
            "states": [o["state"] for o in out],
            "trusted": [o["trusted"] for o in out],
            "first": None if first is None else [first["x"], first["y"], first["vx"], first["vy"], first["sigmaM"]],
            "lookup": {tid: None if v is None else [v[k] for k in LOOKUP_KEYS] for tid, v in lk.items()},
        })  # fmt: skip
    return digests


def _check_digests(got: list[dict[str, Any]]) -> None:
    assert len(got) == len(DIGESTS)
    for k, (g, e) in enumerate(zip(got, DIGESTS, strict=True)):
        msg = f"step {k}"
        assert g["n"] == e["n"], msg
        assert g["ids"] == e["ids"], msg
        assert g["states"] == e["states"], msg
        assert g["trusted"] == e["trusted"], msg
        if e["first"] is None:
            assert g["first"] is None, msg
        else:
            assert g["first"] == pytest.approx(e["first"], rel=1e-12, abs=1e-12), msg
        assert set(g["lookup"]) == set(e["lookup"]), msg
        for tid, ev in e["lookup"].items():
            gv = g["lookup"][tid]
            if ev is None:
                assert gv is None, msg
            else:
                assert gv[:4] == pytest.approx(ev[:4], rel=1e-12, abs=1e-12), msg
                assert gv[4:] == ev[4:], msg


def test_facade_identity() -> None:
    from engine.worldtracks import tracks

    assert legacy.DEFAULTS is tracks.DEFAULTS
    assert legacy.settings is tracks.settings
    assert legacy._WT is tracks.WT
    assert legacy._rot is tracks.rot
    assert legacy._eig_radius is tracks.eig_radius
    assert legacy._interval is tracks.interval
    assert legacy.WorldTracks is tracks.WorldTracks


def test_package_exports() -> None:
    import engine.worldtracks as pkg
    from engine.worldtracks import tracks

    assert pkg.WorldTracks is tracks.WorldTracks
    assert pkg.DEFAULTS is tracks.DEFAULTS
    assert pkg.tracks is tracks


def test_wt_slots() -> None:
    from engine.worldtracks import tracks

    assert list(tracks.WT.__slots__) == WT_SLOTS


def test_worldtracks_attribute_list() -> None:
    from engine.worldtracks import tracks

    wt = tracks.WorldTracks(None, 0.6, 118.0)
    assert list(vars(wt)) == WORLDTRACKS_ATTRS
    assert wt.on is True
    assert wt.half == pytest.approx(HALF, rel=1e-12, abs=1e-12)
    assert wt.hfov == 118.0
    assert wt.next == 1
    assert wt.ms == []
    assert wt.step(0.0, None, [], 0.0, None) == []
    assert tracks.WorldTracks({"enabled": False}, 0.6, 118.0).step(0.0, (0.0, 0.0, 0.0), [], 0.0, None) == []


def test_settings_and_defaults() -> None:
    from engine.worldtracks import tracks

    assert tracks.settings(None) == legacy.settings(None)
    assert tracks.settings(None) is not tracks.DEFAULTS
    assert list(tracks.DEFAULTS) == DEFAULT_KEYS
    assert tracks.settings({"gateChi2": 1.5, "extra": 7})["gateChi2"] == 1.5
    assert tracks.settings({"gateChi2": 1.5, "extra": 7})["extra"] == 7


def test_rot_eig_radius_interval() -> None:
    from engine.worldtracks import tracks

    for deg, rot_exp in ROT.items():
        assert tracks.rot(deg).tolist() == pytest.approx(rot_exp, rel=1e-12, abs=1e-12)
    assert tracks.eig_radius(np.array([[4.0, 1.0], [1.0, 2.0]])) == pytest.approx(EIG, rel=1e-12, abs=1e-12)
    for args, exp in INTERVAL:
        got = tracks.interval(*args)
        if exp is None:
            assert got is None
        else:
            assert got == pytest.approx(exp, rel=1e-12, abs=1e-12)


def test_thirty_step_scenario_digests() -> None:
    from engine.worldtracks import tracks

    _check_digests(_scenario(tracks.WorldTracks(None, 0.6, 118.0)))


def test_unknown_lookup_is_none() -> None:
    from engine.worldtracks import tracks

    wt = tracks.WorldTracks(None, 0.6, 118.0)
    assert wt.lookup(5, 0.0) is None
