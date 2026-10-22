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
    page.wait_for_selector("#wmCanvas:visible")   # always visible since v26.2.0 (no collapsed panel)
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


BOX = "(sel) => { const r = document.querySelector(sel).getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height}; }"


def _open(page, w, h):
    run = test_lab.FULL_RUN
    rec = api(f"/api/runs/{run}")["request"]["recording"]
    page.set_viewport_size({"width": w, "height": h})
    open_lab(page, rec, t=13, run=run)
    page.wait_for_selector("#wmCanvas:visible")
    page.wait_for_timeout(300)


def test_layout_desktop_video_left_map_right_review_right_of_both(page):
    _open(page, 1500, 950)
    v, m, r = page.evaluate(BOX, "#stage"), page.evaluate(BOX, "#wmCanvas"), page.evaluate(BOX, "#reviewPanel")
    assert abs(v["t"] - m["t"]) <= 2, (v, m)                     # same top edge
    assert m["l"] >= v["r"] - 1, (v, m)                          # map to the right of the video
    assert abs(m["w"] - m["h"]) <= 2, m                           # square
    assert abs(m["h"] - v["h"]) <= 6, (v, m)                      # as tall as the video
    assert r["l"] >= m["r"] - 1, (m, r)                          # review right of both
    sb, mn = page.evaluate(BOX, "#sidebar"), page.evaluate(BOX, "#main")
    assert sb["t"] >= max(v["b"], m["b"]) - 1 and mn["t"] >= v["b"] - 1, (sb, mn)   # options start below the video + map
    assert sb["l"] < mn["l"] < r["l"]
    assert not page.errors, page.errors


def test_layout_tablet_viewer_full_width_review_below(page):
    _open(page, 1100, 900)
    v, m, r = page.evaluate(BOX, "#stage"), page.evaluate(BOX, "#wmCanvas"), page.evaluate(BOX, "#reviewPanel")
    sb = page.evaluate(BOX, "#sidebar")
    assert abs(v["t"] - m["t"]) <= 2 and m["l"] >= v["r"] - 1
    assert sb["t"] >= max(v["b"], m["b"]) - 1
    assert r["t"] >= sb["t"] and r["l"] < 20


def test_layout_phone_no_horizontal_overflow(page):
    _open(page, 390, 844)
    v, m = page.evaluate(BOX, "#stage"), page.evaluate(BOX, "#wmCanvas")
    assert m["t"] >= v["b"] - 1 and abs(m["w"] - m["h"]) <= 2 and m["w"] <= 482      # map under the video
    sw, iw = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert sw <= iw, f"horizontal overflow: scrollWidth {sw} > innerWidth {iw}"
