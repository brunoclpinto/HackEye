"""LocalWorker GPU share: flock on a shared lock file (src/gpu_share.py), the model cache and the Lab server honouring it."""
import fcntl
import os
import queue
import sys
import types

import pytest
from fastapi.testclient import TestClient

import gpu_share
from lab import analysis, recordings, server


@pytest.fixture
def lock(tmp_path, monkeypatch):
    path = tmp_path / "gpu.lock"
    path.write_bytes(b"")
    monkeypatch.setattr(gpu_share, "GPUQ_LOCK", path)
    return path


@pytest.fixture
def holder(lock):
    """LocalWorker: an exclusive hold on the lock file (a separate open file description)."""
    fd = os.open(lock, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX)
    yield fd
    os.close(fd)


def test_missing_lock_file_is_not_held(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu_share, "GPUQ_LOCK", tmp_path / "nope.lock")
    assert gpu_share.localworker_holds_gpu() is False
    share = gpu_share.GpuShare()
    assert share.acquire() is True and share.held is False


def test_free_lock_is_not_held_and_probe_leaves_no_lock(lock):
    assert gpu_share.localworker_holds_gpu() is False
    fd = os.open(lock, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the probe left nothing behind
    os.close(fd)


def test_exclusive_holder_blocks(lock, holder):
    assert gpu_share.localworker_holds_gpu() is True
    share = gpu_share.GpuShare()
    assert share.acquire() is False and share.held is False


def test_acquire_idempotent_and_release_frees(lock):
    share = gpu_share.GpuShare()
    assert share.acquire() and share.acquire() and share.held
    assert gpu_share.localworker_holds_gpu() is False  # SH + SH
    fd = os.open(lock, os.O_RDONLY)
    with pytest.raises(OSError):  # LocalWorker cannot take EX while the Lab is resident
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    share.release()
    assert share.held is False
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(fd)
    share.release()  # harmless twice


class _Fake:
    built: list = []
    fail = False

    def __init__(self, *args):
        if type(self).fail:
            raise RuntimeError("load failed")
        type(self).built.append(args)


@pytest.fixture
def cache(lock, monkeypatch, tmp_path):
    import torch

    _Fake.built, _Fake.fail = [], False
    monkeypatch.setitem(sys.modules, "models", types.SimpleNamespace(SegmentationModel=_Fake))
    monkeypatch.setitem(sys.modules, "depth", types.SimpleNamespace(DepthModel=_Fake))
    monkeypatch.setattr(torch, "set_num_threads", lambda n: None)
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis._ModelCache, "_torch_device",
                        staticmethod(lambda d: torch.device("cpu" if d == "cpu" else "cuda:0")))
    return analysis._ModelCache()


def test_gpu_seg_load_holds_share_until_release(cache):
    cache.get("m.pt", "gpu")
    assert cache.share.held
    cache.release()
    assert not cache.share.held


def test_gpu_depth_load_holds_share_and_cpu_never_touches_lock(cache, holder):
    cache.get("m.pt", "cpu")  # blocked by LocalWorker, but CPU never asks
    cache.get_depth("da3-small", "cpu")
    assert not cache.share.held
    cache.release()
    cache.share.release()


def test_depth_gpu_acquires(cache):
    cache.get_depth("da3-small", "gpu")
    assert cache.share.held
    cache.release()
    assert not cache.share.held


def test_blocked_gpu_load_raises_clear_error(cache, holder):
    with pytest.raises(analysis.GpuBlocked, match="GPU in use by LocalWorker; choose CPU"):
        cache.get("m.pt", "gpu")
    with pytest.raises(analysis.GpuBlocked):
        cache.get_depth("da3-small", "gpu")
    assert _Fake.built == [] and not cache.share.held


def test_load_failure_releases_share(cache):
    _Fake.fail = True
    with pytest.raises(RuntimeError):
        cache.get("m.pt", "gpu")
    assert not cache.share.held
    with pytest.raises(RuntimeError):
        cache.get_depth("da3-small", "gpu")
    assert not cache.share.held


def test_depth_failure_keeps_share_for_resident_gpu_seg(cache):
    cache.get("m.pt", "gpu")
    _Fake.fail = True
    with pytest.raises(RuntimeError):
        cache.get_depth("da3-small", "gpu")
    assert cache.share.held
    cache.release()


@pytest.fixture
def client(tmp_path, monkeypatch, lock):
    model = tmp_path / "m.pt"
    model.write_bytes(b"x")
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    monkeypatch.setattr(analysis, "_cancel_flags", {})
    monkeypatch.setattr(analysis, "_jobs", queue.Queue())
    monkeypatch.setattr(analysis, "_busy", None)
    monkeypatch.setattr(analysis, "_maintenance", False)
    monkeypatch.setattr(analysis, "_ensure_worker", lambda: None)
    monkeypatch.setattr(recordings, "get_recording", lambda rid: {"id": rid, "duration": 100.0, "width": 1920, "height": 1080})
    monkeypatch.setattr(analysis, "list_models", lambda: [{"path": str(model), "name": "m.pt", "default": True}])
    body = {"recording": "4929", "start": 0, "end": 10, "model": str(model), "profile": "736p", "fps": 6}
    return TestClient(server.app), body


def test_models_endpoint_reports_gpu_availability(client, holder):
    c, _ = client
    assert c.get("/api/models").json()["gpuAvailable"] is False
    assert c.get("/api/models").json()["gpuBlockedBy"] == "localworker"


def test_models_endpoint_gpu_free(client):
    c, _ = client
    j = c.get("/api/models").json()
    assert j["gpuAvailable"] is True and j["gpuBlockedBy"] is None


def test_gpu_run_rejected_409_while_blocked(client, holder):
    c, body = client
    for extra in ({}, {"device": "gpu"}, {"device": None}, {"device": "gpu", "force": True}):
        r = c.post("/api/runs", json={**body, **extra})
        assert r.status_code == 409
        assert r.json() == {"detail": "GPU in use by LocalWorker; choose CPU"}
    assert analysis._jobs.empty() and not analysis._active


def test_cpu_run_accepted_while_blocked(client, holder):
    c, body = client
    r = c.post("/api/runs", json={**body, "device": "cpu"})
    assert r.status_code == 200 and r.json()["device"] == "cpu"


def test_queued_gpu_job_fails_fast_when_blocked(client, holder, monkeypatch):
    """A job queued before LocalWorker took the GPU reaches the worker: status error, no CUDA OOM."""
    c, body = client
    monkeypatch.setattr(analysis, "_cache", analysis._ModelCache())
    run_id = analysis._run_id(analysis._normalise_request(body))
    doc = {"id": run_id, "request": analysis._normalise_request(body), "device": "gpu", "status": "queued", "progress": 0.0}
    analysis.run_dir(run_id).mkdir(parents=True)
    analysis._write_json(analysis.run_dir(run_id) / "run.json", doc)
    analysis._active[run_id] = doc
    with pytest.raises(analysis.GpuBlocked):
        analysis._run_job(run_id, analysis._cache)
