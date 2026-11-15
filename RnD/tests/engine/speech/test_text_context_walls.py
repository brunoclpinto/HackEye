"""Characterisation tests for engine.speech text / context / walls (v26.3.0 p3-12).

Every literal below was printed by the legacy collision.SpeechPolicy text / context / wall methods and by
collision._followed_wall, _WallFollow and _passing_close in the hackeye-rnd image before the move, by feeding them
the inputs built by the helpers of this file (the policy is built on the raw common/config/collision.json).
The engine modules are imported inside each test (they do not exist yet).
"""

from __future__ import annotations

import inspect
import json
import math
from typing import Any

import collision
from common_paths import find_common_dir

TEXT_NAMES: list[str] = ["_n", "_join_clocks", "_steps_txt", "_fmt", "_text", "_plural", "_kind", "_entry", "_words"]
CONTEXT_NAMES: list[str] = [
    "clear_context",
    "_key",
    "_known",
    "_mem",
    "_seen_before",
    "_register",
    "observe_context",
    "surface_adopted",
    "memory_if_spoken",
]
WALLS_NAMES: list[str] = ["note_wall", "_known_wall"]


def _cfg() -> dict[str, Any]:
    cfg: dict[str, Any] = json.loads((find_common_dir() / "config" / "collision.json").read_text())
    return cfg


def _policy() -> Any:
    return collision.SpeechPolicy(_cfg())


# (label, steps, clock_q, clock_text, flags)
_STUBS: list[tuple[str, float, int, str, dict[str, Any]]] = [
    ("pole", 6.0, 0, "12", {}),
    ("curb", 1.2, 0, "12", {}),
    ("person", 0.2, 4, "1", {}),
    ("pole", math.inf, 0, "12", {}),
    ("pole", math.nan, -1, "11:45", {}),
    ("person", 4.4, 2, "12:30", {"people": True, "moving": True, "approaching": True, "ego_settled": True}),
    (
        "vehicle",
        9.0,
        -4,
        "11",
        {"fast": True, "moving": True, "approaching": True, "ego_settled": True, "role": "danger"},
    ),
    ("vehicle", 5.0, 3, "12:45", {"own_ok": True, "moving": True, "approaching": True, "ego_settled": True}),
    (
        "vehicle",
        5.0,
        2,
        "12:30",
        {"own_ok": True, "moving": True, "approaching": True, "ego_settled": True, "from_side": "right"},
    ),
    ("person", 7.0, 1, "12:15", {"people": True, "moving": True, "receding": True, "ego_settled": True}),
    ("person", 3.0, 0, "12", {"people": True, "moving": False, "ego_settled": True}),
    ("rider", 3.0, 0, "12", {"people": True, "moving": False, "ego_settled": True, "class_name": "rider"}),
    ("person", 5.0, 0, "12", {"people": True, "moving": True, "approaching": True, "ego_settled": False}),
    ("pole", 8.5, -2, "11:30", {}),
    ("car", 6.0, 2, "12:30", {"fast": True, "moving": True, "approaching": True, "own_fast": True, "role": "final"}),
]


