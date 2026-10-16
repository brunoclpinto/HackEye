// Speech review panel (CONTRACTS §10): one row per spoken phrase of the loaded
// run plus user-added phrases; the user marks each correct / incorrect /
// should-not-be-said with a note. Reviews belong to the recording, so they load
// on recording select and don't need a run (verdict rows do).
//
// Updates are optimistic: local state changes first, a single serial queue
// sends the writes, and a failed write (api.js has already toasted the detail)
// reverts the local change. Rows are patched in place; only run/filter/add/
// delete/time changes re-render the whole list, so a focused note never loses
// its caret.
import { $, fmtTime, parseTime, toast, lastAtOrBefore, ROLE_COLOR, ROLES, eventRole } from "./util.js";
import { api } from "./api.js";

const VERDICTS = [["correct", "✓", "Correct (c)"], ["incorrect", "✗", "Incorrect (x)"], ["remove", "⊘", "Should not be said (r)"]];
const ADD_ROLES = [...ROLES, "other"];
const SAVE_DELAY_MS = 600;
const roleColor = (r) => ROLE_COLOR[r] ?? ROLE_COLOR.none;
const t3 = (t) => (+t).toFixed(3);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

export class Reviews {
  /** hooks: {seek(t), getTime(), pause(), transport(id)} supplied by app.js */
  constructor(hooks) {
    this.h = hooks;
    this.rec = null; this.run = null;
    this.speech = []; this.roles = new Set(ROLES);
    this.anns = []; this.vmap = new Map();
    this.items = []; this.curIdx = -2; this.lastT = 0;
    this.expanded = new Set(); this.drafts = new Map(); this.timers = new Map();
    this.queue = Promise.resolve(); this.loadToken = 0;
    this.list = $("#rvList"); this.empty = $("#rvEmpty");
    this._wire();
    this.render();
  }

  // ------------------------------------------------------------ data in
  async setRecording(rec) {
    this.rec = rec; this.anns = []; this._reindex(); this.expanded.clear(); this.drafts.clear();
    this.render();
    if (rec) await this.reload();
  }

  async reload() {
    const tok = ++this.loadToken, id = this.rec?.id;
    if (!id) return;
    try {
      const doc = await api(`/api/recordings/${encodeURIComponent(id)}/reviews`);
      if (tok !== this.loadToken) return;
      this.anns = doc.annotations; this._reindex(); this.render();
    } catch { /* toasted */ }
  }

  /** run: run.json (needs id, collisionVersion) or null; speech: its speech events sorted by t. */
  setRun(run, speech) {
    this.run = run; this.speech = speech ?? [];
    this._reindex(); this.render();
  }
  setRoles(roles) { this.roles = roles; this.render(); }

  // ------------------------------------------------------------ keys
  _evKey(ev) { return `${this.run.id}|${this.run.collisionVersion ?? null}|${t3(ev.t)}|${ev.text}`; }
  _annKey(a) { return `${a.runId}|${a.collisionVersion ?? null}|${t3(a.event.t)}|${a.event.text}`; }
  _reindex() {
    this.vmap = new Map();
    for (const a of this.anns) if (a.kind === "verdict" && a.runId) this.vmap.set(this._annKey(a), a);
  }
  _matchedIds() {
    const ids = new Set();
    if (this.run) for (const ev of this.speech) { const a = this.vmap.get(this._evKey(ev)); if (a) ids.add(a); }
    return ids;
  }

  // ------------------------------------------------------------ rendering
  render() {
    const matched = this._matchedIds();
    const items = [];
    if (this.run) {
      for (const ev of this.speech) {
        if (!this.roles.has(eventRole(ev))) continue;
        items.push({ rk: `ev:${this._evKey(ev)}`, t: ev.t, ev });
      }
    }
    for (const a of this.anns) {
      if (a.kind !== "added") continue;
      if (a.role !== "other" && !this.roles.has(a.role)) continue;
      items.push({ rk: `add:${a.id}`, t: a.t, ann: a });
    }
    items.sort((x, y) => x.t - y.t);
    this.items = items;

    this.list.replaceChildren(...items.map((it) => this._row(it)));
    this.empty.textContent = !this.rec ? "Select a recording."
      : items.length ? "" : this.run ? "No speech events match the role filter." : "Load a run to review its speech, or add phrases below.";
    this._header(matched);
    this._others(matched);
    this.curIdx = -2;
    this.highlight(this.lastT);
  }

