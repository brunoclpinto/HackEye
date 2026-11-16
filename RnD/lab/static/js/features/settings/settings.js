// Settings: the per-recording settings form, its placeholders, and the Config overrides (text + dotted-key controls).
import { $ } from "../../util/index.js";
import { markDefault } from "../../util/ui.js";
import { api } from "../../api.js";
import { on, emit } from "../../bus.js";
import { S } from "../../state.js";

export function fillMountSelect() {
  const sel = $("#mountSel");
  sel.replaceChildren();
  const presets = S.config?.mountPresets ?? {};
  for (const [k, v] of Object.entries(presets)) sel.add(new Option(v.label ?? k, k));
  if (S.config?.defaultMount) { sel.value = S.config.defaultMount; markDefault(sel, S.config.defaultMount); }
  const loc = $("#locSel");
  loc.replaceChildren(new Option("Legacy mount", ""));
  for (const [k, v] of Object.entries(S.config?.body?.cameraLocations ?? {})) loc.add(new Option(v.label ?? k, k));
  const dh = S.config?.body?.defaultUserHeightM;
  $("#userHeightInput").placeholder = dh != null ? `${dh} (default)` : "default";
  if (S.config?.defaultHfovDeg) $("#hfovInput").placeholder = `${S.config.defaultHfovDeg} (default)`;
  updateSettingPlaceholders();
}

/** Placeholders show what an empty field resolves to. With a camera location set, the body-derived values
 *  (from the server's resolved block, or this form's current location/height as a fallback) replace the mount preset. */
function updateSettingPlaceholders() {
  const r = S.settings?.resolved;
  const located = $("#locSel").value !== "";
  $("#mountLbl").hidden = located;
  const fmt = (v) => (v == null ? null : Math.round(v * 1000) / 1000);
  const derived = located && r?.cameraLocation === $("#locSel").value;
  const preset = S.config?.mountPresets?.[$("#mountSel").value];
  const h = derived ? r.cameraHeightM : (located ? null : (preset?.cameraHeightM ?? r?.cameraHeightM));
  $("#camHeightInput").placeholder = h != null ? `${located ? "auto" : ""} ${fmt(h)}${located ? "" : " (preset)"}`.trim() : (located ? "auto" : "preset");
  const dflt = S.config?.geometry?.defaultStepLengthM;
  const step = derived ? r.stepLengthM : null;
  $("#stepLenInput").placeholder = step != null ? `auto ${fmt(step)}` : dflt != null ? `auto (default ${dflt})` : "auto";
  const hint = $("#bodyHint");
  hint.hidden = !located;
  hint.textContent = derived
    ? `Camera ${fmt(r.cameraHeightM)} m high, step ${fmt(r.stepLengthM)} m, horizon ${fmt(r.horizon)}, side offset ${fmt(r.lateralOffsetM)} m (save to refresh).`
    : "Save to see the derived camera height, step length and side offset.";
  const hf = r?.hfovDeg ?? S.config?.defaultHfovDeg;
  if (hf != null) $("#hfovInput").placeholder = `${hf} (default)`;
  const auto = $("#projSel").querySelector('option[value="auto"]');
  auto.textContent = (r?.projection ? `Auto (${r.projection})` : "Auto") + " (default)";
}

async function loadSettings() {
  try { S.settings = await api(`/api/recordings/${encodeURIComponent(S.rec.id)}/settings`); } catch { return; }
  applySettingsToForm();
}
function applySettingsToForm() {
  const s = S.settings;
  if (!s) return;
  $("#mountSel").value = s.mount;
  $("#userHeightInput").value = s.userHeightM ?? "";
  $("#locSel").value = s.cameraLocation ?? "";
  $("#sideSel").value = s.cameraSide ?? "center";
  $("#orientSel").value = s.orientation ?? "landscape";
  emit("label-resolutions");
  $("#hfovInput").value = s.hfovDeg ?? "";
  $("#camHeightInput").value = s.cameraHeightM ?? "";
  $("#stepLenInput").value = s.stepLengthM ?? "";
  $("#projSel").value = s.projection ?? "auto";
  $("#distSel").value = s.distanceSource ?? "depth";
  $("#objDistSel").value = s.objectDistance ?? "depth";
  $("#horizonSel").value = String(s.useHorizon ?? true);
  syncObjDist();
  updateSettingPlaceholders();
}
/** v26.2.11: ground-contact / ground+depth need the horizon: with it off they are greyed out (hint shown) and a selected one falls back to depth. */
function syncObjDist() {
  const off = $("#horizonSel").value === "false", sel = $("#objDistSel");
  for (const o of sel.options) o.disabled = off && o.value !== "depth";
  if (off && sel.value !== "depth") sel.value = "depth";
  $("#objDistHint").hidden = !off;
}

