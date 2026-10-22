"""World map panel (v26.2 step 1 spike, CONTRACTS 8.1 / 9): build on the session's own run, snapshot request 200, the canvas draws."""
from conftest import BASE, api, open_lab, seek
from test_lab import _session_run  # noqa: F401  (the session-analysed run; autouse here too so -k worldmap works alone)
import test_lab

DRAWN = """() => {
  const c = document.querySelector('#wmCanvas'), x = c.getContext('2d');
  const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0;
  for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - 11) + Math.abs(d[i+1] - 13) + Math.abs(d[i+2] - 16) > 30) n++;
  return n / (d.length / 4);
}"""


def test_world_map_panel_builds_and_draws(page):
    run = test_lab.FULL_RUN
    rec = api(f"/api/runs/{run}")["request"]["recording"]
    open_lab(page, rec, t=13, run=run)
    page.wait_for_function("() => document.querySelector('#secWorldmap')")
    if not page.evaluate("() => document.querySelector('#secWorldmap').open"):
        page.click("#secWorldmap > summary")
    meta = api(f"/api/runs/{run}/worldmap")
    if not meta["exists"]:
        page.wait_for_selector("#wmBuild:visible")
        page.click("#wmBuild")
        page.wait_for_function("() => document.querySelector('#wmInfo').textContent.includes('Built in')")
        assert not page.is_visible("#wmBuild")
    assert api(f"/api/runs/{run}/worldmap")["exists"]
    seek(page, 13)
    page.wait_for_function("() => document.querySelector('#wmStatus').textContent.startsWith('t ')")
    page.wait_for_timeout(500)
    snaps = [u for u, _ in page.requests if f"/api/runs/{run}/worldmap/" in u and u.endswith(".png")]
    assert snaps, "no snapshot requested"
    assert page.evaluate("async (u) => (await fetch(u)).status", snaps[-1].replace(BASE, "")) == 200
    assert page.evaluate(DRAWN) > 0.05, "the canvas is (nearly) empty"
    assert not page.errors, page.errors
