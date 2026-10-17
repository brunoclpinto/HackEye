"""Lab browser tests: v26.1.5 (CONTRACTS 12.1, 12.2, 13) and v26.1.6 notification review / beeps (14.2, 14.3)."""
import gzip
import json
import re
import urllib.request

import pytest

from conftest import BASE, HOOKS, LONG_REC, SHORT_REC, annotations, api, audio_log, open_lab, seek


import os
import shutil
import time

# Every test that needs an analysed run uses the one the session analyses itself (version bumps wipe the Lab's runs,
# so no test may depend on a user's run). FULL_RUN is filled in by the autouse fixture below.
FULL_RUN = None
LONG_RANGE = (0, 120)        # seconds of 4929 analysed at 6 fps: long enough for windowing (HALF_S = 90) and every review test
LAB_DIR_MOUNT = os.environ.get("LAB_DIR_MOUNT", "")   # host debug/lab, mounted by run.sh: lets the session delete its own run


@pytest.fixture(scope="session", autouse=True)
def _session_run():
    """Analyse 4929 0-120 s (default model, fps 6; ~30 s) once; delete the run directory at the end if this session created it."""
    global FULL_RUN
    model = next(m["path"] for m in api("/api/models")["models"] if m["default"])
    known = {r["id"] for r in api("/api/runs")}
    run = api("/api/runs", "POST", {"recording": LONG_REC, "start": LONG_RANGE[0], "end": LONG_RANGE[1], "fps": 6, "model": model})
    created = run["id"] not in known
    t0 = time.time()
    while run["status"] not in ("done", "error", "cancelled") and time.time() - t0 < 400:
        time.sleep(1)
        run = api(f"/api/runs/{run['id']}")
    assert run["status"] == "done", run
    FULL_RUN = run["id"]
    yield FULL_RUN
    path = os.path.join(LAB_DIR_MOUNT, "runs", FULL_RUN) if LAB_DIR_MOUNT else ""
    if created and path and os.path.isdir(path):
        shutil.rmtree(path)


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
    ev = next(e for e in long_run_events() if e["role"] in ("danger", "final") and e["t"] > 10)
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
    sp = [e for e in long_run_events() if e["role"] in ("danger", "final") and e["t"] > 10][:3]
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
    far = LONG_RANGE[1] - 5.0        # more than HALF_S (90 s) from the first window -> refetch
    seek(page, far)
    page.wait_for_function("() => !document.querySelector('#hud').hidden", timeout=20_000)
    urls = [u for u, _ in page.requests]
    assert not any(re.search(r"/hazards\.json", u) for u in urls), "full hazards.json requested"
    wins = [u for u in urls if "/hazards?" in u]
    assert wins, urls
    froms = [float(re.search(r"from=(-?[\d.]+)", u).group(1)) for u in wins]
    assert any(f >= far - 100 for f in froms), (far, wins)      # a window centred near the far playhead was fetched
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


# ---------------------------------------------------------------- 14.2 notification review: beeps

BEEP_T0, BEEP_T1 = 40.0, 100.0
BEEP_TEXT = "beeps · e2e pole at 12 · 9→2 steps"
BEEP_FREQ = 1234.5          # distinctive, so injected tones can't be confused with real ones
BEEP_TRACK = 987654


def _beep_events():
    """A synthetic beeps episode + its tones (gapless every 0.5 s over the first 6 s), injected into events.json."""
    beeps = {"type": "beeps", "t": BEEP_T0, "tEnd": BEEP_T1, "trackId": BEEP_TRACK, "label": "pole", "clock": 12,
             "minSteps": 2, "role": "danger", "text": BEEP_TEXT}
    tones = [{"t": BEEP_T0 + 0.5 * i, "type": "tone", "role": "danger", "trackId": BEEP_TRACK, "urgency": "danger",
              "pan": 0.0, "frequencyHz": BEEP_FREQ, "durationSeconds": 0.08} for i in range(12)]
    return beeps, tones


def inject_beeps(page):
    """Older runs have no beeps events (and the collision worker's change may not have landed): add ours on the wire."""
    beeps, tones = _beep_events()

    def handle(route):
        resp = route.fetch()
        doc = resp.json()
        doc["events"] = [e for e in doc["events"] if e.get("trackId") != BEEP_TRACK] + [beeps] + tones
        route.fulfill(response=resp, json=doc)

    page.route(f"**/api/runs/{FULL_RUN}/events.json", handle)


def beep_snapshot():
    beeps, _ = _beep_events()
    return {k: beeps[k] for k in ("t", "text", "role", "trackId", "type", "tEnd", "label", "minSteps")}


