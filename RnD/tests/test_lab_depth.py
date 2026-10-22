"""Lab depth support: request/settings validation, /api/models, depth PNG endpoint, analysis loop."""
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from lab import analysis, recordings, server

REC = {"id": "rec1", "duration": 100.0, "width": 320, "height": 180, "fps": 10.0, "chapters": [], "name": "rec1"}
RUN = "0123456789ab"


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings, "get_recording", lambda i: REC if i == "rec1" else None)
    monkeypatch.setattr(analysis, "list_models", lambda: [{"path": "m.pt", "name": "m", "default": True}])
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    monkeypatch.setattr(server, "_depth_cache", server.OrderedDict())
    return tmp_path


def _req(**extra):
    return {"recording": "rec1", "start": 0, "end": 10, "fps": 6, "model": "m.pt", **extra}


# --- request ---------------------------------------------------------------------------------------

def test_depth_field_validation_and_storage(fake):
    plain = analysis._normalise_request(_req())
    assert "depth" not in plain
    assert analysis._normalise_request(_req(depth="none")) == plain
    assert analysis._normalise_request(_req(depth=None)) == plain
    for v in ("da3-small", "da3-base", "da2-metric-outdoor-small", "unidepth-v2-s"):
        assert analysis._normalise_request(_req(depth=v))["depth"] == v
    with pytest.raises(analysis.RunError, match="depth must be one of"):
        analysis._normalise_request(_req(depth="da3-metric-large"))   # removed from the Lab
    with pytest.raises(analysis.RunError, match="depth must be one of"):
        analysis._normalise_request(_req(depth="midas"))


def test_depth_changes_run_id_but_none_does_not(fake, tmp_path):
    (tmp_path / "m.pt").write_text("x")
    model = str(tmp_path / "m.pt")
    base = {**analysis._normalise_request(_req()), "model": model}
    with_depth = {**base, "depth": "da3-small"}
    assert analysis._run_id(base) != analysis._run_id(with_depth)
    assert analysis._normalise_request(_req(depth="none")) == analysis._normalise_request(_req())


def test_post_runs_422_on_bad_depth(fake):
    r = TestClient(server.app).post("/api/runs", json=_req(depth="nope"))
    assert r.status_code == 422


def test_models_endpoint_lists_depth_models(fake):
    r = TestClient(server.app).get("/api/models").json()
    assert r["depthModels"] == ["none", "da3-small", "da3-base", "da2-metric-outdoor-small", "unidepth-v2-s"]


# --- pinned default model --------------------------------------------------------------------------

def test_default_model_is_pinned_then_falls_back(tmp_path, monkeypatch):
    rel = tmp_path / "rel"
    rel.mkdir()
    for n in ("Yolo26m-sem-HackEye20261011-1280.pt", "Yolo26m-sem-HackEye20261012.pt", "other.pt"):
        (rel / n).write_text("x")
    monkeypatch.setattr(analysis, "MODEL_DIRS", [(rel, "*.pt")])
    defaults = [m["name"] for m in analysis.list_models() if m["default"]]
    assert defaults == ["Yolo26m-sem-HackEye20261011-1280.pt"]
    (rel / "Yolo26m-sem-HackEye20261011-1280.pt").unlink()
    defaults = [m["name"] for m in analysis.list_models() if m["default"]]
    assert defaults == ["Yolo26m-sem-HackEye20261012.pt"]


def test_default_model_env_override(tmp_path, monkeypatch):
    (tmp_path / "Yolo-HackEye20261011.pt").write_text("x")
    (tmp_path / "Yolo-HackEye20261012.pt").write_text("x")
    monkeypatch.setattr(analysis, "MODEL_DIRS", [(tmp_path, "*.pt")])
    monkeypatch.setattr(analysis, "DEFAULT_MODEL", "Yolo-HackEye20261011.pt")
    assert [m["name"] for m in analysis.list_models() if m["default"]] == ["Yolo-HackEye20261011.pt"]


# --- settings ---------------------------------------------------------------------------------------

