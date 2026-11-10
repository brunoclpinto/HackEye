"""v26.2.12 Lab UI: beep repeats, predictive-phrase marks, objects above the horizon are clickable, speech speed default.
Events and hazards are injected on the wire (the session's own run), so nothing depends on what a collision pass produced."""
import json

import pytest
from conftest import annotations, api, open_lab, seek
from test_lab import LONG_REC, _session_run, inject_beeps  # noqa: F401  (the session-analysed run, autouse)
import test_lab

PRED_T, PRED_DT = 12.0, 1.99
PRED_TEXT = "e2e sign at 12:30 in 5"
PRED = {"dt": PRED_DT, "phraseS": 3.7, "dts": [PRED_DT, 3.7], "steps": 5, "clock": "12:30", "fwd": 3.5, "right": 0.7, "stepsNow": 6,
        "textNow": "e2e sign at 12:15 in 6"}


def _run():
    return test_lab.FULL_RUN


def _inject_predicted(page):
    ev = {"t": PRED_T, "type": "speech", "role": "feature", "text": PRED_TEXT, "trackId": 987001, "urgency": "none", "clock": 12,
          "clockText": "12:15", "pan": 0.1, "predicted": PRED}

    def handle(route):
        resp = route.fetch()
        doc = resp.json()
        doc["events"] = [e for e in doc["events"] if e.get("trackId") != 987001] + [ev]
        route.fulfill(response=resp, json=doc)

    page.route(f"**/api/runs/{_run()}/events.json*", handle)


def test_beeps_row_shows_its_repeat_count_and_interval(page):
    inject_beeps(page)
    open_lab(page, LONG_REC, run=_run())
    row = page.locator(".rv-row.beeps", has_text="e2e pole")
    row.wait_for()
    rep = row.locator(".rv-rep")
    assert rep.inner_text() == "× 12 · 0.50 s"           # 12 injected tones every 0.5 s inside the episode
    assert "12 tones" in rep.get_attribute("title") and "0.50" in rep.get_attribute("title")
    assert not page.errors, page.errors


def test_predicted_phrase_has_a_marker_two_clickable_times_and_the_unpredicted_text(page, created_reviews):
    _inject_predicted(page)
    open_lab(page, LONG_REC, run=_run())
    row = page.locator(".rv-row", has_text=PRED_TEXT)
    row.wait_for()
    assert "⏩" in row.locator(".rv-pred").inner_text()
    said, for_ = row.locator(".rv-time").nth(0), row.locator(".rv-time").nth(1)
    assert said.inner_text().startswith("said ") and for_.inner_text().startswith("for ")
    assert row.locator(".rv-text").get_attribute("title") == f"Without prediction: {PRED['textNow']}"
    for_.click()
    page.wait_for_function("(t) => Math.abs(document.querySelector('#video').currentTime - t) < 0.3", arg=PRED_T + PRED_DT)
    said.click()
    page.wait_for_function("(t) => Math.abs(document.querySelector('#video').currentTime - t) < 0.3", arg=PRED_T)
    # the verdict (and so the export) carries the predicted block
    before = {a["id"] for a in annotations(LONG_REC)}
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith(f"/api/recordings/{LONG_REC}/reviews")) as req:
        row.locator(".rv-v.correct").click()
    assert json.loads(req.value.post_data)["event"]["predicted"] == PRED       # the stored copy / export: tests/test_lab_reviews_v26212.py
    page.wait_for_timeout(1000)
    new = [a for a in annotations(LONG_REC) if a["id"] not in before and not a.get("auto")]   # v26.2.14: auto ✓ of earlier items are cleaned by created_reviews
    created_reviews.extend((LONG_REC, a["id"]) for a in new)
    assert len(new) == 1
    assert not page.errors, page.errors


