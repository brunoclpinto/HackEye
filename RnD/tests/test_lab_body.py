"""Lab per-recording body settings: user height, camera location and side drive the camera geometry."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lab import analysis, recordings, server

REC = {"id": "rec1", "duration": 100.0, "width": 320, "height": 180, "fps": 10.0, "chapters": [], "name": "rec1"}
URL = "/api/recordings/rec1/settings"


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings, "get_recording", lambda i: REC if i == "rec1" else None)
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    return tmp_path


def test_defaults_and_round_trip(fake):
    c = TestClient(server.app)
    got = c.get(URL).json()
    assert (got["userHeightM"], got["cameraLocation"], got["cameraSide"]) == (None, None, "center")
    put = c.put(URL, json={"userHeightM": 1.78, "cameraLocation": "chest", "cameraSide": "right"})
    assert put.status_code == 200
    again = c.get(URL).json()
    assert (again["userHeightM"], again["cameraLocation"], again["cameraSide"]) == (1.78, "chest", "right")
    cleared = c.put(URL, json={}).json()
    assert (cleared["userHeightM"], cleared["cameraLocation"], cleared["cameraSide"]) == (None, None, "center")


@pytest.mark.parametrize("body", [{"userHeightM": 0.9}, {"userHeightM": 2.4}, {"userHeightM": "tall"},
                                  {"cameraLocation": "knee"}, {"cameraSide": "top"}])
def test_validation(fake, body):
    assert TestClient(server.app).put(URL, json=body).status_code == 422


def test_resolved_block_chest(fake):
    c = TestClient(server.app)
    r = c.put(URL, json={"userHeightM": 1.78, "cameraLocation": "chest"}).json()["resolved"]
    assert r["userHeightM"] == 1.78 and r["cameraLocation"] == "chest" and r["cameraSide"] == "center"
    assert r["cameraHeightM"] == pytest.approx(1.2816, abs=1e-3)
    assert r["stepLengthM"] == pytest.approx(0.7387, abs=1e-3)
    assert r["horizon"] == pytest.approx(0.45)
    assert r["lateralOffsetM"] == 0
    right = c.put(URL, json={"userHeightM": 1.78, "cameraLocation": "chest", "cameraSide": "right"}).json()["resolved"]
    assert right["lateralOffsetM"] == pytest.approx(0.15)


def test_overrides_win(fake):
    r = TestClient(server.app).put(URL, json={"userHeightM": 1.78, "cameraLocation": "chest",
                                              "cameraHeightM": 1.5, "stepLengthM": 0.6}).json()["resolved"]
    assert r["cameraHeightM"] == 1.5 and r["stepLengthM"] == 0.6


def test_legacy_mount_unchanged(fake):
    import collision
    config = collision.load_config()
    r = TestClient(server.app).get(URL).json()["resolved"]
    assert r["cameraLocation"] is None
    assert r["cameraHeightM"] == config["mountPresets"][config["defaultMount"]]["cameraHeightM"]


def test_collision_pass_receives_body_settings(fake, monkeypatch):
    import collision
    (fake / "runs" / "0123456789ab").mkdir(parents=True)
    d = fake / "runs" / "0123456789ab"
    (d / "run.json").write_text(json.dumps({"id": "0123456789ab", "request": {"recording": "rec1"},
                                            "status": "done", "classNames": ["a"]}))
    np.savez(d / "grids.npz", grids=np.zeros((3, 135, 240), np.uint8), t=np.arange(3.0), index=np.arange(3))
    recordings.save_settings("rec1", {**recordings.get_settings("rec1", "chest"), "userHeightM": 1.7,
                                      "cameraLocation": "eye", "cameraSide": "left"})
    seen = {}
    real = collision.resolve_settings

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(collision, "resolve_settings", spy)
    monkeypatch.setattr(collision, "run_collision", lambda *a, **k: ({"settings": {}}, {"events": []}))
    analysis.collision_pass("0123456789ab")
    assert (seen["user_height_m"], seen["camera_location"], seen["camera_side"]) == (1.7, "eye", "left")