  _header(matched = this._matchedIds()) {
    const c = { correct: 0, incorrect: 0, remove: 0 };
    for (const a of matched) c[a.verdict]++;
    const added = this.anns.filter((a) => a.kind === "added").length;
    const unreviewed = this.run ? this.speech.length - matched.size : 0;
    const set = (id, n) => { $(id).textContent = n; };
    set("#rvCorrect", c.correct); set("#rvIncorrect", c.incorrect); set("#rvRemove", c.remove);
    set("#rvAdded", added); set("#rvUnrev", this.run ? unreviewed : "–");
    const exp = $("#rvExport");
    exp.hidden = !this.rec;
    if (this.rec) exp.href = `/api/reviews/export?recording=${encodeURIComponent(this.rec.id)}`;
    $("#rvAddBtn").disabled = !this.rec;
  }

  _others(matched) {
    const others = this.anns.filter((a) => a.kind === "verdict" && !matched.has(a));
    const box = $("#rvOther");
    box.hidden = !others.length;
    $("#rvOtherSum").textContent = `Other versions (${others.length})`;
    const ul = $("#rvOtherList");
    ul.replaceChildren(...others.map((a) => {
      const li = el("li", "rv-row rv-other");
      const top = el("div", "rv-main");
      const tb = el("button", "rv-time mono", fmtTime(a.t, 1)); tb.type = "button";
      tb.addEventListener("click", () => this._seek(a.t));
      const v = VERDICTS.find((x) => x[0] === a.verdict);
      top.append(tb, el("span", "rv-vmark " + a.verdict, v[1]), el("span", "rv-text" + (a.verdict === "remove" ? " struck" : ""), a.event.text));
      const del = el("button", "rv-icon", "🗑"); del.type = "button"; del.title = "Delete";
      del.addEventListener("click", () => this._delete(a, "Delete this verdict from another run/version?"));
      top.append(del);
      li.append(top, el("div", "rv-sub", `run ${a.runId} · collision ${a.collisionVersion ?? "?"}${a.note ? " · " + a.note : ""}`));
      return li;
    }));
  }

  _row(it) {
    return it.ev ? this._eventRow(it) : this._addedRow(it);
  }

  _eventRow(it) {
    const { ev, rk } = it;
    const a = this.vmap.get(this._evKey(ev));
    const role = eventRole(ev);
    const li = el("li", "rv-row" + (a ? " v-" + a.verdict : ""));
    li.dataset.rk = rk;
    li.style.setProperty("--c", roleColor(role));
    const top = el("div", "rv-main");
    const tb = el("button", "rv-time mono", fmtTime(ev.t, 1)); tb.type = "button"; tb.title = "Seek here";
    tb.addEventListener("click", () => this._seek(ev.t));
    const badge = el("span", "rv-role", role); badge.style.color = roleColor(role);
    top.append(tb, badge, this._toggles(a, (v) => this.toggleVerdict(ev, v)));
    const text = el("div", "rv-text" + (a?.verdict === "remove" ? " struck" : ""), ev.text);
    li.append(top, text);
    const showNote = a || this.expanded.has(rk);
    if (showNote) li.append(this._noteBox(rk, a, a ? a.note : this.drafts.get(rk) ?? "", !a));
    return li;
  }

  _toggles(a, onPick) {
    const g = el("div", "rv-tools");
    for (const [v, sym, title] of VERDICTS) {
      const b = el("button", "rv-v " + v, sym); b.type = "button"; b.title = title; b.setAttribute("aria-label", title);
      b.setAttribute("aria-pressed", String(a?.verdict === v));
      b.addEventListener("click", () => onPick(v));
      g.append(b);
    }
    return g;
  }

