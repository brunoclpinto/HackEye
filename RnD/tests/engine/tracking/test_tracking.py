"""Characterisation tests for engine.tracking (v26.3.0 p2-10): velocity, match, coast.

Every literal below was printed by the legacy ``collision`` functions (``_closing_mps``, ``_depth_closing``,
``_lateral_velocity``, ``_cross_velocity``, ``_match``, ``_Coast``) in the hackeye-rnd image before the move, by
feeding them the inputs built by the ``_*_cases`` / ``_coast_*`` helpers of this file. The engine modules are
imported inside each test (they do not exist yet).
"""

from __future__ import annotations

import json
import math
import types
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

import collision
from common_paths import find_common_dir

if TYPE_CHECKING:
    from collections.abc import Callable


COAST_ATTRS: list[str] = [
    "on",
    "seconds",
    "vehicle_seconds",
    "hist_s",
    "min_points",
    "min_span",
    "max_speed",
    "max_range",
    "rematch",
    "hist",
    "last",
    "active",
    "episodes",
]


def _cfg() -> dict[str, Any]:
    cfg: dict[str, Any] = json.loads((find_common_dir() / "config" / "collision.json").read_text())
    return cfg


def _check(got: float | None, exp: float | None) -> None:
    if exp is None:
        assert got is None
    else:
        assert got is not None
        assert got == pytest.approx(exp, rel=1e-12, abs=1e-12)


def _check_all(got: list[float | None], exp: list[float | None]) -> None:
    assert len(got) == len(exp)
    for g, e in zip(got, exp, strict=False):
        _check(g, e)


# ---- identity --------------------------------------------------------------------------------------------------


def test_facade_identity() -> None:
    from engine.tracking import coast, match, velocity

    assert collision._closing_mps is velocity.closing_mps
    assert collision._depth_closing is velocity.depth_closing
    assert collision._lateral_velocity is velocity.lateral_velocity
    assert collision._cross_velocity is velocity.cross_velocity
    assert collision._match is match.match
    assert collision._Coast is coast.Coast


def test_package_reexports() -> None:
    import engine.tracking as pkg
    from engine.tracking import coast, velocity

    assert pkg.Coast is coast.Coast
    assert pkg.closing_mps is velocity.closing_mps
    assert pkg.depth_closing is velocity.depth_closing
    assert pkg.lateral_velocity is velocity.lateral_velocity
    assert pkg.cross_velocity is velocity.cross_velocity
    for name in ("Coast", "closing_mps", "depth_closing", "lateral_velocity", "cross_velocity"):
        assert name in pkg.__all__
    # the function ``match`` must not shadow the submodule ``engine.tracking.match``
    assert isinstance(pkg.match, types.ModuleType)


def test_coast_attribute_list_and_defaults() -> None:
    from engine.tracking.coast import Coast

    c = Coast({})
    assert list(vars(c)) == COAST_ATTRS
    assert c.on is False
    assert c.seconds == 2.0 and c.vehicle_seconds == 2.0 and c.hist_s == 1.0
    assert c.min_points == 3 and c.min_span == 0.5 and c.max_speed == 15.0
    assert c.max_range == 30.0 and c.rematch == 2.0
    assert c.hist == {} and c.last == {} and c.active == {} and c.episodes == []
    cc = Coast(_cfg()["coast"])
    assert list(vars(cc)) == COAST_ATTRS
    assert cc.on is True and cc.seconds == 2.0 and cc.vehicle_seconds == 3.0


# ---- velocity functions ----------------------------------------------------------------------------------------


