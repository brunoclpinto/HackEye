// node tests of js/util/autofill.js (p6-02; audit 8.2): frameAt, orderCandidates, fillFor.
// Expected literals were printed by running the current Lab modules in the js-check image (p6-02); do not edit by hand.
import test from "node:test";
import assert from "node:assert/strict";
import { frameAt, orderCandidates, fillFor } from "../../lab/static/js/util/autofill.js";

test("frameAt: last analysed frame with t <= time; null outside the run", () => {
  assert.deepEqual(frameAt([{ t: 0, hazards: [] }, { t: 1, hazards: [] }, { t: 2.5, hazards: [] }], 0), { t: 0, hazards: [] });
  assert.deepEqual(frameAt([{ t: 0, hazards: [] }, { t: 1, hazards: [] }, { t: 2.5, hazards: [] }], 0.99), { t: 0, hazards: [] });
  assert.deepEqual(frameAt([{ t: 0, hazards: [] }, { t: 1, hazards: [] }, { t: 2.5, hazards: [] }], 1), { t: 1, hazards: [] });
  assert.deepEqual(frameAt([{ t: 0, hazards: [] }, { t: 1, hazards: [] }, { t: 2.5, hazards: [] }], 2), { t: 1, hazards: [] });
  assert.deepEqual(frameAt([{ t: 0, hazards: [] }, { t: 1, hazards: [] }, { t: 2.5, hazards: [] }], 2.5), { t: 2.5, hazards: [] });
  assert.deepEqual(frameAt([{ t: 0, hazards: [] }, { t: 1, hazards: [] }, { t: 2.5, hazards: [] }], 3.5), { t: 2.5, hazards: [] });
  assert.deepEqual(frameAt([{ t: 0, hazards: [] }, { t: 1, hazards: [] }, { t: 2.5, hazards: [] }], 3.6), null);
  assert.deepEqual(frameAt([{ t: 0, hazards: [] }, { t: 1, hazards: [] }, { t: 2.5, hazards: [] }], -0.1), null);
  assert.deepEqual(frameAt([{ t: 0, hazards: [] }, { t: 1, hazards: [] }, { t: 2.5, hazards: [] }], NaN), null);
  assert.deepEqual(frameAt([], 1), null);
  assert.deepEqual(frameAt(null, 1), null);
  assert.deepEqual(frameAt(undefined, 1), null);
  assert.deepEqual(frameAt([{ t: 5 }], 5.5), { t: 5 });
  assert.deepEqual(frameAt([{ t: 5 }], 6.5), null);
});

test("orderCandidates: role, then level, then steps ascending (nulls last), then input order", () => {
  const frame = { hazards: [
    { className: "a", role: "context", stepsTo: 1 }, { className: "b", role: "danger", stepsTo: 9 }, { className: "c", role: "danger", stepsTo: 3 },
    { className: "d", role: "final", stepsTo: 20 }, { className: "e", role: "feature", stepsTo: null }, { className: "f", role: "danger" },
    { className: "g", stepsTo: 0 }, { label: "h", role: "danger", stepsTo: 3 }, { className: "i", role: "weird", stepsTo: 0 } ] };
  const levels = { a: 5, b: 1, c: 1, e: 2, g: 9, h: 7 };
  const levelOf = (n) => levels[n];
  assert.deepEqual(orderCandidates(frame, levelOf).map((h) => h.className ?? h.label), [ 'd', 'h', 'c', 'b', 'f', 'e', 'a', 'g', 'i' ]);
  assert.deepEqual(orderCandidates(frame, undefined).map((h) => h.className ?? h.label), [ 'd', 'c', 'h', 'b', 'f', 'e', 'a', 'g', 'i' ]);
  assert.deepEqual(orderCandidates(frame, () => NaN).map((h) => h.className ?? h.label), [ 'd', 'c', 'h', 'b', 'f', 'e', 'a', 'g', 'i' ]);
  assert.deepEqual(orderCandidates(null, levelOf), []);
  assert.deepEqual(orderCandidates({}, levelOf), []);
  assert.deepEqual(orderCandidates({ hazards: [] }, levelOf), []);
  assert.deepEqual(orderCandidates(frame, levelOf)[0] === frame.hazards[3], true);
});

test("fillFor: default templates", () => {
  assert.deepEqual(fillFor({ label: "car", role: "danger", clockText: "1", stepsTo: 4.6 }), { text: 'car at 1 in 5', role: 'danger' });
  assert.deepEqual(fillFor({ className: "pole", role: "feature", clock: "11:45", stepsTo: 2.4 }), { text: 'pole at 11:45 in 2', role: 'feature' });
  assert.deepEqual(fillFor({ label: "bench", role: "context", clockText: "12", stepsTo: 7 }), { text: 'bench at 12 in 7', role: 'context' });
  assert.deepEqual(fillFor({ label: "wall", role: "final", clockText: "12", stepsTo: 0.4 }), { text: 'wall at 12 in 0', role: 'final' });
  assert.deepEqual(fillFor({ label: "bike", role: "danger", moving: true, closingMps: 1.2, clockText: "2:30", stepsTo: 6 }), { text: 'bike approaching at 2:30 in 6', role: 'danger' });
  assert.deepEqual(fillFor({ label: "bike", role: "danger", moving: true, closingMps: -1, clockText: "2:30", stepsTo: 6 }), { text: 'bike at 2:30 in 6', role: 'danger' });
  assert.deepEqual(fillFor({ label: "bike", role: "danger", moving: true, closingMps: 0, clockText: "2:30", stepsTo: 6 }), { text: 'bike at 2:30 in 6', role: 'danger' });
  assert.deepEqual(fillFor({ label: "bike", role: "context", moving: true, closingMps: 2, clockText: "2", stepsTo: 6 }), { text: 'bike at 2 in 6', role: 'context' });
  assert.deepEqual(fillFor({ label: "thing" }), { text: 'thing at ? in ?', role: 'danger' });
  assert.deepEqual(fillFor({}), { text: 'object at ? in ?', role: 'danger' });
  assert.deepEqual(fillFor({ className: "tree", role: "none", stepsTo: 3.5 }), { text: 'tree at ? in 4', role: 'danger' });
  assert.deepEqual(fillFor({ label: "x", className: "y", role: "surface" }), { text: 'x at ? in ?', role: 'surface' });
});

test("fillFor: templates override the defaults per key", () => {
  assert.deepEqual(fillFor({ label: "car", role: "danger", clockText: "1", stepsTo: 4.6 }, { danger: "Watch out, {label}, {steps} steps at {clock}" }), { text: 'Watch out, car, 5 steps at 1', role: 'danger' });
  assert.deepEqual(fillFor({ label: "bike", role: "danger", moving: true, closingMps: 3, clockText: "2", stepsTo: 6 }, { approach: "{label} coming, {steps}" }), { text: 'bike coming, 6', role: 'danger' });
  assert.deepEqual(fillFor({ label: "bike", role: "danger", clockText: "2", stepsTo: 6 }, { approach: "unused" }), { text: 'bike at 2 in 6', role: 'danger' });
  assert.deepEqual(fillFor({ label: "a", role: "final", stepsTo: 1 }, { final: "{label}{label}{clock}" }), { text: 'aa?', role: 'final' });
  assert.deepEqual(fillFor({ label: "a", role: "final", stepsTo: 1 }, null), { text: 'a at ? in 1', role: 'final' });
});
