// Collision-warning audio: look-ahead tone scheduler (WebAudio) + speech (speechSynthesis).
import { clamp, firstAtOrAfter } from "./util.js";

const TICK_MS = 50;
const LOOKAHEAD_S = 0.25;   // real seconds of audio scheduled ahead of the playhead
const PEAK_GAIN = 0.5;
const EDGE_S = 0.005;       // attack/release ramp
const LATE_TOLERANCE_S = 0.03;
const LOG_MAX = 2000;

// v26.1.15 (review 7: a danger waited behind the context phrases before it): the player owns the speech queue. Only one utterance at a
// time is handed to speechSynthesis; a phrase of higher priority than the one speaking cancels it and speaks at once, an equal or
// lower one waits here, and a waiting phrase that cannot start within SPEECH_LATE_S (media seconds) of its event time is dropped:
// speech that is out of time is worse than none.
export const SPEECH_LATE_S = 1.0;
export const SPEECH_PRIORITY = { final: 5, danger: 4, feature: 3, surface: 2, context: 1 };   // thin notices are role "feature"; unknown roles = 1
export const speechPriority = (role) => SPEECH_PRIORITY[role] ?? 1;
const LOST_IDLE_MS = 500;       // handed to speechSynthesis, which then claims to be idle and never reported the end: the utterance is gone
const SPEAK_MAX_BASE_MS = 4000, SPEAK_MAX_PER_CHAR_MS = 150;   // ...or it never reports the end at all: give up after this (scaled by 1/rate)

// E2E hook (CONTRACTS 12.2): one entry per speech phrase spoken / tone scheduled.
// {at (performance.now, ms), mediaT, type: "speech"|"tone", text|freq, source: "system"|"added"}
// plus {type: "speech-error", text, error, voice} when the browser rejects an utterance (v26.1.11 follow-up: Chrome mobile)
// (tones are beeps: parking-sensor style, CONTRACTS §14)
export const audioLog = (window.__labAudioLog = window.__labAudioLog || []);
function logAudio(entry) {
  audioLog.push({ at: performance.now(), ...entry });
  if (audioLog.length > LOG_MAX) audioLog.splice(0, audioLog.length - LOG_MAX);
}

// v26.1.11 (review 4: the browser read "curb" as "tarmac"): the phrases are English, but with no lang and no voice the
// default voice of the OS may be another language. When it is (speechPlan, follow-up 4; an English default keeps the
// pre-v26.1.11 behaviour: no lang, no voice), utterances get lang "en-US" and an English voice, picked from
// speechSynthesis.getVoices() (loaded asynchronously: cached, refreshed on "voiceschanged"). No English voice: lang alone.
// Chrome Android: network voices often fail (error "synthesis-failed"/"network"), so a localService voice wins there, and a
// voice that makes speak() error is dropped for good: the phrase is retried once with lang "en-US" only.
// v26.1.12 (review 5: the Mac voice read "curb" as "tarmac"): the text sent to the synthesizer goes through a pronunciation
// map, the display text (events, reviews) stays as it is. Lab-only; logged in the client-log "speak" entries as `spoken`.
export const PRONUNCIATIONS = [[/\bcurb\b/gi, "kerb"]];
export function pronounce(text) {
  return PRONUNCIATIONS.reduce((s, [re, to]) => s.replace(re, to), text);
}
// Remote diagnostics (CONTRACTS 12.2): speech events are batched to POST /api/client-log (debug/lab/client-log.jsonl).
const CLIENT_LOG_URL = "/api/client-log";
const CLIENT_LOG_FLUSH_MS = 2000;
const CLIENT_LOG_QUEUE_MAX = 300;
const clientQueue = [];
let toneCount = 0;           // beeps scheduled since the last flush (one summary entry per batch, not one per beep)
export function clientLog(type, data = {}) {
  clientQueue.push({ ts: Date.now(), at: Math.round(performance.now()), type, ...data });
  if (clientQueue.length > CLIENT_LOG_QUEUE_MAX) clientQueue.splice(0, clientQueue.length - CLIENT_LOG_QUEUE_MAX);
}
export function flushClientLog(beacon = false) {
  if (toneCount) { clientLog("tones", { count: toneCount }); toneCount = 0; }
  if (!clientQueue.length) return;
  const body = JSON.stringify(clientQueue.splice(0));
  try {
    if (beacon && navigator.sendBeacon?.(CLIENT_LOG_URL, new Blob([body], { type: "application/json" }))) return;
    fetch(CLIENT_LOG_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => {});
  } catch { /* diagnostics never break the page */ }
}
setInterval(() => flushClientLog(), CLIENT_LOG_FLUSH_MS);
document.addEventListener("visibilitychange", () => { if (document.hidden) flushClientLog(true); });
function logVoices(reason) {
  const present = "speechSynthesis" in window;
  const voices = present ? (speechSynthesis.getVoices?.() || []) : [];
  clientLog("voices", {
    reason, ua: navigator.userAgent, speechSynthesis: present, count: voices.length, mode: speechMode, chosen: englishVoice?.name ?? null,
    voices: voices.slice(0, 20).map((v) => ({ name: v.name, lang: v.lang, localService: v.localService, default: v.default })),
  });
}
function synthState() {
  if (!("speechSynthesis" in window)) return {};
  return { speaking: speechSynthesis.speaking, pending: speechSynthesis.pending, paused: speechSynthesis.paused };
}

