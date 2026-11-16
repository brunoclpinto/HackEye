// node tests of the pure speech helpers of js/features/audio/speech.js (p6-02; audit 8.2).
// Expected literals were printed by running the current Lab modules in the js-check image (p6-02); do not edit by hand.
import test from "node:test";
import assert from "node:assert/strict";
import { speechPriority, pronounce, canonSoundKind, rankVoice, chooseEnglishVoice, speechPlan, stuckHint, SPEECH_PRIORITY, PRONUNCIATIONS, SOUND_KIND_ALIASES } from "../../lab/static/js/features/audio/speech.js";

test("SPEECH_PRIORITY / speechPriority: unknown roles rank 1", () => {
  assert.deepEqual(SPEECH_PRIORITY, { final: 5, danger: 4, feature: 3, surface: 2, context: 1 });
  assert.deepEqual(speechPriority("final"), 5);
  assert.deepEqual(speechPriority("danger"), 4);
  assert.deepEqual(speechPriority("feature"), 3);
  assert.deepEqual(speechPriority("surface"), 2);
  assert.deepEqual(speechPriority("context"), 1);
  assert.deepEqual(speechPriority("none"), 1);
  assert.deepEqual(speechPriority(undefined), 1);
  assert.deepEqual(speechPriority("bogus"), 1);
});

test("pronounce: curb -> kerb (display text is untouched elsewhere)", () => {
  assert.deepEqual(pronounce("curb ahead"), 'kerb ahead');
  assert.deepEqual(pronounce("Curb, CURB and curb"), 'kerb, kerb and kerb');
  assert.deepEqual(pronounce("curbside"), 'curbside');
  assert.deepEqual(pronounce("a curb-cut"), 'a kerb-cut');
  assert.deepEqual(pronounce("no match"), 'no match');
  assert.deepEqual(pronounce(""), '');
  assert.deepEqual(PRONUNCIATIONS.length, 1);
  assert.deepEqual(PRONUNCIATIONS[0][1], 'kerb');
});

test("canonSoundKind / SOUND_KIND_ALIASES", () => {
  assert.deepEqual(SOUND_KIND_ALIASES, { collision: 'collision-center', 'crosswalk-enter': 'crosswalk-in', 'crosswalk-exit': 'crosswalk-out' });
  assert.deepEqual(canonSoundKind("collision"), 'collision-center');
  assert.deepEqual(canonSoundKind("crosswalk-enter"), 'crosswalk-in');
  assert.deepEqual(canonSoundKind("crosswalk-exit"), 'crosswalk-out');
  assert.deepEqual(canonSoundKind("crosswalk-in"), 'crosswalk-in');
  assert.deepEqual(canonSoundKind("collision-left"), 'collision-left');
  assert.deepEqual(canonSoundKind(undefined), 'collision-center');
  assert.deepEqual(canonSoundKind(""), 'collision-center');
  assert.deepEqual(canonSoundKind(null), 'collision-center');
  assert.deepEqual(canonSoundKind("unknown-kind"), 'unknown-kind');
});

test("rankVoice: default > natural > Enhanced/Premium > en-US > localService (desktop: no Android bonus)", () => {
  assert.deepEqual(rankVoice({"name":"Samantha","lang":"en-US","localService":true,"default":true}), 1111);
  assert.deepEqual(rankVoice({"name":"Samantha","lang":"en-US","localService":true}), 111);
  assert.deepEqual(rankVoice({"name":"Samantha (Enhanced)","lang":"en-US","localService":true}), 131);
  assert.deepEqual(rankVoice({"name":"Karen (Premium)","lang":"en-AU"}), 120);
  assert.deepEqual(rankVoice({"name":"Unknown","lang":"en-US"}), 10);
  assert.deepEqual(rankVoice({"name":"Unknown","lang":"en_us"}), 10);
  assert.deepEqual(rankVoice({"name":"Unknown","lang":"en-GB","localService":true}), 1);
  assert.deepEqual(rankVoice({"name":"Unknown","lang":"en-GB"}), 0);
  assert.deepEqual(rankVoice({"name":"Google UK English Female","lang":"en-GB"}), 100);
  assert.deepEqual(rankVoice({"name":"Samanthas","lang":"en-US"}), 10);
  assert.deepEqual(rankVoice({}), 0);
  assert.deepEqual(rankVoice({"name":"","lang":"en-US","default":true}), 1010);
});

