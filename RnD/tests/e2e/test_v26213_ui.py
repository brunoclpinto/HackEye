"""v26.2.13 Lab UI (user Notes 2026-11-10, "1. horizon line off by default."): the video's Horizon layer starts off and can be turned on."""
from conftest import open_lab
from test_lab import LONG_REC, _session_run  # noqa: F401  (the session-analysed run, autouse)
import test_lab


def test_horizon_layer_is_off_by_default_and_can_be_turned_on(page):
    open_lab(page, LONG_REC, run=test_lab.FULL_RUN)
    assert not page.is_checked("#horizonChk")
    page.check("#horizonChk")
    assert page.is_checked("#horizonChk")