// v26.1.16: the Lab-wide sound profile (GET/PUT /api/sounds). Pitch and duration per sound kind and the speech speed apply to playback
// live (the player overrides the event's own values); the repeat intervals shape the tone schedule, so they need a collision re-run.
export const SOUND_KIND_ALIASES = { collision: "collision-center", "crosswalk-enter": "crosswalk-in", "crosswalk-exit": "crosswalk-out" };
export const canonSoundKind = (kind) => (kind ? SOUND_KIND_ALIASES[kind] ?? kind : "collision-center");

const SPEECH_LANG = "en-US";
const ANDROID = /Android/i.test(navigator.userAgent || "");
let englishVoice = null;
let voiceFailed = false;
// macOS novelty / Eloquence voices (v26.1.11 follow-up: Chrome macOS picked "Albert"): never chosen (name prefix, case-insensitive).
const NOVELTY_VOICES = ["Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Good News", "Jester", "Organ", "Superstar",
  "Trinoids", "Whisper", "Wobble", "Zarvox", "Fred", "Junior", "Ralph", "Kathy", "Eddy", "Flo", "Grandma", "Grandpa", "Reed", "Rocko", "Sandy", "Shelley"]
  .map((n) => n.toLowerCase());
const NATURAL_VOICES = /^(Samantha|Alex|Google US English|Google UK English (Female|Male)|Daniel|Karen|Moira|Tessa|Serena|Ava|Allison|Susan|Tom|Nicky)\b/i;
// Ranking: [Android: localService] > default English voice of the platform > known natural voice ((Enhanced)/(Premium) first) > en-US > any en.
export function rankVoice(v) {
  const name = v.name || "";
  return (v.localService && ANDROID ? 10000 : 0) + (v.default ? 1000 : 0) + (NATURAL_VOICES.test(name) ? 100 : 0)
    + (/\((Enhanced|Premium)\)/i.test(name) ? 20 : 0) + (/^en[-_]US$/i.test(v.lang) ? 10 : 0) + (v.localService ? 1 : 0);
}
export function chooseEnglishVoice(voices) {
  const en = voices.filter((v) => /^en([-_]|$)/i.test(v.lang || "") && !NOVELTY_VOICES.some((n) => (v.name || "").toLowerCase().startsWith(n)));
  return en.sort((a, b) => rankVoice(b) - rankVoice(a))[0] || null;
}
// v26.1.11 follow-up 4: "system" mode = the voice the platform would use anyway is English, so speak as before v26.1.11
// (neither lang nor voice set). "english" mode = lang "en-US" + the ranked English voice (the default voice is another
// language, e.g. an iPhone listing Joana pt-PT first) or lang alone while the voices are not loaded / none is English.
export function speechPlan(voices) {
  const def = voices.find((v) => v.default) || voices[0];
  if (def && /^en([-_]|$)/i.test(def.lang || "")) return { mode: "system", voice: null };
  return { mode: "english", voice: chooseEnglishVoice(voices) };
}
let speechMode = "english";
function refreshVoice() {
  if (!("speechSynthesis" in window)) return;
  const plan = speechPlan(speechSynthesis.getVoices?.() || []);
  speechMode = plan.mode;
  if (!voiceFailed) englishVoice = plan.voice;
}
const IGNORED_SPEECH_ERRORS = ["interrupted", "canceled"];   // our own cancel(): not a failure
if ("speechSynthesis" in window) {
  refreshVoice();
  speechSynthesis.addEventListener?.("voiceschanged", () => { refreshVoice(); logVoices("voiceschanged"); });
}
logVoices("load");
clientLog("page", { ua: navigator.userAgent, url: location.href.split("#")[0] });

// Chrome drops the events of an utterance it garbage-collected: every live one is referenced here until it ends / errors.
const liveUtterances = new Set();
const WATCHDOG_MS = 1500;    // no onstart this long after speak() while the synthesis claims to be busy: it is stuck

