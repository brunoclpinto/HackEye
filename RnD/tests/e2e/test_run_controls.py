"""Cancel button and progress bar while an analysis runs (CONTRACTS 9, Analyse panel). Runs on CPU: the GPU may be busy."""
import os
import shutil

from conftest import BASE, LONG_REC, api, open_lab

LAB_DIR_MOUNT = os.environ.get("LAB_DIR_MOUNT", "")
RANGE = (5, 25)   # a range no other test analyses


def _rm_run(run_id):
    path = os.path.join(LAB_DIR_MOUNT, "runs", run_id) if LAB_DIR_MOUNT else ""
    if path and os.path.isdir(path):
        shutil.rmtree(path)


def _visible(page, sel):
    return page.is_visible(sel)


def _start_cpu_run(page, rng=RANGE):
    page.fill("#rangeStart", str(rng[0]))
    page.fill("#rangeEnd", str(rng[1]))
    page.fill("#fpsInput", "6")
    page.select_option("#deviceSel", "cpu")
    page.click("#analyseBtn")


def test_cancel_and_progress_visible_while_running(page):
    known = {r["id"] for r in api("/api/runs")}
    run_id = None
    try:
        open_lab(page, LONG_REC)
        _start_cpu_run(page)
        page.wait_for_selector("#cancelBtn", state="visible", timeout=10_000)
        page.wait_for_selector("#runProgress", state="visible", timeout=10_000)
        run_id = next(r["id"] for r in api("/api/runs") if r["id"] not in known)
        assert api(f"/api/runs/{run_id}")["device"] == "cpu"
        assert page.is_disabled("#analyseBtn")
        first = page.inner_text("#runProgress span")
        assert first.startswith(("queued", "running")), first
        # Progress advances (CPU is slow; allow a while) and a reload mid-run re-attaches to the run.
        page.wait_for_function("() => /running [1-9]/.test(document.querySelector('#runProgress span').textContent)", timeout=180_000)
        page.reload()
        page.wait_for_selector("#cancelBtn", state="visible", timeout=15_000)
        page.wait_for_selector("#runProgress", state="visible", timeout=15_000)
        assert page.is_disabled("#analyseBtn")
        page.click("#cancelBtn")
        page.wait_for_selector("#cancelBtn", state="hidden", timeout=15_000)
        page.wait_for_selector("#runProgress", state="hidden", timeout=15_000)
        assert api(f"/api/runs/{run_id}")["status"] == "cancelled"
        assert page.is_enabled("#analyseBtn")
        assert "· CPU" in page.inner_text("#runList")
    finally:
        if run_id is None:
            run_id = next((r["id"] for r in api("/api/runs") if r["id"] not in known), None)
        if run_id:
            try:
                api(f"/api/runs/{run_id}/cancel", "POST")
            except AssertionError:
                pass
            _rm_run(run_id)


def test_reanalyse_message_and_progress(page):
    """Analyse twice with the same settings: the second says 'already analysed'; Re-analyse shows the progress bar."""
    known = {r["id"] for r in api("/api/runs")}
    run_id = None
    try:
        open_lab(page, LONG_REC)
        _start_cpu_run(page, (40, 44))   # ~24 frames
        page.wait_for_selector("#cancelBtn", state="visible", timeout=10_000)
        run_id = next(r["id"] for r in api("/api/runs") if r["id"] not in known)
        page.wait_for_function("() => /(queued|running)/.test(document.querySelector('#runProgress span').textContent)")
        assert not page.is_visible("#reusedNote")
        page.wait_for_selector("#cancelBtn", state="hidden", timeout=600_000)   # CPU run finishes
        assert api(f"/api/runs/{run_id}")["status"] == "done"
        page.wait_for_function("() => !document.querySelector('#analyseBtn').disabled")
        page.click("#analyseBtn")
        page.wait_for_selector("#reusedNote", state="visible", timeout=15_000)
        assert "already analysed" in page.inner_text("#reusedNote")
        assert page.is_enabled("#analyseBtn")
        assert not page.is_visible("#runProgress")
        page.click("#reanalyseBtn")
        page.wait_for_selector("#runProgress", state="visible", timeout=10_000)
        assert page.inner_text("#runProgress span").startswith(("queued", "running"))
        assert page.is_disabled("#analyseBtn") and not page.is_visible("#reusedNote")
        assert api(f"/api/runs/{run_id}")["status"] in ("queued", "running")
        page.click("#cancelBtn")
        page.wait_for_selector("#runProgress", state="hidden", timeout=15_000)
        assert page.is_enabled("#analyseBtn")
    finally:
        if run_id is None:
            run_id = next((r["id"] for r in api("/api/runs") if r["id"] not in known), None)
        if run_id:
            try:
                api(f"/api/runs/{run_id}/cancel", "POST")
            except AssertionError:
                pass
            _rm_run(run_id)