  /** Note textarea with autosave; `a` is the owning annotation or null (draft until a verdict exists). */
  _noteBox(rk, a, value, draft) {
    const wrap = el("div", "rv-notewrap");
    const ta = el("textarea", "rv-note"); ta.rows = 2; ta.maxLength = 2000; ta.value = value;
    ta.placeholder = draft ? "Note (pick ✓ ✗ ⊘ to save it)" : "Note";
    const saved = el("span", "rv-saved");
    ta.addEventListener("input", () => {
      const cur = this._annOfRow(rk);
      if (!cur) { this.drafts.set(rk, ta.value); return; }
      cur.note = ta.value; saved.textContent = "…";
      this._debounce(rk, () => this._saveFields(cur, { note: ta.value }, saved));
    });
    ta.addEventListener("blur", () => { if (this.timers.has(rk)) this._flush(rk); });
    wrap.append(ta, saved);
    return wrap;
  }

  _addedRow(it) {
    const a = it.ann, rk = it.rk;
    const li = el("li", "rv-row added");
    li.dataset.rk = rk;
    li.style.setProperty("--c", roleColor(a.role));
    const top = el("div", "rv-main");
    top.append(el("span", "rv-addbadge", "+ added"));
    const tin = el("input", "rv-t mono"); tin.value = fmtTime(a.t, 1); tin.inputMode = "decimal"; tin.size = 7; tin.setAttribute("aria-label", "Time");
    tin.addEventListener("change", () => {
      const v = parseTime(tin.value);
      if (!(v >= 0) || (this.rec && v > this.rec.duration)) { toast("Time must be within the recording."); tin.value = fmtTime(a.t, 1); return; }
      this._editAdded(a, { t: v }, true);
    });
    const head = el("button", "rv-icon", "⟲"); head.type = "button"; head.title = "Set to playhead";
    head.addEventListener("click", () => this._editAdded(a, { t: this.h.getTime() }, true));
    const go = el("button", "rv-icon", "▸"); go.type = "button"; go.title = "Seek here";
    go.addEventListener("click", () => this._seek(a.t));
    const sel = this._roleSelect(a.role);
    sel.addEventListener("change", () => this._editAdded(a, { role: sel.value }, true));
    const del = el("button", "rv-icon", "🗑"); del.type = "button"; del.title = "Delete";
    del.addEventListener("click", () => this._delete(a, "Delete this added phrase?"));
    top.append(tin, head, go, sel, del);
    const txt = el("input", "rv-textin"); txt.value = a.text; txt.maxLength = 300; txt.setAttribute("aria-label", "Spoken text");
    const tsaved = el("span", "rv-saved");
    const saveText = () => {
      const v = txt.value.trim();
      if (!v) { toast("Text can't be empty."); txt.value = a.text; return; }
      if (v !== a.text) this._editAdded(a, { text: v }, false, tsaved);
    };
    txt.addEventListener("change", saveText);
    li.append(top, el("div", "rv-textrow"));
    li.lastChild.append(txt, tsaved);
    li.append(this._noteBox(rk, a, a.note, false));
    return li;
  }

  _roleSelect(value) {
    const sel = el("select", "rv-rolesel");
    for (const r of ADD_ROLES) sel.add(new Option(r, r));
    sel.value = value; sel.setAttribute("aria-label", "Role");
    return sel;
  }

  _rowEl(rk) { return [...this.list.children].find((n) => n.dataset.rk === rk) ?? null; }
  _refreshRow(rk) {
    const old = this._rowEl(rk);
    const it = this.items.find((x) => x.rk === rk);
    if (!old || !it) return;
    const fresh = this._row(it);
    if (old.classList.contains("cur")) fresh.classList.add("cur");
    old.replaceWith(fresh);
    this._header();
    this._others(this._matchedIds());
  }
  _annOfRow(rk) {
    if (rk.startsWith("ev:")) { const ev = this.items.find((x) => x.rk === rk)?.ev; return ev ? this.vmap.get(this._evKey(ev)) : undefined; }
    return this.anns.find((x) => `add:${x.id}` === rk);
  }
  _rkOf(a) { return a.kind === "added" ? `add:${a.id}` : `ev:${this._annKey(a)}`; }

