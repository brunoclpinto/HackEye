"""Characterisation tests for lab.api (v26.3.0 p5-06): the route table of ``server.app``, a smoke call per router, the forwarded caches.

The route list below was printed from the legacy ``lab.server.app`` (path and sorted methods, in registration order) in the
hackeye-rnd image before the move; the smoke literals come from the same app on the same tmp ``LAB_DIR`` fixtures. The ``lab.api``
modules are imported inside the tests that need them (they do not exist yet).
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lab import analysis, recordings, reviews, server

if TYPE_CHECKING:
    from pathlib import Path

RUN = "0123456789ab"
REC = {"id": "rec1", "duration": 100.0, "width": 320, "height": 180, "fps": 10.0, "chapters": [], "name": "rec1"}

ROUTES: list[tuple[str, list[str]]] = [
    ("/openapi.json", ["GET", "HEAD"]),
    ("/docs", ["GET", "HEAD"]),
    ("/docs/oauth2-redirect", ["GET", "HEAD"]),
    ("/redoc", ["GET", "HEAD"]),
    ("/api/version", ["GET"]),
    ("/api/client-log", ["POST"]),
    ("/api/recordings", ["GET"]),
    ("/api/recordings/{rec_id}/proxy", ["POST"]),
    ("/media/{name}", ["GET", "HEAD"]),
    ("/api/recordings/{rec_id}/settings", ["GET"]),
    ("/api/recordings/{rec_id}/settings", ["PUT"]),
    ("/api/config/collision", ["GET"]),
    ("/api/models", ["GET"]),
    ("/api/runs", ["POST"]),
    ("/api/runs/{run_id}/cancel", ["POST"]),
    ("/api/runs", ["GET"]),
    ("/api/runs/{run_id}", ["GET"]),
    ("/api/runs/{run_id}/collision", ["POST"]),
    ("/api/runs/{run_id}/collisions/{cid}/cancel", ["POST"]),
    ("/api/runs/{run_id}/collisions", ["GET"]),
    ("/api/runs/{run_id}/collisions/compare", ["GET"]),
    ("/api/runs/{run_id}/collisions/{cid}", ["PATCH"]),
    ("/api/runs/{run_id}/collisions/{cid}", ["DELETE"]),
    ("/api/runs/{run_id}/worldmap", ["POST"]),
    ("/api/runs/{run_id}/worldmap", ["GET"]),
    ("/api/runs/{run_id}/worldmap/pose.json", ["GET"]),
    ("/api/runs/{run_id}/worldmap/cell", ["GET"]),
    ("/api/runs/{run_id}/worldmap/{index}.png", ["GET"]),
    ("/api/runs/{run_id}/hazards", ["GET"]),
    ("/api/runs/{run_id}/frame", ["GET"]),
    ("/api/runs/{run_id}/{name}.json", ["GET"]),
    ("/api/runs/{run_id}/frames/{index}/mask.png", ["GET"]),
    ("/api/runs/{run_id}/frames/{index}/classes.png", ["GET"]),
    ("/api/runs/{run_id}/depth/{index}.png", ["GET"]),
    ("/api/runs/{run_id}/classes", ["GET"]),
    ("/api/sounds", ["GET"]),
    ("/api/sounds", ["PUT"]),
    ("/api/sounds", ["DELETE"]),
    ("/api/display/{mapping}", ["GET"]),
    ("/api/display/{mapping}/{section}", ["PUT"]),
    ("/api/display/{mapping}/{section}", ["DELETE"]),
    ("/api/notes", ["GET"]),
    ("/api/notes", ["PUT"]),
    ("/api/issues", ["GET"]),
    ("/api/issues/{issue_id}", ["PUT"]),
    ("/api/issues/{issue_id}/state", ["DELETE"]),
    ("/api/reviews/export", ["GET"]),
    ("/api/recordings/{rec_id}/reviews", ["GET"]),
    ("/api/recordings/{rec_id}/reviews", ["POST"]),
    ("/api/recordings/{rec_id}/reviews/{ann_id}", ["PUT"]),
    ("/api/recordings/{rec_id}/reviews/{ann_id}", ["DELETE"]),
    ("/", ["GET"]),
    ("/static", []),
]


def _doc(cid: str) -> dict[str, Any]:
    return {"id": cid, "status": "done", "label": cid, "settings": {"k": cid}, "counts": {"n": 1}}


HAZARDS: dict[str, Any] = {
    "version": "v", "settings": {"a": 1}, "projection": "flat", "gridW": 2, "gridH": 2, "egoAvailable": False,
    "frames": [{"t": 0.0, "h": []}, {"t": 1.0, "h": [1]}, {"t": 2.0, "h": []}],
}  # fmt: skip


@pytest.fixture
def lab(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[TestClient, Path]:
    """A tmp LAB_DIR with one done run that has two collision runs (c1, c2) and the recording ``rec1``."""
    monkeypatch.setattr(recordings, "get_recording", lambda i: REC if i == "rec1" else None)
    # Opus (p5-06): no host recordings in the scan (the check container mounts the real ones at /media).
    monkeypatch.setattr(recordings, "MEDIA_DIR", tmp_path / "no-media")
    for mod in (analysis, recordings, reviews):
        monkeypatch.setattr(mod, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    monkeypatch.setattr(server, "_wm_cache", OrderedDict())
    monkeypatch.setattr(server, "_hz_cache", OrderedDict())
    d = tmp_path / "runs" / RUN
    d.mkdir(parents=True)
    run = {
        "id": RUN, "request": {"recording": "rec1"}, "status": "done", "classNames": ["a"],
        "createdAt": "2026-10-31T10:00:00Z", "collisions": ["c1", "c2"], "collisionSeq": 2,
    }  # fmt: skip
    (d / "run.json").write_text(json.dumps(run))
    np.savez(d / "grids.npz", grids=np.zeros((3, 135, 240), np.uint8), t=np.arange(3.0), index=np.arange(3))
    for cid in ("c1", "c2"):
        cd = d / "collisions" / cid
        cd.mkdir(parents=True)
        (cd / "collision.json").write_text(json.dumps(_doc(cid)))
        (cd / "events.json").write_text(json.dumps({"events": [{"t": 1.0, "type": "speech", "text": "pole"}]}))
        (cd / "hazards.json").write_text(json.dumps(HAZARDS))
    return TestClient(server.app), d


# ---- the route table --------------------------------------------------------------------------------------------------------


def test_route_table_is_today_s_list_in_order() -> None:
    got = [(r.path, sorted(getattr(r, "methods", None) or [])) for r in server.app.routes]
    assert got == ROUTES


# ---- a smoke call per router ------------------------------------------------------------------------------------------------


def test_system_router(lab: tuple[TestClient, Path]) -> None:
    c, root = lab
    r = c.get("/api/version")
    assert r.status_code == 200 and set(r.json()) == {"version", "since", "lastWipe"} and r.json()["since"] is None
    assert c.post("/api/client-log", json=[{"a": 1}]).json() == {"ok": True, "n": 1}
    line = json.loads((root.parent.parent / "client-log.jsonl").read_text().splitlines()[-1])
    assert line["a"] == 1 and line["ua"] == "testclient"
    bad = c.post("/api/client-log", content=b"{}")
    assert (bad.status_code, bad.json()) == (400, {"detail": "body must be a JSON array"})
    page = c.get("/")
    assert page.status_code == 200 and page.headers["content-type"] == "text/html; charset=utf-8"
    assert "<title>HackEye Lab</title>" in page.text and page.headers["cache-control"] == "no-cache"
    assert c.get("/static/index.html").status_code == 200
    miss = c.get("/static/nope.js")
    assert (miss.status_code, miss.json()) == (404, {"detail": "Not Found"})


def test_recordings_router(lab: tuple[TestClient, Path]) -> None:
    c, _ = lab
    assert c.get("/api/recordings").json() == []
    s = c.get("/api/recordings/rec1/settings")
    assert s.status_code == 200 and s.json()["mount"] == "chest" and s.json()["resolved"]["projection"] == "fisheye"
    p = c.put("/api/recordings/rec1/settings", json={"mount": "head"})
    assert p.status_code == 200 and p.json()["mount"] == "head" and p.json()["resolved"]["cameraHeightM"] == 1.65
    for r in (c.get("/api/recordings/nope/settings"), c.post("/api/recordings/nope/proxy")):
        assert (r.status_code, r.json()) == (404, {"detail": "Unknown recording: nope"})
    m = c.get("/media/rec1.mp4")
    assert (m.status_code, m.json()) == (404, {"detail": "Proxy not ready"})


def test_config_router(lab: tuple[TestClient, Path]) -> None:
    c, _ = lab
    cfg = c.get("/api/config/collision").json()
    assert cfg["defaultMount"] == "chest" and cfg["defaultHfovDeg"] == 118
    models = c.get("/api/models").json()
    assert models["models"] == []
    assert models["profiles"] == ["544p", "576p", "608p", "640p", "672p", "704p", "736p"]
    assert models["depthModels"] == ["none", "da3-small", "da3-base", "da2-metric-outdoor-small", "unidepth-v2-s"]


def test_runs_router(lab: tuple[TestClient, Path]) -> None:
    c, _ = lab
    doc = {"id": RUN, "request": {"recording": "rec1"}, "status": "done", "classNames": ["a"], "createdAt": "2026-10-31T10:00:00Z"}
    listed = c.get("/api/runs").json()
    assert [r["id"] for r in listed] == [RUN]
    one = c.get(f"/api/runs/{RUN}").json()
    assert {k: one[k] for k in doc} == doc
    for r in (c.get("/api/runs/zzz"), c.post("/api/runs/zzz/cancel")):
        assert (r.status_code, r.json()) == (404, {"detail": "Unknown run: zzz"})


def test_collisions_router(lab: tuple[TestClient, Path]) -> None:
    c, _ = lab
    assert c.get(f"/api/runs/{RUN}/collisions").json() == [_doc("c1"), _doc("c2")]
    assert c.get(f"/api/runs/{RUN}/collisions/compare?a=c1&b=c2").json() == {
        "a": "c1",
        "b": "c2",
        "settings": [{"key": "settings.k", "a": "c1", "b": "c2"}],
        "counts": {"a": {"n": 1}, "b": {"n": 1}},
        "events": {"same": 1, "changed": [], "onlyA": [], "onlyB": []},
    }
    for r in (
        c.post(f"/api/runs/{RUN}/collisions/c9/cancel"),
        c.patch(f"/api/runs/{RUN}/collisions/c9", json={}),
        c.delete(f"/api/runs/{RUN}/collisions/c9"),
    ):
        assert (r.status_code, r.json()) == (404, {"detail": "Unknown collision run: c9"})
    assert c.patch(f"/api/runs/{RUN}/collisions/c2", json={"label": "new"}).json() == {**_doc("c2"), "label": "new"}
    assert c.delete(f"/api/runs/{RUN}/collisions/c2").json() == {"deleted": "c2", "collisions": ["c1"]}
    assert c.get(f"/api/runs/{RUN}/collisions").json() == [_doc("c1")]


def test_worldmap_router(lab: tuple[TestClient, Path]) -> None:
    c, _ = lab
    assert c.get(f"/api/runs/{RUN}/worldmap").json() == {"exists": False}
    assert c.get(f"/api/runs/{RUN}/worldmap?collision=c2").json() == {"exists": False}
    assert c.get(f"/api/runs/{RUN}/worldmap/cell?x=0&y=0").status_code == 422


def test_rundata_router(lab: tuple[TestClient, Path]) -> None:
    c, _ = lab
    win = c.get(f"/api/runs/{RUN}/hazards?from=0.5&to=2")
    assert win.status_code == 200 and win.headers["cache-control"] == "no-cache"
    assert win.json() == {
        "version": "v", "settings": {"a": 1}, "projection": "flat", "gridW": 2, "gridH": 2, "egoAvailable": False,
        "from": 0.5, "to": 2.0, "frames": [{"t": 1.0, "h": [1]}, {"t": 2.0, "h": []}],
    }  # fmt: skip
    assert c.get(f"/api/runs/{RUN}/frame?t=1.2").json() == {"frame": {"t": 1.0, "h": [1]}}
    far = c.get(f"/api/runs/{RUN}/frame?t=9")
    assert (far.status_code, far.json()) == (404, {"detail": "No analysed frame at this time (outside the run)"})
    bad = c.get(f"/api/runs/{RUN}/hazards?from=2&to=1")
    assert (bad.status_code, bad.json()) == (422, {"detail": "from and to must be finite numbers with to >= from"})
    assert c.get(f"/api/runs/{RUN}/events.json").json() == {"events": [{"t": 1.0, "type": "speech", "text": "pole"}]}
    assert c.get(f"/api/runs/{RUN}/bogus.json").json() == {"detail": "Not found"}
    nodepth = c.get(f"/api/runs/{RUN}/depth/0.png")
    assert (nodepth.status_code, nodepth.json()) == (404, {"detail": "Run has no depth"})
    noframe = c.get(f"/api/runs/{RUN}/frames/0/mask.png")
    assert (noframe.status_code, noframe.json()) == (404, {"detail": "No such frame"})


def test_sounds_display_notes_issues_reviews_routers(lab: tuple[TestClient, Path]) -> None:
    c, _ = lab
    kinds = c.get("/api/sounds").json()["kinds"]
    assert kinds[0] == {
        "kind": "collision-left", "label": "Collision left (9:00-11:30)", "pitchHz": 660, "durationMs": 80,
        "intervalS": 0.5, "default": {"pitchHz": 660, "durationMs": 80, "intervalS": 0.5},
    }  # fmt: skip
    assert c.delete("/api/sounds").json()["kinds"] == kinds
    d = c.get("/api/display/bogus")
    assert (d.status_code, d.json()) == (404, {"detail": "Unknown mapping: bogus"})
    assert c.get("/api/notes").json() == {"text": "", "updatedAt": None}
    put = c.put("/api/notes", json={"text": "hi", "baseUpdatedAt": None}).json()
    assert put["text"] == "hi" and c.get("/api/notes").json() == put
    assert c.get("/api/issues").json()["groups"][0]["id"] == "open"
    for r in (c.put("/api/issues/ZZ", json={}), c.delete("/api/issues/ZZ/state")):
        assert (r.status_code, r.json()) == (404, {"detail": "Unknown issue ZZ"})
    assert c.get("/api/recordings/rec1/reviews").json() == {"recording": "rec1", "annotations": []}
    exp = c.get("/api/reviews/export").json()
    assert set(exp) == {"exportedAt", "recordings", "notes", "issues"} and exp["notes"]["text"] == "hi"
    bad = c.post("/api/recordings/rec1/reviews", json={"t": 1.0, "type": "note", "note": "x"})
    assert (bad.status_code, bad.json()) == (422, {"detail": "kind must be one of ['verdict', 'added']"})


# ---- the caches stay patchable through ``server`` ---------------------------------------------------------------------------


def test_cache_names_are_the_routers_objects() -> None:
    from lab.api import rundata, worldmap

    for name in ("_hz_cache", "_hz_lock", "_grid_cache", "_grid_lock", "_depth_cache", "_depth_lock"):
        assert getattr(server, name) is getattr(rundata, name), name
    for name in ("_wm_cache", "_wm_lock"):
        assert getattr(server, name) is getattr(worldmap, name), name


def test_deps_helpers_are_the_servers_names() -> None:
    from lab.api import deps

    for name in ("_collision", "_recording", "_run"):
        assert getattr(server, name) is getattr(deps, name), name


def test_hz_cache_patch_is_seen_by_the_hazards_handler(lab: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    from lab.api import rundata

    c, d = lab
    st = (d / "collisions" / "c2" / "hazards.json").stat()
    seeded = {
        "sig": (st.st_mtime_ns, st.st_size),
        "head": {"version": "seeded", "gridW": 7},
        "frames": [{"t": 9.0, "h": ["seeded"]}],
        "times": [9.0],
    }
    cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict({(RUN, "c2"): seeded})
    monkeypatch.setattr(server, "_hz_cache", cache)
    assert rundata._hz_cache is cache
    r = c.get(f"/api/runs/{RUN}/hazards?from=9&to=10&collision=c2")
    assert r.status_code == 200
    assert r.json() == {
        "version": "seeded", "settings": None, "projection": None, "gridW": 7, "gridH": None, "egoAvailable": None,
        "from": 9.0, "to": 10.0, "frames": [{"t": 9.0, "h": ["seeded"]}],
    }  # fmt: skip
    # a miss fills the patched cache, not another one
    assert c.get(f"/api/runs/{RUN}/frame?t=1.2&collision=c1").status_code == 200
    assert list(cache) == [(RUN, "c2"), (RUN, "c1")]
