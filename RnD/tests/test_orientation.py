"""Camera orientation (landscape / portrait) with camera-side windows (v26.1.15 follow-up).

The window rule (profiles.camera_window), the scaling of the window to the resolution, the full-frame grid
columns, the geometry of a windowed collision pass (true bearings, horizon, NO_DATA exclusion), the run request /
id / run.json fields and the byte-identity of the matched (landscape) path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import collision as col
import profiles
from lab import analysis, recordings, server
from tests.test_collision import CONFIG, FPS, H, NAMES, SETTINGS, W, base_grid, hz, place

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SRC_4K = (3840, 2160)
SRC_27K = (2704, 1520)


# --------------------------------------------------------------------------
# window rule, scaling
# --------------------------------------------------------------------------

@pytest.mark.parametrize("src, side, expect", [
    (SRC_4K, "left", (0, 0, 1215, 2160)),
    (SRC_4K, "center", (1312, 0, 1215, 2160)),
    (SRC_4K, "right", (2625, 0, 1215, 2160)),
    (SRC_27K, "left", (0, 0, 855, 1520)),
    (SRC_27K, "center", (924, 0, 855, 1520)),
    (SRC_27K, "right", (1849, 0, 855, 1520)),
])
def test_portrait_window_is_the_largest_9_16_window_placed_by_side(src, side, expect):
    win = profiles.camera_window(*src, "portrait", side)
    assert (win["x0"], win["y0"], win["w"], win["h"]) == expect
    assert win["h"] == src[1] and win["x0"] + win["w"] <= src[0]
    assert abs(win["w"] / win["h"] - 9 / 16) < 1e-3
    if side == "left":
        assert win["x0"] == 0
    if side == "right":
        assert win["x0"] + win["w"] == src[0]


@pytest.mark.parametrize("src", [SRC_4K, SRC_27K])
@pytest.mark.parametrize("side", ["left", "center", "right"])
def test_landscape_window_is_the_full_frame_whatever_the_side(src, side):
    win = profiles.camera_window(*src, "landscape", side)
    assert profiles.is_full_window(win, *src)


def test_window_numbers_at_736p_all_six_combinations():
    got = {}
    for name, src in (("4K", SRC_4K), ("2.7K", SRC_27K)):
        for orient in profiles.ORIENTATIONS:
            win = profiles.camera_window(*src, orient, "left")
            spec = profiles.window_spec(*src, 736, orient, "left")
            got[(name, orient)] = ((win["w"], win["h"]), (spec.dst_w, spec.dst_h))
    assert got[("4K", "landscape")] == ((3840, 2160), (1280, 736))
    assert got[("2.7K", "landscape")] == ((2704, 1520), (1280, 736))
    assert got[("4K", "portrait")] == ((1215, 2160), (736, 1280))
    assert got[("2.7K", "portrait")] == ((855, 1520), (736, 1280))


@pytest.mark.parametrize("src", [SRC_4K, SRC_27K])
def test_window_is_scaled_evenly_never_stretched_or_upscaled(src):
    for short in profiles.SHORT_SIDE_OPTIONS:
        spec = profiles.window_spec(*src, short, "portrait", "center")
        win = profiles.camera_window(*src, "portrait", "center")
        # content (before the stride padding) keeps the window's aspect, and is not larger than the window
        content = profiles.short_side_spec(win["w"], win["h"], short)
        assert (spec.dst_w, spec.dst_h) == (content.dst_w, content.dst_h)
        assert spec.dst_w == short and spec.dst_h <= win["h"] and spec.dst_w <= win["w"]
        assert abs(spec.dst_w / spec.dst_h - win["w"] / win["h"]) < 0.04   # the rest is stride padding only


def test_no_upscaling_error_for_a_window_too_small_for_the_resolution():
    with pytest.raises(ValueError, match="upscale"):
        profiles.window_spec(960, 540, 736, "portrait", "left")      # a 303x540 window cannot reach 736
    profiles.window_spec(960, 540, 544, "landscape", "left")


@pytest.mark.parametrize("side, c0", [("left", 0), ("center", 82), ("right", 164)])
def test_grid_columns_are_a_column_range_of_the_full_frame_grid(side, c0):
    for src in (SRC_4K, SRC_27K):
        win = profiles.camera_window(*src, "portrait", side)
        got_c0, cols = profiles.grid_columns(win, src[0], 240)
        assert cols == 76 and got_c0 == c0
        assert got_c0 + cols <= 240
    full = profiles.camera_window(*SRC_4K, "landscape", "left")
    assert profiles.grid_columns(full, SRC_4K[0], 240) == (0, 240)


# --------------------------------------------------------------------------
# collision geometry
# --------------------------------------------------------------------------

C0, COLS = 82, 76      # the centre window on the 240-column grid


def _masked(frames, c0, cols):
    out = []
    for g in frames:
        m = np.full_like(g, col.NO_DATA)
        m[:, c0:c0 + cols] = g[:, c0:c0 + cols]
        out.append(m)
    return out


def _run(frames, window=None):
    return col.run_collision(np.stack(frames), np.arange(len(frames)) / FPS, NAMES, CONFIG, SETTINGS, None, window=window)


def _scene(lat, d):
    base = base_grid()
    frames = []
    for _ in range(30):
        g = base.copy()
        place(g, "pole", d, lat, 0.6, 3.0)
        frames.append(g)
    return frames


def _win(c0, cols):
    return {"c0": c0, "cols": cols, "x0": 0, "y0": 0, "w": 1215, "h": 2160, "srcW": 3840, "srcH": 2160}


@pytest.mark.parametrize("c0, lat, d", [(0, -4.0, 4.0), (C0, -1.0, 8.0), (164, 4.0, 4.0)])
def test_true_bearings_in_a_window_equal_the_full_frame_bearings(c0, lat, d):
    frames = _scene(lat, d)
    full_doc, _ = _run(frames)
    win_doc, _ = _run(_masked(frames, c0, COLS), _win(c0, COLS))
    full, win = hz(full_doc, "pole"), hz(win_doc, "pole")
    assert full and win, "the pole is seen in both"
    f0, w0 = full[-1][1], win[-1][1]
    for key in ("bearingDeg", "clock", "clockText", "pan"):
        if key in f0:
            assert w0[key] == f0[key], key
    assert (w0["bbox"][0], w0["bbox"][2]) == (f0["bbox"][0], f0["bbox"][2])   # full-frame normalised x
    # a window treated as a whole frame (the naive crop) would report another direction
    crop = [g[:, c0:c0 + COLS] for g in frames]
    naive_doc, _ = col.run_collision(np.stack(crop), np.arange(len(crop)) / FPS, NAMES, CONFIG, SETTINGS, None)
    naive = hz(naive_doc, "pole")
    assert not naive or naive[-1][1].get("bearingDeg") != f0.get("bearingDeg")
    assert win_doc["window"]["c0"] == c0 and "window" not in full_doc
    assert win_doc["gridW"] == 240 and win_doc["gridH"] == H


def test_cells_outside_the_window_are_never_surface_or_item():
    frames = _scene(-1.0, 8.0)
    doc, _ = _run(_masked(frames, C0, COLS), _win(C0, COLS))
    lo, hi = C0 / W, (C0 + COLS) / W
    for f in doc["frames"]:
        for h in f["hazards"]:
            assert h["bbox"][0] >= lo - 1e-9 and h["bbox"][2] <= hi + 1e-9
        for row in (f.get("region") or {}).get("rows", []):
            assert row[1] >= lo - 1e-9 and row[2] <= hi + 1e-9


def test_window_edges_count_as_crops_for_the_horizon_fit():
    left = np.full(40, 0.30)
    right = np.full(40, 0.70)
    assert col.estimate_horizon(left, right, CONFIG) is None      # parallel edges
    # a path that fills a window: its bounds are the window edges, not path edges
    rows = np.arange(40)
    left = np.clip(0.4 - 0.004 * rows, 0.3, 1)        # converge upward but stay inside the window bounds
    right = np.clip(0.6 + 0.004 * rows, 0, 0.7)
    assert col.estimate_horizon(left, right, CONFIG, (0.3, 0.7)) is None


def test_horizon_unchanged_for_the_full_frame():
    frames = _scene(0.0, 10.0)
    a, _ = _run(frames)
    b, _ = _run(frames, None)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# --------------------------------------------------------------------------
# matched path: byte-identical
# --------------------------------------------------------------------------

GOLDEN_CHEST0004_REVIEW7 = "0dbb0163094a436c17ebc90ac2c47340a2f5e8baf383ca55d44815f305165fe8"   # v26.2.3 (objectDistance pinned to "depth" in tests/test_collision.CONFIG): re-pinned from e356b6ec... of v26.2.2 only for the version string and the two new settings keys objectDistance / useHorizon (tests/test_collision_v2623.py proves it: stripped, the hash is the v26.2.2 one). Older note, v26.2.2 (re-pinned from 0138457220cb... of v26.2.1: the version string, the new hazards keys faceEdge / faceEdgeLines / insideSolid / solidCorrected / rawDistanceM / coasting and the top-level coast, walls judged by the face / edge test (building 13.50 "at 11:45 in 8"), items inside solid snapped, movers that vanish coasting)
# older: collision output of v26.1.16 (re-pinned there: new sound kinds, rules 6-9; was dbf69f1a... on v26.1.15; re-pinned again by the lane-part follow-up: the 10.9 s building, was 83568a1d...)


def _fixture_output(window=None):
    meta = json.load(open(FIXTURES / "chest0004_review7.json"))
    s = meta["settings"]
    settings = col.resolve_settings(CONFIG, s["mount"], s["hfovDeg"], s["cameraHeightM"], s["stepLengthM"],
                                    projection=s.get("projection"), distance_source=s.get("distanceSource", "ground"),
                                    user_height_m=s.get("userHeightM"), camera_location=s.get("cameraLocation"),
                                    camera_side=s.get("cameraSide"))
    npz = np.load(FIXTURES / "chest0004_review7.npz")
    motion = {"t": npz["w0_mt"], "dx": npz["w0_mdx"], "dy": npz["w0_mdy"], "resid": npz["w0_mresid"]}
    dm = meta["depth"]
    depth = {"t": npz["w0_t"], "depth": npz["w0_depth"], "units": dm["units"], "anchor": dm["anchor"]}
    return col.run_collision(npz["w0_grids"], npz["w0_t"], meta["classNames"], CONFIG, settings, motion, depth,
                             window=window)


def test_matched_path_is_byte_identical_to_the_pre_orientation_output():
    doc, ev = _fixture_output()
    assert hashlib.sha256(json.dumps([doc, ev], sort_keys=True).encode()).hexdigest() == GOLDEN_CHEST0004_REVIEW7
    assert "window" not in doc


def test_a_landscape_run_has_no_window_and_its_request_and_id_do_not_change(tmp_path, monkeypatch):
    model = tmp_path / "m.pt"
    model.write_bytes(b"x")
    rec = {"id": "Chest-center-0004", "duration": 100.0, "width": 2704, "height": 1520, "fps": 24.0, "chapters": [], "name": "x"}
    monkeypatch.setattr(recordings, "get_recording", lambda i: rec)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "list_models", lambda: [{"path": str(model), "name": "m", "default": True}])
    base = {"recording": rec["id"], "start": 0, "end": 10, "fps": 6, "model": str(model), "profile": "736p", "depth": "da2-metric-outdoor-small"}
    land = analysis._normalise_request(base)
    assert land == {"recording": rec["id"], "start": 0.0, "end": 10.0, "model": str(model), "profile": "736p", "fps": 6.0,
                    "depth": "da2-metric-outdoor-small"}
    # an explicit landscape and any side give the same request, hence the same id
    for extra in ({"orientation": "landscape"}, {"orientation": "landscape", "side": "left"}, {"side": "right"}):
        assert analysis._normalise_request({**base, **extra}) == land
    # portrait: orientation and side are part of the request, so portrait runs of one range coexist
    ids = set()
    for side in ("left", "center", "right"):
        p = analysis._normalise_request({**base, "orientation": "portrait", "side": side})
        assert (p["orientation"], p["side"]) == ("portrait", side)
        ids.add(analysis._run_id(p))
    ids.add(analysis._run_id(land))
    assert len(ids) == 4


# --------------------------------------------------------------------------
# lab: settings, request validation, run.json
# --------------------------------------------------------------------------

REC = {"id": "Chest-center-0004", "duration": 100.0, "width": 3840, "height": 2160, "fps": 24.0, "chapters": [], "name": "x"}
URL = "/api/recordings/Chest-center-0004/settings"


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings, "get_recording", lambda i: REC if i == REC["id"] else None)
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    model = tmp_path / "m.pt"
    model.write_bytes(b"x")
    monkeypatch.setattr(analysis, "list_models", lambda: [{"path": str(model), "name": "m", "default": True}])
    monkeypatch.setattr(analysis, "_ensure_worker", lambda: None)
    return tmp_path, str(model)


def test_name_hints():
    assert recordings.name_hints("Chest-center-0004") == {"cameraLocation": "chest", "cameraSide": "center"}
    assert recordings.name_hints("Head-left-0001") == {"cameraLocation": "head", "cameraSide": "left"}
    assert recordings.name_hints("GoPro 4929") == {} and recordings.name_hints("4929") == {}


def test_settings_default_from_the_name_and_round_trip(fake):
    c = TestClient(server.app)
    got = c.get(URL).json()
    assert (got["cameraLocation"], got["cameraSide"], got["orientation"]) == ("chest", "center", "landscape")
    put = c.put(URL, json={"cameraSide": "left", "orientation": "portrait", "cameraLocation": "chest"}).json()
    assert (put["cameraSide"], put["orientation"]) == ("left", "portrait")
    assert c.get(URL).json()["orientation"] == "portrait"
    assert c.put(URL, json={"orientation": "diagonal"}).status_code == 422


def test_recordings_carry_portrait_sizes_and_name_hints():
    sizes = recordings._input_sizes(3840, 2160, "portrait")
    assert sizes["736p"] == [736, 1280] and sizes["544p"] == [544, 960]
    assert recordings._input_sizes(3840, 2160)["736p"] == [1280, 736]


def test_portrait_run_request_run_json_and_validation(fake):
    tmp, model = fake
    base = {"recording": REC["id"], "start": 0, "end": 10, "fps": 6, "model": model, "profile": "736p"}
    doc = analysis.submit_run({**base, "orientation": "portrait", "side": "left"})
    assert doc["request"]["orientation"] == "portrait" and doc["request"]["side"] == "left"
    assert (doc["orientation"], doc["side"]) == ("portrait", "left")
    assert doc["window"] == {"x0": 0, "y0": 0, "w": 1215, "h": 2160}
    analysis._active.clear()
    land = analysis.submit_run({**base, "side": "right"})
    assert land["orientation"] == "landscape" and land["side"] == "right" and "orientation" not in land["request"]
    assert land["window"] == {"x0": 0, "y0": 0, "w": 3840, "h": 2160}
    with pytest.raises(analysis.RunError, match="orientation"):
        analysis._normalise_request({**base, "orientation": "square"})
    with pytest.raises(analysis.RunError, match="side"):
        analysis._normalise_request({**base, "orientation": "portrait", "side": "top"})
