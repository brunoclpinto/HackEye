"""Characterisation tests for lab.store (v26.3.0 p5-02): run docs, collision docs, request validation, forwarding.

Every literal below was printed by the legacy ``lab.analysis`` / ``lab.collisions`` / ``lab.recordings`` functions in
the hackeye-rnd image before the move (same inputs as the ``tmp_path`` scenarios of this file). The ``lab.store``
modules are imported inside each test (they do not exist yet). The flat modules must keep forwarding
every moved name to its home.
"""

from __future__ import annotations

import importlib
import json
import threading
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

R1 = "0123456789ab"
R2 = "ba9876543210"
R3 = "aaaaaaaaaaaa"

# (flat module, name, home module): reading ``flat.name`` must give the object of ``lab.store.<home>`` (audit 7.4, 7.5).
MOVED: list[tuple[str, str, str]] = (
    [
        ("analysis", n, "constants")
        for n in (
            "GRID_W",
            "NO_DATA",
            "ANALYSIS_VERSION",
            "PROFILES",
            "RESOLUTIONS",
            "IDLE_SECONDS",
            "RUN_ID_RE",
            "DEPTH_MODELS",
            "DEPTH_ANCHOR",
            "SUPERSEDED_ANCHORS",
            "DEPTH_W",
            "DEPTH_H",
            "DEPTH_MIN_REL",
            "DEPTH_MIN_M",
            "DEPTH_MAX_M",
            "DEFAULT_MODEL",
            "MODEL_DIRS",
        )
    ]
    + [("analysis", n, "errors") for n in ("RunError", "RunConflict", "_Cancelled")]
    + [("collisions", "CollisionError", "errors")]
    + [("analysis", n, "util") for n in ("_now", "_log", "_write_json")]
    + [("recordings", "_atomic_write_json", "util")]
    + [
        ("analysis", n, "runs")
        for n in (
            "LAB_DIR",
            "run_dir",
            "_state_lock",
            "_active",
            "get_run",
            "list_runs",
            "_update_run",
            "ACTIVE_STATUSES",
            "find_active_for_recording",
            "_conflict_message",
            "_remove_partial_outputs",
        )
    ]
    + [
        ("analysis", n, "requests")
        for n in (
            "_normalise_request",
            "request_side",
            "run_window",
            "DEVICES",
            "_parse_device",
            "_cpu_threads",
            "_run_id",
        )
    ]
    + [("analysis", "list_models", "models")]
    + [
        ("collisions", n, "collision_docs")
        for n in (
            "CID_RE",
            "MAX_LABEL",
            "MATCH_WINDOW_S",
            "FILES",
            "_lock",
            "collisions_root",
            "collision_dir",
            "ids",
            "latest",
            "resolve",
            "read_doc",
            "_add_effective",
            "list_docs",
            "write_doc",
            "update_doc",
            "allocate",
            "register",
            "set_label",
            "delete",
        )
    ]
    + [
        ("recordings", n, "recordings")
        for n in (
            "LAB_DIR",
            "_info_cache",
            "scan_recordings",
            "get_recording",
            "list_recordings",
            "get_settings",
            "save_settings",
            "sensors_path",
        )
    ]
)


@pytest.mark.parametrize(("flat", "name", "home"), MOVED)
def test_flat_name_is_the_home_object(flat: str, name: str, home: str) -> None:
    flat_mod = importlib.import_module(f"lab.{flat}")
    home_mod = importlib.import_module(f"lab.store.{home}")
    assert getattr(flat_mod, name) is getattr(home_mod, name)


def test_shared_state_objects_have_the_expected_types() -> None:
    from lab.store import collision_docs, recordings, runs

    assert isinstance(runs._active, dict)
    assert isinstance(runs._state_lock, type(threading.Lock()))
    assert isinstance(collision_docs._lock, type(threading.RLock()))
    assert isinstance(recordings._info_cache, dict)
    assert runs.ACTIVE_STATUSES == ("queued", "running")


