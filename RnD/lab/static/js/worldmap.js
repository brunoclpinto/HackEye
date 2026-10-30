// World map panel (v26.2 step 1 spike): the fused ego-centric bird's-eye snapshot of the frame at the playhead
// (GET /api/runs/{id}/worldmap/{i}.png, CONTRACTS 8.1), heading-up, forward only (v26.2.4): user at column 100 / row 200 (the bottom
// edge), 0.10 m per cell, 20 m ahead. A click selects a cell (marker kept across frames); the box under the map reads it out.
// Cells are coloured through the same class LUT as the mask (js/classes.js MaskStyle), so colours, hidden classes and
// level edits follow the Classes panel. On top: the user marker, the +-0.6 m corridor to 10 steps, range rings every
// 5 steps, and the current frame's hazards as dots (movers highlighted, the role danger outlined).
import { $, ROLE_COLOR, lastAtOrBefore } from "./util.js";
import { api } from "./api.js";

const SIZE = 200, ORIGIN_COL = 100, ORIGIN_ROW = 200, CELL_M = 0.1;
const UNKNOWN = 255;
const ITEM_NEAR_M = 0.3;     // an item whose position lies within this of the cell is listed with it
const CORRIDOR_HALF_M = 0.6, CORRIDOR_STEPS = 10, RING_EVERY = 5, DEFAULT_STEP_M = 0.7;
const HIT_MIN_CSS_PX = 8;    // v26.2.6: a click hits an item marker within its drawn radius, at least this many CSS px
const MAX_FETCH_HZ = 6, CACHE = 24, STALE_S = 1.0;

/** Quarter-hour clock index / spoken text, same rules as collision.py clock_quarter / clock_text (bearing 0 = 12, + = right). */
function clockQuarter(bearing) {
  const v = bearing / 7.5, q = Math.floor(Math.abs(v) + 0.5) * (v < 0 ? -1 : 1);
  return Math.max(-12, Math.min(12, q));
}
function clockText(q) {
  const m = (720 + 15 * q) % 720, hour = Math.floor(m / 60) || 12, min = m % 60;
  return min === 0 ? `${hour}` : `${hour}:${String(min).padStart(2, "0")}`;
}

/** v26.2.6: massive structures get no marker (their cells and wall lines show them); a click on their cells still reads them. */
export function isMassive(h) { return /\b(building|bridge|tunnel)\b/i.test(h?.className ?? ""); }

/** The text naming one item: class, role, track, distance source and marks. */
export function itemLine(h) {
  const tags = [];
  if (h.insideSolid) tags.push(h.solidCorrected ? "inside solid (snapped)" : "inside solid");
  if (h.coasting) tags.push("coasting");
  if (h.ghost) tags.push("ghost");
  return `${h.className ?? h.label ?? "item"} · role ${h.role ?? "none"} · track ${h.trackId ?? "?"} · distance source ${h.distanceSource ?? h.source ?? "?"}` +
    (tags.length ? ` · ${tags.join(", ")}` : "");
}

/** The marker as drawn, in canvas px (W = canvas width): centre, drawn radius and the radius a click counts as a hit. */
export function markerOf(h, W, minHitPx = 0) {
  const s = W / SIZE, mover = h.group === "moving";
  const r = Math.max(3, W / 70) * (mover ? 1.5 : 1);
  const drawn = h.role === "danger" ? r * 2 : mover ? r * 1.2 : r;      // the danger ring / diamond tip is part of the marker
  return { x: (ORIGIN_COL + 0.5) * s + (h.lateralM / CELL_M) * s, y: (ORIGIN_ROW + 0.5) * s - (h.distanceM / CELL_M) * s, r, drawn, hit: Math.max(drawn, minHitPx) };
}

/** Hazards items of a frame whose position (map / snapped / coasting position, the raw depth position, or the image measurement)
 *  lies within ITEM_NEAR_M of the cell (`ahead`, `right` in metres). Returns one description line per item. */
