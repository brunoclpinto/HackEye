// World map panel (v26.2 step 1 spike): the fused ego-centric bird's-eye snapshot of the frame at the playhead
// (GET /api/runs/{id}/worldmap/{i}.png, CONTRACTS 8.1), heading-up, user at column 100 / row 180, 0.10 m per cell.
// Cells are coloured through the same class LUT as the mask (js/classes.js MaskStyle), so colours, hidden classes and
// level edits follow the Classes panel. On top: the user marker, the +-0.6 m corridor to 10 steps, range rings every
// 5 steps, and the current frame's hazards as dots (movers highlighted, the role danger outlined).
import { $, ROLE_COLOR, lastAtOrBefore } from "./util.js";
import { api } from "./api.js";

const SIZE = 200, ORIGIN_COL = 100, ORIGIN_ROW = 180, CELL_M = 0.1;
const UNKNOWN = 255;
const CORRIDOR_HALF_M = 0.6, CORRIDOR_STEPS = 10, RING_EVERY = 5, DEFAULT_STEP_M = 0.7;
const MAX_FETCH_HZ = 6, CACHE = 24, STALE_S = 1.0;
const OPEN_KEY = "hackeye.lab.worldmap.open";

export class WorldMapPanel {
  /** `getStyle` = () => MaskStyle | null; `getFrames` = () => windowed hazards frames; `isPlaying` = () => bool. */
  constructor({ getStyle, getFrames, isPlaying }) {
    this.getStyle = getStyle;
    this.getFrames = getFrames;
    this.isPlaying = isPlaying;
    this.canvas = $("#wmCanvas");
    this.ctx = this.canvas.getContext("2d");
    this.det = $("#secWorldmap");
    this.reset();
    try { this.det.open = localStorage.getItem(OPEN_KEY) === "1"; } catch { /* storage blocked */ }
    this.det.addEventListener("toggle", () => {
      try { localStorage.setItem(OPEN_KEY, this.det.open ? "1" : "0"); } catch { /* storage blocked */ }
      if (this.det.open) this.update(this.lastT);
    });
    $("#wmBuild").addEventListener("click", () => this.build());
    this.paint();
  }

  reset() {
    this.token = (this.token ?? 0) + 1;
    this.run = null;
    this.meta = null;          // GET /api/runs/{id}/worldmap
    this.poseT = [];           // snapshot times (pose.json), ascending
    this.cache = new Map();    // snapshot index -> Uint8Array(200*200), 255 = unknown
    this.pending = new Map();  // snapshot index -> promise
    this.k = -1;               // snapshot index wanted for the playhead
    this.lastT = 0;
    this.sig = "";
    this.lastFetch = 0;
    this.timer = null;
    this.building = false;
    this.buildNote = "";
  }

  /** Switch run (or null). */
  async setRun(run) {
    this.reset();
    this.run = run;
    this.render();
    if (!run) { this.paint(); return; }
    await this.loadMeta();
  }

  async loadMeta() {
    const id = this.run?.id, token = this.token;
    if (!id) return;
    try {
      const meta = await api(`/api/runs/${id}/worldmap`, { quiet: true });
      if (token !== this.token) return;
      this.meta = meta;
      if (meta.exists) {
        const pose = await api(`/api/runs/${id}/worldmap/pose.json`, { quiet: true });
        if (token !== this.token) return;
        this.poseT = pose.t ?? [];
      }
    } catch { if (token === this.token) this.meta = { exists: false, error: true }; }
    if (token !== this.token) return;
    this.render();
    this.update(this.lastT);
  }

  async build() {
    const id = this.run?.id;
    if (!id || this.building) return;
    this.building = true; this.buildNote = ""; this.render();
    const token = this.token;
    try {
      const r = await api(`/api/runs/${id}/worldmap`, { method: "POST" });
      if (token !== this.token) return;
      this.buildNote = `Built in ${r.elapsedSeconds?.toFixed?.(1) ?? r.elapsedSeconds} s (${r.frames} frames, ${r.msMean?.toFixed?.(1) ?? r.msMean} ms/frame mean, p95 ${r.msP95?.toFixed?.(1) ?? r.msP95}).`;
    } catch (e) {
      if (token !== this.token) return;
      this.buildNote = `Build failed: ${e.message}`;
    }
    this.building = false;
    this.cache.clear();
    await this.loadMeta();
  }

