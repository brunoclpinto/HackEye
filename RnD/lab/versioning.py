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

The policy and the watcher moved to `lab.jobs.versioning` (v26.3.0 p5-03, audit 7.8); every name stays reachable here as a forward.
"""

from __future__ import annotations

from lab._forward import install

install(__name__, dict.fromkeys(
    ("_log", "_atomic_write_json", "read_version", "marker_path", "read_marker", "write_marker", "_wipe_contents",
     "apply_version_policy", "VersionWatcher", "MARKER_NAME", "WIPE_DIRS"),
    "lab.jobs.versioning"))
