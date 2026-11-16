// Pure helpers of the collision-run rows: tags, what-differs summary, option text. `first` is the run's first collision run (S.colls[0]).
export const lsKey = (runId) => `lab.collision.${runId}`;
const SHORT_KEYS = { objectDistance: "objDist", useHorizon: "horizon", distanceSource: "dist", projection: "lens", cameraSide: "side",
  cameraLocation: "loc", userHeightM: "height", hfovDeg: "hfov", cameraHeightM: "camH", stepLengthM: "step", mount: "mount", orientation: "orient" };
export const shortVal = (v) => (v === true ? "on" : v === false ? "off" : v === null || v === undefined ? "auto" : typeof v === "object" ? JSON.stringify(v) : String(v));

export function flatKeys(node, prefix = "", out = {}) {
  if (node && typeof node === "object" && !Array.isArray(node)) for (const [k, v] of Object.entries(node)) flatKeys(v, prefix ? `${prefix}.${k}` : k, out);
  else out[prefix] = node;
  return out;
}

/** v26.2.11: the overrides the row shows as tags (dotted key -> tag name). */
const TAGGED = { "source.mode": "source", "speech.predictive.enabled": "predictive", "ego.headingSource": "heading",
  "horizon.source": "horizon", "ego.cadenceSource": "cadence" };

/** The row's tags: the tagged overrides ("source map"), and the effective object distance when it differs ("ground-contact -> depth (horizon off)"). */
export function collTags(d) {
  const tags = [];
  const flat = flatKeys(d.overrides ?? {});
  for (const [k, v] of Object.entries(flat)) { const name = TAGGED[k.replace(/^collision\./, "")]; if (name) tags.push({ k: name, text: `${name} ${shortVal(v)}` }); }
  const req = d.settings?.objectDistance, eff = d.objectDistanceEffective;
  if (req && eff && req !== eff) tags.push({ k: "objDist", text: `${req} -> ${eff} (horizon ${d.settings?.useHorizon === false ? "off" : "on"})` });
  return tags;
}

/** What differs from the run's first collision run, short: "objDist ground+depth · horizon off · itemLens off"; "first" for c1. */
export function collSummary(d, first) {
  if (!first || first.id === d.id) return "first";
  const parts = [];
  for (const k of Object.keys(d.settings ?? {})) {
    if (k === "cameraSide" || JSON.stringify(d.settings[k]) === JSON.stringify(first.settings?.[k])) continue;
    parts.push(`${SHORT_KEYS[k] ?? k} ${shortVal(d.settings[k])}`);
  }
  const fo = flatKeys(first.overrides ?? {}), o = flatKeys(d.overrides ?? {});
  for (const k of Object.keys(o)) if (!TAGGED[k.replace(/^collision\./, "")] && JSON.stringify(o[k]) !== JSON.stringify(fo[k])) parts.push(`${k.split(".").pop()} ${shortVal(o[k])}`);
  return parts.join(" · ") || "same settings";
}

export function collText(d, first) {
  let hhmm = "";
  try { hhmm = new Date(d.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }); } catch { /* ignore */ }
  return `${d.id} · ${d.label || collSummary(d, first)}${hhmm ? ` · ${hhmm}` : ""}`;
}