def _closing_cases() -> list[tuple[Any, ...]]:
    rng = np.random.RandomState(7)
    horizon, ch, gh, f = 0.45, 1.3, 135, 120.0
    out: list[tuple[Any, ...]] = []
    # an approaching object: its contact row rises from 0.55 to 0.66 over 1 s
    appr = [(0.125 * k, 0.55 + 0.11 * k / 8) for k in range(9)]
    out.append((appr, horizon, ch, gh, f, 8.0, 0.75))
    # a parked object: the row is constant
    out.append(([(0.1 * k, 0.6) for k in range(8)], horizon, ch, gh, f, 8.0, 0.5))
    # noisy row, receding
    noisy = [(0.1 * k, 0.70 - 0.01 * k + 0.002 * float(rng.randn())) for k in range(10)]
    out.append((noisy, horizon, ch, gh, f, 8.0, 0.75))
    # old points near the horizon are dropped, the rest still fit
    near = [(0.0, 0.46), (0.2, 0.47), (0.4, 0.55), (0.6, 0.57), (0.8, 0.6), (1.0, 0.63)]
    out.append((near, horizon, ch, gh, f, 8.0, 0.5))
    # the latest point is near the horizon: None
    out.append(([(0.0, 0.6), (0.3, 0.55), (0.6, 0.5), (0.9, 0.46)], horizon, ch, gh, f, 8.0, 0.5))
    # too short a span: None
    out.append((appr[:4], horizon, ch, gh, f, 8.0, 0.75))
    # too few points: None
    out.append((appr[:2], horizon, ch, gh, f, 8.0, 0.1))
    # min_points override
    out.append((appr[:2], horizon, ch, gh, f, 8.0, 0.1, 2))
    # a different horizon
    out.append((appr, 0.40, ch, gh, f, 8.0, 0.75))
    return out


def _depth_cases() -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    hist = [(0.2 * k, 9.0 - 0.7 * 0.2 * k + (0.05 if k % 2 else -0.05)) for k in range(8)]
    out.append((hist, hist[-1][0], 0.75))
    out.append((hist, hist[-1][0] + 0.1, 0.75))  # latest point is not now: None
    out.append((hist[:3], hist[2][0], 0.75))  # span 0.4 < 0.75: None
    out.append((hist[:2], hist[1][0], 0.1))  # too few points: None
    out.append((hist[:2], hist[1][0], 0.1, 2))
    out.append(([(1.0, 5.0), (1.0, 5.5), (1.0, 6.0)], 1.0, 0.0))  # zero variance in t: None
    out.append(([(0.0, 3.0), (0.5, 3.0), (1.0, 3.0)], 1.0, 0.5))  # flat
    return out


def _lateral_cases() -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    # a static pole at 6 m while we turn right 10 deg/s: lateral shifts left by the turn
    turn = [(0.25 * k, -1.0 - math.radians(2.5 * k) * 6.0, 6.0, 2.5 * k) for k in range(9)]
    out.append((turn, 0.75))
    # a mover crossing at 1.2 m/s, heading constant
    mover = [(0.25 * k, -3.0 + 1.2 * 0.25 * k, 6.0 - 0.1 * k, 10.0) for k in range(9)]
    out.append((mover, 0.75))
    out.append((mover[:3], 0.75))  # too short: None
    out.append(([(t, la, d, None) for t, la, d, _h in mover], 0.75))  # no heading: None
    out.append((mover[:2], 0.1, 2))
    out.append(([(0.0, 1.0, 5.0, 0.0), (0.0, 1.5, 5.0, 0.0), (0.0, 2.0, 5.0, 0.0)], 0.0))  # zero t variance: None
    return out


def _cross_cases() -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    # (t, lateral, distance, heading, bearing)
    static = [
        (0.25 * k, 2.0, 8.0 - 1.4 * 0.25 * k, 0.0, math.degrees(math.atan2(2.0, 8.0 - 1.4 * 0.25 * k)))
        for k in range(9)
    ]
    out.append((static, 1.4, 2.0))
    mover = [
        (0.25 * k, -3.0 + 1.0 * 0.25 * k, 6.0, 5.0, math.degrees(math.atan2(-3.0 + 0.25 * k, 6.0)) - 5.0)
        for k in range(9)
    ]
    out.append((mover, 1.0, 2.0))
    out.append((mover, 0.0, 1.0))  # a narrower window
    out.append((mover[:3], 1.0, 2.0))  # too short: None
    out.append((mover, None, 2.0))  # our speed unknown: None
    out.append(([(t, la, d, None, b) for t, la, d, _h, b in mover], 1.0, 2.0))  # no heading: None
    out.append(([], 1.0, 2.0))  # empty: None
    out.append(([(1.0, 1.0, 5.0, 0.0, 10.0)] * 4, 1.0, 1.0))  # zero t variance: None
    return out


