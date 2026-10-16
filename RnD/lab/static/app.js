// HackEye Lab frontend: state + wiring. Heavy lifting lives in js/*.js.
import { $, parseTime, fmtTime, toast, clamp, lastAtOrBefore, ROLES, ROLE_COLOR, eventRole, eventColor } from "./js/util.js";
import { api } from "./js/api.js";
import { Overlay } from "./js/overlay.js";
import { AudioEngine } from "./js/audio.js";
import { Timeline } from "./js/timeline.js";

const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
const video = $("#video");

const S = {
  recs: [], rec: null, settings: null, config: null, models: null,
  runs: [], run: null, hazards: null, events: [], speech: [], shown: [], roles: new Set(ROLES),
  pendingSeek: null, rangeTouched: false, runPoll: null, recPoll: null, loadedVideoRec: null,
};

const overlay = new Overlay(video, $("#overlay"));
overlay.hudEl = $("#hud");
const audio = new AudioEngine(video);
const timeline = new Timeline($("#timeline"), (t) => seekTo(t));

// ---------------------------------------------------------------- helpers
const recById = (id) => S.recs.find((r) => r.id === id);
const durOf = () => S.rec?.duration ?? video.duration ?? 0;
const isNarrow = () => window.matchMedia("(max-width: 899px)").matches;

function seekTo(t) {
  t = clamp(t, 0, durOf() || t);
  if (video.readyState >= 1) video.currentTime = t;
  else S.pendingSeek = t; // applied on loadedmetadata
}

function setProgress(el, frac, text) {
  el.hidden = false;
  el.firstElementChild.style.width = `${clamp(frac, 0, 1) * 100}%`;
  el.lastElementChild.textContent = text ?? `${Math.round(frac * 100)}%`;
}

// ---------------------------------------------------------------- URL hash
function writeHash() {
  const p = [];
  if (S.rec) p.push(`rec=${encodeURIComponent(S.rec.id)}`);
  if (S.run) p.push(`run=${S.run.id}`);
  if (S.rec && Number.isFinite(video.currentTime)) p.push(`t=${(S.pendingSeek ?? video.currentTime).toFixed(1)}`);
  try { history.replaceState(null, "", `#${p.join("&")}`); } catch { /* ignore */ }
}
const readHash = () => Object.fromEntries(new URLSearchParams(location.hash.slice(1)));

// ---------------------------------------------------------------- library
function renderLibrary() {
  const ul = $("#recList");
  ul.replaceChildren();
  if (!S.recs.length) { ul.innerHTML = '<li class="sub">No recordings found in /media</li>'; return; }
  for (const r of S.recs) {
    const li = document.createElement("li");
    li.className = "clickable" + (S.rec?.id === r.id ? " sel" : "");
    const px = r.proxy || { status: "missing" };
    li.innerHTML = `<div class="t"></div><div class="sub"></div>`;
    li.firstChild.textContent = r.name;
    const tag = document.createElement("span");
    tag.className = `tag ${px.status}`;
    tag.textContent = px.status === "ready" ? "proxy ready" : px.status === "missing" ? "no proxy" : px.status;
    li.firstChild.append(tag);
    li.lastChild.textContent = `${fmtTime(r.duration)} · ${r.width}×${r.height} · ${(+r.fps).toFixed(2)} fps · ${r.chapters.length} ch`;
    if (px.status === "building") {
      const pr = document.createElement("div");
      pr.className = "progress";
      pr.innerHTML = "<div></div><span></span>";
      li.append(pr);
      setProgress(pr, px.progress || 0);
    }
    if (px.status === "missing" || px.status === "error") {
      if (px.error) { const e = document.createElement("div"); e.className = "sub"; e.textContent = px.error; li.append(e); }
      const b = document.createElement("button");
      b.textContent = px.status === "error" ? "Retry build proxy" : "Build proxy";
      b.addEventListener("click", (ev) => { ev.stopPropagation(); buildProxy(r.id); });
      li.append(b);
    }
    li.addEventListener("click", () => selectRecording(r.id));
    ul.append(li);
  }
}

async function refreshRecordings() {
  S.recs = await api("/api/recordings", { quiet: true }).catch((e) => { toast(`Recordings: ${e.message}`); return S.recs; });
  renderLibrary();
  // Selected recording just became ready -> attach the video.
  if (S.rec) {
    S.rec = recById(S.rec.id) ?? S.rec;
    if (S.rec.proxy?.status === "ready" && S.loadedVideoRec !== S.rec.id) attachVideo();
    else updateStageMsg();
  }
  const building = S.recs.some((r) => r.proxy?.status === "building");
  clearTimeout(S.recPoll);
  if (building) S.recPoll = setTimeout(refreshRecordings, 2000);
}

