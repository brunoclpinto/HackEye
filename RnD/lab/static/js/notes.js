// Notes box (v26.2.4 follow-up): one Lab-wide freeform document for reviews, remarks and fix requests (GET/PUT /api/notes).
// Autosave 800 ms after the last keystroke and on blur; failed saves retry with backoff; a stale tab gets a conflict notice
// (Load theirs / Keep mine) instead of silently overwriting newer text; focus / visibility re-sync when nothing is unsaved.
import { $, fmtTime } from "./util.js";

const DEBOUNCE_MS = 800;
const RETRY_MS = [2000, 4000, 8000, 15000];
const DRAFT_KEY = "hackeye.lab.notes.draft";
const OPEN_KEY = "hackeye.lab.notes.open";

const lsGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } };
const lsDel = (k) => { try { localStorage.removeItem(k); } catch { /* storage unavailable */ } };

export class NotesPanel {
  /** getRecId() / getTime() / getRunId(): the open recording id (or null), the playhead in s, the loaded run id (or null). */
  constructor({ getRecId, getTime, getRunId }) {
    this.getRecId = getRecId;
    this.getTime = getTime;
    this.getRunId = getRunId;
    this.serverText = "";
    this.updatedAt = null;
    this.dirty = false;
    this.inflight = false;
    this.conflict = null;
    this.timer = null;
    this.retryTimer = null;
    this.retries = 0;
  }

  async load() {
    this.box = $("#notesText");
    this.status = $("#notesStatus");
    this.sec = $("#secNotes");
    this.stamp = $("#notesStamp");
    this.conf = $("#notesConflict");
    if (!this.box) return;
    const open = lsGet(OPEN_KEY);
    if (open !== null) this.sec.open = open === "1";
    this.sec.addEventListener("toggle", () => lsSet(OPEN_KEY, this.sec.open ? "1" : "0"));
    this.box.addEventListener("input", () => this._edited());
    this.box.addEventListener("blur", () => { if (this.dirty) this._saveNow(); });
    this.stamp.addEventListener("click", () => this._insertStamp());
    $("#notesTheirs").addEventListener("click", () => this._loadTheirs());
    $("#notesMine").addEventListener("click", () => this._keepMine());
    window.addEventListener("beforeunload", (e) => { if (this.dirty) { e.preventDefault(); e.returnValue = ""; } });
    window.addEventListener("focus", () => this.sync());
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") this.sync(); });
    await this._fetchInitial();
    this.recordingChanged();
  }

  /** Enable / disable the Insert-time button (call when the recording changes). */
  recordingChanged() { if (this.stamp) this.stamp.disabled = !this.getRecId(); }

  async _fetchInitial() {
    let cur;
    try { cur = await this._get(); } catch { this._status("Notes: the server is not available."); return; }
    this.updatedAt = cur.updatedAt;
    this.serverText = cur.text;
    const draft = lsGet(DRAFT_KEY);
    if (draft !== null && draft !== cur.text) {
      this.box.value = draft;
      this.dirty = true;
      this._status("Restored an unsaved draft, saving…");
      this._saveNow();
    } else {
      this.box.value = cur.text;
      lsDel(DRAFT_KEY);
    }
  }

  async _get() {
    const r = await fetch("/api/notes");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  _status(msg) { if (this.status) this.status.textContent = msg; }

  _edited() {
    this.dirty = true;
    lsSet(DRAFT_KEY, this.box.value);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this._saveNow(), DEBOUNCE_MS);
  }

  _insertStamp() {
    const rec = this.getRecId();
    if (!rec) return;
    const run = this.getRunId();
    const s = `[${rec} @ ${fmtTime(this.getTime() || 0, 1)}${run ? ` · run ${run}` : ""}] `;
    const b = this.box;
    const a = b.selectionStart ?? b.value.length, z = b.selectionEnd ?? a;
    b.setRangeText(s, a, z, "end");
    b.focus();
    this._edited();
  }

  _saveNow() {
    clearTimeout(this.timer);
    clearTimeout(this.retryTimer);
    if (this.conflict) return;
    if (this.inflight) { this.pendingAgain = true; return; }
    this._save(false);
  }

  async _save(force) {
    const text = this.box.value;
    this.inflight = true;
    this._status("Saving…");
    let res;
    try {
      res = await fetch("/api/notes", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, baseUpdatedAt: this.updatedAt, force: force || undefined }),
      });
    } catch (e) {
      this.inflight = false;
      this._retry(e.message || "offline");
      return;
    }
    this.inflight = false;
    if (res.status === 409) {
      let d = null;
      try { d = (await res.json()).detail; } catch { /* ignore */ }
      this._showConflict(d?.current ?? null);
      return;
    }
    if (!res.ok) {
      let why = `HTTP ${res.status}`;
      try { const j = await res.json(); if (typeof j.detail === "string") why = j.detail; } catch { /* ignore */ }
      if (res.status === 422) { this._status(`Not saved: ${why}`); return; }   // retrying cannot help
      this._retry(why);
      return;
    }
    const doc = await res.json();
    this.updatedAt = doc.updatedAt;
    this.serverText = doc.text;
    this.retries = 0;
    const changed = this.box.value !== text;
    if (changed || this.pendingAgain) {
      this.pendingAgain = false;
      this.dirty = true;
      this._saveNow();
      return;
    }
    this.dirty = false;
    lsDel(DRAFT_KEY);
    const d = new Date(doc.updatedAt);
    this._status(`Saved ✓ ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`);
  }

  _retry(why) {
    const wait = RETRY_MS[Math.min(this.retries, RETRY_MS.length - 1)];
    this.retries += 1;
    this._status(`Not saved: ${why}, retrying`);
    this.retryTimer = setTimeout(() => this._saveNow(), wait);
  }

  _showConflict(current) {
    this.conflict = current ?? { text: this.serverText, updatedAt: this.updatedAt };
    this.conf.hidden = false;
    this._status("Changed elsewhere. Choose which version to keep.");
  }

  _hideConflict() { this.conflict = null; this.conf.hidden = true; }

  _loadTheirs() {
    const c = this.conflict;
    if (!c) return;
    this.box.value = c.text;
    this.updatedAt = c.updatedAt;
    this.serverText = c.text;
    this.dirty = false;
    lsDel(DRAFT_KEY);
    this._hideConflict();
    this._status("Loaded the other version.");
  }

  _keepMine() {
    const c = this.conflict;
    if (!c) return;
    this.updatedAt = c.updatedAt;
    this._hideConflict();
    this._save(true);
  }

  /** Refresh from the server when there is no unsaved edit (text written on the phone shows up on the Mac). */
  async sync() {
    if (!this.box || this.dirty || this.inflight || this.conflict) return;
    let cur;
    try { cur = await this._get(); } catch { return; }
    if (this.dirty || this.inflight || cur.updatedAt === this.updatedAt) return;
    this.updatedAt = cur.updatedAt;
    this.serverText = cur.text;
    this.box.value = cur.text;
    this._status("Updated from the server.");
  }
}
