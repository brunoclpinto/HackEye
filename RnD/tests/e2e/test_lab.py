"""Lab browser tests for v26.1.5 (CONTRACTS sections 12.1, 12.2, 13)."""
import gzip
import json
import re
import urllib.request

import pytest

from conftest import BASE, FULL_RUN, LONG_REC, SHORT_REC, annotations, api, audio_log, open_lab, seek


def long_run_events():
    ev = api(f"/api/runs/{FULL_RUN}/events.json")["events"]
    return [e for e in ev if e["type"] == "speech"]


def first_gesture(page):
    page.mouse.click(5, 5)           # any pointerdown anywhere unlocks audio (12.2)
    page.wait_for_timeout(150)


def add_via_ui(page, text, role="danger"):
    """Click '+ Add speech at playhead', return the time-field text, fill the text, submit."""
    page.click("#rvAddBtn")
    tfield = page.input_value("#rvAddT")
    page.fill("#rvAddText", text)
    page.select_option("#rvAddRole", role)
    page.click("#rvAddSubmit")
    page.wait_for_function("() => document.querySelector('#rvAddForm').hidden")
    return tfield


# ---------------------------------------------------------------- 12.2 defaults

def test_range_defaults_to_full_length(page):
    open_lab(page, SHORT_REC)
    assert page.input_value("#rangeStart") == "0:00"
    assert page.input_value("#rangeEnd") == "0:03"
    page.goto("about:blank")
    open_lab(page, LONG_REC)
    seek(page, 120.0)                # moving the playhead must not move the range
    assert page.input_value("#rangeStart") == "0:00"
    assert page.input_value("#rangeEnd") == "51:33"   # 3093.17 s


def test_audio_armed_and_unlocked_by_first_gesture(page):
    open_lab(page, SHORT_REC)
    assert "Audio on" in page.inner_text("#audioBtn")
    assert page.evaluate("Array.isArray(window.__labAudioLog)")
    assert page.evaluate("window.__acs.filter(c => c.state === 'running').length") == 0, "unlocked before any gesture"
    assert page.is_checked("#speechChk") and page.is_checked("#tonesChk")
    first_gesture(page)
    assert page.evaluate("window.__acs.length") == 1
    assert page.evaluate("window.__acs[0].state") == "running"
    page.mouse.click(6, 6)           # unlock happens once
    assert page.evaluate("window.__acs.length") == 1
    page.click("#audioBtn")          # toggle
    assert "Audio off" in page.inner_text("#audioBtn")
    page.click("#audioBtn")
    assert "Audio on" in page.inner_text("#audioBtn")


# ---------------------------------------------------------------- add form

def test_add_twice_at_two_paused_times(page, created_reviews):
    open_lab(page, SHORT_REC)
    before = {a["id"] for a in annotations(SHORT_REC)}
    seek(page, 1.0)
    t1 = add_via_ui(page, "e2e first")
    seek(page, 2.2)
    t2 = add_via_ui(page, "e2e second")
    new = [a for a in annotations(SHORT_REC) if a["id"] not in before]
    created_reviews.extend((SHORT_REC, a["id"]) for a in new)
    assert (t1, t2) == ("0:01.0", "0:02.2")
    got = {a["text"]: a["t"] for a in new}
    assert got["e2e first"] == pytest.approx(1.0, abs=0.06)
    assert got["e2e second"] == pytest.approx(2.2, abs=0.06), got


def test_add_form_follows_playhead_while_open(page):
    open_lab(page, SHORT_REC)
    seek(page, 0.5)
    page.click("#rvAddBtn")
    assert "following" in page.inner_text("#rvAddForm")
    seek(page, 1.7)
    assert page.input_value("#rvAddT") == "0:01.7"
    for _ in range(6):               # frame steps also drive it
        page.click("#stepFwd")
        page.wait_for_timeout(120)
    assert page.input_value("#rvAddT") != "0:01.7"
    page.fill("#rvAddT", "0:02.5")   # a manual edit stops the tracking...
    assert "following" not in page.inner_text("#rvAddForm")
    seek(page, 0.9)                  # ...until the next seek
    assert page.input_value("#rvAddT") == "0:00.9"
    page.click("#rvAddCancel")


def test_add_twice_with_long_run_loaded(page, created_reviews):
    """The user's scenario: the full run is loaded, two phrases at 0.2 s and 6.6 s."""
    open_lab(page, LONG_REC, run=FULL_RUN)
    before = {a["id"] for a in annotations(LONG_REC)}
    seek(page, 0.2)
    add_via_ui(page, "e2e long first", "context")
    seek(page, 6.6)
    t2 = add_via_ui(page, "e2e long second", "context")
    new = [a for a in annotations(LONG_REC) if a["id"] not in before]
    created_reviews.extend((LONG_REC, a["id"]) for a in new)
    got = {a["text"]: a["t"] for a in new}
    assert t2 == "0:06.6"
    assert got["e2e long second"] == pytest.approx(6.6, abs=0.06), got


