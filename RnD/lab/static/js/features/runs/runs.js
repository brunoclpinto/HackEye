// Runs: the run list, analysis start/follow/cancel, loading a run into every panel, the run badge and the audio-event refresh.
import { $, parseTime, fmtTime, toast, clamp } from "../../util/index.js";
import { setProgress } from "../../util/ui.js";
import { EtaTracker, runStartMs } from "../../util/eta.js";
import { api } from "../../api.js";
import { on, emit } from "../../bus.js";
import { S, video, recById, overlay, hazards, classesPanel, audio, sounds, worldmap, selection, timeline, reviews } from "../../state.js";

/** Which window a run looked at: "landscape" (the full frame, whatever the side) or "portrait-left" / "-center" / "-right". */
export function windowKey(r) {
  const o = r?.orientation ?? r?.request?.orientation ?? "landscape";
  return o === "portrait" ? `portrait-${r?.request?.side ?? r?.side}` : "landscape";
}

/** After Orientation / Camera side changed: save them, and open the done run of this range that was made with them (if any). */
async function windowChanged() {
  if (!S.rec) return;
  try { await emit("put-settings"); } catch { return; }
  if (!S.run) return;
  const want = $("#orientSel").value === "portrait" ? `portrait-${$("#sideSel").value}` : "landscape";
  if (windowKey(S.run) === want) return;
  const q = S.run.request;
  const match = S.runs.find((r) => r.status === "done" && windowKey(r) === want
    && r.request.start === q.start && r.request.end === q.end && r.request.fps === q.fps && r.request.profile === $("#profileSel").value
    && r.request.model === q.model && runDepth(r) === runDepth(S.run));
  if (match) loadRun(match.id, { t: video.currentTime });
}

async function loadRuns() {
  try { S.runs = await api(`/api/runs?recording=${encodeURIComponent(S.rec.id)}`); } catch { S.runs = []; }
  renderRuns();
}

export const DEPTH_LABELS = { "da3-small": "DA3 Small", "da3-base": "DA3 Base", "da2-metric-outdoor-small": "DA2 Metric Outdoor S", "unidepth-v2-s": "UniDepth v2 S" };

/** The depth model of a run, or null (older runs have no field; "none" counts as none). */
export function runDepth(r) {
  const d = r?.depth ?? r?.request?.depth;
  return d && d !== "none" ? d : null;
}

/** "portrait · left" (older runs have no field: full-frame landscape). */
export function runOrientation(r) {
  const o = r?.orientation ?? r?.request?.orientation ?? "landscape";
  const side = r?.request?.side ?? r?.side;
  return side ? `${o} · ${side}` : o;
}

export function runLabel(r) {
  const q = r.request;
  return `${fmtTime(q.start)} – ${fmtTime(q.end)} · ${runOrientation(r)} · ${q.fps} fps${r.inputSpec ? ` · ${r.inputSpec.w}×${r.inputSpec.h}` : ""}${runDepth(r) ? ` · ${runDepth(r)}` : ""}`;
}

// Resolution select: "576p · 1024×576" from the selected recording; options it can't do (would upscale) are disabled.
export function labelResolutions() {
  const sizes = ($("#orientSel").value === "portrait" ? S.rec?.inputSizesPortrait : S.rec?.inputSizes) ?? {};
  for (const o of $("#profileSel").options) {
    const sz = sizes[o.value];
    o.textContent = (sz ? `${o.value} · ${sz[0]}×${sz[1]}` : o.value) + (o.value === "736p" ? " (default)" : "");
    o.disabled = !!S.rec && !sz;
  }
  const sel = $("#profileSel");
  if (sel.selectedOptions[0]?.disabled) sel.value = Object.keys(sizes)[0] ?? sel.value;
}
function renderRuns() {
  const ul = $("#runList");
  ul.replaceChildren();
  if (!S.runs.length) { ul.innerHTML = '<li class="sub">No runs for this recording</li>'; return; }
  S.openRuns ??= new Set();
  for (const r of S.runs) {
    // v26.2.10: each run is a collapsible group: the header is the run as it was shown, its collisions are rows inside
    const li = document.createElement("li");
    li.className = "run-group" + (S.run?.id === r.id ? " sel" : "");
    li.dataset.run = r.id;
    li.dataset.orientation = runOrientation(r);
    const det = document.createElement("details");
    det.open = S.openRuns.has(r.id);
    const head = document.createElement("summary");
    head.className = "run-head clickable";
    head.innerHTML = '<div class="t"></div><div class="sub"></div>';
    head.firstChild.textContent = runLabel(r);
    const tag = document.createElement("span");
    tag.className = `tag ${r.status}`;
    tag.textContent = S.eta?.id === r.id && isActive(r) ? S.eta.text : r.status;
    head.firstChild.append(tag);
    head.lastChild.textContent = [r.modelName + (r.device === "cpu" ? " · CPU" : ""), r.request.profile, runDepth(r) ? `depth ${runDepth(r)}` : null, r.createdAt?.replace("T", " ").replace("Z", "")].filter(Boolean).join(" · ");
    head.addEventListener("click", (e) => {         // the loaded run's header just folds; any other run is loaded (and shown open)
      if (S.run?.id === r.id && r.status === "done") return;
      e.preventDefault();
      openRun(r);
    });
    det.addEventListener("toggle", () => {
      if (det.open) S.openRuns.add(r.id); else S.openRuns.delete(r.id);
      if (det.open && r.status === "done" && S.run?.id !== r.id && !S.runColls?.[r.id]) emit("load-run-colls", r.id);
    });
    const rows = document.createElement("ul");
    rows.className = "coll-rows";
    for (const d of emit("colls-of", r.id)) rows.append(emit("coll-row", r.id, d));
    det.append(head, rows);
    li.append(det);
    ul.append(li);
  }
}