def _run(fn: Callable[..., float | None], cases: list[tuple[Any, ...]]) -> list[float | None]:
    return [fn(*c) for c in cases]


CLOSING_EXPECTED: list[float | None] = [
    5.842561860554171,
    -0.0,
    -2.8519805058582723,
    8.666666666666663,
    None,
    None,
    None,
    11.174603174603192,
    3.195913150944781,
]
DEPTH_EXPECTED: list[float | None] = [0.6761904761904758, None, None, None, 0.1999999999999957, None, -0.0]
LATERAL_EXPECTED: list[float | None] = [0.0, 1.2, None, None, 1.1999999999999993, None]
CROSS_EXPECTED: list[float | None] = [
    0.005028513990275818,
    1.3444833253369595,
    0.9702594030099062,
    None,
    None,
    None,
    None,
    None,
]


def test_closing_mps() -> None:
    from engine.tracking.velocity import closing_mps

    _check_all(_run(closing_mps, _closing_cases()), CLOSING_EXPECTED)


def test_depth_closing() -> None:
    from engine.tracking.velocity import depth_closing

    _check_all(_run(depth_closing, _depth_cases()), DEPTH_EXPECTED)


def test_lateral_velocity() -> None:
    from engine.tracking.velocity import lateral_velocity

    _check_all(_run(lateral_velocity, _lateral_cases()), LATERAL_EXPECTED)


def test_cross_velocity() -> None:
    from engine.tracking.velocity import cross_velocity

    _check_all(_run(cross_velocity, _cross_cases()), CROSS_EXPECTED)


# ---- match -----------------------------------------------------------------------------------------------------


def _item(cls: str, bbox: list[float], dist: float, lat: float, group: str = "moving", lane_part: bool = False) -> Any:
    return collision._Item(
        group=group,
        class_name=cls,
        bbox=bbox,
        contact_y=bbox[3],
        distance_m=dist,
        lateral_m=lat,
        bearing=0.0,
        clock=12,
        pan=0.0,
        area_frac=0.01,
        clipped=False,
        touches=True,
        lane_hit=True,
        along_path=False,
        lane_cover=0.3,
        lane_part=lane_part,
    )


def _track(
    tid: int,
    cls: str,
    box: tuple[float, float, float, float],
    last_t: float,
    dist: float,
    lat: float,
    group: str = "moving",
    closing: float | None = None,
    lane_part: bool = False,
) -> Any:
    tr = collision._Track(tid, group, cls, collision.Box(*box), last_t, 0.0, dist, lat)
    tr.closing = closing
    tr.lane_part = lane_part
    return tr