// Stuck speech engine (CONTRACTS 12.2): Chrome on a Mac can stay "speaking" for the whole browser session without ever
// firing onstart. Detection only; it never changes how speech is produced.
const STUCK_AFTER = 2;       // consecutive utterances (a phrase and its retry count separately) that never started
let noStartRun = 0;
let speechStuck = false;
export function stuckHint(ua = navigator.userAgent, platform = navigator.platform || "", touch = navigator.maxTouchPoints || 0) {
  if (/iPhone|iPad|iPod|CriOS/.test(ua) || (platform === "MacIntel" && touch > 1)) return "Close the browser from the app switcher, then reopen it.";
  if (/Macintosh|Mac OS X/.test(ua)) return "Quit Chrome with Cmd+Q (closing the window is not enough), then reopen it.";
  return "Close all browser windows and reopen it.";
}
function showStuckNotice() {
  const el = document.getElementById("speechStuck");
  if (!el) return;
  el.querySelector(".msg").textContent = `Speech isn't working: the browser's speech engine isn't responding. Quit the browser completely and reopen it. ${stuckHint()} Beeps still work.`;
  el.hidden = false;
}
function noteNoStart() {
  noStartRun++;
  if (noStartRun >= STUCK_AFTER && !speechStuck) {
    speechStuck = true;
    clientLog("speech-stuck", { consecutive: noStartRun });
    showStuckNotice();
  }
}
function noteStarted() {
  noStartRun = 0;
  if (!speechStuck) return;
  speechStuck = false;
  const el = document.getElementById("speechStuck");
  if (el) el.hidden = true;
}
document.getElementById("speechStuckClose")?.addEventListener("click", () => { document.getElementById("speechStuck").hidden = true; });

export class AudioEngine {
  constructor(video) {
    this.video = video;
    this.ctx = null;
    this.master = null;
    this.on = true;            // armed by default (the toggle button); the context itself is unlocked by the first gesture
    this.speechOn = true;
    this.tonesOn = true;
    this.muted = false;
    this.volume = 0.8;
    this.offsetS = 0;          // user-tunable audio delay (+ = audio later), for sync experiments
    this.tones = [];           // tone events sorted by t
    this.speech = [];          // speech events sorted by t
    this.scheduled = new Set();// tone event objects already scheduled
    this.nodes = new Set();    // live {osc, gain, pan}
    this.lastT = null;         // previous tick's media time (speech crossing detection)
    this.speechPrimed = false; // the silent utterance was accepted inside a real user activation
    this.resuming = false;
    this.probe = null;         // "Test speech" button: collects the outcome of the utterance(s) it caused
    this.sounds = {};          // v26.1.16: {kind: {pitchHz, durationMs, intervalS}} from the profile (empty = the events' own values)
    this.speechRate = 1;       // v26.1.16: multiplies the speech rate (the profile's "Speech speed")
    this.queue = [];           // v26.1.15: phrases waiting for the one being spoken, best first {text, rate, ev, prio, t}
    this._cur = null;          // the entry handed to speechSynthesis (its utterance chain: phrase + retry), null = idle

    // Real discontinuities: drop everything scheduled, forget where we were, cut the phrase being spoken.
    for (const ev of ["seeking", "pause", "ratechange", "ended", "emptied"]) {
      video.addEventListener(ev, () => this.reset());
    }
    // Mobile fires waiting/playing all the time while buffering: only the tone schedule restarts (speech keeps going;
    // Chrome Android also drops a speak() that comes right after cancel()).
    for (const ev of ["waiting", "playing"]) {
      video.addEventListener(ev, () => this.resetTones());
    }
    // Mobile suspends audio in the background; the context comes back on the next gesture (or right here if allowed).
    document.addEventListener("visibilitychange", () => { if (!document.hidden) this.resumeCtx(); });
    clientLog("engine", { visibility: document.visibilityState });
    setInterval(() => this.tick(), TICK_MS);
  }

  /** Tones are only scheduled into a running context (a suspended one would hold them silent forever). */
  get enabled() { return this.on && !!this.ctx && this.ctx.state === "running"; }

  /** Resume a suspended / "interrupted" (iOS) context; never throws. Outside a user activation the browser may refuse: harmless. */
  resumeCtx() {
    const ctx = this.ctx;
    if (!ctx || ctx.state === "running" || ctx.state === "closed" || this.resuming) return;
    this.resuming = true;
    Promise.resolve().then(() => ctx.resume()).catch(() => {}).finally(() => { this.resuming = false; });
  }

  /** The "Audio on/off" toggle. Off silences everything and stops scheduling. */
  setOn(on) {
    this.on = on;
    if (!on) this.reset();
  }

  /**
   * Arm audio for the whole page. Browsers only unlock audio inside a user *activation*, and on Android Chrome a touch
   * `pointerdown` is not one (activation comes with pointerup / touchend / click; keydown for keys). So the listeners are
   * on those events and stay for the page's life: every gesture re-runs enable() until the context is "running" and the
   * speech prime was accepted, and afterwards resumes a context the browser suspended again.
   */
  armOnFirstGesture(onUnlocked) {
    const evs = ["pointerup", "touchend", "click", "keydown"];
    let reported = false;
    const onGesture = () => {
      if (!this.on) return;                                  // toggled off: nothing to unlock
      if (this.ctx && this.ctx.state === "running" && this.speechPrimed) return;
      this.enable().then(
        () => { if (!reported && this.ctx.state === "running") { reported = true; onUnlocked?.(); } },
        () => { if (!reported) { reported = true; onUnlocked?.(new Error("audio unlock failed")); } },
      );
    };
    for (const e of evs) window.addEventListener(e, onGesture, { capture: true });
  }

