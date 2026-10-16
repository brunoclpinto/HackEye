// View-only class styling of the mask overlay: which classes are shown and which safety level
// (hence colour + opacity) each is painted with. Nothing here touches shared config or collision logic;
// the choices live in localStorage (one entry per safety-mapping file).
import { $ } from "./util.js";
import { api } from "./api.js";

const KEY = (mapping) => `hackeye.lab.classes.${mapping}`;
const hex = (rgb) => "#" + rgb.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
const unhex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

/** Defaults + user edits -> a 256-entry RGBA lookup table (class id -> pixel).
 *  Two sections, saved independently: "classes" (level + show per class) and "levels" (colour + opacity per level).
 *  Their diff shapes equal the server's `saved` shape (CONTRACTS display): only values that differ from the defaults. */
export class MaskStyle {
  constructor(info) {
    this.info = info;                       // {mapping, classes:[{id,name,level}], levels:[{level,label,color,opacity}]}
    this.version = 0;                       // bumped on every change: rendered frames re-colour lazily
    this.lut = new Uint8ClampedArray(256 * 4);
    this.setClasses({});
    this.setLevels({});
    this.rebuild();
  }

  defaultOpacity(l) { return l.opacity ?? (l.level === 0 ? 0 : 1); }   // "ignored" is invisible unless the user opts in

  /** Replace the classes section by defaults + `d` ({id: {level?, show?}}). No rebuild. */
  setClasses(d) {
    this.hidden = new Set();
    this.levelOf = new Map(this.info.classes.map((c) => [c.id, c.level]));
    const lvls = new Set(this.info.levels.map((l) => l.level));
    for (const [id, e] of Object.entries(d ?? {})) {
      if (!this.levelOf.has(+id) || !e) continue;
      if (lvls.has(e.level)) this.levelOf.set(+id, e.level);
      if (e.show === false) this.hidden.add(+id);
    }
  }

  /** Replace the levels section by defaults + `d` ({level: {color?, opacity?}}). No rebuild. */
  setLevels(d) {
    this.color = new Map(this.info.levels.map((l) => [l.level, [...l.color]]));
    this.opacity = new Map(this.info.levels.map((l) => [l.level, this.defaultOpacity(l)]));
    for (const [lv, e] of Object.entries(d ?? {})) {
      if (!this.color.has(+lv) || !e) continue;
      if (Array.isArray(e.color) && e.color.length === 3 && e.color.every(Number.isFinite)) this.color.set(+lv, e.color.map((v) => Math.max(0, Math.min(255, Math.round(v)))));
      if (Number.isFinite(e.opacity)) this.opacity.set(+lv, Math.max(0, Math.min(1, e.opacity)));
    }
  }

  diffClasses() {
    const d = {};
    for (const c of this.info.classes) {
      const e = {};
      if (this.levelOf.get(c.id) !== c.level) e.level = this.levelOf.get(c.id);
      if (this.hidden.has(c.id)) e.show = false;
      if (Object.keys(e).length) d[c.id] = e;
    }
    return d;
  }

  diffLevels() {
    const d = {};
    for (const l of this.info.levels) {
      const e = {};
      if (hex(this.color.get(l.level)) !== hex(l.color)) e.color = this.color.get(l.level);
      if (this.opacity.get(l.level) !== this.defaultOpacity(l)) e.opacity = this.opacity.get(l.level);
      if (Object.keys(e).length) d[l.level] = e;
    }
    return d;
  }

  get edited() { return Object.keys(this.diffClasses()).length > 0 || Object.keys(this.diffLevels()).length > 0; }

  rebuild() {
    const lut = this.lut;
    lut.fill(0);
    for (const c of this.info.classes) {
      if (c.id > 255 || this.hidden.has(c.id)) continue;
      const lv = this.levelOf.get(c.id), rgb = this.color.get(lv);
      lut.set([rgb[0], rgb[1], rgb[2], Math.round(this.opacity.get(lv) * 255)], c.id * 4);
    }
    this.version++;
  }

  /** Paint a class grid (Uint8Array w*h of class ids) into `img` (ImageData of the same size). */
  paint(grid, img) {
    const lut = this.lut, out = img.data;
    for (let i = 0, j = 0; i < grid.length; i++, j += 4) {
      const k = grid[i] * 4;
      out[j] = lut[k]; out[j + 1] = lut[k + 1]; out[j + 2] = lut[k + 2]; out[j + 3] = lut[k + 3];
    }
  }
}

const canon = (o) => JSON.stringify(o, (_k, v) => (v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, v[k]])) : v));
const SECTIONS = {
  classes: { diff: (st) => st.diffClasses(), set: (st, d) => st.setClasses(d), btn: "#clsSaveC", status: "#clsStatC", discard: "#clsDiscC", noun: "class levels" },
  levels: { diff: (st) => st.diffLevels(), set: (st, d) => st.setLevels(d), btn: "#clsSaveL", status: "#clsStatL", discard: "#clsDiscL", noun: "level colours" },
};