def _match_cases() -> list[tuple[Any, ...]]:
    trk = _cfg()["tracking"]
    people = frozenset({"person", "rider", "animal"})
    out: list[tuple[Any, ...]] = []
    # 1. a deliberate tie: two identical tracks, two identical items; all four pairs score the same
    box = (0.30, 0.40, 0.40, 0.60)
    t1 = {1: _track(1, "person", box, 0.0, 6.0, 0.0), 2: _track(2, "person", box, 0.0, 6.0, 0.0)}
    i1 = [_item("person", [0.30, 0.40, 0.40, 0.60], 6.0, 0.0), _item("person", [0.30, 0.40, 0.40, 0.60], 6.0, 0.0)]
    out.append((t1, i1, 0.1, trk))
    # 2. the same tracks inserted in the other order (the ties follow the insertion order)
    t2 = {2: t1[2], 1: t1[1]}
    out.append((t2, i1, 0.1, trk))
    # 3. three tracks, two items, partial overlaps and equal ground-gate bonus
    t3 = {
        7: _track(7, "person", (0.30, 0.40, 0.40, 0.60), 0.0, 6.0, 0.0),
        5: _track(5, "person", (0.32, 0.40, 0.42, 0.60), 0.0, 6.0, 0.0),
        9: _track(9, "person", (0.34, 0.40, 0.44, 0.60), 0.0, 6.0, 0.0),
    }
    i3 = [_item("person", [0.31, 0.40, 0.41, 0.60], 6.0, 0.0), _item("person", [0.33, 0.40, 0.43, 0.60], 6.0, 0.0)]
    out.append((t3, i3, 0.1, trk))
    # 4. the ground gate matches without any overlap; the expected distance follows the closing speed
    t4 = {3: _track(3, "pole", (0.10, 0.40, 0.14, 0.60), 0.0, 8.0, 1.0, group="static", closing=1.5)}
    i4 = [_item("pole", [0.60, 0.40, 0.64, 0.60], 7.7, 1.2, group="static")]
    out.append((t4, i4, 0.2, trk))
    # 5. same, but the distance is off the gate: no match
    i5 = [_item("pole", [0.60, 0.40, 0.64, 0.60], 6.0, 1.2, group="static")]
    out.append((t4, i5, 0.2, trk))
    # 6. group / class / lane_part mismatches never match
    t6 = {
        1: _track(1, "person", box, 0.0, 6.0, 0.0),
        2: _track(2, "vehicle", box, 0.0, 6.0, 0.0),
        3: _track(3, "person", box, 0.0, 6.0, 0.0, group="static"),
        4: _track(4, "person", box, 0.0, 6.0, 0.0, lane_part=True),
    }
    i6 = [
        _item("person", [0.30, 0.40, 0.40, 0.60], 6.0, 0.0),
        _item("person", [0.30, 0.40, 0.40, 0.60], 6.0, 0.0, lane_part=True),
    ]
    out.append((t6, i6, 0.1, trk))
    # 7. the pan compensation (people only), as in test_collision_v26116
    old = _track(5, "person", (0.3125, 0.45, 0.3833, 0.63), 0.0, 5.9, -2.4)
    new = [_item("person", [0.3875, 0.45, 0.4542, 0.62], 5.7, -0.9)]
    out.append(({5: old}, new, 0.17, trk, 0.077, people))
    out.append(({5: old}, new, 0.17, trk, 0.02, people))
    out.append(({5: old}, new, 0.17, trk, 0.0, people))
    # 8. a bigger shuffled scene: 6 tracks x 6 items, scores with ties between the gate-only pairs
    rng = np.random.RandomState(3)
    tids = [11, 4, 8, 2, 15, 6]
    t8 = {}
    for k, tid in enumerate(tids):
        x = 0.1 + 0.12 * k
        t8[tid] = _track(tid, "person", (x, 0.40, x + 0.08, 0.60), 0.0, 6.0 + 0.3 * k, -1.0 + 0.4 * k)
    i8 = []
    for k in range(6):
        x = 0.1 + 0.12 * k + float(rng.uniform(-0.03, 0.03))
        i8.append(
            _item("person", [x, 0.40, x + 0.08, 0.60], 6.0 + 0.3 * k + float(rng.uniform(-0.2, 0.2)), -1.0 + 0.4 * k)
        )
    out.append((t8, i8, 0.1, trk, 0.0, people))
    out.append((t8, i8[::-1], 0.1, trk, 0.0, people))
    return out


MATCH_EXPECTED: list[dict[int, int]] = [
    {0: 1, 1: 2},
    {0: 2, 1: 1},
    {0: 7, 1: 5},
    {0: 3},
    {},
    {0: 1, 1: 4},
    {0: 5},
    {},
    {},
    {0: 11, 1: 4, 2: 8, 3: 2, 4: 15, 5: 6},
    {0: 6, 1: 15, 2: 2, 3: 8, 4: 4, 5: 11},
]


def test_match_pairings() -> None:
    from engine.tracking.match import match

    got = [match(*c) for c in _match_cases()]
    assert got == MATCH_EXPECTED
    assert [list(g.items()) for g in got] == [list(e.items()) for e in MATCH_EXPECTED]


# ---- coast -----------------------------------------------------------------------------------------------------


def _coast_item(
    cls: str, dist: float, lat: float, group: str = "moving", clipped: bool = False, coasting: bool = False
) -> Any:
    it = _item(cls, [0.4, 0.4, 0.5, 0.6], dist, lat, group=group)
    it.clipped = clipped
    it.coasting = coasting
    it.track_id = 1
    it.moving = group == "moving"
    return it


