"""v26.1.10: quarter clock positions, lens projection and the depth distance sources (synthetic scenes)."""

from __future__ import annotations

import copy
import dataclasses
import math

import numpy as np
import pytest

import collision as col
from tests.test_collision import (CONFIG, FPS, HFOV, NAMES, SETTINGS, W, H, _item, _set_clock, approach_frames, base_grid,
                            hz, motion, place, run, speech)

DH, DW = 68, 120


def with_source(source: str, **kw):
    return dataclasses.replace(SETTINGS, distance_source=source, **kw)


def depth_doc(n: int, value, fps: float = FPS) -> dict:
    """One depth map per frame; ``value`` = a float, an (n,) array of per-frame metres or a callable(i) -> (DH, DW) map."""
    maps = np.empty((n, DH, DW), dtype=np.float32)
    for i in range(n):
        v = value(i) if callable(value) else (value[i] if hasattr(value, "__len__") else value)
        maps[i] = v
    return {"t": np.arange(n) / fps, "depth": maps}


def static_scene(cls: str, d: float, n: int = 30, w: float = 0.6, h: float = 3.0) -> list[np.ndarray]:
    g = base_grid()
    place(g, cls, d, 0.0, w, h)
    return [g.copy() for _ in range(n)]


def last(doc, cls="pole"):
    return hz(doc, cls)[-1][1]


def strip(doc: dict) -> dict:
    """Hazards document without the new reporting keys (depthM, distanceSource)."""
    d = copy.deepcopy(doc)
    d.pop("distanceSource", None)
    for f in d["frames"]:
        f.pop("corridor", None)               # v26.2.1: the map's nearest object in the corridor is placed with the depth when there is one
        f.pop("faceEdgeLines", None)          # v26.2.2: the face / edge test reads the map, which is placed with the depth
        f["ego"].pop("depthAnchor", None)
        f["ego"].pop("depthAnchorMode", None)
        for k in ("depthPitchDeg", "depthCameraHeightUnits", "depthGaitCheck"):
            f["ego"].pop(k, None)
        f["ego"].pop("depthLevel", None)
        f["ego"].pop("depthLevelSource", None)
        f["ego"].pop("depthScale", None)
        f["ego"].pop("depthScaleSource", None)
        for h in f["hazards"]:
            h.pop("depthM", None)
            for k in ("faceEdge", "insideSolid", "solidCorrected", "rawDistanceM"):      # v26.2.2: map diagnostics, depth-dependent numbers
                h.pop(k, None)
    return d


# --------------------------------------------------------------------------
# Quarter clock
# --------------------------------------------------------------------------

@pytest.mark.parametrize("q, text", [(0, "12"), (1, "12:15"), (-1, "11:45"), (2, "12:30"), (-2, "11:30"), (3, "12:45"),
                                     (4, "1"), (5, "1:15"), (6, "1:30"), (8, "2"), (-4, "11"), (-8, "10"),
                                     (-12, "9"), (12, "3"), (-9, "9:45"), (11, "2:45")])
def test_clock_text_table(q, text):
    assert col.clock_text(q) == text


def test_clock_quarter_rounds_and_clamps():
    assert [col.clock_quarter(b) for b in (0, 3.7, 3.8, 7.5, 8, 11.2, 11.3, 15, 22.5, 90, 120, 300)] == \
        [0, 0, 1, 1, 1, 1, 2, 2, 3, 12, 12, 12]
    assert [col.clock_quarter(b) for b in (-3.7, -3.8, -8, -22.5, -90, -120)] == [0, -1, -1, -3, -12, -12]
    assert col.clock_quarter(3.75) == 1 and col.clock_quarter(-3.75) == -1      # half away from zero, both sides


def test_item_carries_whole_hour_and_quarter_clock():
    it = _item(1, "danger", 6, "pole", clock=1)
    assert (it.clock, it.clock_q, it.clock_text) == (1, 4, "1")
    assert (_item(1, "danger", 6, "pole", clock=11).clock_q, _item(1, "danger", 6, "pole", clock=9).clock_text) == (-4, "9")


def test_detected_items_have_quarter_clock_and_hazards_report_it():
    doc, ev = run(approach_frames(lat=1.0, seconds=6), mot=motion(6))
    for _, h in hz(doc, "pole"):
        assert h["clockText"] == col.clock_text(col.clock_quarter(h["bearingDeg"]))
        assert h["clock"] == col.clock_from_bearing(h["bearingDeg"])
    for e in speech(ev):
        if e["trackId"] is not None:
            assert e["clockText"] and f" at {e['clockText']}" in e["text"] or e["role"] == "surface", e


def test_phrase_says_quarter_text_for_a_small_bearing():
    p = col.SpeechPolicy(CONFIG)
    it = _item(1, "danger", 6, "obstacle")
    it.clock_q, it.clock_text = col.clock_quarter(8.0), col.clock_text(col.clock_quarter(8.0))
    assert it.clock_text == "12:15"
    assert p._text("danger", it) == "obstacle at 12:15 in 6"
    assert p._text("final", it).startswith("obstacle at 12:15")