def test_constants_values() -> None:
    from lab.store import constants

    assert constants.GRID_W == 240
    assert constants.NO_DATA == 255
    assert constants.ANALYSIS_VERSION == 3
    assert constants.PROFILES == ["default", "production", "half", "quarter"]
    assert constants.RESOLUTIONS == ["544p", "576p", "608p", "640p", "672p", "704p", "736p"]
    assert constants.DEPTH_MODELS == ("none", "da3-small", "da3-base", "da2-metric-outdoor-small", "unidepth-v2-s")
    assert constants.DEPTH_ANCHOR == {
        "da3-small": "per-frame",
        "da3-base": "per-frame",
        "da2-metric-outdoor-small": "plane",
        "unidepth-v2-s": "none",
    }
    assert {"da2-metric-outdoor-small": {"initial"}} == constants.SUPERSEDED_ANCHORS
    assert (constants.DEPTH_W, constants.DEPTH_H) == (120, 68)
    assert constants.DEPTH_MIN_REL == 0.001
    assert (constants.DEPTH_MIN_M, constants.DEPTH_MAX_M) == (0.1, 200.0)
    assert constants.RUN_ID_RE.match("0123456789ab") is not None
    assert constants.RUN_ID_RE.match("0123456789AB") is None
    assert constants.RUN_ID_RE.match("0123") is None


def test_error_types() -> None:
    from lab.store import errors

    assert issubclass(errors.RunError, ValueError)
    assert issubclass(errors.RunConflict, errors.RunError)
    assert issubclass(errors._Cancelled, Exception)
    assert not issubclass(errors._Cancelled, errors.RunError)
    exc = errors.CollisionError(404, "Unknown collision run: c1")
    assert (exc.status, exc.message, str(exc)) == (404, "Unknown collision run: c1", "Unknown collision run: c1")


def test_util_writers(tmp_path: Path) -> None:
    from lab.store import util

    util._write_json(tmp_path / "b.json", {"b": [1]})
    assert (tmp_path / "b.json").read_text() == '{"b": [1]}'
    with pytest.raises(FileNotFoundError):  # _write_json never creates parent directories
        util._write_json(tmp_path / "missing" / "b.json", {"b": 1})
    util._atomic_write_json(tmp_path / "sub" / "a.json", {"a": 1})  # ... _atomic_write_json does
    assert (tmp_path / "sub" / "a.json").read_text() == '{"a": 1}'
    assert sorted(p.name for p in (tmp_path / "sub").iterdir()) == ["a.json"]  # no .tmp left behind
    assert util._now().endswith("Z")
    assert len(util._now()) == 20


# --------------------------------------------------------------------------
# LAB_DIR names stay independent
# --------------------------------------------------------------------------


def test_lab_dir_names_start_equal() -> None:
    from lab import reviews
    from lab.store import recordings, runs

    assert runs.LAB_DIR == recordings.LAB_DIR == reviews.LAB_DIR


def test_patching_analysis_lab_dir_leaves_the_other_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lab import analysis, recordings, reviews
    from lab.store import recordings as store_recordings
    from lab.store import runs

    before = (recordings.LAB_DIR, reviews.LAB_DIR)
    monkeypatch.setattr(analysis, "LAB_DIR", tmp_path)
    assert tmp_path == runs.LAB_DIR
    assert tmp_path == analysis.LAB_DIR
    assert before == (recordings.LAB_DIR, reviews.LAB_DIR)
    assert before[0] == store_recordings.LAB_DIR


def test_patching_recordings_lab_dir_leaves_the_other_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lab import analysis, recordings, reviews
    from lab.store import recordings as store_recordings
    from lab.store import runs

    before = (analysis.LAB_DIR, reviews.LAB_DIR)
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    assert tmp_path == store_recordings.LAB_DIR
    assert tmp_path == recordings.LAB_DIR
    assert before == (analysis.LAB_DIR, reviews.LAB_DIR)
    assert before[0] == runs.LAB_DIR


