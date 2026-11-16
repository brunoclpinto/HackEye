"""Error types of the Lab store (moved verbatim from lab/analysis.py and lab/collisions.py)."""

from __future__ import annotations


class RunError(ValueError):
    """Bad request (maps to HTTP 4xx)."""


class RunConflict(RunError):
    """Request conflicts with current state (maps to HTTP 409)."""


class _Cancelled(Exception):
    """Raised inside the worker when a run's cancel flag is seen."""


class CollisionError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
