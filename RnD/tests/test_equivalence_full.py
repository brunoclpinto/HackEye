"""v26.3.0 equivalence oracle, full tier: every fixture window x every applicable mode + the Lab API session
(tools/equivalence.py compare).

Slow (minutes, parallel workers); ``pytest -m "not slow"`` skips it. A failure prints the drift report."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import equivalence

pytestmark = pytest.mark.slow


def test_full_equivalence_against_the_corpus() -> None:
    report = equivalence.compare(jobs=8, log=lambda _m: None)
    planned = len([c for c in equivalence.plan()[0]])
    assert len(report.results) >= planned, f"compared {len(report.results)} of {planned} planned cases"
    assert report.ok, "\n" + report.text()
