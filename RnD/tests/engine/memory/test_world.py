"""Characterisation tests for engine.memory.world.WorldMemory (v26.3.0 p2-12).

The expected literals were produced by running the legacy ``collision._WorldMemory`` on today's code (hackeye-rnd image)
through the same scenario functions; the engine module is imported inside each test (it does not exist yet).
Pose floats are compared with ``==`` (the DeadReckoner delegation must be bit-identical).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import collision

if TYPE_CHECKING:
    from collections.abc import Callable

CFG: dict[str, Any] = {
    "matchRadiusM": 2.5,
    "matchRangeFraction": 0.10,
    "maxRangeM": 30.0,
    "behindM": -1.0,
    "speedHoldSeconds": 5.0,
    "seenHoldSeconds": 1.0,
    "moverTakeoverSeconds": 1.0,
    "ownerAdoptSeconds": 3.0,
    "radiusOverrides": {"vehicle": 4.0},
}

ATTRS_AFTER_INIT = sorted(
    [
        "enabled",
        "radius",
        "range_frac",
        "max_range",
        "behind",
        "hold_s",
        "seen_hold_s",
        "takeover_s",
        "adopt_s",
        "overrides",
        "x",
        "y",
        "theta",
        "speed",
        "speed_t",
        "entries",
        "_next",
    ]
)


def _item(
    track_id: int,
    label: str,
    dist: float,
    lat: float,
    family: str = "",
    people: bool = False,
    moving: bool | None = None,
) -> Any:
    from engine.core.types import Item

    it = Item(
        group="static",
        class_name=label,
        bbox=[0.4, 0.5, 0.5, 0.6],
        contact_y=0.6,
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
        lane_cover=1.0,
    )
    it.track_id, it.label, it.family, it.people, it.moving = track_id, label, family, people, moving
    return it


def _tracks(*ids: int) -> dict[int, Any]:
    from engine.core.geom import Box
    from engine.core.types import Track

    box = Box(0.4, 0.5, 0.5, 0.6)
    return {i: Track(i, "static", "x", box, last_t=0.0, first_t=0.0, last_distance=0.0, last_lateral=5.0) for i in ids}


def _snap(label: str, m: Any, **extra: Any) -> tuple[Any, ...]:
    return (
        label,
        m.x,
        m.y,
        m.theta,
        m.speed,
        m.speed_t,
        m.active,
        m._next,
        {k: dict(v) for k, v in m.entries.items()},
        extra,
    )


def _scenario(cls: Any) -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    m = cls(CFG)
    out.append(_snap("init", m))
    m.advance(0.0, 0.0, 1.26, 0.0)
    out.append(_snap("first", m))
    m.advance(0.2, 0.2, 1.3, 5.0)
    out.append(_snap("walk1", m))
    tr = _tracks(*range(1, 12))
    pole, person, car, wall = (
        _item(1, "pole", 10.0, 1.0),
        _item(2, "person", 6.0, -2.0, people=True),
        _item(3, "vehicle", 12.0, 3.0),
        _item(4, "building", 20.0, -4.0),
    )
    m.link([pole, person, car, wall], tr, 0.2)
    out.append(
        _snap(
            "link0",
            m,
            mem=[i.mem_id for i in (pole, person, car, wall)],
            w=[(i.wx, i.wy) for i in (pole, person, car, wall)],
            tr=[(t.mem_id, t.linked_t) for t in tr.values()][:4],
        )
    )
    ids = [m.add(i, 0.2) for i in (pole, person, car, wall)]
    out.append(_snap("added", m, ids=ids))
    m.advance(0.4, 0.2, None, 8.0)
    out.append(_snap("walk2", m))
    # same family, nearby: matched; far / other family: not; the vehicle override widens the radius
    near, far = _item(5, "pole", 10.0, 2.5), _item(6, "pole", 10.0, 6.0)
    parked = _item(7, "parked car", 12.0, 6.5, family="vehicle")
    m.link([near, far, parked], tr, 0.5)
    out.append(
        _snap(
            "link1",
            m,
            mem=[i.mem_id for i in (near, far, parked)],
            w=[(i.wx, i.wy) for i in (near, far, parked)],
            active=m.active,
        )
    )
    out.append(
        _snap(
            "match",
            m,
            a=m.match(near, 0.5),
            b=m.match(far, 0.5),
            c=m.match(parked, 0.5),
            d=m.match(person, 0.5),
            e=m.match(person, 3.0),
        )
    )
    # a person walks on: refreshed by the owning track
    mover = _item(2, "person", 6.0, -2.0, people=True, moving=True)
    m.link([mover], tr, 0.6)
    out.append(_snap("mover", m, mem=mover.mem_id, w=(mover.wx, mover.wy), tr=(tr[2].mem_id, tr[2].linked_t)))
    m.refresh(ids[0], near, 0.7)
    out.append(_snap("refresh", m))
    loc = m.locate(far)
    out.append(_snap("locate", m, loc=loc))
    # speed hold expires, then a pose from the online map, then the turn
    m.advance(7.0, 6.6, None, 20.0)
    out.append(_snap("hold_expired", m))
    m.advance(7.2, 0.2, 1.1, 30.0, (3.5, 4.5, 31.0))
    out.append(_snap("pose", m))
    m.advance(7.5, 0.3, 1.2, 40.0)
    out.append(_snap("walk3", m))
    m.advance(7.8, 0.3, 1.2, None)
    out.append(_snap("no_heading", m, active=m.active))
    m.advance(8.1, 0.3, 1.2, 95.0)
    out.append(_snap("resume", m, active=m.active))
    for k in range(6):
        m.advance(9.0 + k * 3.0, 3.0, 1.4, 95.0 + 10.0 * k)
        out.append(_snap(f"far{k}", m))
    m.enabled = False
    out.append(_snap("disabled", m, active=m.active))
    return out


def _scenario_defaults(cls: Any) -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    m = cls({}, True)
    out.append(_snap("init", m, en=m.enabled, hold=m.hold_s, r=(m.radius, m.range_frac, m.max_range, m.behind)))
    off = cls({"enabled": False})
    out.append(_snap("cfg_off", off, active=off.active))
    off2 = cls({}, enabled=False)
    out.append(_snap("arg_off", off2, active=off2.active))
    m.advance(1.0, 1.0, 2.0, 90.0)
    m.advance(2.0, 1.0, 2.0, 90.0)
    out.append(_snap("east", m))
    it = _item(1, "bench", 5.0, 0.5)
    tr = _tracks(1)
    m.link([it], tr, 2.0)
    out.append(_snap("link", m, mem=it.mem_id, w=(it.wx, it.wy)))
    eid = m.add(it, 2.0, named=False)
    out.append(_snap("add", m, eid=eid))
    again = _item(1, "bench", 5.0, 0.5)
    tr[1].mem_id = None
    m.link([again], tr, 2.5)
    out.append(
        _snap(
            "relink",
            m,
            mem=again.mem_id,
            named=again.mem_named,
            ap=again.mem_approach,
            dg=again.mem_danger,
            tr=(tr[1].mem_id, tr[1].linked_t),
        )
    )
    return out


def _scenario_said(cls: Any, say: Callable[[Any, int, float, float], None]) -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    m = cls(CFG)
    m.advance(0.0, 0.0, 1.0, 0.0)
    a, b = _item(1, "pole", 10.0, 0.0), _item(2, "sign", 4.0, 0.0)
    m.link([a, b], _tracks(1, 2), 0.0)
    ea, eb = m.add(a, 0.0), m.add(b, 0.0)
    out.append(_snap("added", m, ids=(ea, eb)))
    say(m, ea, 7.0, 0.5)
    out.append(_snap("said_a", m))
    say(m, eb, 3.5, 0.75)
    out.append(_snap("said_b", m))
    m.advance(0.9, 0.9, 1.0, 0.0)
    out.append(_snap("kept_in_view", m))
    # past the seen hold: b (4 m ahead) is passed after walking 6 m, a (10 m ahead) is kept
    m.advance(3.0, 2.1, 2.0, 0.0)
    out.append(_snap("b_pruned_a_kept", m))
    m.advance(6.0, 3.0, 2.0, 0.0)
    out.append(_snap("a_pruned", m))
    m.advance(12.0, 6.0, 2.0, 0.0)
    out.append(_snap("nothing_left", m))
    return out


def _assert_same(got: list[tuple[Any, ...]], want: list[tuple[Any, ...]]) -> None:
    assert len(got) == len(want)
    for g, w in zip(got, want, strict=True):
        assert g == w, w[0]


def test_identity() -> None:
    import engine.memory as memory_pkg
    from engine.core.types import Item, Track
    from engine.memory.world import WorldMemory

    assert collision._WorldMemory is WorldMemory
    assert memory_pkg.WorldMemory is WorldMemory
    assert "WorldMemory" in memory_pkg.__all__
    assert collision._Item is Item and collision._Track is Track


def test_attribute_list_after_init() -> None:
    from engine.memory.world import WorldMemory

    m = WorldMemory(CFG)
    assert all(hasattr(m, name) for name in ATTRS_AFTER_INIT)
    legacy = collision._WorldMemory(CFG)
    for name in ATTRS_AFTER_INIT:
        assert getattr(m, name) == getattr(legacy, name)
    assert m.active is legacy.active is False


def test_attributes_assignable() -> None:
    from engine.memory.world import WorldMemory

    m = WorldMemory(CFG)
    m.x, m.y, m.theta, m.speed, m.speed_t, m.hold_s = 1.5, -2.5, 33.0, 0.7, 4.0, 2.0
    assert (m.x, m.y, m.theta, m.speed, m.speed_t, m.hold_s) == (1.5, -2.5, 33.0, 0.7, 4.0, 2.0)
    assert m.active
    m.theta = None
    assert not m.active
    # tests build instances with __new__ and assign attributes
    n = WorldMemory.__new__(WorldMemory)
    n.entries = {}
    n.enabled, n.theta = True, 10.0
    assert n.active


def test_full_sequence_matches_legacy() -> None:
    from engine.memory.world import WorldMemory

    _assert_same(_scenario(WorldMemory), EXPECTED_SCENARIO)


def test_defaults_scenario_matches_legacy() -> None:
    from engine.memory.world import WorldMemory

    _assert_same(_scenario_defaults(WorldMemory), EXPECTED_DEFAULTS)


def _said_via_api(m: Any, mem_id: int, steps: float, t: float) -> None:
    m.mark_said(mem_id, steps, t)


def _said_direct(m: Any, mem_id: int, steps: float, t: float) -> None:
    m.entries[mem_id]["said"] = (steps, t)


def test_said_scenario_matches_legacy() -> None:
    from engine.memory.world import WorldMemory

    _assert_same(_scenario_said(WorldMemory, _said_via_api), EXPECTED_SAID)
    # the direct write of the speech code gives the same states as the new API
    _assert_same(_scenario_said(WorldMemory, _said_direct), EXPECTED_SAID)


def test_mark_said_round_trip() -> None:
    from engine.memory.world import WorldMemory

    m = WorldMemory(CFG)
    m.advance(0.0, 0.0, 1.0, 0.0)
    it = _item(1, "pole", 10.0, 0.0)
    m.link([it], _tracks(1), 0.0)
    eid = m.add(it, 0.0)
    assert m.said_at(eid) is None
    assert "said" not in m.entries[eid]
    m.mark_said(eid, 6.0, 12.5)
    assert m.said_at(eid) == (6.0, 12.5)
    assert m.entries[eid]["said"] == (6.0, 12.5)
    m.mark_said(eid, 4.0, 14.0)
    assert m.said_at(eid) == (4.0, 14.0)
    # a value written directly under the same key (speech today) is read back
    m.entries[eid]["said"] = (2.0, 20.0)
    assert m.said_at(eid) == (2.0, 20.0)


def test_object_memory_protocol_in_core() -> None:
    from engine.core.types import ObjectMemory
    from engine.memory.world import WorldMemory

    for name in ("active", "entries", "add", "mark_said", "said_at"):
        assert name in ObjectMemory.__dict__.get("__annotations__", {}) or hasattr(ObjectMemory, name)
    assert hasattr(WorldMemory, "mark_said") and hasattr(WorldMemory, "said_at")


EXPECTED_SCENARIO: list[tuple[Any, ...]] = [
    ("init", 0.0, 0.0, None, None, -math.inf, False, 1, {}, {}),
    ("first", 0.0, 0.0, 0.0, 1.26, 0.0, True, 1, {}, {}),
    ("walk1", 0.011341040714987361, 0.25975253761128303, 5.0, 1.3, 0.2, True, 1, {}, {}),
    (
        "link0",
        0.011341040714987361,
        0.25975253761128303,
        5.0,
        1.3,
        0.2,
        True,
        1,
        {},
        {
            "mem": [None, None, None, None],
            "w": [
                (1.8790931662833144, 10.13454377578108),
                (-1.4581138989825546, 6.411232211657073),
                (4.045794047962122, 11.952621686469255),
                (-2.2303228966988318, 20.532269470436827),
            ],
            "tr": [(None, 0.2), (None, 0.2), (None, 0.2), (None, 0.2)],
        },
    ),
    (
        "added",
        0.011341040714987361,
        0.25975253761128303,
        5.0,
        1.3,
        0.2,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 1.8790931662833144,
                "y": 10.13454377578108,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 1,
            },
            2: {
                "family": "person",
                "x": -1.4581138989825546,
                "y": 6.411232211657073,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 2,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {"ids": [1, 2, 3, 4]},
    ),
    (
        "walk2",
        0.04077387629464311,
        0.5180812200871958,
        8.0,
        1.3,
        0.2,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 1.8790931662833144,
                "y": 10.13454377578108,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 1,
            },
            2: {
                "family": "person",
                "x": -1.4581138989825546,
                "y": 6.411232211657073,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 2,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {},
    ),
    (
        "link1",
        0.04077387629464311,
        0.5180812200871958,
        8.0,
        1.3,
        0.2,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 1.8790931662833144,
                "y": 10.13454377578108,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 1,
            },
            2: {
                "family": "person",
                "x": -1.4581138989825546,
                "y": 6.411232211657073,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 2,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {
            "mem": [1, None, 3],
            "w": [
                (3.908175057749223, 10.072829155102735),
                (7.37411329834472, 9.585723301742506),
                (8.147593534635636, 11.496672888745614),
            ],
            "active": True,
        },
    ),
    (
        "match",
        0.04077387629464311,
        0.5180812200871958,
        8.0,
        1.3,
        0.2,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 1.8790931662833144,
                "y": 10.13454377578108,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 1,
            },
            2: {
                "family": "person",
                "x": -1.4581138989825546,
                "y": 6.411232211657073,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 2,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {"a": 1, "b": None, "c": 3, "d": 2, "e": None},
    ),
    (
        "mover",
        0.04077387629464311,
        0.5180812200871958,
        8.0,
        1.3,
        0.2,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 1.8790931662833144,
                "y": 10.13454377578108,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 1,
            },
            2: {
                "family": "person",
                "x": -1.104723655428105,
                "y": 6.73803583445675,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.6,
                "fresh": 0.6,
                "owner": 2,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {"mem": 2, "w": (-1.104723655428105, 6.73803583445675), "tr": (2, 0.6)},
    ),
    (
        "refresh",
        0.04077387629464311,
        0.5180812200871958,
        8.0,
        1.3,
        0.2,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 3.908175057749223,
                "y": 10.072829155102735,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.7,
                "fresh": 0.7,
                "owner": 5,
            },
            2: {
                "family": "person",
                "x": -1.104723655428105,
                "y": 6.73803583445675,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.6,
                "fresh": 0.6,
                "owner": 2,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {},
    ),
    (
        "locate",
        0.04077387629464311,
        0.5180812200871958,
        8.0,
        1.3,
        0.2,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 3.908175057749223,
                "y": 10.072829155102735,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.7,
                "fresh": 0.7,
                "owner": 5,
            },
            2: {
                "family": "person",
                "x": -1.104723655428105,
                "y": 6.73803583445675,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.6,
                "fresh": 0.6,
                "owner": 2,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {"loc": (7.37411329834472, 9.585723301742506)},
    ),
    (
        "hold_expired",
        0.04077387629464311,
        0.5180812200871958,
        20.0,
        1.3,
        0.2,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 3.908175057749223,
                "y": 10.072829155102735,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.7,
                "fresh": 0.7,
                "owner": 5,
            },
            2: {
                "family": "person",
                "x": -1.104723655428105,
                "y": 6.73803583445675,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.6,
                "fresh": 0.6,
                "owner": 2,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {},
    ),
    (
        "pose",
        3.5,
        4.5,
        31.0,
        1.1,
        7.2,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 3.908175057749223,
                "y": 10.072829155102735,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.7,
                "fresh": 0.7,
                "owner": 5,
            },
            2: {
                "family": "person",
                "x": -1.104723655428105,
                "y": 6.73803583445675,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.6,
                "fresh": 0.6,
                "owner": 2,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {},
    ),
    (
        "walk3",
        3.7090530640559383,
        4.793081586608275,
        40.0,
        1.2,
        7.5,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 3.908175057749223,
                "y": 10.072829155102735,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.7,
                "fresh": 0.7,
                "owner": 5,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {},
    ),
    (
        "no_heading",
        3.7090530640559383,
        4.793081586608275,
        None,
        1.2,
        7.5,
        False,
        5,
        {
            1: {
                "family": "pole",
                "x": 3.908175057749223,
                "y": 10.072829155102735,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.7,
                "fresh": 0.7,
                "owner": 5,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
            4: {
                "family": "building",
                "x": -2.2303228966988318,
                "y": 20.532269470436827,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 4,
            },
        },
        {"active": False},
    ),
    (
        "resume",
        4.067683155368966,
        4.7617055192191176,
        95.0,
        1.2,
        8.1,
        True,
        5,
        {
            1: {
                "family": "pole",
                "x": 3.908175057749223,
                "y": 10.072829155102735,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.7,
                "fresh": 0.7,
                "owner": 5,
            },
            3: {
                "family": "vehicle",
                "x": 4.045794047962122,
                "y": 11.952621686469255,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.2,
                "fresh": 0.2,
                "owner": 3,
            },
        },
        {"active": True},
    ),
    ("far0", 8.251700887354296, 4.395651399678953, 95.0, 1.4, 9.0, True, 5, {}, {}),
    ("far1", 12.387893450005569, 3.666329053477846, 105.0, 1.4, 12.0, True, 5, {}, {}),
    ("far2", 16.334602457306385, 2.2298444515100373, 115.0, 1.4, 15.0, True, 5, {}, {}),
    ("far3", 19.971909153201025, 0.12984445151003854, 125.0, 1.4, 18.0, True, 5, {}, {}),
    ("far4", 23.18929581430073, -2.5698635091734263, 135.0, 1.4, 21.0, True, 5, {}, {}),
    ("far5", 25.889003774984197, -5.787250170273133, 145.0, 1.4, 24.0, True, 5, {}, {}),
    ("disabled", 25.889003774984197, -5.787250170273133, 145.0, 1.4, 24.0, False, 5, {}, {"active": False}),
]

EXPECTED_DEFAULTS: list[tuple[Any, ...]] = [
    ("init", 0.0, 0.0, None, None, -math.inf, False, 1, {}, {"en": True, "hold": 5.0, "r": (2.5, 0.1, 30.0, -1.0)}),
    ("cfg_off", 0.0, 0.0, None, None, -math.inf, False, 1, {}, {"active": False}),
    ("arg_off", 0.0, 0.0, None, None, -math.inf, False, 1, {}, {"active": False}),
    ("east", 4.0, 2.4492935982947064e-16, 90.0, 2.0, 2.0, True, 1, {}, {}),
    ("link", 4.0, 2.4492935982947064e-16, 90.0, 2.0, 2.0, True, 1, {}, {"mem": None, "w": (9.0, -0.49999999999999944)}),
    (
        "add",
        4.0,
        2.4492935982947064e-16,
        90.0,
        2.0,
        2.0,
        True,
        2,
        {
            1: {
                "family": "bench",
                "x": 9.0,
                "y": -0.49999999999999944,
                "named": False,
                "approach": False,
                "danger": False,
                "seen": 2.0,
                "fresh": 2.0,
                "owner": 1,
            }
        },
        {"eid": 1},
    ),
    (
        "relink",
        4.0,
        2.4492935982947064e-16,
        90.0,
        2.0,
        2.0,
        True,
        2,
        {
            1: {
                "family": "bench",
                "x": 9.0,
                "y": -0.49999999999999944,
                "named": False,
                "approach": False,
                "danger": False,
                "seen": 2.5,
                "fresh": 2.0,
                "owner": 1,
            }
        },
        {"mem": 1, "named": False, "ap": False, "dg": False, "tr": (1, 2.5)},
    ),
]

EXPECTED_SAID: list[tuple[Any, ...]] = [
    (
        "added",
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        True,
        3,
        {
            1: {
                "family": "pole",
                "x": 0.0,
                "y": 10.0,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.0,
                "fresh": 0.0,
                "owner": 1,
            },
            2: {
                "family": "sign",
                "x": 0.0,
                "y": 4.0,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.0,
                "fresh": 0.0,
                "owner": 2,
            },
        },
        {"ids": (1, 2)},
    ),
    (
        "said_a",
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        True,
        3,
        {
            1: {
                "family": "pole",
                "x": 0.0,
                "y": 10.0,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.0,
                "fresh": 0.0,
                "owner": 1,
                "said": (7.0, 0.5),
            },
            2: {
                "family": "sign",
                "x": 0.0,
                "y": 4.0,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.0,
                "fresh": 0.0,
                "owner": 2,
            },
        },
        {},
    ),
    (
        "said_b",
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        True,
        3,
        {
            1: {
                "family": "pole",
                "x": 0.0,
                "y": 10.0,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.0,
                "fresh": 0.0,
                "owner": 1,
                "said": (7.0, 0.5),
            },
            2: {
                "family": "sign",
                "x": 0.0,
                "y": 4.0,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.0,
                "fresh": 0.0,
                "owner": 2,
                "said": (3.5, 0.75),
            },
        },
        {},
    ),
    (
        "kept_in_view",
        0.0,
        0.9,
        0.0,
        1.0,
        0.9,
        True,
        3,
        {
            1: {
                "family": "pole",
                "x": 0.0,
                "y": 10.0,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.0,
                "fresh": 0.0,
                "owner": 1,
                "said": (7.0, 0.5),
            },
            2: {
                "family": "sign",
                "x": 0.0,
                "y": 4.0,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.0,
                "fresh": 0.0,
                "owner": 2,
                "said": (3.5, 0.75),
            },
        },
        {},
    ),
    (
        "b_pruned_a_kept",
        0.0,
        5.1000000000000005,
        0.0,
        2.0,
        3.0,
        True,
        3,
        {
            1: {
                "family": "pole",
                "x": 0.0,
                "y": 10.0,
                "named": True,
                "approach": False,
                "danger": False,
                "seen": 0.0,
                "fresh": 0.0,
                "owner": 1,
                "said": (7.0, 0.5),
            }
        },
        {},
    ),
    ("a_pruned", 0.0, 11.100000000000001, 0.0, 2.0, 6.0, True, 3, {}, {}),
    ("nothing_left", 0.0, 23.1, 0.0, 2.0, 12.0, True, 3, {}, {}),
]