def post_beep_verdict(verdict, created):
    run = api(f"/api/runs/{FULL_RUN}")
    ann = api(f"/api/recordings/{LONG_REC}/reviews", "POST",
              {"kind": "verdict", "verdict": verdict, "t": BEEP_T0, "event": beep_snapshot(),
               "runId": FULL_RUN, "collisionVersion": run.get("collisionVersion")})
    created.append((LONG_REC, ann["id"]))
    return ann


def beep_tones(page, source="system"):
    return [e for e in audio_log(page) if e["type"] == "tone" and e.get("freq") == pytest.approx(BEEP_FREQ, abs=0.1)
            and e["source"] == source]


def play_window(page, a, b):
    page.evaluate("window.__labAudioLog.length = 0")
    seek(page, a)
    page.click("#playBtn")
    page.wait_for_function(f"() => document.querySelector('#video').currentTime > {b}", timeout=30_000)
    page.click("#playBtn")        # pause


def test_renamed_labels(page):
    open_lab(page, SHORT_REC)
    assert page.inner_text("#reviewPanel h2") == "Notification review"
    assert page.get_attribute("#reviewPanel", "aria-label") == "Notification review"
    assert "Beeps" in page.inner_text("label:has(#tonesChk)") and "Tones" not in page.inner_text("label:has(#tonesChk)")
    assert "notification" in page.inner_text("#rvAddBtn").lower() and "speech" not in page.inner_text("#rvAddBtn").lower()
    assert page.get_attribute("#rvExport", "download") == "notification-reviews.json"
    assert "Speech review" not in page.inner_text("body")
    page.click("#rvAddBtn")
    assert page.eval_on_selector_all("#rvAddType option", "os => os.map(o => o.value)") == ["speech", "beeps"]


def test_counts_line_and_old_runs_without_beeps(page):
    """Without injection the run shows its own notifications and a '<n> notifications · <m> beeps' count."""
    open_lab(page, LONG_REC, run=FULL_RUN)
    page.wait_for_selector("#rvList .rv-row")
    assert re.fullmatch(r"\d+ notifications · \d+ beeps?s?", page.inner_text("#rvTotal")), page.inner_text("#rvTotal")
    assert page.is_visible("#timeline") and page.errors == []


def test_beeps_row_renders_and_saves_verdict(page, created_reviews):
    inject_beeps(page)
    open_lab(page, LONG_REC, run=FULL_RUN)
    row = page.locator(".rv-row.beeps", has_text="e2e pole")
    row.wait_for()
    assert "🔔" in row.inner_text()
    assert "60.0 s" in row.inner_text()           # duration of the episode
    m = re.fullmatch(r"(\d+) notifications · (\d+) beeps?s?", page.inner_text("#rvTotal"))
    assert m and int(m.group(2)) >= 1
    before = {a["id"] for a in annotations(LONG_REC)}
    row.locator(".rv-v.correct").click()
    row.locator("textarea").fill("e2e beep note")
    page.wait_for_timeout(1200)       # note autosave (600 ms)
    new = [a for a in annotations(LONG_REC) if a["id"] not in before]
    created_reviews.extend((LONG_REC, a["id"]) for a in new)
    assert len(new) == 1
    a = new[0]
    assert a["verdict"] == "correct" and a["note"] == "e2e beep note"
    assert a["event"]["type"] == "beeps" and a["event"]["text"] == BEEP_TEXT and a["event"]["tEnd"] == BEEP_T1
    assert a["runId"] == FULL_RUN
    # reload: the verdict stays attached through the matching key
    open_lab(page, LONG_REC, run=FULL_RUN)
    row = page.locator(".rv-row.beeps", has_text="e2e pole")
    row.wait_for()
    assert "v-correct" in row.get_attribute("class")
    # toggling the active one deletes it again
    row.locator(".rv-v.correct").click()
    page.wait_for_function("() => !document.querySelector('.rv-row.beeps.v-correct')")


def test_remove_on_beeps_row_silences_its_tones(page, created_reviews):
    post_beep_verdict("remove", created_reviews)
    inject_beeps(page)
    open_lab(page, LONG_REC, run=FULL_RUN, t=BEEP_T0 - 1)
    page.locator(".rv-row.beeps.v-remove", has_text="e2e pole").wait_for()
    page.mouse.click(5, 5)
    # control: preview off -> the episode's tones are scheduled
    page.uncheck("#reviewPreviewChk")
    play_window(page, BEEP_T0 - 1, BEEP_T0 + 2.2)
    assert len(beep_tones(page)) >= 3, audio_log(page)
    # preview on (default) -> silenced
    page.check("#reviewPreviewChk")
    play_window(page, BEEP_T0 - 1, BEEP_T0 + 2.2)
    assert beep_tones(page) == [], beep_tones(page)
    # and removing the ⊘ brings them back
    page.locator(".rv-row.beeps", has_text="e2e pole").locator(".rv-v.remove").click()
    page.wait_for_function("() => !document.querySelector('.rv-row.beeps.v-remove')")
    play_window(page, BEEP_T0 - 1, BEEP_T0 + 2.2)
    assert len(beep_tones(page)) >= 3


