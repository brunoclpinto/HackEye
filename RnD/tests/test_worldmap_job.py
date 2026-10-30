"""v26.2.6: the world map is built with the run and after every collision re-run, also when none existed."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lab import analysis, recordings, server

RUN = "0123456789ab"
REC = {"id": "rec1", "duration": 100.0, "width": 320, "height": 180, "fps": 10.0, "chapters": [], "name": "rec1"}


@pytest.fixture
def run_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings, "get_recording", lambda i: REC if i == "rec1" else None)
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    d = tmp_path / "runs" / RUN
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"id": RUN, "request": {"recording": "rec1"}, "status": "done", "classNames": ["a"]}))
    np.savez(d / "grids.npz", grids=np.zeros((3, 135, 240), np.uint8), t=np.arange(3.0), index=np.arange(3))
    return d


def test_collision_rerun_builds_a_map_when_none_existed(run_dir):
    assert not (run_dir / "worldmap.npz").exists()
    r = TestClient(server.app).post(f"/api/runs/{RUN}/collision")
    assert r.status_code == 200, r.text
    assert (run_dir / "worldmap.npz").exists()


def test_collision_rerun_survives_a_failing_map(run_dir, monkeypatch):
    def boom(run_id):
        raise RuntimeError("no map")
    monkeypatch.setattr(analysis, "worldmap_pass", boom)
    assert TestClient(server.app).post(f"/api/runs/{RUN}/collision").status_code == 200


def test_job_helper_builds_the_map_and_swallows_a_failure(run_dir, monkeypatch):
    analysis.collision_pass(RUN)
    analysis._build_worldmap(RUN)
    assert (run_dir / "worldmap.npz").exists()

    def boom(run_id):
        raise RuntimeError("no map")
    monkeypatch.setattr(analysis, "worldmap_pass", boom)
    analysis._build_worldmap(RUN)          # logged, not raised
