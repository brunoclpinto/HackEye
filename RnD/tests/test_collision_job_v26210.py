"""v26.2.10: the collision re-run is a background job with progress and Cancel; one at a time; never with an analysis."""
import json
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lab import analysis, collisions, recordings, server

GATES: list = []                     # the events the slow passes wait on; released at teardown
RUN = "0123456789ab"
REC = {"id": "rec1", "duration": 100.0, "width": 320, "height": 180, "fps": 10.0, "chapters": [], "name": "rec1"}


@pytest.fixture
def lab(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings, "get_recording", lambda i: REC if i == "rec1" else None)
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    d = tmp_path / "runs" / RUN
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"id": RUN, "request": {"recording": "rec1"}, "status": "done", "classNames": ["a"],
                                            "createdAt": "2026-11-03T10:00:00Z"}))
    np.savez(d / "grids.npz", grids=np.zeros((3, 135, 240), np.uint8), t=np.arange(3.0), index=np.arange(3))
    monkeypatch.setattr(collisions, "_job", None)
    GATES.clear()
    yield TestClient(server.app), d
    for g in GATES:
        g.set()                      # let a job parked in the slow pass run on
    collisions.cancel_job()
    for _ in range(300):
        if not collisions.job_active():
            break
        time.sleep(0.02)


def _docs(c):
    return c.get(f"/api/runs/{RUN}/collisions").json()


def _slow_pass(monkeypatch, gate):
    """The frame loop stops at its second frame until `gate` is set; reports progress like the real one."""
    import collision
    real = collision.run_collision
    GATES.append(gate)

    def slow(grids, times, names, config, settings, *a, progress=None, **k):
        for i in range(len(grids)):
            progress(i, len(grids))
            if i == 1:
                gate.wait(10)
        return real(grids, times, names, config, settings, *a, progress=None, **k)
    monkeypatch.setattr(collision, "run_collision", slow)


def _wait(c, pred, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        docs = _docs(c)
        if pred(docs):
            return docs
        time.sleep(0.02)
    raise AssertionError("timeout")


def test_rerun_returns_running_progress_grows_and_ends_done(lab, monkeypatch):
    c, _ = lab
    gate = threading.Event()
    _slow_pass(monkeypatch, gate)
    r = c.post(f"/api/runs/{RUN}/collision")
    assert r.status_code == 200 and r.json()["status"] == "running" and r.json()["id"] == "c1"
    docs = _wait(c, lambda ds: ds and ds[0]["progress"] > 0)
    assert docs[0]["status"] == "running" and 0 < docs[0]["progress"] < 0.4
    gate.set()
    docs = _wait(c, lambda ds: ds and ds[0]["status"] != "running")
    assert docs[0]["status"] == "done" and docs[0]["progress"] == 1.0 and docs[0]["error"] is None


def test_second_job_and_an_analysis_are_refused_while_running(lab, monkeypatch):
    c, _ = lab
    gate = threading.Event()
    _slow_pass(monkeypatch, gate)
    assert c.post(f"/api/runs/{RUN}/collision").status_code == 200
    assert c.post(f"/api/runs/{RUN}/collision").status_code == 409
    monkeypatch.setattr(analysis, "_normalise_request", lambda req: {
        "recording": "rec1", "start": 0.0, "end": 10.0, "model": "m.pt", "profile": "default", "fps": 6.0})
    monkeypatch.setattr(analysis, "_run_id", lambda r: "aaaaaaaaaaaa")
    monkeypatch.setattr(analysis, "_ensure_worker", lambda: None)
    with pytest.raises(analysis.RunConflict, match="collision re-run"):
        analysis.submit_run({})
    # a running collision cannot be deleted
    assert c.delete(f"/api/runs/{RUN}/collisions/c1").status_code == 409
    gate.set()
    _wait(c, lambda ds: ds and ds[0]["status"] == "done")
    assert c.post(f"/api/runs/{RUN}/collision").status_code == 200


def test_rerun_is_refused_while_an_analysis_runs(lab, monkeypatch):
    c, _ = lab
    monkeypatch.setattr(analysis, "analysis_active", lambda: True)
    r = c.post(f"/api/runs/{RUN}/collision")
    assert r.status_code == 409 and "analysis" in r.json()["detail"].lower()
    assert _docs(c) == []


def test_cancel_removes_the_directory_and_the_id_is_not_reused(lab, monkeypatch):
    c, d = lab
    gate = threading.Event()
    _slow_pass(monkeypatch, gate)
    assert c.post(f"/api/runs/{RUN}/collision").status_code == 200
    _wait(c, lambda ds: ds and ds[0]["progress"] > 0)
    r = c.post(f"/api/runs/{RUN}/collisions/c1/cancel")
    assert r.status_code == 200 and r.json()["collisions"] == []
    gate.set()
    assert not (d / "collisions" / "c1").exists() and _docs(c) == []
    assert c.post(f"/api/runs/{RUN}/collisions/c1/cancel").status_code in (404, 409)
    r = c.post(f"/api/runs/{RUN}/collision")
    assert r.json()["id"] == "c2"
    _wait(c, lambda ds: ds and ds[0]["status"] == "done")


def test_a_failing_pass_leaves_an_error_row(lab, monkeypatch):
    c, _ = lab
    import collision

    def boom(*a, **k):
        raise RuntimeError("pass blew up")
    monkeypatch.setattr(collision, "run_collision", boom)
    assert c.post(f"/api/runs/{RUN}/collision").status_code == 200
    docs = _wait(c, lambda ds: ds and ds[0]["status"] != "running")
    assert docs[0]["status"] == "error" and "blew up" in docs[0]["error"]
    assert c.delete(f"/api/runs/{RUN}/collisions/c1").status_code == 200       # an errored row can always go


def test_running_doc_without_a_live_job_reads_as_interrupted(lab):
    c, d = lab
    cdir = d / "collisions" / "c1"
    cdir.mkdir(parents=True)
    (cdir / "collision.json").write_text(json.dumps({"id": "c1", "status": "running", "progress": 0.2}))
    run = json.loads((d / "run.json").read_text())
    run["collisions"] = ["c1"]
    (d / "run.json").write_text(json.dumps(run))
    doc = _docs(c)[0]
    assert doc["status"] == "error" and doc["error"] == "interrupted"
