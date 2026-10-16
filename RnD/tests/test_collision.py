"""Synthetic-grid tests for collision.py (no model, no GPU)."""

from __future__ import annotations

import copy
import json
import math

import numpy as np
import pytest

import collision as col
from common_paths import find_common_dir

W, H = 240, 135
FPS = 10.0

_MAPPING = json.load(open(find_common_dir() / "config" / "safety_mapping_hackeye48.json"))
NAMES = [c["name"] for c in sorted(_MAPPING["classes"], key=lambda c: c["id"])]
ID = {n: i for i, n in enumerate(NAMES)}
BG = ID["flat sidewalk"]

CONFIG = col.load_config()
SETTINGS = col.resolve_settings(CONFIG, None, None, None)


def make_grid(*objs):
    """objs: (class name, x_center_px, width_px, bottom_row, height_rows)."""
    g = np.full((H, W), BG, dtype=np.uint8)
    for name, cx, w, bottom, h in objs:
        x0 = int(cx - w // 2)
        g[max(0, bottom - h):bottom, x0:x0 + w] = ID[name]
    return g


def run(frames, config=CONFIG, fps=FPS, settings=SETTINGS):
    grids = np.stack(frames)
    times = np.arange(len(frames)) / fps
    return col.run_collision(grids, times, NAMES, config, settings)


def hazards_of(doc):
    return [f["hazards"] for f in doc["frames"]]


def approach_frames(name="pole", cx=120, seconds=5.5, start_row=68, rows_per_s=11.5):
    """Obstacle whose bottom edge slides down the frame (we walk towards it)."""
    n = int(seconds * FPS)
    return [make_grid((name, cx, 8, min(H, int(start_row + rows_per_s * i / FPS)), 30)) for i in range(n)]


def no_cooldown(config):
    c = copy.deepcopy(config)
    c["speech"]["trackCooldownSeconds"] = 0.0
    c["speech"]["globalMinGapSeconds"] = 0.0
    return c


def no_ttc(config):
    c = copy.deepcopy(config)
    for g in c["urgency"].values():
        for rule in g.values():
            rule["ttc"] = None
    return c


# 1 ------------------------------------------------------------------------

def test_bearing_and_clock():
    assert col.bearing_deg(0.5, 118) == pytest.approx(0.0)
    assert col.bearing_deg(1.0, 118) == pytest.approx(59.0, abs=0.01)
    assert col.bearing_deg(0.0, 118) == pytest.approx(-59.0, abs=0.01)
    assert col.clock_from_bearing(0) == 12
    assert col.clock_from_bearing(col.bearing_deg(0.0, 118)) == 10
    assert col.clock_from_bearing(col.bearing_deg(1.0, 118)) == 2
    assert col.clock_from_bearing(-90) == 9
    assert col.clock_from_bearing(90) == 3
    assert col.clock_from_bearing(-150) == 9  # clamped
    assert col.clock_from_bearing(31) == 1
    assert col.clock_from_bearing(-31) == 11


# 2 ------------------------------------------------------------------------

def test_corridor_mask_shape():
    c = SETTINGS.corridor
    m = col.corridor_mask(W, H, c)
    assert m.shape == (H, W) and m.dtype == bool
    assert not m[:int(c.horizon * H) - 1].any()          # above horizon
    assert m[H - 1, W // 2] and not m[H - 1, 0]          # bottom centre in, corner out
    widths = m.sum(axis=1)
    assert widths[H - 1] > widths[int(0.6 * H)] > 0      # widens towards the bottom
    assert widths[H - 1] == pytest.approx(0.6 * W, abs=2)


def test_obstacle_outside_corridor_ignored():
    frames = [make_grid(("pole", 10, 8, 130, 40)) for _ in range(5)]
    hz, ev = run(frames)
    assert all(h == [] for h in hazards_of(hz))
    assert ev["events"] == []


def test_tiny_component_ignored():
    frames = [make_grid(("pole", 120, 2, 130, 3)) for _ in range(3)]
    hz, _ = run(frames)
    assert all(h == [] for h in hazards_of(hz))


# 3 ------------------------------------------------------------------------

def test_static_approach_escalates_with_one_speech_per_level():
    cfg = no_cooldown(CONFIG)
    hz, ev = run(approach_frames(), config=cfg)
    hs = [h[0] for h in hazards_of(hz) if h]
    prox = [h["proximity"] for h in hs]
    assert prox == sorted(prox) and prox[-1] > prox[0] + 0.5
    assert any(h["ttc"] is not None and h["ttc"] > 0 for h in hs)

    levels = [h["urgency"] for h in hs]
    order = [l for i, l in enumerate(levels) if i == 0 or l != levels[i - 1]]
    assert order == ["none", "caution", "warning", "imminent"]

    speech = [e for e in ev["events"] if e["type"] == "speech"]
    assert [e["urgency"] for e in speech] == ["caution", "warning", "imminent"]
    assert all(e["text"] == "pole, 12 o'clock" for e in speech)
    assert len({e["trackId"] for e in speech}) == 1


# 4 ------------------------------------------------------------------------

def test_moving_obstacle_cautions_earlier_than_static():
    row = 83  # proximity ~0.30: between moving (0.25) and static (0.35) caution
    pole, _ = run([make_grid(("pole", 120, 8, row, 30))] * 4)
    person, _ = run([make_grid(("person", 120, 8, row, 30))] * 4)
    hp, hm = hazards_of(pole)[-1][0], hazards_of(person)[-1][0]
    assert 0.25 <= hp["proximity"] < 0.35
    assert hp["urgency"] == "none" and hp["group"] == "static"
    assert hm["urgency"] == "caution" and hm["group"] == "moving"


# 5 ------------------------------------------------------------------------

def test_track_identity():
    frames = [make_grid(("pole", 100 + i // 2, 8, 90, 30), ("sign", 140, 8, 100, 30)) for i in range(10)]
    hz, _ = run(frames)
    ids_by_class = {}
    for h in sum(hazards_of(hz), []):
        ids_by_class.setdefault(h["className"], set()).add(h["trackId"])
    assert ids_by_class["pole"] != ids_by_class["sign"]
    assert len(ids_by_class["pole"]) == 1 and len(ids_by_class["sign"]) == 1
    assert min(ids_by_class["pole"] | ids_by_class["sign"]) == 1


def test_track_survives_short_gap_but_not_long():
    obj = make_grid(("pole", 120, 8, 100, 30))
    empty = make_grid()
    ids = lambda frames: {h["trackId"] for h in sum(hazards_of(run(frames)[0]), [])}
    assert len(ids([obj, obj, empty, empty, obj, obj])) == 1
    assert len(ids([obj] + [empty] * 15 + [obj])) == 2


# 6 ------------------------------------------------------------------------

def test_same_frame_escalation_only_most_urgent_speaks():
    both = make_grid(("pole", 105, 8, 108, 30), ("person", 135, 8, 110, 30))
    hz, ev = run([make_grid()] * 2 + [both] * 3)
    speech = [e for e in ev["events"] if e["type"] == "speech"]
    assert len(speech) == 1
    h = {x["className"]: x for x in hazards_of(hz)[2]}
    assert h["person"]["proximity"] > h["pole"]["proximity"]
    assert h["person"]["urgency"] == h["pole"]["urgency"] == "warning"
    assert speech[0]["trackId"] == h["person"]["trackId"]  # tie -> higher proximity


def test_track_cooldown_suppresses_but_imminent_overrides():
    cfg = no_ttc(CONFIG)
    rows = {"caution": 90, "warning": 108, "imminent": 128}
    frames = [make_grid(("pole", 120, 8, r, 30)) for r in rows.values() for _ in range(5)]
    hz, ev = run(frames, config=cfg, fps=5.0)  # 3 s total < 4 s cooldown
    speech = [e for e in ev["events"] if e["type"] == "speech"]
    assert [e["urgency"] for e in speech] == ["caution", "imminent"]


def test_global_gap_drops_second_speaker():
    cfg = no_ttc(CONFIG)
    a = make_grid(("pole", 105, 8, 90, 30))
    b = make_grid(("pole", 105, 8, 90, 30), ("person", 140, 8, 90, 30))
    # second hazard appears 0.2 s after the first spoke: inside the 1.2 s gap
    hz, ev = run([a, a, b, b, b, b], config=cfg)
    speech = [e for e in ev["events"] if e["type"] == "speech"]
    assert len(speech) == 1


# 7 ------------------------------------------------------------------------

def test_tones_warning_spacing_and_pan():
    hz, ev = run(approach_frames(cx=135))
    tones = [e for e in ev["events"] if e["type"] == "tone"]
    assert tones and all(e["pan"] > 0 for e in tones)
    warn = [e["t"] for e in tones if e["urgency"] == "warning"]
    assert len(warn) >= 3
    gaps = np.diff(warn)
    assert np.allclose(gaps, 0.5, atol=0.011)
    assert {e["frequencyHz"] for e in tones if e["urgency"] == "warning"} == {880}
    speech = [e for e in ev["events"] if e["type"] == "speech"]
    assert speech[0]["urgency"] == "caution" and speech[0]["pan"] > 0


def test_tones_left_pan_negative():
    _, ev = run(approach_frames(cx=90))
    tones = [e for e in ev["events"] if e["type"] == "tone"]
    assert tones and all(e["pan"] < 0 for e in tones)


def test_no_tones_without_hazard():
    _, ev = run([make_grid()] * 10)
    assert ev["events"] == []
    # present but far (proximity < caution): still silent
    _, ev = run([make_grid(("pole", 120, 8, 70, 10))] * 10)
    assert ev["events"] == []


def test_single_stream_beeps_stay_on_one_rate():
    """Two simultaneous hazards must not interleave into a double-rate stream."""
    f = make_grid(("pole", 105, 8, 108, 30), ("person", 135, 8, 108, 30))
    _, ev = run([f] * 20, config=no_ttc(CONFIG))
    t = [e["t"] for e in ev["events"] if e["type"] == "tone"]
    assert np.allclose(np.diff(t), 0.5, atol=0.011)


# 8 ------------------------------------------------------------------------

def test_output_shapes_and_json():
    hz, ev = run(approach_frames())
    json.dumps(hz)
    json.dumps(ev)
    assert {"version", "settings", "gridW", "gridH", "frames"} <= set(hz)
    assert hz["version"] == "v26.1.0" and hz["gridW"] == W and hz["gridH"] == H
    assert {"corridor", "hfovDeg", "mount"} <= set(hz["settings"])
    assert set(hz["settings"]["corridor"]) == {"horizon", "bottomY", "topWidth", "bottomWidth", "centerX"}
    frame = next(f for f in hz["frames"] if f["hazards"])
    assert {"index", "t", "hazards"} <= set(frame)
    assert set(frame["hazards"][0]) == {
        "trackId", "className", "group", "label", "bbox", "contactY", "proximity", "bearingDeg",
        "clock", "pan", "ttc", "urgency", "areaFrac"}
    assert ev["version"] == "v26.1.0"
    times = [e["t"] for e in ev["events"]]
    assert times == sorted(times)
    for e in ev["events"]:
        keys = {"t", "type", "trackId", "urgency", "pan"}
        keys |= {"text", "clock"} if e["type"] == "speech" else {"frequencyHz", "durationSeconds"}
        assert set(e) == keys


def test_resolve_settings_overrides():
    s = col.resolve_settings(CONFIG, "head", 90, None)
    assert s.corridor.horizon == 0.40 and s.hfov_deg == 90
    custom = {"horizon": 0.3, "bottomY": 0.9, "topWidth": 0.1, "bottomWidth": 0.5, "centerX": 0.4}
    assert col.resolve_settings(CONFIG, None, None, custom).corridor.center_x == 0.4


def test_unknown_class_skipped(capsys):
    names = [n for n in NAMES if n != "animal"]
    grids = np.full((2, H, W), BG, dtype=np.uint8)
    col.run_collision(grids, np.array([0.0, 0.1]), names, CONFIG, SETTINGS)
    assert "[collision]" in capsys.readouterr().err
