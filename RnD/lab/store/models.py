"""Model listing of the Lab (moved verbatim from lab/analysis.py)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from lab.store import constants

if TYPE_CHECKING:
    from pathlib import Path


def list_models() -> list[dict[str, Any]]:
    paths: list[Path] = []
    for directory, pattern in constants.MODEL_DIRS:
        if directory.is_dir():
            paths += sorted(directory.glob(pattern))
    releases = [p for p in paths if "HackEye" in p.name]

    # Newest app release first: versioned names ("...HackEye26.1-48-1280") by version, then
    # legacy dated names ("...HackEye20261011") by date. Dataset-creation models
    # ("...-Vistas124-HackEye-1280") and other unversioned names rank last, so the
    # fallback never picks one while an app release exists.
    def release_key(p: Path) -> tuple[int, tuple[int, ...], str]:
        v = re.search(r"HackEye(\d+)\.(\d+)(?:\.(\d+))?-", p.name)
        if v:
            return (2, tuple(int(x or 0) for x in v.groups()), p.name)
        d = re.search(r"HackEye(\d{8})", p.name)
        if d:
            return (1, (int(d.group(1)),), p.name)
        return (0, (), p.name)

    # Pinned default (by file name); without that file, the newest release.
    default = next((p for p in releases if p.name == constants.DEFAULT_MODEL), None)
    if default is None and releases:
        default = max(releases, key=release_key)
    return [{"path": str(p), "name": p.name, "default": p == default} for p in paths]