def test_an_item_above_the_horizon_is_clickable_through_bboxfull_and_outlinefull(page):
    TRACK = 777001
    box, full = [0.40, 0.55, 0.60, 0.70], [0.40, 0.20, 0.60, 0.70]

    def handle(route):
        resp = route.fetch()
        doc = resp.json()
        h = {"label": "e2e wall", "className": "wall", "trackId": TRACK, "role": "danger", "urgency": "danger", "clock": 12, "clockText": "12",
             "stepsTo": 4, "distanceM": 3.0, "contactY": 0.7, "bbox": box, "bboxFull": full,
             "outline": [[0.4, 0.55], [0.6, 0.55], [0.6, 0.7], [0.4, 0.7]], "outlineFull": [[0.4, 0.2], [0.6, 0.2], [0.6, 0.7], [0.4, 0.7]]}
        for f in doc["frames"]:
            f["hazards"] = [h]
            f["horizonY"] = 0.5
        route.fulfill(response=resp, json=doc)

    page.route(f"**/api/runs/{_run()}/hazards?*", handle)
    open_lab(page, LONG_REC, run=_run(), t=10)
    seek(page, 10.0)
    page.wait_for_function("() => !document.querySelector('#hud').hidden", timeout=20_000)
    r = page.evaluate("() => { const r = document.querySelector('#overlay').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }")
    at = lambda x, y: (r[0] + x * r[2], r[1] + y * r[3])
    sel = lambda: page.evaluate("document.querySelector('#overlay').dataset.selTrack")
    page.mouse.click(*at(0.5, 0.62))                    # below the horizon: the old box
    page.wait_for_function("(t) => document.querySelector('#overlay').dataset.selTrack === t", arg=str(TRACK))
    page.mouse.click(*at(0.05, 0.05))                   # nothing
    page.wait_for_function("() => document.querySelector('#overlay').dataset.selTrack === ''")
    page.mouse.click(*at(0.5, 0.30))                    # above the horizon (y 0.5): only the full outline covers it
    page.wait_for_function("(t) => document.querySelector('#overlay').dataset.selTrack === t", arg=str(TRACK))
    page.mouse.move(*at(0.5, 0.30))
    page.wait_for_function("() => !document.querySelector('#itemTip').hidden")
    assert "wall" in page.inner_text("#itemTip")
    page.mouse.click(*at(0.7, 0.30))   # beside the item, above the horizon: not hit
    page.wait_for_function("() => document.querySelector('#overlay').dataset.selTrack === ''")
    assert not page.errors, page.errors


def test_speech_speed_default_is_marked_and_follows_the_config(page):
    cfg = api("/api/config/collision")["tones"]["speechRate"]
    assert cfg == 1.25
    assert api("/api/sounds")["defaultSpeechRate"] == cfg
    saved = {}

    def put(route):                                     # never write the Lab-wide profile from a test
        saved["body"] = route.request.post_data
        route.fulfill(status=200, content_type="application/json", body="{}")

    page.route("**/api/sounds", lambda route: put(route) if route.request.method == "PUT" else route.continue_())
    open_lab(page, LONG_REC, profile=True)
    page.wait_for_function("() => document.querySelectorAll('#sndRows tr').length > 0")
    stored = api("/api/sounds")["speechRate"]
    assert page.input_value("#sndSpeech") == str(stored)
    assert (page.inner_text("#sndSpeechDef") == "(default)") == (stored == cfg)
    page.evaluate("() => { const r = document.querySelector('#sndSpeech'); r.value = '1'; r.dispatchEvent(new Event('input')); }")
    assert page.inner_text("#sndSpeechDef") == "" and page.inner_text("#sndSpeechOut").startswith("1.00")
    page.evaluate("() => { const r = document.querySelector('#sndSpeech'); r.value = '1.25'; r.dispatchEvent(new Event('input')); }")
    assert page.inner_text("#sndSpeechDef") == "(default)"
    page.wait_for_function("() => document.querySelector('#sndStatus').textContent.startsWith('Saved')")
    assert json.loads(saved["body"])["speechRate"] == 1.25
    assert not page.errors, page.errors