async function buildProxy(id) {
  try { await api(`/api/recordings/${encodeURIComponent(id)}/proxy`, { method: "POST" }); } catch { return; }
  refreshRecordings();
}

function updateStageMsg() {
  const msg = $("#stageMsg");
  const px = S.rec?.proxy;
  if (!S.rec) msg.textContent = "Select a recording";
  else if (!px || px.status !== "ready") {
    msg.textContent = px?.status === "building" ? `Building proxy… ${Math.round((px.progress || 0) * 100)}%`
      : px?.status === "error" ? `Proxy failed: ${px.error ?? "unknown error"}` : "No browser proxy yet — press “Build proxy” in the library";
  } else msg.textContent = "";
}

function attachVideo() {
  const id = S.rec.id;
  S.loadedVideoRec = id;
  video.src = `/media/${encodeURIComponent(id)}.mp4`;
  video.load();
  updateStageMsg();
}

async function selectRecording(id, { keepRun = false } = {}) {
  const rec = recById(id);
  if (!rec) { toast(`Unknown recording ${id}`); return; }
  const changed = S.rec?.id !== id;
  S.rec = rec;
  if (changed) {
    video.pause();
    S.pendingSeek = null;
    if (!keepRun) unloadRun();
    S.loadedVideoRec = null;
    video.removeAttribute("src");
    video.load();
    S.rangeTouched = false;
    $("#rangeStart").value = $("#rangeEnd").value = "";
  }
  renderLibrary();
  if (rec.proxy?.status === "ready") { if (changed) attachVideo(); } else updateStageMsg();
  $("#analyseBtn").disabled = false;
  if (changed) {
    await Promise.all([loadSettings(), loadRuns()]);
    if (isNarrow()) { $("#secLib").open = false; $("#stage").scrollIntoView({ behavior: "smooth", block: "start" }); }
  }
  syncDefaultRange();
  writeHash();
}

// ---------------------------------------------------------------- settings
function fillMountSelect() {
  const sel = $("#mountSel");
  sel.replaceChildren();
  const presets = S.config?.mountPresets ?? {};
  for (const [k, v] of Object.entries(presets)) sel.add(new Option(v.label ?? k, k));
  if (S.config?.defaultMount) sel.value = S.config.defaultMount;
  if (S.config?.defaultHfovDeg) $("#hfovInput").placeholder = `${S.config.defaultHfovDeg} (default)`;
  updateSettingPlaceholders();
}

/** Placeholders show what an empty field resolves to; camera height follows the selected mount. */
function updateSettingPlaceholders() {
  const r = S.settings?.resolved;
  const preset = S.config?.mountPresets?.[$("#mountSel").value];
  const h = preset?.cameraHeightM ?? r?.cameraHeightM;
  $("#camHeightInput").placeholder = h != null ? `${h} (preset)` : "preset";
  const dflt = S.config?.geometry?.defaultStepLengthM;
  $("#stepLenInput").placeholder = dflt != null ? `auto (default ${dflt})` : "auto";
  const hf = r?.hfovDeg ?? S.config?.defaultHfovDeg;
  if (hf != null) $("#hfovInput").placeholder = `${hf} (default)`;
}

async function loadSettings() {
  try { S.settings = await api(`/api/recordings/${encodeURIComponent(S.rec.id)}/settings`); } catch { return; }
  applySettingsToForm();
}
function applySettingsToForm() {
  const s = S.settings;
  if (!s) return;
  $("#mountSel").value = s.mount;
  $("#hfovInput").value = s.hfovDeg ?? "";
  $("#camHeightInput").value = s.cameraHeightM ?? "";
  $("#stepLenInput").value = s.stepLengthM ?? "";
  updateSettingPlaceholders();
}
function settingsFromForm() {
  const num = (id) => { const v = $(id).value.trim(); return v === "" ? null : Number(v); };
  return {
    mount: $("#mountSel").value,
    hfovDeg: num("#hfovInput"),
    cameraHeightM: num("#camHeightInput"),
    stepLengthM: num("#stepLenInput"),
  };
}
async function putSettings() {
  S.settings = await api(`/api/recordings/${encodeURIComponent(S.rec.id)}/settings`, { method: "PUT", body: settingsFromForm() });
  applySettingsToForm();
}

