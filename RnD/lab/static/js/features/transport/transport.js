// Transport: playhead, seek, step, speed, play/pause, mute, default range, role chips, and the player-side wiring
// (media events, audio controls, overlay layer toggles, keyboard shortcuts).
import { $, fmtTime, toast, clamp, ROLES, ROLE_COLOR } from "../../util/index.js";
import { markDefault } from "../../util/ui.js";
import { on, emit } from "../../bus.js";
import { S, video, durOf, overlay, hazards, audio, worldmap, selection, timeline, reviews } from "../../state.js";

const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];

export function seekTo(t) {
  t = clamp(t, 0, durOf() || t);
  S.seekGen++;
  if (video.readyState >= 1) video.currentTime = t;
  else S.pendingSeek = t; // applied on loadedmetadata
}

function syncDefaultRange() {
  if (S.rangeTouched || !S.rec) return;
  $("#rangeStart").value = fmtTime(0);
  $("#rangeEnd").value = fmtTime(S.rec.duration);
}
function setFromHead(which) {
  S.rangeTouched = true;
  $(which === "start" ? "#rangeStart" : "#rangeEnd").value = fmtTime(video.currentTime, 1);
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
      reviews.setRoles(S.roles);
    });
    host.append(lab);
  }
}

export function updateTime(t) {
  const dur = durOf();
  $("#timeLabel").textContent = `${fmtTime(t, 1)} / ${fmtTime(dur)}`;
  const bar = $("#seekBar");
  if (!draggingSeek) { bar.max = dur || 1; bar.value = t; }
  timeline.setPlayhead(t);
  reviews.highlight(t);
  hazards.update(t);
  worldmap.update(t);
}
let draggingSeek = false;
function step(dir) {
  video.pause();
  const cur = video.currentTime;
  const f = hazards.frames;
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

export function wire() {
  on("seek", seekTo);
  on("sync-default-range", syncDefaultRange);
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
  video.addEventListener("play", () => { S.seekGen++; $("#playBtn").innerHTML = "&#10074;&#10074;"; reviews.playheadChanged(); });
  video.addEventListener("pause", () => { $("#playBtn").innerHTML = "&#9654;"; emit("write-hash"); reviews.playheadChanged(); });
  video.addEventListener("ended", () => { $("#playBtn").innerHTML = "&#9654;"; });
  video.addEventListener("timeupdate", () => { if (!("requestVideoFrameCallback" in video)) updateTime(video.currentTime); });
  video.addEventListener("seeked", () => { updateTime(video.currentTime); syncDefaultRange(); emit("write-hash"); reviews.playheadChanged(); });
  overlay.onFrame = updateTime; // exact presented-frame time from rVFC (or currentTime in fallback)
  setInterval(() => { if (!video.paused) emit("write-hash"); }, 1000);

  // transport
  $("#playBtn").addEventListener("click", togglePlay);
  $("#stepBack").addEventListener("click", () => step(-1));
  $("#stepFwd").addEventListener("click", () => step(1));
  const speedSel = $("#speedSel");
  for (const s of SPEEDS) speedSel.add(new Option(`${s}×`, String(s)));
  speedSel.value = "1"; markDefault(speedSel, "1");
  speedSel.addEventListener("change", () => setSpeed(Number(speedSel.value)));
  const bar = $("#seekBar");
  bar.addEventListener("input", () => { draggingSeek = true; seekTo(Number(bar.value)); });
  bar.addEventListener("change", () => { draggingSeek = false; });
  bar.addEventListener("pointerup", () => { draggingSeek = false; });

  // audio: armed by default; pointerup/touchend/click/keydown anywhere unlock AudioContext + speech until it runs (12.2)
  const ab = $("#audioBtn");
  const paintAudioBtn = () => {
    ab.innerHTML = audio.on ? "&#128266; Audio on" : "&#128263; Audio off";
    ab.classList.toggle("on", audio.on);
    ab.setAttribute("aria-pressed", String(audio.on));
  };
  audio.armOnFirstGesture((err) => { if (err) toast(`Audio: ${err.message}`); });
  ab.addEventListener("click", async () => {
    audio.setOn(!audio.on);
    paintAudioBtn();
    if (audio.on) { try { await audio.enable(); } catch (e) { toast(`Audio: ${e.message}`); } }
  });
  paintAudioBtn();
  $("#testSpeechBtn").addEventListener("click", async () => {
    const r = await audio.testSpeech();
    const flags = `speaking ${r.speaking} / pending ${r.pending} / paused ${r.paused}`;
    toast(`Speech test: ${r.outcome}${r.retried ? " (retried)" : ""}; voice ${r.voice ?? "none"}; ${r.voices} voices; ${flags}${r.outcome === "no event" ? ". See the notice in the Audio panel: the speech engine may be stuck" : ""}`,
      r.ended || r.started ? "info" : "error", 10000);
  });
  $("#reviewPreviewChk").addEventListener("change", () => emit("audio-events-changed"));
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
  layer("#maskChk", "mask"); layer("#depthChk", "depth"); layer("#regionChk", "region"); layer("#laneChk", "lane");
  layer("#horizonChk", "horizon"); layer("#hazardChk", "hazards"); layer("#showAllChk", "showAll");
  const shapeSel = $("#shapeSel");
  try { const v = localStorage.getItem("hackeye.lab.shapes"); if (v === "outlines" || v === "boxes") shapeSel.value = v; } catch { /* storage blocked */ }
  overlay.outlines = shapeSel.value === "outlines";
  shapeSel.addEventListener("change", () => {
    overlay.outlines = shapeSel.value === "outlines";
    try { localStorage.setItem("hackeye.lab.shapes", shapeSel.value); } catch { /* storage blocked */ }
    overlay.redraw();
  });
  renderRoleChips();
  $("#maskOpacity").addEventListener("input", (e) => { overlay.maskOpacity = Number(e.target.value); overlay.redraw(); });
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
      case "Escape": selection.clear(); break;
    }
  });
  // Space on a focused button would otherwise also "click" it on keyup.
  window.addEventListener("keyup", (e) => { if (e.key === " " && !typing(e.target)) e.preventDefault(); });
}
