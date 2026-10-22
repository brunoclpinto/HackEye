// Timeline strip: speech ticks (role colours, filterable), beep episodes as bars (role colours; runs without
// `beeps` events fall back to the tone-density heat row), playhead; click/drag to seek.
import { eventColor, eventRole, URGENCY_RANK, fmtTime, clamp } from "./util.js";

export class Timeline {
  constructor(canvas, onSeek) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onSeek = onSeek;
    this.start = 0; this.end = 0;
    this.allSpeech = []; this.speech = []; this.tones = []; this.allBeeps = []; this.beeps = [];
    this.roles = null;       // Set of visible roles, null = all
    this.playhead = null;
    this.heat = null;
    this.down = false;

    new ResizeObserver(() => { this.heat = null; this.draw(); }).observe(canvas);
    canvas.addEventListener("pointerdown", (e) => { this.down = true; canvas.setPointerCapture(e.pointerId); this.seekFrom(e, true); });
    canvas.addEventListener("pointermove", (e) => { if (this.down) this.seekFrom(e, false); });
    canvas.addEventListener("pointerup", () => { this.down = false; });
    canvas.addEventListener("pointercancel", () => { this.down = false; });
  }

  set(run, events) {
    this.start = run ? run.request.start : 0;
    this.end = run ? run.request.end : 0;
    this.allSpeech = events.filter((e) => e.type === "speech");
    this.allBeeps = events.filter((e) => e.type === "beeps" && e.tEnd > e.t);
    this.applyRoles();
    this.tones = events.filter((e) => e.type === "tone");
    this.heat = null;
    this.draw();
  }

  applyRoles() {
    const vis = (list) => (this.roles ? list.filter((e) => this.roles.has(eventRole(e))) : list);
    this.speech = vis(this.allSpeech);
    this.beeps = vis(this.allBeeps);
  }

  setRoles(roles) { this.roles = roles; this.applyRoles(); this.draw(); }

  setPlayhead(t) {
    if (t === this.playhead) return;
    this.playhead = t;
    this.draw();
  }

  xOf(t, w) { return ((t - this.start) / (this.end - this.start)) * w; }
  tOf(x, w) { return this.start + (x / w) * (this.end - this.start); }

  seekFrom(e, snap) {
    if (this.end <= this.start) return;
    const r = this.canvas.getBoundingClientRect();
    const x = clamp(e.clientX - r.left, 0, r.width);
    let t = this.tOf(x, r.width);
    if (snap) { // click near a speech tick -> jump exactly to it
      let best = null, bd = 7;
      for (const s of this.speech) {
        const d = Math.abs(this.xOf(s.t, r.width) - x);
        if (d < bd) { bd = d; best = s; }
      }
      if (best) t = best.t;
    }
    this.onSeek(t);
  }

  computeHeat(w) {
    const bins = Math.max(1, Math.floor(w / 3));
    const counts = new Array(bins).fill(0);
    const span = this.end - this.start;
    for (const e of this.tones) {
      const b = Math.floor(((e.t - this.start) / span) * bins);
      if (b >= 0 && b < bins) counts[b] += 1 + 0.5 * (URGENCY_RANK[e.urgency] || 0);
    }
    this.heat = { counts, max: Math.max(1, ...counts) };
  }

  draw() {
    const c = this.canvas, ctx = this.ctx;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (!w || !h) return;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
      c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const css = getComputedStyle(document.documentElement);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = css.getPropertyValue("--panel2").trim() || "#222";
    ctx.fillRect(0, 0, w, h);
    if (this.end <= this.start) {
      ctx.fillStyle = css.getPropertyValue("--muted").trim() || "#888";
      ctx.font = "12px system-ui, sans-serif";
      ctx.fillText("Load a run to see its timeline", 8, h / 2 + 4);
      return;
    }
    const tickH = h - 32;
    // speech ticks
    ctx.lineWidth = 3;
    for (const s of this.speech) {
      const x = Math.round(this.xOf(s.t, w));
      ctx.strokeStyle = eventColor(s);
      ctx.beginPath(); ctx.moveTo(x, 4); ctx.lineTo(x, tickH); ctx.stroke();
    }
    const hy = tickH + 4;
    c.dataset.beeps = String(this.beeps.length);   // E2E hook: beep bars drawn
    if (this.allBeeps.length) {
      // beep episodes: one bar per episode, coloured by role (at least 2 px wide so short ones stay visible)
      for (const b of this.beeps) {
        const x0 = this.xOf(b.t, w), x1 = this.xOf(b.tEnd, w);
        ctx.fillStyle = eventColor(b);
        ctx.fillRect(x0, hy, Math.max(2, x1 - x0), 10);
      }
    } else {
      // older runs: tone-density heat row
      if (!this.heat) this.computeHeat(w);
      const { counts, max } = this.heat;
      const bw = w / counts.length;
      counts.forEach((n, i) => {
        if (!n) return;
        ctx.fillStyle = `rgba(255,140,26,${(0.15 + 0.85 * n / max).toFixed(3)})`;
        ctx.fillRect(i * bw, hy, Math.ceil(bw), 10);
      });
    }
    // labels
    ctx.fillStyle = css.getPropertyValue("--muted").trim() || "#888";
    ctx.font = "11px system-ui, sans-serif";
    ctx.textBaseline = "alphabetic";
    ctx.textAlign = "left"; ctx.fillText(fmtTime(this.start), 4, h - 4);
    ctx.textAlign = "right"; ctx.fillText(fmtTime(this.end), w - 4, h - 4);
    ctx.textAlign = "left";
    // playhead
    if (this.playhead !== null && this.playhead >= this.start && this.playhead <= this.end) {
      const x = this.xOf(this.playhead, w);
      ctx.strokeStyle = css.getPropertyValue("--fg").trim() || "#fff";
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
  }
}
