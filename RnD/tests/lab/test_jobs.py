"""Characterisation tests for lab.jobs (v26.3.0 p5-03): queue, worker, collision job, proxy globals, version watcher, JobContext.

Today every name lives on the flat modules (``analysis``, ``collisions``, ``recordings``, ``versioning``). After the move the flat modules
forward each moved name to its home (``lab.jobs.queue``, ``lab.jobs.worker``, ``lab.jobs.collision``, ``lab.jobs.proxy``,
``lab.jobs.versioning``); every assert here holds on both sides, and the literals come from the legacy code in the hackeye-rnd image.
The ``lab.jobs`` / ``lab.store`` modules are imported inside each test (they do not exist yet).
"""

from __future__ import annotations

import json
import queue
import threading
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from lab import analysis, collisions, recordings, versioning

RUN = "0123456789ab"
REC = {"id": "rec1", "duration": 100.0, "width": 320, "height": 180, "fps": 10.0, "chapters": [], "name": "rec1"}


class _Stop(BaseException):
    """Ends the worker loop once its one-job queue is drained."""


class _OneShot(queue.Queue):  # type: ignore[type-arg]
    """A job queue that serves what was put in it once, then ends the worker loop."""

    served = False

    def get(self, block: bool = True, timeout: float | None = None) -> Any:
        if self.served:
            raise _Stop
        item = super().get(block, timeout)
        self.served = True
        return item


@pytest.fixture
def clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    monkeypatch.setattr(analysis, "_cancel_flags", {})
    monkeypatch.setattr(analysis, "_jobs", queue.Queue())
    monkeypatch.setattr(analysis, "_busy", None)
    monkeypatch.setattr(analysis, "_maintenance", False)
    monkeypatch.setattr(analysis, "_ensure_worker", lambda: None)
    monkeypatch.setattr(collisions, "_job", None)
    return tmp_path


def _fake_request(monkeypatch: pytest.MonkeyPatch, rec: str, start: int) -> None:
    monkeypatch.setattr(
        analysis,
        "_normalise_request",
        lambda req: {"recording": rec, "start": start, "end": start + 10, "model": "m.pt", "profile": "default", "fps": 6.0},
    )
    monkeypatch.setattr(analysis, "_run_id", lambda r: f"{int(r['start']):012x}")


# ---- identity through the facades -----------------------------------------------------------------------------------------------


def test_queue_functions_are_the_analysis_names() -> None:
    from lab.jobs import queue as jq

    for name in (
        "submit_run",
        "cancel_run",
        "_finish_cancelled",
        "cancel_all",
        "is_idle",
        "analysis_active",
        "wait_idle",
        "release_model",
        "begin_maintenance",
        "end_maintenance",
    ):
        assert getattr(analysis, name) is getattr(jq, name), name


def test_queue_globals_are_the_analysis_globals() -> None:
    from lab.jobs import queue as jq

    for name in ("_jobs", "_cancel_flags", "_worker", "_cache", "_busy", "_maintenance"):
        assert getattr(analysis, name) is getattr(jq, name), name


def test_worker_functions_are_the_analysis_names() -> None:
    from lab.jobs import worker as jw

    for name in ("_ensure_worker", "_worker_loop", "_check_cancel", "_finish"):
        assert getattr(analysis, name) is getattr(jw, name), name


def test_collision_job_names_are_the_collisions_names() -> None:
    from lab.jobs import collision as jc

    for name in ("Job", "_job", "job_active", "cancel_job", "start_job", "_run_job"):
        assert getattr(collisions, name) is getattr(jc, name), name


def test_proxy_names_are_the_recordings_names() -> None:
    from lab.jobs import proxy as jp

    for name in ("_proxy_lock", "_building", "_build_proxy"):
        assert getattr(recordings, name) is getattr(jp, name), name


def test_version_watcher_and_policy_are_the_versioning_names() -> None:
    from lab.jobs import versioning as jv

    for name in ("VersionWatcher", "apply_version_policy"):
        assert getattr(versioning, name) is getattr(jv, name), name


def test_cancelled_is_the_store_type() -> None:
    from lab.store import errors

    assert analysis._Cancelled is errors._Cancelled


# ---- patched module globals reach the home modules ------------------------------------------------------------------------------


