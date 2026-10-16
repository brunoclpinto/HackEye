// Small shared helpers: time parsing/formatting, DOM shortcuts, toasts, urgency colours.

export const $ = (sel, root = document) => root.querySelector(sel);

// Urgency colours (spec). "none" is only used for dim UI hints.
export const URGENCY_COLOR = {
  caution: "#f5c518",
  warning: "#ff8c1a",
  imminent: "#ff2d2d",
  none: "#8a8f98",
};
export const URGENCY_RANK = { none: 0, caution: 1, warning: 2, imminent: 3 };
export const CORRIDOR_COLOR = "#22d3ee";

/** Parse "ss", "mm:ss" or "hh:mm:ss" (fractions allowed). Returns NaN if invalid. */
export function parseTime(str) {
  const s = String(str ?? "").trim();
  if (!s) return NaN;
  const parts = s.split(":");
  if (parts.length > 3) return NaN;
  let total = 0;
  for (const p of parts) {
    if (!/^\d+(\.\d+)?$|^\.\d+$/.test(p.trim())) return NaN;
    total = total * 60 + parseFloat(p);
  }
  return total;
}

/** Format seconds as m:ss (or h:mm:ss); `decimals` adds fractional seconds. */
export function fmtTime(sec, decimals = 0) {
  if (!Number.isFinite(sec)) return "--:--";
  const neg = sec < 0;
  sec = Math.abs(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const f = 10 ** decimals;
  const s = Math.floor((sec % 60) * f + 1e-6) / f; // floor, so 59.96 never shows as 60.0
  const ss = decimals ? s.toFixed(decimals).padStart(3 + decimals, "0") : String(Math.floor(s)).padStart(2, "0");
  const body = h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
  return (neg ? "-" : "") + body;
}

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Binary search: index of the last element with arr[i].t <= t, or -1. */
export function lastAtOrBefore(arr, t, key = (x) => x.t) {
  let lo = 0, hi = arr.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (key(arr[mid]) <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

/** Index of the first element with arr[i].t >= t (arr.length if none). */
export function firstAtOrAfter(arr, t, key = (x) => x.t) {
  let lo = 0, hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (key(arr[mid]) < t) lo = mid + 1; else hi = mid;
  }
  return lo;
}

export function toast(msg, kind = "error", ms = 6000) {
  const host = $("#toasts");
  if (!host) { console.error(msg); return; }
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  el.addEventListener("click", () => el.remove());
  host.appendChild(el);
  setTimeout(() => el.remove(), ms);
}
