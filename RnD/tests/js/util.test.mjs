// node tests of the pure helpers of js/util/index.js (p6-02; audit 8.2).
// Expected literals were printed by running the current Lab modules in the js-check image (p6-02); do not edit by hand.
import test from "node:test";
import assert from "node:assert/strict";
import { parseTime, fmtTime, clamp, lastAtOrBefore, firstAtOrAfter, eventRole, eventColor, beepRepeats, ROLES, URGENCY_RANK } from "../../lab/static/js/util/index.js";

test("parseTime: ss, mm:ss, hh:mm:ss, fractions", () => {
  assert.deepEqual(parseTime("90"), 90);
  assert.deepEqual(parseTime("1:30"), 90);
  assert.deepEqual(parseTime("1:02:03"), 3723);
  assert.deepEqual(parseTime("0:00.5"), 0.5);
  assert.deepEqual(parseTime(".5"), 0.5);
  assert.deepEqual(parseTime("  2:05 "), 125);
  assert.deepEqual(parseTime("1.5"), 1.5);
  assert.deepEqual(parseTime(7), 7);
  assert.deepEqual(parseTime("0"), 0);
  assert.deepEqual(parseTime("10:00:00"), 36000);
});

test("parseTime: invalid input is NaN", () => {
  assert.deepEqual(parseTime(""), NaN);
  assert.deepEqual(parseTime("   "), NaN);
  assert.deepEqual(parseTime(null), NaN);
  assert.deepEqual(parseTime(undefined), NaN);
  assert.deepEqual(parseTime("a:b"), NaN);
  assert.deepEqual(parseTime("1:2:3:4"), NaN);
  assert.deepEqual(parseTime("-5"), NaN);
  assert.deepEqual(parseTime("1:"), NaN);
  assert.deepEqual(parseTime("12abc"), NaN);
  assert.deepEqual(parseTime("1,5"), NaN);
  assert.deepEqual(parseTime("1:-3"), NaN);
});

test("fmtTime: m:ss / h:mm:ss", () => {
  assert.deepEqual(fmtTime(0), '0:00');
  assert.deepEqual(fmtTime(5), '0:05');
  assert.deepEqual(fmtTime(59), '0:59');
  assert.deepEqual(fmtTime(60), '1:00');
  assert.deepEqual(fmtTime(61), '1:01');
  assert.deepEqual(fmtTime(599.9), '9:59');
  assert.deepEqual(fmtTime(3599), '59:59');
  assert.deepEqual(fmtTime(3600), '1:00:00');
  assert.deepEqual(fmtTime(3661), '1:01:01');
  assert.deepEqual(fmtTime(86399), '23:59:59');
  assert.deepEqual(fmtTime(4929), '1:22:09');
});

test("fmtTime: decimals floor, never round up to 60", () => {
  assert.deepEqual(fmtTime(59.96), '0:59');
  assert.deepEqual(fmtTime(59.96, 1), '0:59.9');
  assert.deepEqual(fmtTime(59.96, 2), '0:59.96');
  assert.deepEqual(fmtTime(3661.5, 1), '1:01:01.5');
  assert.deepEqual(fmtTime(125.678, 2), '2:05.67');
  assert.deepEqual(fmtTime(5.05, 1), '0:05.0');
  assert.deepEqual(fmtTime(0.04, 1), '0:00.0');
  assert.deepEqual(fmtTime(7, 3), '0:07.000');
  assert.deepEqual(fmtTime(0.1 + 0.2, 1), '0:00.3');
});

test("fmtTime: negative and non-finite", () => {
  assert.deepEqual(fmtTime(-5), '-0:05');
  assert.deepEqual(fmtTime(-0.5, 1), '-0:00.5');
  assert.deepEqual(fmtTime(-3725), '-1:02:05');
  assert.deepEqual(fmtTime(NaN), '--:--');
  assert.deepEqual(fmtTime(Infinity), '--:--');
  assert.deepEqual(fmtTime(-Infinity), '--:--');
  assert.deepEqual(fmtTime(undefined), '--:--');
  assert.deepEqual(fmtTime(null), '--:--');
  assert.deepEqual(fmtTime("12"), '--:--');
});

test("clamp", () => {
  assert.deepEqual(clamp(5, 0, 10), 5);
  assert.deepEqual(clamp(-1, 0, 10), 0);
  assert.deepEqual(clamp(11, 0, 10), 10);
  assert.deepEqual(clamp(0, 0, 10), 0);
  assert.deepEqual(clamp(10, 0, 10), 10);
  assert.deepEqual(clamp(0.5, 0, 1), 0.5);
  assert.deepEqual(clamp(NaN, 0, 1), NaN);
  assert.deepEqual(clamp(3, 5, 2), 2);
});

