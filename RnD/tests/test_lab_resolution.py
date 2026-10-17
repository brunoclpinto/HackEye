"""Lab resolution (Np profile): request validation, /api/models, Recording.inputSizes."""
import pytest
from fastapi.testclient import TestClient

from lab import analysis, recordings, server

REC_4K = {"id": "r4k", "duration": 100.0, "width": 3840, "height": 2160, "fps": 24.0, "chapters": [], "name": "r4k"}
REC_SMALL = {"id": "rsm", "duration": 100.0, "width": 960, "height": 540, "fps": 24.0, "chapters": [], "name": "rsm"}


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    recs = {r["id"]: r for r in (REC_4K, REC_SMALL)}
    monkeypatch.setattr(recordings, "get_recording", lambda i: recs.get(i))
    monkeypatch.setattr(analysis, "list_models", lambda: [{"path": "m.pt", "name": "m", "default": True}])


def _req(rec, profile=None):
    r = {"recording": rec, "start": 0, "end": 10, "fps": 6, "model": "m.pt"}
    if profile is not None:
        r["profile"] = profile
    return r


def test_np_profile_validates_and_is_stored():
    assert analysis._normalise_request(_req("r4k", "576p"))["profile"] == "576p"


def test_legacy_and_missing_profile_accepted():
    for p in ("default", "production", "half", "quarter"):
        assert analysis._normalise_request(_req("r4k", p))["profile"] == p
    assert analysis._normalise_request(_req("r4k"))["profile"] == "default"


def test_upscaling_np_is_a_run_error():
    assert analysis._normalise_request(_req("rsm", "544p"))["profile"] == "544p"
    with pytest.raises(analysis.RunError, match="upscale"):
        analysis._normalise_request(_req("rsm", "576p"))
    with pytest.raises(analysis.RunError):
        analysis._normalise_request(_req("r4k", "500p"))


def test_models_endpoint_offers_the_seven_resolutions():
    r = TestClient(server.app).get("/api/models").json()
    assert r["profiles"] == ["544p", "576p", "608p", "640p", "672p", "704p", "736p"]


def test_input_sizes():
    s = recordings._input_sizes(1920, 1080)
    assert list(s) == ["544p", "576p", "608p", "640p", "672p", "704p", "736p"]
    assert s["544p"] == [960, 544] and s["736p"] == [1280, 736]
    assert list(recordings._input_sizes(960, 540)) == ["544p"]
