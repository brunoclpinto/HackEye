"""Stderr logging with the legacy ``[collision] `` prefix, and warn-once de-duplication."""

from __future__ import annotations

import sys

__all__ = ["WARNED", "log", "warn_once"]

WARNED: set[str] = set()


def log(msg: str) -> None:
    print(f"[collision] {msg}", file=sys.stderr)


def warn_once(msg: str) -> None:
    if msg not in WARNED:
        WARNED.add(msg)
        log(msg)
