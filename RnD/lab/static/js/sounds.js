// Sound tuner (v26.1.16): pitch (low <-> high), duration and repeat interval of every notification sound, and the speech speed.
// The profile is Lab-wide and lives on the server (GET/PUT /api/sounds, debug/lab/display/sounds.json): every browser shares it.
// Pitch, duration and speech speed apply to playback live (AudioEngine.setSounds); the intervals shape the tone schedule, so changing
// one offers "Apply timing to this run" (the collision pass reads the profile).
import { $, clamp } from "./util.js";
import { api } from "./api.js";

const SAVE_DEBOUNCE_MS = 400;
export const PITCH_STEPS = 1000;                       // slider resolution
export const sliderToHz = (v, lo, hi) => Math.round(lo * Math.pow(hi / lo, clamp(v, 0, PITCH_STEPS) / PITCH_STEPS));
export const hzToSlider = (hz, lo, hi) => Math.round(PITCH_STEPS * Math.log(clamp(hz, lo, hi) / lo) / Math.log(hi / lo));
const TEST_PAN = { "collision-left": -0.7, "collision-right": 0.7 };

export class SoundsPanel {
  /** `audio` = AudioEngine; `rerun` = async () => void re-running the collision pass of the open run (null/undefined: none open). */
  constructor({ audio, rerun, hasRun }) {
    this.audio = audio;
    this.rerun = rerun;
    this.hasRun = hasRun;
    this.data = null;                                  // GET /api/sounds
    this.values = {};                                  // kind -> {pitchHz, durationMs, intervalS}
    this.speechRate = 1;
    this.dirty = false;                                // an interval changed since the run was last scored with the profile
    this.saveTimer = null;
    this.saving = Promise.resolve();
  }

  async load() {
    try { this.data = await api("/api/sounds", { quiet: true }); } catch { this._status("Sounds: the server profile is not available."); return; }
    this._adopt(this.data);
    this._render();
  }

  _adopt(d) {
    this.values = Object.fromEntries(d.kinds.map((k) => [k.kind, { pitchHz: k.pitchHz, durationMs: k.durationMs, intervalS: k.intervalS }]));
    this.speechRate = d.speechRate;
    this._applyAudio();
  }

  _applyAudio() { this.audio.setSounds(this.values, this.speechRate); }

  _status(msg) { const s = $("#sndStatus"); if (s) s.textContent = msg; }