test("lastAtOrBefore: binary search on .t", () => {
  assert.deepEqual(lastAtOrBefore([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], -1), -1);
  assert.deepEqual(lastAtOrBefore([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 0), 0);
  assert.deepEqual(lastAtOrBefore([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 0.5), 0);
  assert.deepEqual(lastAtOrBefore([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 1), 1);
  assert.deepEqual(lastAtOrBefore([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 2), 3);
  assert.deepEqual(lastAtOrBefore([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 4.9), 3);
  assert.deepEqual(lastAtOrBefore([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 5), 4);
  assert.deepEqual(lastAtOrBefore([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 99), 4);
  assert.deepEqual(lastAtOrBefore([], 3), -1);
  assert.deepEqual(lastAtOrBefore([{ t: 4 }], 3), -1);
  assert.deepEqual(lastAtOrBefore([{ t: 4 }], 4), 0);
});

test("lastAtOrBefore: custom key", () => {
  assert.deepEqual(lastAtOrBefore([1, 3, 5, 7], 4, (x) => x), 1);
  assert.deepEqual(lastAtOrBefore([1, 3, 5, 7], 0, (x) => x), -1);
  assert.deepEqual(lastAtOrBefore([{ at: 1 }, { at: 9 }], 9, (x) => x.at), 1);
});

test("firstAtOrAfter: binary search on .t", () => {
  assert.deepEqual(firstAtOrAfter([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], -1), 0);
  assert.deepEqual(firstAtOrAfter([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 0), 0);
  assert.deepEqual(firstAtOrAfter([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 0.5), 1);
  assert.deepEqual(firstAtOrAfter([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 2), 2);
  assert.deepEqual(firstAtOrAfter([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 2.1), 4);
  assert.deepEqual(firstAtOrAfter([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 5), 4);
  assert.deepEqual(firstAtOrAfter([{ t: 0 }, { t: 1 }, { t: 2 }, { t: 2 }, { t: 5 }], 5.1), 5);
  assert.deepEqual(firstAtOrAfter([], 3), 0);
  assert.deepEqual(firstAtOrAfter([1, 3, 5, 7], 4, (x) => x), 2);
});

test("eventRole / eventColor", () => {
  assert.deepEqual(eventRole({ role: "feature" }), 'feature');
  assert.deepEqual(eventRole({}), 'danger');
  assert.deepEqual(eventRole({ role: null }), 'danger');
  assert.deepEqual(eventRole({ urgency: "caution" }), 'danger');
  assert.deepEqual(eventColor({ role: "danger" }), '#ff8c1a');
  assert.deepEqual(eventColor({ role: "final" }), '#ff2d2d');
  assert.deepEqual(eventColor({ role: "feature" }), '#22d3ee');
  assert.deepEqual(eventColor({ role: "context" }), '#c9ced6');
  assert.deepEqual(eventColor({ role: "surface" }), '#a78bfa');
  assert.deepEqual(eventColor({ role: "none" }), '#6b7280');
  assert.deepEqual(eventColor({}), '#6b7280');
  assert.deepEqual(eventColor({ role: "bogus" }), '#6b7280');
  assert.deepEqual(eventColor({ urgency: "caution" }), '#f5c518');
  assert.deepEqual(eventColor({ urgency: "warning" }), '#ff8c1a');
  assert.deepEqual(eventColor({ urgency: "imminent" }), '#ff2d2d');
  assert.deepEqual(eventColor({ role: "danger", urgency: "caution" }), '#ff8c1a');
  assert.deepEqual(eventColor({ role: "bogus", urgency: "imminent" }), '#ff2d2d');
});

test("constants: ROLES order and URGENCY_RANK", () => {
  assert.deepEqual(ROLES, [ 'context', 'surface', 'feature', 'danger', 'final' ]);
  assert.deepEqual(URGENCY_RANK, { none: 0, danger: 1, final: 2 });
});

test("beepRepeats: n and median interval", () => {
  assert.deepEqual(beepRepeats({ kind: "k", t: 1, tEnd: 2 }, [{ kind: "k", t: 1 }, { kind: "k", t: 1.5 }, { kind: "k", t: 2 }, { kind: "k", t: 2.5 }, { kind: "o", t: 1.2 }]), { n: 3, intervalS: 0.5 });
  assert.deepEqual(beepRepeats({ kind: "k", t: 1, tEnd: 3 }, [{ kind: "k", t: 3 }, { kind: "k", t: 1 }, { kind: "k", t: 1.2 }, { kind: "k", t: 2 }]), { n: 4, intervalS: 0.8 });
  assert.deepEqual(beepRepeats({ kind: "k", t: 1 }, [{ kind: "k", t: 1 }]), { n: 1, intervalS: null });
  assert.deepEqual(beepRepeats({ kind: "k", t: 1 }, [{ kind: "k", t: 1 }, { kind: "k", t: 1.0000001 }]), { n: 2, intervalS: 1.0000000005838672e-7 });
  assert.deepEqual(beepRepeats({ kind: "k", t: 1, tEnd: 4 }, [{ kind: "k", t: 0.5 }, { kind: "k", t: 4.5 }]), { n: 0, intervalS: null });
  assert.deepEqual(beepRepeats({ kind: "k", t: 1, tEnd: 4 }, []), { n: 0, intervalS: null });
  assert.deepEqual(beepRepeats({ kind: "k", t: 1, tEnd: 4 }, undefined), { n: 0, intervalS: null });
  assert.deepEqual(beepRepeats({ kind: "k", t: 1, tEnd: 4 }, null), { n: 0, intervalS: null });
  assert.deepEqual(beepRepeats({ kind: "k", t: 0, tEnd: 1 }, [{ kind: "k", t: 0 }, { kind: "k", t: 0.1 }, { kind: "k", t: 0.5 }, { kind: "k", t: 1 }]), { n: 4, intervalS: 0.4 });
});
