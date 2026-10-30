"""World map panel (v26.2 step 1 spike, CONTRACTS 8.1 / 9): the map exists on the session's own run (built with it, v26.2.6), snapshot request 200, the canvas draws."""
import re

import pytest
from conftest import BASE, annotations, api, open_lab, seek
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
    assert meta["exists"], "v26.2.6: the map is built with the run, no click needed"
    assert page.query_selector("#wmBuild") is None and page.query_selector("#wmRules") is None      # the button and the toggle are gone
    seek(page, 13)
    page.wait_for_function("() => document.querySelector('#wmStatus').textContent.startsWith('t ')")
    page.wait_for_timeout(500)
    snaps = [u for u, _ in page.requests if f"/api/runs/{run}/worldmap/" in u and u.endswith(".png")]
    assert snaps, "no snapshot requested"
    assert page.evaluate("async (u) => (await fetch(u)).status", snaps[-1].replace(BASE, "")) == 200
    assert page.evaluate(DRAWN) > 0.05, "the canvas is (nearly) empty"
    assert not page.is_visible("#wmReadout") if page.query_selector("#wmReadout") else True      # v26.2.4: the hover readout is gone
    assert page.inner_text("#wmCell") == "Click the map to read a cell."
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


def _click_cell(page, col, row):
    box = page.evaluate("() => { const r = document.querySelector('#wmCanvas').getBoundingClientRect(); return {l: r.left, t: r.top, w: r.width, h: r.height}; }")
    page.mouse.click(box["l"] + box["w"] * (col + 0.5) / 200, box["t"] + box["h"] * (row + 0.5) / 200)


def test_click_readout_mapped_and_unmapped_cell(page):
    """v26.2.4: a click selects a cell; the box under the map (not overlaid) reads coordinates, region and object; unmapped = only 'unmapped'."""
    run = test_lab.FULL_RUN
    rec = api(f"/api/runs/{run}")["request"]["recording"]
    open_lab(page, rec, t=13, run=run)
    page.wait_for_selector("#wmCanvas:visible")
    assert api(f"/api/runs/{run}/worldmap")["exists"]
    seek(page, 13)
    page.wait_for_function("() => document.querySelector('#wmStatus').textContent.startsWith('t ')")
    cv, bx = page.evaluate(BOX, "#wmCanvas"), page.evaluate(BOX, "#wmCell")
    assert bx["t"] >= cv["b"] - 1, (cv, bx)                       # below the map, not over it
    # the nearest cells ahead of the user are ground: pick a mapped cell from the server, and an unmapped one
    t_idx = api(f"/api/runs/{run}/worldmap/pose.json")["t"]
    k = max(j for j, tt in enumerate(t_idx) if tt <= 13.05)
    mapped = unmapped = None
    for row in range(198, 120, -1):
        d = api(f"/api/runs/{run}/worldmap/cell?i={k}&col=100&row={row}")
        if mapped is None and d["surface"] is not None:
            mapped = (100, row, d)
    for col in (1, 198):
        for row in (1, 2, 3):
            d = api(f"/api/runs/{run}/worldmap/cell?i={k}&col={col}&row={row}")
            if unmapped is None and d["surface"] is None and d["object"] is None:
                unmapped = (col, row)
    assert mapped, "no mapped cell ahead of the user"
    _click_cell(page, mapped[0], mapped[1])
    page.wait_for_function("() => /Region: /.test(document.querySelector('#wmCell').textContent)")
    txt = page.inner_text("#wmCell")
    assert f"col {mapped[0]} row {mapped[1]}" in txt and "m ahead" in txt and "steps" in txt and "Object:" in txt and "Item:" in txt, txt
    assert "Region: none observed" not in txt
    assert "Beyond 20 m" not in txt, txt                           # v26.2.6: only the cell's own lines
    seek(page, 13.5)                                              # the selection stays across frames
    page.wait_for_timeout(600)
    assert f"col {mapped[0]} row {mapped[1]}" in page.inner_text("#wmCell")
    if unmapped:
        _click_cell(page, *unmapped)
        page.wait_for_function("() => document.querySelector('#wmCell').textContent === 'unmapped'")
    assert not page.errors, page.errors


