"""Fixtures for the Lab browser tests (CONTRACTS section 13).

Real Google Chrome (H.264 proxy playback), autoplay allowed, and two page
hooks installed before any script runs:
  window.__spoken  every speechSynthesis.speak() call (blank unlock utterances
                   excluded), independent of the Lab's own __labAudioLog
  window.__acs     every AudioContext the page creates
"""
import json
import os
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import sync_playwright

BASE = os.environ.get("LAB_URL", "http://127.0.0.1:8765")
LONG_REC = "4929"
SHORT_REC = "4928"

HOOKS = """
window.__spoken = [];
window.__acs = [];
(() => {
  const sp = window.speechSynthesis;
  if (sp) {
    sp.speak = (u) => {
      if ((u.text || '').trim()) {
        const v = document.querySelector('video');
        window.__spoken.push({text: u.text, mediaT: v ? v.currentTime : null});
      }
    };
  }
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

def open_lab(page, rec, t=None, run=None):
    h = f"rec={rec}" + (f"&run={run}" if run else "") + (f"&t={t}" if t is not None else "")
    page.goto(f"{BASE}/#{h}")
    page.wait_for_function("() => { const v = document.querySelector('#video'); return v && v.readyState >= 2 && v.duration > 0; }")
    if run:
        page.wait_for_function("() => document.querySelector('#runBadge').textContent.includes('run ')")


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
