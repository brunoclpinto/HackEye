"""Collision runs (v26.2.8, CONTRACTS 8 / 9 / 10): every re-run makes its own id (c1, c2, ...), kept side by side, selectable, compared A / B,
with reviews per collision run. They work on the session's own analysed run and delete the collision runs they make."""
import pytest
from conftest import annotations, api, open_lab, seek
from test_lab import _session_run  # noqa: F401  (the session-analysed run; autouse here too so -k collision works alone)
import test_lab

OVERRIDE = '{"collision": {"speech.globalMinGapSeconds": 30}}'     # far fewer speech events than the default 2.5 s
ROWS = '#rvList .rv-row[data-rk^="ev:"]:not(.beeps)'


def _run():
    return test_lab.FULL_RUN


def _ids():
    return [c["id"] for c in api(f"/api/runs/{_run()}/collisions")]


def _drop(ids):
    for cid in ids:
        try:
            api(f"/api/runs/{_run()}/collisions/{cid}", "DELETE")
        except AssertionError:
            pass


def _wait_selected(page, cid):
    page.wait_for_function("(c) => document.querySelector('#collSel').value === c && document.querySelector('#runBadge').textContent.includes(c)",
                           arg=cid, timeout=120_000)
    page.wait_for_function("() => document.querySelectorAll('#rvList .rv-row').length > 0", timeout=20_000)


def _rerun(page, overrides=""):
    seq = api(f"/api/runs/{_run()}")["collisionSeq"]
    page.fill("#collOverrides", overrides)
    page.click("#rerunBtn")
    _wait_selected(page, f"c{seq + 1}")
    page.wait_for_function("() => !document.querySelector('#rerunBtn').disabled", timeout=120_000)
    return f"c{seq + 1}"


def test_rerun_makes_new_ids_switching_reloads_label_and_compare(page):
    made = []
    try:
        open_lab(page, test_lab.LONG_REC, run=_run(), t=5)
        page.wait_for_selector("#collSel:visible")
        n0 = len(_ids())
        assert page.input_value("#collSel") == _ids()[-1]
        a = _rerun(page, OVERRIDE); made.append(a)
        b = _rerun(page)           # identical settings still make a new id
        made.append(b)
        assert page.locator("#collSel option").count() == n0 + 2 and page.input_value("#collSel") == b
        assert f"{a} ·" in page.inner_text("#collSel") and "globalMinGapSeconds 30" in page.locator(f'#collSel option[value="{a}"]').inner_text()
        assert api(f"/api/runs/{_run()}/collisions")[-2]["overrides"] == {"collision": {"speech.globalMinGapSeconds": 30}}

        # switching reloads the events: the overridden run speaks less
        n_b = page.locator(ROWS).count()
        page.select_option("#collSel", a)
        _wait_selected(page, a)
        n_a = page.locator(ROWS).count()
        assert 0 < n_a < n_b, (n_a, n_b)

        # label: saved on change
        page.fill("#collLabel", "e2e gap 30")
        page.press("#collLabel", "Enter")
        page.wait_for_function("(c) => document.querySelector(`#collSel option[value=\"${c}\"]`).textContent.includes('e2e gap 30')", arg=a)
        assert [c for c in api(f"/api/runs/{_run()}/collisions") if c["id"] == a][0]["label"] == "e2e gap 30"

        # the choice is kept per run
        open_lab(page, test_lab.LONG_REC, run=_run(), t=5)
        _wait_selected(page, a)

        # compare: the overrides key is in the settings table, rows seek the video
        page.click("#secCompare > summary")
        page.select_option("#cmpA", b)
        page.select_option("#cmpB", a)
        page.wait_for_selector("#cmpSettings")
        assert page.locator('#cmpSettings tr[data-key="overrides.collision.speech.globalMinGapSeconds"]').count() == 1
        page.evaluate("document.querySelector('#cmpOnlyA').open = true")
        row = page.locator("#cmpOnlyA button").first                     # in the default run, dropped by the 30 s gap
        row.wait_for()
        t = float(api(f"/api/runs/{_run()}/collisions/compare?a={b}&b={a}")["events"]["onlyA"][0]["t"])
        row.click()
        page.wait_for_function("(t) => Math.abs(document.querySelector('#video').currentTime - t) < 1.0", arg=t, timeout=10_000)
        assert not page.errors, page.errors
    finally:
        _drop(made)


def test_a_verdict_belongs_to_its_collision_run_and_a_reviewed_one_cannot_be_deleted(page, created_reviews):
    made = []
    try:
        made.append(api(f"/api/runs/{_run()}/collision", "POST", {})["id"])
        made.append(api(f"/api/runs/{_run()}/collision", "POST", {})["id"])
        a, b = made
        open_lab(page, test_lab.LONG_REC, run=_run(), t=5)
        page.select_option("#collSel", a)
        _wait_selected(page, a)
        row = page.locator(ROWS).first
        row.locator("button.rv-v.correct").click()
        page.wait_for_function("() => document.querySelector('#rvCorrect').textContent === '1'")
        page.wait_for_timeout(800)                                       # the POST is queued behind the optimistic update
        mine = [x for x in annotations(test_lab.LONG_REC) if x.get("collisionId") == a and x["kind"] == "verdict"]
        assert mine, annotations(test_lab.LONG_REC)
        created_reviews.append((test_lab.LONG_REC, mine[0]["id"]))
        assert mine[0]["runId"] == _run()

        page.select_option("#collSel", b)                                # not shown on the other collision run
        _wait_selected(page, b)
        assert page.inner_text("#rvCorrect") == "0"
        page.select_option("#collSel", a)
        _wait_selected(page, a)
        assert page.inner_text("#rvCorrect") == "1"

        page.once("dialog", lambda d: d.accept())
        page.click("#collDel")
        page.wait_for_function("() => document.querySelector('#toasts').textContent.includes('1 review')", timeout=10_000)
        assert a in _ids()
    finally:
        for rec, ann_id in list(created_reviews):
            try:
                api(f"/api/recordings/{rec}/reviews/{ann_id}", "DELETE")
            except AssertionError:
                pass
        created_reviews.clear()
        _drop(made)


def test_bad_overrides_show_a_message_and_make_no_collision_run(page):
    open_lab(page, test_lab.LONG_REC, run=_run(), t=5)
    page.wait_for_selector("#collSel:visible")
    before = _ids()
    page.fill("#collOverrides", "{not json")
    page.click("#rerunBtn")
    page.wait_for_selector("#collOvErr:visible")
    assert "JSON" in page.inner_text("#collOvErr")
    page.fill("#collOverrides", '{"collision": {"distance.nope": "off"}}')
    page.click("#rerunBtn")
    page.wait_for_function("() => document.querySelector('#collOvErr').textContent.includes('distance.nope')", timeout=20_000)
    assert _ids() == before
    page.fill("#collOverrides", "")


def test_collision_run_ui_fits_a_phone(page):
    page.set_viewport_size({"width": 390, "height": 844})
    open_lab(page, test_lab.LONG_REC, run=_run(), t=5)
    page.wait_for_selector("#collSel:visible")
    page.evaluate("document.querySelector('#secCompare').open = true")
    for sel in ("#collSel", "#collLabel", "#collDel", "#collOverrides"):
        box = page.evaluate("(s) => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.right]; }", sel)
        assert box[0] >= 0 and box[1] <= 390 + 1, (sel, box)
    sw, iw = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert sw <= iw, f"horizontal overflow: scrollWidth {sw} > innerWidth {iw}"
