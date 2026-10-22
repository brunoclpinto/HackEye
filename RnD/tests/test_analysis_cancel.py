import json
import queue
import threading

import pytest

from lab import analysis, versioning


def _doc(rid, rec, status):
    return {"id": rid, "request": {"recording": rec}, "status": status, "progress": 0.5}


def test_guard_pure_function():
    active = {"a": _doc("a", "4929", "running"), "b": _doc("b", "5000", "queued")}
    assert analysis.find_active_for_recording(active, "4929")["id"] == "a"
    assert analysis.find_active_for_recording(active, "9999") is None
    active["a"]["status"] = "done"
    assert analysis.find_active_for_recording(active, "4929") is None


@pytest.fixture
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    monkeypatch.setattr(analysis, "_cancel_flags", {})
    monkeypatch.setattr(analysis, "_jobs", queue.Queue())
    monkeypatch.setattr(analysis, "_busy", None)
    monkeypatch.setattr(analysis, "_maintenance", False)
    monkeypatch.setattr(analysis, "_ensure_worker", lambda: None)
    return tmp_path


def _fake_request(monkeypatch, rec, start):
    monkeypatch.setattr(analysis, "_normalise_request", lambda req: {
        "recording": rec, "start": start, "end": start + 10, "model": "m.pt", "profile": "default", "fps": 6.0})
    monkeypatch.setattr(analysis, "_run_id", lambda r: f"{int(r['start']):012x}")


def test_submit_409_same_recording_other_range(clean, monkeypatch):
    _fake_request(monkeypatch, "4929", 600)
    first = analysis.submit_run({})
    assert first["status"] == "queued"
    assert analysis.submit_run({})["id"] == first["id"]  # identical -> in-flight run
    _fake_request(monkeypatch, "4929", 700)
    with pytest.raises(analysis.RunConflict, match=r"already running for 4929 \(run 000000000258, 0%\)"):
        analysis.submit_run({})
    _fake_request(monkeypatch, "5000", 700)  # other recording queues fine
    assert analysis.submit_run({})["status"] == "queued"


def test_submit_refused_during_maintenance(clean, monkeypatch):
    _fake_request(monkeypatch, "4929", 600)
    analysis.begin_maintenance()
    with pytest.raises(analysis.RunConflict):
        analysis.submit_run({})
    analysis.end_maintenance()
    assert analysis.submit_run({})["status"] == "queued"


def test_cancel_queued_job_and_resubmit(clean, monkeypatch):
    _fake_request(monkeypatch, "4929", 600)
    run = analysis.submit_run({})
    out = analysis.run_dir(run["id"])
    (out / "masks").mkdir()
    (out / "masks" / "0.png").write_text("x")
    (out / "grids.npz").write_text("x")
    doc = analysis.cancel_run(run["id"])
    assert doc["status"] == "cancelled"
    assert analysis._jobs.empty() and analysis._active == {}
    assert not (out / "masks").exists() and not (out / "grids.npz").exists()
    assert (out / "run.json").exists()
    with pytest.raises(analysis.RunConflict):
        analysis.cancel_run(run["id"])
    assert analysis.cancel_run("0" * 12) is None
    again = analysis.submit_run({})  # re-POST starts fresh
    assert again["status"] == "queued"


def _finish_fake(run_id, device="gpu"):
    """Mark a queued run as done the way the worker would (drop it from _active, empty the queue)."""
    analysis._jobs.get_nowait()
    analysis._update_run(run_id, status="done", progress=1.0)
    analysis._active.pop(run_id)


def test_submit_reused_and_force(clean, monkeypatch):
    _fake_request(monkeypatch, "4929", 600)
    run = analysis.submit_run({"device": "cpu"})
    assert "reused" not in run  # in flight: returned as is, no marker
    assert analysis.submit_run({"force": True})["id"] == run["id"] and analysis._jobs.qsize() == 1  # active: no double run
    _finish_fake(run["id"])
    out = analysis.run_dir(run["id"])
    (out / "grids.npz").write_text("x")
    (clean / "reviews").mkdir()
    (clean / "reviews" / "4929.json").write_text("{}")
    again = analysis.submit_run({"device": "gpu"})
    assert again["reused"] is True and again["status"] == "done" and again["device"] == "cpu"
    assert "reused" not in json.loads((out / "run.json").read_text())  # response-only
    assert (out / "grids.npz").exists() and analysis._jobs.empty()
    forced = analysis.submit_run({"force": True, "device": "gpu"})
    assert forced["id"] == run["id"] and forced["status"] == "queued" and "reused" not in forced
    assert forced["device"] == "gpu" and forced["finishedAt"] is None
    assert not (out / "grids.npz").exists() and (clean / "reviews" / "4929.json").exists()
    assert analysis._jobs.qsize() == 1
    # force on a cancelled run also restarts; the per-recording guard still applies
    analysis.cancel_run(run["id"])
    assert analysis.submit_run({"force": True})["status"] == "queued"
    _fake_request(monkeypatch, "4929", 700)
    with pytest.raises(analysis.RunConflict):
        analysis.submit_run({"force": True})


class FakeWorker:
    def __init__(self, idle=True, log=None):
        self.idle, self.log = idle, log if log is not None else []

    def begin_maintenance(self): self.log.append("begin")
    def wait_idle(self, t): self.log.append("wait"); return self.idle
    def release_model(self): self.log.append("release")
    def end_maintenance(self): self.log.append("end")


@pytest.fixture
def lab(tmp_path):
    lab = tmp_path / "lab"
    (lab / "runs" / "r1").mkdir(parents=True)
    (lab / "reviews").mkdir()
    (lab / "proxies").mkdir()
    (lab / "proxies" / "p").write_text("x")
    vf = tmp_path / "VERSION"
    vf.write_text("v1\n")
    versioning.apply_version_policy(lab, vf)
    return lab, vf


def test_watcher_noop_when_unchanged(lab):
    d, vf = lab
    w = FakeWorker()
    assert versioning.VersionWatcher(d, vf, w).tick() is None
    assert w.log == []


def test_watcher_cancel_then_wipe_sequence(lab):
    d, vf = lab
    vf.write_text("v2\n")
    w = FakeWorker()
    seen = []
    res = versioning.VersionWatcher(d, vf, w, on_result=seen.append).tick()
    assert w.log == ["begin", "wait", "release", "end"]
    assert res["wiped"] and seen == [res]
    assert not (d / "runs" / "r1").exists() and (d / "proxies" / "p").exists()


def test_watcher_skips_wipe_when_not_idle_then_retries(lab):
    d, vf = lab
    vf.write_text("v2\n")
    w = FakeWorker(idle=False)
    wt = versioning.VersionWatcher(d, vf, w)
    assert wt.tick() is None
    assert w.log == ["begin", "wait", "end"]  # no release, no wipe
    assert (d / "runs" / "r1").exists()
    w.idle = True
    assert wt.tick()["wiped"]


def test_watcher_ignores_bad_version(lab):
    d, vf = lab
    vf.write_text("")
    w = FakeWorker()
    assert versioning.VersionWatcher(d, vf, w).tick() is None and w.log == []
