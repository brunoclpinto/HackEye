// Page bootstrap: constructs the panels, registers them in state.js, wires every feature (in today's order) and runs init().
import { $ } from "../util/index.js";
import { markDefault } from "../util/ui.js";
import { api } from "../api.js";
import { emit } from "../bus.js";
import { S, register, recById, isNarrow } from "../state.js";
import { Overlay } from "../features/overlay/overlay.js";
import { AudioEngine } from "../features/audio/audio.js";
import { Timeline } from "../features/timeline/timeline.js";
import { Reviews } from "../features/reviews/reviews.js";
import { HazardWindow } from "../features/hazards/hazards.js";
import { ClassesPanel } from "../features/classes/classes.js";
import { SoundsPanel } from "../features/sounds/sounds.js";
import { NotesPanel } from "../features/notes/notes.js";
import { IssuesPanel } from "../features/issues/issues.js";
import { WorldMapPanel } from "../features/worldmap/worldmap.js";
import { Selection } from "../util/selection.js";
import { wire as wireLibrary, readHash, refreshRecordings, selectRecording } from "../features/library/library.js";
import { wire as wireTransport, seekTo, updateTime } from "../features/transport/transport.js";
import { wire as wireSettings, fillMountSelect, ovDefaults } from "../features/settings/settings.js";
import { wire as wireRuns, loadRun, labelResolutions, DEPTH_LABELS } from "../features/runs/runs.js";
import { wire as wireCollisions, rerunCollision } from "../features/collisions/collisions.js";

const video = $("#video");

const overlay = new Overlay(video, $("#overlay"));
// Windowed hazards (CONTRACTS 12.1): the overlay, HUD and frame stepping use the frames around the playhead.
const hazards = new HazardWindow((frames, head) => overlay.setFrames(frames, head));
overlay.hudEl = $("#hud");
const classesPanel = new ClassesPanel(overlay);
const audio = new AudioEngine(video);
window.__labAudio = audio;                                  // E2E hook (CONTRACTS 13): the tests set / clear the sound profile on it

const sounds = new SoundsPanel({ audio, rerun: () => rerunCollision(), hasRun: () => !!S.run });
const notesPanel = new NotesPanel({ getRecId: () => S.rec?.id ?? null, getTime: () => S.pendingSeek ?? (video.currentTime || 0), getRunId: () => S.run?.id ?? null });
const issuesPanel = new IssuesPanel();
const worldmap = new WorldMapPanel({ getStyle: () => overlay.style, getFrames: () => overlay.frames, isPlaying: () => !video.paused,
  getLens: () => ({ hfovDeg: overlay.head?.settings?.hfovDeg, projection: overlay.head?.projection }) });
window.__labWorldmap = worldmap;                           // E2E hook (CONTRACTS 13): the tests read the snapshot grid to find a wall cell
// v26.2.10: items (and map regions) are selected as a whole; the video overlay and the world map share the selection
const selection = new Selection();
overlay.selection = selection;
worldmap.selection = selection;
selection.onChange(() => { overlay.redraw(); worldmap.onSelection(); });
const timeline = new Timeline($("#timeline"), (t) => emit("seek", t));
const reviews = new Reviews({
  seek: (t) => emit("seek", t),
  pause: () => video.pause(),
  getTime: () => video.currentTime || 0,
  isPaused: () => video.paused,
  getFrame: (t) => hazards.frameAt(t),
  levelOf: (name) => { const st = overlay.style, c = st?.info?.classes?.find((x) => x.name === name); return c ? st.levelOf.get(c.id) : 0; },
  /** Auto-fill without a loaded run: load the newest done run of this recording that covers t. */
  ensureRun: async (t) => {
    if (S.run) return true;
    const r = (S.runs ?? []).filter((x) => x.status === "done" && x.request.start <= t && t <= x.request.end + 1)
      .sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)))[0];
    if (!r) return false;
    await emit("load-run", r.id, { seek: false });
    return !!S.run;
  },
  changed: () => emit("audio-events-changed"),
  getTemplates: () => S.config?.speech?.templates ?? null,
  transport: (id) => $(`#${id}`).click(),
});
register({ video, overlay, hazards, classesPanel, audio, sounds, notesPanel, issuesPanel, worldmap, selection, timeline, reviews });

async function init() {
  wireLibrary();
  wireTransport();
  wireSettings();
  wireRuns();
  wireCollisions();
  if (isNarrow()) { $("#secSettings").open = false; $("#secRuns").open = false; }
  updateTime(0);
  api("/api/version", { quiet: true }).then((v) => {
    if (v && v.version) $("#verBadge").textContent = `\u00b7 ${v.version}`;
  }).catch(() => {});
  const [config, models] = await Promise.all([
    api("/api/config/collision").catch(() => null),
    api("/api/models").catch(() => null),
    refreshRecordings(),
  ]);
  S.config = config; S.models = models;
  sounds.load();
  notesPanel.load();
  issuesPanel.load();
  fillMountSelect();
  ovDefaults();
  for (const [id, v] of [["#orientSel", "landscape"], ["#deviceSel", "gpu"], ["#sideSel", "center"], ["#distSel", "depth"], ["#objDistSel", "depth"], ["#horizonSel", "true"], ["#shapeSel", "outlines"]]) markDefault($(id), v);
  if (models) {
    for (const m of models.models) $("#modelSel").add(new Option(m.name + (m.default ? " (default)" : ""), m.path));
    const d = models.models.find((m) => m.default);
    if (d) $("#modelSel").value = d.path;
    for (const p of models.profiles) $("#profileSel").add(new Option(p, p));
    $("#profileSel").value = "736p";
    const dm = models.depthModels ?? [];
    if (dm.length) {
      for (const d of dm) $("#depthSel").add(new Option(d === "none" ? "Off" : DEPTH_LABELS[d] ?? d, d));
      if (!dm.includes("none")) $("#depthSel").add(new Option("Off", "none"), 0);
      $("#depthSel").value = dm.includes("da2-metric-outdoor-small") ? "da2-metric-outdoor-small" : "none";   // depth on by default (v26.1.10)
      markDefault($("#depthSel"), $("#depthSel").value);
      $("#depthLbl").hidden = false;
    }
  } else $("#profileSel").add(new Option("default", "default"));
  labelResolutions();
  try { const v = localStorage.getItem("hackeye.lab.device"); if (v === "gpu" || v === "cpu") $("#deviceSel").value = v; } catch { /* storage blocked */ }
  $("#deviceSel").addEventListener("change", () => {
    try { localStorage.setItem("hackeye.lab.device", $("#deviceSel").value); } catch { /* storage blocked */ }
  });

  // Restore state from the URL hash.
  const h = readHash();
  const t = h.t !== undefined ? parseFloat(h.t) : NaN;
  if (h.rec && recById(h.rec)) {
    await selectRecording(h.rec);
    if (!Number.isNaN(t)) seekTo(t);
  }
  // The hash time was already applied above; loadRun must not re-apply it after a slow load.
  if (h.run) await loadRun(h.run, { seek: Number.isNaN(t), t: Number.isNaN(t) ? undefined : t });
}

init();
