// ETA label for an analysis run (CONTRACTS, Analyse panel). Pure functions + a per-run tracker; no DOM, no server support needed.
export const WINDOW_S = 60;        // sliding window of (time, progress) samples
export const MIN_SPAN_S = 10;      // need this much watched time ...
export const MIN_DP = 0.02;        // ... and this much progress before an ETA is shown
export const STALL_S = 60;         // no progress change for this long while running: "stalled?"
export const REFRESH_S = 5;        // the shown ETA is re-based on the estimate at most this often (or on a >= 10 % change)

/** < 60 s -> "about 40 s", < 1 h -> "about 3 min", else "about 1 h 05 min". */
export function formatEta(sec) {
  if (!Number.isFinite(sec)) return "";
  sec = Math.max(0, sec);
  if (sec < 60) return `about ${Math.max(5, Math.round(sec / 5) * 5)} s`;
  const min = Math.round(sec / 60);
  if (min < 60) return `about ${min} min`;
  const h = Math.floor(min / 60);
  return `about ${h} h ${String(min % 60).padStart(2, "0")} min`;
}

export class EtaTracker {
  /** @param {number} createdMs run start (ms epoch) used for the average-rate fallback when the page was opened mid-run */
  constructor(createdMs = NaN) {
    this.createdMs = createdMs;
    this.samples = [];       // {t (ms), p}
    this.first = null;       // first sample seen
    this.lastChangeT = null; // when progress last changed
    this.ema = null;         // smoothed ETA (s)
    this.shownEta = null;    // ETA (s) at shownAt
    this.shownAt = 0;
  }

  /** Remaining seconds from the rate, or null when there is not enough data yet. */
  _rawEta(now, p) {
    const s = this.samples;
    const a = s[0], b = s[s.length - 1];
    const span = (b.t - a.t) / 1000, dp = b.p - a.p;
    let rate = null;
    if (span >= MIN_SPAN_S && dp >= MIN_DP) rate = dp / span;
    else if (this.first.p >= MIN_DP && Number.isFinite(this.createdMs) && (now - this.createdMs) / 1000 >= MIN_SPAN_S && p >= MIN_DP) {
      rate = p / ((now - this.createdMs) / 1000);   // opened mid-run: average since the run was created
    }
    return rate && rate > 0 ? (1 - p) / rate : null;
  }

  /** Label for a run poll result `run` ({status, progress}) at time `now` (ms). */
  label(run, now = Date.now()) {
    const p = Math.min(1, Math.max(0, run.progress || 0));
    const pct = Math.round(p * 100);
    if (run.status === "queued") return "queued";
    const text = `${run.status} ${pct}%`;
    const last = this.samples[this.samples.length - 1];
    if (!this.first) { this.first = { t: now, p }; this.lastChangeT = now; }
    if (last && p !== last.p) this.lastChangeT = now;
    this.samples.push({ t: now, p });
    while (this.samples.length > 2 && now - this.samples[0].t > WINDOW_S * 1000) this.samples.shift();
    if (now - this.lastChangeT > STALL_S * 1000 && now - this.first.t > STALL_S * 1000) return `${text} · stalled?`;
    const raw = this._rawEta(now, p);
    if (raw === null) return `${text} · estimating…`;
    this.ema = this.ema === null ? raw : this.ema + 0.3 * (raw - this.ema);
    const countdown = this.shownEta === null ? null : this.shownEta - (now - this.shownAt) / 1000;
    if (countdown === null || countdown <= 0 || now - this.shownAt >= REFRESH_S * 1000
        || Math.abs(this.ema - countdown) / countdown >= 0.1) {
      // never creep upwards by a little: keep counting down unless the estimate grew by >= 10 %
      const keep = countdown > 0 && this.ema > countdown && this.ema < countdown * 1.1;
      this.shownEta = keep ? countdown : this.ema;
      this.shownAt = now;
    }
    const left = this.shownEta - (now - this.shownAt) / 1000;
    return `${text} · ${formatEta(left)} left`;
  }
}

/** Parse a run's start timestamp (run.json startedAt if present, else createdAt) to ms; NaN when absent. */
export function runStartMs(run) {
  return Date.parse(run.startedAt || run.createdAt || "");
}