def _world(heading: float | None = 0.0, speed: float | None = None) -> Any:
    w = collision._WorldMemory({}, enabled=True)
    w.advance(0.0, 0.0, speed, heading)
    return w


def _item_row(g: Any) -> list[float]:
    return [
        g.distance_m,
        g.lateral_m,
        g.bearing,
        float(g.clock),
        float(g.clock_q),
        g.pan,
        g.closing,
        g.closing_raw,
        float(g.present_run),
        float(g.coasting),
        float(g.speak),
        float(g.clipped),
        float(g.map_cells),
    ]


def _item_labels(g: Any) -> list[str]:
    return [g.class_name, g.group, g.clock_text, g.srcsel]


def _episode_row(ep: dict[str, Any]) -> list[Any]:
    return [ep["track"], ep["class"], ep["t0"], ep.get("t1"), ep.get("end"), ep["steps0"], ep["speedMps"], ep["moving"]]


def _coast_digest(coast_cls: Callable[[dict[str, Any]], Any]) -> tuple[list[str], list[float]]:
    """Run six scenarios; returns (labels, floats) in a fixed order."""
    cfg = _cfg()["coast"]
    labels: list[str] = []
    vals: list[float] = []

    def put_items(tag: str, out: list[Any]) -> None:
        labels.append(f"{tag}:n={len(out)}")
        for g in out:
            labels.extend(_item_labels(g))
            vals.extend(_item_row(g))

    def put_state(tag: str, coast: Any, tracks: dict[int, Any]) -> None:
        labels.append(f"{tag}:hist={sorted(coast.hist)}:last={sorted(coast.last)}:active={sorted(coast.active)}")
        for tid in sorted(coast.hist):
            for p in coast.hist[tid]:
                vals.extend(p)
        for ep in coast.episodes:
            row = _episode_row(ep)
            labels.append(f"{tag}:ep:{row[0]}:{row[1]}:{row[4]}:{row[7]}")
            vals.extend(float(x) for x in (row[2], row[3] if row[3] is not None else -1.0, row[5], row[6]))
        for tid in sorted(tracks):
            tr = tracks[tid]
            vals.extend((tr.last_t, tr.last_distance, tr.last_lateral, float(tr.present_run)))

    def mover(cls: str, lat0: float, dist: float, vlat: float, n: int = 6) -> tuple[Any, Any, dict[int, Any]]:
        coast = coast_cls(cfg)
        world = _world()
        tracks: dict[int, Any] = {}
        for k in range(n):
            t = 0.2 * k
            it = _coast_item(cls, dist, lat0 + vlat * t)
            coast.observe(it, t, world)
            tracks[1] = types.SimpleNamespace(last_t=t, last_distance=dist, last_lateral=it.lateral_m, present_run=k)
        return coast, world, tracks

    # A: the v26.2.2 person crossing from the left (6 m ahead, 1.5 m/s)
    coast, world, tracks = mover("person", -3.0, 6.0, 1.5)
    put_items("A1", coast.items(1.4, {}, world, tracks, 0.7))
    put_items("A2", coast.items(1.8, {}, world, tracks, 0.7))
    put_state("A", coast, tracks)
    put_items("A3", coast.items(4.0, {}, world, tracks, 0.7))
    put_state("A-end", coast, tracks)
    # B: a vehicle coasts for vehicleSeconds (3 s) instead of 2 s
    coast, world, tracks = mover("vehicle", -4.0, 12.0, 2.0)
    put_items("B1", coast.items(2.9, {}, world, tracks, 0.7))
    put_items("B2", coast.items(3.5, {}, world, tracks, 0.7))
    put_state("B", coast, tracks)
    # C: the walking user (speed 1.2 m/s, heading 20 deg) moves the closing speed
    coast, world, tracks = mover("person", 1.0, 9.0, -0.5)
    world.advance(1.0, 1.0, 1.2, 20.0)
    put_items("C1", coast.items(1.6, {}, world, tracks, 0.7))
    put_state("C", coast, tracks)

    # D: end reasons. The mover is first coasted at t=1.0 (an episode starts), then the second call ends it.
    def ended(tag: str, dist: float, vlat: float, t2: float, speed: float | None = None, **kw: Any) -> None:
        coast, world, tracks = mover("person", -1.0, dist, vlat)
        if speed is not None:
            world.advance(1.0, 1.0, speed, 0.0)
        put_items(tag + "-1", coast.items(1.2, {}, world, tracks, 0.7))
        if "seen" in kw:
            put_items(tag + "-2", coast.items(t2, kw["seen"], world, kw.get("tracks", tracks), 0.7))
        else:
            put_items(
                tag + "-2",
                coast.items(t2, {}, world, kw.get("tracks", tracks), 0.7, blocked=kw.get("blocked"), ext=kw.get("ext")),
            )
        put_state(tag, coast, kw.get("tracks", tracks))

    ended("D-seen", 6.0, 0.5, 1.6, seen={1: _coast_item("person", 6.0, 0.0)})
    ended("D-lost", 6.0, 0.5, 1.6, tracks={})
    ended("D-rematch", 6.0, 0.5, 1.6, seen={9: _coast_item("person", 6.0, -0.2)})
    ended("D-passed", 6.0, 0.5, 1.6, ext=lambda tid: {"x": 0.5, "y": -1.0, "vx": 0.0, "vy": 0.0})
    ended("D-solid", 6.0, 0.5, 1.6, blocked=lambda fwd, right: fwd > 5.0)
    ended("D-range", 6.0, 0.5, 1.6, ext=lambda tid: {"x": 0.5, "y": 40.0, "vx": 0.0, "vy": 0.0})
    ended("D-ext", 6.0, 0.5, 1.6, ext=lambda tid: {"x": 0.5, "y": 7.0, "vx": 0.4, "vy": 0.1} if tid == 1 else None)
    # E: observe() skip rules, history trimming, and a mover too fast to be coasted
    coast = coast_cls(cfg)
    world = _world()
    for tag, it in (
        ("static", _coast_item("pole", 6.0, 0.0, group="static")),
        ("clipped", _coast_item("person", 6.0, 0.0, clipped=True)),
        ("coasting", _coast_item("person", 6.0, 0.0, coasting=True)),
    ):
        coast.observe(it, 0.0, world)
        labels.append(f"E-{tag}:{sorted(coast.hist)}:{sorted(coast.last)}")
    coast.observe(_coast_item("person", 6.0, 0.0), 0.0, _world(None))
    labels.append(f"E-notheta:{sorted(coast.hist)}")
    off = coast_cls({})
    off.observe(_coast_item("person", 6.0, 0.0), 0.0, world)
    labels.append(f"E-off:{sorted(off.hist)}:{off.items(1.0, {}, world, {}, 0.7)}")
    coast, world, tracks = mover("person", -1.0, 6.0, 0.0, n=12)
    put_state("E-trim", coast, tracks)
    coast, world, tracks = mover("person", -1.0, 6.0, 20.0)
    put_items("E-fast", coast.items(1.4, {}, world, tracks, 0.7))
    return labels, vals


