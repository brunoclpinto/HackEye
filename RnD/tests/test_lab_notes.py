"""Lab notes box (v26.2.4 follow-up): GET / PUT /api/notes, stored in LAB_DIR/notes.json (survives version wipes), carried by the reviews export."""
import json

import pytest
from fastapi.testclient import TestClient

from lab import notes, recordings, server, versioning


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    return TestClient(server.app), tmp_path


def test_empty_when_there_is_no_file(client):
    c, root = client
    assert c.get("/api/notes").json() == {"text": "", "updatedAt": None}
    assert not (root / "notes.json").exists()


def test_put_then_get_and_backup(client):
    c, root = client
    a = c.put("/api/notes", json={"text": "first", "baseUpdatedAt": None}).json()
    assert a["text"] == "first" and a["updatedAt"]
    assert c.get("/api/notes").json() == a
    assert not (root / "notes.prev.json").exists()
    b = c.put("/api/notes", json={"text": "second", "baseUpdatedAt": a["updatedAt"]}).json()
    assert b["updatedAt"] != a["updatedAt"]
    assert json.loads((root / "notes.prev.json").read_text())["text"] == "first"
    # an empty text is saved like any other
    e = c.put("/api/notes", json={"text": "", "baseUpdatedAt": b["updatedAt"]}).json()
    assert e["text"] == "" and json.loads((root / "notes.json").read_text())["text"] == ""


def test_stale_base_is_a_409_and_force_overwrites(client):
    c, root = client
    a = c.put("/api/notes", json={"text": "one", "baseUpdatedAt": None}).json()
    c.put("/api/notes", json={"text": "two", "baseUpdatedAt": a["updatedAt"]})
    r = c.put("/api/notes", json={"text": "stale", "baseUpdatedAt": a["updatedAt"]})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["message"] and d["current"]["text"] == "two"
    assert c.get("/api/notes").json()["text"] == "two"
    assert c.put("/api/notes", json={"text": "stale", "baseUpdatedAt": None}).status_code == 409
    f = c.put("/api/notes", json={"text": "forced", "baseUpdatedAt": a["updatedAt"], "force": True})
    assert f.status_code == 200 and c.get("/api/notes").json()["text"] == "forced"


def test_bad_text_is_a_422(client):
    c, _ = client
    assert c.put("/api/notes", json={"text": 5, "baseUpdatedAt": None}).status_code == 422
    assert c.put("/api/notes", json={"baseUpdatedAt": None}).status_code == 422
    assert c.put("/api/notes", json={"text": "x" * (notes.MAX_CHARS + 1), "baseUpdatedAt": None}).status_code == 422
    assert c.put("/api/notes", json={"text": "x" * notes.MAX_CHARS, "baseUpdatedAt": None}).status_code == 200


def test_export_carries_the_notes(client):
    c, _ = client
    assert c.get("/api/reviews/export").json()["notes"] == {"text": "", "updatedAt": None}
    a = c.put("/api/notes", json={"text": "fix the curb", "baseUpdatedAt": None}).json()
    assert c.get("/api/reviews/export").json()["notes"] == a


def test_notes_survive_a_version_wipe(client, tmp_path):
    c, root = client
    c.put("/api/notes", json={"text": "keep me", "baseUpdatedAt": None})
    (root / "runs" / "abc").mkdir(parents=True)
    (root / "runs" / "abc" / "run.json").write_text("{}")
    versioning.write_marker(root, "v26.2.3")
    vf = tmp_path / "VERSION"
    vf.write_text("v26.2.4\n")
    res = versioning.apply_version_policy(root, vf)
    assert res["wiped"] and not (root / "runs" / "abc").exists()
    assert c.get("/api/notes").json()["text"] == "keep me"
