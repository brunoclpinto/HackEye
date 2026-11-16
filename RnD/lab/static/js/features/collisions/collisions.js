// Collisions: the re-run job (start, follow, resume, cancel), the collision rows of a run, selection, labels, delete and the A/B compare.
import { $, fmtTime, toast } from "../../util/index.js";
import { setProgress } from "../../util/ui.js";
import { api } from "../../api.js";
import { on, emit } from "../../bus.js";
import { S, video, hazards } from "../../state.js";
import { lsKey, collTags, collSummary, collText } from "./summary.js";

export async function rerunCollision() {
  if (!S.run || !S.rec) return false;
  const btn = $("#rerunBtn"), info = $("#rerunInfo");
  const overrides = emit("all-overrides");
  if (overrides === null) return false;
  btn.disabled = true; info.textContent = "Running…";
  const t0 = performance.now();
  try {
    await emit("put-settings");
    let r;
    try { r = await api(`/api/runs/${S.run.id}/collision`, { method: "POST", body: overrides ? { overrides } : {}, quiet: true }); }
    catch (e) {
      if (overrides) { $("#collOvErr").textContent = e.message; $("#collOvErr").hidden = false; }
      else toast(`Re-run collision: ${e.message}`);
      throw e;
    }
    const runId = S.run.id;
    await refreshCollisions();
    emit("render-runs");
    const d = await followCollisionJob(runId, r.id);       // v26.2.10: a background job; the row shows progress + Cancel
    if (!d) { info.textContent = `${r.id} · cancelled`; return false; }
    if (d.status === "error") { toast(`Re-run collision: ${d.error ?? "failed"}`); throw new Error(d.error); }
    if (S.run?.id !== runId) return false;                // the user moved to another run meanwhile
    await selectCollision(r.id, { force: true });
    const ms = performance.now() - t0;
    const fmt = (v) => (v < 1000 ? Math.round(v) + " ms" : (v / 1000).toFixed(2) + " s");
    const compute = d.elapsedSeconds != null ? `${fmt(d.elapsedSeconds * 1000)} compute, ` : "";
    $("#rerunBtn").classList.remove("primary");
    info.textContent = `${r.id} · Collision ${d.collisionVersion ?? ""} re-run: ${compute}${fmt(ms)} total · ${S.events.filter((e) => e.type === "speech").length} speech events · ${S.events.filter((e) => e.type === "beeps").length} beeps`;
    return true;
  } catch { if (!/cancelled/.test(info.textContent)) info.textContent = "Failed (see error)"; return false; }
  finally { btn.disabled = !S.run; }
}

/** Poll the run's collisions once a second while `cid` runs (progress in its row). Resolves with its final doc, or null when it was
 *  cancelled (its row is gone). One poller per run: a second caller shares it. */
function followCollisionJob(runId, cid) {
  S.collFollow ??= {};
  const key = `${runId}/${cid}`;
  if (S.collFollow[key]) return S.collFollow[key];
  S.collFollow[key] = new Promise((resolve) => {
    const poll = async () => {
      if (S.run?.id !== runId) { delete S.collFollow[key]; resolve(null); return; }
      await refreshCollisions();
      const d = S.colls.find((c) => c.id === cid);
      if (!d || d.status !== "running") {
        delete S.collFollow[key];
        renderColl();
        resolve(d ?? null);
        return;
      }
      if (!document.activeElement?.closest?.("#runList")) emit("render-runs");     // not while a label is being typed
      else updateCollProgress();
      setTimeout(poll, 1000);
    };
    poll();
  });
  return S.collFollow[key];
}

/** If the open run has a collision job in flight (e.g. started before a reload), follow it. */
function resumeCollisionJob() {
  const d = S.colls.find((c) => c.status === "running");
  $("#rerunBtn").disabled = !S.run || !!d;
  if (d) followCollisionJob(S.run.id, d.id).then(() => { $("#rerunBtn").disabled = !S.run; });
}

async function cancelCollisionJob(cid) {
  if (!S.run) return;
  try { await api(`/api/runs/${S.run.id}/collisions/${cid}/cancel`, { method: "POST", quiet: true }); }
  catch (e) { toast(`Cancel ${cid}: ${e.message}`); }
  await refreshCollisions();
  renderColl();
}

