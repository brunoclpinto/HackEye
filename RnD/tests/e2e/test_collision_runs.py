"""Collision runs (v26.2.8, CONTRACTS 8 / 9 / 10): every re-run makes its own id (c1, c2, ...), kept side by side, selectable, compared A / B,
with reviews per collision run. They work on the session's own analysed run and delete the collision runs they make."""
import pytest
from conftest import annotations, api, collision_job, open_lab, seek
from test_lab import _session_run  # noqa: F401  (the session-analysed run; autouse here too so -k collision works alone)
import test_lab

OVERRIDE = '{"collision": {"speech.globalMinGapSeconds": 30}}'     # far fewer speech events than the default 2.5 s
GROUP = "#runList li.run-group"
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


def _row(cid):
    """The collision's row inside its run's group in the runs list (v26.2.10)."""
    return f'{GROUP}[data-run="{_run()}"] .coll-row[data-cid="{cid}"]'


def _wait_selected(page, cid):
    page.wait_for_function("(c) => document.querySelector(`#runList .coll-row.sel[data-cid=\"${c}\"]`) && document.querySelector('#runBadge').textContent.includes(c)",
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
        page.wait_for_selector(f"{GROUP}[data-run='{_run()}'] .coll-row")
        n0 = len(_ids())
        assert page.locator(f"{GROUP}[data-run='{_run()}'] .coll-row.sel").get_attribute("data-cid") == _ids()[-1]
        a = _rerun(page, OVERRIDE); made.append(a)
        b = _rerun(page)           # identical settings still make a new id
        made.append(b)
        assert page.locator(f"{GROUP}[data-run='{_run()}'] .coll-row").count() == n0 + 2
        assert page.locator(f"{GROUP}[data-run='{_run()}'] .coll-row.sel").get_attribute("data-cid") == b
        assert "globalMinGapSeconds 30" in page.inner_text(_row(a))
        assert api(f"/api/runs/{_run()}/collisions")[-2]["overrides"] == {"collision": {"speech.globalMinGapSeconds": 30}}

        # switching reloads the events: the overridden run speaks less
        n_b = page.locator(ROWS).count()
        page.click(f"{_row(a)} .sub")
        _wait_selected(page, a)
        n_a = page.locator(ROWS).count()
        assert 0 < n_a < n_b, (n_a, n_b)

        # label: saved on change
        page.fill(f"{_row(a)} .coll-label", "e2e gap 30")
        page.press(f"{_row(a)} .coll-label", "Enter")
        page.wait_for_function("(c) => document.querySelector(`#cmpA option[value=\"${c}\"]`).textContent.includes('e2e gap 30')", arg=a)
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
        made.append(collision_job(_run())["id"])
        made.append(collision_job(_run())["id"])
        a, b = made
        open_lab(page, test_lab.LONG_REC, run=_run(), t=5)
        page.click(f"{_row(a)} .sub")
        _wait_selected(page, a)
        row = page.locator(ROWS).first
        row.locator("button.rv-v.correct").click()
        page.wait_for_function("() => document.querySelector('#rvCorrect').textContent === '1'")
        page.wait_for_timeout(800)                                       # the POST is queued behind the optimistic update
        mine = [x for x in annotations(test_lab.LONG_REC) if x.get("collisionId") == a and x["kind"] == "verdict"]
        assert mine, annotations(test_lab.LONG_REC)
        created_reviews.append((test_lab.LONG_REC, mine[0]["id"]))
        assert mine[0]["runId"] == _run()

        page.click(f"{_row(b)} .sub")                                    # not shown on the other collision run
        _wait_selected(page, b)
        assert page.inner_text("#rvCorrect") == "0"
        page.click(f"{_row(a)} .sub")
        _wait_selected(page, a)
        assert page.inner_text("#rvCorrect") == "1"

        page.once("dialog", lambda d: d.accept())
        page.click(f"{_row(a)} .coll-del")
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
    page.wait_for_selector(f"{GROUP}[data-run='{_run()}'] .coll-row")
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
    page.evaluate("document.querySelector('#secRuns').open = true; document.querySelector('#secCompare').open = true")   # collapsed on a phone
    page.wait_for_selector(f"{GROUP}[data-run='{_run()}'] .coll-row")
    for sel in (f"{GROUP}[data-run='{_run()}']", f"{GROUP} .coll-row .coll-label", f"{GROUP} .coll-row .coll-del", "#collOverrides"):
        box = page.evaluate("(s) => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.right]; }", sel)
        assert box[0] >= 0 and box[1] <= 390 + 1, (sel, box)
    sw, iw = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert sw <= iw, f"horizontal overflow: scrollWidth {sw} > innerWidth {iw}"


def test_rerun_shows_progress_and_cancel_in_its_row_and_cancel_leaves_nothing(page):
    """v26.2.10: the re-run is a job: a row in the run's group with the Analyse-style progress bar + Cancel; Cancel removes it, the id is burnt."""
    made = []
    try:
        open_lab(page, test_lab.LONG_REC, run=_run(), t=5)
        page.wait_for_selector(f"{GROUP}[data-run='{_run()}'] .coll-row")
        before = _ids()
        seq = api(f"/api/runs/{_run()}")["collisionSeq"]
        page.click("#rerunBtn")
        row = f"{GROUP}[data-run='{_run()}'] .coll-row[data-cid='c{seq + 1}']"
        page.wait_for_selector(f"{row} .progress", timeout=20_000)
        assert page.is_visible(f"{row} .coll-cancel") and page.is_disabled("#rerunBtn")
        assert page.inner_text(f"{row} .tag") == "running"
        page.wait_for_function("(r) => parseFloat(document.querySelector(r + ' .progress > div').style.width) > 0", arg=row, timeout=60_000)
        page.click(f"{row} .coll-cancel")
        page.wait_for_selector(row, state="detached", timeout=30_000)
        page.wait_for_function("() => !document.querySelector('#rerunBtn').disabled", timeout=30_000)
        assert _ids() == before
        assert api(f"/api/runs/{_run()}")["collisionSeq"] == seq + 1            # c<seq+1> is burnt
        made.append(collision_job(_run())["id"])
        assert made[0] == f"c{seq + 2}"
        assert not page.errors, page.errors
    finally:
        _drop(made)


def test_rerun_ends_in_a_row_of_its_runs_group_with_label_and_delete(page):
    made = []
    try:
        open_lab(page, test_lab.LONG_REC, run=_run(), t=5)
        page.wait_for_selector(f"{GROUP}[data-run='{_run()}'] .coll-row")
        a = _rerun(page)
        made.append(a)
        row = _row(a)
        assert page.locator(f"{GROUP}[data-run='{_run()}'] ul.coll-rows > li.coll-row[data-cid='{a}']").count() == 1      # inside its run's group
        assert page.inner_text(f"{row} .tag") == "done" and "speech" in page.inner_text(row) and "beeps" in page.inner_text(row)
        page.fill(f"{row} .coll-label", "e2e row label")
        page.press(f"{row} .coll-label", "Enter")
        for _ in range(50):                                              # the PATCH is async
            if [c for c in api(f"/api/runs/{_run()}/collisions") if c["id"] == a][0]["label"] == "e2e row label":
                break
            page.wait_for_timeout(200)
        assert [c for c in api(f"/api/runs/{_run()}/collisions") if c["id"] == a][0]["label"] == "e2e row label"
        assert page.input_value(f"{row} .coll-label") == "e2e row label"
        # the group folds, the run header stays
        page.click(f"{GROUP}[data-run='{_run()}'] summary")
        assert not page.is_visible(row)
        page.click(f"{GROUP}[data-run='{_run()}'] summary")
        assert page.is_visible(row)
        page.once("dialog", lambda d: d.accept())
        page.click(f"{row} .coll-del")
        page.wait_for_selector(row, state="detached", timeout=20_000)
        made.remove(a)
        assert a not in _ids()
        assert not page.errors, page.errors
    finally:
        _drop(made)