  // ------------------------------------------------------------ writes
  _send(fn) { this.queue = this.queue.then(fn).catch(() => {}); return this.queue; }
  _base() { return `/api/recordings/${encodeURIComponent(this.rec.id)}/reviews`; }
  _debounce(rk, fn) {
    clearTimeout(this.timers.get(rk)?.id);
    const id = setTimeout(() => { this.timers.delete(rk); fn(); }, SAVE_DELAY_MS);
    this.timers.set(rk, { id, fn });
  }
  _flush(rk) {
    const t = this.timers.get(rk);
    if (!t) return;
    clearTimeout(t.id); this.timers.delete(rk); t.fn();
  }

  /** PUT {fields} for annotation `a` (already mutated locally); revert on failure. */
  _saveFields(a, fields, indicator) {
    const rec = this.rec;
    return this._send(async () => {
      if (a.dead) return;
      try {
        const res = await api(`/api/recordings/${encodeURIComponent(rec.id)}/reviews/${a.id}`, { method: "PUT", body: fields });
        a.updatedAt = res.updatedAt;
        if (indicator) { indicator.textContent = "saved ✓"; setTimeout(() => { if (indicator.textContent === "saved ✓") indicator.textContent = ""; }, 1500); }
      } catch {
        if (indicator) indicator.textContent = "not saved";
        await this.reload();
      }
    });
  }

  toggleVerdict(ev, verdict) {
    if (!this.run || !this.rec) { toast("Load a run first.", "info"); return; }
    const key = this._evKey(ev), rk = `ev:${key}`;
    const cur = this.vmap.get(key);
    if (cur && cur.verdict === verdict) { this._delete(cur); return; }
    if (cur) {
      cur.verdict = verdict;
      this._refreshRow(rk);
      this._send(async () => {
        if (cur.dead) return;
        try { await api(`${this._base()}/${cur.id}`, { method: "PUT", body: { verdict } }); }
        catch { await this.reload(); }
      });
      return;
    }
    const snapshot = {};
    for (const k of ["t", "text", "role", "trackId", "urgency", "clock"]) if (ev[k] !== undefined) snapshot[k] = ev[k];
    const run = this.run, rec = this.rec;
    const draft = this.drafts.get(rk) ?? "";
    this.drafts.delete(rk);
    const a = { id: `tmp-${Math.random().toString(16).slice(2)}`, kind: "verdict", verdict, note: draft, t: ev.t, event: snapshot,
      runId: run.id, collisionVersion: run.collisionVersion ?? null };
    this.anns.push(a); this._reindex();
    this._refreshRow(rk);
    this._send(async () => {
      if (a.dead) return;
      try {
        const res = await api(this._base(), { method: "POST", body: { kind: "verdict", verdict, note: draft, t: ev.t, event: snapshot, runId: run.id, collisionVersion: run.collisionVersion ?? undefined } });
        const localNote = a.note, localVerdict = a.verdict;
        Object.assign(a, res);
        a.verdict = localVerdict; a.note = localNote;
        if (localVerdict !== res.verdict) await api(`${this._base()}/${a.id}`, { method: "PUT", body: { verdict: localVerdict } });
        if (localNote !== res.note) await api(`${this._base()}/${a.id}`, { method: "PUT", body: { note: localNote } });
      } catch {
        a.dead = true;
        if (this.rec === rec) await this.reload();
      }
    });
  }

  _delete(a, confirmMsg) {
    if (confirmMsg && !confirm(confirmMsg)) return;
    const rk = this._rkOf(a);
    this.anns = this.anns.filter((x) => x !== a); this._reindex();
    this.expanded.delete(rk);
    this.render();
    this._send(async () => {
      if (a.dead) return;
      try { await api(`${this._base()}/${a.id}`, { method: "DELETE" }); a.dead = true; }
      catch { await this.reload(); }
    });
  }

  _editAdded(a, fields, rerender, indicator) {
    const rk = this._rkOf(a);
    Object.assign(a, fields);
    if (rerender) this.render(); else this._refreshRow(rk);
    this._saveFields(a, fields, indicator);
  }

  // ------------------------------------------------------------ add form
  openAdd() {
    if (!this.rec) return;
    const f = $("#rvAddForm");
    f.hidden = false;
    $("#rvAddT").value = fmtTime(this.h.getTime(), 1);
    $("#rvAddText").focus();
  }
  closeAdd() { $("#rvAddForm").hidden = true; $("#rvAddText").value = ""; $("#rvAddNote").value = ""; }

