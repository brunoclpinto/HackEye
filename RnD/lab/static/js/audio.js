// Collision-warning audio: look-ahead tone scheduler (WebAudio) + speech (speechSynthesis).
import { clamp, firstAtOrAfter } from "./util.js";

const TICK_MS = 50;
const LOOKAHEAD_S = 0.25;   // real seconds of audio scheduled ahead of the playhead
const PEAK_GAIN = 0.5;
const EDGE_S = 0.005;       // attack/release ramp
const LATE_TOLERANCE_S = 0.03;

export class AudioEngine {
  constructor(video) {
    this.video = video;
    this.ctx = null;
    this.master = null;
    this.speechOn = true;
    this.tonesOn = true;
    this.muted = false;
    this.volume = 0.8;
    this.offsetS = 0;          // user-tunable audio delay (+ = audio later), for sync experiments
    this.tones = [];           // tone events sorted by t
    this.speech = [];          // speech events sorted by t
    this.scheduled = new Set();// indices into this.tones already scheduled
    this.nodes = new Set();    // live {osc, gain, pan}
    this.lastT = null;         // previous tick's media time (speech crossing detection)

    // Any discontinuity: drop everything scheduled and forget where we were.
    for (const ev of ["seeking", "pause", "ratechange", "ended", "waiting", "playing", "emptied"]) {
      video.addEventListener(ev, () => this.reset());
    }
    setInterval(() => this.tick(), TICK_MS);
  }

  get enabled() { return !!this.ctx; }

  /** Must be called from a user gesture (iOS requires this to create/unlock audio). */
  async enable() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC();
      this.master = this.ctx.createGain();
      this.master.connect(this.ctx.destination);
      this.applyVolume();
    }
    await this.ctx.resume();
    // iOS unlock: play one silent buffer inside the gesture.
    const src = this.ctx.createBufferSource();
    src.buffer = this.ctx.createBuffer(1, 1, 22050);
    src.connect(this.ctx.destination);
    src.start(0);
    // Same for speech synthesis: a silent utterance within the gesture.
    if ("speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(" ");
      u.volume = 0;
      speechSynthesis.speak(u);
    }
  }

  setEvents(events) {
    const byT = (a, b) => a.t - b.t;
    this.tones = events.filter((e) => e.type === "tone").sort(byT);
    this.speech = events.filter((e) => e.type === "speech").sort(byT);
    this.reset();
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

  cancelSpeech() { if ("speechSynthesis" in window) speechSynthesis.cancel(); }

  /** Stop all scheduled tones, forget scheduling state, cancel speech. */
  reset() {
    for (const n of this.nodes) {
      try { n.osc.stop(); } catch { /* already stopped */ }
      n.osc.disconnect(); n.gain.disconnect(); n.pan.disconnect();
    }
    this.nodes.clear();
    this.scheduled.clear();
    this.lastT = null;
    this.cancelSpeech();
  }

  tick() {
    const v = this.video;
    if (!this.ctx || v.paused || v.seeking || v.ended || v.readyState < 3) { this.lastT = null; return; }
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
      if (this.scheduled.has(i)) continue;
      this.scheduled.add(i);
      const when = now + (e.t + shift - cur) / rate;
      this.playTone(e, Math.max(when, now));
    }
  }

  playTone(e, when) {
    const ctx = this.ctx;
    const dur = Math.max(0.03, e.durationSeconds || 0.08);
    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = e.frequencyHz || 880;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0, when);
    gain.gain.linearRampToValueAtTime(PEAK_GAIN, when + EDGE_S);
    gain.gain.setValueAtTime(PEAK_GAIN, when + dur - EDGE_S);
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
  }

  /** Speak when the playhead *crosses* an event time during normal playback (not on seeks). */
  maybeSpeak(cur, rate, shift) {
    const prev = this.lastT;
    this.lastT = cur;
    if (prev === null) return;
    // A jump much larger than one tick of real time is a seek/stall, not playback: ignore.
    if (cur <= prev || cur - prev > 0.5 * rate + 0.2) return;
    const a = prev - shift, b = cur - shift;
    let hit = null;
    for (let i = firstAtOrAfter(this.speech, a); i < this.speech.length && this.speech[i].t <= b; i++) {
      const e = this.speech[i];
      if (e.t <= a) continue;
      // A final call wins the window; otherwise keep the latest phrase.
      if (!hit || e.role === "final" || hit.role !== "final") hit = e;
    }
    if (hit) this.speak(hit.text, rate, hit.role === "final");
  }

  /** Final calls pre-empt whatever is being spoken; other phrases queue behind it. */
  speak(text, rate, final = false) {
    if (!("speechSynthesis" in window)) return;
    if (final) speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = clamp(rate, 0.5, 2);
    u.volume = this.volume;
    speechSynthesis.speak(u);
  }
}
