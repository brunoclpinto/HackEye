// Small DOM helpers shared by several features (moved out of app.js).
import { clamp } from "./index.js";

export function setProgress(el, frac, text) {
  el.hidden = false;
  el.firstElementChild.style.width = `${clamp(frac, 0, 1) * 100}%`;
  el.lastElementChild.textContent = text ?? `${Math.round(frac * 100)}%`;
}

/** v26.2.11: the option whose value is the default shows " (default)" after its label (no separate "config default" entry). */
export function markDefault(sel, value) {
  for (const o of sel.options) {
    o.dataset.base ??= o.textContent;
    o.textContent = o.dataset.base + (value != null && o.value === String(value) ? " (default)" : "");
  }
}
