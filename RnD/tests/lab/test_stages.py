"""Characterisation tests for lab.stages (v26.3.0 p5-04): model cache, frame reader, collision pass, worldmap pass.

Today every name lives on ``lab.analysis``; after the move ``analysis`` forwards each moved name to its home
(``lab.stages.models``, ``.frames``, ``.inference``, ``.collision``, ``.worldmap``). Every assert holds on both sides: the literals were
printed by running the legacy code in the hackeye-rnd image. The ``lab.stages`` modules are imported inside each test (they do not exist yet).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from lab import analysis, collisions, recordings

RUN = "0123456789ab"
REC = {"id": "rec1", "duration": 100.0, "width": 320, "height": 180, "fps": 10.0, "chapters": [], "name": "rec1"}


# ---- identity through analysis --------------------------------------------------------------------------------------------------


def test_stage_names_are_the_analysis_names() -> None:
    from lab.stages import collision as sc
    from lab.stages import frames, inference, models
    from lab.stages import worldmap as sw

    assert analysis._ModelCache is models._ModelCache
    assert analysis._FrameReader is frames._FrameReader
    assert analysis.MOTION_W is frames.MOTION_W and analysis.MOTION_H is frames.MOTION_H
    assert (frames.MOTION_W, frames.MOTION_H) == (160, 90)
    assert analysis._run_job is inference._run_job
    assert analysis._build_worldmap is sc._build_worldmap
    assert analysis.collision_pass is sc.collision_pass
    assert analysis.worldmap_pass is sw.worldmap_pass


# ---- _ModelCache ------------------------------------------------------------------------------------------------------------------


class _FakeModel:
    def __init__(self, *args: Any) -> None:
        self.args = args


def test_model_cache_uses_the_patched_device_hook_and_the_flat_models_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lab.stages import models

    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.delenv("YOLO_CONFIG_DIR", raising=False)
    monkeypatch.setitem(sys.modules, "models", types.SimpleNamespace(SegmentationModel=_FakeModel))
    monkeypatch.setitem(sys.modules, "depth", types.SimpleNamespace(DepthModel=_FakeModel))
    asked: list[str] = []

    def device(d: str) -> str:
        asked.append(d)
        return f"dev-{d}"

    monkeypatch.setattr(models._ModelCache, "_torch_device", staticmethod(device))
    cache = analysis._ModelCache()
    assert (cache.path, cache.device, cache.model, cache.depth_model, cache.last_used) == (None, None, None, None, 0.0)
    m = cache.get("m.pt", "cpu")
    assert isinstance(m, _FakeModel) and m.args == ("m.pt", "dev-cpu") and cache.path == "m.pt" and cache.device == "cpu"
    assert cache.get("m.pt", "cpu") is m and asked == ["cpu"]
    assert cache.get("m.pt", "gpu") is not m and asked == ["cpu", "gpu"]
    assert (tmp_path / ".ultralytics").is_dir()
    import os

    assert os.environ["YOLO_CONFIG_DIR"] == str(tmp_path / ".ultralytics")
    monkeypatch.delenv("YOLO_CONFIG_DIR")
    d = cache.get_depth("da3-small", "gpu")
    assert isinstance(d, _FakeModel) and d.args == ("dev-gpu", "da3-small") and (cache.depth_variant, cache.depth_device) == ("da3-small", "gpu")
    assert cache.get_depth("da3-small", "gpu") is d


# ---- _FrameReader ------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def video(tmp_path: Path) -> dict[str, Any]:
    """10 frames of 64x48 (gradient + a moving box) in one MJPG chapter at 10 fps."""
    f = tmp_path / "v.avi"
    w = cv2.VideoWriter(str(f), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48))
    for i in range(10):
        img = np.zeros((48, 64, 3), np.uint8)
        img[:, :, 0] = np.linspace(0, 255, 64, dtype=np.uint8)[None, :]
        img[:, :, 1] = i * 20
        img[10 + i : 20 + i, 5 : 15 + i, 2] = 200
        w.write(img)
    w.release()
    return {"fps": 10.0, "chapters": [{"file": str(f), "start": 0.0, "duration": 1.0, "frames": 10}]}


FRAME_SUMS = [406618, 468926, 531829, 596476, 659065, 721831, 785991, 849247, 911954, 975958]


def test_frame_reader_reads_every_frame_then_none(video: dict[str, Any]) -> None:
    from lab.stages.frames import _FrameReader

    r = _FrameReader(video)
    got = [r.read(i / 10) for i in range(12)]
    assert got[10] is None and got[11] is None
    frames = [g for g in got if g is not None]
    assert len(frames) == 10
    assert [t for t, _ in frames] == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    assert all(b.shape == (48, 64, 3) for _, b in frames)
    assert [int(b.sum()) for _, b in frames] == FRAME_SUMS
    import zlib

    assert zlib.crc32(frames[0][1].tobytes()) == 1277757356
    r.close()


def test_frame_reader_repeat_and_backward_reads(video: dict[str, Any]) -> None:
    from lab.stages.frames import _FrameReader

    r = _FrameReader(video)
    a = r.read(0.5)
    assert a is not None and a[0] == 0.5 and int(a[1].sum()) == FRAME_SUMS[5]
    b = r.read(0.5)
    assert b is not None and b[1] is a[1]  # the cached frame, not a second decode
    c = r.read(0.0)
    assert c is not None and c[0] == 0.0 and int(c[1].sum()) == FRAME_SUMS[0]
    r.close()


def test_frame_reader_locate(video: dict[str, Any]) -> None:
    from lab.stages.frames import _FrameReader

    r = _FrameReader(video)
    assert r._locate(0.0) == (0, 0)
    assert r._locate(0.97) == (1, 0)
    assert r._locate(1.0) == (1, 0)
    assert r._locate(5.0) == (1, 0)


def test_frame_reader_motion_track(video: dict[str, Any]) -> None:
    from lab.stages.frames import _FrameReader

    r = _FrameReader(video, motion_end=1.0)
    for i in range(10):
        r.read(i / 10)
    r.finish_motion()
    m = r.motion_track()
    assert {k: (v.dtype.str, v.shape) for k, v in m.items()} == {"t": ("<f8", (10,)), "dx": ("<f4", (10,)), "dy": ("<f4", (10,)), "resid": ("<f4", (10,))}
    assert m["t"].tolist() == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    dx = [0.0, 0.007431801, 0.011782384, 0.010923866, 0.01914124, 0.011977654, 0.010685218, 0.013573699, 0.012696162, 0.011134763]
    dy = [0.0, 0.023009978, 0.017591847, 0.017168751, 0.023224143, 0.02206042, 0.020450674, 0.020784713, 0.018595546, 0.022294099]
    assert m["dx"].tolist() == pytest.approx(dx, rel=1e-6, abs=1e-8)
    assert m["dy"].tolist() == pytest.approx(dy, rel=1e-6, abs=1e-8)
    assert np.isnan(m["resid"]).tolist() == [True, True, True, True, True, True, False, True, True, True]
    assert float(m["resid"][6]) == pytest.approx(2.906263828277588, rel=1e-6)
    r.close()


# ---- collision_pass / worldmap_pass ----------------------------------------------------------------------------------------------


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(recordings, "get_recording", lambda i: REC if i == "rec1" else None)
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    d = tmp_path / "runs" / RUN
    d.mkdir(parents=True)
    (d / "run.json").write_text(
        json.dumps({"id": RUN, "request": {"recording": "rec1"}, "status": "done", "classNames": ["a"], "createdAt": "2026-11-03T10:00:00Z"})
    )
    np.savez(d / "grids.npz", grids=np.zeros((3, 135, 240), np.uint8), t=np.arange(3.0), index=np.arange(3))
    return d


class _Job:
    def __init__(self, cid: str) -> None:
        self.cid = cid
        self.reported: list[float] = []

    def report(self, fraction: float) -> None:
        self.reported.append(fraction)


def test_collision_pass_calls_the_patched_engine_entry_points(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import collision
    import worldmap

    calls: list[str] = []
    seen: list[tuple[Any, ...]] = []
    real_run, real_settings = collision.run_collision, collision.resolve_settings
    real_cload, real_wload = collision.load_config, worldmap.load_config

    def run(grids: Any, times: Any, names: Any, config: Any, settings: Any, *a: Any, **k: Any) -> Any:
        seen.append((grids.shape, grids.dtype.str, times.tolist(), names, len(a), sorted(k)))
        return real_run(grids, times, names, config, settings, *a, **k)

    def resolve(*a: Any, **k: Any) -> Any:
        calls.append("resolve_settings")
        return real_settings(*a, **k)

    def cload(*a: Any, **k: Any) -> Any:
        calls.append("collision.load_config")
        return real_cload(*a, **k)

    def wload(*a: Any, **k: Any) -> Any:
        calls.append("worldmap.load_config")
        return real_wload(*a, **k)

    monkeypatch.setattr(collision, "run_collision", run)
    monkeypatch.setattr(collision, "resolve_settings", resolve)
    monkeypatch.setattr(collision, "load_config", cload)
    monkeypatch.setattr(worldmap, "load_config", wload)
    doc = analysis.collision_pass(RUN, {}, "")
    assert seen == [((3, 135, 240), "|u1", [0.0, 1.0, 2.0], ["a"], 1, ["depth", "sounds", "worldmap_config"])]
    # legacy order: ['collision.load_config', 'worldmap.load_config', 'collision.load_config', 'collision.load_config', 'resolve_settings',
    # 'collision.load_config']; the later load_config calls come from code that does not move (recordings / collisions)
    assert calls[:2] == ["collision.load_config", "worldmap.load_config"] and calls.count("worldmap.load_config") == 1
    assert calls.count("resolve_settings") == 1 and calls.index("resolve_settings") > 1
    assert doc is not None and doc["id"] == "c1" and doc["status"] == "done" and doc["progress"] == 1.0 and doc["label"] == ""
    assert doc["counts"] == {"speech": 0, "beeps": 0} and doc["overrides"] == {} and doc["collisionVersion"] == "v26.2.14"
    assert analysis.get_run(RUN)["collisions"] == ["c1"]
    assert sorted(p.name for p in (lab / "collisions" / "c1").iterdir()) == ["collision.json", "events.json", "hazards.json"]


def test_collision_pass_with_a_job_reports_progress_and_leaves_the_document_running(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import collision

    real_run = collision.run_collision
    kwargs: list[list[str]] = []

    def run(grids: Any, times: Any, names: Any, config: Any, settings: Any, *a: Any, **k: Any) -> Any:
        kwargs.append(sorted(k))
        return real_run(grids, times, names, config, settings, *a, **k)

    monkeypatch.setattr(collision, "run_collision", run)
    job = _Job("c7")
    doc = analysis.collision_pass(RUN, {}, "", job=job)
    assert kwargs == [["depth", "progress", "sounds", "worldmap_config"]]
    assert job.reported == [0.0, 0.13333333333333333, 0.26666666666666666]
    assert doc is not None and doc["id"] == "c7" and doc["status"] == "running" and doc["progress"] == 0.4
    assert "collisions" not in analysis.get_run(RUN)  # the job registers the id, the pass does not
    assert sorted(p.name for p in (lab / "collisions" / "c7").iterdir()) == ["collision.json", "events.json", "hazards.json"]


def test_collision_pass_stops_when_the_job_is_cancelled(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _Job("c7")

    def report(fraction: float) -> None:
        raise analysis._Cancelled()

    job.report = report  # type: ignore[method-assign]
    with pytest.raises(analysis._Cancelled):
        analysis.collision_pass(RUN, {}, "", job=job)
    assert "collisions" not in analysis.get_run(RUN)


def test_collision_pass_without_a_job_removes_its_folder_on_failure(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import collision

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(collision, "run_collision", boom)
    with pytest.raises(RuntimeError, match="boom"):
        analysis.collision_pass(RUN, {}, "")
    assert not collisions.collision_dir(RUN, "c1").exists() and analysis.get_run(RUN).get("collisions") is None


def test_collision_pass_label_is_stored_and_clipped(lab: Path) -> None:
    doc = analysis.collision_pass(RUN, {}, "hello")
    assert doc is not None and doc["label"] == "hello" and doc["id"] == "c1"
    long = analysis.collision_pass(RUN, {}, "x" * 80)
    assert long is not None and long["id"] == "c2" and long["label"] == "x" * 60


def test_worldmap_pass_calls_the_patched_build(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import worldmap

    analysis.collision_pass(RUN, {}, "")
    seen: list[tuple[Any, ...]] = []
    real = worldmap.build

    def build(grids: Any, times: Any, names: Any, hazards: Any, ccfg: Any, cfg: Any, depth: Any, hook: Any = None) -> Any:
        seen.append((grids.shape, times.tolist(), names, depth, hook is None))
        return real(grids, times, names, hazards, ccfg, cfg, depth, hook=hook)

    monkeypatch.setattr(worldmap, "build", build)
    res = analysis.worldmap_pass(RUN, "c1")
    assert seen == [((3, 135, 240), [0.0, 1.0, 2.0], ["a"], None, True)]
    assert sorted(res) == ["elapsedSeconds", "frames", "msMean", "msP95", "version"] and res["frames"] == 3 and res["version"] == "v26.2.11"
    assert (lab / "collisions" / "c1" / "worldmap.npz").exists() and not (lab / "collisions" / "c1" / "worldmap.tmp.npz").exists()
    assert collisions.read_doc(RUN, "c1")["worldmapVersion"] == "v26.2.11"


def test_worldmap_pass_with_a_job_reports_the_second_part_of_the_progress(lab: Path) -> None:
    analysis.collision_pass(RUN, {}, "")
    job = _Job("c1")
    analysis.worldmap_pass(RUN, "c1", job=job)
    assert job.reported == [0.6, 0.8, 1.0]


def test_worldmap_pass_defaults_to_the_latest_and_checks_its_inputs(lab: Path) -> None:
    analysis.collision_pass(RUN, {}, "")
    assert analysis.worldmap_pass(RUN)["frames"] == 3
    with pytest.raises(collisions.CollisionError, match="Unknown collision run: c9"):
        analysis.worldmap_pass(RUN, "c9")
    (lab / "collisions" / "c1" / "hazards.json").unlink()
    with pytest.raises(FileNotFoundError, match="hazards.json"):
        analysis.worldmap_pass(RUN, "c1")


def test_build_worldmap_swallows_a_pass_failure(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def bad(run_id: str, cid: str | None = None, job: Any = None) -> None:
        raise RuntimeError("map broke")

    monkeypatch.setattr(analysis, "worldmap_pass", bad)
    analysis._build_worldmap(RUN, "c1")  # logged, not raised


def test_build_worldmap_calls_the_patched_worldmap_pass(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(analysis, "worldmap_pass", lambda run_id, cid=None, job=None: calls.append((run_id, cid)))
    analysis._build_worldmap(RUN, "c1")
    assert calls == [(RUN, "c1")]