export function itemsNear(frame, ahead, right) {
  const out = [];
  for (const h of frame?.hazards ?? []) {
    const pts = [];
    if (Number.isFinite(h.distanceM) && Number.isFinite(h.lateralM)) pts.push([h.distanceM, h.lateralM]);
    if (h.solidCorrected && Number.isFinite(h.rawDistanceM) && h.distanceM > 0) pts.push([h.rawDistanceM, h.lateralM * h.rawDistanceM / h.distanceM]);
    if (Number.isFinite(h.imageDistanceM) && Number.isFinite(h.imageLateralM)) pts.push([h.imageDistanceM, h.imageLateralM]);
    if (!pts.some(([f, r]) => Math.hypot(f - ahead, r - right) <= ITEM_NEAR_M)) continue;
    out.push(itemLine(h));
  }
  return out;
}

export class WorldMapPanel {
  /** `getStyle` = () => MaskStyle | null; `getFrames` = () => windowed hazards frames; `isPlaying` = () => bool. */
  constructor({ getStyle, getFrames, isPlaying }) {
    this.getStyle = getStyle;
    this.getFrames = getFrames;
    this.isPlaying = isPlaying;
    this.canvas = $("#wmCanvas");
    this.ctx = this.canvas.getContext("2d");
    this.reset();
    // The canvas follows the layout (CSS size x devicePixelRatio): repaint when its box changes.
    new ResizeObserver(() => { this.sig = ""; this.paintIfNeeded(); }).observe(this.canvas);
    this.canvas.addEventListener("click", (e) => this.select(e));
    this.paint();
  }

  /** The drawn item markers of a frame (massive structures have none). */
  markers(frame) {
    return (frame?.hazards ?? []).filter((h) => Number.isFinite(h.distanceM) && Number.isFinite(h.lateralM) && !isMassive(h));
  }

  /** Click / tap: an item marker under the pointer wins (selection snaps to its cell); else select the map cell under the pointer.
   *  The marker stays until another click. */
  select(e) {
    const r = this.canvas.getBoundingClientRect();
    if (!r.width) return;
    const px = this.canvas.width / r.width;                       // canvas px per CSS px (devicePixelRatio and layout scale)
    const cx = (e.clientX - r.left) * px, cy = (e.clientY - r.top) * px;
    let best = null, bestD = Infinity;
    for (const h of this.markers(this.currentHazardFrame())) {
      const m = markerOf(h, this.canvas.width, HIT_MIN_CSS_PX * px), d = Math.hypot(m.x - cx, m.y - cy);
      if (d <= m.hit && d < bestD) { best = { h, m }; bestD = d; }
    }
    const at = best ? [best.m.x, best.m.y] : [cx, cy], cell = this.canvas.width / SIZE;
    const col = Math.min(SIZE - 1, Math.max(0, Math.floor(at[0] / cell)));
    const row = Math.min(SIZE - 1, Math.max(0, Math.floor(at[1] / cell)));
    this.sel = { col, row };
    this.selItem = best ? { trackId: best.h.trackId ?? null, className: best.h.className, h: best.h } : null;
    this.cellData = null; this.cellKey = "";
    this.sig = ""; this.refreshCell(); this.paintIfNeeded();
  }

  /** Fetch the selected cell's layers for the current snapshot (GET /worldmap/cell); latest wins. */
  refreshCell() {
    const sel = this.sel;
    if (!sel || !this.run || !this.meta?.exists) { this.renderCell(); return; }
    if (this.k < 0) { this.cellData = null; this.cellKey = ""; this.renderCell(); return; }
    const key = `${this.run.id}|${this.k}|${sel.col}|${sel.row}`;
    if (key === this.cellKey) { this.renderCell(); return; }
    this.cellKey = key;
    const token = this.token;
    api(`/api/runs/${this.run.id}/worldmap/cell?i=${this.k}&col=${sel.col}&row=${sel.row}`, { quiet: true })
      .then((d) => { if (token === this.token && key === this.cellKey) { this.cellData = d; this.renderCell(); } })
      .catch(() => { if (token === this.token && key === this.cellKey) { this.cellData = null; this.renderCell(); } });
  }