/** The dotted-key controls of the re-run form: {key: value} for every control whose value differs from the shipped config default. */
const OV_VALUES = { on: true, off: false };
export function ovDefaults() {
  for (const el of document.querySelectorAll("select[data-key]")) {
    let v = el.dataset.key.split(".").reduce((o, k) => o?.[k], S.config ?? {});
    if (typeof v === "boolean") v = v ? "on" : "off";
    if (v != null && [...el.options].some((o) => o.value === v)) { el.dataset.default = v; el.value = v; markDefault(el, v); }
    else delete el.dataset.default;
  }
}
function overrideControls() {
  const out = {};
  for (const el of document.querySelectorAll("select[data-key]")) if (el.value !== el.dataset.default) out[el.dataset.key] = el.value in OV_VALUES ? OV_VALUES[el.value] : el.value;
  return out;
}
function settingsFromForm() {
  const num = (id) => { const v = $(id).value.trim(); return v === "" ? null : Number(v); };
  return {
    mount: $("#mountSel").value,
    userHeightM: num("#userHeightInput"),
    cameraLocation: $("#locSel").value || null,
    cameraSide: $("#sideSel").value,
    orientation: $("#orientSel").value,
    hfovDeg: num("#hfovInput"),
    cameraHeightM: num("#camHeightInput"),
    stepLengthM: num("#stepLenInput"),
    projection: $("#projSel").value,
    distanceSource: $("#distSel").value,
    objectDistance: $("#objDistSel").value,
    useHorizon: $("#horizonSel").value === "true",
  };
}
async function putSettings() {
  S.settings = await api(`/api/recordings/${encodeURIComponent(S.rec.id)}/settings`, { method: "PUT", body: settingsFromForm() });
  applySettingsToForm();
}

/** The Config overrides input: undefined (empty), the parsed object, or null (invalid: the message is shown under it). */
function readOverrides() {
  const err = $("#collOvErr"), raw = $("#collOverrides").value.trim();
  err.hidden = true;
  if (!raw) return undefined;
  const bad = (m) => { err.textContent = m; err.hidden = false; return null; };
  let v;
  try { v = JSON.parse(raw); } catch (e) { return bad(`Overrides are not valid JSON: ${e.message}`); }
  if (!v || typeof v !== "object" || Array.isArray(v)) return bad('Overrides must be an object like {"collision": {"distance.itemLens": "off"}}');
  return v;
}

/** The text field merged with the dotted-key controls (the controls win); undefined when both are empty, null when the text is invalid. */
function allOverrides() {
  const typed = readOverrides();
  if (typed === null) return null;
  const ctl = overrideControls();
  if (!Object.keys(ctl).length) return typed;
  return { ...(typed ?? {}), collision: { ...((typed ?? {}).collision ?? {}), ...ctl } };
}

export function wire() {
  on("load-settings", loadSettings);
  on("put-settings", putSettings);
  on("all-overrides", allOverrides);
  $("#horizonSel").addEventListener("change", syncObjDist);
  $("#mountSel").addEventListener("change", updateSettingPlaceholders);
  const geometryChanged = () => { // body settings change the collision geometry: offer the re-run like Distance does
    updateSettingPlaceholders();
    if (S.rec) putSettings().catch(() => {}); // save now so the derived hints refresh
    if (!S.run) return;
    $("#rerunBtn").classList.add("primary");
    $("#rerunInfo").textContent = "Body settings changed: click Re-run collision to compare.";
  };
  for (const id of ["#locSel", "#sideSel"]) $(id).addEventListener("change", geometryChanged);
  $("#userHeightInput").addEventListener("change", geometryChanged);
}
