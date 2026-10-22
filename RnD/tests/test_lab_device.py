"""Opt-in CPU device for Lab analysis runs: request parsing, run doc, id stability, model cache."""
import queue
import sys
import types

import pytest
from fastapi.testclient import TestClient

from lab import analysis, recordings, server


@pytest.fixture
def client(tmp_path, monkeypatch):
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


def _post(c, body, **extra):
    return c.post("/api/runs", json={**body, **extra})


def test_cpu_recorded_and_id_independent_of_device(client):
    c, body = client
    cpu = _post(c, body, device="cpu")
    assert cpu.status_code == 200 and cpu.json()["device"] == "cpu"
    assert "device" not in cpu.json()["request"]
    again = _post(c, body, device="gpu")  # identical in-flight run is returned as recorded
    assert again.json()["id"] == cpu.json()["id"] and again.json()["device"] == "cpu"
    assert analysis._run_id(analysis._normalise_request(body)) == cpu.json()["id"]


def test_missing_or_null_device_is_gpu(client):
    c, body = client
    r = _post(c, body)
    assert r.status_code == 200 and r.json()["device"] == "gpu"
    analysis._active.clear()
    assert _post(c, body, device=None).json()["device"] == "gpu"


def test_bad_device_is_422(client):
    c, body = client
    r = _post(c, body, device="tpu")
    assert r.status_code == 422
    assert "device must be one of ['gpu', 'cpu']" in r.text
    assert analysis._jobs.empty()


class _Fake:
    built: list = []

    def __init__(self, *args):
        self.device = args[1] if len(args) > 1 and not isinstance(args[1], str) else args[0]
        type(self).built.append(self.device)


@pytest.fixture
def cache(monkeypatch):
    import torch

    _Fake.built = []
    monkeypatch.setitem(sys.modules, "models", types.SimpleNamespace(SegmentationModel=_Fake))
    monkeypatch.setitem(sys.modules, "depth", types.SimpleNamespace(DepthModel=_Fake))
    monkeypatch.setattr(torch, "set_num_threads", lambda n: None)
    monkeypatch.setattr(analysis._ModelCache, "_torch_device",
                        staticmethod(lambda d: torch.device("cpu" if d == "cpu" else "cuda:0")))
    return analysis._ModelCache()


def test_segmentation_cache_reloads_on_device_change(cache, tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    a = cache.get("m.pt", "cpu")
    assert cache.get("m.pt", "cpu") is a  # same key: reused
    b = cache.get("m.pt", "gpu")
    assert b is not a
    assert [str(d) for d in _Fake.built] == ["cpu", "cuda:0"]


def test_depth_cache_reloads_on_device_change(cache):
    a = cache.get_depth("da3-small", "cpu")
    assert cache.get_depth("da3-small", "cpu") is a
    b = cache.get_depth("da3-small", "gpu")
    assert b is not a
    c = cache.get_depth("da3-base", "gpu")
    assert c is not b
    assert [str(d) for d in _Fake.built] == ["cpu", "cuda:0", "cuda:0"]


def test_release_without_cuda(cache, tmp_path, monkeypatch):
    import torch

    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: pytest.fail("empty_cache without CUDA"))
    cache.get("m.pt", "cpu")
    cache.get_depth("da3-small", "cpu")
    cache.release()
    assert cache.model is None and cache.depth_model is None and cache.device is None


def test_cpu_threads_env(monkeypatch):
    monkeypatch.setenv("HACKEYE_LAB_CPU_THREADS", "3")
    assert analysis._cpu_threads() == 3
    monkeypatch.delenv("HACKEYE_LAB_CPU_THREADS")
    assert analysis._cpu_threads() >= 1