  render() {
    const m = this.meta, has = !!this.run;
    const btn = $("#wmBuild");
    btn.hidden = !has || !m || m.exists;
    btn.disabled = this.building;
    btn.textContent = this.building ? "Building…" : "Build map";
    const parts = [];
    if (!has) parts.push("Open an analysed run to see its world map.");
    else if (!m) parts.push("Checking…");
    else if (m.exists) parts.push(`${m.frames} frames · ${m.msMean} ms/frame mean, p95 ${m.msP95} ms`);
    else parts.push(m.error ? "World map unavailable for this run." : "This run has no world map yet.");
    if (this.buildNote) parts.push(this.buildNote);
    $("#wmInfo").textContent = parts.join(" · ");
  }

  /** Playhead moved (called on every drawn video frame). */
  update(t) {
    if (Number.isFinite(t)) this.lastT = t;
    if (!this.run || !this.meta?.exists || !this.det.open || !this.poseT.length) { this.paintIfNeeded(); return; }
    const k = lastAtOrBefore(this.poseT, this.lastT, (x) => x);
    const inRange = k >= 0 && this.lastT - this.poseT[k] <= STALE_S + (this.poseT[k + 1] - this.poseT[k] || 0);
    this.k = inRange ? k : -1;
    if (this.k >= 0 && !this.cache.has(this.k)) this.request(this.k);
    this.paintIfNeeded();
  }

  /** Fetch snapshot k: immediately when paused / seeking, at most MAX_FETCH_HZ per second while playing (latest wins). */
  request(k) {
    if (this.pending.has(k)) return;
    const wait = this.isPlaying() ? this.lastFetch + 1000 / MAX_FETCH_HZ - performance.now() : 0;
    if (wait > 0) {
      if (!this.timer) this.timer = setTimeout(() => { this.timer = null; this.update(this.lastT); }, wait);
      return;
    }
    this.lastFetch = performance.now();
    const id = this.run.id, token = this.token;
    const p = this.load(id, k).then((grid) => {
      if (token !== this.token) return;
      this.cache.set(k, grid);
      while (this.cache.size > CACHE) this.cache.delete(this.cache.keys().next().value);
    }).catch(() => { /* quiet: the next update retries */ }).finally(() => {
      if (token !== this.token) return;
      this.pending.delete(k);
      this.update(this.lastT);
    });
    this.pending.set(k, p);
  }