def test_grouped_clocks_are_distinct_and_ordered_left_to_right():
    p = col.SpeechPolicy(CONFIG)
    a, b, c, d = (_item(i, "danger", 6 + i, "pole") for i in range(1, 5))
    for it, q in ((a, 4), (b, -1), (c, 1), (d, 4)):
        it.clock_q, it.clock_text = q, col.clock_text(q)
    assert p._entry("thin", [a, b, c, d]) == "poles at 11:45, 12:15 and 1 in 7"
    assert p._entry("danger", [c, b]) == "pole at 11:45 and 12:15 in 8"
    left, right = _item(5, "danger", 6, "person", group="moving"), _item(6, "danger", 9, "person", group="moving")
    left.clock_q = right.clock_q = -9
    _set_clock(left, 10), _set_clock(right, 3)
    assert p._entry("danger", [right, left]) == "person at 10 and 3 in 6"


def test_beeps_episode_text_and_events_carry_clock_text():
    doc, ev = run(approach_frames(seconds=18), mot=motion(18))
    beeps = [e for e in ev["events"] if e["type"] == "beeps"]
    assert beeps
    for b in beeps:
        assert b["clockText"] and f" at {b['clockText']} " in b["text"]


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------

def test_resolve_projection_auto_by_hfov():
    assert col.resolve_projection(None, 118) == "fisheye" and col.resolve_projection("auto", 100) == "fisheye"
    assert col.resolve_projection(None, 99.9) == "rectilinear" and col.resolve_projection("auto", 70) == "rectilinear"
    assert col.resolve_projection("rectilinear", 118) == "rectilinear" and col.resolve_projection("fisheye", 60) == "fisheye"


def test_resolve_settings_stores_projection_and_distance_source():
    s = col.resolve_settings(CONFIG)
    assert (s.projection, s.distance_source) == ("fisheye", "ground")
    s = col.resolve_settings(CONFIG, "chest", 90, None, None, "fisheye", "depth")
    assert (s.projection, s.distance_source) == ("fisheye", "depth")
    assert col.resolve_settings(CONFIG, distance_source="fused").distance_source == "ground"   # dropped in v26.1.10
    assert col.resolve_settings(CONFIG, hfov_deg=90).projection == "rectilinear"
    assert col.resolve_settings(CONFIG, distance_source="bogus").distance_source == "ground"


def test_fisheye_vs_rectilinear_bearing_at_x_075():
    assert col.bearing_deg(0.75, 118, "fisheye") == pytest.approx(29.5)
    assert col.bearing_deg(0.75, 118, "rectilinear") == pytest.approx(math.degrees(math.atan(0.5 * math.tan(math.radians(59)))))
    assert col.bearing_deg(0.75, 118) == col.bearing_deg(0.75, 118, "rectilinear")
    assert col.bearing_deg(0.25, 118, "fisheye") == pytest.approx(-29.5) and col.bearing_deg(0.5, 118, "fisheye") == 0.0
    assert col.bearing_deg(0.75, 118, "rectilinear") - col.bearing_deg(0.75, 118, "fisheye") > 9


def test_projection_changes_bearing_clock_and_pan_but_not_geometry():
    frames = approach_frames(lat=2.0, d0=14.0, seconds=4, half_w=3.0)
    docs = {p: run(frames, settings=dataclasses.replace(SETTINGS, projection=p))[0] for p in ("fisheye", "rectilinear")}
    assert docs["fisheye"]["projection"] == "fisheye" and docs["rectilinear"]["projection"] == "rectilinear"
    a, b = hz(docs["fisheye"], "pole"), hz(docs["rectilinear"], "pole")
    assert a and len(a) == len(b)
    for (_, x), (_, y) in zip(a, b):
        assert (x["distanceM"], x["lateralM"], x["stepsTo"], x["role"]) == (y["distanceM"], y["lateralM"], y["stepsTo"], y["role"])
        assert x["bearingDeg"] < y["bearingDeg"] and x["pan"] < y["pan"]


# --------------------------------------------------------------------------
# Depth distance sources
# --------------------------------------------------------------------------

def test_depth_mode_uses_metric_depth_without_gait_scale_and_steps_from_it():
    frames = approach_frames(seconds=12)
    true = np.array([22.0 - 1.4 * i / FPS for i in range(len(frames))])
    depth = depth_doc(len(frames), true * 1.5)                    # deliberately not the ground distance
    doc, _ = col.run_collision(np.stack(frames), np.arange(len(frames)) / FPS, NAMES, CONFIG, with_source("depth"), motion(12), depth)
    assert doc["distanceSource"] == "depth"
    step = doc["frames"][0]["ego"]["stepLengthM"]
    for (t, h) in hz(doc, "pole")[5:]:
        i = int(round(t * FPS))
        assert h["depthM"] == pytest.approx(true[i] * 1.5, abs=0.01)
        assert h["distanceM"] == pytest.approx(h["depthM"], abs=0.01)
        assert h["stepsTo"] == pytest.approx(h["depthM"] / step, abs=0.06)
    assert last(doc)["closingMps"] == pytest.approx(1.4 * 1.5, abs=0.25)      # slope of the depth history


