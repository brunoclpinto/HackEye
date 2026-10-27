// Open issues panel (v26.2.4 follow-up): the catalogue (lab/issues.json) in groups, with the user's Close / Reopen and a comment per issue
// (GET /api/issues, PUT /api/issues/{id}; state in LAB_DIR/issues-state.json). Close / Reopen is optimistic; all writes go through one serial queue.
import { $ } from "./util.js";
import { api } from "./api.js";

const SAVE_DELAY_MS = 600;
const KEY = "hackeye.lab.issues.ui";

const lsGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } };

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/** Text with `backticks` as <code>; everything else is escaped (built with text nodes). */
function richText(text, into) {
  String(text).split("`").forEach((part, i) => {
    if (i % 2 && part) into.append(el("code", "", part)); else if (part) into.append(document.createTextNode(part));
  });
  return into;
}

export class IssuesPanel {
  constructor() {
    this.groups = [];            // group defs [{id, title}] in catalogue order
    this.items = [];             // flat, each with .group (origin), .status, .note
    this.expanded = new Set();
    this.timers = new Map();     // id -> {id: timeout, fn}
    this.queue = Promise.resolve();
    this.pending = 0;
    const ui = (() => { try { return JSON.parse(lsGet(KEY) || "{}"); } catch { return {}; } })();
    this.ui = ui && typeof ui === "object" ? ui : {};
  }

  async load() {
    this.root = $("#issuesBody");
    this.sec = $("#secIssues");
    if (!this.root) return;
    if (typeof this.ui.section === "boolean") this.sec.open = this.ui.section;
    this.sec.addEventListener("toggle", () => this._remember("section", this.sec.open));
    window.addEventListener("focus", () => this.sync());
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") this.sync(); });
    await this.reload();
  }

  _remember(k, v) { this.ui[k] = v; lsSet(KEY, JSON.stringify(this.ui)); }

  async reload() {
    let d;
    try { d = await api("/api/issues", { quiet: true }); } catch { this.root.textContent = "Issues: the server list is not available."; return; }
    this.groups = d.groups.map((g) => ({ id: g.id, title: g.title }));
    this.items = d.groups.flatMap((g) => g.items);
    this.render();
  }

  /** Re-fetch when nothing is being edited or written. */
  async sync() {
    if (!this.root || this.timers.size || this.pending || this.root.contains(document.activeElement) && document.activeElement.tagName === "TEXTAREA") return;
    await this.reload();
  }

  _grouped() {
    const ids = new Set(this.groups.map((g) => g.id));
    const firstOpen = this.groups.find((g) => g.id !== "closed")?.id;
    return this.groups.map((g) => {
      const items = g.id === "closed"
        ? this.items.filter((i) => i.status === "closed")
        : this.items.filter((i) => i.status === "open" && (i.group === g.id || (g.id === firstOpen && (!ids.has(i.group) || i.group === "closed"))));
      return { ...g, items, openCount: items.filter((i) => i.status === "open").length };
    });
  }

  render() {
    const groups = this._grouped();
    const total = groups.reduce((n, g) => n + g.openCount, 0);
    $("#issuesTitle").textContent = `Open issues (${total} open)`;
    const frag = document.createDocumentFragment();
    for (const g of groups) {
      const d = el("details", "iss-group");
      d.dataset.group = g.id;
      d.open = g.id in (this.ui.groups ?? {}) ? !!this.ui.groups[g.id] : g.id !== "closed";
      d.append(el("summary", "", `${g.title} (${g.id === "closed" ? g.items.length : g.openCount})`));
      d.addEventListener("toggle", () => { this._remember("groups", { ...(this.ui.groups ?? {}), [g.id]: d.open }); });
      const ul = el("ul", "iss-list");
      for (const it of g.items) ul.append(this._row(it));
      if (!g.items.length) ul.append(el("li", "hint", "Nothing here."));
      d.append(ul);
      frag.append(d);
    }
    this.root.replaceChildren(frag);
  }