def test_settings_defaults_validation_and_resolved(fake):
    c = TestClient(server.app)
    got = c.get("/api/recordings/rec1/settings").json()
    assert got["projection"] == "auto" and got["distanceSource"] == "depth"
    assert got["resolved"]["projection"] == "fisheye"        # default HFOV 118 -> fisheye
    put = c.put("/api/recordings/rec1/settings", json={"projection": "rectilinear", "distanceSource": "depth",
                                                       "hfovDeg": 90})
    assert put.status_code == 200
    body = put.json()
    assert (body["projection"], body["distanceSource"], body["resolved"]["projection"]) == ("rectilinear", "depth", "rectilinear")
    assert c.get("/api/recordings/rec1/settings").json()["distanceSource"] == "depth"
    assert c.put("/api/recordings/rec1/settings", json={"projection": "equirect"}).status_code == 422
    assert c.put("/api/recordings/rec1/settings", json={"distanceSource": "lidar"}).status_code == 422
    assert c.put("/api/recordings/rec1/settings", json={"distanceSource": "fused"}).status_code == 422   # dropped in v26.1.10
    # omitted keys fall back to the defaults
    again = c.put("/api/recordings/rec1/settings", json={}).json()
    assert (again["projection"], again["distanceSource"]) == ("auto", "depth")


# --- depth PNG --------------------------------------------------------------------------------------

def _make_run(tmp_path, depth=None):
    d = tmp_path / "runs" / RUN
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"id": RUN, "request": {"recording": "rec1"}, "status": "done"}))
    if depth is not None:
        np.savez(d / "depth.npz", depth=depth, t=np.arange(len(depth), dtype=np.float64))
    return d


def test_depth_png_404_without_depth_or_out_of_range(fake):
    _make_run(fake)
    c = TestClient(server.app)
    assert c.get(f"/api/runs/{RUN}/depth/0.png").status_code == 404
    assert c.get(f"/api/runs/{'f' * 12}/depth/0.png").status_code == 404


def _png_near_far_ok(r):
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)   # BGR
    assert img.shape == (68, 120, 3)
    near, far = img[10, 10], img[10, 100]
    assert near[2] > near[0] and far[0] > far[2]        # near reddish, far bluish


@pytest.mark.parametrize("scale", [1.0, 0.01])
def test_depth_png_relative_uses_per_frame_percentiles(fake, scale):
    """Relative maps are coloured by their own percentiles, so any overall scale looks the same."""
    depth = np.empty((1, 68, 120), np.float16)
    depth[0, :, :60], depth[0, :, 60:] = 2.0 * scale, 8.0 * scale
    d = _make_run(fake, depth)
    np.savez(d / "depth.npz", depth=depth, t=np.zeros(1), units=np.array("relative"))
    _png_near_far_ok(TestClient(server.app).get(f"/api/runs/{RUN}/depth/0.png"))


def test_depth_png_metric_npz_keeps_fixed_range(fake):
    depth = np.full((1, 68, 120), 0.5, np.float16)
    depth[0, :, 60:] = 30.0
    d = _make_run(fake, depth)
    np.savez(d / "depth.npz", depth=depth, t=np.zeros(1), units=np.array("metric"))
    _png_near_far_ok(TestClient(server.app).get(f"/api/runs/{RUN}/depth/0.png"))


def test_depth_png_200_near_is_warm(fake):
    depth = np.empty((2, 68, 120), np.float16)
    depth[0, :, :60], depth[0, :, 60:] = 0.5, 30.0     # left near, right far
    depth[1] = 5.0
    _make_run(fake, depth)   # no units field: an older run, metric
    c = TestClient(server.app)
    r = c.get(f"/api/runs/{RUN}/depth/0.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "max-age=86400"
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)   # BGR
    assert img.shape == (68, 120, 3)
    near, far = img[10, 10], img[10, 100]
    assert near[2] > near[0] and far[0] > far[2]        # near reddish, far bluish
    assert c.get(f"/api/runs/{RUN}/depth/2.png").status_code == 404
    assert c.get(f"/api/runs/{RUN}/depth/-1.png").status_code == 404


# --- analysis loop with a fake depth model -----------------------------------------------------------

class _FakeSeg:
    def predict_class_grid(self, img, w, h):
        return np.zeros((h, w), np.int64)


class _FakeDepth:
    def __init__(self, units="relative", value=7.0):
        self.calls, self.units, self.value = [], units, value

    def predict(self, rgb):
        self.calls.append(rgb.shape)
        out = np.full((28, 50), self.value, np.float32)
        out[0, 0] = np.nan                      # guarded: non-finite never reaches the npz as inf
        return out, self.units


class _FakeCache:
    def __init__(self, depth):
        self.model, self.class_names, self.depth_model = _FakeSeg(), ["a"], depth

    def get(self, path, device="gpu"):
        return self.model

    def get_depth(self, variant="da3-small", device="gpu"):
        self.variant = variant
        return self.depth_model


def _video(path, n=40):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 180))
    for i in range(n):
        w.write(np.full((180, 320, 3), i * 5, np.uint8))
    w.release()


