"""Lab sound profile (v26.1.16): GET / PUT / DELETE /api/sounds, stored in LAB_DIR/display/sounds.json (survives version wipes), and the
collision pass that reads it."""
import json

import pytest
from fastapi.testclient import TestClient

import collision as col
from lab import recordings, server, sounds, versioning

TONES = col.load_config()["tones"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    return TestClient(server.app), tmp_path / "display" / "sounds.json"


def _kind(doc, kind):
    return next(k for k in doc["kinds"] if k["kind"] == kind)


def test_defaults_come_from_the_config_and_no_file_is_written(client):
    c, path = client
    d = c.get("/api/sounds").json()
    assert [k["kind"] for k in d["kinds"]] == list(TONES["sounds"])
    left, cin = _kind(d, "collision-left"), _kind(d, "crosswalk-in")
    assert (left["pitchHz"], left["durationMs"], left["intervalS"]) == (660, 80, 0.5)
    assert cin["intervalS"] is None and cin["default"]["pitchHz"] == 330
    assert d["speechRate"] == 1.0 and d["ranges"]["pitchHz"] == [150, 2000] and d["updatedAt"] is None
    assert not path.exists()


def test_put_saves_only_the_overrides_and_get_returns_them(client):
    c, path = client
    body = {"kinds": {"collision-left": {"pitchHz": 700, "durationMs": 80, "intervalS": 0.5}, "proximity": {"intervalS": 2.0}}, "speechRate": 1.5}
    d = c.put("/api/sounds", json=body).json()
    assert _kind(d, "collision-left")["pitchHz"] == 700 and _kind(d, "proximity")["intervalS"] == 2.0 and d["speechRate"] == 1.5
    saved = json.loads(path.read_text())
    assert saved["kinds"] == {"collision-left": {"pitchHz": 700}, "proximity": {"intervalS": 2.0}}      # defaults are not stored
    assert saved["speechRate"] == 1.5 and saved["updatedAt"]
    assert c.get("/api/sounds").json()["speechRate"] == 1.5
    # the collision pass takes the overrides
    prof = sounds.profile()
    assert col.resolve_sounds(TONES, prof)["kinds"]["collision-left"]["pitchHz"] == 700


def test_values_are_clamped_and_bad_input_is_refused(client):
    c, path = client
    d = c.put("/api/sounds", json={"kinds": {"collision-center": {"pitchHz": 99999, "durationMs": 1, "intervalS": 99}}, "speechRate": 9}).json()
    k = _kind(d, "collision-center")
    assert (k["pitchHz"], k["durationMs"], k["intervalS"]) == (2000, 20, 5.0) and d["speechRate"] == 2.0
    assert c.put("/api/sounds", json={"kinds": {"nope": {"pitchHz": 500}}}).status_code == 422
    assert c.put("/api/sounds", json={"kinds": {"collision-left": {"pitchHz": "high"}}}).status_code == 422
    assert c.put("/api/sounds", json={"kinds": [1]}).status_code == 422
    assert c.put("/api/sounds", json={"speechRate": "fast"}).status_code == 422
    assert _kind(c.get("/api/sounds").json(), "collision-center")["pitchHz"] == 2000          # the refusals changed nothing


def test_the_unused_interval_of_crosswalk_in_is_ignored(client):
    c, path = client
    d = c.put("/api/sounds", json={"kinds": {"crosswalk-in": {"intervalS": 3.0, "pitchHz": 400}}}).json()
    assert _kind(d, "crosswalk-in")["intervalS"] is None and _kind(d, "crosswalk-in")["pitchHz"] == 400
    assert json.loads(path.read_text())["kinds"] == {"crosswalk-in": {"pitchHz": 400}}


def test_putting_the_defaults_or_deleting_removes_the_file(client):
    c, path = client
    c.put("/api/sounds", json={"speechRate": 1.25})
    assert path.exists()
    c.put("/api/sounds", json={"kinds": {}, "speechRate": 1.0})
    assert not path.exists()
    c.put("/api/sounds", json={"speechRate": 0.75})
    assert path.exists()
    d = c.delete("/api/sounds").json()
    assert not path.exists() and d["speechRate"] == 1.0


def test_the_profile_survives_a_version_wipe(client, tmp_path):
    c, path = client
    c.put("/api/sounds", json={"speechRate": 1.25})
    root = path.parent.parent
    (root / "runs" / "abc").mkdir(parents=True)
    (root / "runs" / "abc" / "run.json").write_text("{}")
    versioning.write_marker(root, "v26.1.15")
    vf = tmp_path / "VERSION"
    vf.write_text("v26.1.16\n")
    res = versioning.apply_version_policy(root, vf)
    assert res["wiped"] and not (root / "runs" / "abc").exists()
    assert path.exists() and json.loads(path.read_text())["speechRate"] == 1.25