  /** The text of the box under the map: the selected cell at the current frame. A never-observed cell (no surface, no object, no item) reads only "unmapped". */
  cellText() {
    if (!this.sel) return "Click the map to read a cell.";
    const { col, row } = this.sel;
    const ahead = (ORIGIN_ROW - row) * CELL_M, right = (col - ORIGIN_COL) * CELL_M;
    const d = this.cellData;
    if (!d) return this.k >= 0 && this.meta?.exists && this.cellKey ? "…" : "no snapshot at this time";
    const frame = this.currentHazardFrame();
    const items = itemsNear(frame, ahead, right);
    // v26.2.6: the item named on the Object line: the clicked one (followed by track id across frames), else the nearest drawn marker covering the cell
    let hit = null;
    if (this.selItem) {
      hit = this.selItem.trackId !== null
        ? (frame?.hazards ?? []).find((h) => h.trackId === this.selItem.trackId && h.className === this.selItem.className && !isMassive(h))
        : (frame?.hazards ?? []).find((h) => h === this.selItem.h);
    }
    const W = this.canvas.width, s = W / SIZE, cx = (col + 0.5) * s, cy = (row + 0.5) * s;
    if (hit) {      // a followed item that moved away from the selected cell is no longer "at" it
      const m = markerOf(hit, W, HIT_MIN_CSS_PX * W / (this.canvas.clientWidth || W));
      if (!Number.isFinite(m.x) || Math.hypot(m.x - cx, m.y - cy) > m.hit + s) hit = null;
    }
    if (!hit) {
      let bestD = Infinity;
      for (const h of this.markers(frame)) {
        const m = markerOf(h, W), d = Math.hypot(m.x - cx, m.y - cy);
        if (d <= m.drawn && d < bestD) { hit = h; bestD = d; }
      }
    }
    const style = this.getStyle();
    const name = (id) => style?.info?.classes?.find?.((c) => c.id === id)?.name ?? `class ${id}`;
    const level = (id) => {
      const lv = style?.levelOf?.get(id);
      const lab = style?.info?.levels?.find?.((l) => l.level === lv)?.label;
      return lv === undefined ? "" : ` (level ${lv}${lab ? " " + lab : ""})`;
    };
    const surface = d.layers ? d.surface : d.combined;      // maps built before v26.2.4 have one class per cell
    const obj = d.layers ? d.object : null;
    if (surface === null && obj === null && !items.length && !hit) return "unmapped";
    const dist = Math.hypot(ahead, right), bearing = Math.atan2(right, ahead) * 180 / Math.PI;
    const step = this.stepM || DEFAULT_STEP_M;
    const lines = [`${clockText(clockQuarter(bearing))} · ${(dist / step).toFixed(1)} steps · ${ahead.toFixed(1)} m ahead · ${Math.abs(right).toFixed(1)} m ${right < 0 ? "left" : "right"} · cell col ${col} row ${row}`,
      `Region: ${surface === null ? "none observed" : name(surface) + level(surface)}`,
      `Object: ${hit ? itemLine(hit) + (obj === null ? "" : ` · map: ${name(obj)}${level(obj)}`) : obj === null ? "none" : name(obj) + level(obj)}`];
    for (const it of items) lines.push(`Item: ${it}`);
    if (!items.length) lines.push("Item: none");
    return lines.join("\n");
  }

  renderCell() {
    const txt = this.cellText(), el = $("#wmCell");
    if (el.textContent !== txt) el.textContent = txt;
  }