function updateCollProgress() {
  for (const d of S.colls) {
    const el = document.querySelector(`#runList .coll-row[data-run="${S.run.id}"][data-cid="${d.id}"] .progress`);
    if (el && d.status === "running") setProgress(el, d.progress || 0, `${Math.round((d.progress || 0) * 100)}%`);
  }
}

async function refreshCollisions() {
  try { S.colls = await api(`/api/runs/${S.run.id}/collisions`, { quiet: true }); } catch { S.colls = []; }
}

/** The collision run to show for a run: the remembered one (localStorage), else the latest finished one. */
function pickCollision(runId) {
  let want = null;
  try { want = localStorage.getItem(lsKey(runId)); } catch { /* storage blocked */ }
  const done = S.colls.filter((c) => (c.status ?? "done") === "done");
  return done.some((c) => c.id === want) ? want : (done.at(-1)?.id ?? null);
}

/** The runs list shows the collisions (rows inside each run's group); the Compare pickers take the same finished rows. */
function renderColl() {
  emit("render-runs");
  const done = S.colls.filter((c) => (c.status ?? "done") === "done");
  for (const id of ["#cmpA", "#cmpB"]) {
    const el = $(id), keep = el.value;
    el.replaceChildren(...done.map((d) => new Option(collText(d, S.colls[0]), d.id)));
    if (done.some((c) => c.id === keep)) el.value = keep;
  }
}

/** Compare defaults: B = the selected collision run, A = the one before it. */
function resetCompareDefaults() {
  const done = S.colls.filter((c) => (c.status ?? "done") === "done");
  const i = done.findIndex((c) => c.id === S.cid);
  if (i < 0) return;
  $("#cmpB").value = S.cid;
  $("#cmpA").value = done[i > 0 ? i - 1 : Math.min(1, done.length - 1)]?.id ?? S.cid;
}

async function selectCollision(cid, { force = false } = {}) {
  if (!S.run) return;
  if (cid === S.cid && !force) { renderColl(); return; }
  S.cid = cid || null;
  try { if (cid) localStorage.setItem(lsKey(S.run.id), cid); } catch { /* storage blocked */ }
  try { S.run = await emit("load-run-data", S.run, S.cid); } catch { /* toasted */ }
  emit("apply-run-meta");
  renderColl();
  resetCompareDefaults();
  renderCompare();
  hazards.update(video.currentTime || 0);
}

async function saveCollLabel(runId, d, input) {
  const label = input.value.trim();
  if (label === (d.label ?? "")) return;
  try {
    Object.assign(d, await api(`/api/runs/${runId}/collisions/${d.id}`, { method: "PATCH", body: { label } }));
    renderColl();
    renderCompare();
  } catch { /* toasted */ }
}

async function deleteColl(runId, d) {
  if (!window.confirm(`Delete collision run ${d.id}${d.label ? ` (${d.label})` : ""}? Its events, hazards and world map are removed.`)) return;
  try { await api(`/api/runs/${runId}/collisions/${d.id}`, { method: "DELETE", quiet: true }); }
  catch (e) { toast(`Delete ${d.id}: ${e.message}`); return; }
  if (S.run?.id === runId) {
    const wasSel = S.cid === d.id;
    await refreshCollisions();
    if (wasSel) {
      try { localStorage.removeItem(lsKey(runId)); } catch { /* storage blocked */ }
      S.cid = null;
      await selectCollision(pickCollision(runId), { force: true });
    } else renderColl();
  } else {
    delete S.runColls?.[runId];
    await loadRunColls(runId);
  }
}

/** Collisions of a run that is not the open one (loaded when its group is opened). */
async function loadRunColls(runId) {
  S.runColls ??= {};
  try { S.runColls[runId] = await api(`/api/runs/${runId}/collisions`, { quiet: true }); } catch { S.runColls[runId] = []; }
  emit("render-runs");
}

const collsOf = (runId) => (S.run?.id === runId ? S.colls : S.runColls?.[runId] ?? []);

