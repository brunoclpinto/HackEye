// Shared page state: the `S` record, the singleton registry and the small helpers over them.
// Features import this module (never each other). bootstrap.js constructs the instances and calls register() once;
// the instance exports are live bindings, so a feature that imports `overlay` sees it once registered.
import { ROLES } from "./util/index.js";

export const S = {
  recs: [], rec: null, settings: null, config: null, models: null,
  runs: [], run: null, colls: [], cid: null, events: [], speech: [], tones: [], notes: [], roles: new Set(ROLES),
  pendingSeek: null, seekGen: 0, rangeTouched: false, runPoll: null, recPoll: null, loadedVideoRec: null,
};

export let video = null;
export let overlay = null, hazards = null, classesPanel = null, audio = null, sounds = null, notesPanel = null;
export let issuesPanel = null, worldmap = null, selection = null, timeline = null, reviews = null;

/** Called once by app/bootstrap.js after it constructed the page's instances. */
export function register(inst) {
  ({ video, overlay, hazards, classesPanel, audio, sounds, notesPanel, issuesPanel, worldmap, selection, timeline, reviews } = inst);
}

export const recById = (id) => S.recs.find((r) => r.id === id);
export const durOf = () => S.rec?.duration ?? video.duration ?? 0;
export const isNarrow = () => window.matchMedia("(max-width: 899px)").matches;