def test_add_beeps_entry_and_hear_it_in_preview(page, created_reviews):
    open_lab(page, SHORT_REC)
    before = {a["id"] for a in annotations(SHORT_REC)}
    seek(page, 0.4)
    page.click("#rvAddBtn")
    assert page.is_hidden("#rvAddEndRow")
    page.select_option("#rvAddType", "beeps")
    page.wait_for_selector("#rvAddEndRow", state="visible")
    assert page.input_value("#rvAddEnd") == "0:03.2"      # default end = start + 3 s, clamped to the recording (3.295)
    seek(page, 1.9)                                      # a beeps entry has two times: seeking leaves the start alone
    assert page.input_value("#rvAddT") == "0:00.4"
    page.click("#rvAddEndHead")
    assert page.input_value("#rvAddEnd") == "0:01.9"
    page.fill("#rvAddText", "beeps · e2e bollard at 1")
    page.click("#rvAddSubmit")
    page.wait_for_function("() => document.querySelector('#rvAddForm').hidden")
    new = [a for a in annotations(SHORT_REC) if a["id"] not in before]
    created_reviews.extend((SHORT_REC, a["id"]) for a in new)
    assert len(new) == 1
    a = new[0]
    assert a["type"] == "beeps" and a["kind"] == "added" and a["t"] == pytest.approx(0.4, abs=0.06)
    assert a["tEnd"] == pytest.approx(1.9, abs=0.06) and a["text"] == "beeps · e2e bollard at 1"
    row = page.locator(".rv-row.added.beeps")
    assert "🔔" in row.inner_text() and row.locator("input[aria-label='End time']").count() == 1
    # preview: parking-style beeps over [t, tEnd], tagged "added"
    seek(page, 0.0)
    page.evaluate("window.__labAudioLog.length = 0")
    page.click("#playBtn")
    page.wait_for_function("() => document.querySelector('#video').currentTime > 2.1", timeout=15_000)
    page.click("#playBtn")
    added = [e for e in audio_log(page) if e["type"] == "tone" and e["source"] == "added"]
    assert len(added) >= 3, audio_log(page)
    assert all(0.35 <= e["mediaT"] <= 1.95 for e in added), added
    gaps = [b["mediaT"] - a_["mediaT"] for a_, b in zip(added, added[1:])]
    assert all(g == pytest.approx(0.5, abs=0.01) for g in gaps), gaps       # medium, steady rate
    # with the preview off they are not played
    page.uncheck("#reviewPreviewChk")
    seek(page, 0.0)
    page.evaluate("window.__labAudioLog.length = 0")
    page.click("#playBtn")
    page.wait_for_function("() => document.querySelector('#video').currentTime > 2.1", timeout=15_000)
    page.click("#playBtn")
    assert [e for e in audio_log(page) if e["source"] == "added"] == []


def test_timeline_draws_beep_bars(page):
    inject_beeps(page)
    open_lab(page, LONG_REC, run=FULL_RUN)
    page.wait_for_function("() => +document.querySelector('#timeline').dataset.beeps >= 1")
    run = api(f"/api/runs/{FULL_RUN}")["request"]
    px = page.evaluate("""([start, end, t]) => {
        const c = document.querySelector('#timeline'), ctx = c.getContext('2d');
        const x = Math.round((t - start) / (end - start) * c.width), y = Math.round(c.height * (c.clientHeight - 32 + 4 + 5) / c.clientHeight);
        return Array.from(ctx.getImageData(x, y, 1, 1).data);
    }""", [run["start"], run["end"], (BEEP_T0 + BEEP_T1) / 2])
    r, g, b, _ = px
    assert r > 200 and 100 < g < 180 and b < 80, px      # the danger colour (#ff8c1a), not the panel background


# ---------------------------------------------------------------- 14.3 backend validation

