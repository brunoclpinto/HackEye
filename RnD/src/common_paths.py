"""Locate common/ regardless of whether we're running bare on the host or
inside the RnD container.

RnD/ and common/ are siblings in the repo, but compose.yaml mounts them as
separate top-level volumes (/rnd and /common) — code under RnD/src can't
reach common/ via '../..' inside the container.
"""

import os
from pathlib import Path


def find_common_dir() -> Path:
    env = os.environ.get("HACKEYE_COMMON_DIR")
    if env and Path(env).exists():
        return Path(env)
    container_mount = Path("/common")
    if container_mount.exists():
        return container_mount
    return Path(__file__).resolve().parents[2] / "common"