def test_patching_reviews_lab_dir_leaves_the_other_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lab import analysis, recordings, reviews
    from lab.store import recordings as store_recordings
    from lab.store import runs

    before = (analysis.LAB_DIR, recordings.LAB_DIR)
    monkeypatch.setattr(reviews, "LAB_DIR", tmp_path)
    assert tmp_path == reviews.LAB_DIR
    assert before == (analysis.LAB_DIR, recordings.LAB_DIR)
    assert before[0] == runs.LAB_DIR
    assert before[1] == store_recordings.LAB_DIR


def test_patches_on_the_flat_module_reach_the_home_and_undo(monkeypatch: pytest.MonkeyPatch) -> None:
    from lab import analysis, collisions
    from lab.store import collision_docs, runs

    live: dict[str, dict[str, Any]] = {}
    old_active = runs._active
    monkeypatch.setattr(analysis, "_active", live)
    assert runs._active is live
    monkeypatch.setattr(analysis, "get_run", lambda run_id: {"id": run_id})
    assert runs.get_run("x") == {"id": "x"}
    lock = threading.RLock()
    monkeypatch.setattr(collisions, "_lock", lock)
    assert collision_docs._lock is lock
    monkeypatch.undo()
    assert runs._active is old_active
    assert analysis._active is old_active


# --------------------------------------------------------------------------
# Run docs on a tmp LAB_DIR
# --------------------------------------------------------------------------


@pytest.fixture
def lab_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from lab.store import recordings, runs

    monkeypatch.setattr(runs, "LAB_DIR", tmp_path)
    monkeypatch.setattr(runs, "_active", {})
    monkeypatch.setattr(recordings, "LAB_DIR", tmp_path)
    return tmp_path


def _make_runs(root: Path) -> None:
    from lab.store import runs, util

    for rid, rec, ts in (
        (R1, "rec1", "2026-10-31T10:00:00Z"),
        (R2, "rec2", "2026-11-01T10:00:00Z"),
        (R3, "rec1", "2026-11-02T10:00:00Z"),
    ):
        d = runs.run_dir(rid)
        d.mkdir(parents=True)
        util._write_json(d / "run.json", {"id": rid, "request": {"recording": rec}, "status": "done", "createdAt": ts})
    (root / "runs" / "notarun").mkdir()


def test_run_dir(lab_dir: Path) -> None:
    from lab.store import runs

    assert runs.run_dir(R1) == lab_dir / "runs" / R1


def test_get_run_and_update_run_round_trip(lab_dir: Path) -> None:
    from lab.store import runs

    _make_runs(lab_dir)
    assert runs.get_run(R1) == {
        "id": "0123456789ab",
        "request": {"recording": "rec1"},
        "status": "done",
        "createdAt": "2026-10-31T10:00:00Z",
    }
    assert runs.get_run("ffffffffffff") is None
    expected = {
        "id": "0123456789ab",
        "request": {"recording": "rec1"},
        "status": "error",
        "createdAt": "2026-10-31T10:00:00Z",
        "progress": 0.5,
    }
    assert runs._update_run(R1, status="error", progress=0.5) == expected
    assert runs.get_run(R1) == expected
    assert json.loads((runs.run_dir(R1) / "run.json").read_text()) == expected


def test_update_run_without_persist_leaves_the_file(lab_dir: Path) -> None:
    from lab.store import runs

    _make_runs(lab_dir)
    snap = runs._update_run(R2, persist=False, status="x")
    assert snap == {
        "id": "ba9876543210",
        "request": {"recording": "rec2"},
        "status": "x",
        "createdAt": "2026-11-01T10:00:00Z",
    }
    assert json.loads((runs.run_dir(R2) / "run.json").read_text()) == {
        "id": "ba9876543210",
        "request": {"recording": "rec2"},
        "status": "done",
        "createdAt": "2026-11-01T10:00:00Z",
    }


def test_list_runs_sorts_newest_first_and_filters(lab_dir: Path) -> None:
    from lab.store import runs

    _make_runs(lab_dir)
    assert [r["id"] for r in runs.list_runs(None)] == ["aaaaaaaaaaaa", "ba9876543210", "0123456789ab"]
    assert [r["id"] for r in runs.list_runs("rec1")] == ["aaaaaaaaaaaa", "0123456789ab"]
    assert runs.list_runs("nope") == []


