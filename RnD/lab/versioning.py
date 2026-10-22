"""Version-scoped Lab content (CONTRACTS section 11).

The rule: each new HackEye version cleans up the previous version's Lab
content so it starts fresh. `RnD/VERSION` holds the current version; the
marker `LAB_DIR/.lab-version` records which version last owned the content.
At startup `apply_version_policy` compares the two:

  * VERSION missing/unreadable/empty -> log an error, do nothing.
  * marker missing                   -> write it (first adoption), wipe nothing.
  * marker unreadable/corrupt        -> log an error, do nothing.
  * marker == current                -> nothing.
  * marker != current                -> wipe the CONTENTS of runs/ and reviews/,
                                        then rewrite the marker.

Never wipe on doubt: any ambiguity (bad VERSION, bad marker, a runs/ or
reviews/ that is itself a symlink, an entry resolving outside its root)
means skip. Only entries directly inside runs/ and reviews/ are removed;
symlinks are unlinked themselves, never followed. proxies/, recordings/,
.ultralytics/ and the marker are never touched.

Live changes: `VersionWatcher` re-reads VERSION every 30 s. On a mismatch with
the marker it cancels every analysis, waits up to 30 s for the GPU worker to
go idle, releases the model, and only then wipes. If the worker is not idle in
time it logs an error and skips the wipe (retried on the next tick). If a wipe fails part-way the
marker is left unchanged so the next startup retries.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

MARKER_NAME = ".lab-version"
WIPE_DIRS = ("runs", "reviews")


def _log(msg: str) -> None:
    print(f"[lab] {msg}", file=sys.stderr, flush=True)


def _atomic_write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc))
    os.replace(tmp, path)


def read_version(version_file: Path) -> str | None:
    """The stripped first non-empty line of the VERSION file, or None."""
    try:
        text = Path(version_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def marker_path(lab_dir: Path) -> Path:
    return Path(lab_dir) / MARKER_NAME


def read_marker(lab_dir: Path) -> dict | None:
    """The marker doc; None if absent. Raises ValueError if present but bad."""
    p = marker_path(lab_dir)
    if not p.exists() and not p.is_symlink():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"unreadable marker {p}: {exc}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("version"), str) or not doc["version"]:
        raise ValueError(f"malformed marker {p}")
    return doc


def write_marker(lab_dir: Path, version: str) -> dict:
    doc = {"version": version, "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _atomic_write_json(marker_path(lab_dir), doc)
    return doc


def _wipe_contents(root: Path) -> int:
    """Delete everything directly inside `root`; return the number of entries removed.

    Raises OSError if an entry cannot be removed. A missing root removes 0.
    """
    if root.is_symlink() or not root.is_dir():
        if root.exists() or root.is_symlink():
            _log(f"refusing to wipe {root}: not a real directory")
        return 0
    real_root = root.resolve()
    removed = 0
    with os.scandir(real_root) as it:
        entries = list(it)
    for e in entries:
        p = Path(e.path)
        if e.is_symlink():
            p.unlink()  # the link itself, never its target
        else:
            if p.resolve().parent != real_root:
                _log(f"refusing to remove {p}: resolves outside {real_root}")
                continue
            if e.is_dir(follow_symlinks=False):
                shutil.rmtree(p)  # does not follow symlinks inside
            else:
                p.unlink()
        removed += 1
    return removed


def apply_version_policy(lab_dir: Path, version_file: Path) -> dict:
    lab_dir = Path(lab_dir)
    result = {"previous": None, "current": None, "wiped": False,
              "runsRemoved": 0, "reviewFilesRemoved": 0}
    current = read_version(version_file)
    if current is None:
        _log(f"ERROR: version file {version_file} missing or empty; leaving Lab content untouched")
        return result
    result["current"] = current

    try:
        marker = read_marker(lab_dir)
    except ValueError as exc:
        _log(f"ERROR: {exc}; leaving Lab content untouched")
        return result

    if marker is None:
        write_marker(lab_dir, current)
        _log(f"version {current}: first adoption, marker written, nothing removed")
        return result

    previous = marker["version"]
    result["previous"] = previous
    if previous == current:
        _log(f"version {current}: unchanged")
        return result

    try:
        result["runsRemoved"] = _wipe_contents(lab_dir / "runs")
        result["reviewFilesRemoved"] = _wipe_contents(lab_dir / "reviews")
    except OSError as exc:
        _log(f"ERROR: wipe {previous} -> {current} failed ({exc}); marker kept, will retry next start")
        return result
    write_marker(lab_dir, current)
    result["wiped"] = True
    _log(f"version {previous} -> {current}: removed {result['runsRemoved']} runs, "
         f"{result['reviewFilesRemoved']} review files")
    return result


class VersionWatcher:
    """Background re-check of VERSION (CONTRACTS 11a).

    `worker` provides begin_maintenance() (refuse new runs + cancel all),
    wait_idle(timeout) -> bool, release_model() and end_maintenance();
    the `lab.analysis` module satisfies this."""

    def __init__(self, lab_dir: Path, version_file: Path, worker, *, interval: float = 30.0,
                 idle_timeout: float = 30.0, on_result=None) -> None:
        self.lab_dir, self.version_file, self.worker = Path(lab_dir), Path(version_file), worker
        self.interval, self.idle_timeout, self.on_result = interval, idle_timeout, on_result
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> dict | None:
        """One check; returns the policy result if a wipe was attempted, else None."""
        current = read_version(self.version_file)
        if current is None:
            return None  # never act on doubt; the startup check already logged it
        try:
            marker = read_marker(self.lab_dir)
        except ValueError:
            return None
        if marker is None or marker["version"] == current:
            return None
        _log(f"VERSION changed {marker['version']} -> {current}: cancelling analyses before cleanup")
        self.worker.begin_maintenance()
        try:
            if not self.worker.wait_idle(self.idle_timeout):
                _log(f"ERROR: worker not idle after {self.idle_timeout:.0f}s; skipping wipe, will retry")
                return None
            self.worker.release_model()
            result = apply_version_policy(self.lab_dir, self.version_file)
        finally:
            self.worker.end_maintenance()
        if self.on_result is not None:
            self.on_result(result)
        return result

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - the watcher must survive
                _log(f"ERROR: version watcher: {exc!r}")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="version-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