def test_slow_run_load_does_not_move_the_add_form_time(page, created_reviews):
    """Issue 4. Reload with a stale #t=0.2 while the run is still loading (slow link): the user
    scrubs to 6.6 s and opens the add form; when the run finally arrives the page used to seek
    back to the hash time, silently resetting the form (paused + 'seeked') to 0.2."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 20,
             "downloadThroughput": 8 * 1024 * 1024, "uploadThroughput": -1})
    page.goto(f"{BASE}/#rec={LONG_REC}&run={FULL_RUN}&t=0.2")
    page.wait_for_function("() => { const v = document.querySelector('#video'); return v && v.readyState >= 2; }")
    seek(page, 6.6)
    page.click("#rvAddBtn")
    assert page.input_value("#rvAddT") == "0:06.6"
    in_flight = page.evaluate("document.querySelector('#runBadge').textContent === ''")
    page.wait_for_function("() => document.querySelector('#runBadge').textContent.includes('run ')", timeout=120_000)
    page.wait_for_timeout(1500)
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
    assert page.input_value("#rvAddT") == "0:06.6", f"form time jumped (run was still loading when form opened: {in_flight})"
    assert abs(page.evaluate("document.querySelector('#video').currentTime") - 6.6) < 0.1
    before = {a["id"] for a in annotations(LONG_REC)}
    page.fill("#rvAddText", "e2e slow load")
    page.click("#rvAddSubmit")
    page.wait_for_function("() => document.querySelector('#rvAddForm').hidden")
    new = [a for a in annotations(LONG_REC) if a["id"] not in before]
    created_reviews.extend((LONG_REC, a["id"]) for a in new)
    assert new[0]["t"] == pytest.approx(6.6, abs=0.06)


def test_autofill_is_quick_on_a_slow_link(page):
    """Issue 3. Over a slow link the 118 MB hazards.json used to be needed before auto-fill had any frame."""
    ev = next(e for e in long_run_events() if e["role"] in ("danger", "final") and e["t"] > 20)
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 20,
             "downloadThroughput": 8 * 1024 * 1024, "uploadThroughput": -1})
    page.goto(f"{BASE}/#rec={LONG_REC}&run={FULL_RUN}&t={ev['t'] + 0.001}")
    page.wait_for_function("() => { const v = document.querySelector('#video'); return v && v.readyState >= 2; }")
    # The run must be usable within seconds (events.json is small); it used to appear only after ~15 s here.
    page.wait_for_function("() => document.querySelector('#runBadge').textContent.includes('run ')", timeout=6_000)
    page.click("#rvAddBtn")
    page.click("#rvAddAuto")
    # ~15 s of download on this link if the whole file were needed; the one-frame request is milliseconds.
    page.wait_for_function("() => document.querySelector('#rvAddText').value.length > 0", timeout=5_000)
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})


# ---------------------------------------------------------------- auto-fill

def test_autofill_on_long_run(page):
    sp = [e for e in long_run_events() if e["role"] in ("danger", "final") and e["t"] > 20][:3]
    assert sp
    open_lab(page, LONG_REC, run=FULL_RUN)
    for ev in sp:
        seek(page, ev["t"] + 0.001)  # exactly where the Lab's frame step lands
        page.click("#rvAddBtn")
        page.fill("#rvAddText", "")
        page.click("#rvAddAuto")
        page.wait_for_function("() => document.querySelector('#rvAddText').value.length > 0", timeout=20_000)
        text = page.input_value("#rvAddText")
        role = page.input_value("#rvAddRole")
        assert text and role in ("final", "danger", "feature", "context", "surface", "other")
        info = page.inner_text("#rvAddAutoInfo")
        assert re.match(r"\d+/\d+", info), info
        page.click("#rvAddCancel")


# ---------------------------------------------------------------- audio of reviews

def test_added_phrase_spoken_after_rewind(page, created_reviews):
    open_lab(page, SHORT_REC)
    before = {a["id"] for a in annotations(SHORT_REC)}
    seek(page, 1.2)
    add_via_ui(page, "e2e spoken bench", "feature")
    created_reviews.extend((SHORT_REC, a["id"]) for a in annotations(SHORT_REC) if a["id"] not in before)
    seek(page, 0.2)                  # rewind past the phrase
    page.click("#playBtn")           # (also the first gesture)
    page.wait_for_function("() => document.querySelector('#video').currentTime > 1.6", timeout=15_000)
    page.wait_for_timeout(200)
    spoken = page.evaluate("window.__spoken.map(s => s.text)")
    assert "e2e spoken bench" in spoken, spoken
    log = [e for e in audio_log(page) if e.get("text") == "e2e spoken bench"]
    assert log and log[0]["source"] == "added" and log[0]["type"] == "speech"
    assert log[0]["mediaT"] == pytest.approx(1.2, abs=0.35)
    assert page.is_checked("#reviewPreviewChk")     # "Hear review edits" is on by default


def test_removed_system_phrase_is_not_spoken(page, created_reviews):
    run = api(f"/api/runs/{FULL_RUN}")
    judged = {(round(a["event"]["t"], 3), a["event"]["text"]) for a in annotations(LONG_REC) if a["kind"] == "verdict"}
    ev = next(e for e in long_run_events()      # an event the user has NOT judged: never touch their verdicts
              if e["role"] in ("context", "feature") and 10 < e["t"] < 200 and (round(e["t"], 3), e["text"]) not in judged)
    snap = {k: ev[k] for k in ("t", "text", "role", "trackId", "urgency", "clock") if k in ev}
    ann = api(f"/api/recordings/{LONG_REC}/reviews", "POST",
              {"kind": "verdict", "verdict": "remove", "t": ev["t"], "event": snap,
               "runId": FULL_RUN, "collisionVersion": run.get("collisionVersion")})
    created_reviews.append((LONG_REC, ann["id"]))

    def play_through():
        page.evaluate("window.__spoken.length = 0")
        seek(page, ev["t"] - 3)
        page.click("#playBtn")
        page.wait_for_function(f"() => document.querySelector('#video').currentTime > {ev['t'] + 0.8}", timeout=20_000)
        page.click("#playBtn")       # pause
        return page.evaluate("window.__spoken.map(s => s.text)")

    open_lab(page, LONG_REC, run=FULL_RUN, t=ev["t"] - 3)
    # Positive control first: with the preview off the system's own phrase is spoken...
    page.uncheck("#reviewPreviewChk")
    assert ev["text"] in play_through(), "control: the system phrase should be spoken with the preview off"
    # ...and with it on (the default) the phrase marked ⊘ is skipped.
    page.check("#reviewPreviewChk")
    assert ev["text"] not in play_through(), "removed phrase was spoken"
    assert any(e.get("source") == "system" for e in audio_log(page))


# ---------------------------------------------------------------- 12.1 windowed hazards + gzip

def test_long_run_uses_windowed_hazards_and_gzip(page):
    open_lab(page, LONG_REC, run=FULL_RUN)
    seek(page, 1500.0)               # outside the first window -> refetch
    page.wait_for_function("() => !document.querySelector('#hud').hidden", timeout=20_000)
    urls = [u for u, _ in page.requests]
    assert not any(re.search(r"/hazards\.json", u) for u in urls), "full hazards.json requested"
    wins = [u for u in urls if "/hazards?" in u]
    assert wins, urls
    assert any(re.search(r"from=1[34]\d\d", u) for u in wins), wins
    for u in wins:
        assert page.responses[u].get("content-encoding") == "gzip", (u, page.responses[u])
    ev_url = next(u for u in page.responses if u.endswith("/events.json"))
    assert page.responses[ev_url].get("content-encoding") == "gzip"


def _get(path, accept_gzip=False):
    req = urllib.request.Request(BASE + path, headers={"Accept-Encoding": "gzip"} if accept_gzip else {})
    return urllib.request.urlopen(req, timeout=60)


def test_windowed_endpoints():
    r = _get(f"/api/runs/{FULL_RUN}/hazards?from=100&to=110", accept_gzip=True)
    assert r.headers["Content-Encoding"] == "gzip"
    d = json.loads(gzip.decompress(r.read()))
    assert d["from"] == 100 and d["to"] == 110 and d["gridW"] and d["gridH"]
    ts = [f["t"] for f in d["frames"]]
    assert ts and min(ts) >= 100 and max(ts) <= 110
    fr = api(f"/api/runs/{FULL_RUN}/frame?t=100.05")["frame"]
    assert fr["t"] <= 100.05 and 100.05 - fr["t"] < 0.5
    with pytest.raises(AssertionError, match="422"):
        api(f"/api/runs/{FULL_RUN}/hazards?from=0&to=601")
    with pytest.raises(AssertionError, match="404"):
        api(f"/api/runs/{FULL_RUN}/frame?t=99999")
