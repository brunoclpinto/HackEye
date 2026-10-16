// Canvas overlay: mask PNG, walking region, danger lane, horizon, role-coloured item boxes, ego HUD. Frame-synchronised to the <video>.
import { ROLE_COLOR, lastAtOrBefore } from "./util.js";

const PRELOAD = 20;          // frames each side of the playhead
const CACHE_MAX = 160;       // LRU size (> 2*PRELOAD+1)
const STALE_MASK_S = 0.5;    // reuse an earlier loaded mask only within this age

export class Overlay {
  constructor(video, canvas) {
    this.video = video;
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.layers = { mask: true, region: true, lane: true, horizon: true, hazards: true, showAll: false };
    this.hudEl = null;        // set by app: element receiving the HUD lines
    this.maskOpacity = 0.45;
    this.run = null;
    this.frames = [];
    this.cache = new Map();   // key -> {img, ready}; Map order = LRU order
    this.mt = null;           // last mediaTime reported by requestVideoFrameCallback
    this.lastK = -2;
    this.cw = 0; this.ch = 0;
    this.onFrame = null;      // callback(mediaTime) after each draw

    const v = video;
    // Seeking invalidates the rVFC time until the new frame is presented.
    v.addEventListener("seeking", () => { this.mt = null; });
    for (const ev of ["loadedmetadata", "resize", "seeked", "pause", "emptied"]) {
      v.addEventListener(ev, () => { if (ev === "emptied") this.mt = null; this.layout(); this.redraw(); });
    }
    if ("requestVideoFrameCallback" in v) {
      const loop = (_now, meta) => {
        this.mt = meta.mediaTime; // exact presentation time of the frame on screen
        this.redraw();
        v.requestVideoFrameCallback(loop);
      };
      v.requestVideoFrameCallback(loop);
    } else {
      // Fallback: rAF while playing, plus timeupdate / seeked when not.
      v.addEventListener("timeupdate", () => this.redraw());
      const raf = () => { if (!v.paused) this.redraw(); requestAnimationFrame(raf); };
      requestAnimationFrame(raf);
    }
    new ResizeObserver(() => { this.layout(); this.redraw(); }).observe(video);
  }

  setRun(run, hazards) {
    this.run = run;
    this.frames = hazards?.frames ?? [];
    this.fixedStep = hazards?.settings?.stepLengthM ?? null; // user-set step length, if any
    this.cache.clear();
    this.lastK = -2;
    this.redraw();
  }