def test_beeps_annotation_validation(created_reviews):
    base = f"/api/recordings/{SHORT_REC}/reviews"

    def post(body):
        try:
            return api(base, "POST", body)
        except AssertionError as e:
            return str(e)

    ok = post({"kind": "added", "type": "beeps", "t": 0.5, "tEnd": 2.0, "text": "beeps · e2e api", "role": "danger"})
    assert isinstance(ok, dict) and ok["type"] == "beeps" and ok["tEnd"] == 2.0
    created_reviews.append((SHORT_REC, ok["id"]))
    for bad in ({"tEnd": None}, {"tEnd": 0.5}, {"tEnd": 0.2}, {"tEnd": 99}, {"type": "tone"}):
        body = {"kind": "added", "type": "beeps", "t": 0.5, "tEnd": 2.0, "text": "beeps · e2e bad", "role": "danger", **bad}
        assert "422" in str(post(body)), bad
    assert "422" in str(post({"kind": "added", "type": "speech", "t": 0.5, "tEnd": 2.0, "text": "x"}))
    # an old-style annotation (no type) stays valid and means speech
    old = post({"kind": "added", "t": 1.0, "text": "e2e old style", "role": "context"})
    assert isinstance(old, dict)
    created_reviews.append((SHORT_REC, old["id"]))
    assert old.get("type", "speech") == "speech" and "tEnd" not in old
    # PUT: tEnd must stay after t
    assert "422" in str(api_put(f"{base}/{ok['id']}", {"tEnd": 0.1}))
    assert api_put(f"{base}/{ok['id']}", {"tEnd": 2.5})["tEnd"] == 2.5
    exp = api(f"/api/reviews/export?recording={SHORT_REC}")["recordings"][0]["annotations"]
    by_id = {a["id"]: a for a in exp}
    assert by_id[ok["id"]]["type"] == "beeps" and by_id[ok["id"]]["tEnd"] == 2.5
    assert by_id[old["id"]].get("type", "speech") == "speech"
    # verdict snapshots carry type/tEnd and validate tEnd
    ann = api(f"/api/recordings/{LONG_REC}/reviews", "POST",
              {"kind": "verdict", "verdict": "incorrect", "t": BEEP_T0, "event": beep_snapshot(),
               "runId": FULL_RUN})
    created_reviews.append((LONG_REC, ann["id"]))
    assert ann["event"]["type"] == "beeps" and ann["event"]["tEnd"] == BEEP_T1
    bad = {**beep_snapshot(), "tEnd": BEEP_T0 - 1}
    assert "422" in str(post_raw(f"/api/recordings/{LONG_REC}/reviews", {"kind": "verdict", "verdict": "correct", "t": BEEP_T0, "event": bad, "runId": FULL_RUN}))


def api_put(path, body):
    try:
        return api(path, "PUT", body)
    except AssertionError as e:
        return str(e)


def post_raw(path, body):
    try:
        return api(path, "POST", body)
    except AssertionError as e:
        return str(e)


# ---------------------------------------------------------------- classes & safety levels (view-only mask styling)

T_CLS = 31.0     # inside the session run (0-120 s)


@pytest.fixture
def cls_run(_session_run):
    return _session_run


@pytest.fixture
def display_guard(cls_run):
    """Snapshot the server-saved display prefs of the run's mapping and restore them afterwards."""
    mapping = api(f"/api/runs/{cls_run}/classes")["mapping"]
    before = api(f"/api/display/{mapping}")["saved"]
    yield mapping
    for section in ("classes", "levels"):
        if before[section]:
            api(f"/api/display/{mapping}/{section}", "PUT", {section: before[section]})
        else:
            api(f"/api/display/{mapping}/{section}", "DELETE")


