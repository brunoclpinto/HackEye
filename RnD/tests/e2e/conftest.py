"""Fixtures for the Lab browser tests (CONTRACTS section 13).

Real Google Chrome (H.264 proxy playback), autoplay allowed, and two page
hooks installed before any script runs:
  window.__spoken  every speechSynthesis.speak() call (blank unlock utterances
                   excluded), independent of the Lab's own __labAudioLog
  window.__acs     every AudioContext the page creates
  window.__osc     every oscillator the page starts: {f: frequency (Hz), when: start time of the audio clock}

The test recordings (v26.1.14: the footage was renamed, 4928 / 4929 are gone) come from one place, with env overrides:
  HACKEYE_E2E_RECORDING        a recording of at least 2 minutes with a proxy or room to build one (default Chest-center-0002;
                               its 0-120 s hold two crosswalk crossings, 41-50 s and 62-65 s)
  HACKEYE_E2E_SHORT_RECORDING  any short recording for the tests that only need a video to look at (default Chest-center-0005, 88 s)
"""
import json
import os
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import sync_playwright

BASE = os.environ.get("LAB_URL", "http://127.0.0.1:8765")
LONG_REC = os.environ.get("HACKEYE_E2E_RECORDING", "Chest-center-0002")
SHORT_REC = os.environ.get("HACKEYE_E2E_SHORT_RECORDING", "Chest-center-0005")
DEFAULT_LONG_REC = "Chest-center-0002"

HOOKS = """
window.__spoken = [];
window.__acs = [];
(() => {
  const sp = window.speechSynthesis;
  if (sp) {
    sp.speak = (u) => {
      if ((u.text || '').trim()) {
        const v = document.querySelector('video');
        window.__spoken.push({text: u.text, mediaT: v ? v.currentTime : null, rate: u.rate});
      }
      // v26.1.15: the player queue hands one utterance at a time and waits for its end, so the stub reports start / end like a voice
      setTimeout(() => u.onstart && u.onstart({}), 10);
      setTimeout(() => u.onend && u.onend({}), 150);
    };
  }
  window.__osc = [];
  const start = OscillatorNode.prototype.start;
  OscillatorNode.prototype.start = function (when) { window.__osc.push({f: this.frequency.value, when}); return start.apply(this, arguments); };
  const AC = window.AudioContext;
  if (AC) window.AudioContext = class extends AC { constructor(...a) { super(...a); window.__acs.push(this); } };
})();
"""


def api(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise AssertionError(f"{method} {path} -> {e.code} {e.read()[:200]!r}") from None


def clock(sec, decimals=0):
    """The Lab's time format (floor): 87.671 -> 1:27, 3.4 -> 0:03.4."""
    f = 10 ** decimals
    s = int(((sec % 60) * f) + 1e-6) / f
    ss = f"{s:.{decimals}f}".zfill(3 + decimals if decimals else 2)
    return f"{int(sec // 60)}:{ss}"


@pytest.fixture(scope="session", autouse=True)
def _recordings():
    """Both test recordings must exist (clear message otherwise) and have a proxy; returns {id: duration}."""
    import time
    known = {r["id"]: r for r in api("/api/recordings")}
    for rec, env in ((LONG_REC, "HACKEYE_E2E_RECORDING"), (SHORT_REC, "HACKEYE_E2E_SHORT_RECORDING")):
        if rec not in known:
            pytest.exit(f"E2E recording '{rec}' is not in the Lab (have: {sorted(known)[:6]}...). Set {env} to an existing one.",
                        returncode=2)
    for rec in {LONG_REC, SHORT_REC}:
        if known[rec]["proxy"]["status"] != "ready":
            api(f"/api/recordings/{rec}/proxy", "POST")
    t0 = time.time()
    while time.time() - t0 < 600:
        status = {r["id"]: r["proxy"] for r in api("/api/recordings") if r["id"] in (LONG_REC, SHORT_REC)}
        if all(v["status"] == "ready" for v in status.values()):
            break
        bad = [k for k, v in status.items() if v["status"] == "error"]
        assert not bad, f"proxy build failed: {status}"
        time.sleep(3)
    else:
        raise AssertionError(f"proxies not ready after 10 min: {status}")
    durations = {rec: known[rec]["duration"] for rec in (LONG_REC, SHORT_REC)}
    assert durations[LONG_REC] >= 125, f"{LONG_REC} is {durations[LONG_REC]:.0f} s; the tests analyse its first 120 s"
    return durations


@pytest.fixture(scope="session")
def durations(_recordings):
    return _recordings


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True,
                              args=["--autoplay-policy=no-user-gesture-required"])
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    ctx.add_init_script(HOOKS)
    pg = ctx.new_page()
    pg.set_default_timeout(60_000)
    pg.requests = []        # [(url, method)]
    pg.responses = {}       # url -> response headers (lower-case keys)
    pg.on("request", lambda r: pg.requests.append((r.url, r.method)))
    pg.on("response", lambda r: pg.responses.__setitem__(r.url, {k.lower(): v for k, v in r.headers.items()}))
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    yield pg
    ctx.close()


@pytest.fixture
def created_reviews():
    """Collect (rec, id) of annotations a test creates; delete them afterwards (only those ids)."""
    made = []
    yield made
    for rec, ann_id in made:
        try:
            api(f"/api/recordings/{rec}/reviews/{ann_id}", "DELETE")
        except AssertionError:
            pass


# ---- page helpers --------------------------------------------------------

def open_lab(page, rec, t=None, run=None, profile=False):
    """Open the Lab on a recording / run. The Lab-wide sound profile (v26.1.16) overrides the pitch and duration of every tone by kind;
    unless ``profile`` is True the page's profile is cleared once it has loaded, so that injected events sound as they are written."""
    h = f"rec={rec}" + (f"&run={run}" if run else "") + (f"&t={t}" if t is not None else "")
    page.goto(f"{BASE}/#{h}")
    page.wait_for_function("() => { const v = document.querySelector('#video'); return v && v.readyState >= 2 && v.duration > 0; }")
    if run:
        page.wait_for_function("() => document.querySelector('#runBadge').textContent.includes('run ')")
    page.wait_for_function("() => document.querySelectorAll('#sndRows tr').length > 0")
    if not profile:
        page.evaluate("window.__labAudio.setSounds({}, 1)")


def now(page):
    return page.evaluate("document.querySelector('#video').currentTime")


def seek(page, t):
    """Pause and seek exactly like the UI does (setting currentTime), wait for 'seeked'."""
    page.evaluate("""(t) => new Promise((res) => {
        const v = document.querySelector('#video'); v.pause();
        if (Math.abs(v.currentTime - t) < 1e-3 && !v.seeking) return res();
        v.addEventListener('seeked', () => res(), {once: true}); v.currentTime = t; })""", t)
    page.wait_for_timeout(250)


def annotations(rec):
    return api(f"/api/recordings/{rec}/reviews")["annotations"]


def audio_log(page):
    return page.evaluate("window.__labAudioLog || null")