/** The collapsible "Classes & safety levels" panel.
 *  Edits preview instantly. Unsaved edits are a per-browser draft (localStorage); the two Save buttons store
 *  each section on the Lab server (LAB_DIR/display/<mapping>) so every device shows the same view. */
export class ClassesPanel {
  constructor(overlay) {
    this.overlay = overlay;
    this.style = null;
    this.runId = null;
    this.saved = { classes: {}, levels: {} };   // server overrides, per section
    this.flash = {};                            // section -> "Saved" tick shown until the next edit
    this.rows = new Map();   // class id -> {tr, cb, sw, sel}
    this.levelRows = new Map();
    $("#clsAll").addEventListener("click", () => this.setAll(true));
    $("#clsNone").addEventListener("click", () => this.setAll(false));
    $("#clsReset").addEventListener("click", () => this.resetAll());
    $("#clsFilter").addEventListener("input", () => this.applyFilter());
    for (const name of Object.keys(SECTIONS)) {
      $(SECTIONS[name].btn).addEventListener("click", () => this.save(name));
      $(SECTIONS[name].discard).addEventListener("click", () => this.discard(name));
    }
    this.render();
  }

  /** Load the run's class list (null = no run). Falls back to the pre-rendered masks if it fails. */
  async setRun(run) {
    this.runId = run?.id ?? null;
    this.style = null;
    this.saved = { classes: {}, levels: {} };
    this.flash = {};
    this.render();
    if (!run) return;
    const id = run.id;
    try {
      const info = await api(`/api/runs/${id}/classes`, { quiet: true });
      if (this.runId !== id) return;
      if (!info?.classes?.length || !info?.levels?.length) throw new Error("empty class info");
      try {   // the server-saved view; unreachable = defaults + local draft only
        const d = await api(`/api/display/${info.mapping}`, { quiet: true });
        this.saved = { classes: d.saved?.classes ?? {}, levels: d.saved?.levels ?? {} };
      } catch { /* keep defaults */ }
      if (this.runId !== id) return;
      const st = this.style = new MaskStyle(info);
      for (const name of Object.keys(SECTIONS)) SECTIONS[name].set(st, this.saved[name]);
      const draft = this.readDraft();
      for (const name of Object.keys(SECTIONS)) if (draft[name]) SECTIONS[name].set(st, draft[name]);   // unsaved edits win
      st.rebuild();
      this.render();
      this.overlay.setMaskStyle(st);
    } catch (e) {
      if (this.runId !== id) return;
      this.render(`Class list unavailable (${e.message}); showing the pre-rendered masks.`);
      this.overlay.setMaskStyle(null);
    }
  }

  draftKey() { return `hackeye.lab.classes.${this.style.info.mapping}`; }
  readDraft() {
    try {
      const d = JSON.parse(localStorage.getItem(this.draftKey()) || "null");
      return d && typeof d === "object" ? d : {};
    } catch { return {}; }
  }
  /** Keep only the sections that differ from the server-saved ones. */
  writeDraft() {
    const d = {};
    for (const name of Object.keys(SECTIONS)) if (this.dirty(name)) d[name] = SECTIONS[name].diff(this.style);
    try {
      if (Object.keys(d).length) localStorage.setItem(this.draftKey(), JSON.stringify(d));
      else localStorage.removeItem(this.draftKey());
    } catch { /* storage blocked */ }
  }

  dirty(name) { return canon(SECTIONS[name].diff(this.style)) !== canon(this.saved[name]); }

  changed(name) {
    this.flash = {};
    this.style.rebuild();
    this.writeDraft();
    this.syncControls();
    this.overlay.redraw();
  }

  async save(name) {
    const sec = SECTIONS[name], body = { [name]: sec.diff(this.style) };
    try {
      const d = await api(`/api/display/${this.style.info.mapping}/${name}`, { method: "PUT", body });
      this.saved[name] = d.saved?.[name] ?? body[name];
      this.flash[name] = true;
    } catch { return; }   // api() already toasted
    this.writeDraft();
    this.syncControls();
  }

  /** Drop this section's unsaved edits: back to the server-saved view. */
  discard(name) {
    SECTIONS[name].set(this.style, this.saved[name]);
    this.changed(name);
  }

  async resetAll() {
    const st = this.style;
    if (!st || !window.confirm("Reset classes, levels and colours to the defaults? This also clears the saved view on the server.")) return;
    try {
      for (const name of Object.keys(SECTIONS)) {
        if (canon(this.saved[name]) !== "{}") {
          await api(`/api/display/${st.info.mapping}/${name}`, { method: "DELETE" });
          this.saved[name] = {};
        }
      }
    } catch { /* toasted; reset what we can */ }
    for (const name of Object.keys(SECTIONS)) if (canon(this.saved[name]) === "{}") SECTIONS[name].set(st, {});
    this.changed();
  }