def test_active_registry_wins_over_disk_and_is_updated_in_place(lab_dir: Path) -> None:
    from lab.store import runs

    _make_runs(lab_dir)
    runs._active[R3] = {
        "id": R3,
        "request": {"recording": "rec1"},
        "status": "running",
        "createdAt": "2026-11-02T10:00:00Z",
    }
    assert runs.get_run(R3) is not None
    assert (runs.get_run(R3) or {})["status"] == "running"
    runs._update_run(R3, progress=0.25)
    assert runs._active[R3] == {
        "id": "aaaaaaaaaaaa",
        "request": {"recording": "rec1"},
        "status": "running",
        "createdAt": "2026-11-02T10:00:00Z",
        "progress": 0.25,
    }
    assert json.loads((runs.run_dir(R3) / "run.json").read_text())["status"] == "running"
    copy = runs.get_run(R3) or {}
    copy["status"] = "zzz"  # get_run returns a copy of the live doc
    assert runs._active[R3]["status"] == "running"


def test_find_active_and_conflict_message() -> None:
    from lab.store import runs

    act = {
        "a": {"id": "a", "request": {"recording": "4929"}, "status": "running"},
        "b": {"id": "b", "request": {"recording": "5000"}, "status": "queued"},
    }
    assert runs.find_active_for_recording(act, "5000") == {
        "id": "b",
        "request": {"recording": "5000"},
        "status": "queued",
    }
    assert runs.find_active_for_recording(act, "9999") is None
    assert runs._conflict_message(act["a"]) == "Analysis already running for 4929 (run a, 0%)"
    assert runs._conflict_message(act["b"]) == "Analysis already running for 5000 (run b, 0%)"


def test_remove_partial_outputs(lab_dir: Path) -> None:
    from lab.store import runs

    _make_runs(lab_dir)
    d = runs.run_dir(R1)
    (d / "masks").mkdir()
    (d / "masks" / "0.png").write_text("x")
    (d / "collisions" / "c1").mkdir(parents=True)
    for name in ("grids.npz", "motion.npz", "depth.npz", "keep.txt"):
        (d / name).write_text("x")
    runs._remove_partial_outputs(R1)
    assert sorted(p.name for p in d.iterdir()) == ["keep.txt", "run.json"]
    runs._remove_partial_outputs(R1)  # a second call finds nothing and is quiet


# --------------------------------------------------------------------------
# Collision docs
# --------------------------------------------------------------------------


def test_collision_constants() -> None:
    from lab.store import collision_docs

    assert collision_docs.CID_RE.match("c1") is not None
    assert collision_docs.CID_RE.match("c0") is None
    assert collision_docs.MAX_LABEL == 60
    assert collision_docs.MATCH_WINDOW_S == 1.0
    assert collision_docs.FILES == ("hazards.json", "events.json", "worldmap.npz", "collision.json")


def _collision_run(root: Path) -> None:
    from lab.store import runs, util

    d = runs.run_dir(R1)
    d.mkdir(parents=True)
    util._write_json(d / "run.json", {"id": R1, "request": {"recording": "rec1"}, "status": "done", "createdAt": "x"})


def test_collision_paths_and_empty_run(lab_dir: Path) -> None:
    from lab.store import collision_docs, errors, runs

    _collision_run(lab_dir)
    assert collision_docs.collisions_root(R1) == lab_dir / "runs" / R1 / "collisions"
    assert collision_docs.collision_dir(R1, "c1") == lab_dir / "runs" / R1 / "collisions" / "c1"
    run = runs.get_run(R1) or {}
    assert collision_docs.ids(run) == []
    assert collision_docs.latest(run) is None
    with pytest.raises(errors.CollisionError) as e1:
        collision_docs.resolve(run, None)
    assert (e1.value.status, e1.value.message) == (404, "This run has no collision run")
    with pytest.raises(errors.CollisionError) as e2:
        collision_docs.resolve(run, "c1")
    assert (e2.value.status, e2.value.message) == (404, "Unknown collision run: c1")