/** "running 42% · about 3 min left" for an active run; one EtaTracker per run id, fed by every poll. */
function progressLabel(r) {
  if (!S.eta || S.eta.id !== r.id) S.eta = { id: r.id, tracker: new EtaTracker(runStartMs(r)) };
  const text = S.eta.text = S.eta.tracker.label(r);
  for (const tag of document.querySelectorAll(`#runList li.run-group[data-run="${r.id}"] .run-head .tag`)) tag.textContent = text; // runs list shows it too
  return text;
}

export const isActive = (r) => r.status === "queued" || r.status === "running";

/** Analyse is disabled (with the reason) and Cancel shown while `run` is in flight for this recording. */
function setBusy(run, label) {
  const a = $("#analyseBtn"), c = $("#cancelBtn");
  c.hidden = !run;
  c.dataset.run = run?.id ?? "";
  a.disabled = !S.rec || !!run;
  a.title = run ? `An analysis is already ${run.status} for this recording (run ${run.id}, ${label ?? `${Math.round((run.progress || 0) * 100)}%`})` : "";
}

/** If this recording has a queued/running run (even one started elsewhere), follow it. */
function watchActiveRun() {
  const act = S.runs.find(isActive);
  if (act) watchRun(act.id);
}

async function cancelAnalysis() {
  const id = $("#cancelBtn").dataset.run;
  if (!id) return;
  $("#cancelBtn").disabled = true;
  try { await api(`/api/runs/${id}/cancel`, { method: "POST" }); } catch { /* toasted */ }
  $("#cancelBtn").disabled = false;
  watchRun(id);
}

function openRun(r) {
  $("#reusedNote").hidden = true;
  if (r.status === "done") loadRun(r.id);
  else if (r.status === "cancelled") toast("This run was cancelled");
  else if (r.status === "error") toast(`Run failed: ${r.error ?? "unknown"}`);
  else watchRun(r.id);
}

async function startAnalysis() {
  if (!S.rec) return;
  const dur = S.rec.duration;
  let start = parseTime($("#rangeStart").value);
  let end = parseTime($("#rangeEnd").value);
  if (Number.isNaN(start)) start = 0;
  if (Number.isNaN(end)) end = dur;
  start = clamp(start, 0, dur); end = Math.min(end, dur);
  if (!(end > start)) { toast("Range end must be after range start (and within the recording)."); return; }
  const fps = Number($("#fpsInput").value) || 6;
  const body = { recording: S.rec.id, start, end, model: $("#modelSel").value, profile: $("#profileSel").value || "default", fps,
    orientation: $("#orientSel").value, side: $("#sideSel").value };
  if ($("#depthSel").value && $("#depthSel").value !== "none") body.depth = $("#depthSel").value;
  body.device = $("#deviceSel").value;
  await submitAnalysis(body, false);
}