  /** Must be called from a user activation (iOS and Chrome mobile require it to create/unlock audio). Safe to repeat. */
  async enable() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC();
      this.master = this.ctx.createGain();
      this.master.connect(this.ctx.destination);
      this.applyVolume();
    }
    if (this.ctx.state !== "running") {
      try { await this.ctx.resume(); } catch { /* not allowed yet: the next gesture retries */ }
      clientLog("unlock", { ctx: this.ctx.state, sampleRate: this.ctx.sampleRate });
      // iOS unlock: play one silent buffer inside the gesture.
      const src = this.ctx.createBufferSource();
      src.buffer = this.ctx.createBuffer(1, 1, 22050);
      src.connect(this.ctx.destination);
      src.start(0);
    }
    // Same for speech synthesis: a silent utterance within the gesture ("not-allowed" -> try again on the next one).
    // Not on Android: its TTS engine may never fire end/error for a whitespace-only utterance, which would leave
    // speaking/pending true and the queue stuck behind it for good. Chrome only needs the sticky activation the gesture
    // already gave for the real speak() calls, so there the prime is skipped (a "not-allowed" error still re-arms it).
    if (!this.speechPrimed && "speechSynthesis" in window) {
      this.speechPrimed = true;
      if (ANDROID) { clientLog("prime", { skipped: true, ...synthState() }); }
      else {
        const u = new SpeechSynthesisUtterance(" ");
        u.volume = 0;
        liveUtterances.add(u);
        const done = () => liveUtterances.delete(u);
        u.onend = done;
        u.onerror = (e) => {
          done();
          clientLog("prime-error", { error: e.error });
          if (e.error === "not-allowed") this.speechPrimed = false;
          else if (!IGNORED_SPEECH_ERRORS.includes(e.error)) console.warn("speech prime error:", e.error);
        };
        clientLog("prime", { skipped: false, ...synthState() });
        speechSynthesis.speak(u);
      }
    }
  }

  /** The sound profile: {kinds: {kind: {pitchHz, durationMs, intervalS}}, speechRate}. Applies at once to tones not yet scheduled. */
  setSounds(kinds, speechRate = 1) {
    this.sounds = kinds || {};
    this.speechRate = clamp(Number(speechRate) || 1, 0.5, 2);
  }

  setEvents(events) {
    const byT = (a, b) => a.t - b.t;
    this.tones = events.filter((e) => e.type === "tone").sort(byT);
    this.speech = events.filter((e) => e.type === "speech").sort(byT);
    this.reset();
  }

  /** Replace only the tone list (⊘-silenced beeps removed, added beeps merged) without cutting off tones already scheduled. */
  setToneEvents(tones) {
    this.tones = [...tones].sort((a, b) => a.t - b.t);
  }

  /** Replace only the speech list (review edits merged / removed) without cutting off tones or the phrase being spoken. */
  setSpeechEvents(speech) {
    this.speech = [...speech].sort((a, b) => a.t - b.t);
  }

  applyVolume() {
    if (this.master) this.master.gain.value = this.muted ? 0 : this.volume;
  }
  setVolume(v) { this.volume = v; this.applyVolume(); }
  setMuted(m) {
    this.muted = m;
    this.applyVolume();
    if (m) this.cancelSpeech();
  }
  setTones(on) { this.tonesOn = on; if (!on) this.reset(); }
  setSpeech(on) { this.speechOn = on; if (!on) this.cancelSpeech(); }

  /** Only cancel when something is queued: Chrome Android drops a speak() that follows an idle cancel(). Also forgets the player queue. */
  cancelSpeech() {
    this.queue.length = 0;
    if (this._cur) { const cur = this._cur; this._cur = null; clearTimeout(cur.handTimer); cur.abort?.(); }
    if (!("speechSynthesis" in window)) return;
    if (speechSynthesis.speaking || speechSynthesis.pending) this.cancelNow("cancelSpeech");
  }

  /** The one place that calls speechSynthesis.cancel(): logged with its reason and the state before it. */
  cancelNow(reason) {
    clientLog("cancel", { reason, ...synthState() });
    speechSynthesis.cancel();
  }

  /** Stop all scheduled tones and forget the scheduling state (speech untouched). */
  resetTones() {
    for (const n of this.nodes) {
      try { n.osc.stop(); } catch { /* already stopped */ }
      n.osc.disconnect(); n.gain.disconnect(); n.pan.disconnect();
    }
    this.nodes.clear();
    this.scheduled.clear();
    this.lastT = null;
  }

  /** Stop all scheduled tones, forget scheduling state, cancel speech. */
  reset() {
    this.resetTones();
    this.cancelSpeech();
  }

  tick() {
    const v = this.video;
    this.speechHousekeeping();
    if (this.on && this.ctx && this.ctx.state !== "running") this.resumeCtx();
    if (!this.enabled || v.paused || v.seeking || v.ended || v.readyState < 3) { this.lastT = null; return; }
    const cur = v.currentTime;
    const rate = v.playbackRate || 1;
    // Event times are shifted by the user offset: an event at t is *heard* at t + offset.
    const shift = this.offsetS;

    if (this.tonesOn && !this.muted) this.scheduleTones(cur, rate, shift);
    if (this.speechOn && !this.muted) this.maybeSpeak(cur, rate, shift);
    else this.lastT = cur; // keep tracking so toggling speech back on doesn't replay old events
  }

  /**
   * Media time -> AudioContext time: ctxTime = ctx.currentTime + (mediaT - cur) / rate.
   * Schedule every tone whose media time falls within the next LOOKAHEAD_S of *real* time
   * (= LOOKAHEAD_S * rate of media time). Each is scheduled once (index set) and
   * keeps playing on the audio clock even if a later tick has jitter.
   */
  scheduleTones(cur, rate, shift) {
    const lo = cur - shift - LATE_TOLERANCE_S * rate;
    const hi = cur - shift + LOOKAHEAD_S * rate;
    const now = this.ctx.currentTime;
    for (let i = firstAtOrAfter(this.tones, lo); i < this.tones.length; i++) {
      const e = this.tones[i];
      if (e.t > hi) break;
      if (this.scheduled.has(e)) continue;
      this.scheduled.add(e);
      const when = now + (e.t + shift - cur) / rate;
      this.playTone(e, Math.max(when, now));
    }
  }

  /**
   * One tone event. `collision` (default, no `kind`): a parking beep, `PEAK_GAIN`, 5 ms edges. `proximity` (v26.1.13 follow-up): the
   * event carries its own `frequencyHz`, `gain` and `chirp` {count, gapSeconds, attackSeconds}: `count` soft sines of
   * `durationSeconds` each, `gapSeconds` apart, with a slower attack. `crosswalk-enter` / `crosswalk-exit` (v26.1.14) use the same
   * fields: a deep (330 Hz) long tone for stepping onto a crosswalk, two short ones for stepping off.
   */
  playTone(e, when) {
    // v26.1.16: pitch and duration come from the sound profile by kind (the event's own values when there is none). A continuous
    // collision chunk (gapless tone close to the obstacle) keeps its length.
    const prof = this.sounds[canonSoundKind(e.kind)];
    if (prof) {
      e = { ...e };
      if (prof.pitchHz) e.frequencyHz = prof.pitchHz;
      if (prof.durationMs && !e.continuous) e.durationSeconds = prof.durationMs / 1000;
    }
    const chirp = e.chirp ?? null;
    const count = Math.max(1, Math.min(4, chirp?.count ?? 1));
    const step = Math.max(0.03, e.durationSeconds || 0.08) + (chirp?.gapSeconds ?? 0);
    const peak = clamp(e.gain ?? PEAK_GAIN, 0, 1);
    const edge = chirp?.attackSeconds ?? EDGE_S;
    for (let k = 0; k < count; k++) this._tonePart(e, when + k * step, peak, edge, k === 0);
  }

  _tonePart(e, when, peak, edge, first) {
    const ctx = this.ctx;
    const dur = Math.max(0.03, e.durationSeconds || 0.08);
    const ramp = Math.min(edge, dur / 2);
    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = e.frequencyHz || 880;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0, when);
    gain.gain.linearRampToValueAtTime(peak, when + ramp);
    gain.gain.setValueAtTime(peak, when + dur - ramp);
    gain.gain.linearRampToValueAtTime(0, when + dur);
    const pan = ctx.createStereoPanner();
    pan.pan.value = clamp(e.pan ?? 0, -1, 1);
    osc.connect(gain).connect(pan).connect(this.master);
    const node = { osc, gain, pan };
    this.nodes.add(node);
    osc.onended = () => {
      this.nodes.delete(node);
      osc.disconnect(); gain.disconnect(); pan.disconnect();
    };
    osc.start(when);
    osc.stop(when + dur + 0.01);
    if (!first) return;                      // one count and one log entry per tone event, whatever its chirp
    toneCount++;
    logAudio({ mediaT: e.t, type: "tone", freq: osc.frequency.value, dur, kind: e.kind ?? "collision", gain: peak, source: e.source ?? "system" });
  }

  /**
   * The ▶ test button of the sound tuner (v26.1.16): plays one sound kind with the values given ({pitchHz, durationMs, intervalS}), inside
   * the click. Collision kinds: ~2 s of beeps at the 5-step rate (one every intervalS); proximity: the soft double chirp every intervalS for
   * ~2 s; crosswalk-in: the single long tone; crosswalk-out: two tones intervalS apart. Resolves once scheduled.
   */
  async testSound(kind, values, pan = 0) {
    await this.enable();
    if (!this.ctx || this.ctx.state !== "running") return false;
    const when0 = this.ctx.currentTime + 0.05;
    const dur = Math.max(0.02, (values.durationMs || 80) / 1000);
    const base = { type: "tone", kind, urgency: "none", pan, frequencyHz: values.pitchHz, durationSeconds: dur, source: "test", t: this.video.currentTime };
    const iv = Math.max(0.05, values.intervalS || 0.5);
    const profile = this.sounds; this.sounds = {};            // the values given are the ones to hear (the profile may lag one debounce)
    try {
      if (kind.startsWith("collision")) {
        for (let t = 0; t < 2; t += iv) this.playTone({ ...base, role: "danger", urgency: "danger" }, when0 + t);
      } else if (kind === "proximity") {
        const chirp = { count: 2, gapSeconds: 0.1, attackSeconds: 0.04 };
        for (let t = 0; t < 2; t += Math.max(iv, 2 * dur + 0.3)) this.playTone({ ...base, gain: 0.25, chirp }, when0 + t);
      } else if (kind === "crosswalk-out") {
        this.playTone({ ...base, gain: 0.5, chirp: { count: 2, gapSeconds: iv, attackSeconds: 0.02 } }, when0);
      } else {
        this.playTone({ ...base, gain: 0.5, chirp: { count: 1, gapSeconds: 0, attackSeconds: 0.03 } }, when0);
      }
    } finally { this.sounds = profile; }
    return true;
  }

  /** Speak when the playhead *crosses* an event time during normal playback (not on seeks). */
  maybeSpeak(cur, rate, shift) {
    const prev = this.lastT;
    this.lastT = cur;
    if (prev === null) return;
    // A jump much larger than one tick of real time is a seek/stall, not playback: ignore.
    if (cur <= prev || cur - prev > 0.5 * rate + 0.2) return;
    const a = prev - shift, b = cur - shift;
    for (let i = firstAtOrAfter(this.speech, a); i < this.speech.length && this.speech[i].t <= b; i++) {
      const e = this.speech[i];
      if (e.t <= a) continue;
      this.speak(e.text, rate, e.role === "final", e);     // (v26.1.15: every phrase of the window goes to the player queue, which orders them)
    }
  }

  /**
   * One phrase whose time has come (v26.1.15 player queue). It is logged at once (the audio log is "what the playhead crossed"), then:
   * nothing speaking -> spoken now; a higher priority than the phrase being spoken (final > danger > feature > surface > context) ->
   * that one is cancelled and this one is spoken at once; otherwise it waits in the queue, where it is dropped as late if it cannot
   * start within SPEECH_LATE_S media seconds of its event time.
   */
  speak(text, rate, final = false, ev = null) {
    logAudio({ mediaT: ev?.t ?? this.video.currentTime, type: "speech", text, source: ev?.source ?? "system" });
    if (!("speechSynthesis" in window)) return;
    const role = final ? "final" : ev?.role;
    const entry = { text, rate: clamp(rate * this.speechRate, 0.5, 2), ev, role, prio: speechPriority(role), t: ev?.t ?? this.video.currentTime, source: ev?.source ?? "system" };
    const cur = this._cur;
    if (cur && entry.prio > cur.prio) this._preempt(entry);
    else { this.queue.push(entry); this.queue.sort((x, y) => y.prio - x.prio || x.t - y.t); this._pump(); }
  }

  /** Media time "now" in the frame of the event times (the user offset shifts when an event is heard). */
  _eventNow() { return this.video.currentTime - this.offsetS; }

  /** Drop what has waited too long: a phrase that cannot start within SPEECH_LATE_S of its event time is not said. */
  _dropLate() {
    const now = this._eventNow();
    this.queue = this.queue.filter((e) => {
      const late = now - e.t;
      if (late <= SPEECH_LATE_S) return true;
      logAudio({ mediaT: e.t, type: "speech-dropped-late", text: e.text, lateS: +late.toFixed(2), role: e.role ?? null, source: e.source });
      clientLog("speech-dropped-late", { text: e.text, role: e.role ?? null, lateS: +late.toFixed(2) });
      return false;
    });
  }

  /** Hand the best waiting phrase to speechSynthesis when none of ours is speaking. */
  _pump() {
    if (this._cur) return;
    this._dropLate();
    const next = this.queue.shift();
    if (next) this._handOff(next, false);
  }

  _handOff(entry, afterCancel) {
    this._cur = entry;
    entry.maxMs = SPEAK_MAX_BASE_MS + SPEAK_MAX_PER_CHAR_MS * entry.text.length / entry.rate;
    const go = () => {
      if (this._cur !== entry) return;
      entry.handedAt = performance.now();
      if (afterCancel) { if (speechSynthesis.paused) speechSynthesis.resume(); }   // (our own cancel just emptied the queue: nothing to unstick)
      else this.unstick();
      this.say(entry.text, entry.rate, true, null, entry);
    };
    // Chrome Android drops a speak() that is glued to a cancel(): after a deliberate cancel it waits a moment (elsewhere: at once)
    if (afterCancel && ANDROID) entry.handTimer = setTimeout(go, 60); else go();
  }

  /** A phrase of higher priority than the one being spoken: cut that one off and speak this at once. The cancel is ours: the aborted
   *  utterance is retired first, so neither the watchdog nor the stuck notice ever sees it. */
  _preempt(entry) {
    const cur = this._cur;
    const started = !!cur.u?._started;
    clientLog("speech-preempted", { text: cur.text, by: entry.text, role: cur.role ?? null, byRole: entry.role ?? null, started });
    logAudio({ mediaT: cur.t, type: "speech-preempted", text: cur.text, by: entry.text, started, source: cur.source });
    this._cur = null;
    clearTimeout(cur.handTimer);
    cur.abort?.();
    if (!started) { this.queue.push(cur); this.queue.sort((x, y) => y.prio - x.prio || x.t - y.t); }   // never heard: it may still be on time
    const busy = speechSynthesis.speaking || speechSynthesis.pending;
    if (busy) this.cancelNow("preempt");
    this._handOff(entry, busy);
  }

  /** The entry's utterance chain has ended (spoken, failed for good, or lost): the next phrase may go. */
  _entryDone(entry) {
    if (this._cur !== entry) return;
    this._cur = null;
    clearTimeout(entry.handTimer);
    this._pump();
  }

  /** Every tick: late phrases leave the queue; an utterance the engine silently lost (it claims to be idle, or never ends) is let go,
   *  so that one missing end event cannot block the phrases behind it. */
  speechHousekeeping() {
    if (this.queue.length) this._dropLate();
    const cur = this._cur;
    if (!cur || !cur.handedAt || !("speechSynthesis" in window)) return;
    const now = performance.now();
    const busy = speechSynthesis.speaking || speechSynthesis.pending;
    if (busy) cur.idleSince = null;
    else if (cur.idleSince == null) cur.idleSince = now;
    const lost = !busy && now - cur.idleSince > LOST_IDLE_MS;
    const hung = now - cur.handedAt > cur.maxMs;
    if (!lost && !hung) return;
    clientLog(hung ? "utt-hung" : "utt-lost", { text: cur.text, started: !!cur.u?._started, ms: Math.round(now - cur.handedAt), ...synthState() });
    cur.abort?.();
    if (hung) this.cancelNow("utt-hung");
    this._entryDone(cur);
  }

  /** Before a new phrase: un-pause, and clear a queue that is busy but holds nothing of ours (e.g. a lost prime) or only an
   *  utterance that never started. */
  unstick() {
    if (speechSynthesis.paused) { clientLog("resume", synthState()); speechSynthesis.resume(); }   // Chrome Android sometimes leaves it stuck paused
    if (!(speechSynthesis.speaking || speechSynthesis.pending)) return;
    const now = performance.now();
    if ([...liveUtterances].some((u) => u._started)) return;   // one of ours is being heard: never cut it
    const stale = [...liveUtterances].some((u) => u._t0 !== undefined && !u._started && now - u._t0 > WATCHDOG_MS);
    if (liveUtterances.size === 0 || stale) this.cancelNow(stale ? "stuck-queue-stale" : "stuck-queue-foreign");
  }

  /** "Test speech" button: speaks directly inside the click and resolves (<= 3 s) with what the browser did. */
  testSpeech(rate = this.speechRate) {
    const probe = { started: false, ended: false, error: null, voice: null, retried: false };
    this.probe = probe;
    const voices = "speechSynthesis" in window ? (speechSynthesis.getVoices?.() || []).length : 0;
    if (!("speechSynthesis" in window)) return Promise.resolve({ ...probe, voices, outcome: "no speechSynthesis", ...synthState() });
    clientLog("test-speech", synthState());
    this.unstick();
    this.say("speech test", clamp(rate, 0.5, 2), true);
    return new Promise((resolve) => setTimeout(() => {
      this.probe = null;
      const outcome = probe.error ? `error ${probe.error}` : probe.ended ? "ended" : probe.started ? "started" : "no event";
      const res = { ...probe, voices, outcome, ...synthState() };
      clientLog("test-speech-result", res);
      flushClientLog();
      resolve(res);
    }, 2800));
  }

  /**
   * One utterance. Events are logged with the elapsed ms; the utterance is referenced until it ends (Chrome GCs the rest).
   * Watchdog: no onstart within WATCHDOG_MS while the synthesis is busy -> cancel and speak it again once, without the voice.
   * It only runs while none of our utterances is being heard (a phrase queued behind a speaking one is just waiting): it is
   * armed at speak() if nothing of ours has started, else when the utterance ahead ends / errors; it never cancels a started one.
   * A voice that errors (or never starts) is retried once with lang "en-US" only, and dropped for good only if that retry starts.
   * `suspect` = the voice of the failed attempt this call retries without.
   * `entry` (v26.1.15) = the player-queue entry this utterance chain belongs to: it is done when the chain ends (end, failure for good,
   * or a retry that ended); a retry hands the entry on, an abort (preemption, seek, mute) retires the utterance without a trace.
   */
  say(text, rate, mayRetry, suspect = null, entry = null) {
    const spoken = pronounce(text);
    const u = new SpeechSynthesisUtterance(spoken);
    if (speechMode !== "system") u.lang = SPEECH_LANG;        // system mode: neither lang nor voice (platform default)
    if (!englishVoice && !voiceFailed) refreshVoice();
    const voice = speechMode === "system" || voiceFailed || suspect ? null : englishVoice;
    if (voice) u.voice = voice;
    u.rate = rate;
    u.volume = this.volume;
    const probe = this.probe;
    if (probe) probe.voice = voice?.name ?? null;
    const t0 = performance.now();
    u._started = false;                                        // u._t0 = when its watchdog was armed (unset while it waits)
    let settled = false;                                       // ended / errored / replaced by the watchdog
    let timer = null;
    let retired = false;                                       // this attempt handed the entry on (retry) or was aborted: its events no longer end it
    const conclude = () => { if (entry && !retired) this._entryDone(entry); };
    if (entry) {
      entry.u = u;
      entry.abort = () => { retired = true; settled = true; clearTimeout(timer); liveUtterances.delete(u); };
    }
    const ms = () => Math.round(performance.now() - t0);
    const fire = () => {
      timer = null;
      if (settled || u._started || !(speechSynthesis.speaking || speechSynthesis.pending)) return;
      if ([...liveUtterances].some((o) => o._started)) return;    // one of ours started meanwhile: re-armed when it ends
      clientLog("watchdog", { text, voice: voice?.name ?? null, retry: mayRetry, ms: ms(), ...synthState() });
      finish(false);
      noteNoStart();
      if (mayRetry) retired = true;                                       // the retry carries the entry on; the cancel below must not end it
      this.cancelNow("watchdog");
      if (!mayRetry) { conclude(); return; }
      if (probe) probe.retried = true;
      setTimeout(() => { if (!entry || this._cur === entry) this.say(text, rate, false, voice || null, entry); }, 60);   // Chrome Android drops a speak() glued to a cancel()
    };
    u._arm = () => {
      if (settled || u._started || timer || [...liveUtterances].some((o) => o._started)) return;
      u._t0 = performance.now();
      timer = setTimeout(fire, WATCHDOG_MS);
    };
    const finish = (rearm = true) => {
      settled = true; clearTimeout(timer); liveUtterances.delete(u);
      if (rearm) for (const o of liveUtterances) o._arm?.();   // the phrases queued behind this one start waiting now
    };
    clientLog("speak", { text, spoken, voice: voice?.name ?? null, lang: u.lang, rate: u.rate, volume: u.volume, retry: !mayRetry, ...synthState() });
    u.onstart = () => {
      if (settled) return;
      u._started = true; clearTimeout(timer);
      noteStarted();
      if (suspect) { voiceFailed = true; englishVoice = null; clientLog("voice-dropped", { voice: suspect.name }); }   // without it, it starts
      if (probe) probe.started = true;
      clientLog("utt-start", { text, ms: ms() });
    };
    u.onend = () => {
      if (probe) probe.ended = true;
      clientLog("utt-end", { text, ms: ms() });
      finish();
      conclude();
    };
    u.onerror = (e) => {
      const error = e.error || "unknown";
      clientLog("utt-error", { text, error, voice: voice?.name ?? null, ms: ms() });
      finish();
      if (IGNORED_SPEECH_ERRORS.includes(error)) { conclude(); return; }
      if (probe) probe.error = error;
      console.warn("speech error:", error, "voice:", voice?.name ?? null, "text:", text);
      logAudio({ mediaT: this.video.currentTime, type: "speech-error", text, error, voice: voice?.name ?? null });
      if (error === "not-allowed") { this.speechPrimed = false; conclude(); }   // the next gesture primes again
      else if (voice && mayRetry) { retired = true; this.say(text, rate, false, voice, entry); }
      else conclude();
    };
    liveUtterances.add(u);
    speechSynthesis.speak(u);
    u._arm();
  }
}