  async submitAdd() {
    if (!this.rec) return;
    const t = parseTime($("#rvAddT").value), text = $("#rvAddText").value.trim();
    if (!(t >= 0) || t > this.rec.duration) { toast("Time must be within the recording."); return; }
    if (!text) { toast("Enter the phrase that should have been spoken."); $("#rvAddText").focus(); return; }
    const body = { kind: "added", t, text, role: $("#rvAddRole").value, note: $("#rvAddNote").value };
    if (this.run) { body.runId = this.run.id; body.collisionVersion = this.run.collisionVersion ?? undefined; }
    const btn = $("#rvAddSubmit"); btn.disabled = true;
    try {
      const a = await api(this._base(), { method: "POST", body });
      this.anns.push(a); this.anns.sort((x, y) => x.t - y.t);
      this.closeAdd(); this.render();
      this.lastT = a.t; this.curIdx = -2; this.highlight(a.t);
    } catch { /* toasted; keep the form */ }
    finally { btn.disabled = false; }
  }

  // ------------------------------------------------------------ playback
  _seek(t) { this.h.pause(); this.h.seek(t + 0.001); }

  highlight(t) {
    this.lastT = t;
    const i = lastAtOrBefore(this.items, t);
    if (i === this.curIdx) return;
    this.list.children[this.curIdx]?.classList.remove("cur");
    this.curIdx = i;
    const row = this.list.children[i];
    if (!row) return;
    row.classList.add("cur");
    const a = document.activeElement;
    if (a && this.list.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return; // don't yank while typing
    const lt = this.list.scrollTop, lh = this.list.clientHeight;
    if (row.offsetTop < lt || row.offsetTop + row.offsetHeight > lt + lh) {
      this.list.scrollTop = Math.max(0, row.offsetTop - lh / 3);
    }
  }

  // ------------------------------------------------------------ wiring
  _wire() {
    const sel = $("#rvAddRole");
    for (const r of ADD_ROLES) sel.add(new Option(r, r));
    sel.value = "danger";
    $("#rvAddBtn").addEventListener("click", () => ($("#rvAddForm").hidden ? this.openAdd() : this.closeAdd()));
    $("#rvAddHead").addEventListener("click", () => { $("#rvAddT").value = fmtTime(this.h.getTime(), 1); });
    $("#rvAddCancel").addEventListener("click", () => this.closeAdd());
    $("#rvAddSubmit").addEventListener("click", () => this.submitAdd());
    $("#rvAddText").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); this.submitAdd(); } });
    $("#rvAddForm").addEventListener("keydown", (e) => { if (e.key === "Escape") this.closeAdd(); });
    for (const [id, tid] of [["#rvPrev", "stepBack"], ["#rvPlay", "playBtn"], ["#rvNext", "stepFwd"]]) {
      $(id).addEventListener("click", () => this.h.transport(tid));
    }
    // c / x / r on the highlighted event row; a opens "add at playhead".
    window.addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target;
      if (t && (t.tagName === "INPUT" && t.type !== "checkbox" && t.type !== "range" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      const k = e.key.toLowerCase();
      if (k === "a") { e.preventDefault(); this.openAdd(); return; }
      const v = { c: "correct", x: "incorrect", r: "remove" }[k];
      if (!v) return;
      const it = this.items[this.curIdx];
      if (it?.ev) { e.preventDefault(); this.toggleVerdict(it.ev, v); }
    });
    // Row text toggles the note box for unreviewed rows.
    this.list.addEventListener("click", (e) => {
      const txt = e.target.closest(".rv-text");
      const row = txt?.closest(".rv-row");
      if (!row || !row.dataset.rk?.startsWith("ev:")) return;
      const rk = row.dataset.rk;
      if (this._annOfRow(rk)) return; // note is always visible once reviewed
      if (this.expanded.has(rk)) this.expanded.delete(rk); else this.expanded.add(rk);
      this._refreshRow(rk);
      if (this.expanded.has(rk)) this._rowEl(rk)?.querySelector("textarea")?.focus();
    });
  }
}
