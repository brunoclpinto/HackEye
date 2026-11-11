"""Share the GPU with LocalWorker (its CONTRACTS section 8): a flock on a shared file.

LocalWorker holds LOCK_EX on the lock file while its LLM is loaded; the Lab only
ever takes LOCK_SH | LOCK_NB, so it never blocks. A missing lock file means
LocalWorker is not installed / not running: the GPU is free.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path

GPUQ_LOCK = Path(os.environ.get("LOCALWORKER_GPU_LOCK", "/gpuq/gpu.lock"))
BLOCKED_MESSAGE = "GPU in use by LocalWorker; choose CPU"


def _open_shared(path: Path) -> int | None:
    """An fd holding LOCK_SH on `path`, None if LocalWorker holds it exclusively. FileNotFoundError if missing."""
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def localworker_holds_gpu() -> bool:
    try:
        fd = _open_shared(GPUQ_LOCK)
    except OSError:  # missing (or unreadable) lock file: nobody arbitrates
        return False
    if fd is None:
        return True
    os.close(fd)  # closing drops the lock
    return False


class GpuShare:
    """The Lab's shared hold on the GPU while a GPU model is resident."""

    def __init__(self) -> None:
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        """Non-blocking LOCK_SH; idempotent. False when LocalWorker holds the GPU."""
        if self._fd is not None:
            return True
        try:
            fd = _open_shared(GPUQ_LOCK)
        except OSError:
            return True  # no lock file: nothing to share with, nothing held
        if fd is None:
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