/** POST the run request. A finished run with the same settings comes back `reused`: say so and offer Re-analyse (force). */
async function submitAnalysis(body, force) {
  const note = $("#reusedNote");
  note.hidden = true;
  $("#analyseBtn").disabled = true;
  let follow = null;
  try {
    await emit("put-settings"); // the post-inference collision pass uses the stored settings
    const run = await api("/api/runs", { method: "POST", body: force ? { ...body, force: true } : body });
    await loadRuns();
    if (run.reused) {
      const when = (run.finishedAt || run.createdAt || "").replace("T", " ").replace("Z", "");
      note.firstChild.textContent = `This range was already analysed with these settings (finished ${when}, collision ${run.collisionVersion ?? "?"}, ${(run.device || "gpu").toUpperCase()}). Loaded it. `;
      note.reanalyse = () => submitAnalysis(body, true);
      note.hidden = false;
      loadRun(run.id);
    } else if (isActive(run)) {
      follow = run;
    } else if (run.status === "done") {
      loadRun(run.id);
    }
  } catch {
    // e.g. 409: another analysis of this recording is already in flight; follow it.
    await loadRuns();
    watchActiveRun();
  }
  if (follow) {
    const pr = $("#runProgress");
    pr.hidden = false;
    setProgress(pr, follow.progress || 0, progressLabel(follow));
    setBusy(follow);
    watchRun(follow.id);
  } else if (!S.runs.some(isActive)) {
    $("#analyseBtn").disabled = !S.rec;
  }
}

/** Poll a run once a second, driving the progress bar; load it when done. */
function watchRun(runId) {
  clearTimeout(S.runPoll);
  const pr = $("#runProgress");
  const poll = async () => {
    let r;
    try { r = await api(`/api/runs/${runId}`, { quiet: true }); }
    catch (e) { toast(`Run poll: ${e.message}`); pr.hidden = true; setBusy(null); return; }
    if (S.rec && r.request.recording !== S.rec.id) return; // user moved on to another recording
    if (r.status === "done") {
      pr.hidden = true; setBusy(null);
      await loadRuns(); loadRun(runId); return;
    }
    if (r.status === "error") {
      pr.hidden = true; setBusy(null);
      toast(`Analysis failed: ${r.error ?? "unknown error"}`); loadRuns(); return;
    }
    if (r.status === "cancelled") {
      pr.hidden = true; setBusy(null);
      toast("Analysis cancelled"); loadRuns(); return;
    }
    pr.hidden = false;
    const label = progressLabel(r);
    setProgress(pr, r.progress || 0, label);
    setBusy(r, label);
    S.runPoll = setTimeout(poll, 1000);
  };
  poll();
}

/** The overlay's Depth toggle only works for runs that have depth maps. */
function setDepthAvailable(on) {
  const chk = $("#depthChk");
  overlay.hasDepth = on;
  chk.disabled = !on;
  chk.title = on ? "" : "This run has no depth maps (analyse with a depth model)";
  if (!on) { chk.checked = false; overlay.layers.depth = false; }
}

function unloadRun() {
  S.run = null; S.colls = []; S.runColls = {}; S.cid = null; S.events = []; S.speech = []; S.tones = []; S.notes = [];
  sounds.runChanged();
  hazards.setRun(null);
  overlay.setRun(null);
  classesPanel.setRun(null);
  worldmap.setRun(null);
  audio.setEvents([]);
  timeline.set(null, []);
  reviews.setRun(null, []);
  $("#runBadge").textContent = "";
  $("#rerunBtn").disabled = true;
  setDepthAvailable(false);
  emit("render-coll");
  emit("render-compare");
}

/** Show collision run `cid` of an analysis run (null: it has none). Returns the run object the panels got (with collisionId / collisionVersion). */
async function loadRunData(run0, cid) {
  const d = S.colls.find((c) => c.id === cid);
  const run = { ...run0, collisionId: cid ?? null, collisionVersion: d?.collisionVersion ?? run0.collisionVersion };
  const events = cid ? await api(`/api/runs/${run.id}/events.json?collision=${encodeURIComponent(cid)}`) : { events: [] };
  selection.clear();
  S.events = events.events ?? [];
  S.speech = S.events.filter((e) => e.type === "speech");
  S.tones = S.events.filter((e) => e.type === "tone");
  // Notifications (CONTRACTS §14): speech phrases and beeps episodes; runs without `beeps` events just show speech.
  S.notes = S.events.filter((e) => e.type === "speech" || e.type === "beeps").sort((a, b) => a.t - b.t);
  // Only the window around the playhead is fetched (never the whole hazards.json); it streams in behind the UI.
  hazards.setRun(run);
  overlay.setRun(run);
  classesPanel.setRun(run);
  worldmap.setRun(run);
  setDepthAvailable(!!runDepth(run));
  hazards.update(playheadForRun(run));
  audio.setEvents(S.events);
  refreshAudioEvents();
  timeline.set(run, S.events);
  reviews.setRun(run, S.notes, S.tones);
  return run;
}

/** Where the playhead will be once this run is shown (a pending seek wins, then the current time, clamped into the run). */
function playheadForRun(run) {
  const t = S.pendingSeek ?? (video.currentTime || 0);
  return clamp(t, run.request.start, run.request.end);
}

/**
 * System events + (with "Hear review edits") the user's added phrases and beeps, minus the ⊘ removed
 * phrases and the tones of ⊘ removed beeps episodes.
 */
