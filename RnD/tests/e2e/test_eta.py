"""ETA on the analyse progress bar (CONTRACTS, Analyse panel): formatter / tracker unit checks evaluated in the page, plus a real CPU run."""
import os
import shutil

from conftest import LONG_REC, api, open_lab

LAB_DIR_MOUNT = os.environ.get("LAB_DIR_MOUNT", "")


def _eta(page, expr):
    return page.evaluate(f"async () => {{ const m = await import('/static/js/eta.js'); return ({expr}); }}")


def test_format_eta(page):
    page.goto(os.environ.get("LAB_URL", "http://127.0.0.1:8765") + "/")
    got = _eta(page, "[5, 12, 40, 59, 60, 200, 3000, 3599, 3900, 7500, NaN].map(m.formatEta)")
    assert got[:5] == ["about 5 s", "about 10 s", "about 40 s", "about 60 s", "about 1 min"], got
    assert got[5:10] == ["about 3 min", "about 50 min", "about 1 h 00 min", "about 1 h 05 min", "about 2 h 05 min"], got
    assert got[10] == ""


def test_tracker_states(page):
    page.goto(os.environ.get("LAB_URL", "http://127.0.0.1:8765") + "/")
    out = _eta(page, """(() => {
      const L = [], t = new m.EtaTracker(0);
      const at = (s, p, st = 'running') => t.label({status: st, progress: p}, s * 1000);
      L.push(new m.EtaTracker().label({status: 'queued', progress: 0}, 0));
      L.push(at(1, 0.001));                 // too early
      L.push(at(12, 0.003));                // >= 10 s but < 2 % progress
      for (let s = 13; s < 40; s++) at(s, 0.003 + (s - 12) * 0.004);   // steady 0.4 %/s
      L.push(at(40, 0.003 + 28 * 0.004));   // ~ 115 s left
      const pStall = 0.003 + 29 * 0.004; L.push(at(41, pStall));
      L.push(at(120, pStall));               // no change since ~ t=40: stalled
      // opened mid-run: first sample already at 30 %, run created 100 s ago -> average-rate fallback
      const mid = new m.EtaTracker(0);
      L.push(mid.label({status: 'running', progress: 0.3}, 100000));
      // the shown ETA only counts down while the estimate wobbles by < 10 %
      const w = new m.EtaTracker(0); let prev = Infinity, rose = false;
      for (let s = 0; s <= 100; s++) {
        const p = 0.01 * s * (1 + 0.04 * Math.sin(s));
        const x = w.label({status: 'running', progress: Math.min(p, 0.99)}, s * 1000);
        const mm = /about (\\d+) min/.exec(x);
        if (mm) { if (+mm[1] > prev) rose = true; prev = +mm[1]; }
      }
      L.push(String(rose));
      return L;
    })()""")
    assert out[0] == "queued"
    assert out[1] == "running 0% · estimating…"
    assert out[2] == "running 0% · estimating…"
    assert "left" in out[3] and out[3].startswith("running 12% · about "), out[3]
    assert out[3] in ("running 12% · about 4 min left", "running 12% · about 5 min left"), out[3]   # 221 s true; the EMA lags a little
    assert out[5] == "running 12% · stalled?", out[5]
    assert out[6] == "running 30% · about 4 min left", out[6]   # 70 % at 0.3 % / s
    assert out[7] == "false", "ETA text rose while only wobbling"


def _rm_run(run_id):
    path = os.path.join(LAB_DIR_MOUNT, "runs", run_id) if LAB_DIR_MOUNT else ""
    if path and os.path.isdir(path):
        shutil.rmtree(path)


def test_progress_label_shows_eta_on_real_run(page):
    """Start a small CPU analysis and watch the label go "estimating…" / "… left" before it ends. The Lab runs one job at a time:
    if somebody else's run is in flight (ours would only queue), follow that one read-only instead and touch nothing."""
    runs = api("/api/runs")
    known = {r["id"] for r in runs}
    foreign = next((r for r in runs if r["status"] in ("queued", "running")), None)
    run_id = None
    pattern = ("() => /^running \\d+% · (estimating…|about .+ left|stalled\\?)$/"
               ".test(document.querySelector('#runProgress span').textContent)")
    try:
        if foreign:
            open_lab(page, foreign["request"]["recording"])
            page.wait_for_selector("#runProgress", state="visible", timeout=20_000)
            page.wait_for_function(pattern, timeout=60_000)
            label = page.inner_text("#runProgress span")
            assert page.inner_text(f'#runList li[data-run="{foreign["id"]}"] .tag') .startswith("running"), label
            assert "·" in page.get_attribute("#analyseBtn", "title"), label
            return
        open_lab(page, LONG_REC)
        page.fill("#rangeStart", "50")
        page.fill("#rangeEnd", "70")
        page.fill("#fpsInput", "6")
        page.select_option("#deviceSel", "cpu")
        page.click("#analyseBtn")
        page.wait_for_selector("#runProgress", state="visible", timeout=10_000)
        run_id = next(r["id"] for r in api("/api/runs") if r["id"] not in known)
        page.wait_for_function(pattern, timeout=300_000)
        label = page.inner_text("#runProgress span")
        assert api(f"/api/runs/{run_id}")["status"] in ("running", "done"), label
        assert page.inner_text(f'#runList li[data-run="{run_id}"] .tag') .startswith("running"), label   # the runs list shows it too
        page.click("#cancelBtn")
        page.wait_for_selector("#runProgress", state="hidden", timeout=15_000)
    finally:
        if run_id is None and not foreign:
            run_id = next((r["id"] for r in api("/api/runs") if r["id"] not in known), None)
        if run_id:
            try:
                api(f"/api/runs/{run_id}/cancel", "POST")
            except AssertionError:
                pass
            _rm_run(run_id)