def test_collision_doc_round_trip(lab_dir: Path) -> None:
    from lab.store import collision_docs as cd
    from lab.store import runs

    _collision_run(lab_dir)
    assert cd.allocate(R1) == "c1"
    assert cd.allocate(R1) == "c2"
    assert (runs.get_run(R1) or {})["collisionSeq"] == 2
    cd.collision_dir(R1, "c1").mkdir(parents=True)
    cd.collision_dir(R1, "c2").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):  # the directory must exist
        cd.write_doc(R1, "c3", {"id": "c3"})
    cd.write_doc(R1, "c1", {"id": "c1", "status": "done", "label": "", "settings": {}})
    cd.write_doc(
        R1,
        "c2",
        {
            "id": "c2",
            "status": "error",
            "label": "b",
            "settings": {"objectDistance": "ground", "useHorizon": False},
            "resolved": {},
        },
    )
    cd.register(R1, "c1")
    cd.register(R1, "c2")
    cd.register(R1, "c2")  # idempotent
    run = runs.get_run(R1) or {}
    assert run == {
        "id": "0123456789ab",
        "request": {"recording": "rec1"},
        "status": "done",
        "createdAt": "x",
        "collisionSeq": 2,
        "collisions": ["c1", "c2"],
    }
    assert cd.ids(run) == ["c1", "c2"]
    assert cd.latest(run) == "c1"  # c2 is an error doc: the newest usable one wins
    assert cd.resolve(run, None) == "c1"
    assert cd.resolve(run, "c2") == "c2"
    assert cd.read_doc(R1, "c1") == {"id": "c1", "status": "done", "label": "", "settings": {}}
    assert cd.read_doc(R1, "c2") == {
        "id": "c2",
        "status": "error",
        "label": "b",
        "settings": {"objectDistance": "ground", "useHorizon": False},
        "resolved": {"objectDistanceEffective": "depth"},
        "objectDistanceEffective": "depth",
    }
    assert cd.read_doc(R1, "c9") is None
    assert [d["id"] for d in cd.list_docs(R1)] == ["c1", "c2"]


def test_collision_doc_update_label_and_delete(lab_dir: Path) -> None:
    from lab.store import collision_docs as cd
    from lab.store import errors, runs

    _collision_run(lab_dir)
    for _ in range(2):
        cid = cd.allocate(R1)
        cd.collision_dir(R1, cid).mkdir(parents=True)
        cd.write_doc(R1, cid, {"id": cid, "status": "done" if cid == "c1" else "error", "label": "", "settings": {}})
        cd.register(R1, cid)
    assert cd.update_doc(R1, "c1", label="x", n=3) == {
        "id": "c1",
        "status": "done",
        "label": "x",
        "settings": {},
        "n": 3,
    }
    assert cd.update_doc(R1, "c9", label="x") is None
    assert cd.set_label(R1, "c1", "  hello  ") == {
        "id": "c1",
        "status": "done",
        "label": "hello",
        "settings": {},
        "n": 3,
    }
    with pytest.raises(errors.CollisionError, match="label must be a string") as e1:
        cd.set_label(R1, "c1", 5)
    assert e1.value.status == 422
    with pytest.raises(errors.CollisionError, match="label must be at most 60 characters") as e2:
        cd.set_label(R1, "c1", "x" * 61)
    assert e2.value.status == 422
    with pytest.raises(errors.CollisionError, match="Unknown collision run: c7") as e3:
        cd.set_label(R1, "c7", "a")
    assert e3.value.status == 404
    cd.delete(R1, "c2", 0)
    assert (runs.get_run(R1) or {})["collisions"] == ["c1"]
    assert not cd.collision_dir(R1, "c2").exists()
    with pytest.raises(
        errors.CollisionError, match="c1 is the only collision run of this run; it cannot be deleted"
    ) as e4:
        cd.delete(R1, "c1", 0)
    assert e4.value.status == 409


# --------------------------------------------------------------------------
# Request validation (6+ requests from test_lab_depth / test_lab_resolution / test_orientation)
# --------------------------------------------------------------------------