function refreshAudioEvents() {
  const preview = $("#reviewPreviewChk").checked;
  let speech = S.speech, tones = S.tones;
  if (preview) {
    speech = [...speech.filter((e) => !reviews.isRemoved(e)), ...reviews.addedEvents()];
    const silenced = reviews.silencedBeeps();
    if (silenced.length) {
      const EPS = 0.05;
      tones = tones.filter((e) => !silenced.some((b) => e.t >= b.t - EPS && e.t <= (b.tEnd ?? b.t) + EPS
        && (b.trackId === undefined || e.trackId === undefined || b.trackId === e.trackId)));
    }
    tones = [...tones, ...reviews.addedTones()];
  }
  audio.setSpeechEvents(speech);
  audio.setToneEvents(tones);
}

function applyRunMeta() {
  sounds.runChanged();
  const r = S.run;
  if (!r) return;
  $("#runBadge").textContent = `run ${r.id}${r.collisionId ? ` · ${r.collisionId}` : ""} · ${runLabel(r)} · ${r.frameCount} frames · ${r.modelName ?? ""}${r.device === "cpu" ? " · CPU" : ""}${r.msPerFrame ? ` · ${Math.round(r.msPerFrame)} ms/frame` : ""} · collision ${r.collisionVersion ?? "?"}${r.collisionId ? "" : " (none)"}${runDepth(r) ? ` · depth ${runDepth(r)}${r.depthMsPerFrame ? ` ${Math.round(r.depthMsPerFrame)} ms/frame` : ""}` : ""}${r.motionFrames ? "" : " · no motion track"}`;
}

export async function loadRun(runId, { seek = true, t } = {}) {
  let run;
  try { run = await api(`/api/runs/${runId}`); } catch { return; }
  if (run.status !== "done") { watchRun(runId); return; }
  if (S.rec?.id !== run.request.recording) {
    if (!recById(run.request.recording)) await emit("refresh-recordings");
    await emit("select-recording", run.request.recording, { keepRun: true });
  }
  const gen = S.seekGen; // the user may scrub while the run loads; don't yank them back afterwards
  S.run = run;               // the collision list below needs S.run.id
  S.runColls = {};
  (S.openRuns ??= new Set()).add(run.id);
  await emit("refresh-collisions");
  const cid = emit("pick-collision", run.id);
  S.cid = cid;
  try { S.run = await loadRunData(run, cid); } catch { S.run = null; return; }
  applyRunMeta();
  emit("render-coll");
  emit("reset-compare-defaults");
  emit("render-compare");
  emit("resume-collision-job");
  S.rangeTouched = true; // keep the user's run range, don't auto-sync to playhead
  $("#rangeStart").value = fmtTime(run.request.start);
  $("#rangeEnd").value = fmtTime(run.request.end);
  $("#orientSel").value = run.orientation ?? run.request.orientation ?? "landscape";
  if (run.request.side && run.orientation === "portrait") $("#sideSel").value = run.request.side;
  labelResolutions();
  if ([...$("#profileSel").options].some((o) => o.value === run.request.profile)) $("#profileSel").value = run.request.profile;
  $("#depthSel").value = [...$("#depthSel").options].some((o) => o.value === runDepth(run)) ? runDepth(run) : "none";
  renderRuns();
  if (seek && gen === S.seekGen) emit("seek", t ?? run.request.start);
  else hazards.update(video.currentTime || 0);
  emit("write-hash");
}

export function wire() {
  on("load-runs", loadRuns);
  on("watch-active-run", watchActiveRun);
  on("set-busy", setBusy);
  on("unload-run", unloadRun);
  on("label-resolutions", labelResolutions);
  on("render-runs", renderRuns);
  on("load-run", loadRun);
  on("load-run-data", loadRunData);
  on("apply-run-meta", applyRunMeta);
  on("audio-events-changed", refreshAudioEvents);
  // Orientation / camera side pick the run's window: show the resolutions of the window, and load the matching run when there is one.
  for (const id of ["#orientSel", "#sideSel"]) $(id).addEventListener("change", () => { labelResolutions(); windowChanged(); });
  $("#distSel").addEventListener("change", () => { // A/B in one click: the re-run button lights up for runs with depth maps
    if (!S.run || !runDepth(S.run)) return;
    $("#rerunBtn").classList.add("primary");
    $("#rerunInfo").textContent = "Distance source changed: click Re-run collision to compare.";
  });
  $("#analyseBtn").addEventListener("click", startAnalysis);
  $("#reanalyseBtn").addEventListener("click", () => $("#reusedNote").reanalyse?.());
  $("#cancelBtn").addEventListener("click", cancelAnalysis);
}
