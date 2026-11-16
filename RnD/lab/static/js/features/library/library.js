// Library: the recordings list, proxy building, video attach, recording selection and the URL hash.
import { $, fmtTime, toast } from "../../util/index.js";
import { setProgress } from "../../util/ui.js";
import { api } from "../../api.js";
import { on, emit } from "../../bus.js";
import { S, video, recById, isNarrow, notesPanel, reviews } from "../../state.js";

function writeHash() {
  const p = [];
  if (S.rec) p.push(`rec=${encodeURIComponent(S.rec.id)}`);
  if (S.run) p.push(`run=${S.run.id}`);
  if (S.rec && Number.isFinite(video.currentTime)) p.push(`t=${(S.pendingSeek ?? video.currentTime).toFixed(1)}`);
  try { history.replaceState(null, "", `#${p.join("&")}`); } catch { /* ignore */ }
}
export const readHash = () => Object.fromEntries(new URLSearchParams(location.hash.slice(1)));

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

export async function refreshRecordings() {
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

export async function selectRecording(id, { keepRun = false } = {}) {
  const rec = recById(id);
  if (!rec) { toast(`Unknown recording ${id}`); return; }
  const changed = S.rec?.id !== id;
  S.rec = rec;
  notesPanel.recordingChanged();
  if (changed) {
    clearTimeout(S.runPoll);
    $("#runProgress").hidden = true;
    emit("set-busy", null);
    video.pause();
    S.pendingSeek = null;
    if (!keepRun) emit("unload-run");
    S.loadedVideoRec = null;
    video.removeAttribute("src");
    video.load();
    S.rangeTouched = false;
    $("#rangeStart").value = $("#rangeEnd").value = "";
  }
  renderLibrary();
  emit("label-resolutions");
  if (rec.proxy?.status === "ready") { if (changed) attachVideo(); } else updateStageMsg();
  $("#analyseBtn").disabled = !!$("#cancelBtn").dataset.run;
  if (changed) {
    await Promise.all([emit("load-settings"), emit("load-runs"), reviews.setRecording(rec)]);
    emit("watch-active-run");
    if (isNarrow()) { $("#secLib").open = false; $("#stage").scrollIntoView({ behavior: "smooth", block: "start" }); }
  }
  emit("sync-default-range");
  writeHash();
}

export function wire() {
  on("write-hash", writeHash);
  on("refresh-recordings", refreshRecordings);
  on("select-recording", selectRecording);
}