RECS: dict[str, dict[str, Any]] = {
    "rec1": {"id": "rec1", "duration": 100.0, "width": 320, "height": 180, "fps": 10.0, "chapters": [], "name": "rec1"},
    "r4k": {"id": "r4k", "duration": 100.0, "width": 3840, "height": 2160, "fps": 24.0, "chapters": [], "name": "r4k"},
    "rsm": {"id": "rsm", "duration": 100.0, "width": 960, "height": 540, "fps": 24.0, "chapters": [], "name": "rsm"},
    "Chest-center-0004": {
        "id": "Chest-center-0004",
        "duration": 100.0,
        "width": 2704,
        "height": 1520,
        "fps": 24.0,
        "chapters": [],
        "name": "x",
    },
}


@pytest.fixture
def req_env(lab_dir: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    from lab import analysis, recordings

    model = lab_dir / "m.pt"
    model.write_bytes(b"x")
    monkeypatch.setattr(recordings, "get_recording", lambda i: RECS.get(i))
    monkeypatch.setattr(analysis, "list_models", lambda: [{"path": str(model), "name": "m", "default": True}])
    return str(model)


def _req(model: str, **extra: Any) -> dict[str, Any]:
    return {"start": 0, "end": 10, "fps": 6, "model": model, **extra}


def test_normalise_plain_and_depth(req_env: str) -> None:
    from lab.store import requests

    plain = {"recording": "rec1", "start": 0.0, "end": 10.0, "model": req_env, "profile": "default", "fps": 6.0}
    assert requests._normalise_request(_req(req_env, recording="rec1")) == plain
    assert requests._normalise_request(_req(req_env, recording="rec1", depth="none")) == plain
    assert requests._normalise_request(_req(req_env, recording="rec1", depth="da3-small")) == {
        **plain,
        "depth": "da3-small",
    }


def test_normalise_clamps_end_to_the_recording(req_env: str) -> None:
    from lab.store import requests

    got = requests._normalise_request(_req(req_env, recording="rec1", end=500))
    assert got == {"recording": "rec1", "start": 0.0, "end": 100.0, "model": req_env, "profile": "default", "fps": 6.0}


def test_normalise_resolution_profiles(req_env: str) -> None:
    from lab.store import errors, requests

    assert requests._normalise_request(_req(req_env, recording="r4k", profile="576p")) == {
        "recording": "r4k",
        "start": 0.0,
        "end": 10.0,
        "model": req_env,
        "profile": "576p",
        "fps": 6.0,
    }
    with pytest.raises(errors.RunError) as up:
        requests._normalise_request(_req(req_env, recording="rsm", profile="576p"))
    assert str(up.value) == (
        "576p would upscale a 960x540 source "
        "(the largest native-aspect input without upscaling has a short side of 544)"
    )
    with pytest.raises(errors.RunError) as bad:
        requests._normalise_request(_req(req_env, recording="r4k", profile="500p"))
    assert str(bad.value) == (
        "profile must be one of ['544p', '576p', '608p', '640p', '672p', '704p', '736p', "
        "'default', 'production', 'half', 'quarter']"
    )


def test_normalise_orientation_and_side(req_env: str) -> None:
    from lab.store import errors, requests

    base = _req(req_env, recording="Chest-center-0004", profile="736p", depth="da2-metric-outdoor-small")
    land = {
        "recording": "Chest-center-0004",
        "start": 0.0,
        "end": 10.0,
        "model": req_env,
        "profile": "736p",
        "fps": 6.0,
        "depth": "da2-metric-outdoor-small",
    }
    assert requests._normalise_request({**base, "orientation": "landscape", "side": "left"}) == land
    assert requests._normalise_request({**base, "orientation": "portrait", "side": "left"}) == {
        **land,
        "orientation": "portrait",
        "side": "left",
    }
    with pytest.raises(errors.RunError) as side:
        requests._normalise_request({**base, "orientation": "portrait", "side": "up"})
    assert str(side.value) == "side must be one of ['left', 'center', 'right']"
    with pytest.raises(errors.RunError) as ori:
        requests._normalise_request(_req(req_env, recording="rec1", orientation="diag"))
    assert str(ori.value) == "orientation must be one of ['landscape', 'portrait']"


def test_normalise_errors(req_env: str) -> None:
    from lab.store import errors, requests

    cases: list[tuple[dict[str, Any], str]] = [
        (
            _req(req_env, recording="rec1", depth="midas"),
            "depth must be one of ['none', 'da3-small', 'da3-base', 'da2-metric-outdoor-small', 'unidepth-v2-s']",
        ),
        (_req(req_env, recording="rec1", start=20, end=10), "Range must satisfy 0 <= start < end <= 100.0"),
        (_req(req_env, recording="rec1", fps=61), "fps must be in (0, 60]"),
        (_req(req_env, recording="nope"), "Unknown recording: 'nope'"),
        (_req(req_env, recording="rec1", start="a"), "start, end and fps must be numbers"),
        ({**_req(req_env, recording="rec1"), "model": "zzz"}, "Unknown model: 'zzz'"),
    ]
    for body, message in cases:
        with pytest.raises(errors.RunError) as exc:
            requests._normalise_request(body)
        assert str(exc.value) == message


def test_run_id_is_stable_twelve_hex_and_depth_sensitive(req_env: str) -> None:
    from lab.store import constants, requests

    plain = requests._normalise_request(_req(req_env, recording="rec1"))
    deep = requests._normalise_request(_req(req_env, recording="rec1", depth="da3-small"))
    a, b = requests._run_id(plain), requests._run_id(deep)
    assert a == requests._run_id(dict(plain))
    assert a != b
    assert constants.RUN_ID_RE.match(a) is not None
    assert constants.RUN_ID_RE.match(b) is not None


def test_device_and_window_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    from lab.store import errors, requests

    monkeypatch.delenv("HACKEYE_LAB_DEFAULT_DEVICE", raising=False)
    assert requests.DEVICES == ["gpu", "cpu"]
    assert requests._parse_device({}) == "gpu"
    assert requests._parse_device({"device": "cpu"}) == "cpu"
    with pytest.raises(errors.RunError) as exc:
        requests._parse_device({"device": "tpu"})
    assert str(exc.value) == "device must be one of ['gpu', 'cpu']"
    monkeypatch.setenv("HACKEYE_LAB_CPU_THREADS", "3")
    assert requests._cpu_threads() == 3


def test_request_side_and_run_window(req_env: str) -> None:
    from lab.store import requests

    assert req_env
    assert requests.request_side({"side": "left"}, RECS["rec1"]) == "left"
    assert requests.request_side({}, RECS["rec1"]) == "center"
    chest = RECS["Chest-center-0004"]
    assert requests.run_window(chest, {"orientation": "portrait", "side": "left"}) == {
        "x0": 0,
        "y0": 0,
        "w": 855,
        "h": 1520,
    }
    assert requests.run_window(chest, {}) == {"x0": 0, "y0": 0, "w": 2704, "h": 1520}


# --------------------------------------------------------------------------
# Recordings (store part): settings, sensors path
# --------------------------------------------------------------------------


def test_settings_round_trip_and_sensors_path(lab_dir: Path) -> None:
    from lab.store import recordings

    assert recordings.sensors_path("recX") == lab_dir / "sensors" / "recX.npz"
    defaults = recordings.get_settings("recX", "chest")
    assert defaults["mount"] == "chest"
    assert defaults["projection"] == "auto"
    assert defaults["distanceSource"] == "depth"
    assert defaults["cameraSide"] == "center"
    assert defaults["orientation"] == "landscape"
    assert defaults["hfovDeg"] is None
    recordings.save_settings("recX", {"mount": "head", "cameraSide": "left", "bogus": 1})
    assert (lab_dir / "recordings" / "recX.json").read_text() == '{"mount": "head", "cameraSide": "left", "bogus": 1}'
    saved = recordings.get_settings("recX", "chest")
    assert saved["mount"] == "head"
    assert saved["cameraSide"] == "left"
    assert "bogus" not in saved
    assert set(saved) == set(defaults)