def test_click_on_an_item_marker_reads_that_item(page):
    """v26.2.6: a click on a drawn (non-building) item marker snaps to its cell and names the item on the Object line."""
    run = test_lab.FULL_RUN
    rq = api(f"/api/runs/{run}")["request"]
    massive = re.compile(r"\b(building|bridge|tunnel)\b", re.I)
    pick = None
    for a in range(int(rq["start"]), int(rq["end"]), 30):
        doc = api(f"/api/runs/{run}/hazards?from={a}&to={a + 30}")
        for f in doc["frames"]:
            hs = [h for h in f.get("hazards", []) if h.get("distanceM") is not None and h.get("lateralM") is not None]
            for h in hs:
                if massive.search(h.get("className") or "") or not (3 < h["distanceM"] < 15 and abs(h["lateralM"]) < 6):
                    continue
                if any(o is not h and not massive.search(o.get("className") or "") and abs(o["distanceM"] - h["distanceM"]) < 1.5
                       and abs(o["lateralM"] - h["lateralM"]) < 1.5 for o in hs):
                    continue                                       # keep the nearest-marker rule out of the test
                pick = (f, h)
                break
            if pick:
                break
        if pick:
            break
    if not pick:
        pytest.skip("no isolated non-building item inside the map in the run")
    f, h = pick
    open_lab(page, rq["recording"], t=f["t"] + 0.01, run=run)
    page.wait_for_selector("#wmCanvas:visible")
    seek(page, f["t"] + 0.01)
    page.wait_for_function("() => document.querySelector('#wmStatus').textContent.startsWith('t ')")
    page.wait_for_timeout(600)
    col, row = 100 + h["lateralM"] / 0.1, 200 - h["distanceM"] / 0.1
    _click_cell(page, int(col), int(row))
    page.wait_for_function("() => /Object: /.test(document.querySelector('#wmCell').textContent)")
    obj = next(l for l in page.inner_text("#wmCell").splitlines() if l.startswith("Object:"))
    assert (h.get("className") or "item") in obj and f"track {h.get('trackId', '?')}" in obj, obj
    assert "Beyond 20 m" not in page.inner_text("#wmCell")
    assert not page.errors, page.errors


def test_autofill_populates_time_phrase_role_and_type_without_saving(page):
    """v26.2.4: Auto-fill on a paused frame sets the time to the playhead and fills phrase, role and type; it saves nothing."""
    run = "116731b3e5c2"
    if not any(r["id"] == run for r in api("/api/runs")):
        run = test_lab.FULL_RUN
    rq = api(f"/api/runs/{run}")["request"]
    t0 = rq["start"] + 14.2
    before = len(annotations(rq["recording"]))
    open_lab(page, rq["recording"], t=t0, run=run)
    page.wait_for_function("() => document.querySelector('#video').paused")
    page.click("#rvAddBtn")
    page.fill("#rvAddT", "0:01.0")                                # a stale / typed time: the playhead must win
    page.click("#rvAddAuto")
    page.wait_for_function("() => document.querySelector('#rvAddText').value.length > 0", timeout=20_000)
    t_play = page.evaluate("document.querySelector('#video').currentTime")
    assert abs(_parse(page.input_value("#rvAddT")) - t_play) < 0.11
    text = page.input_value("#rvAddText")
    assert re.search(r" at \S+ in \d+| at \S+ in \?", text), text
    assert page.input_value("#rvAddRole") in ("final", "danger", "feature", "context")
    assert page.input_value("#rvAddType") == "speech"
    got = page.evaluate("""async ([run, t]) => { const m = await import('/static/js/autofill.js');
        const f = (await (await fetch(`/api/runs/${run}/frame?t=` + t)).json()).frame;
        const o = m.orderCandidates(f, () => 0)[0]; return {role: o.role, cls: o.className, n: f.hazards.length}; }""", [run, t_play])
    assert page.input_value("#rvAddRole") == ("danger" if got["role"] == "none" else got["role"])
    assert len(annotations(rq["recording"])) == before        # nothing saved
    assert not page.errors, page.errors


def _parse(txt):
    m, s = txt.split(":")
    return int(m) * 60 + float(s)
