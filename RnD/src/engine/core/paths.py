"""Locate the shared common/ directory on the host or inside the RnD container."""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["find_common_dir"]


def find_common_dir() -> Path:
    env = os.environ.get("HACKEYE_COMMON_DIR")
    if env and Path(env).exists():
        return Path(env)
    container_mount = Path("/common")
    if container_mount.exists():
        return container_mount
    return Path(__file__).resolve().parents[4] / "common"