  /** Size/position the canvas over the displayed video *content* (object-fit: contain letterboxing). */
  layout() {
    const v = this.video;
    const ew = v.clientWidth, eh = v.clientHeight;
    const vw = v.videoWidth, vh = v.videoHeight;
    if (!ew || !eh || !vw || !vh) { this.cw = this.ch = 0; this.canvas.style.display = "none"; return; }
    const scale = Math.min(ew / vw, eh / vh);
    const cw = vw * scale, ch = vh * scale;
    const left = v.offsetLeft + (ew - cw) / 2, top = v.offsetTop + (eh - ch) / 2;
    const dpr = window.devicePixelRatio || 1;
    Object.assign(this.canvas.style, {
      display: "block", left: `${left}px`, top: `${top}px`, width: `${cw}px`, height: `${ch}px`,
    });
    const pw = Math.round(cw * dpr), ph = Math.round(ch * dpr);
    if (this.canvas.width !== pw || this.canvas.height !== ph) {
      this.canvas.width = pw; this.canvas.height = ph;
    }
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0); // draw in CSS px
    this.cw = cw; this.ch = ch;
  }

  currentTime() { return this.mt ?? this.video.currentTime; }

  redraw() {
    const t = this.currentTime();
    this.draw(t);
    if (this.onFrame) this.onFrame(t);
  }

  draw(t) {
    const { ctx, cw, ch } = this;
    if (!cw) return;
    ctx.clearRect(0, 0, cw, ch);
    const run = this.run;
    if (!run || !this.frames.length) { this.updateHud(null); return; }
    // Only inside the analysed range, and only once the first analysed frame is reached.
    if (t < run.request.start || t > run.request.end) { this.updateHud(null); return; }
    const k = lastAtOrBefore(this.frames, t);
    if (k < 0) { this.updateHud(null); return; }
    if (k !== this.lastK) { this.lastK = k; this.preload(k); }
    const f = this.frames[k];

    if (this.layers.mask) this.drawMask(k, t);
    if (this.layers.lane && f.lane?.length) this.drawLane(f.lane);
    if (this.layers.region && f.region?.rows?.length) this.drawRegion(f.region);
    if (this.layers.horizon && f.horizonY != null) this.drawHorizon(f.horizonY, !!f.horizonEstimated);
    if (this.layers.hazards) {
      // Dim items first so danger / final end up on top.
      const hs = f.hazards ?? [];
      for (const h of hs) if (h.role === "none") this.drawHazard(h);
      for (const h of hs) if (h.role !== "none") this.drawHazard(h);
    }
    this.updateHud(f);
  }

  // ---- HUD ----------------------------------------------------------------
  updateHud(f) {
    const el = this.hudEl;
    if (!el) return;
    let lines = null;
    if (f) {
      const e = f.ego;
      if (!e) lines = ["no ego data (re-analyse)"];
      else {
        const est = e.estimated ?? {};
        const num = (v, d) => (v == null || !Number.isFinite(v) ? null : v.toFixed(d));
        const mark = (v, on, off) => (v == null ? "" : on ? ` (${on})` : off ? ` (${off})` : "");
        const sp = num(e.speedMps, 2);
        const cad = e.cadenceHz == null ? null : (e.cadenceHz * 60).toFixed(0);
        const sl = num(e.stepLengthM, 2);
        const hd = num(e.headingDeg, 1);
        lines = [
          `speed  ${sp ? `${sp} m/s · ${(e.speedMps * 3.6).toFixed(1)} km/h` : "—"}${mark(e.speedMps, est.speed ? "est" : "")}`,
          `cadence  ${cad ? `${cad} steps/min` : "—"}${mark(e.cadenceHz, est.cadence ? "est" : "")}`,
          `step  ${sl ? `${sl} m` : "—"}${mark(e.stepLengthM, est.stepLength ? "est" : this.fixedStep != null ? "set" : "default")}`,
          `heading  ${hd ? `${hd > 0 ? "+" : ""}${hd}°` : "—"}`,
        ];
      }
    }
    const text = lines ? lines.join("\n") : "";
    if (el.dataset.txt === text) return;
    el.dataset.txt = text;
    el.textContent = text;
    el.hidden = !text;
  }

  // ---- mask images ------------------------------------------------------
  key(k) { return `${this.run.id}:${this.frames[k].index}`; }

  ensure(k) {
    if (k < 0 || k >= this.frames.length) return;
    const key = this.key(k);
    const hit = this.cache.get(key);
    if (hit) { this.cache.delete(key); this.cache.set(key, hit); return; } // refresh LRU
    const entry = { img: new Image(), ready: false };
    const runId = this.run.id;
    entry.img.onload = () => {
      entry.ready = true;
      // Redraw if this mask is (near) the one currently needed.
      if (this.run && this.run.id === runId && Math.abs(k - this.lastK) <= 12) this.redraw();
    };
    entry.img.src = `/api/runs/${runId}/frames/${this.frames[k].index}/mask.png`;
    this.cache.set(key, entry);
    while (this.cache.size > CACHE_MAX) this.cache.delete(this.cache.keys().next().value);
  }

  preload(k) {
    // Nearest first so the frame about to be shown wins the connection queue.
    this.ensure(k);
    for (let d = 1; d <= PRELOAD; d++) { this.ensure(k + d); this.ensure(k - d); }
  }

  drawMask(k, t) {
    // Exact frame if loaded; otherwise the nearest earlier loaded one if < 0.5 s old; else nothing.
    for (let j = k; j >= 0 && t - this.frames[j].t <= STALE_MASK_S; j--) {
      const e = this.cache.get(this.key(j));
      if (e && e.ready) {
        const { ctx } = this;
        ctx.save();
        ctx.globalAlpha = this.maskOpacity;
        ctx.imageSmoothingEnabled = false; // show the 240-px grid honestly
        ctx.drawImage(e.img, 0, 0, this.cw, this.ch);
        ctx.restore();
        return;
      }
    }
  }

  // ---- vector layers ----------------------------------------------------
  drawLane(pts) {
    const { ctx, cw, ch } = this;
    ctx.save();
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x * cw, y * ch) : ctx.moveTo(x * cw, y * ch)));
    ctx.closePath();
    ctx.fillStyle = "rgba(255,45,45,0.22)";
    ctx.fill();
    ctx.restore();
  }

  drawRegion(reg) {
    const { ctx, cw, ch } = this;
    const rows = reg.rows; // [y, left, right], bottom -> top
    ctx.save();
    ctx.beginPath();
    rows.forEach(([y, l], i) => (i ? ctx.lineTo(l * cw, y * ch) : ctx.moveTo(l * cw, y * ch)));
    for (let i = rows.length - 1; i >= 0; i--) ctx.lineTo(rows[i][2] * cw, rows[i][0] * ch);
    ctx.closePath();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "rgba(255,255,255,0.9)";
    ctx.stroke();
    if (reg.label) {
      const [ty, tl, tr] = rows[rows.length - 1];
      ctx.font = "600 12px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      const x = ((tl + tr) / 2) * cw, y = Math.max(14, ty * ch - 3);
      ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,0.7)"; ctx.strokeText(reg.label, x, y);
      ctx.fillStyle = "#fff"; ctx.fillText(reg.label, x, y);
    }
    ctx.restore();
  }

  drawHorizon(y, estimated) {
    const { ctx, cw, ch } = this;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(0, y * ch); ctx.lineTo(cw, y * ch);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "rgba(250,204,21,0.85)";
    ctx.setLineDash(estimated ? [] : [8, 6]); // solid = estimated this frame, dashed = preset fallback
    ctx.stroke();
    ctx.restore();
  }

  drawHazard(h) {
    const { ctx, cw, ch } = this;
    const legacy = h.role === undefined; // v26.1.0 run
    const role = h.role ?? "danger";
    const col = legacy ? (h.urgency === "imminent" ? ROLE_COLOR.final : ROLE_COLOR.danger)
      : role === "danger" && h.urgency === "final" ? ROLE_COLOR.final : ROLE_COLOR[role] ?? ROLE_COLOR.none;
    const dim = role === "none";
    const [x0, y0, x1, y1] = h.bbox;
    const X = x0 * cw, Y = y0 * ch, W = (x1 - x0) * cw, H = (y1 - y0) * ch;
    ctx.save();
    ctx.lineWidth = dim ? 1 : 3;
    ctx.strokeStyle = col;
    ctx.strokeRect(X, Y, W, H);

    if (!dim || this.layers.showAll) {
      let text = `${h.label} · ${h.clock}`;
      if (legacy) text += ` · ${Number(h.proximity).toFixed(2)}`;
      else if (role !== "context" && h.stepsTo != null) text += ` · ${Math.round(h.stepsTo)}st`;
      ctx.font = `${dim ? 500 : 600} ${dim ? 11 : 13}px system-ui, sans-serif`;
      ctx.textBaseline = "middle";
      const pad = 4, th = dim ? 15 : 18, tw = ctx.measureText(text).width + pad * 2;
      const lx = Math.min(Math.max(0, X - 1.5), Math.max(0, cw - tw));
      let ly = Y - th - 1.5;
      if (ly < 0) ly = Y + 1.5; // no room above: put the label inside the box
      ctx.fillStyle = col;
      ctx.fillRect(lx, ly, tw, th);
      ctx.fillStyle = "#111";
      ctx.fillText(text, lx + pad, ly + th / 2 + 0.5);
    }

    if (!dim) { // contact point: where the obstacle meets the ground
      ctx.beginPath();
      ctx.arc(((x0 + x1) / 2) * cw, h.contactY * ch, 5, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "#000";
      ctx.stroke();
    }
    ctx.restore();
  }
}
