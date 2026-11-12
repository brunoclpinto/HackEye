"""v26.3.0 equivalence oracle, quick tier: 3 windows x 3 modes + the Lab API session against the corpus
``tests/fixtures/equivalence`` (tools/equivalence.py).

A failure prints the drift report. After an intended behaviour change, re-capture the corpus in the same commit."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import equivalence


def test_quick_equivalence_against_the_corpus() -> None:
    report = equivalence.compare(quick=True, jobs=4, log=lambda _m: None)
    assert report.results, "no cases were compared"
    assert report.ok, "\n" + report.text()
