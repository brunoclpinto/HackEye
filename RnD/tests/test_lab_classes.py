"""Lab endpoints for client-side mask colouring: classes.png and /classes (view-only data)."""
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import segmentation
from lab import analysis, server

RUN = "0123456789ab"
_CLASSES = segmentation._load_mapping(segmentation._CONFIG_DIR / "safety_mapping_hackeye48.json")[0]
NAMES = [_CLASSES[i]["name"] for i in range(48)]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    monkeypatch.setattr(server, "_grid_cache", server.OrderedDict())
    d = tmp_path / "runs" / RUN
    d.mkdir(parents=True)
    grids = (np.arange(3 * 4 * 5, dtype=np.uint8) % 48).reshape(3, 4, 5)
    np.savez(d / "grids.npz", grids=grids, t=np.arange(3, dtype=np.float64), index=np.arange(3, dtype=np.int32))
    doc = {"id": RUN, "request": {"recording": "x"}, "status": "done", "classNames": NAMES}
    (d / "run.json").write_text(json.dumps(doc))
    return TestClient(server.app), d, grids


def test_classes_png_roundtrip(client):
    c, _, grids = client
    r = c.get(f"/api/runs/{RUN}/frames/1/classes.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "max-age=86400"
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_UNCHANGED)
    assert img.ndim == 2 and img.dtype == np.uint8
    assert np.array_equal(img, grids[1])


def test_classes_png_errors(client):
    c, d, _ = client
    assert c.get(f"/api/runs/{RUN}/frames/3/classes.png").status_code == 404
    assert c.get(f"/api/runs/{RUN}/frames/-1/classes.png").status_code == 404
    assert c.get("/api/runs/ffffffffffff/frames/0/classes.png").status_code == 404
    doc = json.loads((d / "run.json").read_text())
    doc["status"] = "running"
    (d / "run.json").write_text(json.dumps(doc))
    assert c.get(f"/api/runs/{RUN}/frames/0/classes.png").status_code == 409


def test_cache_follows_mtime(client):
    c, d, _ = client
    c.get(f"/api/runs/{RUN}/frames/0/classes.png")
    new = np.full((2, 4, 5), 7, np.uint8)
    np.savez(d / "grids.npz", grids=new, t=np.zeros(2), index=np.arange(2, dtype=np.int32))
    import os
    st = (d / "grids.npz").stat()
    os.utime(d / "grids.npz", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    r = c.get(f"/api/runs/{RUN}/frames/1/classes.png")
    assert cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_UNCHANGED).max() == 7
    assert c.get(f"/api/runs/{RUN}/frames/2/classes.png").status_code == 404


def test_classes_endpoint(client):
    c, d, _ = client
    j = c.get(f"/api/runs/{RUN}/classes").json()
    assert j["mapping"] == "safety_mapping_hackeye48.json"
    assert [x["id"] for x in j["classes"]] == list(range(48))
    assert [x["name"] for x in j["classes"]] == NAMES
    assert all(0 <= x["level"] <= 4 for x in j["classes"])
    assert [l["level"] for l in j["levels"]] == [0, 1, 2, 3, 4]
    assert j["levels"][3] == {"level": 3, "label": "danger", "color": [255, 0, 0], "opacity": 1.0}
    doc = json.loads((d / "run.json").read_text())
    doc["classNames"] = ["nope"]
    (d / "run.json").write_text(json.dumps(doc))
    assert c.get(f"/api/runs/{RUN}/classes").status_code == 404


MAP = "safety_mapping_hackeye48.json"


@pytest.fixture
def disp(tmp_path, monkeypatch):
    from lab import recordings
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    return TestClient(server.app), tmp_path / "display" / MAP


def test_display_defaults_and_unknown_mapping(disp):
    c, f = disp
    j = c.get(f"/api/display/{MAP}").json()
    assert j["saved"]["classes"] == {} and j["saved"]["levels"] == {}
    assert len(j["classes"]) == 48 and all(x["show"] for x in j["classes"])
    assert [l["opacity"] for l in j["levels"]] == [0.0, 1.0, 1.0, 1.0, 1.0]
    assert c.get("/api/display/safety_mapping_nope.json").status_code == 404
    assert c.get("/api/display/collision.json").status_code == 404
    assert not f.exists()


def test_display_save_prune_and_reset(disp):
    c, f = disp
    default_lv = c.get(f"/api/display/{MAP}").json()["classes"][0]["level"]
    other = 1 if default_lv != 1 else 2
    r = c.put(f"/api/display/{MAP}/classes", json={"classes": {"0": {"level": other, "show": False},
                                                              "1": {"level": c.get(f"/api/display/{MAP}").json()["classes"][1]["level"], "show": True}}})
    assert r.status_code == 200
    j = r.json()
    assert j["saved"]["classes"] == {"0": {"level": other, "show": False}}   # entry equal to defaults pruned
    assert j["classes"][0]["level"] == other and j["classes"][0]["show"] is False
    r = c.put(f"/api/display/{MAP}/levels", json={"levels": {"3": {"color": [1, 2, 3], "opacity": 0.5}, "1": {"opacity": 1}}})
    j = r.json()
    assert j["saved"]["levels"] == {"3": {"color": [1, 2, 3], "opacity": 0.5}}
    assert j["levels"][3]["color"] == [1, 2, 3] and j["levels"][3]["opacity"] == 0.5
    on_disk = json.loads(f.read_text())
    assert set(on_disk) == {"classes", "levels", "updatedAt"}
    assert c.delete(f"/api/display/{MAP}/classes").json()["saved"]["classes"] == {}
    assert json.loads(f.read_text())["levels"]            # other section kept
    c.delete(f"/api/display/{MAP}/levels")
    assert not f.exists()                                 # all defaults: no file


@pytest.mark.parametrize("section,body", [
    ("classes", {"classes": {"48": {"level": 1}}}),
    ("classes", {"classes": {"x": {"level": 1}}}),
    ("classes", {"classes": {"0": {"level": 9}}}),
    ("classes", {"classes": {"0": {"show": "no"}}}),
    ("classes", {"levels": {}}),
    ("levels", {"levels": {"7": {"opacity": 1}}}),
    ("levels", {"levels": {"1": {"color": [0, 0, 256]}}}),
    ("levels", {"levels": {"1": {"color": [0, 0]}}}),
    ("levels", {"levels": {"1": {"opacity": 1.5}}}),
    ("levels", {"levels": {"1": {"opacity": True}}}),
])
def test_display_validation(disp, section, body):
    c, f = disp
    assert c.put(f"/api/display/{MAP}/{section}", json=body).status_code == 422
    assert not f.exists()
    assert c.put(f"/api/display/{MAP}/other", json=body).status_code == 404