def test_patched_jobs_queue_is_the_one_submit_run_uses(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lab.jobs import queue as jq

    q: queue.Queue[str] = queue.Queue()
    monkeypatch.setattr(analysis, "_jobs", q)
    assert jq._jobs is q
    _fake_request(monkeypatch, "4929", 600)
    run = analysis.submit_run({})
    assert run["status"] == "queued" and run["id"] == "000000000258"
    assert q.qsize() == 1 and q.get_nowait() == "000000000258"
    assert analysis._active["000000000258"]["status"] == "queued"
    assert (clean / "runs" / "000000000258" / "run.json").exists()
    flag = analysis._cancel_flags["000000000258"]
    assert isinstance(flag, threading.Event) and not flag.is_set()


def test_submit_run_calls_the_patched_ensure_worker_once(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(analysis, "_ensure_worker", lambda: calls.append(1))
    _fake_request(monkeypatch, "4929", 600)
    analysis.submit_run({})
    assert calls == [1]


def test_patched_state_flags_are_seen_by_the_queue_functions(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert analysis.is_idle() is True
    monkeypatch.setattr(analysis, "_busy", "000000000001")
    assert analysis.is_idle() is False
    monkeypatch.setattr(analysis, "_busy", None)
    _fake_request(monkeypatch, "4929", 600)
    monkeypatch.setattr(analysis, "_maintenance", True)
    with pytest.raises(analysis.RunConflict, match="cleaning up for a new version"):
        analysis.submit_run({})
    monkeypatch.setattr(analysis, "_maintenance", False)
    assert analysis.submit_run({})["status"] == "queued"
    assert analysis.analysis_active() is True and analysis.is_idle() is False


def test_maintenance_flag_and_wait_idle(clean: Path) -> None:
    analysis.begin_maintenance()
    assert analysis._maintenance is True
    analysis.end_maintenance()
    assert analysis._maintenance is False
    assert analysis.wait_idle(0.05) is True
    analysis._busy = "000000000001"
    try:
        assert analysis.wait_idle(0.05) is False
    finally:
        analysis._busy = None


def test_begin_maintenance_cancels_what_is_in_flight(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_request(monkeypatch, "4929", 600)
    run = analysis.submit_run({})
    analysis.begin_maintenance()
    assert analysis.get_run(run["id"])["status"] == "cancelled"
    assert analysis._jobs.empty() and analysis._active == {} and analysis._maintenance is True
    analysis.end_maintenance()


def test_release_model_reaches_the_patched_cache(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    analysis.release_model()  # no cache yet: nothing happens
    released: list[int] = []
    monkeypatch.setattr(analysis, "_cache", types.SimpleNamespace(release=lambda: released.append(1)))
    analysis.release_model()
    assert released == [1]


def test_patched_collision_job_is_seen_by_job_active_and_cancel_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from lab.jobs import collision as jc

    assert collisions.job_active() is False and collisions.cancel_job() is False
    gate = threading.Event()
    job = collisions.Job(RUN, "c1")
    job.thread = threading.Thread(target=gate.wait, args=(10,), daemon=True)
    job.thread.start()
    try:
        monkeypatch.setattr(collisions, "_job", job)
        assert jc._job is job
        assert collisions.job_active() is True
        assert collisions.cancel_job(RUN, "c2") is False and not job.cancel.is_set()
        assert collisions.cancel_job(RUN, "c1") is True and job.cancel.is_set()
    finally:
        gate.set()
        job.thread.join(5)


# ---- the worker loop ------------------------------------------------------------------------------------------------------------


def _drive_worker(monkeypatch: pytest.MonkeyPatch, run_id_start: int, run_job: Any, cache: Any) -> str:
    """Submit one run and let a real `_worker_loop` thread take it from a one-job queue; returns the run id."""
    q = _OneShot()
    monkeypatch.setattr(analysis, "_jobs", q)
    monkeypatch.setattr(analysis, "_cache", cache)
    monkeypatch.setattr(analysis, "_run_job", run_job)
    _fake_request(monkeypatch, "4929", run_id_start)
    run = analysis.submit_run({})

    def loop() -> None:
        try:
            analysis._worker_loop()
        except _Stop:
            pass

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive()
    return str(run["id"])


def _cache(released: list[int]) -> Any:
    return types.SimpleNamespace(model=None, depth_model=None, last_used=0.0, release=lambda: released.append(1))


def test_worker_runs_a_job_and_clears_its_bookkeeping(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str | None]] = []

    def run_job(run_id: str, *args: Any) -> None:
        seen.append((run_id, analysis._busy))

    rid = _drive_worker(monkeypatch, 600, run_job, _cache([]))
    assert rid == "000000000258" and seen == [("000000000258", "000000000258")]
    assert analysis._busy is None and rid not in analysis._cancel_flags


def test_worker_marks_a_failed_job_as_error(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    released: list[int] = []

    def run_job(run_id: str, *args: Any) -> None:
        raise RuntimeError("boom")

    rid = _drive_worker(monkeypatch, 600, run_job, _cache(released))
    doc = analysis.get_run(rid)
    assert doc["status"] == "error" and doc["error"] == "boom" and doc["finishedAt"]
    assert rid not in analysis._active and released == []


def test_worker_releases_the_model_on_cuda_errors_and_memory_errors(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    released: list[int] = []

    def cuda(run_id: str, *args: Any) -> None:
        raise RuntimeError("CUDA out of memory")

    rid = _drive_worker(monkeypatch, 600, cuda, _cache(released))
    assert analysis.get_run(rid)["error"] == "CUDA out of memory" and released == [1]

    def mem(run_id: str, *args: Any) -> None:
        raise MemoryError

    rid = _drive_worker(monkeypatch, 700, mem, _cache(released))
    assert analysis.get_run(rid)["status"] == "error" and analysis.get_run(rid)["error"] == "MemoryError()" and released == [1, 1]


def test_worker_finishes_a_cancelled_job_and_drops_partial_outputs(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = analysis.run_dir("000000000258")

    def run_job(run_id: str, *args: Any) -> None:
        (out / "grids.npz").write_text("x")
        raise analysis._Cancelled()

    rid = _drive_worker(monkeypatch, 600, run_job, _cache([]))
    doc = analysis.get_run(rid)
    assert doc["status"] == "cancelled" and doc["error"] is None and doc["finishedAt"]
    assert not (out / "grids.npz").exists() and rid not in analysis._active


def test_ensure_worker_starts_one_daemon_thread_and_a_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = threading.Event()
    monkeypatch.setattr(analysis, "_worker", None)
    monkeypatch.setattr(analysis, "_cache", None)
    monkeypatch.setattr(analysis, "_worker_loop", lambda: stop.wait(10))
    try:
        analysis._ensure_worker()
        first = analysis._worker
        assert isinstance(first, threading.Thread) and first.name == "gpu-worker" and first.daemon and first.is_alive()
        assert isinstance(analysis._cache, analysis._ModelCache)
        cache = analysis._cache
        analysis._ensure_worker()
        assert analysis._worker is first and analysis._cache is cache
    finally:
        stop.set()
        if analysis._worker is not None:
            analysis._worker.join(5)


# ---- the collision re-run job ---------------------------------------------------------------------------------------------------


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(recordings, "get_recording", lambda i: REC if i == "rec1" else None)
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    monkeypatch.setattr(collisions, "_job", None)
    d = tmp_path / "runs" / RUN
    d.mkdir(parents=True)
    (d / "run.json").write_text(
        json.dumps({"id": RUN, "request": {"recording": "rec1"}, "status": "done", "classNames": ["a"], "createdAt": "2026-11-03T10:00:00Z"})
    )
    np.savez(d / "grids.npz", grids=np.zeros((3, 135, 240), np.uint8), t=np.arange(3.0), index=np.arange(3))
    return d


def _running_collision() -> tuple[Any, str]:
    cid = collisions.allocate(RUN)
    collisions.collision_dir(RUN, cid).mkdir(parents=True, exist_ok=True)
    collisions.write_doc(RUN, cid, {"id": cid, "runId": RUN, "status": "running", "progress": 0.4, "error": None, "label": ""})
    collisions.register(RUN, cid)
    return collisions.Job(RUN, cid), cid


def test_job_report_clamps_progress_and_raises_when_cancelled() -> None:
    job = collisions.Job(RUN, "c1")
    assert (job.run_id, job.cid, job.progress, job.thread) == (RUN, "c1", 0.0, None) and not job.cancel.is_set()
    job.report(0.5)
    assert job.progress == 0.5
    job.report(1.7)
    assert job.progress == 1.0
    job.report(-3)
    assert job.progress == 0.0
    job.cancel.set()
    with pytest.raises(analysis._Cancelled):
        job.report(0.9)
    assert job.progress == 0.0


def test_run_job_calls_the_patched_passes_then_marks_the_document_done(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job, cid = _running_collision()
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(analysis, "collision_pass", lambda run_id, overrides, label, job=None: calls.append(("collision", run_id, overrides, label, job)))
    monkeypatch.setattr(analysis, "worldmap_pass", lambda run_id, cid=None, job=None: calls.append(("worldmap", run_id, cid, job)))
    collisions._run_job(job, {"collision": {}}, "lbl")
    assert calls == [("collision", RUN, {"collision": {}}, "lbl", job), ("worldmap", RUN, "c1", job)]
    doc = collisions.read_doc(RUN, cid)
    assert doc["status"] == "done" and doc["progress"] == 1.0 and doc["error"] is None


def test_run_job_keeps_the_collision_when_the_map_refresh_fails(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job, cid = _running_collision()
    monkeypatch.setattr(analysis, "collision_pass", lambda run_id, overrides, label, job=None: None)

    def bad_map(run_id: str, cid: str | None = None, job: Any = None) -> None:
        raise RuntimeError("map broke")

    monkeypatch.setattr(analysis, "worldmap_pass", bad_map)
    collisions._run_job(job, {}, "")
    assert collisions.read_doc(RUN, cid)["status"] == "done"


def test_run_job_records_an_error_document(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job, cid = _running_collision()

    def bad_pass(run_id: str, overrides: Any, label: str, job: Any = None) -> None:
        raise RuntimeError("bad pass")

    monkeypatch.setattr(analysis, "collision_pass", bad_pass)
    collisions._run_job(job, {}, "")
    doc = collisions.read_doc(RUN, cid)
    assert doc["status"] == "error" and doc["error"] == "bad pass"


def test_run_job_cancelled_removes_the_directory_and_unregisters(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job, cid = _running_collision()
    assert analysis.get_run(RUN)["collisions"] == ["c1"]

    def cancelled(run_id: str, overrides: Any, label: str, job: Any = None) -> None:
        raise analysis._Cancelled()

    monkeypatch.setattr(analysis, "collision_pass", cancelled)
    collisions._run_job(job, {}, "")
    assert not collisions.collision_dir(RUN, cid).exists()
    run = analysis.get_run(RUN)
    assert run["collisions"] == [] and run["collisionSeq"] == 1


def test_start_job_runs_in_a_thread_and_finishes(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis, "collision_pass", lambda run_id, overrides, label, job=None: None)
    monkeypatch.setattr(analysis, "worldmap_pass", lambda run_id, cid=None, job=None: {})
    doc = collisions.start_job(RUN, {}, "lbl")
    assert doc["id"] == "c1" and doc["status"] == "running" and doc["label"] == "lbl" and doc["runId"] == RUN
    job = collisions._job
    assert job is not None and (job.run_id, job.cid) == (RUN, "c1") and job.thread is not None and job.thread.name == "collision-0123456789ab-c1"
    job.thread.join(10)
    assert collisions.job_active() is False
    assert collisions.read_doc(RUN, "c1")["status"] == "done"


def test_start_job_is_refused_while_a_job_or_an_analysis_runs(lab: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()
    monkeypatch.setattr(analysis, "collision_pass", lambda run_id, overrides, label, job=None: gate.wait(10))
    monkeypatch.setattr(analysis, "worldmap_pass", lambda run_id, cid=None, job=None: {})
    try:
        collisions.start_job(RUN, {}, "")
        with pytest.raises(collisions.CollisionError, match="already running") as exc:
            collisions.start_job(RUN, {}, "")
        assert exc.value.status == 409
    finally:
        gate.set()
        job = collisions._job
        assert job is not None and job.thread is not None
        job.thread.join(10)
    monkeypatch.setattr(analysis, "analysis_active", lambda: True)
    with pytest.raises(collisions.CollisionError, match="analysis is running") as exc2:
        collisions.start_job(RUN, {}, "")
    assert exc2.value.status == 409


# ---- the proxy builder globals --------------------------------------------------------------------------------------------------


def test_patched_building_dict_is_what_proxy_status_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    from lab.jobs import proxy as jp

    live = {"status": "building", "progress": 0.25, "error": None}
    monkeypatch.setattr(recordings, "_building", {"r1": live})
    assert jp._building == {"r1": live}
    got = recordings.proxy_status("r1")
    assert got == live and got is not live


def test_set_proxy_writes_through_the_shared_lock_and_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    monkeypatch.setattr(recordings, "_building", {})
    recordings._set_proxy("r2", progress=0.5)
    assert recordings._building == {"r2": {"status": "building", "progress": 0.5, "error": None}}
    assert recordings.proxy_status("r2") == {"status": "building", "progress": 0.5, "error": None}
    assert json.loads((tmp_path / "proxies" / "r2.json").read_text()) == {"status": "building", "progress": 0.5, "error": None}


# ---- version watcher with the analysis facade as its worker ---------------------------------------------------------------------


def test_version_watcher_drives_the_analysis_facade(clean: Path, tmp_path: Path) -> None:
    lab_dir = tmp_path / "labdir"
    (lab_dir / "runs" / "r1").mkdir(parents=True)
    (lab_dir / "reviews").mkdir()
    vf = tmp_path / "VERSION"
    vf.write_text("v1\n")
    versioning.apply_version_policy(lab_dir, vf)
    log: list[str] = []

    class Worker:
        def begin_maintenance(self) -> None:
            analysis.begin_maintenance()
            log.append(f"begin:{analysis._maintenance}")

        def wait_idle(self, t: float) -> bool:
            log.append("wait")
            return analysis.wait_idle(t)

        def release_model(self) -> None:
            analysis.release_model()
            log.append("release")

        def end_maintenance(self) -> None:
            analysis.end_maintenance()
            log.append(f"end:{analysis._maintenance}")

    watcher = versioning.VersionWatcher(lab_dir, vf, Worker(), idle_timeout=1.0)
    assert watcher.tick() is None and log == []
    vf.write_text("v2\n")
    res = watcher.tick()
    assert res is not None and res["wiped"] is True and res["runsRemoved"] == 1
    assert log == ["begin:True", "wait", "release", "end:False"]
    assert not (lab_dir / "runs" / "r1").exists()


# ---- JobContext ------------------------------------------------------------------------------------------------------------------


def _ctx(run_id: str, flag: threading.Event) -> Any:
    """The context the worker builds for one job: the cancel flag of the run and the worker's finish routine."""
    from lab.store.jobctx import JobContext

    return JobContext(run_id, is_cancelled=flag.is_set, finish=analysis._finish)


def test_check_cancel_raises_after_cancel_run_on_a_running_job(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_request(monkeypatch, "4929", 600)
    run = analysis.submit_run({})
    rid = run["id"]
    flag = analysis._cancel_flags[rid]
    analysis._jobs.get_nowait()  # the worker took it
    analysis._update_run(rid, status="running")
    ctx = _ctx(rid, flag)
    ctx.check_cancel()  # not cancelled yet: returns None
    doc = analysis.cancel_run(rid)
    assert doc["status"] == "running"  # a running job flips only when the worker sees the flag
    with pytest.raises(analysis._Cancelled):
        ctx.check_cancel()


def test_check_cancel_raises_after_cancel_run_on_a_queued_job(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_request(monkeypatch, "4929", 600)
    rid = analysis.submit_run({})["id"]
    flag = analysis._cancel_flags[rid]
    ctx = _ctx(rid, flag)
    ctx.check_cancel()
    assert analysis.cancel_run(rid)["status"] == "cancelled"
    with pytest.raises(analysis._Cancelled):
        ctx.check_cancel()


def test_progress_updates_the_run_doc(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_request(monkeypatch, "4929", 600)
    rid = analysis.submit_run({})["id"]
    ctx = _ctx(rid, analysis._cancel_flags[rid])
    ctx.progress(0.25)
    assert analysis.get_run(rid)["progress"] == 0.25
    ctx.progress(0.5)
    assert analysis._active[rid]["progress"] == 0.5 and analysis.get_run(rid)["progress"] == 0.5


def test_finish_writes_the_run_doc_and_drops_it_from_active(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_request(monkeypatch, "4929", 600)
    rid = analysis.submit_run({})["id"]
    ctx = _ctx(rid, analysis._cancel_flags[rid])
    ctx.finish(status="done", progress=1.0)
    on_disk = json.loads((clean / "runs" / rid / "run.json").read_text())
    assert on_disk["status"] == "done" and on_disk["progress"] == 1.0 and on_disk["finishedAt"]
    assert rid not in analysis._active
