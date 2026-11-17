"""v26.2.14 Lab UI: earlier notifications count as reviewed (auto-correct), and any item is clickable above the horizon.
The auto-correct tests need the server code of v26.2.14 (restart the Lab first); the horizon test runs on the wire and needs only the static files."""
import json

import pytest
from conftest import annotations, api, open_lab, seek
from test_lab import LONG_REC, _session_run, long_run_events  # noqa: F401  (the session-analysed run, autouse)
import test_lab


def _run():
    return test_lab.FULL_RUN


@pytest.mark.parametrize("with_outline", [True, False], ids=["outlineFull", "bboxFull-only"])
def test_a_no_role_item_above_the_horizon_is_clickable_through_bboxfull_and_outlinefull(page, with_outline):
    TRACK = 777002
    box, full = [0.40, 0.55, 0.60, 0.70], [0.40, 0.10, 0.60, 0.70]

    def handle(route):
        resp = route.fetch()
        doc = resp.json()
        h = {"label": "e2e building", "className": "building", "trackId": TRACK, "role": "none", "urgency": "none", "clock": 12, "clockText": "12",
             "stepsTo": 9, "distanceM": 7.0, "contactY": 0.7, "bbox": box, "bboxFull": full,
             "outline": [[0.4, 0.55], [0.6, 0.55], [0.6, 0.7], [0.4, 0.7]], "outlineFull": [[0.4, 0.1], [0.6, 0.1], [0.6, 0.7], [0.4, 0.7]]}
        if not with_outline:
            del h["outlineFull"]                         # the clipped `outline` must not decide a hit above the horizon
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
    for y in (0.62, 0.30, 0.12):                        # below the horizon, just above it, near the top of the full outline
        page.mouse.click(*at(0.5, 0.05))
        page.wait_for_function("() => document.querySelector('#overlay').dataset.selTrack === ''")
        page.mouse.click(*at(0.5, y))
        page.wait_for_function("(t) => document.querySelector('#overlay').dataset.selTrack === t", arg=str(TRACK))
    page.mouse.move(*at(0.5, 0.2))
    page.wait_for_function("() => !document.querySelector('#itemTip').hidden")
    assert "building" in page.inner_text("#itemTip")
    page.mouse.click(*at(0.7, 0.2))                     # beside it, above the horizon: not hit
    page.wait_for_function("() => document.querySelector('#overlay').dataset.selTrack === ''")
    assert not page.errors, page.errors


def _post_verdict_on(page, text):
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith(f"/api/recordings/{LONG_REC}/reviews")):
        page.locator(".rv-row", has_text=text).locator(".rv-v.correct").first.click()
    page.wait_for_timeout(1200)


def test_reviewing_a_later_item_counts_the_earlier_ones_correct(page, created_reviews):
    ev = [e for e in api(f"/api/runs/{_run()}/events.json")["events"] if e["type"] in ("speech", "beeps")]
    ev.sort(key=lambda e: e["t"])
    if len(ev) < 3:
        pytest.skip("the session run has fewer than 3 notifications")
    last = ev[-1]
    earlier = [e for e in ev if e["t"] < last["t"]]
    before = {a["id"] for a in annotations(LONG_REC)}
    open_lab(page, LONG_REC, run=_run())
    page.locator(".rv-row", has_text=last["text"]).first.wait_for()
    _post_verdict_on(page, last["text"])
    new = [a for a in annotations(LONG_REC) if a["id"] not in before]
    created_reviews.extend((LONG_REC, a["id"]) for a in new)
    autos = [a for a in new if a.get("auto")]
    # every earlier notification without a verdict (identical events share one verdict, as the matching key does) is counted correct
    assert autos and len(new) == len(autos) + 1 and len(autos) <= len(earlier)
    assert all(a["verdict"] == "correct" and a["t"] < last["t"] for a in autos)
    row = page.locator(".rv-row.auto").first
    row.wait_for()
    assert page.locator(".rv-row.auto").count() == len(autos)
    assert row.get_attribute("title") == "counted correct (reviewed later items)"
    assert row.locator(".rv-v.correct").get_attribute("aria-pressed") == "true"
    # the export carries them
    exp = api(f"/api/reviews/export?recording={LONG_REC}")["recordings"][0]["annotations"]
    assert sum(1 for a in exp if a.get("auto")) == len(autos)
    # the user takes one over: the verdict changes and `auto` drops, the others stay
    first = autos[0]
    page.locator(".rv-row.auto").first.locator(".rv-v.incorrect").click()
    page.wait_for_timeout(1200)
    now = {a["id"]: a for a in annotations(LONG_REC)}
    assert now[first["id"]]["verdict"] == "incorrect" and "auto" not in now[first["id"]]
    assert page.locator(".rv-row.auto").count() == len(autos) - 1
    # deleting the later verdict keeps the auto ones
    later = next(a for a in new if not a.get("auto"))
    page.locator(".rv-row", has_text=last["text"]).first.locator(".rv-v.correct").click()   # toggle off = delete
    page.wait_for_timeout(1200)
    ids = {a["id"] for a in annotations(LONG_REC)}
    assert later["id"] not in ids and all(a["id"] in ids for a in autos)
    assert not page.errors, page.errors
