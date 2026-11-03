// v26.2.10: the selection shared by the video overlay and the world map, and the hover tooltip.
// An ITEM is selected as a whole and followed by its track id (and class) frame to frame; a REGION (map only) is the 8-connected
// same-class cells of the snapshot shown around a clicked object-layer cell. Esc or a click on nothing clears it.
import { $ } from "./util.js";

export class Selection {
  constructor() {
    this.item = null;          // {trackId, className, h}: h = the hazard clicked (matched by identity when it has no track id)
    this.region = null;        // {col, row, classId}: the seed cell and the class of the clicked object-layer cell
    this.listeners = [];
  }

  onChange(fn) { this.listeners.push(fn); }

  _fire() { for (const fn of this.listeners) fn(this); }

  selectItem(h) {
    this.item = { trackId: h.trackId ?? null, className: h.className, h };
    this.region = null;
    this._fire();
  }

  selectRegion(region) {
    this.region = region;
    this.item = null;
    this._fire();
  }

  clear() {
    if (!this.item && !this.region) return;
    this.item = null; this.region = null;
    this._fire();
  }

  /** The selected item as it is in `frame` (matched by track id + class), or null when it is not there. */
  find(frame) {
    const it = this.item;
    if (!it || !frame) return null;
    const hs = frame.hazards ?? [];
    return it.trackId !== null ? hs.find((h) => h.trackId === it.trackId && h.className === it.className) ?? null
      : hs.find((h) => h === it.h) ?? null;
  }
}

/** The world track of the frame that carries this item's image track id (shadow mode), or null. */
export function worldTrackOf(frame, h) {
  if (h?.trackId === null || h?.trackId === undefined) return null;
  return (frame?.worldTracks ?? []).find((w) => w.trackId === h.trackId && w.state !== "dropped") ?? null;
}

/** The hover text of one item: class, role, track, distance (m + steps), clock, distance source, world track + speed. */
export function itemTooltip(h, frame) {
  const num = (v, d) => (Number.isFinite(v) ? v.toFixed(d) : "?");
  const lines = [`${h.className ?? h.label ?? "item"} · role ${h.role ?? "none"} · track ${h.trackId ?? "?"}`,
    `${num(h.distanceM, 1)} m · ${num(h.stepsTo, 1)} steps · ${h.clockText ?? h.clock ?? "?"}`,
    `distance source ${h.distanceSource ?? h.source ?? "?"}`];
  const w = worldTrackOf(frame, h);
  if (w) lines.push(`world track ${w.id} · ${num(w.speedMps, 1)} m/s`);
  return lines.join("\n");
}

let tip = null;
/** Show the tooltip `text` next to the pointer (client coordinates); null hides it. */
export function showTip(text, clientX, clientY) {
  tip ??= $("#itemTip");
  if (!tip) return;
  if (text === null) { tip.hidden = true; return; }
  if (tip.textContent !== text) tip.textContent = text;
  tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = `${Math.max(4, Math.min(clientX + 14, window.innerWidth - w - 4))}px`;
  tip.style.top = `${Math.max(4, Math.min(clientY + 14, window.innerHeight - h - 4))}px`;
}