  reset() {
    this.token = (this.token ?? 0) + 1;
    this.run = null;
    this.meta = null;          // GET /api/runs/{id}/worldmap
    this.poseT = [];           // snapshot times (pose.json), ascending
    this.cache = new Map();    // snapshot index -> Uint8Array(200*200), 255 = unknown
    this.pending = new Map();  // snapshot index -> promise
    this.k = -1;               // snapshot index wanted for the playhead
    this.sel = null;           // selected cell {col, row}: kept across frames until another click
    this.cellData = null;      // GET /worldmap/cell of the selected cell at snapshot k
    this.cellKey = "";
    this.lastT = 0;
    this.sig = "";
    this.lastFetch = 0;
    this.timer = null;
    this.selItem = null;       // v26.2.6: the item marker the selection was snapped to (followed by track id)
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

  render() {
    const m = this.meta, has = !!this.run;
    const parts = [];
    if (!has) parts.push("Open an analysed run to see its world map.");
    else if (!m) parts.push("Checking…");
    else if (m.exists) parts.push(`${m.frames} frames · ${m.msMean} ms/frame mean, p95 ${m.msP95} ms`);
    else parts.push(m.error ? "World map unavailable for this run." : "This run has no world map.");
    $("#wmInfo").textContent = parts.join(" · ");
  }

  /** Playhead moved (called on every drawn video frame). */
  update(t) {
    if (Number.isFinite(t)) this.lastT = t;
    if (!this.run || !this.meta?.exists || !this.poseT.length) { this.k = -1; this.refreshCell(); this.paintIfNeeded(); return; }
    const k = lastAtOrBefore(this.poseT, this.lastT, (x) => x);
    const inRange = k >= 0 && this.lastT - this.poseT[k] <= STALE_S + (this.poseT[k + 1] - this.poseT[k] || 0);
    this.k = inRange ? k : -1;
    if (this.k >= 0 && !this.cache.has(this.k)) this.request(this.k);
    this.refreshCell();
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
    const sig = `${this.run?.id}|${this.k}|${grid ? 1 : 0}|${f?.index}|${this.getStyle()?.version}`;
    if (sig === this.sig) return;
    this.sig = sig;
    this.paint(grid, f);
    this.renderCell();
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
      ctx.fillText(this.run && this.meta?.exists ? "no snapshot at this time" : "", W / 2, W / 2);
    }
    const ux = (ORIGIN_COL + 0.5) * s, uy = (ORIGIN_ROW + 0.5) * s;
    const step = frame?.ego?.stepLengthM > 0 ? frame.ego.stepLengthM : DEFAULT_STEP_M;
    const stepPx = step / CELL_M * s;
    const fs = Math.max(10, Math.round(W / 34));
    ctx.font = `${fs}px sans-serif`;
    this.stepM = step;
    // clock spokes (hours full length to the canvas edge, quarter hours to 10 steps), faint so the map colours stay readable
    const dirs = (b) => [Math.sin(b * Math.PI / 180), -Math.cos(b * Math.PI / 180)];
    const edge = (b) => {
      const [dx, dy] = dirs(b);
      let t = Infinity;
      if (dx > 1e-6) t = Math.min(t, (W - ux) / dx); else if (dx < -1e-6) t = Math.min(t, ux / -dx);
      if (dy < -1e-6) t = Math.min(t, uy / -dy);
      return t;
    };
    ctx.lineWidth = Math.max(1, W / 400);
    for (let q = -12; q <= 12; q++) {
      const hour = q % 4 === 0, b = q * 7.5, [dx, dy] = dirs(b);
      const len = hour ? edge(b) : Math.min(edge(b), CORRIDOR_STEPS * stepPx);
      ctx.strokeStyle = hour ? "rgba(255,255,255,0.20)" : "rgba(255,255,255,0.08)";
      ctx.beginPath(); ctx.moveTo(ux, uy); ctx.lineTo(ux + dx * len, uy + dy * len); ctx.stroke();
    }
    // rings: every step to 10 steps (faint), every 5 steps beyond; the 5-step rings are stronger and labelled; ticks at the quarter spokes
    const tick = Math.max(2, W / 180);
    ctx.textAlign = "center";
    for (let n = 1; n * stepPx < uy + 1; n += n < CORRIDOR_STEPS ? 1 : RING_EVERY) {
      const r = n * stepPx, major = n % RING_EVERY === 0;
      ctx.lineWidth = 1; ctx.strokeStyle = major ? "rgba(255,255,255,0.28)" : "rgba(255,255,255,0.10)";
      ctx.beginPath(); ctx.arc(ux, uy, r, Math.PI, 2 * Math.PI); ctx.stroke();
      ctx.strokeStyle = major ? "rgba(255,255,255,0.45)" : "rgba(255,255,255,0.22)";
      ctx.beginPath();
      for (let q = -12; q <= 12; q++) {
        const [dx, dy] = dirs(q * 7.5), t = q % 4 === 0 ? tick * 1.6 : tick;
        ctx.moveTo(ux + dx * (r - t), uy + dy * (r - t)); ctx.lineTo(ux + dx * (r + t), uy + dy * (r + t));
      }
      ctx.stroke();
      // "N st" label beside the 12 o'clock spoke; skipped near the top edge where the "12" label sits
      if (major && uy - r > fs * 2.4) { ctx.fillStyle = "rgba(255,255,255,0.7)"; ctx.fillText(`${n} st`, ux + fs * 1.6, uy - r - 3); }
    }
    // hour labels once, at the outer end of each hour spoke, inside the canvas
    ctx.fillStyle = "rgba(255,255,255,0.5)"; ctx.textBaseline = "middle";
    for (let q = -12; q <= 12; q += 4) {
      const b = q * 7.5, [dx, dy] = dirs(b), r = edge(b) - fs * 0.9;
      ctx.fillText(String(clockText(q)), ux + dx * r, Math.min(uy + dy * r, W - fs * 0.8));
    }
    ctx.textBaseline = "alphabetic";
    // corridor +-0.6 m to 10 steps
    const hw = CORRIDOR_HALF_M / CELL_M * s, len = CORRIDOR_STEPS * stepPx;
    ctx.fillStyle = "rgba(255,45,45,0.12)"; ctx.fillRect(ux - hw, uy - len, 2 * hw, len);
    ctx.strokeStyle = "rgba(255,120,120,0.9)"; ctx.lineWidth = 1.5; ctx.strokeRect(ux - hw, uy - len, 2 * hw, len);
    // v26.2.2: the face / edge test of the walls the map judges (always drawn since v26.2.6): fitted wall lines, face and edge cells
    if (frame) {
      const cellPx = Math.max(2, s);
      for (const [side, ln] of Object.entries(frame.faceEdgeLines ?? {})) {
        if (!ln) continue;
        ctx.strokeStyle = "rgba(255,230,0,0.95)"; ctx.lineWidth = 2; ctx.beginPath();
        ctx.moveTo(ux + (ln.a / CELL_M) * s, uy); ctx.lineTo(ux + ((ln.a + ln.b * 8) / CELL_M) * s, uy - (8 / CELL_M) * s); ctx.stroke();
      }
      for (const h of frame.hazards ?? []) {
        const fe = h.faceEdge;
        if (!fe) continue;
        for (const [key, col] of [["edgeCells", "rgba(0,230,255,0.9)"], ["faceCells", "rgba(255,40,200,0.95)"]]) {
          ctx.fillStyle = col;
          for (const [f, r] of fe[key] ?? []) ctx.fillRect(ux + (r / CELL_M) * s - cellPx / 2, uy - (f / CELL_M) * s - cellPx / 2, cellPx, cellPx);
        }
      }
    }
    // hazards: ahead = distanceM, right = lateralM
    if (frame) {
      const hs = this.markers(frame);       // v26.2.6: no dot for building / bridge / tunnel items
      const drawOne = (h) => {
        const x = ux + (h.lateralM / CELL_M) * s, y = uy - (h.distanceM / CELL_M) * s;
        if (x < -4 || y < -4 || x > W + 4 || y > W + 4) return;
        const col = h.role === "danger" && h.urgency === "final" ? ROLE_COLOR.final : ROLE_COLOR[h.role] ?? ROLE_COLOR.none;
        const mover = h.group === "moving", r = Math.max(3, W / 70) * (mover ? 1.5 : 1);
        ctx.beginPath();
        if (mover) { ctx.moveTo(x, y - r * 1.2); ctx.lineTo(x + r * 1.2, y); ctx.lineTo(x, y + r * 1.2); ctx.lineTo(x - r * 1.2, y); ctx.closePath(); }
        else ctx.arc(x, y, r, 0, 2 * Math.PI);
        if (h.coasting) {   // predicted position of a mover that left the image: hollow, dashed
          ctx.setLineDash([4, 3]); ctx.lineWidth = 2; ctx.strokeStyle = col; ctx.stroke(); ctx.setLineDash([]);
        } else {
          ctx.fillStyle = col; ctx.globalAlpha = h.role === "none" ? 0.6 : 1; ctx.fill(); ctx.globalAlpha = 1;
          ctx.lineWidth = mover ? 2 : 1; ctx.strokeStyle = mover ? "#ffffff" : "rgba(0,0,0,0.6)"; ctx.stroke();
        }
        if (h.solidCorrected && h.distanceM > 0) {   // depth correction: a line from the raw position to the snapped one (the wall's near border)
          const k = h.rawDistanceM / h.distanceM, rx = ux + (h.lateralM * k / CELL_M) * s, ry = uy - (h.rawDistanceM / CELL_M) * s;
          ctx.setLineDash([3, 3]); ctx.lineWidth = 1.5; ctx.strokeStyle = "#ffffff";
          ctx.beginPath(); ctx.moveTo(rx, ry); ctx.lineTo(x, y); ctx.stroke(); ctx.setLineDash([]);
          ctx.beginPath(); ctx.arc(rx, ry, Math.max(2, r * 0.5), 0, 2 * Math.PI); ctx.stroke();
        } else if (h.insideSolid) {   // suppressed mode: crossed
          const q = r * 1.6; ctx.lineWidth = 2; ctx.strokeStyle = "#ffffff";
          ctx.beginPath(); ctx.moveTo(x - q, y - q); ctx.lineTo(x + q, y + q); ctx.moveTo(x + q, y - q); ctx.lineTo(x - q, y + q); ctx.stroke();
        }
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
    const my = Math.min(uy, W) - m * 1.1;               // the user stands on the bottom edge: keep the marker inside the canvas
    ctx.beginPath(); ctx.moveTo(ux, my - m * 1.5); ctx.lineTo(ux + m, my + m); ctx.lineTo(ux, my + m * 0.4); ctx.lineTo(ux - m, my + m); ctx.closePath();
    ctx.fill(); ctx.stroke();
    if (this.sel) {                                      // the selected cell (click readout): crosshair box, kept while the frame changes
      const cx = (this.sel.col + 0.5) * s, cy = (this.sel.row + 0.5) * s, q = Math.max(5, W / 60);
      ctx.lineWidth = 3; ctx.strokeStyle = "#000000"; ctx.strokeRect(cx - q, cy - q, 2 * q, 2 * q);
      ctx.lineWidth = 1.5; ctx.strokeStyle = "#ffe14d"; ctx.strokeRect(cx - q, cy - q, 2 * q, 2 * q);
      ctx.beginPath(); ctx.moveTo(cx - q * 1.6, cy); ctx.lineTo(cx + q * 1.6, cy); ctx.moveTo(cx, cy - q * 1.6); ctx.lineTo(cx, cy + q * 1.6); ctx.stroke();
    }
    $("#wmStatus").textContent = this.k >= 0 && this.poseT.length ? `t ${this.poseT[this.k].toFixed(1)} s · frame ${this.k + 1}/${this.poseT.length} · step ${step.toFixed(2)} m` : "";
  }
}
