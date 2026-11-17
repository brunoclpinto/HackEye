"""Open issues panel (v26.2.4 follow-up): expand + comment + reload, close / reopen. The user's real issue state is backed up and put back."""
import pytest

from conftest import SHORT_REC, api, open_lab


@pytest.fixture(autouse=True)
def keep_user_issues():
    before = {i["id"]: (i["status"], i["note"], i["userChanged"]) for g in api("/api/issues")["groups"] for i in g["items"]}
    try:
        yield
    finally:
        for iid, (status, note, touched) in before.items():
            cur = {i["id"]: i for g in api("/api/issues")["groups"] for i in g["items"]}[iid]
            if not touched:
                if cur["userChanged"] or cur["status"] != status:
                    api(f"/api/issues/{iid}/state", "DELETE")
                continue
            if cur["status"] != status:
                api(f"/api/issues/{iid}", "PUT", {"status": status})
            if cur["note"] != note:
                api(f"/api/issues/{iid}", "PUT", {"note": note})


def _first_open():
    d = api("/api/issues")
    return next(i for g in d["groups"] if g["id"] != "closed" for i in g["items"])


def _title_count(page):
    return int(page.inner_text("#issuesTitle").split("(")[1].split(" ")[0])


def test_comment_survives_reload(page):
    it = _first_open()
    open_lab(page, SHORT_REC)
    page.wait_for_selector(f'.iss-item[data-id="{it["id"]}"]')
    page.click(f'.iss-item[data-id="{it["id"]}"] .iss-title')
    ta = page.locator(f'.iss-item[data-id="{it["id"]}"] textarea')
    ta.fill("e2e comment")
    page.wait_for_function("(id) => document.querySelector(`.iss-item[data-id='${id}'] .rv-saved`).textContent.includes('saved')", arg=it["id"])
    assert api("/api/issues")  # still reachable
    page.reload()
    page.wait_for_selector(f'.iss-item[data-id="{it["id"]}"] .iss-title')
    page.click(f'.iss-item[data-id="{it["id"]}"] .iss-title')
    assert page.input_value(f'.iss-item[data-id="{it["id"]}"] textarea') == "e2e comment"


def test_close_and_reopen_move_the_row(page):
    it = _first_open()
    open_lab(page, SHORT_REC)
    sel = f'.iss-item[data-id="{it["id"]}"]'
    page.wait_for_selector(sel)
    n = _title_count(page)
    page.click(f"{sel} [data-act=close]")
    page.wait_for_function("(n) => +document.querySelector('#issuesTitle').textContent.match(/\\((\\d+) open/)[1] === n - 1", arg=n)
    assert page.locator(f'.iss-group[data-group="closed"] {sel}').count() == 1
    page.wait_for_function("(id) => { const i = [...document.querySelectorAll('.iss-item')].find(e => e.dataset.id === id); return !!i; }", arg=it["id"])
    page.wait_for_timeout(500)
    assert [i["status"] for g in api("/api/issues")["groups"] for i in g["items"] if i["id"] == it["id"]] == ["closed"]
    page.evaluate("document.querySelector('.iss-group[data-group=closed]').open = true")   # Closed is collapsed by default
    page.click(f"{sel} [data-act=reopen]")
    page.wait_for_function("(n) => +document.querySelector('#issuesTitle').textContent.match(/\\((\\d+) open/)[1] === n", arg=n)
    assert page.locator(f'.iss-group[data-group="closed"] {sel}').count() == 0
