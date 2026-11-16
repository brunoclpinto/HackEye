// Pure speech helpers of the Lab audio player (no DOM, timers or window at load; importable in node). Moved verbatim from audio.js (v26.3.0 p6-03).

// Guarded for node (tests): the Android bonus of rankVoice is untested there.
export const ANDROID = typeof navigator !== "undefined" && /Android/i.test(navigator.userAgent || "");

export const SPEECH_PRIORITY = { final: 5, danger: 4, feature: 3, surface: 2, context: 1 };   // thin notices are role "feature"; unknown roles = 1
export const speechPriority = (role) => SPEECH_PRIORITY[role] ?? 1;

export const PRONUNCIATIONS = [[/\bcurb\b/gi, "kerb"]];
export function pronounce(text) {
  return PRONUNCIATIONS.reduce((s, [re, to]) => s.replace(re, to), text);
}

// v26.1.16: the Lab-wide sound profile (GET/PUT /api/sounds). Pitch and duration per sound kind and the speech speed apply to playback
// live (the player overrides the event's own values); the repeat intervals shape the tone schedule, so they need a collision re-run.
export const SOUND_KIND_ALIASES = { collision: "collision-center", "crosswalk-enter": "crosswalk-in", "crosswalk-exit": "crosswalk-out" };
export const canonSoundKind = (kind) => (kind ? SOUND_KIND_ALIASES[kind] ?? kind : "collision-center");

// macOS novelty / Eloquence voices (v26.1.11 follow-up: Chrome macOS picked "Albert"): never chosen (name prefix, case-insensitive).
const NOVELTY_VOICES = ["Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Good News", "Jester", "Organ", "Superstar",
  "Trinoids", "Whisper", "Wobble", "Zarvox", "Fred", "Junior", "Ralph", "Kathy", "Eddy", "Flo", "Grandma", "Grandpa", "Reed", "Rocko", "Sandy", "Shelley"]
  .map((n) => n.toLowerCase());
const NATURAL_VOICES = /^(Samantha|Alex|Google US English|Google UK English (Female|Male)|Daniel|Karen|Moira|Tessa|Serena|Ava|Allison|Susan|Tom|Nicky)\b/i;
// Ranking: [Android: localService] > default English voice of the platform > known natural voice ((Enhanced)/(Premium) first) > en-US > any en.
export function rankVoice(v) {
  const name = v.name || "";
  return (v.localService && ANDROID ? 10000 : 0) + (v.default ? 1000 : 0) + (NATURAL_VOICES.test(name) ? 100 : 0)
    + (/\((Enhanced|Premium)\)/i.test(name) ? 20 : 0) + (/^en[-_]US$/i.test(v.lang) ? 10 : 0) + (v.localService ? 1 : 0);
}
export function chooseEnglishVoice(voices) {
  const en = voices.filter((v) => /^en([-_]|$)/i.test(v.lang || "") && !NOVELTY_VOICES.some((n) => (v.name || "").toLowerCase().startsWith(n)));
  return en.sort((a, b) => rankVoice(b) - rankVoice(a))[0] || null;
}
// v26.1.11 follow-up 4: "system" mode = the voice the platform would use anyway is English, so speak as before v26.1.11
// (neither lang nor voice set). "english" mode = lang "en-US" + the ranked English voice (the default voice is another
// language, e.g. an iPhone listing Joana pt-PT first) or lang alone while the voices are not loaded / none is English.
export function speechPlan(voices) {
  const def = voices.find((v) => v.default) || voices[0];
  if (def && /^en([-_]|$)/i.test(def.lang || "")) return { mode: "system", voice: null };
  return { mode: "english", voice: chooseEnglishVoice(voices) };
}

export function stuckHint(ua = navigator.userAgent, platform = navigator.platform || "", touch = navigator.maxTouchPoints || 0) {
  if (/iPhone|iPad|iPod|CriOS/.test(ua) || (platform === "MacIntel" && touch > 1)) return "Close the browser from the app switcher, then reopen it.";
  if (/Macintosh|Mac OS X/.test(ua)) return "Quit Chrome with Cmd+Q (closing the window is not enough), then reopen it.";
  return "Close all browser windows and reopen it.";
}
