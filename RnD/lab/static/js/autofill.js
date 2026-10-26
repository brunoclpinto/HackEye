// Pure helpers for the review panel's add-form "Auto-fill" (CONTRACTS §10a).
// No DOM access, so they can be unit-tested under node.
const ROLE_ORDER = { final: 0, danger: 1, feature: 2, context: 3, none: 4 };
const DEFAULT_TEMPLATES = {
  context: "{label} at {clock} in {steps}", feature: "{label} at {clock} in {steps}",
  danger: "{label} at {clock} in {steps}", approach: "{label} approaching at {clock} in {steps}",
  final: "{label} at {clock} in {steps}",
};

/** Analysed frame with the largest t <= t, or null when t is outside the run (before the first frame or > 1 s past the last). */
export function frameAt(frames, t) {
  if (!frames?.length || !(t >= frames[0].t)) return null;
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (frames[m].t <= t) lo = m; else hi = m - 1; }
  const f = frames[lo];
  return lo === frames.length - 1 && t > f.t + 1 ? null : f;
}

/** Items of the frame ordered final > danger > feature > context > none, then the higher safety level (`levelOf(className)`, from
 *  safety_mapping.json / the Classes panel; unknown = 0), then stepsTo ascending (nulls last). The first one is the highest-priority object. */
export function orderCandidates(frame, levelOf) {
  const rank = (it) => ROLE_ORDER[it.role] ?? ROLE_ORDER.none;
  const level = (it) => Number(levelOf?.(it.className ?? it.label)) || 0;
  const steps = (it) => (typeof it.stepsTo === "number" ? it.stepsTo : Infinity);
  return (frame?.hazards ?? []).map((it, i) => [it, i])
    .sort(([a, i], [b, j]) => rank(a) - rank(b) || level(b) - level(a) || (steps(a) === steps(b) ? 0 : steps(a) < steps(b) ? -1 : 1) || i - j)
    .map(([it]) => it);
}

/** {text, role} for one hazards item; role "none" maps to "danger" (a missed item is usually a missed warning). */
export function fillFor(item, templates) {
  const T = { ...DEFAULT_TEMPLATES, ...(templates ?? {}) };
  const role = item.role ?? "none";
  let key = { final: "final", feature: "feature", context: "context" }[role] ?? "danger";
  if (key === "danger" && item.moving === true && item.closingMps > 0) key = "approach";
  const vals = {
    label: item.label ?? item.className ?? "object",
    clock: item.clockText ?? item.clock ?? "?",
    steps: typeof item.stepsTo === "number" ? Math.round(item.stepsTo) : "?",
  };
  const text = T[key].replace(/\{(label|clock|steps)\}/g, (_, k) => vals[k]);
  return { text, role: role === "none" ? "danger" : role };
}
