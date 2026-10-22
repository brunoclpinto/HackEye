import json
import os

import pytest

from lab import versioning as V


@pytest.fixture
def env(tmp_path):
    lab = tmp_path / "lab"
    for d in ("runs", "reviews", "proxies", "recordings", ".ultralytics"):
        (lab / d).mkdir(parents=True)
    (lab / "runs" / "abc").mkdir()
    (lab / "runs" / "abc" / "f.json").write_text("{}")
    (lab / "runs" / "def").mkdir()
    (lab / "reviews" / "r1.json").write_text("{}")
    (lab / "proxies" / "p.mp4").write_text("x")
    (lab / "recordings" / "r1.json").write_text("{}")
    (lab / ".ultralytics" / "s.json").write_text("{}")
    vf = tmp_path / "VERSION"
    vf.write_text("v1.0.0\n")
    return lab, vf


def _kept(lab):
    return all((lab / p).exists() for p in ("proxies/p.mp4", "recordings/r1.json", ".ultralytics/s.json"))


def test_first_adoption_writes_marker_no_wipe(env):
    lab, vf = env
    r = V.apply_version_policy(lab, vf)
    assert r == {"previous": None, "current": "v1.0.0", "wiped": False,
                 "runsRemoved": 0, "reviewFilesRemoved": 0}
    assert json.loads((lab / ".lab-version").read_text())["version"] == "v1.0.0"
    assert (lab / "runs" / "abc" / "f.json").exists() and (lab / "reviews" / "r1.json").exists()


def test_same_version_noop(env):
    lab, vf = env
    V.apply_version_policy(lab, vf)
    r = V.apply_version_policy(lab, vf)
    assert not r["wiped"] and r["previous"] == "v1.0.0"
    assert (lab / "runs" / "abc").exists()


def test_changed_version_wipes_runs_and_reviews_only(env):
    lab, vf = env
    V.apply_version_policy(lab, vf)
    vf.write_text("v1.0.1\n")
    r = V.apply_version_policy(lab, vf)
    assert r["wiped"] and r["previous"] == "v1.0.0" and r["current"] == "v1.0.1"
    assert r["runsRemoved"] == 2 and r["reviewFilesRemoved"] == 1
    assert (lab / "runs").is_dir() and list((lab / "runs").iterdir()) == []
    assert (lab / "reviews").is_dir() and list((lab / "reviews").iterdir()) == []
    assert _kept(lab)
    assert json.loads((lab / ".lab-version").read_text())["version"] == "v1.0.1"


@pytest.mark.parametrize("content", [None, "", "\n  \n"])
def test_missing_or_empty_version_no_wipe(env, content):
    lab, vf = env
    (lab / ".lab-version").write_text(json.dumps({"version": "old", "since": "x"}))
    if content is None:
        vf.unlink()
    else:
        vf.write_text(content)
    r = V.apply_version_policy(lab, vf)
    assert not r["wiped"] and r["current"] is None
    assert (lab / "runs" / "abc").exists() and (lab / "reviews" / "r1.json").exists()
    assert json.loads((lab / ".lab-version").read_text())["version"] == "old"


def test_corrupt_marker_no_wipe(env):
    lab, vf = env
    (lab / ".lab-version").write_text("not json")
    assert not V.apply_version_policy(lab, vf)["wiped"]
    assert (lab / "runs" / "abc").exists()


def test_symlinks_removed_not_followed(env, tmp_path):
    lab, vf = env
    V.apply_version_policy(lab, vf)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("precious")
    os.symlink(outside, lab / "runs" / "dirlink")
    os.symlink(outside / "keep.txt", lab / "reviews" / "filelink")
    (lab / "runs" / "abc" / "inner").symlink_to(outside)
    vf.write_text("v2\n")
    r = V.apply_version_policy(lab, vf)
    assert r["wiped"]
    assert (outside / "keep.txt").read_text() == "precious"
    assert not os.path.lexists(lab / "runs" / "dirlink")
    assert not os.path.lexists(lab / "reviews" / "filelink")


def test_symlinked_runs_dir_is_refused(env, tmp_path):
    lab, vf = env
    V.apply_version_policy(lab, vf)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    import shutil
    shutil.rmtree(lab / "runs")
    os.symlink(outside, lab / "runs")
    vf.write_text("v2\n")
    V.apply_version_policy(lab, vf)
    assert (outside / "keep.txt").exists()