  _row(it) {
    const li = el("li", "iss-item" + (it.status === "closed" ? " closed" : ""));
    li.dataset.id = it.id;
    const head = el("div", "iss-head");
    const toggle = el("button", "iss-title");
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", String(this.expanded.has(it.id)));
    toggle.append(el("span", "iss-id", it.id), el("span", "iss-name", it.title));
    if (it.note && it.note.trim()) toggle.append(el("span", "iss-hasnote", "✎"));
    toggle.addEventListener("click", () => {
      if (this.expanded.has(it.id)) this.expanded.delete(it.id); else this.expanded.add(it.id);
      this.render();
    });
    const act = el("button", "iss-act", it.status === "closed" ? "Reopen" : "Close");
    act.type = "button";
    act.dataset.act = it.status === "closed" ? "reopen" : "close";
    act.addEventListener("click", () => this._setStatus(it, it.status === "closed" ? "open" : "closed"));
    head.append(toggle, act);
    li.append(head);
    if (this.expanded.has(it.id)) li.append(this._detail(it));
    return li;
  }

  _detail(it) {
    const box = el("div", "iss-detail");
    if (it.status === "closed") {
      const o = this.groups.find((g) => g.id === it.group);
      const bits = [];
      if (it.closedAt) bits.push(`closed ${String(it.closedAt).slice(0, 10)}`);
      if (o && o.id !== "closed") bits.push(`from: ${o.title}`);
      if (bits.length) box.append(el("div", "hint", bits.join(" · ")));
      if (it.reason) box.append(richText(it.reason, el("div", "iss-reason")));
    }
    if (it.details?.length) {
      const ul = el("ul", "iss-lines");
      for (const line of it.details) ul.append(richText(line, el("li")));
      box.append(ul);
    }
    if (it.refs?.length) box.append(el("div", "hint", `refs: ${it.refs.join(", ")}`));
    const wrap = el("div", "rv-notewrap");
    const ta = el("textarea", "rv-note"); ta.rows = 2; ta.maxLength = 4000; ta.value = it.note || "";
    ta.placeholder = "Comment";
    ta.setAttribute("aria-label", `Comment on ${it.id}`);
    const saved = el("span", "rv-saved");
    ta.addEventListener("input", () => {
      it.note = ta.value; saved.textContent = "…";
      this._debounce(it.id, () => this._saveNote(it, saved));
    });
    ta.addEventListener("blur", () => this._flush(it.id));
    wrap.append(ta, saved);
    box.append(wrap);
    return box;
  }

  _debounce(id, fn) {
    const t = this.timers.get(id);
    if (t) clearTimeout(t.id);
    this.timers.set(id, { id: setTimeout(() => { this.timers.delete(id); fn(); }, SAVE_DELAY_MS), fn });
  }

  _flush(id) {
    const t = this.timers.get(id);
    if (!t) return;
    clearTimeout(t.id); this.timers.delete(id); t.fn();
  }

  _send(fn) {
    this.pending += 1;
    const run = this.queue.then(fn);
    this.queue = run.catch(() => {}).then(() => { this.pending -= 1; });
    return run;
  }

  _saveNote(it, indicator) {
    const note = it.note;
    return this._send(async () => {
      try {
        await api(`/api/issues/${encodeURIComponent(it.id)}`, { method: "PUT", body: { note } });
        indicator.textContent = "saved ✓";
        setTimeout(() => { if (indicator.textContent === "saved ✓") indicator.textContent = ""; }, 1500);
      } catch {
        indicator.textContent = "not saved";
        await this.reload();
      }
    });
  }

  _setStatus(it, status) {
    this._flush(it.id);
    it.status = status;
    this.render();
    return this._send(async () => {
      try { await api(`/api/issues/${encodeURIComponent(it.id)}`, { method: "PUT", body: { status } }); }
      catch { await this.reload(); }
    });
  }
}