async function rerunCollision() {
  if (!S.run || !S.rec) return;
  const btn = $("#rerunBtn"), info = $("#rerunInfo");
  btn.disabled = true; info.textContent = "Running…";
  const t0 = performance.now();
  try {
    await putSettings();
    const r = await api(`/api/runs/${S.run.id}/collision`, { method: "POST" });
    await loadRunData(S.run, r);
    const ms = performance.now() - t0;
    const fmt = (v) => (v < 1000 ? Math.round(v) + " ms" : (v / 1000).toFixed(2) + " s");
    const compute = r.elapsedSeconds != null ? `${fmt(r.elapsedSeconds * 1000)} compute, ` : "";
    info.textContent = `Collision ${r.version ?? ""} re-run: ${compute}${fmt(ms)} total · ${S.events.filter((e) => e.type === "speech").length} speech events`;
    api(`/api/runs/${S.run.id}`, { quiet: true }).then((run) => { S.run = run; applyRunMeta(); }).catch(() => {});
  } catch { info.textContent = "Failed (see error)"; }
  finally { btn.disabled = !S.run; }
}

// ---------------------------------------------------------------- runs
async function loadRuns() {
  try { S.runs = await api(`/api/runs?recording=${encodeURIComponent(S.rec.id)}`); } catch { S.runs = []; }
  renderRuns();
}

function runLabel(r) {
  const q = r.request;
  return `${fmtTime(q.start)} – ${fmtTime(q.end)} · ${q.fps} fps`;
}
function renderRuns() {
  const ul = $("#runList");
  ul.replaceChildren();
  if (!S.runs.length) { ul.innerHTML = '<li class="sub">No runs for this recording</li>'; return; }
  for (const r of S.runs) {
    const li = document.createElement("li");
    li.className = "clickable" + (S.run?.id === r.id ? " sel" : "");
    li.innerHTML = '<div class="t"></div><div class="sub"></div>';
    li.firstChild.textContent = runLabel(r);
    const tag = document.createElement("span");
    tag.className = `tag ${r.status}`;
    tag.textContent = r.status;
    li.firstChild.append(tag);
    li.lastChild.textContent = [r.modelName, r.request.profile, r.createdAt?.replace("T", " ").replace("Z", "")].filter(Boolean).join(" · ");
    li.addEventListener("click", () => openRun(r));
    ul.append(li);
  }
}

function openRun(r) {
  if (r.status === "done") loadRun(r.id);
  else if (r.status === "error") toast(`Run failed: ${r.error ?? "unknown"}`);
  else watchRun(r.id);
}

async function startAnalysis() {
  if (!S.rec) return;
  const dur = S.rec.duration;
  let start = parseTime($("#rangeStart").value);
  let end = parseTime($("#rangeEnd").value);
  if (Number.isNaN(start)) start = video.currentTime || 0;
  if (Number.isNaN(end)) end = start + 60;
  start = clamp(start, 0, dur); end = Math.min(end, dur);
  if (!(end > start)) { toast("Range end must be after range start (and within the recording)."); return; }
  const fps = Number($("#fpsInput").value) || 6;
  const body = { recording: S.rec.id, start, end, model: $("#modelSel").value, profile: $("#profileSel").value || "default", fps };
  $("#analyseBtn").disabled = true;
  try {
    await putSettings(); // the post-inference collision pass uses the stored settings
    const run = await api("/api/runs", { method: "POST", body });
    await loadRuns();
    if (run.status === "done") loadRun(run.id); else watchRun(run.id);
  } catch { $("#analyseBtn").disabled = false; }
}

/** Poll a run once a second, driving the progress bar; load it when done. */
function watchRun(runId) {
  clearTimeout(S.runPoll);
  const pr = $("#runProgress");
  const poll = async () => {
    let r;
    try { r = await api(`/api/runs/${runId}`, { quiet: true }); }
    catch (e) { toast(`Run poll: ${e.message}`); $("#analyseBtn").disabled = false; return; }
    if (r.status === "done") {
      pr.hidden = true; $("#analyseBtn").disabled = !S.rec;
      await loadRuns(); loadRun(runId); return;
    }
    if (r.status === "error") {
      pr.hidden = true; $("#analyseBtn").disabled = !S.rec;
      toast(`Analysis failed: ${r.error ?? "unknown error"}`); loadRuns(); return;
    }
    setProgress(pr, r.progress || 0, `${r.status} ${Math.round((r.progress || 0) * 100)}%`);
    $("#analyseBtn").disabled = true;
    S.runPoll = setTimeout(poll, 1000);
  };
  poll();
}