/** Open a collision row: the same run switches collision run, another run is loaded showing it. */
async function openCollRow(runId, d) {
  if ((d.status ?? "done") !== "done") return;
  if (S.run?.id === runId) { await selectCollision(d.id); return; }
  try { localStorage.setItem(lsKey(runId), d.id); } catch { /* storage blocked */ }
  await emit("load-run", runId);
}

function pickCompare(which, cid) {
  const box = $("#secCompare");
  box.open = true;
  $(which).value = cid;
  renderCompare();
}

function collRow(runId, d) {
  const li = document.createElement("li");
  li.className = "coll-row" + (S.run?.id === runId && S.cid === d.id ? " sel" : "");
  li.dataset.run = runId; li.dataset.cid = d.id;
  const status = d.status ?? "done";
  const top = document.createElement("div");
  top.className = "coll-top";
  const id = document.createElement("b"); id.textContent = d.id;
  const label = document.createElement("input");
  label.className = "coll-label"; label.maxLength = 60; label.placeholder = collSummary(d, S.colls[0]); label.value = d.label ?? "";
  label.autocomplete = "off"; label.setAttribute("aria-label", `Label of ${d.id}`);
  label.addEventListener("click", (e) => e.stopPropagation());
  label.addEventListener("change", () => saveCollLabel(runId, d, label));
  label.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") label.blur(); });
  const tag = document.createElement("span"); tag.className = `tag ${status}`; tag.textContent = status === "error" ? "error" : status;
  if (status === "error" && d.error) tag.title = d.error;
  top.append(id, label, tag);
  const sub = document.createElement("div");
  sub.className = "sub";
  const c = d.counts ?? {};
  sub.textContent = [`collision ${d.collisionVersion ?? "?"}`, d.worldmapVersion ? `map ${d.worldmapVersion}` : null,
    status === "done" ? `${c.speech ?? 0} speech · ${c.beeps ?? 0} beeps` : null, collSummary(d, S.colls[0])].filter(Boolean).join(" · ");
  li.append(top, sub);
  const tags = collTags(d);
  if (tags.length) {
    const box = document.createElement("div");
    box.className = "coll-tags";
    for (const t of tags) { const sp = document.createElement("span"); sp.className = "coll-ovtag"; sp.dataset.tag = t.k; sp.textContent = t.text; box.append(sp); }
    li.append(box);
  }
  if (status === "running") {
    const pr = document.createElement("div");
    pr.className = "progress";
    pr.innerHTML = "<div></div><span></span>";
    setProgress(pr, d.progress || 0, `${Math.round((d.progress || 0) * 100)}%`);
    const cancel = document.createElement("button");
    cancel.type = "button"; cancel.className = "coll-cancel"; cancel.textContent = "Cancel";
    cancel.addEventListener("click", (e) => { e.stopPropagation(); cancelCollisionJob(d.id); });
    li.append(pr, cancel);
  } else {
    const bar = document.createElement("div");
    bar.className = "coll-btns";
    if (status === "done") {
      for (const w of ["A", "B"]) {
        const b = document.createElement("button");
        b.type = "button"; b.className = `coll-pick coll-${w}`; b.textContent = w; b.title = `Use ${d.id} as ${w} in Compare collision runs`;
        b.addEventListener("click", (e) => { e.stopPropagation(); if (S.run?.id === runId) pickCompare(`#cmp${w}`, d.id); });
        bar.append(b);
      }
    }
    const del = document.createElement("button");
    del.type = "button"; del.className = "coll-del"; del.textContent = "Delete";
    del.title = "Delete this collision run (not the only one, not one with reviews)";
    del.disabled = collsOf(runId).length < 2 && status !== "error";
    del.addEventListener("click", (e) => { e.stopPropagation(); deleteColl(runId, d); });
    bar.append(del);
    li.append(bar);
  }
  if (status === "done") { li.classList.add("clickable"); li.addEventListener("click", () => openCollRow(runId, d)); }
  return li;
}