@pytest.mark.parametrize("use_depth,variant,units,value,expect", [
    (True, "da3-small", "relative", 7.0, 7.0),
    (True, "unidepth-v2-s", "metric", 450.0, 200.0),      # metric depth is clipped to [0.1, 200] m
    (True, "da2-metric-outdoor-small", "metric", 12.5, 12.5),
    (False, None, None, None, None)])
def test_run_job_writes_aligned_depth_npz(fake, tmp_path, monkeypatch, use_depth, variant, units, value, expect):
    vid = tmp_path / "v.mp4"
    _video(vid)
    rec = {**REC, "chapters": [{"file": str(vid), "start": 0.0, "duration": 4.0, "frames": 40}]}
    monkeypatch.setattr(recordings, "get_recording", lambda i: rec)
    request = {"recording": "rec1", "start": 0.0, "end": 3.0, "model": "m.pt", "profile": "default", "fps": 5.0}
    if use_depth:
        request["depth"] = variant
    doc = {"id": RUN, "request": request, "status": "queued", "progress": 0.0}
    d = tmp_path / "runs" / RUN
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps(doc))
    analysis._active[RUN] = dict(doc)
    real_pass, passes = analysis.collision_pass, []
    monkeypatch.setattr(analysis, "collision_pass", lambda rid: passes.append(rid) or real_pass(rid))
    fd = _FakeDepth(units, value)
    _cache = _FakeCache(fd)
    analysis._run_job(RUN, _cache)
    done = analysis.get_run(RUN)
    with np.load(d / "grids.npz") as g:
        n = len(g["t"])
        times = g["t"]
    assert n == 15 and passes == [RUN]
    assert (d / "hazards.json").exists()      # the real collision pass accepted depth=... and the new settings
    if use_depth:
        with np.load(d / "depth.npz") as z:
            assert z["depth"].shape == (n, 68, 120) and z["depth"].dtype == np.float16
            assert np.array_equal(z["t"], times)
            assert str(z["units"]) == units
            assert str(z["anchor"]) == analysis.DEPTH_ANCHOR[variant]
            assert not np.isinf(z["depth"]).any() and (z["depth"][:, 30:, 30:].astype(np.float32) == expect).all()
        assert len(fd.calls) == n and fd.calls[0] == (180, 320, 3) and _cache.variant == variant
        assert done["depth"] == variant and done["depthUnits"] == units and done["depthMsPerFrame"] is not None
    else:
        assert not (d / "depth.npz").exists() and not fd.calls


# --- anchor mode per depth variant -------------------------------------------------------------------

def test_variant_anchor_table():
    assert analysis.DEPTH_ANCHOR == {"da3-small": "per-frame", "da3-base": "per-frame",
                                     "da2-metric-outdoor-small": "plane", "unidepth-v2-s": "none"}


@pytest.mark.parametrize("variant,units,npz_anchor,expect", [
    ("da2-metric-outdoor-small", "metric", None, "plane"),        # older run: from the request's variant
    ("da2-metric-outdoor-small", "metric", "initial", "plane"),   # superseded stored anchor: the variant table wins
    ("da2-metric-outdoor-small", "metric", "per-frame", "per-frame"),
    ("da3-small", "relative", None, "per-frame"),
    ("unidepth-v2-s", "metric", None, "none"),
    (None, "relative", None, "per-frame"),                        # no variant: default rule by units
    (None, "metric", None, "none"),
    ("da3-small", "relative", "initial", "initial")])             # the npz field wins
def test_collision_pass_passes_the_anchor_mode(fake, monkeypatch, variant, units, npz_anchor, expect):
    import collision
    d = _make_run(fake)
    req = {"recording": "rec1"}
    if variant:
        req["depth"] = variant
    (d / "run.json").write_text(json.dumps({"id": RUN, "request": req, "status": "done", "classNames": ["a"]}))
    np.savez(d / "grids.npz", grids=np.zeros((3, 135, 240), np.uint8), t=np.arange(3.0), index=np.arange(3))
    extra = {} if npz_anchor is None else {"anchor": np.array(npz_anchor)}
    np.savez(d / "depth.npz", depth=np.ones((3, 68, 120), np.float16), t=np.arange(3.0),
             units=np.array(units), **extra)
    seen = {}

    def fake_run(grids, times, names, config, settings, motion=None, depth=None, sounds=None):
        seen.update(depth=depth, source=settings.distance_source)
        return {"frames": []}, {"events": []}
    monkeypatch.setattr(collision, "run_collision", fake_run)
    analysis.collision_pass(RUN)
    assert seen["depth"]["anchor"] == expect and seen["source"] == "depth"    # default distance source is depth
