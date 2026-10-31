"""Lab browser tests: v26.1.5 (CONTRACTS 12.1, 12.2, 13) and v26.1.6 notification review / beeps (14.2, 14.3)."""
import gzip
import json
import re
import urllib.request

import pytest

from conftest import BASE, DEFAULT_LONG_REC, HOOKS, LONG_REC, SHORT_REC, annotations, api, audio_log, clock, open_lab, seek


import os
import shutil
import time

# Every test that needs an analysed run uses the one the session analyses itself (version bumps wipe the Lab's runs,
# so no test may depend on a user's run). FULL_RUN is filled in by the autouse fixture below.
FULL_RUN = None
LONG_RANGE = (0, 120)        # seconds of the long recording analysed at 6 fps: long enough for windowing (HALF_S = 90) and every review test
LAB_DIR_MOUNT = os.environ.get("LAB_DIR_MOUNT", "")   # host debug/lab, mounted by run.sh: lets the session delete its own run


@pytest.fixture(scope="session", autouse=True)
def _session_run():
    """Analyse the long recording 0-120 s (default model, fps 6; ~30 s) once; delete the run directory at the end if this session created it."""
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

def test_range_defaults_to_full_length(page, durations):
    open_lab(page, SHORT_REC)
    assert page.input_value("#rangeStart") == "0:00"
    assert page.input_value("#rangeEnd") == clock(durations[SHORT_REC])
    page.goto("about:blank")
    open_lab(page, LONG_REC)
    seek(page, 120.0)                # moving the playhead must not move the range
    assert page.input_value("#rangeStart") == "0:00"
    assert page.input_value("#rangeEnd") == clock(durations[LONG_REC])


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
    ev_url = next(u for u in page.responses if "/events.json" in u)
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

    page.route(f"**/api/runs/{FULL_RUN}/events.json*", handle)


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


SOFT_T0, SOFT_T1 = 40.0, 60.0
SOFT_TEXT = "soft \u00b7 e2e person at 1:30 \u00b7 4\u21922 steps"
SOFT_FREQ = 543.2           # distinctive, like BEEP_FREQ
SOFT_TRACK = 987655


def inject_both_sounds(page):
    """v26.1.13 follow-up: one collision beeps episode (BEEP_FREQ) and one soft proximity episode (SOFT_FREQ, double chirp)."""
    beeps, tones = _beep_events()
    beeps = {**beeps, "kind": "collision"}
    tones = [{**t, "kind": "collision"} for t in tones]
    soft = {"type": "beeps", "kind": "proximity", "t": SOFT_T0, "tEnd": SOFT_T1, "trackId": SOFT_TRACK, "label": "person", "clock": 1,
            "minSteps": 2, "role": "danger", "text": SOFT_TEXT}
    soft_tones = [{"t": SOFT_T0 + 1.2 * i, "type": "tone", "kind": "proximity", "role": "danger", "trackId": SOFT_TRACK,
                   "urgency": "danger", "pan": 0.0, "frequencyHz": SOFT_FREQ, "gain": 0.25, "durationSeconds": 0.12,
                   "chirp": {"count": 2, "gapSeconds": 0.1, "attackSeconds": 0.04}} for i in range(12)]

    def handle(route):
        resp = route.fetch()
        doc = resp.json()
        doc["events"] = ([e for e in doc["events"] if e.get("trackId") not in (BEEP_TRACK, SOFT_TRACK)]
                         + [beeps, soft] + tones + soft_tones)
        route.fulfill(response=resp, json=doc)

    page.route(f"**/api/runs/{FULL_RUN}/events.json*", handle)


def test_two_distinct_sounds_are_scheduled_and_the_review_panel_shows_the_kind(page):
    inject_both_sounds(page)
    open_lab(page, LONG_REC, run=FULL_RUN, t=SOFT_T0 - 1)
    soft_row = page.locator(".rv-row.beeps", has_text="e2e person")
    soft_row.wait_for()
    assert soft_row.get_attribute("data-kind") == "proximity" and "soft" in soft_row.inner_text()
    assert "soft \u00b7 e2e person at 1:30" in soft_row.inner_text() and "\U0001F514" not in soft_row.inner_text()
    pole_row = page.locator(".rv-row.beeps", has_text="e2e pole")
    assert pole_row.get_attribute("data-kind") == "collision" and "\U0001F514" in pole_row.inner_text()
    page.mouse.click(5, 5)
    page.uncheck("#reviewPreviewChk")
    play_window(page, SOFT_T0 - 1, SOFT_T0 + 2.8)
    log = audio_log(page)
    soft = [e for e in log if e["type"] == "tone" and e.get("freq") == pytest.approx(SOFT_FREQ, abs=0.1)]
    beeps = beep_tones(page)
    assert len(soft) >= 2 and len(beeps) >= 3, log                       # two sounds, two distinct frequencies
    assert {e["kind"] for e in soft} == {"proximity"} and {e["kind"] for e in beeps} == {"collision"}
    assert all(e["gain"] == pytest.approx(0.25) for e in soft) and all(e["gain"] == pytest.approx(0.5) for e in beeps)
    # the Beeps checkbox covers both kinds
    page.uncheck("#tonesChk")
    play_window(page, SOFT_T0 - 1, SOFT_T0 + 2.8)
    assert [e for e in audio_log(page) if e["type"] == "tone"] == []
    page.check("#tonesChk")


# ---------------------------------------------------------------- v26.1.14: crosswalk enter / exit tones

CW_IN_T, CW_OUT_T = 40.0, 52.0
CW_IN_TEXT, CW_OUT_TEXT = "\u21e5 crosswalk in \u00b7 one deep tone", "\u21e4 crosswalk out \u00b7 two deep tones"
CW_TRACK = 987654


def inject_crosswalk_tones(page, in_t=CW_IN_T, out_t=CW_OUT_T):
    """One enter (one 330 Hz tone of 0.6 s) and one exit (two 0.2 s tones, 0.12 s apart) with their episode rows."""
    enter = {"t": in_t, "type": "tone", "kind": "crosswalk-enter", "role": "feature", "urgency": "none", "pan": 0.0,
             "frequencyHz": 330.0, "gain": 0.5, "durationSeconds": 0.6,
             "chirp": {"count": 1, "gapSeconds": 0.0, "attackSeconds": 0.03}}
    exit_ = {"t": out_t, "type": "tone", "kind": "crosswalk-exit", "role": "feature", "urgency": "none", "pan": 0.0,
             "frequencyHz": 330.0, "gain": 0.5, "durationSeconds": 0.2,
             "chirp": {"count": 2, "gapSeconds": 0.12, "attackSeconds": 0.02}}
    eps = [{"t": in_t, "tEnd": in_t + 0.6, "type": "beeps", "kind": "crosswalk-enter", "role": "feature", "urgency": "none", "text": CW_IN_TEXT},
           {"t": out_t, "tEnd": out_t + 0.52, "type": "beeps", "kind": "crosswalk-exit", "role": "feature", "urgency": "none", "text": CW_OUT_TEXT}]

    def handle(route):
        resp = route.fetch()
        doc = resp.json()
        doc["events"] = [e for e in doc["events"] if not str(e.get("kind", "")).startswith("crosswalk")] + [enter, exit_] + eps
        route.fulfill(response=resp, json=doc)

    page.route(f"**/api/runs/{FULL_RUN}/events.json*", handle)