function unloadRun() {
  S.run = null; S.hazards = null; S.events = []; S.speech = []; S.shown = [];
  overlay.setRun(null, null);
  audio.setEvents([]);
  timeline.set(null, []);
  renderEvents();
  $("#runBadge").textContent = "";
  $("#rerunBtn").disabled = true;
}

async function loadRunData(run, links) {
  const hz = links?.hazards ?? `/api/runs/${run.id}/hazards.json`;
  const ev = links?.events ?? `/api/runs/${run.id}/events.json`;
  const [hazards, events] = await Promise.all([api(hz), api(ev)]);
  S.hazards = hazards;
  S.events = events.events ?? [];
  S.speech = S.events.filter((e) => e.type === "speech");
  S.shown = S.speech.filter((e) => S.roles.has(eventRole(e)));
  overlay.setRun(run, hazards);
  audio.setEvents(S.events);
  timeline.set(run, S.events);
  renderEvents();
}

function applyRunMeta() {
  const r = S.run;
  if (!r) return;
  $("#runBadge").textContent = `run ${r.id} · ${runLabel(r)} · ${r.frameCount} frames · ${r.modelName ?? ""}${r.msPerFrame ? ` · ${Math.round(r.msPerFrame)} ms/frame` : ""} · collision ${r.collisionVersion ?? "?"}${r.motionFrames ? "" : " · no motion track"}`;
}

async function loadRun(runId, { seek = true, t } = {}) {
  let run;
  try { run = await api(`/api/runs/${runId}`); } catch { return; }
  if (run.status !== "done") { watchRun(runId); return; }
  if (S.rec?.id !== run.request.recording) {
    if (!recById(run.request.recording)) await refreshRecordings();
    await selectRecording(run.request.recording, { keepRun: true });
  }
  try { await loadRunData(run); } catch { return; }
  S.run = run;
  applyRunMeta();
  $("#rerunBtn").disabled = false;
  S.rangeTouched = true; // keep the user's run range, don't auto-sync to playhead
  $("#rangeStart").value = fmtTime(run.request.start);
  $("#rangeEnd").value = fmtTime(run.request.end);
  renderRuns();
  if (seek) seekTo(t ?? run.request.start);
  writeHash();
}

// ---------------------------------------------------------------- range inputs
function syncDefaultRange() {
  if (S.rangeTouched || !S.rec) return;
  const start = Math.min(video.currentTime || 0, S.rec.duration);
  $("#rangeStart").value = fmtTime(start);
  $("#rangeEnd").value = fmtTime(Math.min(start + 60, S.rec.duration));
}
function setFromHead(which) {
  S.rangeTouched = true;
  $(which === "start" ? "#rangeStart" : "#rangeEnd").value = fmtTime(video.currentTime, 1);
}

// ---------------------------------------------------------------- events list
function renderEvents() {
  const ol = $("#eventList");
  ol.replaceChildren();
  S.shown = S.speech.filter((e) => S.roles.has(eventRole(e)));
  $("#eventCount").textContent = S.speech.length
    ? `(${S.shown.length === S.speech.length ? S.speech.length : `${S.shown.length} of ${S.speech.length}`})` : "";
  S.shown.forEach((e, i) => {
    const li = document.createElement("li");
    li.dataset.i = i;
    const c = eventColor(e);
    li.innerHTML = '<span class="mono"></span><span></span><span class="u"></span>';
    li.children[0].textContent = fmtTime(e.t, 1);
    li.children[1].textContent = e.text;
    li.children[2].textContent = e.role ?? e.urgency;
    li.children[2].style.color = c;
    li.style.boxShadow = `inset 4px 0 0 ${c}`;
    li.addEventListener("click", () => { video.pause(); seekTo(e.t + 0.001); });
    ol.append(li);
  });
  curEventIdx = -2;
}