def class_probe(page, run):
    """Pick the largest class with level >= 1 in the frame at T_CLS and a grid pixel whose 3x3 neighbourhood is all it.
    Returns {id, name, level, gx, gy, w, h}."""
    idx = api(f"/api/runs/{run}/frame?t={T_CLS}")["frame"]["index"]
    info = api(f"/api/runs/{run}/classes")
    grid = page.evaluate("""async (url) => {
        const img = new Image(); img.src = url; await img.decode();
        const c = document.createElement('canvas'); c.width = img.naturalWidth; c.height = img.naturalHeight;
        const x = c.getContext('2d'); x.drawImage(img, 0, 0);
        const d = x.getImageData(0, 0, c.width, c.height).data;
        const g = []; for (let i = 0; i < d.length; i += 4) g.push(d[i]);
        return {w: c.width, h: c.height, g};
    }""", f"/api/runs/{run}/frames/{idx}/classes.png")
    w, h, g = grid["w"], grid["h"], grid["g"]
    count = {}
    for v in g:
        count[v] = count.get(v, 0) + 1
    lv = {c["id"]: c["level"] for c in info["classes"]}
    names = {c["id"]: c["name"] for c in info["classes"]}
    for cid in sorted(count, key=lambda k: -count[k]):
        if lv[cid] < 1:
            continue
        for gy in range(2, h - 2):
            for gx in range(2, w - 2):
                if all(g[(gy + dy) * w + gx + dx] == cid for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                    return {"id": cid, "name": names[cid], "level": lv[cid], "gx": gx, "gy": gy, "w": w, "h": h}
    raise AssertionError("no class with level >= 1 and a solid 3x3 patch in the test frame")


def prepare_lab(page, run):
    open_lab(page, LONG_REC, t=T_CLS, run=run)
    seek(page, T_CLS)
    for sel in ("#regionChk", "#laneChk", "#horizonChk", "#hazardChk"):   # leave only the mask on the canvas
        page.uncheck(sel)
    page.evaluate("""() => { const r = document.querySelector('#maskOpacity'); r.value = 1; r.dispatchEvent(new Event('input')); }""")
    page.evaluate("document.querySelector('#secClasses').open = true")
    page.wait_for_function("document.querySelectorAll('#clsClasses tr').length > 0")


def px(page, p):
    """RGBA of the overlay canvas where the probe pixel's grid cell is."""
    return page.evaluate("""(p) => { const c = document.querySelector('#overlay'); const x = c.getContext('2d');
        const d = x.getImageData(Math.floor((p.gx + 0.5) * c.width / p.w), Math.floor((p.gy + 0.5) * c.height / p.h), 1, 1).data;
        return [d[0], d[1], d[2], d[3]]; }""", p)


def wait_px(page, p, cond):
    page.wait_for_function("""([p, cond]) => { const c = document.querySelector('#overlay'); const x = c.getContext('2d');
        const d = x.getImageData(Math.floor((p.gx + 0.5) * c.width / p.w), Math.floor((p.gy + 0.5) * c.height / p.h), 1, 1).data;
        return new Function('a', 'return ' + cond)(Array.from(d)); }""", arg=[p, cond])


def fresh_page(browser):
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    ctx.add_init_script(HOOKS)
    pg = ctx.new_page()
    pg.set_default_timeout(60_000)
    pg.on("dialog", lambda d: d.accept())
    return ctx, pg


def test_classes_panel_renders_and_checkbox_hides_pixels(page, cls_run, display_guard):
    prepare_lab(page, cls_run)
    assert page.locator("#clsClasses tr").count() == 48
    assert page.locator("#clsLevels tr").count() == 5
    p = class_probe(page, cls_run)
    wait_px(page, p, "a[3] > 0")
    assert page.is_checked(f'#clsClasses input[type=checkbox][data-cls="{p["id"]}"]')
    page.uncheck(f'#clsClasses input[type=checkbox][data-cls="{p["id"]}"]')
    wait_px(page, p, "a[3] === 0")
    assert not page.is_hidden("#clsEdited")
    page.check(f'#clsClasses input[type=checkbox][data-cls="{p["id"]}"]')
    wait_px(page, p, "a[3] > 0")
    # Show none / Show all / filter
    page.click("#clsNone")
    wait_px(page, p, "a[3] === 0")
    page.click("#clsAll")
    wait_px(page, p, "a[3] > 0")
    page.fill("#clsFilter", p["name"])
    assert page.locator("#clsClasses tr:not([hidden])").count() >= 1
    assert page.locator("#clsClasses tr:not([hidden])").count() < 48
    page.fill("#clsFilter", "")
    assert page.locator("#clsClasses tr:not([hidden])").count() == 48


def test_level_colour_opacity_and_class_level(page, cls_run, display_guard):
    prepare_lab(page, cls_run)
    p = class_probe(page, cls_run)
    wait_px(page, p, "a[3] > 0")
    before = px(page, p)
    page.fill(f'#clsLevels input[type=color][data-level="{p["level"]}"]', "#12ab34")
    wait_px(page, p, "a[0] === 18 && a[1] === 171 && a[2] === 52 && a[3] === 255")
    assert px(page, p)[:3] != before[:3]
    # level opacity multiplies into the alpha
    page.evaluate("""(l) => { const r = document.querySelector(`#clsLevels input[type=range][data-level="${l}"]`);
        r.value = 0.5; r.dispatchEvent(new Event('input', {bubbles: true})); }""", p["level"])
    wait_px(page, p, "a[3] >= 127 && a[3] <= 129")
    # moving the class to level 0 ("ignored", opacity 0 by default) hides it; the swatch follows
    page.select_option(f'#clsClasses select[data-cls="{p["id"]}"]', "0")
    wait_px(page, p, "a[3] === 0")
    # reset (asks for confirmation)
    page.once("dialog", lambda d: d.accept())
    page.click("#clsReset")
    wait_px(page, p, "a[3] === 255 && a[0] === %d" % before[0])


def test_classes_settings_persist_across_reload(page, cls_run, display_guard):
    prepare_lab(page, cls_run)
    p = class_probe(page, cls_run)
    wait_px(page, p, "a[3] > 0")
    page.uncheck(f'#clsClasses input[type=checkbox][data-cls="{p["id"]}"]')
    page.fill(f'#clsLevels input[type=color][data-level="{p["level"]}"]', "#0000ff")
    wait_px(page, p, "a[3] === 0")
    page.reload()
    page.wait_for_function("() => { const v = document.querySelector('#video'); return v && v.readyState >= 2 && v.duration > 0; }")
    page.evaluate("document.querySelector('#secClasses').open = true")
    page.wait_for_function("document.querySelectorAll('#clsClasses tr').length > 0")
    assert not page.is_checked(f'#clsClasses input[type=checkbox][data-cls="{p["id"]}"]')
    assert page.input_value(f'#clsLevels input[type=color][data-level="{p["level"]}"]') == "#0000ff"
    assert not page.is_hidden("#clsEdited")
    assert page.text_content("#clsStatC") == "unsaved changes" and page.is_enabled("#clsSaveC")
    page.click("#clsDiscC")                              # drop the class draft only
    assert page.is_checked(f'#clsClasses input[type=checkbox][data-cls="{p["id"]}"]')
    assert page.is_disabled("#clsSaveC") and page.is_enabled("#clsSaveL")
    assert api(f"/api/display/{display_guard}")["saved"]["classes"] == {}   # nothing was saved


def test_save_buttons_share_view_with_a_fresh_browser(browser, page, cls_run, display_guard):
    prepare_lab(page, cls_run)
    p = class_probe(page, cls_run)
    cid = f'{p["id"]}'
    assert page.is_disabled("#clsSaveC") and page.is_disabled("#clsSaveL")
    page.uncheck(f'#clsClasses input[type=checkbox][data-cls="{cid}"]')
    page.select_option(f'#clsClasses select[data-cls="{cid}"]', "0")
    page.fill(f'#clsLevels input[type=color][data-level="{p["level"]}"]', "#00ff00")
    assert page.is_enabled("#clsSaveC") and page.is_enabled("#clsSaveL")
    # classes only: the level colour stays a local draft
    page.click("#clsSaveC")
    page.wait_for_function("document.querySelector('#clsStatC').textContent.includes('Saved')")
    assert page.is_disabled("#clsSaveC") and page.is_enabled("#clsSaveL")
    saved = api(f"/api/display/{display_guard}")["saved"]
    assert saved["classes"] == {cid: {"level": 0, "show": False}} and saved["levels"] == {}
    ctx, pg = fresh_page(browser)
    try:
        prepare_lab(pg, cls_run)
        assert not pg.is_checked(f'#clsClasses input[type=checkbox][data-cls="{cid}"]')
        assert pg.input_value(f'#clsClasses select[data-cls="{cid}"]') == "0"
        assert pg.input_value(f'#clsLevels input[type=color][data-level="{p["level"]}"]') != "#00ff00"
        assert pg.is_disabled("#clsSaveC") and pg.is_disabled("#clsSaveL")
        wait_px(pg, p, "a[3] === 0")
        ctx.close()
        # level colours
        page.click("#clsSaveL")
        page.wait_for_function("document.querySelector('#clsStatL').textContent.includes('Saved')")
        assert api(f"/api/display/{display_guard}")["saved"]["levels"] == {str(p["level"]): {"color": [0, 255, 0]}}
        ctx, pg = fresh_page(browser)
        prepare_lab(pg, cls_run)
        assert pg.input_value(f'#clsLevels input[type=color][data-level="{p["level"]}"]') == "#00ff00"
        # un-hide the class + put it back on its level in the fresh browser: the pixel is painted with the saved green
        pg.check(f'#clsClasses input[type=checkbox][data-cls="{cid}"]')
        pg.select_option(f'#clsClasses select[data-cls="{cid}"]', str(p["level"]))
        wait_px(pg, p, "a[0] === 0 && a[1] === 255 && a[2] === 0 && a[3] === 255")
        # Reset to defaults (confirm accepted) clears the server too
        pg.click("#clsReset")
        pg.wait_for_function("document.querySelector('#clsEdited').hidden")
        assert api(f"/api/display/{display_guard}")["saved"] == {"classes": {}, "levels": {}, "updatedAt": None}
        ctx.close()
        ctx, pg = fresh_page(browser)
        prepare_lab(pg, cls_run)
        assert pg.is_checked(f'#clsClasses input[type=checkbox][data-cls="{cid}"]')
        assert pg.input_value(f'#clsClasses select[data-cls="{cid}"]') == str(p["level"])
        assert pg.is_hidden("#clsEdited")
    finally:
        ctx.close()


def test_falls_back_to_prerendered_masks(page, cls_run):
    page.route("**/classes", lambda r: r.fulfill(status=500, body="boom"))
    open_lab(page, LONG_REC, t=T_CLS, run=cls_run)
    seek(page, T_CLS)
    for sel in ("#regionChk", "#laneChk", "#horizonChk", "#hazardChk"):
        page.uncheck(sel)
    page.evaluate("document.querySelector('#secClasses').open = true")
    page.wait_for_function("document.querySelector('#clsMsg').textContent.includes('unavailable')")
    assert page.locator("#clsClasses tr").count() == 0
    # mask.png still paints: some pixel of the overlay is non-transparent
    page.wait_for_function("""() => { const c = document.querySelector('#overlay'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        for (let i = 3; i < d.length; i += 4) if (d[i] > 0) return true; return false; }""")
    assert not any(u.endswith("classes.png") for u, _ in page.requests)


# ---- Resolution select (CONTRACTS 5, Analyse panel) -----------------------------------------------------------

def test_resolution_select_and_run_badge(page):
    """The Resolution select offers 544p-736p with sizes; a short 576p run shows its 1024x576 input in the run badge."""
    open_lab(page, SHORT_REC)
    texts = page.eval_on_selector_all("#profileSel option", "os => os.map(o => o.textContent)")
    assert texts == ["544p · 960×544", "576p · 1024×576", "608p · 1056×608", "640p · 1120×640",
                     "672p · 1184×672", "704p · 1248×704", "736p · 1280×736"]
    assert page.input_value("#profileSel") == "736p"
    assert page.inner_text("label:has(#profileSel)").startswith("Resolution")
    model = next(m["path"] for m in api("/api/models")["models"] if m["default"])
    known = {r["id"] for r in api("/api/runs")}
    page.select_option("#profileSel", "576p")
    page.click("#analyseBtn")
    page.wait_for_function("() => document.querySelector('#runBadge').textContent.includes('1024×576')", timeout=120_000)
    run_id = next(r["id"] for r in api("/api/runs") if r["id"] not in known)
    try:
        run = api(f"/api/runs/{run_id}")
        assert run["request"]["profile"] == "576p" and run["inputSpec"]["w"] == 1024 and run["inputSpec"]["h"] == 576
        assert "1024×576" in page.inner_text("#runList")
        # Loading the run in a fresh page selects its resolution.
        page.goto(f"{BASE}/#rec={SHORT_REC}&run={run_id}")
        page.reload()
        page.wait_for_function("() => document.querySelector('#runBadge').textContent.includes('run ')")
        assert page.input_value("#profileSel") == "576p"
    finally:
        path = os.path.join(LAB_DIR_MOUNT, "runs", run_id) if LAB_DIR_MOUNT else ""
        if path and os.path.isdir(path):
            shutil.rmtree(path)


# ---- v26.2: panel auto-scroll, quarter clocks, depth ------------------------------------------------------------

def _rm_run(run_id):
    path = os.path.join(LAB_DIR_MOUNT, "runs", run_id) if LAB_DIR_MOUNT else ""
    if path and os.path.isdir(path):
        shutil.rmtree(path)


def test_review_panel_follows_playhead_on_desktop(page):
    """>= 1200 px: #reviewPanel is the scroll container; seeking to a late notification scrolls it so the current row is visible."""
    evs = [e for e in api(f"/api/runs/{FULL_RUN}/events.json")["events"] if e["type"] in ("speech", "beeps")]
    evs.sort(key=lambda e: e["t"])
    if len(evs) < 12:
        pytest.skip("not enough notifications in the session run to overflow the panel")
    open_lab(page, LONG_REC, t=0, run=FULL_RUN)
    page.wait_for_selector("#rvList > li")
    assert page.evaluate("() => { const p = document.querySelector('#reviewPanel'); return p.scrollHeight > p.clientHeight; }"), "panel does not overflow"
    assert page.evaluate("document.querySelector('#reviewPanel').scrollTop") == 0
    seek(page, evs[-1]["t"] + 0.05)
    page.wait_for_function("() => document.querySelector('#rvList > li.cur')")
    page.wait_for_function("() => document.querySelector('#reviewPanel').scrollTop > 0")
    inside = page.evaluate("""() => { const r = document.querySelector('#rvList > li.cur').getBoundingClientRect();
        const b = document.querySelector('#reviewPanel').getBoundingClientRect(); return r.top >= b.top - 1 && r.bottom <= b.bottom + 1; }""")
    assert inside, "current row is outside the panel viewport"
    assert page.evaluate("window.scrollY") == 0, "the window must not scroll"
    seek(page, evs[0]["t"] + 0.05)     # and back up
    page.wait_for_function("() => document.querySelector('#reviewPanel').scrollTop < 5 || document.querySelector('#rvList > li.cur').getBoundingClientRect().top >= document.querySelector('#reviewPanel').getBoundingClientRect().top")


def test_quarter_clock_labels(page):
    """When the backend emits clockText, phrases and overlay labels use it (never the 'o'clock' wording)."""
    doc = api(f"/api/runs/{FULL_RUN}/hazards?from=0&to=120")
    items = [h for f in doc["frames"] for h in f.get("hazards", [])]
    if not items or not any("clockText" in h for h in items):
        pytest.skip("backend does not emit clockText yet (restart the lab container)")
    assert all(isinstance(h["clockText"], str) and re.fullmatch(r"\d{1,2}(:(15|30|45))?", h["clockText"]) for h in items if "clockText" in h)
    spoken = [e for e in api(f"/api/runs/{FULL_RUN}/events.json")["events"] if e["type"] == "speech"]
    assert not any("o'clock" in e["text"] for e in spoken)
    # Overlay label: draw a frame with an item and read what the page would label it with.
    fr = next(f for f in doc["frames"] if any(h.get("role") in ("danger", "final", "feature") and "clockText" in h for h in f["hazards"]))
    h = next(h for h in fr["hazards"] if h.get("role") in ("danger", "final", "feature"))
    open_lab(page, LONG_REC, t=fr["t"] + 0.01, run=FULL_RUN)
    page.wait_for_timeout(1500)
    got = page.evaluate("""async (t) => { const m = await import('/static/js/autofill.js');
        const f = await (await fetch('/api/runs/%s/frame?t=' + t)).json();
        return f.frame.hazards.map((h) => m.fillFor(h, null).text); }""" % FULL_RUN, fr["t"])
    assert got and not any("o'clock" in x or " at ? " in x for x in got)
    assert any(h["clockText"] in x for x in got)


def _depth_models():
    return api("/api/models").get("depthModels") or []


def test_depth_toggle_disabled_without_depth(page):
    open_lab(page, LONG_REC, t=10, run=FULL_RUN)
    assert page.is_visible("#depthChk")
    assert page.is_disabled("#depthChk")
    assert page.evaluate("document.querySelector('#depthSel').value || 'none'") == "none"


def test_depth_run_toggle_and_image(page):
    """A short depth run: Analyse sends depth, the badge/list show it, the Depth toggle fetches depth PNGs (200)."""
    if "da3-small" not in _depth_models():
        pytest.skip("/api/models has no depthModels yet (restart the lab container)")
    open_lab(page, SHORT_REC)
    labels = page.eval_on_selector_all("#depthSel option", "os => os.map(o => [o.value, o.textContent])")
    assert labels[0] == ["none", "Off"] and ["da3-small", "DA3 Small"] in labels and ["da3-base", "DA3 Base"] in labels
    assert ["da2-metric-outdoor-small", "DA2 Metric Outdoor S"] in labels and ["unidepth-v2-s", "UniDepth v2 S"] in labels
    assert not any(v == "da3-metric-large" for v, _ in labels)
    assert page.input_value("#depthSel") == "da2-metric-outdoor-small"   # DA2 + initial anchor is the default
    known = {r["id"] for r in api("/api/runs")}
    page.fill("#rangeStart", "0")
    page.fill("#rangeEnd", "6")
    page.select_option("#depthSel", "da3-small")
    page.click("#analyseBtn")
    page.wait_for_function("() => document.querySelector('#runBadge').textContent.includes('depth')", timeout=300_000)
    run_id = next(r["id"] for r in api("/api/runs") if r["id"] not in known)
    try:
        run = api(f"/api/runs/{run_id}")
        assert run["request"].get("depth") == "da3-small" or run.get("depth") == "da3-small"
        assert "depth" in page.inner_text("#runList")
        assert page.is_enabled("#depthChk")
        page.uncheck("#depthChk") if page.is_checked("#depthChk") else None
        seek(page, 2.0)
        with page.expect_response(lambda r: re.search(r"/depth/\d+\.png", r.url) is not None, timeout=30_000) as info:
            page.check("#depthChk")
        assert info.value.status == 200
        # Loading another (non-depth) run disables the toggle again; reloading this one selects its depth model.
        page.reload()
        page.wait_for_function("() => document.querySelector('#runBadge').textContent.includes('run ')")
        assert page.input_value("#depthSel") == "da3-small"
    finally:
        _rm_run(run_id)