def _stub(label: str, steps: float, clock_q: int, clock_text: str, flags: dict[str, Any]) -> Any:
    it = collision._Item(
        group="static",
        class_name=label,
        bbox=[0.4, 0.5, 0.5, 0.6],
        contact_y=0.6,
        distance_m=steps * 0.7,
        lateral_m=0.0,
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
    it.label, it.steps, it.clock_q, it.clock_text = label, steps, clock_q, clock_text
    for k, v in flags.items():
        setattr(it, k, v)
    return it


def _stubs() -> list[Any]:
    return [_stub(*s) for s in _STUBS]


def _text_rows() -> list[list[Any]]:
    """Per stub: steps text, kind of "danger", the "danger" / "approach" / "feature" texts."""
    p = _policy()
    rows: list[list[Any]] = []
    for it in _stubs():
        rows.append(
            [
                p._steps_txt(it),
                p._kind(it, "danger"),
                p._text("danger", it),
                p._text("approach", it),
                p._text("feature", it),
            ]
        )
    return rows


def _entry_rows() -> list[Any]:
    p = _policy()
    st = _stubs()
    out: list[Any] = [
        p._entry("danger", [st[0]]),
        p._entry("danger", [st[0], st[13]]),
        p._entry("danger", [st[0], st[1], st[13]]),
        p._entry("thin", [st[0]]),
        p._entry("thin", [st[0], st[13]]),
        p._entry("approach", [st[5]]),
        p._entry("approach", [st[6]]),
        p._entry("approach", [st[8]]),
        p._entry("approach", [st[5], st[7]]),
        p._entry("receding", [st[9]]),
        p._entry("standing", [st[10]]),
        p._entry("standing", [st[10], st[2]]),
        p._entry("stopped", [st[11]]),
        p._entry("danger", [st[3]]),
    ]
    return out


def _misc_rows() -> list[Any]:
    p = _policy()
    st = _stubs()
    return [
        [p._n(s) for s in (0.0, 0.4, 0.5, 1.5, 2.5, 7.6)],
        p._join_clocks([st[0]]),
        p._join_clocks([st[5], st[2]]),
        p._join_clocks([st[6], st[5], st[2]]),
        [p._plural("pole"), p._plural("poles")],
        [p._words("pole at 12 in 8, curb at 1"), p._words("")],
        p._text("surface", None, "road"),
        p._fmt("danger", label="pole", clock="12", steps=None),
        p._fmt("danger", label="pole", clock="12", steps="3"),
        sorted(p.STATE_WORDS),
    ]


def _walls_policy_rows() -> list[Any]:
    """note_wall / _known_wall with known walls on, then observe_context / clear_context / memory_if_spoken."""
    p = _policy()
    p.known_on = True
    a = _stub("building", 3.0, -3, "10:15", {"family": "building", "wx": 1.0, "wy": 5.0})
    p.known_classes = frozenset({"building", "wall"})
    out: list[Any] = []
    out.append(p._known_wall(10.0, a))
    p.note_wall(10.0, a)
    out.append(len(p.known_walls))
    b = _stub("building", 3.5, -3, "10:15", {"family": "building", "wx": 9.0, "wy": 9.0})
    out.append(p._known_wall(12.0, b))  # same relative place
    c = _stub("building", 9.0, 3, "12:45", {"family": "building", "wx": 9.0, "wy": 9.0})
    out.append(p._known_wall(12.5, c))  # elsewhere
    d = _stub("building", 3.0, -3, "10:15", {"family": "building", "wx": 1.5, "wy": 5.0})
    out.append(p._known_wall(60.0, d))  # window over
    pole = _stub("pole", 3.0, 0, "12", {"wx": 1.0, "wy": 5.0})
    p.note_wall(11.0, pole)
    out.append(len(p.known_walls))
    p.note_wall(50.0, a)
    out.append(len(p.known_walls))  # the first one aged out
    # context
    q = _policy()
    q.memory = {"pole": 1.0, "curb": 20.0}
    q.observe_context(40.0, {"pole"})
    out.append(sorted(q.memory.items()))
    q.observe_context(100.0, set())
    out.append(sorted(q.memory.items()))
    q.memory = {"curb": 5.0}
    q.pending_since = {"x": 1.0}
    q.thin_armed = False
    q.clear_context(7.0)
    out.append([q.memory, q.pending_since, q.thin_armed, q.first_summary, q.summary, q.summary_since])
    r = _policy()
    r.context_speak = {"pole"}
    r.memory_if_spoken(3.0, _stub("pole", 3.0, 0, "12", {}))
    r.memory_if_spoken(4.0, _stub("curb", 3.0, 0, "12", {}))
    r.memory_if_spoken(5.0, _stub("vehicle", 3.0, 0, "12", {"family": "vehicle"}))
    out.append(dict(r.memory))
    out.append(
        [r._key(_stub("pole", 1.0, 0, "12", {})), r._key(_stub("parked car", 1.0, 0, "12", {"family": "vehicle"}))]
    )
    out.append([r._known("pole"), r._known("curb"), r._mem])
    out.append(r._seen_before(_stub("pole", 1.0, 0, "12", {})))
    s = _policy()
    s.surface_adopted("sidewalk", "road", {"announceGroups": ["road"], "groups": {"road": {"label": "road"}}})
    out.append(s.surface_pending)
    s.surface_pending = None
    s.surface_adopted("sidewalk", "bike", {"announceGroups": ["road"], "groups": {"bike": {"label": "bike lane"}}})
    out.append(s.surface_pending)
    s.surface_adopted(
        "road", "sidewalk", {"announceGroups": ["road"], "groups": {"sidewalk": {"label": "sidewalk"}}}, announce=False
    )
    out.append(s.surface_pending)
    return out


def _wall(clock_q: int, steps: float = 3.0, lat: float = 0.5, cls: str = "building") -> Any:
    it = _stub(cls, steps, clock_q, "x", {})
    it.class_name, it.lateral_m, it.family = cls, lat, "building"
    return it


def _followed_rows(followed_wall: Any) -> list[Any]:
    cfg = _cfg()["beeps"]["follow"] | {"enabled": True}
    st: dict[Any, Any] = {}
    seq = [
        (_wall(3, lat=0.4), 10.0),
        (_wall(3, lat=0.4), 10.2),
        (_wall(2, lat=0.5), 12.7),
        (_wall(2, lat=0.5), 14.0),
        (_wall(2, lat=0.5), 16.5),
    ]
    out: list[Any] = [followed_wall(it, t, st, cfg) for it, t in seq]
    out.append(sorted((k, round(v["t"], 6), round(v["t_real"], 6), v["lat"]) for k, v in st.items()))
    for it in (
        _wall(0),
        _wall(3, steps=1.0),
        _wall(3, lat=1.2),
        _wall(-3, lat=-0.5),
        _wall(3, cls="pole"),
        _wall(1),
        _wall(-2, lat=0.4),
    ):
        st = {}
        followed_wall(_wall(3), 10.0, st, cfg)
        out.append(followed_wall(it, 12.7, st, cfg))
    return out


def _follow_item(tid: int, dist: float, cls: str = "building") -> Any:
    it = _stub(cls, dist / 0.74, 0, "12", {})
    it.class_name, it.family, it.lateral_m, it.track_id, it.distance_m = cls, "building", 0.4, tid, dist
    return it


def _run(
    wf: Any, dists: list[float], dt: float = 0.2, speed: float | None = 1.3, tid: int = 1, t0: float = 10.0
) -> list[Any]:
    out = []
    for k, d in enumerate(dists):
        it = _follow_item(tid, d)
        wf.advance(dt, speed)
        wf.observe(t0 + k * dt, [it])
        out.append(it)
    return out


def _walk_rows(wall_follow: Any) -> list[Any]:
    cfg = _cfg()["beeps"]["follow"] | {"enabled": True}

    def known() -> Any:
        wf = wall_follow(cfg)
        wf.first[1] = 0.0
        return wf

    out: list[Any] = []
    for dists, kw in (
        ([3.0] * 12, {}),
        ([6.0 - 0.26 * k for k in range(12)], {}),
        ([3.0 - 0.1 * k for k in range(12)], {}),
        ([4.0 - 0.15 * k for k in range(12)], {}),
        ([3.0] * 12, {"speed": 0.0}),
        ([0.7] * 12, {}),
        ([1.8] * 8 + [7.0] * 3, {}),
        ([3.0] * 12, {"speed": None}),
    ):
        its = _run(known(), dists, **kw)
        out.append([bool(i.followed) for i in its])
    # unknown track: a just-appeared wall is news, unless a wall was due a moment ago; known after 8 s
    wf = wall_follow(cfg)
    out.append(bool(_run(wf, [3.0] * 12)[-1].followed))
    wf = wall_follow(cfg)
    wf.candidate(9.0, _follow_item(1, 3.0))
    out.append(bool(_run(wf, [3.0] * 12)[-1].followed))
    wf = wall_follow(cfg)
    out.append(bool(_run(wf, [3.0] * 40)[-1].followed))
    # a gap restarts the history
    wf = known()
    _run(wf, [3.0] * 8)
    it = _follow_item(1, 3.0)
    wf.advance(1.5, 1.3)
    wf.observe(13.0, [it])
    out.append(bool(it.followed))
    # coasting / ghost / other classes are never followed
    wf = known()
    for flag in ("coasting", "ghost"):
        it = _follow_item(1, 3.0)
        setattr(it, flag, True)
        it.followed = True
        wf.observe(10.0, [it])
        out.append(bool(it.followed))
    it = _follow_item(1, 3.0, cls="pole")
    it.followed = True
    wf.observe(10.0, [it])
    out.append(bool(it.followed))
    # quiet / candidate / beeped
    wf = wall_follow(cfg)
    it = _follow_item(1, 3.0)
    it.followed = True
    q = [wf.quiet(20.0, it, 1.5)]
    wf.beeped(19.0, it)
    q += [wf.quiet(20.0, it, 1.5), wf.quiet(21.0, it, 1.5)]
    it.followed = False
    q.append(wf.quiet(21.0, it, 1.5))
    out.append(q)
    wf = wall_follow(cfg)
    c = [wf.candidate(1.0, it), wf.candidate(1.5, it), wf.candidate(4.0, it), wf.candidate(4.2, it)]
    out.append([c, sorted(wf.cand_last.items()), sorted(wf.prev_end.items())])
    return out


def _passing_item(group: str, lat: float, steps: float, closing: float | None, **kw: Any) -> Any:
    it = _stub("person", steps, 0, "12", {})
    it.group, it.lateral_m, it.closing = group, lat, closing
    it.moving, it.collision, it.receding = True, False, False
    for k, v in kw.items():
        setattr(it, k, v)
    return it


def _passing_rows(passing_close: Any) -> list[bool]:
    cfg = _cfg()["beeps"]["passing"] | {"enabled": True}
    items = [
        _passing_item("moving", 0.6, 3.0, 2.0),
        _passing_item("moving", -1.8, 3.0, 2.0),
        _passing_item("moving", 1.5, 3.0, 2.0),
        _passing_item("moving", 0.6, 5.0, 2.0),
        _passing_item("moving", 0.6, 4.0, 2.0),
        _passing_item("moving", 0.6, 3.0, 0.5),
        _passing_item("moving", 0.6, 3.0, 0.8),
        _passing_item("moving", 0.6, 3.0, None),
        _passing_item("moving", 0.6, 3.0, -1.0),
        _passing_item("static", 0.6, 3.0, 2.0),
        _passing_item("moving", 0.6, 3.0, 2.0, moving=False),
        _passing_item("moving", 0.6, 3.0, 2.0, moving=None),
        _passing_item("moving", 0.6, 3.0, 2.0, coasting=True),
        _passing_item("moving", 0.6, 3.0, 2.0, ghost=True),
        _passing_item("moving", 0.6, 3.0, 2.0, receding=True),
        _passing_item("moving", 0.6, 3.0, 2.0, collision=True),
    ]
    return [bool(passing_close(it, cfg)) for it in items]


# ----------------------------------------------------------------------
# facade identity
# ----------------------------------------------------------------------


def test_text_methods_are_the_engine_mixin_methods() -> None:
    from engine.speech import text

    for name in TEXT_NAMES:
        assert inspect.getattr_static(collision.SpeechPolicy, name) is inspect.getattr_static(text.TextMixin, name), (
            name
        )
    for name in ("_n", "_join_clocks", "_plural", "_kind", "_words"):
        assert isinstance(inspect.getattr_static(text.TextMixin, name), staticmethod), name
    assert collision.SpeechPolicy._text is text.TextMixin._text
    assert collision.SpeechPolicy._entry is text.TextMixin._entry


def test_context_methods_are_the_engine_mixin_methods() -> None:
    from engine.speech import context

    for name in CONTEXT_NAMES:
        assert inspect.getattr_static(collision.SpeechPolicy, name) is inspect.getattr_static(
            context.ContextMixin, name
        ), name
    assert isinstance(inspect.getattr_static(context.ContextMixin, "_key"), staticmethod)
    assert isinstance(inspect.getattr_static(context.ContextMixin, "_mem"), property)
    assert collision.SpeechPolicy.observe_context is context.ContextMixin.observe_context


def test_walls_methods_and_free_names_are_the_engine_objects() -> None:
    from engine.speech import walls

    for name in WALLS_NAMES:
        assert inspect.getattr_static(collision.SpeechPolicy, name) is inspect.getattr_static(walls.WallsMixin, name), (
            name
        )
    assert collision._followed_wall is walls.followed_wall
    assert collision._passing_close is walls.passing_close
    assert collision._WallFollow is walls.WallFollow


def test_no_method_is_defined_in_two_mixins() -> None:
    from engine.speech import context, text, walls

    names = [
        {k for k in vars(m) if not k.startswith("__") and k not in ("_abc_impl",)}
        for m in (text.TextMixin, context.ContextMixin, walls.WallsMixin)
    ]
    assert not (names[0] & names[1]) and not (names[0] & names[2]) and not (names[1] & names[2])
    assert sorted(names[0]) == sorted(TEXT_NAMES)
    assert sorted(names[1]) == sorted(CONTEXT_NAMES)
    assert sorted(names[2]) == sorted(WALLS_NAMES)
    for m in (text.TextMixin, context.ContextMixin, walls.WallsMixin):
        assert "__init__" not in vars(m)


def test_mixins_leave_the_policy_state_to_init() -> None:
    from engine.speech import context, text, walls

    p = collision.SpeechPolicy.__new__(collision.SpeechPolicy)
    assert vars(p) == {}
    for m in (text.TextMixin, context.ContextMixin, walls.WallsMixin):
        assert not any(
            isinstance(v, (int, float, str, dict, list, set)) for k, v in vars(m).items() if not k.startswith("__")
        )


# ----------------------------------------------------------------------
# behaviour (literals printed by the legacy code)
# ----------------------------------------------------------------------


def test_text_kind_and_steps_on_stub_items() -> None:
    assert _text_rows() == EXPECTED_TEXT


def test_entry_on_stub_items() -> None:
    assert _entry_rows() == EXPECTED_ENTRY


def test_text_helpers() -> None:
    assert _misc_rows() == EXPECTED_MISC


def test_known_walls_and_context_memory() -> None:
    assert _walls_policy_rows() == EXPECTED_POLICY


def test_followed_wall_sequences() -> None:
    from engine.speech.walls import followed_wall

    assert _followed_rows(followed_wall) == EXPECTED_FOLLOWED


def test_wall_follow_sequences() -> None:
    from engine.speech.walls import WallFollow

    assert _walk_rows(WallFollow) == EXPECTED_WALK


def test_wall_follow_attributes() -> None:
    from engine.speech.walls import WallFollow

    wf = WallFollow(_cfg()["beeps"]["follow"] | {"enabled": True})
    assert sorted(vars(wf)) == EXPECTED_WF_ATTRS


def test_passing_close_table() -> None:
    from engine.speech.walls import passing_close

    assert _passing_rows(passing_close) == EXPECTED_PASSING


def test_observe_writes_followed() -> None:
    from engine.speech.walls import WallFollow

    wf = WallFollow(_cfg()["beeps"]["follow"] | {"enabled": True})
    it = _follow_item(1, 3.0)
    wf.observe(10.0, [it])
    assert it.followed is False  # an unknown track has no history to decide on


EXPECTED_TEXT: Any = [
    ["6", "danger", "pole at 12 in 6", "pole approaching at 12 in 6", "pole at 12 in 6"],
    ["1 step", "danger", "curb at 12 in 1 step", "curb approaching at 12 in 1 step", "curb at 12 in 1 step"],
    ["1 step", "danger", "person at 1 in 1 step", "person approaching at 1 in 1 step", "person at 1 in 1 step"],
    [None, "danger", "pole at 12", "pole approaching at 12", "pole at 12"],
    [None, "danger", "pole at 11:45", "pole approaching at 11:45", "pole at 11:45"],
    ["4", "approach", "person at 12:30 in 4", "person approaching at 12:30 in 4", "person at 12:30 in 4"],
    ["9", "approach", "vehicle at 11 in 9", "vehicle approaching at 11", "vehicle at 11 in 9"],
    ["5", "approach", "vehicle at 12:45 in 5", "vehicle approaching at 12:45 in 5", "vehicle at 12:45 in 5"],
    ["5", "approach", "vehicle at 12:30 in 5", "vehicle approaching from right at 12:30 in 5", "vehicle at 12:30 in 5"],
    ["7", "receding", "person at 12:15 in 7", "person approaching at 12:15 in 7", "person at 12:15 in 7"],
    ["3", "standing", "person at 12 in 3", "person approaching at 12 in 3", "person at 12 in 3"],
    ["3", "stopped", "rider at 12 in 3", "rider approaching at 12 in 3", "rider at 12 in 3"],
    ["5", "danger", "person at 12 in 5", "person approaching at 12 in 5", "person at 12 in 5"],
    ["8", "danger", "pole at 11:30 in 8", "pole approaching at 11:30 in 8", "pole at 11:30 in 8"],
    ["6", "approach", "car at 12:30 in 6", "car approaching at 12:30", "car at 12:30 in 6"],
]
EXPECTED_ENTRY: Any = [
    "pole at 12 in 6",
    "pole at 11:30 and 12 in 6",
    "curb at 11:30 and 12 in 1 step",
    "pole at 12 in 6",
    "poles at 11:30 and 12 in 6",
    "person approaching at 12:30 in 4",
    "vehicle approaching at 11",
    "vehicle approaching from right at 12:30 in 5",
    "person approaching at 12:30 and 12:45 in 4",
    "person moving away at 12:15 in 7",
    "person standing at 12 in 3",
    "person standing at 12 and 1 in 1 step",
    "rider stopped at 12 in 3",
    "pole at 12",
]
EXPECTED_MISC: Any = [
    [1, 1, 1, 2, 2, 8],
    "12",
    "12:30 and 1",
    "11, 12:30 and 1",
    ["poles", "poles"],
    [8, 0],
    "road",
    "pole at 12",
    "pole at 12 in 3",
    ["approach", "receding", "standing", "stopped"],
]
EXPECTED_POLICY: Any = [
    False,
    1,
    True,
    True,
    False,
    1,
    1,
    [("curb", 20.0), ("pole", 40.0)],
    [],
    [{}, {}, True, False, True, 7.0],
    {"pole": 3.0},
    ["pole", "vehicle"],
    [True, False, False],
    False,
    ("road", "road"),
    None,
    None,
]
EXPECTED_FOLLOWED: Any = [
    False,
    False,
    True,
    True,
    False,
    [(("building", "right"), 16.5, 16.5, 0.5)],
    False,
    False,
    False,
    False,
    False,
    False,
    False,
]
EXPECTED_WALK: Any = [
    [False, False, False, True, True, True, True, True, True, True, True, True],
    [False, False, False, False, False, False, False, False, False, False, False, False],
    [False, False, False, True, True, True, True, True, True, True, True, True],
    [False, False, False, False, False, False, False, False, False, False, False, False],
    [False, False, False, False, False, False, False, False, False, False, False, False],
    [False, False, False, False, False, False, False, False, False, False, False, False],
    [False, False, False, True, True, True, True, True, False, False, False],
    [False, False, False, False, False, False, False, False, False, False, False, False],
    False,
    True,
    True,
    False,
    False,
    False,
    False,
    [True, False, True, False],
    [[True, False, True, False], [("building", 4.2)], [("building", 1.5)]],
]
EXPECTED_WF_ATTRS: Any = [
    "beside_s",
    "cand_last",
    "classes",
    "first",
    "gap",
    "hist",
    "jump",
    "last_followed",
    "last_real",
    "min_ratio",
    "min_span",
    "min_walk",
    "near_steps",
    "on",
    "prev_end",
    "recent_s",
    "run_gap",
    "walked",
    "window",
]
EXPECTED_PASSING: Any = [
    True,
    False,
    True,
    False,
    True,
    False,
    True,
    False,
    False,
    False,
    False,
    False,
    False,
    False,
    False,
    False,
]
