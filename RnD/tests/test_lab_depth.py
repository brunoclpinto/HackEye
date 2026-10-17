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
    assert analysis._normalise_request(_req(depth="da3-metric-large"))["depth"] == "da3-metric-large"
    with pytest.raises(analysis.RunError, match="depth must be one of"):
        analysis._normalise_request(_req(depth="midas"))


def test_depth_changes_run_id_but_none_does_not(fake, tmp_path):
    (tmp_path / "m.pt").write_text("x")
    model = str(tmp_path / "m.pt")
    base = {**analysis._normalise_request(_req()), "model": model}
    with_depth = {**base, "depth": "da3-metric-large"}
    assert analysis._run_id(base) != analysis._run_id(with_depth)
    assert analysis._normalise_request(_req(depth="none")) == analysis._normalise_request(_req())


def test_post_runs_422_on_bad_depth(fake):
    r = TestClient(server.app).post("/api/runs", json=_req(depth="nope"))
    assert r.status_code == 422


def test_models_endpoint_lists_depth_models(fake):
    r = TestClient(server.app).get("/api/models").json()
    assert r["depthModels"] == ["none", "da3-metric-large"]


# --- pinned default model --------------------------------------------------------------------------

def test_default_model_is_pinned_then_falls_back(tmp_path, monkeypatch):
    rel = tmp_path / "rel"
    rel.mkdir()
    for n in ("Yolo26m-sem-HackEye20261011.pt", "Yolo26m-sem-HackEye20261012.pt", "other.pt"):
        (rel / n).write_text("x")
    monkeypatch.setattr(analysis, "MODEL_DIRS", [(rel, "*.pt")])
    defaults = [m["name"] for m in analysis.list_models() if m["default"]]
    assert defaults == ["Yolo26m-sem-HackEye20261011.pt"]
    (rel / "Yolo26m-sem-HackEye20261011.pt").unlink()
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
    put = c.put("/api/recordings/rec1/settings", json={"projection": "rectilinear", "distanceSource": "ground",
                                                       "hfovDeg": 90})
    assert put.status_code == 200
    body = put.json()
    assert (body["projection"], body["distanceSource"], body["resolved"]["projection"]) == ("rectilinear", "ground", "rectilinear")
    assert c.get("/api/recordings/rec1/settings").json()["distanceSource"] == "ground"
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


def test_depth_png_200_near_is_warm(fake):
    depth = np.empty((2, 68, 120), np.float16)
    depth[0, :, :60], depth[0, :, 60:] = 0.5, 30.0     # left near, right far
    depth[1] = 5.0
    _make_run(fake, depth)
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
    def __init__(self):
        self.calls = []

    def predict_metric(self, rgb, focal_px):
        self.calls.append((rgb.shape, focal_px))
        return np.full((28, 50), 7.0, np.float32)


class _FakeCache:
    def __init__(self, depth):
        self.model, self.class_names, self.depth_model = _FakeSeg(), ["a"], depth

    def get(self, path):
        return self.model

    def get_depth(self):
        return self.depth_model


def _video(path, n=40):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 180))
    for i in range(n):
        w.write(np.full((180, 320, 3), i * 5, np.uint8))
    w.release()


@pytest.mark.parametrize("use_depth", [True, False])
def test_run_job_writes_aligned_depth_npz(fake, tmp_path, monkeypatch, use_depth):
    vid = tmp_path / "v.mp4"
    _video(vid)
    rec = {**REC, "chapters": [{"file": str(vid), "start": 0.0, "duration": 4.0, "frames": 40}]}
    monkeypatch.setattr(recordings, "get_recording", lambda i: rec)
    request = {"recording": "rec1", "start": 0.0, "end": 3.0, "model": "m.pt", "profile": "default", "fps": 5.0}
    if use_depth:
        request["depth"] = "da3-metric-large"
    doc = {"id": RUN, "request": request, "status": "queued", "progress": 0.0}
    d = tmp_path / "runs" / RUN
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps(doc))
    analysis._active[RUN] = dict(doc)
    real_pass, passes = analysis.collision_pass, []
    monkeypatch.setattr(analysis, "collision_pass", lambda rid: passes.append(rid) or real_pass(rid))
    fd = _FakeDepth()
    analysis._run_job(RUN, _FakeCache(fd))
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
            assert np.allclose(z["depth"].astype(np.float32), 7.0)
        assert len(fd.calls) == n and fd.calls[0][0] == (180, 320, 3) and fd.calls[0][1] > 0
        assert done["depth"] == "da3-metric-large" and done["depthMsPerFrame"] is not None
    else:
        assert not (d / "depth.npz").exists() and not fd.calls
