// Windowed hazards (CONTRACTS 12.1). A full-length run's hazards.json is ~120 MB, so the page
// never loads it: it holds the analysed frames within +-HALF_S of the playhead, prefetches the
// next stretch when the playhead gets within AHEAD_S of the window's end, and refetches on a
// seek outside the window. `frames` is always sorted by t; `onChange(frames, head)` fires
// whenever it is replaced so the overlay can pick the new array up.
import { api } from "./api.js";

const HALF_S = 90;
const AHEAD_S = 30;

export class HazardWindow {
  constructor(onChange) {
    this.onChange = onChange;
    this.reset();
  }

  reset() {
    this.runId = null;
    this.run = null;
    this.frames = [];
    this.head = null;          // {version, settings, gridW, gridH, egoAvailable} of the latest response
    this.from = 0; this.to = -1; // time range the frames cover (to < from = empty)
    this.token = 0;            // invalidates in-flight fetches (run change / re-run)
    this.inflight = null;      // {from, to, merge, promise}
    this.retryAt = 0;          // back off after a failed fetch
    this.onChange?.([], null);
  }

  /** Switch to a run (or null). Call update(t) afterwards. */
  setRun(run) {
    this.reset();
    this.run = run;
    this.runId = run?.id ?? null;
  }

  /** Drop the loaded frames (e.g. after a collision re-run rewrote hazards.json). */
  invalidate() {
    const run = this.run;
    this.setRun(run);
  }

  _covers(t) { return t >= this.from && t <= this.to; }

  /** Make sure the window covers the playhead; prefetch ahead during playback. Returns a promise (or null). */
  update(t) {
    if (!this.runId || !Number.isFinite(t)) return null;
    const { start, end } = this.run.request;
    if (t < start - 1 || t > end + 1 || performance.now() < this.retryAt) return null;
    if (!this._covers(t)) {
      const f = this.inflight;
      if (f && !f.merge && t >= f.from && t <= f.to) return f.promise; // already on its way
      return this._fetch(Math.max(0, t - HALF_S), t + HALF_S, false);
    }
    if (this.to < end && this.to - t < AHEAD_S && !(this.inflight && this.inflight.from >= this.to - 1e-6)) {
      return this._fetch(this.to, this.to + 2 * HALF_S, true, t);
    }
    return this.inflight?.promise ?? null;
  }

  _fetch(from, to, merge, playhead) {
    if (this.inflight && this.inflight.from === from && this.inflight.to === to) return this.inflight.promise;
    const token = this.token, runId = this.runId;
    const url = `/api/runs/${runId}/hazards?from=${from.toFixed(3)}&to=${to.toFixed(3)}`;
    const entry = { from, to, merge, promise: null };
    entry.promise = api(url, { quiet: true }).then((doc) => {
      if (token !== this.token || runId !== this.runId || this.inflight !== entry) return; // run changed / superseded by a newer fetch
      this.head = { version: doc.version, settings: doc.settings, gridW: doc.gridW, gridH: doc.gridH, egoAvailable: doc.egoAvailable };
      if (merge && this._covers(from - 1e-6)) {
        // Prefetch: append the next stretch, drop frames far behind the playhead.
        const keepFrom = Math.max(this.from, (playhead ?? from) - HALF_S);
        const kept = this.frames.filter((f) => f.t >= keepFrom);
        const lastT = kept.length ? kept[kept.length - 1].t : -Infinity;
        this.frames = kept.concat(doc.frames.filter((f) => f.t > lastT));
        this.from = keepFrom; this.to = doc.to;
      } else {
        this.frames = doc.frames; this.from = doc.from; this.to = doc.to;
      }
      this.onChange?.(this.frames, this.head);
    }).catch(() => { this.retryAt = performance.now() + 3000; }) // quiet; update() retries after the back-off
      .finally(() => { if (this.inflight === entry) this.inflight = null; });
    this.inflight = entry;
    return entry.promise;
  }

  /** The analysed frame with the largest t <= s from the server (auto-fill). Resolves to the frame or null. */
  async frameAt(t) {
    if (!this.runId) return null;
    try { return (await api(`/api/runs/${this.runId}/frame?t=${t.toFixed(3)}`, { quiet: true })).frame ?? null; }
    catch { return null; }
  }
}