function renderRoleChips() {
  const host = $("#roleChips");
  for (const role of ROLES) {
    const lab = document.createElement("label");
    lab.className = "chip on";
    lab.style.setProperty("--c", ROLE_COLOR[role]);
    lab.innerHTML = '<input type="checkbox" checked><i></i><span></span>';
    lab.lastChild.textContent = role;
    lab.firstChild.addEventListener("change", (e) => {
      if (e.target.checked) S.roles.add(role); else S.roles.delete(role);
      lab.classList.toggle("on", e.target.checked);
      timeline.setRoles(S.roles);
      renderEvents();
      highlightEvent(video.currentTime);
    });
    host.append(lab);
  }
}

let curEventIdx = -2;
function highlightEvent(t) {
  const i = lastAtOrBefore(S.shown, t);
  if (i === curEventIdx) return;
  const ol = $("#eventList");
  ol.children[curEventIdx]?.classList.remove("cur");
  curEventIdx = i;
  ol.children[i]?.classList.add("cur");
}

// ---------------------------------------------------------------- transport
function updateTime(t) {
  const dur = durOf();
  $("#timeLabel").textContent = `${fmtTime(t, 1)} / ${fmtTime(dur)}`;
  const bar = $("#seekBar");
  if (!draggingSeek) { bar.max = dur || 1; bar.value = t; }
  timeline.setPlayhead(t);
  highlightEvent(t);
}
let draggingSeek = false;

function step(dir) {
  video.pause();
  const cur = video.currentTime;
  const f = S.hazards?.frames;
  let target;
  if (f?.length) {
    // Previous/next *analysed* frame relative to the playhead.
    if (dir > 0) { const k = f.findIndex((x) => x.t > cur + 0.002); target = k < 0 ? f[f.length - 1].t : f[k].t; }
    else { let k = f.length - 1; while (k >= 0 && f[k].t >= cur - 0.002) k--; target = k < 0 ? f[0].t : f[k].t; }
    target += 0.001; // land inside the video frame whose time is >= analysed t
  } else {
    target = cur + dir / (S.rec?.fps || 24);
  }
  seekTo(target);
}

function setSpeed(r) {
  r = clamp(r, SPEEDS[0], SPEEDS[SPEEDS.length - 1]);
  video.playbackRate = r;
  $("#speedSel").value = String(r);
}
function stepSpeed(dir) {
  const cur = video.playbackRate;
  let i = SPEEDS.findIndex((s) => Math.abs(s - cur) < 1e-6);
  if (i < 0) i = SPEEDS.findIndex((s) => s >= cur);
  setSpeed(SPEEDS[clamp(i + dir, 0, SPEEDS.length - 1)]);
}

function togglePlay() {
  if (!video.currentSrc) return;
  if (video.paused) video.play().catch((e) => toast(`Playback: ${e.message}`)); else video.pause();
}

function toggleMute(force) {
  const m = force ?? !audio.muted;
  $("#muteChk").checked = m;
  audio.setMuted(m);
}