  load(id, k) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const c = document.createElement("canvas"); c.width = SIZE; c.height = SIZE;
        const cx = c.getContext("2d", { willReadFrequently: true });
        cx.drawImage(img, 0, 0);
        const px = cx.getImageData(0, 0, SIZE, SIZE).data;
        const grid = new Uint8Array(SIZE * SIZE);
        for (let i = 0; i < grid.length; i++) grid[i] = px[i * 4 + 3] === 0 ? UNKNOWN : px[i * 4];   // A=0: unknown; else R = class id
        resolve(grid);
      };
      img.onerror = () => reject(new Error(`worldmap/${k}.png`));
      img.src = `/api/runs/${id}/worldmap/${k}.png`;
    });
  }

  currentHazardFrame() {
    const frames = this.getFrames();
    if (!frames?.length) return null;
    const i = lastAtOrBefore(frames, this.lastT);
    return i >= 0 && this.lastT - frames[i].t <= STALE_S ? frames[i] : null;
  }

  paintIfNeeded() {
    const f = this.currentHazardFrame();
    const grid = this.k >= 0 ? this.cache.get(this.k) : null;
    const sig = `${this.run?.id}|${this.k}|${grid ? 1 : 0}|${f?.index}|${this.getStyle()?.version}|${this.det.open}`;
    if (sig === this.sig) return;
    this.sig = sig;
    this.paint(grid, f);
  }

  paint(grid = null, frame = null) {
    const { canvas, ctx } = this;
    const px = Math.round(canvas.clientWidth * (window.devicePixelRatio || 1)) || canvas.width;
    if (canvas.width !== px) { canvas.width = px; canvas.height = px; }
    const W = canvas.width, s = W / SIZE;
    ctx.fillStyle = "#0b0d10";
    ctx.fillRect(0, 0, W, W);
    ctx.imageSmoothingEnabled = false;
    if (grid) {
      const style = this.getStyle();
      if (!this.off) { this.off = document.createElement("canvas"); this.off.width = SIZE; this.off.height = SIZE; }
      const octx = this.off.getContext("2d");
      const img = octx.createImageData(SIZE, SIZE), out = img.data, lut = style?.lut;
      for (let i = 0, j = 0; i < grid.length; i++, j += 4) {
        const c = grid[i];
        if (c === UNKNOWN) continue;
        if (lut) {
          if (lut[c * 4 + 3] === 0) continue;                // hidden / ignored class
          out[j] = lut[c * 4]; out[j + 1] = lut[c * 4 + 1]; out[j + 2] = lut[c * 4 + 2];
        } else { out[j] = out[j + 1] = out[j + 2] = 90 + (c * 37) % 150; }   // style not loaded: grey by id
        out[j + 3] = 255;
      }
      octx.putImageData(img, 0, 0);
      ctx.drawImage(this.off, 0, 0, W, W);
    } else {
      ctx.fillStyle = "#6b7280"; ctx.font = `${Math.round(W / 28)}px sans-serif`; ctx.textAlign = "center";
      ctx.fillText(this.run && this.meta?.exists ? (this.det.open ? "no snapshot at this time" : "") : "", W / 2, W / 2);
    }
    const ux = (ORIGIN_COL + 0.5) * s, uy = (ORIGIN_ROW + 0.5) * s;
    const step = frame?.ego?.stepLengthM > 0 ? frame.ego.stepLengthM : DEFAULT_STEP_M;
    const stepPx = step / CELL_M * s;
    const fs = Math.max(10, Math.round(W / 34));
    ctx.font = `${fs}px sans-serif`;
    // range rings every 5 steps
    ctx.lineWidth = 1; ctx.strokeStyle = "rgba(255,255,255,0.28)"; ctx.fillStyle = "rgba(255,255,255,0.7)"; ctx.textAlign = "center";
    for (let n = RING_EVERY; n * stepPx < uy + 1; n += RING_EVERY) {
      ctx.beginPath(); ctx.arc(ux, uy, n * stepPx, Math.PI * 1.02, Math.PI * 1.98); ctx.stroke();
      if (uy - n * stepPx > fs) ctx.fillText(`${n} st`, ux + fs * 1.6, uy - n * stepPx - 3);
    }
    // corridor +-0.6 m to 10 steps
    const hw = CORRIDOR_HALF_M / CELL_M * s, len = CORRIDOR_STEPS * stepPx;
    ctx.fillStyle = "rgba(255,45,45,0.12)"; ctx.fillRect(ux - hw, uy - len, 2 * hw, len);
    ctx.strokeStyle = "rgba(255,120,120,0.9)"; ctx.lineWidth = 1.5; ctx.strokeRect(ux - hw, uy - len, 2 * hw, len);
    // hazards: ahead = distanceM, right = lateralM
    if (frame) {
      const hs = (frame.hazards ?? []).filter((h) => Number.isFinite(h.distanceM) && Number.isFinite(h.lateralM));
      const drawOne = (h) => {
        const x = ux + (h.lateralM / CELL_M) * s, y = uy - (h.distanceM / CELL_M) * s;
        if (x < -4 || y < -4 || x > W + 4 || y > W + 4) return;
        const col = h.role === "danger" && h.urgency === "final" ? ROLE_COLOR.final : ROLE_COLOR[h.role] ?? ROLE_COLOR.none;
        const mover = h.group === "moving", r = Math.max(3, W / 70) * (mover ? 1.5 : 1);
        ctx.beginPath();
        if (mover) { ctx.moveTo(x, y - r * 1.2); ctx.lineTo(x + r * 1.2, y); ctx.lineTo(x, y + r * 1.2); ctx.lineTo(x - r * 1.2, y); ctx.closePath(); }
        else ctx.arc(x, y, r, 0, 2 * Math.PI);
        ctx.fillStyle = col; ctx.globalAlpha = h.role === "none" ? 0.6 : 1; ctx.fill(); ctx.globalAlpha = 1;
        ctx.lineWidth = mover ? 2 : 1; ctx.strokeStyle = mover ? "#ffffff" : "rgba(0,0,0,0.6)"; ctx.stroke();
        if (h.role === "danger") {   // danger: extra outline ring
          ctx.beginPath(); ctx.arc(x, y, r * 2, 0, 2 * Math.PI); ctx.lineWidth = 2; ctx.strokeStyle = col; ctx.stroke();
        }
      };
      for (const h of hs) if (h.role === "none") drawOne(h);
      for (const h of hs) if (h.role !== "none") drawOne(h);
    }
    // user marker
    ctx.fillStyle = "#ffffff"; ctx.strokeStyle = "#000000"; ctx.lineWidth = 1.5;
    const m = Math.max(5, W / 55);
    ctx.beginPath(); ctx.moveTo(ux, uy - m * 1.5); ctx.lineTo(ux + m, uy + m); ctx.lineTo(ux, uy + m * 0.4); ctx.lineTo(ux - m, uy + m); ctx.closePath();
    ctx.fill(); ctx.stroke();
    $("#wmStatus").textContent = this.k >= 0 && this.poseT.length ? `t ${this.poseT[this.k].toFixed(1)} s · frame ${this.k + 1}/${this.poseT.length} · step ${step.toFixed(2)} m` : "";
  }
}