test("chooseEnglishVoice: best-ranked English voice, novelty voices skipped, null when none", () => {
  assert.deepEqual(chooseEnglishVoice([{"name":"Joana","lang":"pt-PT","default":true}, {"name":"Samantha","lang":"en-US","localService":true}, {"name":"Daniel","lang":"en-GB","localService":true}, {"name":"Albert","lang":"en-US","localService":true}, {"name":"Google US English","lang":"en_US"}, {"name":"Karen (Enhanced)","lang":"en-AU","localService":true}, {"name":"Thomas","lang":"fr-FR"}])?.name, 'Karen (Enhanced)');
  assert.deepEqual(chooseEnglishVoice([{"name":"Joana","lang":"pt-PT","default":true}, {"name":"Samantha","lang":"en-US","localService":true}, {"name":"Daniel","lang":"en-GB","localService":true}, {"name":"Albert","lang":"en-US","localService":true}, {"name":"Google US English","lang":"en_US"}, {"name":"Karen (Enhanced)","lang":"en-AU","localService":true}, {"name":"Thomas","lang":"fr-FR"}].slice(3))?.name, 'Karen (Enhanced)');
  assert.deepEqual(chooseEnglishVoice([{"name":"Albert","lang":"en-US"}, {"name":"alberto","lang":"en-GB"}, {"name":"Zarvox","lang":"en-US"}]), null);
  assert.deepEqual(chooseEnglishVoice([{"name":"Joana","lang":"pt-PT"}, {"name":"Thomas","lang":"fr-FR"}]), null);
  assert.deepEqual(chooseEnglishVoice([]), null);
  assert.deepEqual(chooseEnglishVoice([{"name":"A","lang":"en"}, {"name":"B","lang":"en-US","default":true}])?.name, 'B');
  assert.deepEqual(chooseEnglishVoice([{"name":"A","lang":"english"}, {"name":"B","lang":"EN-us"}])?.name, 'B');
  assert.deepEqual(chooseEnglishVoice([{ name: "NoLang" }]), null);
});

test("speechPlan: system when the default voice is English, otherwise english + ranked voice", () => {
  assert.deepEqual(speechPlan([{"name":"Joana","lang":"pt-PT","default":true}, {"name":"Samantha","lang":"en-US","localService":true}, {"name":"Daniel","lang":"en-GB","localService":true}, {"name":"Albert","lang":"en-US","localService":true}, {"name":"Google US English","lang":"en_US"}, {"name":"Karen (Enhanced)","lang":"en-AU","localService":true}, {"name":"Thomas","lang":"fr-FR"}]), { mode: 'english', voice: { name: 'Karen (Enhanced)', lang: 'en-AU', localService: true } });
  assert.deepEqual(speechPlan([{"name":"Samantha","lang":"en-US","default":true}, {"name":"Joana","lang":"pt-PT"}]), { mode: 'system', voice: null });
  assert.deepEqual(speechPlan([{"name":"Joana","lang":"pt-PT"}, {"name":"Samantha","lang":"en-US"}]), { mode: 'english', voice: { name: 'Samantha', lang: 'en-US' } });
  assert.deepEqual(speechPlan([{"name":"Daniel","lang":"en-GB"}]), { mode: 'system', voice: null });
  assert.deepEqual(speechPlan([{"name":"Joana","lang":"pt-PT"}]), { mode: 'english', voice: null });
  assert.deepEqual(speechPlan([]), { mode: 'english', voice: null });
  assert.deepEqual(speechPlan([{"name":"X","lang":"en_GB"}, {"name":"Y","lang":"de-DE","default":true}]), { mode: 'english', voice: { name: 'X', lang: 'en_GB' } });
});

test("stuckHint: advice per platform", () => {
  assert.deepEqual(stuckHint("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "iPhone", 5), 'Close the browser from the app switcher, then reopen it.');
  assert.deepEqual(stuckHint("Mozilla/5.0 (iPad)", "iPad", 5), 'Close the browser from the app switcher, then reopen it.');
  assert.deepEqual(stuckHint("Mozilla/5.0 CriOS/120", "", 0), 'Close the browser from the app switcher, then reopen it.');
  assert.deepEqual(stuckHint("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "MacIntel", 5), 'Close the browser from the app switcher, then reopen it.');
  assert.deepEqual(stuckHint("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "MacIntel", 0), 'Quit Chrome with Cmd+Q (closing the window is not enough), then reopen it.');
  assert.deepEqual(stuckHint("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "MacIntel", 1), 'Quit Chrome with Cmd+Q (closing the window is not enough), then reopen it.');
  assert.deepEqual(stuckHint("Mozilla/5.0 (X11; Linux x86_64)", "Linux x86_64", 0), 'Close all browser windows and reopen it.');
  assert.deepEqual(stuckHint("Mozilla/5.0 (Windows NT 10.0)", "Win32", 10), 'Close all browser windows and reopen it.');
  assert.deepEqual(stuckHint("", "", 0), 'Close all browser windows and reopen it.');
});