def test_crosswalk_tones_are_scheduled_deeper_and_shown_in_the_review_panel(page):
    inject_crosswalk_tones(page)
    open_lab(page, LONG_REC, run=FULL_RUN, t=CW_IN_T - 1)
    row_in = page.locator(".rv-row.beeps", has_text="crosswalk in")
    row_out = page.locator(".rv-row.beeps", has_text="crosswalk out")
    row_in.wait_for()
    assert row_in.get_attribute("data-kind") == "crosswalk-enter" and row_out.get_attribute("data-kind") == "crosswalk-exit"
    assert "\u21e5 crosswalk in" in row_in.inner_text() and "\u21e4 crosswalk out" in row_out.inner_text()
    assert row_in.locator(".rv-v.correct").count() == 1 and row_in.locator(".rv-v.incorrect").count() == 1 and row_in.locator(".rv-v.remove").count() == 1
    page.mouse.click(5, 5)
    page.uncheck("#reviewPreviewChk")
    page.evaluate("window.__osc.length = 0")
    play_window(page, CW_IN_T - 1, CW_IN_T + 1.5)
    log = [e for e in audio_log(page) if e["type"] == "tone" and e.get("kind") == "crosswalk-enter"]
    assert len(log) == 1 and log[0]["freq"] == pytest.approx(330, abs=0.1) and log[0]["gain"] == pytest.approx(0.5), audio_log(page)
    deep = [o for o in page.evaluate("window.__osc") if abs(o["f"] - 330) < 0.5]
    assert len(deep) == 1, deep                                                                   # one tone
    page.evaluate("window.__osc.length = 0")
    play_window(page, CW_OUT_T - 1, CW_OUT_T + 1.5)
    log = [e for e in audio_log(page) if e["type"] == "tone" and e.get("kind") == "crosswalk-exit"]
    assert len(log) == 1 and log[0]["freq"] == pytest.approx(330, abs=0.1), audio_log(page)
    osc = [o for o in page.evaluate("window.__osc") if abs(o["f"] - 330) < 0.5]
    assert len(osc) == 2, osc                                                                      # two tones
    assert osc[1]["when"] - osc[0]["when"] == pytest.approx(0.32, abs=0.03), osc                   # 0.2 s tone + 0.12 s gap
    # deeper than the collision beeps (880 Hz) and the proximity chirp (440 Hz)
    assert log[0]["freq"] < 440
    # the Beeps checkbox covers them
    page.uncheck("#tonesChk")
    play_window(page, CW_IN_T - 1, CW_IN_T + 1.5)
    assert [e for e in audio_log(page) if e["type"] == "tone"] == []
    page.check("#tonesChk")


def test_remove_on_a_crosswalk_row_silences_its_tone(page):
    inject_crosswalk_tones(page)
    open_lab(page, LONG_REC, run=FULL_RUN, t=CW_IN_T - 1)
    row = page.locator(".rv-row.beeps", has_text="crosswalk in")
    row.wait_for()
    page.mouse.click(5, 5)
    row.locator(".rv-v.remove").click()
    try:
        page.locator(".rv-row.beeps.v-remove", has_text="crosswalk in").wait_for()
        page.check("#reviewPreviewChk")
        play_window(page, CW_IN_T - 1, CW_IN_T + 1.5)
        assert [e for e in audio_log(page) if e["type"] == "tone" and e.get("kind") == "crosswalk-enter"] == []
    finally:
        page.locator(".rv-row.beeps", has_text="crosswalk in").locator(".rv-v.remove").click()   # toggling it off deletes the verdict
        page.wait_for_function("() => !document.querySelector('.rv-row.beeps.v-remove')")