COAST_LABELS_EXPECTED: list[str] = [
    "A1:n=1",
    "person",
    "moving",
    "11:45",
    "",
    "A2:n=1",
    "person",
    "moving",
    "12",
    "",
    "A:hist=[1]:last=[1]:active=[1]",
    "A3:n=0",
    "A-end:hist=[]:last=[]:active=[]",
    "A-end:ep:1:person:expired:True",
    "B1:n=1",
    "vehicle",
    "moving",
    "12:15",
    "",
    "B2:n=1",
    "vehicle",
    "moving",
    "12:30",
    "",
    "B:hist=[1]:last=[1]:active=[1]",
    "C1:n=1",
    "person",
    "moving",
    "11:15",
    "",
    "C:hist=[1]:last=[1]:active=[1]",
    "D-seen-1:n=1",
    "person",
    "moving",
    "11:45",
    "",
    "D-seen-2:n=0",
    "D-seen:hist=[1]:last=[1]:active=[]",
    "D-seen:ep:1:person:rematch:True",
    "D-lost-1:n=1",
    "person",
    "moving",
    "11:45",
    "",
    "D-lost-2:n=0",
    "D-lost:hist=[]:last=[]:active=[]",
    "D-lost:ep:1:person:lost:True",
    "D-rematch-1:n=1",
    "person",
    "moving",
    "11:45",
    "",
    "D-rematch-2:n=0",
    "D-rematch:hist=[]:last=[]:active=[]",
    "D-rematch:ep:1:person:rematch:True",
    "D-passed-1:n=1",
    "person",
    "moving",
    "11:45",
    "",
    "D-passed-2:n=0",
    "D-passed:hist=[]:last=[]:active=[]",
    "D-passed:ep:1:person:passed:True",
    "D-solid-1:n=1",
    "person",
    "moving",
    "11:45",
    "",
    "D-solid-2:n=0",
    "D-solid:hist=[]:last=[]:active=[]",
    "D-solid:ep:1:person:solid:True",
    "D-range-1:n=1",
    "person",
    "moving",
    "11:45",
    "",
    "D-range-2:n=0",
    "D-range:hist=[]:last=[]:active=[]",
    "D-range:ep:1:person:range:True",
    "D-ext-1:n=1",
    "person",
    "moving",
    "11:45",
    "",
    "D-ext-2:n=1",
    "person",
    "moving",
    "12:15",
    "track",
    "D-ext:hist=[1]:last=[1]:active=[1]",
    "E-static:[]:[]",
    "E-clipped:[]:[]",
    "E-coasting:[]:[]",
    "E-notheta:[]",
    "E-off:[]:[]",
    "E-trim:hist=[1]:last=[1]:active=[]",
    "E-fast:n=0",
]
COAST_VALUES_EXPECTED: list[float] = [
    6.0,
    -0.9,
    -8.530765609948133,
    12.0,
    -1.0,
    -0.14834045293024464,
    0.22251067939536698,
    0.22251067939536698,
    6.0,
    1.0,
    0.0,
    1.0,
    0.0,
    6.0,
    -0.2999999999999998,
    -2.862405226111746,
    12.0,
    0.0,
    -0.04993761694389221,
    0.07490642541583832,
    0.07490642541583832,
    7.0,
    1.0,
    0.0,
    1.0,
    0.0,
    0.0,
    -3.0,
    6.0,
    0.2,
    -2.7,
    6.0,
    0.4,
    -2.4,
    6.0,
    0.6000000000000001,
    -2.0999999999999996,
    6.0,
    0.8,
    -1.7999999999999998,
    6.0,
    1.0,
    -1.5,
    6.0,
    1.8,
    6.0,
    -0.2999999999999998,
    7.0,
    1.4,
    4.0,
    8.6,
    1.5,
    1.8,
    6.0,
    -0.2999999999999998,
    7.0,
    12.0,
    1.8000000000000007,
    8.530765609948137,
    12.0,
    1.0,
    0.14834045293024473,
    -0.29668090586048945,
    -0.29668090586048945,
    6.0,
    1.0,
    0.0,
    1.0,
    0.0,
    12.0,
    3.000000000000001,
    14.036243467926484,
    12.0,
    2.0,
    0.24253562503633308,
    -0.4850712500726662,
    -0.4850712500726662,
    7.0,
    1.0,
    0.0,
    1.0,
    0.0,
    0.0,
    -4.0,
    12.0,
    0.2,
    -3.6,
    12.0,
    0.4,
    -3.2,
    12.0,
    0.6000000000000001,
    -2.8,
    12.0,
    0.8,
    -2.4,
    12.0,
    1.0,
    -2.0,
    12.0,
    3.5,
    12.0,
    3.000000000000001,
    7.0,
    7.343868312123661,
    -2.6818649525735205,
    -20.06139664750756,
    11.0,
    -3.0,
    -0.3430268966175354,
    1.126654911165464,
    1.126654911165464,
    6.0,
    1.0,
    0.0,
    1.0,
    0.0,
    0.0,
    1.0,
    9.0,
    0.2,
    0.9,
    9.0,
    0.4,
    0.8,
    9.0,
    0.6000000000000001,
    0.7,
    9.0,
    0.8,
    0.6,
    9.0,
    1.0,
    0.5,
    9.0,
    1.6,
    7.343868312123661,
    -2.6818649525735205,
    6.0,
    6.0,
    -0.4,
    -3.8140748342903543,
    12.0,
    -1.0,
    -0.06651901052377393,
    0.03325950526188697,
    0.03325950526188697,
    6.0,
    1.0,
    0.0,
    1.0,
    0.0,
    0.0,
    -1.0,
    6.0,
    0.2,
    -0.9,
    6.0,
    0.4,
    -0.8,
    6.0,
    0.6000000000000001,
    -0.7,
    6.0,
    0.8,
    -0.6,
    6.0,
    1.0,
    -0.5,
    6.0,
    1.2,
    1.6,
    8.6,
    0.5,
    1.2,
    6.0,
    -0.4,
    6.0,
    6.0,
    -0.4,
    -3.8140748342903543,
    12.0,
    -1.0,
    -0.06651901052377393,
    0.03325950526188697,
    0.03325950526188697,
    6.0,
    1.0,
    0.0,
    1.0,
    0.0,
    1.2,
    1.6,
    8.6,
    0.5,
    6.0,
    -0.4,
    -3.8140748342903543,
    12.0,
    -1.0,
    -0.06651901052377393,
    0.03325950526188697,
    0.03325950526188697,
    6.0,
    1.0,
    0.0,
    1.0,
    0.0,
    1.2,
    1.6,
    8.6,
    0.5,
    1.2,
    6.0,
    -0.4,
    6.0,
    6.0,
    -0.4,
    -3.8140748342903543,
    12.0,
    -1.0,
    -0.06651901052377393,
    0.03325950526188697,
    0.03325950526188697,
    6.0,
    1.0,
    0.0,
    1.0,
    0.0,
    1.2,
    1.6,
    8.6,
    0.5,
    1.2,
    6.0,
    -0.4,
    6.0,
    6.0,
    -0.4,
    -3.8140748342903543,
    12.0,
    -1.0,
    -0.06651901052377393,
    0.03325950526188697,
    0.03325950526188697,
    6.0,
    1.0,
    0.0,
    1.0,
    0.0,
    1.2,
    1.6,
    8.6,
    0.5,
    1.2,
    6.0,
    -0.4,
    6.0,
    6.0,
    -0.4,
    -3.8140748342903543,
    12.0,
    -1.0,
    -0.06651901052377393,
    0.03325950526188697,
    0.03325950526188697,
    6.0,
    1.0,
    0.0,
    1.0,
    0.0,
    1.2,
    1.6,
    8.6,
    0.5,
    1.2,
    6.0,
    -0.4,
    6.0,
    6.0,
    -0.4,
    -3.8140748342903543,
    12.0,
    -1.0,
    -0.06651901052377393,
    0.03325950526188697,
    0.03325950526188697,
    6.0,
    1.0,
    0.0,
    1.0,
    0.0,
    7.0,
    0.5,
    4.085616779974877,
    12.0,
    1.0,
    0.07124704998790964,
    -0.12824468997823738,
    -0.12824468997823738,
    7.0,
    1.0,
    0.0,
    1.0,
    0.0,
    0.0,
    -1.0,
    6.0,
    0.2,
    -0.9,
    6.0,
    0.4,
    -0.8,
    6.0,
    0.6000000000000001,
    -0.7,
    6.0,
    0.8,
    -0.6,
    6.0,
    1.0,
    -0.5,
    6.0,
    1.6,
    7.0,
    0.5,
    7.0,
    1.2000000000000002,
    -1.0,
    6.0,
    1.4000000000000001,
    -1.0,
    6.0,
    1.6,
    -1.0,
    6.0,
    1.8,
    -1.0,
    6.0,
    2.0,
    -1.0,
    6.0,
    2.2,
    -1.0,
    6.0,
    2.2,
    6.0,
    -1.0,
    11.0,
]


def test_coast_over_a_sequence() -> None:
    from engine.tracking.coast import Coast

    labels, vals = _coast_digest(Coast)
    assert labels == COAST_LABELS_EXPECTED
    assert len(vals) == len(COAST_VALUES_EXPECTED)
    assert vals == pytest.approx(COAST_VALUES_EXPECTED, rel=1e-12, abs=1e-12)