// ---- compare A / B
let cmpToken = 0;      // only the latest compare request renders (re-run, select and label save can each ask for one)
async function renderCompare() {
  const box = $("#secCompare"), out = $("#cmpOut"), msg = $("#cmpMsg");
  if (!box.open) return;
  const token = ++cmpToken;
  out.replaceChildren();
  if (!S.run || S.colls.filter((c) => (c.status ?? "done") === "done").length < 2) { msg.textContent = S.run ? "This run has one collision run; re-run collision to compare." : "Open a run first."; return; }
  const a = $("#cmpA").value, b = $("#cmpB").value, runId = S.run.id;
  if (!a || !b || a === b) { msg.textContent = "Pick two different collision runs."; return; }
  msg.textContent = "Comparing…";
  let c;
  try { c = await api(`/api/runs/${runId}/collisions/compare?a=${a}&b=${b}`, { quiet: true }); }
  catch (e) { if (token === cmpToken) msg.textContent = `Compare failed: ${e.message}`; return; }
  if (token !== cmpToken || S.run?.id !== runId || $("#cmpA").value !== a || $("#cmpB").value !== b) return;     // superseded
  msg.textContent = "";
  out.replaceChildren();
  const mk = (tag, cls, text) => { const x = document.createElement(tag); if (cls) x.className = cls; if (text !== undefined) x.textContent = text; return x; };
  const val = (v) => (v === undefined || v === null ? "–" : typeof v === "object" ? JSON.stringify(v) : String(v));
  // settings table
  out.append(mk("div", "cmp-sub", `Settings that differ (${c.settings.length})`));
  const wrap = mk("div", "cmp-scroll"), tbl = mk("table", "cmp-table");
  tbl.id = "cmpSettings";
  const head = tbl.createTHead().insertRow();
  for (const h of ["key", c.a, c.b]) head.append(mk("th", "", h));
  const body = tbl.createTBody();
  for (const r of c.settings) { const tr = body.insertRow(); tr.dataset.key = r.key; for (const x of [r.key, val(r.a), val(r.b)]) tr.insertCell().textContent = x; }
  if (!c.settings.length) body.insertRow().insertCell().textContent = "no differing setting";
  wrap.append(tbl); out.append(wrap);
  // counts
  const cnt = (x) => `${x.speech ?? 0} speech · ${x.beeps ?? 0} beeps`;
  out.append(mk("div", "cmp-sub", `Counts: ${c.a} ${cnt(c.counts.a)} | ${c.b} ${cnt(c.counts.b)}`));
  // event lists
  const ev = c.events;
  const evText = (e) => `${e.type === "beeps" ? "🔔 " : ""}${e.text}`;
  const list = (title, rows, line) => {
    const d = document.createElement("details");
    d.className = "cmp-group"; d.open = rows.length > 0 && rows.length <= 40;
    d.append(mk("summary", "", `${title} (${rows.length})`));
    const ul = mk("ul", "cmp-list");
    for (const r of rows) {
      const li = document.createElement("li"), btn = mk("button", "", "");
      btn.type = "button";
      const t = r.t ?? r.a?.t;
      btn.append(mk("span", "cmp-t mono", fmtTime(t, 1)), mk("span", "cmp-x", line(r)));
      btn.addEventListener("click", () => emit("seek", t));
      li.append(btn); ul.append(li);
    }
    d.append(ul); return d;
  };
  const g = (id, node) => { node.id = id; out.append(node); };
  g("cmpChanged", list("Changed", ev.changed, (r) => `${c.a}: ${evText(r.a)}  →  ${c.b}: ${evText(r.b)}`));
  g("cmpOnlyA", list(`Only ${c.a}`, ev.onlyA, evText));
  g("cmpOnlyB", list(`Only ${c.b}`, ev.onlyB, evText));
  out.append(mk("p", "hint", `${ev.same} the same`));
  out.lastChild.id = "cmpSame";
}

export function wire() {
  on("refresh-collisions", refreshCollisions);
  on("pick-collision", pickCollision);
  on("render-coll", renderColl);
  on("render-compare", renderCompare);
  on("reset-compare-defaults", resetCompareDefaults);
  on("load-run-colls", loadRunColls);
  on("colls-of", collsOf);
  on("coll-row", collRow);
  on("resume-collision-job", resumeCollisionJob);
  $("#rerunBtn").addEventListener("click", rerunCollision);
  $("#secCompare").addEventListener("toggle", renderCompare);
  $("#cmpA").addEventListener("change", renderCompare);
  $("#cmpB").addEventListener("change", renderCompare);
}