def test_depth_is_median_over_the_lowest_rows_of_the_item():
    frames = static_scene("pole", 10.0, n=8)
    split_row = 33                                                # depth rows >= 33 (grid rows >= ~66) are near
    def dm(i):
        m = np.full((DH, DW), 50.0, dtype=np.float32)
        m[split_row:] = 5.0
        return m
    doc, _ = col.run_collision(np.stack(frames), np.arange(8) / FPS, NAMES, CONFIG, SETTINGS, None, depth_doc(8, dm))
    assert last(doc)["depthM"] == 5.0


def test_depth_without_valid_pixels_reports_null_and_falls_back_to_ground():
    frames = static_scene("pole", 10.0, n=8)
    nan = depth_doc(8, np.nan)
    ground, _ = col.run_collision(np.stack(frames), np.arange(8) / FPS, NAMES, CONFIG, SETTINGS, None, None)
    doc, _ = col.run_collision(np.stack(frames), np.arange(8) / FPS, NAMES, CONFIG, with_source("depth"), None, nan)
    h = last(doc)
    assert "depthM" in h and h["depthM"] is None
    assert h["distanceM"] == last(ground)["distanceM"]


def test_depth_maps_are_matched_by_nearest_time():
    frames = static_scene("pole", 10.0, n=4)
    d = depth_doc(4, np.array([6.0, 7.0, 8.0, 9.0]))
    d["t"] = d["t"] + 0.02                                        # offset below half a frame: same pairing
    doc, _ = col.run_collision(np.stack(frames), np.arange(4) / FPS, NAMES, CONFIG, SETTINGS, None, d)
    assert [h["depthM"] for _, h in hz(doc, "pole")] == [6.0, 7.0, 8.0, 9.0]


def test_depth_lateral_follows_the_depth_distance():
    g = base_grid(half_w_m=3.0)
    place(g, "pole", 8.0, 1.0, 0.6, 3.0)
    frames = [g.copy() for _ in range(10)]
    args = (np.stack(frames), np.arange(10) / FPS, NAMES, CONFIG)
    gd, _ = col.run_collision(*args, SETTINGS, None, depth_doc(10, 20.0))
    dd, _ = col.run_collision(*args, with_source("depth"), None, depth_doc(10, 20.0))
    a, b = last(gd), last(dd)
    assert b["distanceM"] == 20.0 and b["lateralM"] == pytest.approx(a["lateralM"] * 20.0 / a["distanceM"], rel=0.02)
    assert b["bearingDeg"] == a["bearingDeg"]


def test_ground_mode_with_depth_is_identical_to_without_apart_from_depth_m():
    frames = approach_frames(seconds=16)
    mot = motion(16)
    times = np.arange(len(frames)) / FPS
    depth = depth_doc(len(frames), lambda i: 3.0 + 0.1 * i)
    a_doc, a_ev = col.run_collision(np.stack(frames), times, NAMES, CONFIG, SETTINGS, mot, None)
    b_doc, b_ev = col.run_collision(np.stack(frames), times, NAMES, CONFIG, SETTINGS, mot, depth)
    assert a_ev == b_ev
    assert all("depthM" not in h for f in a_doc["frames"] for h in f["hazards"])
    assert all("depthM" in h for f in b_doc["frames"] for h in f["hazards"])
    assert strip(a_doc) == strip(b_doc)


def test_without_depth_data_depth_source_behaves_as_ground():
    source = "depth"
    frames = approach_frames(seconds=16)
    mot = motion(16)
    ground = run(frames, mot=mot)
    other = run(frames, mot=mot, settings=with_source(source))
    assert other[1] == ground[1]
    assert other[0]["distanceSource"] == source and ground[0]["distanceSource"] == "ground"
    assert strip(other[0]) == strip(ground[0])


def test_metric_units_are_the_default_and_explicit_metric_is_identical():
    frames = approach_frames(seconds=8)
    times = np.arange(len(frames)) / FPS
    d = depth_doc(len(frames), 12.0)
    a, ea = col.run_collision(np.stack(frames), times, NAMES, CONFIG, with_source("depth"), motion(8), d)
    b, eb = col.run_collision(np.stack(frames), times, NAMES, CONFIG, with_source("depth"), motion(8), {**d, "units": "metric"})
    assert a == b and ea == eb
    assert all(f["ego"]["depthScaleSource"] == "metric" and f["ego"]["depthScale"] == 1.0 for f in a["frames"])
    c, _ = run(frames, mot=motion(8))
    assert all(f["ego"]["depthScale"] is None and f["ego"]["depthScaleSource"] == "none" for f in c["frames"])
