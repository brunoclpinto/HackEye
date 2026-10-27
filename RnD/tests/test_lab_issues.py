"""Open-issues panel (v26.2.4 follow-up): GET /api/issues, PUT /api/issues/{id}; catalogue lab/issues.json + user state in LAB_DIR/issues-state.json."""
import json

import pytest
from fastapi.testclient import TestClient

from lab import issues, recordings, server, versioning

CAT = {
    "updatedAt": "2026-10-27",
    "groups": [{"id": "open", "title": "Open issues"}, {"id": "debt", "title": "Debt"}, {"id": "closed", "title": "Closed"}],
    "items": [
        {"id": "O1", "group": "open", "title": "one", "details": ["a `b`"]},
        {"id": "O2", "group": "open", "title": "two", "details": []},
        {"id": "D1", "group": "debt", "title": "debt one", "details": []},
        {"id": "C1", "group": "debt", "title": "old", "details": [], "status": "closed", "closedAt": "2026-10-26", "reason": "done"},
    ],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    cat = tmp_path / "cat.json"
    cat.write_text(json.dumps(CAT))
    monkeypatch.setattr(issues, "CATALOGUE", cat)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path / "lab")
    return TestClient(server.app), tmp_path / "lab"


def _ids(d, gid):
    return [i["id"] for g in d["groups"] if g["id"] == gid for i in g["items"]]


def test_list_groups_and_catalogue_closed_items(client):
    c, _ = client
    d = c.get("/api/issues").json()
    assert d["updatedAt"] == "2026-10-27" and [g["id"] for g in d["groups"]] == ["open", "debt", "closed"]
    assert _ids(d, "open") == ["O1", "O2"] and _ids(d, "debt") == ["D1"] and _ids(d, "closed") == ["C1"]
    assert [g["openCount"] for g in d["groups"]] == [2, 1, 0]
    c1 = d["groups"][2]["items"][0]
    assert c1["status"] == "closed" and c1["group"] == "debt" and c1["closedAt"] == "2026-10-26" and c1["reason"] == "done"
    assert not c1["userChanged"] and c1["note"] == ""


def test_close_reopen_and_note_round_trip(client):
    c, root = client
    r = c.put("/api/issues/O1", json={"status": "closed", "note": "fixed it"}).json()
    assert r["status"] == "closed" and r["closedAt"] and r["note"] == "fixed it" and r["noteUpdatedAt"] and r["userChanged"]
    d = c.get("/api/issues").json()
    assert _ids(d, "open") == ["O2"] and sorted(_ids(d, "closed")) == ["C1", "O1"]
    assert d["groups"][0]["openCount"] == 1
    assert json.loads((root / "issues-state.json").read_text())["O1"]["status"] == "closed"
    r = c.put("/api/issues/O1", json={"status": "open"}).json()
    assert r["status"] == "open" and r["closedAt"] is None and r["note"] == "fixed it"       # the note is kept
    assert "O1" in _ids(c.get("/api/issues").json(), "open")
    # the user can reopen a catalogue-closed item; it then sits in the first open group
    c.put("/api/issues/C1", json={"status": "open"})
    d = c.get("/api/issues").json()
    assert "C1" in _ids(d, "debt") and "C1" not in _ids(d, "closed")


def test_unknown_id_and_bad_values(client):
    c, _ = client
    assert c.put("/api/issues/NOPE", json={"note": "x"}).status_code == 404
    assert c.put("/api/issues/O1", json={"status": "done"}).status_code == 422
    assert c.put("/api/issues/O1", json={"note": 5}).status_code == 422
    assert c.put("/api/issues/O1", json={"note": "x" * 4001}).status_code == 422
    assert c.put("/api/issues/O1", json={"note": "x" * 4000}).status_code == 200


def test_export_has_only_touched_items(client):
    c, _ = client
    assert c.get("/api/reviews/export").json()["issues"] == []
    c.put("/api/issues/O2", json={"note": "please act"})
    c.put("/api/issues/D1", json={"status": "closed"})
    c.put("/api/issues/O1", json={"note": "   "})            # a blank note alone is not a change
    ex = c.get("/api/reviews/export").json()["issues"]
    assert sorted(i["id"] for i in ex) == ["D1", "O2"]
    o2 = next(i for i in ex if i["id"] == "O2")
    assert o2["title"] == "two" and o2["note"] == "please act" and o2["status"] == "open"


def test_state_survives_a_version_wipe(client, tmp_path):
    c, root = client
    c.put("/api/issues/O1", json={"status": "closed", "note": "keep"})
    (root / "runs" / "abc").mkdir(parents=True)
    (root / "runs" / "abc" / "run.json").write_text("{}")
    versioning.write_marker(root, "v26.2.3")
    vf = tmp_path / "VERSION"
    vf.write_text("v26.2.4\n")
    assert versioning.apply_version_policy(root, vf)["wiped"]
    assert (root / "issues-state.json").exists()
    assert "O1" in _ids(c.get("/api/issues").json(), "closed")


def test_reset_drops_the_user_state(client):
    c, _ = client
    c.put("/api/issues/O1", json={"status": "closed", "note": "x"})
    it = c.delete("/api/issues/O1/state").json()
    assert it["status"] == "open" and not it["userChanged"] and not it["note"]
    assert c.get("/api/reviews/export").json()["issues"] == []
    assert c.delete("/api/issues/NOPE/state").status_code == 404
