"""Locate common/ regardless of whether we're running bare on the host or
inside the RnD container.

RnD/ and common/ are siblings in the repo, but compose.yaml mounts them as
separate top-level volumes (/rnd and /common) — code under RnD/src can't
reach common/ via '../..' inside the container.

The implementation lives in engine.core.paths; this module re-exports it.
"""

from engine.core.paths import find_common_dir  # noqa: F401