  _render() {
    const { ranges, kinds } = this.data;
    const body = $("#sndRows");
    body.textContent = "";
    for (const k of kinds) {
      const tr = document.createElement("tr");
      tr.dataset.kind = k.kind;
      const [lo, hi] = ranges.pitchHz, [dlo, dhi] = ranges.durationMs, [ilo, ihi] = ranges.intervalS;
      const unused = k.default.intervalS == null;
      tr.innerHTML = `
        <th scope="row">${k.label}</th>
        <td class="snd-pitch"><span class="snd-lo">low</span><input type="range" min="0" max="${PITCH_STEPS}" step="1" data-f="pitchHz" aria-label="${k.label}: pitch"><span class="snd-hi">high</span> <output class="mono" data-o="pitchHz"></output></td>
        <td><input type="number" class="snd-num" data-f="durationMs" min="${dlo}" max="${dhi}" step="10" aria-label="${k.label}: duration in ms"> <span class="muted">ms</span></td>
        <td><input type="number" class="snd-num" data-f="intervalS" min="${ilo}" max="${ihi}" step="0.05" ${unused ? "disabled" : ""} aria-label="${k.label}: repeat interval in s"> <span class="muted">s</span></td>
        <td><button type="button" class="snd-test" aria-label="Test ${k.label}">&#9654;</button></td>`;
      const v = this.values[k.kind];
      const slider = tr.querySelector('[data-f="pitchHz"]');
      slider.value = hzToSlider(v.pitchHz, lo, hi);
      tr.querySelector('[data-o="pitchHz"]').textContent = `${Math.round(v.pitchHz)} Hz`;
      tr.querySelector('[data-f="durationMs"]').value = Math.round(v.durationMs);
      tr.querySelector('[data-f="intervalS"]').value = unused ? "" : v.intervalS;
      slider.addEventListener("input", () => {
        const hz = sliderToHz(Number(slider.value), lo, hi);
        tr.querySelector('[data-o="pitchHz"]').textContent = `${hz} Hz`;
        this._set(k.kind, "pitchHz", hz);
      });
      for (const f of ["durationMs", "intervalS"]) {
        const inp = tr.querySelector(`[data-f="${f}"]`);
        inp.addEventListener("input", () => {
          const n = Number(inp.value);
          if (!Number.isFinite(n) || inp.value === "") return;
          this._set(k.kind, f, clamp(n, ...ranges[f]));
        });
        inp.addEventListener("change", () => { if (inp.value !== "") inp.value = this.values[k.kind][f]; });
      }
      tr.querySelector(".snd-test").addEventListener("click", () => {
        this.audio.testSound(k.kind, this.values[k.kind], TEST_PAN[k.kind] ?? 0).catch(() => {});
      });
      body.append(tr);
    }
    const rate = $("#sndSpeech");
    rate.min = ranges.speechRate[0]; rate.max = ranges.speechRate[1];
    rate.value = this.speechRate;
    $("#sndSpeechOut").textContent = `${this.speechRate.toFixed(2)}×`;
    if (!rate.dataset.wired) {
      rate.dataset.wired = "1";
      rate.addEventListener("input", () => {
        this.speechRate = clamp(Number(rate.value), ...this.data.ranges.speechRate);
        $("#sndSpeechOut").textContent = `${this.speechRate.toFixed(2)}×`;
        this._applyAudio();
        this._queueSave();
      });
      $("#sndSpeechTest").addEventListener("click", () => { this.audio.testSpeech(this.speechRate); });
      $("#sndReset").addEventListener("click", () => this.reset());
      $("#sndApply").addEventListener("click", () => this.apply());
    }
  }

  _set(kind, field, value) {
    this.values[kind][field] = value;
    if (field === "intervalS") { this.dirty = true; this._paintApply(); }
    this._applyAudio();
    this._queueSave();
  }

  _paintApply() {
    const b = $("#sndApply");
    b.hidden = !this.dirty;
    b.disabled = !this.hasRun?.();
    $("#sndApplyNote").hidden = !this.dirty;
  }

  /** Call when a run is opened / closed so that the Apply button follows. */
  runChanged() { this._paintApply(); }

  _queueSave() {
    clearTimeout(this.saveTimer);
    this._status("Saving…");
    this.saveTimer = setTimeout(() => this.flush(), SAVE_DEBOUNCE_MS);
  }

  /** Save now (also what a pending debounce does); resolves when the server has the profile. */
  flush() {
    clearTimeout(this.saveTimer);
    this.saveTimer = null;
    const body = { kinds: this.values, speechRate: this.speechRate };
    this.saving = this.saving.then(() => api("/api/sounds", { method: "PUT", body, quiet: true })).then(
      () => this._status("Saved for every device."), () => this._status("Saving failed: changes apply here only."));
    return this.saving;
  }

  async reset() {
    clearTimeout(this.saveTimer);
    try { this.data = await api("/api/sounds", { method: "DELETE" }); } catch { return; }
    this.dirty = true;                                 // the defaults may differ from what the run was scored with
    this._adopt(this.data);
    this._render();
    this._paintApply();
    this._status("Defaults restored.");
  }

  /** "Apply timing to this run": save, then re-run the collision pass (reads the profile) and report. */
  async apply() {
    const b = $("#sndApply");
    b.disabled = true;
    this._status("Saving…");
    try {
      await this.flush();
      this._status("Re-scoring this run…");
      const ok = await this.rerun?.();
      if (ok === false) throw new Error("rerun failed");
      this.dirty = false;
      this._status("Timing applied to this run.");
    } catch { this._status("Re-scoring failed (see the error)."); }
    this._paintApply();
  }
}