def test_the_run_has_crosswalk_tones_that_alternate_in_and_out():
    ev = api(f"/api/runs/{FULL_RUN}/events.json")["events"]
    tones = sorted((e for e in ev if e["type"] == "tone" and str(e.get("kind", "")).startswith("crosswalk-")), key=lambda e: e["t"])
    kinds = [e["kind"] for e in tones]
    assert kinds == ["crosswalk-in", "crosswalk-out"] * (len(kinds) // 2) + (["crosswalk-in"] if len(kinds) % 2 else []), kinds
    assert all(e["frequencyHz"] == 330 for e in tones)
    eps = [e for e in ev if e["type"] == "beeps" and str(e.get("kind", "")).startswith("crosswalk-")]
    assert len(eps) == len(tones)
    if LONG_REC == DEFAULT_LONG_REC:                          # the known footage: crossings at ~41-50 s and ~62-65 s
        ins = [e["t"] for e in tones if e["kind"] == "crosswalk-in"]
        outs = [e["t"] for e in tones if e["kind"] == "crosswalk-out"]
        assert any(40 <= t <= 43 for t in ins) and any(49 <= t <= 52 for t in outs), (ins, outs)


def test_a_real_crosswalk_tone_plays_while_the_video_runs(page):
    ev = api(f"/api/runs/{FULL_RUN}/events.json")["events"]
    enter = next((e for e in sorted(ev, key=lambda e: e["t"]) if e["type"] == "tone" and e.get("kind") == "crosswalk-in"), None)
    assert enter, "no crosswalk-in tone in the first 120 s of the long recording"
    open_lab(page, LONG_REC, run=FULL_RUN, t=max(0, enter["t"] - 1))
    page.mouse.click(5, 5)
    page.uncheck("#reviewPreviewChk")
    play_window(page, max(0, enter["t"] - 1), enter["t"] + 1.5)
    log = [e for e in audio_log(page) if e["type"] == "tone" and e.get("kind") == "crosswalk-in"]
    assert log and log[0]["freq"] == pytest.approx(330, abs=0.1), audio_log(page)


def test_add_beeps_entry_and_hear_it_in_preview(page, created_reviews, durations):
    open_lab(page, SHORT_REC)
    before = {a["id"] for a in annotations(SHORT_REC)}
    seek(page, 0.4)
    page.click("#rvAddBtn")
    assert page.is_hidden("#rvAddEndRow")
    page.select_option("#rvAddType", "beeps")
    page.wait_for_selector("#rvAddEndRow", state="visible")
    assert page.input_value("#rvAddEnd") == clock(min(0.4 + 3.0, durations[SHORT_REC]), 1)   # default end = start + 3 s, clamped to the recording
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
    page.fill("#rangeEnd", "6")          # a few seconds: the short recording is minutes long now
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


# ---- body settings: height / camera location / side ----------------------------------------------------------

def test_body_settings_controls_persist_and_hint(page):
    open_lab(page, SHORT_REC)
    before = api(f"/api/recordings/{SHORT_REC}/settings")
    try:
        for sel in ("#userHeightInput", "#locSel", "#sideSel"):
            assert page.is_visible(sel)
        labels = page.eval_on_selector_all("#locSel option", "os => os.map(o => o.value)")
        assert labels[0] == "" and {"waist", "chest", "eye", "head"} <= set(labels)
        page.fill("#userHeightInput", "1.78")
        page.select_option("#locSel", "chest")
        page.select_option("#sideSel", "center")
        page.wait_for_function("() => document.querySelector('#camHeightInput').placeholder.startsWith('auto 1.28')")
        assert not page.is_visible("#mountSel")
        saved = api(f"/api/recordings/{SHORT_REC}/settings")
        assert (saved["userHeightM"], saved["cameraLocation"], saved["cameraSide"]) == (1.78, "chest", "center")
        assert abs(saved["resolved"]["cameraHeightM"] - 1.28) < 0.01
        page.reload()
        page.wait_for_function("() => document.querySelector('#locSel').value === 'chest'")
        assert page.input_value("#userHeightInput") == "1.78"
        assert "1.28" in page.get_attribute("#camHeightInput", "placeholder")
    finally:
        api(f"/api/recordings/{SHORT_REC}/settings", "PUT",
            {k: before[k] for k in ("mount", "hfovDeg", "cameraHeightM", "stepLengthM", "projection", "distanceSource",
                                    "userHeightM", "cameraLocation", "cameraSide")})


# ---------------------------------------------------------------- Chrome mobile audio (v26.1.11 follow-up)

def test_mobile_touch_tap_unlocks_audio_and_plays(browser):
    """Touch-only (no mouse): a tap unlocks the AudioContext and playback logs beeps and speech (12.2)."""
    ctx = browser.new_context(
        viewport={"width": 412, "height": 915}, device_scale_factor=2.625, is_mobile=True, has_touch=True,
        user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Mobile Safari/537.36")
    ctx.add_init_script(HOOKS)
    page = ctx.new_page()
    page.set_default_timeout(60_000)
    try:
        spoken_t = long_run_events()[0]["t"]
        inject_beeps(page)
        open_lab(page, LONG_REC, run=FULL_RUN, t=BEEP_T0 - 1)
        assert page.evaluate("window.__acs.filter(c => c.state === 'running').length") == 0, "unlocked before any gesture"
        page.evaluate("window.__labAudioLog.length = 0")
        page.tap("#playBtn")         # a real touch sequence: touchstart/pointerdown/touchend/pointerup/click
        page.wait_for_function("() => window.__acs.length === 1 && window.__acs[0].state === 'running'")
        page.wait_for_function(f"() => document.querySelector('#video').currentTime > {BEEP_T0 + 2.2}", timeout=30_000)
        page.tap("#playBtn")         # pause
        assert len(beep_tones(page)) >= 3, audio_log(page)
        # speech: the first phrase of the run
        page.evaluate("window.__labAudioLog.length = 0; window.__spoken.length = 0")
        seek(page, max(0, spoken_t - 1.5))
        page.tap("#playBtn")
        page.wait_for_function(f"() => document.querySelector('#video').currentTime > {spoken_t + 0.5}", timeout=30_000)
        page.tap("#playBtn")
        assert [e for e in audio_log(page) if e["type"] == "speech"], audio_log(page)
        assert page.evaluate("window.__spoken.length") >= 1
        assert not [e for e in audio_log(page) if e["type"] == "speech-error"]
        assert page.evaluate("window.__acs[0].state") == "running"
    finally:
        ctx.close()


# ---------------------------------------------------------------- speech diagnostics (v26.1.11 follow-up, 12.2)

def _client_log_collector(page):
    """Entries the page POSTs to /api/client-log (read off the wire)."""
    got = []
    def on_request(req):
        if req.url.endswith("/api/client-log") and req.method == "POST":
            try:
                got.extend(json.loads(req.post_data or "[]"))
            except ValueError:
                pass
    page.on("request", on_request)
    return got


def test_client_log_endpoint_round_trip():
    marker = f"e2e-{time.time_ns()}"
    assert api("/api/client-log", "POST", [{"type": "e2e", "marker": marker}, {"type": "e2e", "n": 2}])["n"] == 2
    root = os.environ.get("LAB_DIR_MOUNT")
    if root:
        lines = [json.loads(l) for l in open(os.path.join(root, "client-log.jsonl"), encoding="utf-8").read().splitlines()[-2:]]
        assert lines[0]["marker"] == marker and lines[0]["server"] and "ua" in lines[0]
    with pytest.raises(AssertionError, match="400"):
        api("/api/client-log", "POST", {"not": "an array"})


def test_test_speech_button_reports_and_logs(page):
    got = _client_log_collector(page)
    open_lab(page, SHORT_REC)
    page.click("#testSpeechBtn")
    page.wait_for_selector(".toast:has-text('Speech test')", timeout=6000)
    text = page.inner_text(".toast:has-text('Speech test')")
    assert "voices" in text and "speaking" in text, text
    deadline = time.time() + 6
    while time.time() < deadline and not any(e["type"] == "test-speech-result" for e in got):
        time.sleep(0.2)
    types = {e["type"] for e in got}
    assert {"voices", "test-speech", "test-speech-result"} <= types, types
    assert any(e["type"] == "speak" and e["text"] == "speech test" for e in got), got
    assert page.evaluate("window.__spoken.some(s => s.text === 'speech test')")


def test_speech_watchdog_retries_when_synthesis_never_starts(browser):
    ctx = browser.new_context(viewport={"width": 1200, "height": 800})
    ctx.add_init_script(HOOKS)
    ctx.add_init_script("""
      window.__stub = {speaks: [], cancels: 0};
      const sp = window.speechSynthesis;
      sp.speak = (u) => { window.__stub.speaks.push({text: u.text, voice: u.voice ? u.voice.name : null}); };  // never fires onstart
      sp.cancel = () => { window.__stub.cancels++; };
      Object.defineProperty(sp, 'speaking', {get: () => true});
    """)
    page = ctx.new_page()
    page.set_default_timeout(60_000)
    got = _client_log_collector(page)
    try:
        open_lab(page, SHORT_REC)
        page.click("#testSpeechBtn")
        page.wait_for_function("() => window.__stub.speaks.length >= 2", timeout=6000)
        stub = page.evaluate("window.__stub")
        assert stub["cancels"] >= 1
        assert stub["speaks"][1]["voice"] is None and stub["speaks"][1]["text"] == "speech test"
        page.wait_for_selector(".toast:has-text('Speech test')", timeout=6000)
        assert "retried" in page.inner_text(".toast:has-text('Speech test')")
        deadline = time.time() + 6
        while time.time() < deadline and not any(e["type"] == "watchdog" for e in got):
            time.sleep(0.2)
        assert any(e["type"] == "watchdog" for e in got), [e["type"] for e in got]
    finally:
        ctx.close()


def test_queued_phrase_does_not_trigger_watchdog_or_cancel(browser):
    """A phrase spoken while the previous one is still speaking is only queued: no watchdog, no cancel, voice kept."""
    ctx = browser.new_context(viewport={"width": 1200, "height": 800})
    ctx.add_init_script(HOOKS)
    ctx.add_init_script("""
      window.__stub = {speaks: [], cancels: 0};
      const sp = window.speechSynthesis;
      const queue = []; let active = null;
      const next = () => {
        if (active || !queue.length) return;
        active = queue.shift();
        const u = active, dur = !u.text.trim() ? 30 : window.__stub.speaks.filter((t) => t.trim()).length <= 1 ? 3500 : 300;
        setTimeout(() => u.onstart && u.onstart({}), 30);
        setTimeout(() => { active = null; u.onend && u.onend({}); next(); }, dur);
      };
      sp.speak = (u) => { window.__stub.speaks.push(u.text); queue.push(u); next(); };
      sp.cancel = () => { window.__stub.cancels++; };
      Object.defineProperty(sp, 'speaking', {get: () => !!active});
      Object.defineProperty(sp, 'pending', {get: () => queue.length > 0});
    """)
    page = ctx.new_page()
    page.set_default_timeout(60_000)
    got = _client_log_collector(page)
    try:
        open_lab(page, SHORT_REC)
        page.click("#testSpeechBtn")
        page.wait_for_timeout(300)
        page.click("#testSpeechBtn")                      # queued behind the 3.5 s utterance
        page.wait_for_function("() => window.__stub.speaks.length >= 2", timeout=3000)
        page.wait_for_timeout(5500)                       # past the first end and well past 1.5 s after the second speak()
        assert page.evaluate("window.__stub.cancels") == 0, [e for e in got if e["type"] == "cancel"]
        deadline = time.time() + 6
        while time.time() < deadline and sum(e["type"] == "utt-end" for e in got) < 2:
            time.sleep(0.2)
        types = [e["type"] for e in got]
        assert types.count("utt-start") == 2 and types.count("utt-end") == 2, types
        assert not {"watchdog", "voice-dropped", "utt-error"} & set(types), types
        assert not any(e["type"] == "speak" and e.get("retry") for e in got)
    finally:
        ctx.close()


def test_voice_ranking(page):
    open_lab(page, SHORT_REC)
    res = page.evaluate("""async () => {
      const m = await import('/static/js/audio.js');
      const v = (name, lang, localService = true, def = false) => ({name, lang, localService, default: def});
      const mac = [v('Albert', 'en-US'), v('Alice', 'it-IT'), v('Bahh', 'en-US'), v('Bad News', 'en-US'), v('Bells', 'en-US'),
        v('Daniel', 'en-GB', true, true), v('Eddy (English (US))', 'en-US'), v('Fred', 'en-US'), v('Samantha', 'en-US'), v('Zarvox', 'en-US')];
      const macNoDefault = mac.map((x) => ({...x, default: false}));
      const ios = [v('Aaron', 'en-US'), v('Alice', 'it-IT'), v('Fred', 'en-US'), v('Samantha', 'en-US', true, true), v('Daniel', 'en-GB')];
      const iosNoDefault = ios.map((x) => ({...x, default: false}));
      const enhanced = [v('Samantha', 'en-US'), v('Samantha (Enhanced)', 'en-US'), v('Albert', 'en-US')];
      const name = (l) => (m.chooseEnglishVoice(l) || {}).name || null;
      return {mac: name(mac), macNoDefault: name(macNoDefault), ios: name(ios), iosNoDefault: name(iosNoDefault),
              enhanced: name(enhanced), onlyNovelty: name([v('Albert', 'en-US'), v('Bahh', 'en-US')]), none: name([v('Alice', 'it-IT')])};
    }""")
    assert res == {"mac": "Daniel", "macNoDefault": "Samantha", "ios": "Samantha", "iosNoDefault": "Samantha",
                   "enhanced": "Samantha (Enhanced)", "onlyNovelty": None, "none": None}, res


def test_speech_plan(page):
    """System voice rule: an English platform default voice -> no lang/voice set; otherwise lang en-US + ranked English voice."""
    open_lab(page, SHORT_REC)
    res = page.evaluate("""async () => {
      const m = await import('/static/js/audio.js');
      const v = (name, lang, localService = true, def = false) => ({name, lang, localService, default: def});
      const mac = [v('Albert', 'en-US'), v('Alice', 'it-IT'), v('Daniel', 'en-GB', true, true), v('Samantha', 'en-US')];
      const ios = [v('Joana', 'pt-PT', true, true), v('Aaron', 'en-US'), v('Fred', 'en-US'), v('Samantha', 'en-US'), v('Daniel', 'en-GB')];
      const iosFirst = ios.map((x) => ({...x, default: false}));
      const p = (l) => { const r = m.speechPlan(l); return [r.mode, r.voice ? r.voice.name : null]; };
      return {mac: p(mac), ios: p(ios), iosFirst: p(iosFirst), empty: p([]), noEnglish: p([v('Alice', 'it-IT', true, true)])};
    }""")
    assert res == {"mac": ["system", None], "ios": ["english", "Samantha"], "iosFirst": ["english", "Samantha"],
                   "empty": ["english", None], "noEnglish": ["english", None]}, res


def test_pronunciation_map_changes_the_spoken_text_only(page):
    """v26.1.12 (review 5: the Mac voice read "curb" as "tarmac"): the synthesizer gets "kerb", the display text and the log's
    ``text`` stay "curb"; the client-log "speak" entry carries ``spoken``."""
    got = _client_log_collector(page)
    open_lab(page, SHORT_REC)
    res = page.evaluate("""async () => {
      const m = await import('/static/js/audio.js');
      return [m.pronounce('curb at 12 in 3'), m.pronounce('Curb ahead, curb at 1'), m.pronounce('curbside'), m.pronounce('pole at 12 in 8')];
    }""")
    assert res == ["kerb at 12 in 3", "kerb ahead, kerb at 1", "curbside", "pole at 12 in 8"], res
    page.click("#testSpeechBtn")
    page.wait_for_selector(".toast:has-text('Speech test')", timeout=6000)
    deadline = time.time() + 6
    while time.time() < deadline and not any(e["type"] == "test-speech-result" for e in got):
        time.sleep(0.2)
    entry = [e for e in got if e["type"] == "speak" and e.get("text") == "speech test"]
    assert entry and entry[0]["spoken"] == "speech test", got          # (a phrase with no mapped word is spoken as it is)


def test_static_no_cache(page):
    for path in ("/static/js/audio.js", "/"):
        req = urllib.request.Request(BASE + path)
        with urllib.request.urlopen(req) as r:
            assert r.headers.get("Cache-Control") == "no-cache", (path, dict(r.headers))


def test_stuck_speech_engine_shows_notice_and_clears_on_start(browser):
    """Speech engine that is 'speaking' but never fires onstart: after a phrase and its retry the notice shows (once), logged;
    a later onstart hides it. Mac UA gets the Cmd+Q hint."""
    mac_ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/141.0.0.0 Safari/537.36")
    ctx = browser.new_context(viewport={"width": 1200, "height": 800}, user_agent=mac_ua)
    ctx.add_init_script(HOOKS)
    ctx.add_init_script("""
      window.__stub = {speaks: 0, fire: false};
      const sp = window.speechSynthesis;
      sp.speak = (u) => { window.__stub.speaks++; if (window.__stub.fire) setTimeout(() => { u.onstart && u.onstart({}); u.onend && u.onend({}); }, 20); };
      sp.cancel = () => {};
      Object.defineProperty(sp, 'speaking', {get: () => !window.__stub.fire});
    """)
    page = ctx.new_page()
    page.set_default_timeout(60_000)
    got = _client_log_collector(page)
    try:
        open_lab(page, SHORT_REC)
        assert not page.is_visible("#speechStuck")
        page.click("#testSpeechBtn")
        page.wait_for_selector("#speechStuck", state="visible", timeout=8000)
        text = page.inner_text("#speechStuck")
        assert "Speech isn't working: the browser's speech engine isn't responding. Quit the browser completely and reopen it." in text, text
        assert "Quit Chrome with Cmd+Q (closing the window is not enough), then reopen it." in text, text
        assert "Beeps still work." in text, text
        assert "Audio" in page.inner_text("fieldset:has(#speechStuck) legend")
        page.wait_for_selector(".toast:has-text('Speech test')", timeout=6000)
        assert "notice" in page.inner_text(".toast:has-text('Speech test')")
        deadline = time.time() + 6
        while time.time() < deadline and not any(e["type"] == "speech-stuck" for e in got):
            page.wait_for_timeout(200)   # (time.sleep would not let Playwright deliver the request events)
        stuck = [e for e in got if e["type"] == "speech-stuck"]
        assert len(stuck) == 1 and stuck[0]["consecutive"] == 2, stuck
        # dismissable
        page.click("#speechStuckClose")
        assert not page.is_visible("#speechStuck")
        # the engine recovers: onstart hides the notice and resets the episode
        page.evaluate("window.__stub.fire = true")
        page.click("#testSpeechBtn")
        page.wait_for_function("() => document.querySelector('#speechStuck').hidden", timeout=6000)
        # a new episode shows it again
        page.evaluate("window.__stub.fire = false")
        page.wait_for_timeout(2900)   # let the previous test finish its probe
        page.click("#testSpeechBtn")
        page.wait_for_selector("#speechStuck", state="visible", timeout=8000)
        page.evaluate("window.__stub.fire = true")
        page.click("#testSpeechBtn")
        page.wait_for_function("() => document.querySelector('#speechStuck').hidden", timeout=6000)
    finally:
        ctx.close()


def test_stuck_hint_per_platform(page):
    open_lab(page, SHORT_REC)
    hints = page.evaluate("""async () => {
      const m = await import('/static/js/audio.js');
      return [m.stuckHint('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 'MacIntel', 0),
              m.stuckHint('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit CriOS/141', 'iPhone', 5),
              m.stuckHint('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)', 'iPad', 5),
              m.stuckHint('Mozilla/5.0 (Windows NT 10.0) Chrome/141', 'Win32', 0)];
    }""")
    assert hints[0].startswith("Quit Chrome with Cmd+Q")
    assert hints[1] == hints[2] == "Close the browser from the app switcher, then reopen it."
    assert hints[3] == "Close all browser windows and reopen it."


# ---------------------------------------------------------------- v26.1.15: the player's speech queue (review 7)

QUEUE_STUB = """
  window.__q = {speaks: [], cancels: [], startDelay: 30, dur: 2000};
  (() => {
    const sp = window.speechSynthesis;
    let active = null; const q = [];
    const kick = () => {
      if (active || !q.length) return;
      const u = active = q.shift();
      const startAfter = typeof window.__q.startDelay === 'function' ? window.__q.startDelay(u) : window.__q.startDelay;
      u._t1 = setTimeout(() => { u.onstart && u.onstart({}); u._t2 = setTimeout(() => { active = null; u.onend && u.onend({}); kick(); }, window.__q.dur); }, startAfter);
    };
    sp.speak = (u) => { if (u.text.trim()) window.__q.speaks.push({text: u.text, at: performance.now(), activeAtSpeak: !!active, queued: q.length}); q.push(u); kick(); };
    sp.cancel = () => {
      window.__q.cancels.push(performance.now());
      const all = (active ? [active] : []).concat(q.splice(0)); active = null;
      all.forEach((u) => { clearTimeout(u._t1); clearTimeout(u._t2); setTimeout(() => u.onerror && u.onerror({error: 'interrupted'}), 0); });
    };
    Object.defineProperty(sp, 'speaking', {get: () => !!active});
    Object.defineProperty(sp, 'pending', {get: () => q.length > 0});
  })();
"""


def _queue_page(browser):
    ctx = browser.new_context(viewport={"width": 1200, "height": 800})
    ctx.add_init_script(HOOKS)
    ctx.add_init_script(QUEUE_STUB)
    page = ctx.new_page()
    page.set_default_timeout(60_000)
    return ctx, page


NEW_ENGINE = """async () => {
  const m = await import('/static/js/audio.js');
  window.__eng = new m.AudioEngine(document.querySelector('#video'));
  window.__say = (text, role, extra = {}) => window.__eng.speak(text, 1, false, {t: document.querySelector('#video').currentTime, role, ...extra});
  return true;
}"""


def _started(page):
    return page.evaluate("window.__q.speaks.map((s) => s.text)")


def test_player_queue_danger_preempts_a_speaking_context_phrase(browser):
    """Review 7: "a danger overlaps other notifications ... if speech is to start out of time, don't". A danger (an added review phrase
    counts too) cancels the context phrase being spoken and starts at once; equal priority waits its turn."""
    ctx, page = _queue_page(browser)
    got = _client_log_collector(page)
    try:
        open_lab(page, SHORT_REC)
        page.evaluate(NEW_ENGINE)
        page.evaluate("window.__say('building at 1:15 in 2, obstacle at 12:45 in 2', 'context')")
        page.wait_for_function("() => window.__q.speaks.length === 1")
        page.wait_for_timeout(300)                                        # the context phrase is being heard
        t0 = page.evaluate("performance.now()")
        page.evaluate("window.__say('Person static at 12 in 9', 'danger', {source: 'added'})")
        page.wait_for_function("() => window.__q.speaks.length === 2", timeout=2000)
        q = page.evaluate("window.__q")
        assert q["speaks"][1]["text"] == "Person static at 12 in 9" and len(q["cancels"]) == 1, q
        assert q["speaks"][1]["at"] - t0 < 300, "the danger must start at once, not behind the 2 s context phrase"
        # equal priority waits: a second danger comes after the first one's end, with no further cancel
        page.evaluate("window.__say('pole at 11:45 in 9', 'danger')")
        page.wait_for_timeout(300)
        assert _started(page) == ["building at 1:15 in 2, obstacle at 12:45 in 2", "Person static at 12 in 9"]
        page.wait_for_function("() => window.__q.speaks.length === 3", timeout=4000)
        assert len(page.evaluate("window.__q.cancels")) == 1
        log = audio_log(page)
        pre = [e for e in log if e["type"] == "speech-preempted"]
        assert len(pre) == 1 and pre[0]["by"] == "Person static at 12 in 9" and pre[0]["started"] is True, log
        assert any(e["type"] == "speech" and e["text"] == "Person static at 12 in 9" and e["source"] == "added" for e in log)
        deadline = time.time() + 4
        while time.time() < deadline and not any(e["type"] == "speech-preempted" for e in got):
            page.wait_for_timeout(200)
        assert any(e["type"] == "speech-preempted" and e["byRole"] == "danger" for e in got), [e["type"] for e in got]
    finally:
        ctx.close()


def test_player_queue_priority_order_final_danger_feature_surface_context(browser):
    """Waiting phrases leave the queue best first; a phrase outranking the one being spoken cuts it off."""
    ctx, page = _queue_page(browser)
    try:
        open_lab(page, SHORT_REC)
        page.evaluate(NEW_ENGINE)
        page.evaluate("window.__q.dur = 250")
        page.evaluate("window.__say('first', 'surface')")
        page.wait_for_function("() => window.__q.speaks.length === 1")
        page.wait_for_timeout(100)
        page.evaluate("""() => { for (const [t, r] of [['c', 'context'], ['s2', 'surface'], ['f', 'feature']]) window.__say(t, r); }""")
        page.wait_for_function("() => window.__q.speaks.length >= 2", timeout=3000)
        page.wait_for_timeout(1500)
        spoken = _started(page)
        # 'f' (feature) outranks the surface phrase being spoken and cuts it off; then the waiting ones: surface before context
        assert spoken == ["first", "f", "s2", "c"], spoken
    finally:
        ctx.close()


def test_player_queue_drops_a_phrase_that_cannot_start_in_time(browser):
    """A waiting phrase older than 1 s (media time) of its event time is not said late: logged ``speech-dropped-late``."""
    ctx, page = _queue_page(browser)
    got = _client_log_collector(page)
    try:
        open_lab(page, SHORT_REC)
        page.evaluate(NEW_ENGINE)
        page.evaluate("window.__say('building at 1:15 in 2', 'context')")
        page.wait_for_function("() => window.__q.speaks.length === 1")
        page.wait_for_timeout(200)                                        # heard (a phrase cut off before its onstart goes back to the queue)
        page.evaluate("window.__say('pole at 11:45 in 9', 'feature'); window.__say('crosswalk at 12 in 12', 'feature')")
        # the first feature is preempting (feature > context): speaks at once; the second waits behind it ...
        page.wait_for_function("() => window.__q.speaks.length === 2", timeout=2000)
        # ... and 1.2 s of media time pass (the video is paused: the user offset moves the clock the events are judged by)
        page.evaluate("window.__eng.offsetS = -1.2")
        page.wait_for_timeout(400)
        log = audio_log(page)
        dropped = [e for e in log if e["type"] == "speech-dropped-late"]
        assert [e["text"] for e in dropped] == ["crosswalk at 12 in 12"] and dropped[0]["lateS"] > 1.0, log
        page.wait_for_timeout(2500)
        assert "crosswalk at 12 in 12" not in _started(page)
        deadline = time.time() + 4
        while time.time() < deadline and not any(e["type"] == "speech-dropped-late" for e in got):
            page.wait_for_timeout(200)
        assert any(e["type"] == "speech-dropped-late" and e["text"] == "crosswalk at 12 in 12" for e in got)
    finally:
        ctx.close()


def test_player_queue_preemption_triggers_neither_the_watchdog_nor_the_stuck_notice(browser):
    """Cancelling our own utterances (also ones that never started yet) is not a failure: three preemptions in a row, no watchdog,
    no ``speech-stuck`` (STUCK_AFTER is 2), no notice, no extra cancel from the unstick logic."""
    ctx, page = _queue_page(browser)
    got = _client_log_collector(page)
    try:
        open_lab(page, SHORT_REC)
        page.evaluate(NEW_ENGINE)
        page.evaluate("window.__q.startDelay = 900")               # slow to start: each is cut off before onstart
        page.evaluate("window.__say('context phrase', 'context')")
        page.wait_for_timeout(150)
        for text, role in (("feature phrase", "feature"), ("danger phrase", "danger"), ("final phrase", "final")):
            page.evaluate(f"window.__say('{text}', '{role}')")
            page.wait_for_timeout(150)
        assert len(page.evaluate("window.__q.cancels")) == 3
        page.evaluate("window.__q.startDelay = 30; window.__q.dur = 250")
        page.wait_for_timeout(4500)
        types = [e["type"] for e in got]
        assert not {"watchdog", "speech-stuck", "voice-dropped"} & set(types), types
        assert not page.is_visible("#speechStuck")
        spoken = _started(page)
        assert "final phrase" in spoken
        # the phrases cut off before they were heard are still waiting (on time): they follow the final in priority order
        order = [t for t in spoken if t.endswith("phrase")]
        assert order[order.index("final phrase"):][:3] == ["final phrase", "danger phrase", "feature phrase"], spoken
        assert not any(e["type"] == "cancel" and e.get("reason") in ("watchdog", "stuck-queue-stale", "stuck-queue-foreign") for e in got), got
    finally:
        ctx.close()


def test_player_queue_lost_end_event_does_not_block_the_next_phrase(browser):
    """An engine that claims to be idle without ever reporting the end of an utterance (WebKit has done this) must not hold the queue."""
    ctx, page = _queue_page(browser)
    got = _client_log_collector(page)
    try:
        open_lab(page, SHORT_REC)
        page.evaluate(NEW_ENGINE)
        page.evaluate("""() => { const sp = window.speechSynthesis; sp.speak = (u) => { window.__q.speaks.push({text: u.text}); u.onstart && u.onstart({}); }; }""")
        page.evaluate("window.__say('first', 'danger')")
        page.evaluate("window.__say('second', 'danger', {t: document.querySelector('#video').currentTime + 5})")
        page.wait_for_function("() => window.__q.speaks.length === 2", timeout=3000)
        deadline = time.time() + 3
        while time.time() < deadline and not any(e["type"] == "utt-lost" for e in got):
            page.wait_for_timeout(200)
        assert any(e["type"] == "utt-lost" for e in got), [e["type"] for e in got]
    finally:
        ctx.close()


# ---- Orientation (v26.1.15 follow-up, CONTRACTS 1a / 5) ------------------------------------------------------------

def test_portrait_left_run_window_overlay_and_label(page):
    """Orientation sits above Resolution; a short portrait-left run is cut to the left 9:16 window, its overlay is dimmed
    outside the window, and the runs list says 'portrait · left'."""
    open_lab(page, SHORT_REC)
    before = api(f"/api/recordings/{SHORT_REC}/settings")
    ob, pb = page.locator("#orientSel").bounding_box(), page.locator("#profileSel").bounding_box()
    assert ob["y"] < pb["y"], "Orientation is above Resolution"
    assert page.eval_on_selector_all("#orientSel option", "os => os.map(o => o.value)") == ["landscape", "portrait"]
    assert page.input_value("#orientSel") == "landscape" and page.input_value("#sideSel") == "center"   # from the name
    known = {r["id"] for r in api("/api/runs")}
    run_id = None
    try:
        page.select_option("#orientSel", "portrait")
        page.select_option("#sideSel", "left")
        texts = page.eval_on_selector_all("#profileSel option", "os => os.map(o => o.textContent)")
        assert texts[-1] == "736p · 736×1280" and texts[0] == "544p · 544×960"
        page.fill("#rangeEnd", "6")
        page.click("#analyseBtn")
        page.wait_for_function("() => document.querySelector('#runBadge').textContent.includes('736×1280')", timeout=180_000)
        run_id = next(r["id"] for r in api("/api/runs") if r["id"] not in known)
        run = api(f"/api/runs/{run_id}")
        assert run["request"]["orientation"] == "portrait" and run["request"]["side"] == "left"
        w = run["window"]
        assert (w["x0"], w["y0"], w["w"], w["h"]) == (0, 0, run["srcH"] * 9 // 16, run["srcH"])
        assert run["gridWindow"] == {"c0": 0, "cols": 76}
        assert "portrait · left" in page.inner_text("#runList")
        # the stored grid is full-frame: NO_DATA (255) right of the window, classes inside it
        grid = page.evaluate("""async (url) => {
            const img = new Image(); img.src = url; await img.decode();
            const c = document.createElement('canvas'); c.width = img.naturalWidth; c.height = img.naturalHeight;
            const x = c.getContext('2d'); x.drawImage(img, 0, 0); const d = x.getImageData(0, 0, c.width, c.height).data;
            let right = 0, left = 0; for (let r = 0; r < c.height; r++) for (let q = 0; q < c.width; q++) {
              const v = d[(r * c.width + q) * 4]; if (q >= 76 && v !== 255) right++; if (q < 76 && v === 255) left++; }
            return {w: c.width, h: c.height, right, left};
        }""", f"/api/runs/{run_id}/frames/0/classes.png")
        assert grid["w"] == 240 and grid["right"] == 0 and grid["left"] == 0
        hz = api(f"/api/runs/{run_id}/hazards?from=0&to=6")
        assert hz["gridW"] == 240 and hz["frames"]
        # overlay: dimmed right of the window, untouched inside it (all other layers off)
        for sel in ("#maskChk", "#regionChk", "#laneChk", "#horizonChk", "#hazardChk"):
            page.uncheck(sel)
        seek(page, 2)
        probe = """(fx) => { const c = document.querySelector('#overlay'); const x = c.getContext('2d');
            return x.getImageData(Math.floor(fx * c.width), Math.floor(c.height / 2), 1, 1).data[3]; }"""
        page.wait_for_function(f"({probe})(0.9) > 50")
        assert page.evaluate(probe, 0.1) == 0
        assert page.evaluate(probe, 0.9) > 50
    finally:
        api(f"/api/recordings/{SHORT_REC}/settings", "PUT",
            {k: before[k] for k in ("mount", "hfovDeg", "cameraHeightM", "stepLengthM", "projection", "distanceSource",
                                    "userHeightM", "cameraLocation", "cameraSide", "orientation")})
        if run_id:
            _rm_run(run_id)


# ---------------------------------------------------------------- v26.1.16: the sound tuner, the sound kinds, speech speed

KINDS = ["collision-left", "collision-center", "collision-right", "crosswalk-in", "crosswalk-out", "proximity"]


def _hz(slider):
    """The tuner's log pitch scale: 0..1000 -> 150..2000 Hz (js/sounds.js)."""
    return int(150 * (2000 / 150) ** (slider / 1000) + 0.5)


def _set(page, selector, value):
    page.eval_on_selector(selector, "(el, v) => { el.value = v; el.dispatchEvent(new Event('input', {bubbles: true})); }", str(value))


def _row(kind, field):
    return f'#sndRows tr[data-kind="{kind}"] [data-f="{field}"]'


@pytest.fixture
def sounds_guard():
    """The profile is Lab-wide: every test that changes it starts and ends on the defaults."""
    api("/api/sounds", "DELETE")
    yield
    api("/api/sounds", "DELETE")


def test_sound_tuner_is_in_the_middle_section_with_a_row_per_kind(page, sounds_guard):
    open_lab(page, SHORT_REC, profile=True)
    assert page.evaluate("document.querySelector('#main').contains(document.querySelector('#secSounds'))")
    assert not page.evaluate("document.querySelector('#sidebar').contains(document.querySelector('#secSounds'))")
    assert page.evaluate("[...document.querySelectorAll('#sndRows tr')].map((r) => r.dataset.kind)") == KINDS
    for k in KINDS:
        assert page.locator(f'#sndRows tr[data-kind="{k}"] .snd-test').count() == 1
    assert page.input_value(_row("collision-center", "durationMs")) == "80" and page.input_value(_row("collision-center", "intervalS")) == "0.5"
    assert page.input_value(_row("crosswalk-in", "durationMs")) == "600"
    assert page.is_disabled(_row("crosswalk-in", "intervalS")) and not page.is_disabled(_row("crosswalk-out", "intervalS"))
    assert page.inner_text('#sndRows tr[data-kind="collision-left"] [data-o="pitchHz"]') == "660 Hz"
    assert page.input_value("#sndSpeech") == "1" and "1.00" in page.inner_text("#sndSpeechOut")
    assert page.locator("#sndSpeechTest").count() == 1 and page.is_hidden("#sndApply")


def test_sound_changes_persist_through_the_api_and_across_a_reload(page, sounds_guard):
    open_lab(page, SHORT_REC, profile=True)
    _set(page, _row("collision-left", "pitchHz"), 500)
    page.fill(_row("collision-left", "durationMs"), "150")
    page.fill(_row("proximity", "intervalS"), "2")
    _set(page, "#sndSpeech", 1.5)
    page.wait_for_function("() => document.querySelector('#sndStatus').textContent.includes('Saved')")
    saved = api("/api/sounds")
    left = next(k for k in saved["kinds"] if k["kind"] == "collision-left")
    assert (left["pitchHz"], left["durationMs"]) == (_hz(500), 150)
    assert next(k for k in saved["kinds"] if k["kind"] == "proximity")["intervalS"] == 2.0 and saved["speechRate"] == 1.5
    assert page.inner_text('#sndRows tr[data-kind="collision-left"] [data-o="pitchHz"]') == f"{_hz(500)} Hz"
    page.reload()
    page.wait_for_function("() => document.querySelectorAll('#sndRows tr').length > 0")
    assert page.input_value(_row("collision-left", "durationMs")) == "150" and page.input_value(_row("proximity", "intervalS")) == "2"
    assert page.input_value("#sndSpeech") == "1.5" and page.inner_text('#sndRows tr[data-kind="collision-left"] [data-o="pitchHz"]') == f"{_hz(500)} Hz"
    page.click("#sndReset")
    page.wait_for_function("() => document.querySelector('#sndStatus').textContent.includes('Defaults')")
    assert page.input_value(_row("collision-left", "durationMs")) == "80" and api("/api/sounds")["speechRate"] == 1.0


def test_the_test_button_plays_the_chosen_frequency_inside_the_click(page, sounds_guard):
    open_lab(page, SHORT_REC, profile=True)
    page.mouse.click(5, 5)
    page.wait_for_timeout(200)
    page.evaluate("window.__osc.length = 0; window.__labAudioLog.length = 0")
    _set(page, _row("collision-right", "pitchHz"), 800)
    page.click('#sndRows tr[data-kind="collision-right"] .snd-test')
    page.wait_for_function("() => window.__osc.length >= 4")
    osc = page.evaluate("window.__osc")
    assert {round(o["f"]) for o in osc} == {_hz(800)}, osc                      # the value on the slider, saved or not
    assert 3 <= len(osc) <= 6                                                    # ~2 s of beeps at the 5-step rate (0.5 s)
    log = [e for e in audio_log(page) if e["type"] == "tone"]
    assert log and {e["kind"] for e in log} == {"collision-right"} and {e["source"] for e in log} == {"test"}
    # crosswalk out: two tones, the repeat interval is the gap
    page.fill(_row("crosswalk-out", "intervalS"), "0.4")
    page.evaluate("window.__osc.length = 0")
    page.click('#sndRows tr[data-kind="crosswalk-out"] .snd-test')
    page.wait_for_function("() => window.__osc.length >= 2")
    osc = page.evaluate("window.__osc")
    assert len(osc) == 2 and osc[1]["when"] - osc[0]["when"] == pytest.approx(0.2 + 0.4, abs=0.03), osc
    # crosswalk in: one tone
    page.evaluate("window.__osc.length = 0")
    page.click('#sndRows tr[data-kind="crosswalk-in"] .snd-test')
    page.wait_for_function("() => window.__osc.length >= 1")
    page.wait_for_timeout(300)
    assert len(page.evaluate("window.__osc")) == 1


def test_pitch_and_duration_change_the_playback_of_events_live(page, sounds_guard):
    inject_both_sounds(page)
    open_lab(page, LONG_REC, run=FULL_RUN, t=SOFT_T0 - 1, profile=True)
    page.mouse.click(5, 5)
    page.uncheck("#reviewPreviewChk")
    _set(page, _row("collision-center", "pitchHz"), 900)
    _set(page, _row("proximity", "pitchHz"), 100)
    play_window(page, SOFT_T0 - 1, SOFT_T0 + 2.8)
    log = [e for e in audio_log(page) if e["type"] == "tone" and e["source"] == "system"]
    assert {round(e["freq"]) for e in log if e["kind"] == "collision"} == {_hz(900)}, log          # the event's own 1234.5 Hz is overridden by kind
    assert {round(e["freq"]) for e in log if e["kind"] == "proximity"} == {_hz(100)}


def test_speech_speed_multiplies_the_rate_of_every_utterance(page, sounds_guard):
    open_lab(page, SHORT_REC, profile=True)
    page.mouse.click(5, 5)
    page.evaluate("window.__spoken.length = 0")
    _set(page, "#sndSpeech", 1.5)
    page.click("#sndSpeechTest")
    page.wait_for_function("() => window.__spoken.some((s) => s.text === 'speech test')")
    assert page.evaluate("window.__spoken.filter((s) => s.text === 'speech test')[0].rate") == pytest.approx(1.5)
    page.evaluate("window.__spoken.length = 0")
    page.evaluate("window.__labAudio.speak('pole at 12 in 8', 1.25, false, {t: 1, role: 'danger'})")           # a playback phrase at 1.25x
    page.wait_for_function("() => window.__spoken.length >= 1")
    assert page.evaluate("window.__spoken[0].rate") == pytest.approx(1.875)
    _set(page, "#sndSpeech", 2)
    page.evaluate("window.__spoken.length = 0")
    page.evaluate("window.__labAudio.speak('pole at 12 in 7', 1.5, false, {t: 2, role: 'danger'})")
    page.wait_for_function("() => window.__spoken.length >= 1")
    assert page.evaluate("window.__spoken[0].rate") == pytest.approx(2.0)                                     # clamped to the speech engine's range


def inject_kind_episodes(page):
    def ep(t, kind, text):
        return {"t": t, "tEnd": t + 1.0, "type": "beeps", "kind": kind, "role": "danger", "urgency": "danger", "trackId": 1, "label": "person",
                "clock": 12, "clockText": "12", "minSteps": 3, "text": text}
    eps = [ep(30.0, "collision-left", "beeps \u00b7 left \u00b7 e2e person at 11:30 \u00b7 4\u21922 steps"),
           ep(34.0, "collision-center", "beeps \u00b7 center \u00b7 e2e person at 12 \u00b7 3 steps"),
           ep(38.0, "collision-right", "beeps \u00b7 right \u00b7 e2e person at 12:30 \u00b7 3 steps")]
    tones = [{"t": e["t"] + 0.1 * k, "type": "tone", "kind": e["kind"], "role": "danger", "urgency": "danger", "pan": 0.0, "frequencyHz": 1.0,
              "durationSeconds": 0.08} for e in eps for k in range(3)]

    def handle(route):
        resp = route.fetch()
        doc = resp.json()
        doc["events"] = [e for e in doc["events"] if not (e["type"] in ("tone", "beeps") and 29 <= e["t"] <= 40)] + eps + tones
        route.fulfill(response=resp, json=doc)

    page.route(f"**/api/runs/{FULL_RUN}/events.json*", handle)


def test_the_review_panel_shows_the_collision_sectors_and_each_plays_its_pitch(page, sounds_guard):
    inject_kind_episodes(page)
    open_lab(page, LONG_REC, run=FULL_RUN, t=29, profile=True)
    for kind, side in (("collision-left", "left"), ("collision-center", "center"), ("collision-right", "right")):
        row = page.locator(".rv-row.beeps", has_text="e2e person at").and_(page.locator(f'[data-kind="{kind}"]'))
        row.wait_for()
        assert f"beeps \u00b7 {side} \u00b7 e2e person" in row.inner_text() and "\U0001F514" in row.inner_text()
    page.mouse.click(5, 5)
    page.uncheck("#reviewPreviewChk")
    play_window(page, 29.5, 39.5)
    log = [e for e in audio_log(page) if e["type"] == "tone" and e["source"] == "system"]
    by_kind = {k: {round(e["freq"]) for e in log if e["kind"] == k} for k in ("collision-left", "collision-center", "collision-right")}
    assert by_kind == {"collision-left": {660}, "collision-center": {880}, "collision-right": {1100}}, by_kind


def test_apply_timing_rescores_the_open_run_with_the_new_intervals(page, sounds_guard):
    open_lab(page, LONG_REC, run=FULL_RUN, t=1, profile=True)
    assert page.is_hidden("#sndApply")
    page.fill(_row("collision-center", "intervalS"), "1")
    page.wait_for_function("() => !document.querySelector('#sndApply').hidden")
    assert page.is_enabled("#sndApply") and page.is_visible("#sndApplyNote")
    n_before = len([r for r in page.requests if r[1] == "POST" and r[0].endswith(f"/api/runs/{FULL_RUN}/collision")])
    page.click("#sndApply")
    page.wait_for_function("() => document.querySelector('#sndStatus').textContent.includes('applied')", timeout=120_000)
    assert len([r for r in page.requests if r[1] == "POST" and r[0].endswith(f"/api/runs/{FULL_RUN}/collision")]) == n_before + 1
    assert next(k for k in api("/api/sounds")["kinds"] if k["kind"] == "collision-center")["intervalS"] == 1.0
    assert page.is_hidden("#sndApply")
    ev = api(f"/api/runs/{FULL_RUN}/events.json")["events"]
    assert not [e for e in ev if e.get("kind") in ("collision", "crosswalk-enter", "crosswalk-exit")]               # the new kinds only
    kinds = {e["kind"] for e in ev if e["type"] in ("tone", "beeps")}
    assert kinds <= set(KINDS), kinds
    api("/api/sounds", "DELETE")
    api(f"/api/runs/{FULL_RUN}/collision", "POST")                                                                    # back to the default intervals