  setAll(on) {
    if (!this.style) return;
    const shown = [...this.rows].filter(([, r]) => !r.tr.hidden).map(([id]) => id);   // only the filtered rows
    for (const id of shown) on ? this.style.hidden.delete(id) : this.style.hidden.add(id);
    this.changed("classes");
  }

  applyFilter() {
    const q = $("#clsFilter").value.trim().toLowerCase();
    for (const [id, r] of this.rows) r.tr.hidden = q !== "" && !r.name.includes(q) && !String(id).startsWith(q);
  }

  /** Push the style state into the (already built) controls. */
  syncControls() {
    const st = this.style;
    if (!st) return;
    for (const [id, r] of this.rows) {
      const lv = st.levelOf.get(id), shown = !st.hidden.has(id);
      r.cb.checked = shown;
      r.sel.value = String(lv);
      r.sw.style.background = hex(st.color.get(lv));
      r.sw.style.opacity = shown ? String(Math.max(0.25, st.opacity.get(lv))) : "0.15";
      r.sw.title = `level ${lv}: ${hex(st.color.get(lv))}, opacity ${st.opacity.get(lv)}`;
    }
    for (const [lv, r] of this.levelRows) {
      r.color.value = hex(st.color.get(lv));
      r.range.value = String(st.opacity.get(lv));
      r.out.textContent = st.opacity.get(lv).toFixed(2);
    }
    for (const name of Object.keys(SECTIONS)) {
      const sec = SECTIONS[name], dirty = this.dirty(name);
      const btn = $(sec.btn), stat = $(sec.status);
      btn.disabled = !dirty;
      $(sec.discard).hidden = !dirty;
      stat.textContent = dirty ? "unsaved changes" : this.flash[name] ? "Saved \u2713" : "";
      stat.classList.toggle("cls-dirty", dirty);
    }
    $("#clsEdited").hidden = !st.edited;
    $("#clsReset").disabled = !st.edited && canon(this.saved.classes) === "{}" && canon(this.saved.levels) === "{}";
  }

  render(message = null) {
    const st = this.style;
    const msg = $("#clsMsg"), ctl = $("#clsBody");
    this.rows.clear(); this.levelRows.clear();
    $("#clsBody tbody#clsClasses").replaceChildren();
    $("#clsBody tbody#clsLevels").replaceChildren();
    msg.textContent = message ?? (st ? `${st.info.classes.length} classes · mapping ${st.info.mapping}` : "Load an analysed run to edit its classes.");
    ctl.hidden = !st;
    $("#clsEdited").hidden = true;
    if (!st) return;

    const levelsTb = $("#clsLevels");
    for (const l of st.info.levels) {
      const tr = document.createElement("tr");
      const label = document.createElement("td"); label.textContent = `${l.level} ${l.label}`;
      const cTd = document.createElement("td"), color = document.createElement("input");
      color.type = "color"; color.setAttribute("aria-label", `${l.label} colour`); color.dataset.level = l.level;
      color.addEventListener("input", () => { st.color.set(l.level, unhex(color.value)); this.changed("levels"); });
      cTd.append(color);
      const oTd = document.createElement("td"), range = document.createElement("input"), out = document.createElement("output");
      range.type = "range"; range.min = 0; range.max = 1; range.step = 0.05; range.dataset.level = l.level;
      range.setAttribute("aria-label", `${l.label} opacity`);
      range.addEventListener("input", () => { st.opacity.set(l.level, Number(range.value)); this.changed("levels"); });
      out.className = "mono";
      oTd.append(range, " ", out);
      tr.append(label, cTd, oTd);
      levelsTb.append(tr);
      this.levelRows.set(l.level, { color, range, out });
    }

    const tb = $("#clsClasses");
    for (const c of st.info.classes) {
      const tr = document.createElement("tr");
      const cbTd = document.createElement("td"), cb = document.createElement("input");
      cb.type = "checkbox"; cb.dataset.cls = c.id; cb.setAttribute("aria-label", `show ${c.name}`);
      cb.addEventListener("change", () => { cb.checked ? st.hidden.delete(c.id) : st.hidden.add(c.id); this.changed("classes"); });
      cbTd.append(cb);
      const swTd = document.createElement("td"), sw = document.createElement("span");
      sw.className = "cls-sw"; swTd.append(sw);
      const nameTd = document.createElement("td"); nameTd.textContent = c.name; nameTd.className = "cls-name";
      const selTd = document.createElement("td"), sel = document.createElement("select");
      sel.dataset.cls = c.id; sel.setAttribute("aria-label", `${c.name} safety level`);
      for (const l of st.info.levels) sel.add(new Option(`${l.level} ${l.label}`, String(l.level)));
      sel.addEventListener("change", () => { st.levelOf.set(c.id, Number(sel.value)); this.changed("classes"); });
      selTd.append(sel);
      tr.append(cbTd, swTd, nameTd, selTd);
      tb.append(tr);
      this.rows.set(c.id, { tr, cb, sw, sel, name: c.name.toLowerCase() });
    }
    this.syncControls();
    this.applyFilter();
  }
}