// ---------------------------------------------------------------- init & wiring
function wire() {
  // media
  video.addEventListener("loadedmetadata", () => {
    if (S.pendingSeek !== null) { video.currentTime = S.pendingSeek; S.pendingSeek = null; }
    video.playbackRate = Number($("#speedSel").value);
    updateTime(video.currentTime);
    syncDefaultRange();
  });
  video.addEventListener("error", () => {
    if (video.currentSrc) toast(`Video failed to load (${video.error?.message || "unsupported or missing proxy"})`);
  });
  video.addEventListener("play", () => { $("#playBtn").innerHTML = "&#10074;&#10074;"; });
  video.addEventListener("pause", () => { $("#playBtn").innerHTML = "&#9654;"; writeHash(); });
  video.addEventListener("ended", () => { $("#playBtn").innerHTML = "&#9654;"; });
  video.addEventListener("timeupdate", () => { if (!("requestVideoFrameCallback" in video)) updateTime(video.currentTime); });
  video.addEventListener("seeked", () => { updateTime(video.currentTime); syncDefaultRange(); writeHash(); });
  overlay.onFrame = updateTime; // exact presented-frame time from rVFC (or currentTime in fallback)
  setInterval(() => { if (!video.paused) writeHash(); }, 1000);

  // transport
  $("#playBtn").addEventListener("click", togglePlay);
  $("#stepBack").addEventListener("click", () => step(-1));
  $("#stepFwd").addEventListener("click", () => step(1));
  const speedSel = $("#speedSel");
  for (const s of SPEEDS) speedSel.add(new Option(`${s}×`, String(s)));
  speedSel.value = "1";
  speedSel.addEventListener("change", () => setSpeed(Number(speedSel.value)));
  const bar = $("#seekBar");
  bar.addEventListener("input", () => { draggingSeek = true; seekTo(Number(bar.value)); });
  bar.addEventListener("change", () => { draggingSeek = false; });
  bar.addEventListener("pointerup", () => { draggingSeek = false; });

  // audio
  const ab = $("#audioBtn");
  ab.addEventListener("click", async () => {
    try { await audio.enable(); ab.textContent = "Audio enabled"; ab.classList.remove("primary"); ab.classList.add("on"); }
    catch (e) { toast(`Audio: ${e.message}`); }
  });
  $("#speechChk").addEventListener("change", (e) => audio.setSpeech(e.target.checked));
  $("#tonesChk").addEventListener("change", (e) => audio.setTones(e.target.checked));
  $("#muteChk").addEventListener("change", (e) => toggleMute(e.target.checked));
  $("#videoSoundChk").addEventListener("change", (e) => { video.muted = !e.target.checked; });
  $("#volRange").addEventListener("input", (e) => audio.setVolume(Number(e.target.value)));
  $("#offsetRange").addEventListener("input", (e) => {
    audio.offsetS = Number(e.target.value) / 1000;
    $("#offsetOut").textContent = `${e.target.value} ms`;
    audio.reset();
  });

  // overlay layers
  const layer = (id, key) => $(id).addEventListener("change", (e) => { overlay.layers[key] = e.target.checked; overlay.redraw(); });
  layer("#maskChk", "mask"); layer("#regionChk", "region"); layer("#laneChk", "lane");
  layer("#horizonChk", "horizon"); layer("#hazardChk", "hazards"); layer("#showAllChk", "showAll");
  $("#mountSel").addEventListener("change", updateSettingPlaceholders);
  renderRoleChips();
  $("#maskOpacity").addEventListener("input", (e) => { overlay.maskOpacity = Number(e.target.value); overlay.redraw(); });

  // run panel
  $("#analyseBtn").addEventListener("click", startAnalysis);
  $("#rerunBtn").addEventListener("click", rerunCollision);
  $("#startFromHead").addEventListener("click", () => setFromHead("start"));
  $("#endFromHead").addEventListener("click", () => setFromHead("end"));
  for (const id of ["#rangeStart", "#rangeEnd"]) $(id).addEventListener("input", () => { S.rangeTouched = true; });

  // keyboard
  const typing = (el) => el && (el.tagName === "INPUT" && el.type !== "checkbox" && el.type !== "range" || el.tagName === "SELECT" || el.tagName === "TEXTAREA");
  window.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
    switch (e.key) {
      case " ": e.preventDefault(); togglePlay(); break;
      case "ArrowLeft": e.preventDefault(); step(-1); break;
      case "ArrowRight": e.preventDefault(); step(1); break;
      case "[": stepSpeed(-1); break;
      case "]": stepSpeed(1); break;
      case "m": case "M": toggleMute(); break;
    }
  });
  // Space on a focused button would otherwise also "click" it on keyup.
  window.addEventListener("keyup", (e) => { if (e.key === " " && !typing(e.target)) e.preventDefault(); });
}

async function init() {
  wire();
  if (isNarrow()) { $("#secSettings").open = false; $("#secRuns").open = false; }
  updateTime(0);
  const [config, models] = await Promise.all([
    api("/api/config/collision").catch(() => null),
    api("/api/models").catch(() => null),
    refreshRecordings(),
  ]);
  S.config = config; S.models = models;
  fillMountSelect();
  if (models) {
    for (const m of models.models) $("#modelSel").add(new Option(m.name + (m.default ? " (default)" : ""), m.path));
    const d = models.models.find((m) => m.default);
    if (d) $("#modelSel").value = d.path;
    for (const p of models.profiles) $("#profileSel").add(new Option(p, p));
  } else $("#profileSel").add(new Option("default", "default"));

  // Restore state from the URL hash.
  const h = readHash();
  const t = h.t !== undefined ? parseFloat(h.t) : NaN;
  if (h.rec && recById(h.rec)) {
    await selectRecording(h.rec);
    if (!Number.isNaN(t)) seekTo(t);
  }
  if (h.run) await loadRun(h.run, { seek: Number.isNaN(t), t: Number.isNaN(t) ? undefined : t });
  if (h.run && !Number.isNaN(t)) seekTo(t);
}

init();
