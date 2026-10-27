"""Notes box (v26.2.4 follow-up): autosave + reload, Insert time, stale-tab conflict.
The live Lab holds the user's real notes: they are saved first and restored (force PUT) at the end."""
import pytest

from conftest import BASE, SHORT_REC, api, open_lab, seek


@pytest.fixture(autouse=True)
def keep_user_notes():
    saved = api("/api/notes")
    try:
        yield
    finally:
        api("/api/notes", "PUT", {"text": saved["text"], "baseUpdatedAt": None, "force": True})


def _saved(page):
    page.wait_for_function("() => document.querySelector('#notesStatus').textContent.startsWith('Saved')")


def test_autosave_survives_reload(page):
    open_lab(page, SHORT_REC)
    page.fill("#notesText", "e2e note one")
    _saved(page)
    assert api("/api/notes")["text"] == "e2e note one"
    page.reload()
    page.wait_for_function("() => document.querySelector('#notesText').value === 'e2e note one'")


def test_insert_time_at_cursor(page):
    open_lab(page, SHORT_REC)
    seek(page, 3.4)
    page.fill("#notesText", "")
    page.click("#notesText")
    page.click("#notesStamp")
    v = page.input_value("#notesText")
    assert v.startswith(f"[{SHORT_REC} @ 0:03.4"), v
    _saved(page)


def test_stale_tab_gets_the_conflict_notice(page):
    open_lab(page, SHORT_REC)
    page.fill("#notesText", "mine v1")
    _saved(page)
    cur = api("/api/notes")
    api("/api/notes", "PUT", {"text": "theirs", "baseUpdatedAt": cur["updatedAt"]})   # another device writes
    page.fill("#notesText", "mine v2")
    page.wait_for_selector("#notesConflict:not([hidden])")
    assert api("/api/notes")["text"] == "theirs"                                      # nothing overwritten without a click
    page.click("#notesTheirs")
    assert page.input_value("#notesText") == "theirs"
    page.fill("#notesText", "mine v3")
    _saved(page)
    api("/api/notes", "PUT", {"text": "theirs2", "baseUpdatedAt": api("/api/notes")["updatedAt"]})
    page.fill("#notesText", "mine v4")
    page.wait_for_selector("#notesConflict:not([hidden])")
    page.click("#notesMine")
    _saved(page)
    assert api("/api/notes")["text"] == "mine v4"
