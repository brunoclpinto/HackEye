// node tests of js/util/eta.js (p6-02; audit 8.2): formatEta, EtaTracker.label(run, now), runStartMs, constants.
// Expected literals were printed by running the current Lab modules in the js-check image (p6-02); do not edit by hand.
import test from "node:test";
import assert from "node:assert/strict";
import { formatEta, EtaTracker, runStartMs, WINDOW_S, MIN_SPAN_S, MIN_DP, STALL_S, REFRESH_S } from "../../lab/static/js/util/eta.js";

test("constants", () => {
  assert.deepEqual([WINDOW_S, MIN_SPAN_S, MIN_DP, STALL_S, REFRESH_S], [ 60, 10, 0.02, 60, 5 ]);
});

test("formatEta", () => {
  assert.deepEqual(formatEta(0), 'about 5 s');
  assert.deepEqual(formatEta(-3), 'about 5 s');
  assert.deepEqual(formatEta(1), 'about 5 s');
  assert.deepEqual(formatEta(7), 'about 5 s');
  assert.deepEqual(formatEta(12.4), 'about 10 s');
  assert.deepEqual(formatEta(40), 'about 40 s');
  assert.deepEqual(formatEta(57.4), 'about 55 s');
  assert.deepEqual(formatEta(59.9), 'about 60 s');
  assert.deepEqual(formatEta(60), 'about 1 min');
  assert.deepEqual(formatEta(89), 'about 1 min');
  assert.deepEqual(formatEta(90), 'about 2 min');
  assert.deepEqual(formatEta(180), 'about 3 min');
  assert.deepEqual(formatEta(3540), 'about 59 min');
  assert.deepEqual(formatEta(3599), 'about 1 h 00 min');
  assert.deepEqual(formatEta(3600), 'about 1 h 00 min');
  assert.deepEqual(formatEta(3900), 'about 1 h 05 min');
  assert.deepEqual(formatEta(7384), 'about 2 h 03 min');
  assert.deepEqual(formatEta(NaN), '');
  assert.deepEqual(formatEta(Infinity), '');
  assert.deepEqual(formatEta(undefined), '');
});

test("runStartMs: startedAt wins over createdAt", () => {
  assert.deepEqual(runStartMs({ startedAt: "2026-01-02T03:04:05Z", createdAt: "2026-01-01T00:00:00Z" }), 1767323045000);
  assert.deepEqual(runStartMs({ createdAt: "2026-01-01T00:00:00Z" }), 1767225600000);
  assert.deepEqual(runStartMs({ startedAt: "", createdAt: "2026-01-01T00:00:00Z" }), 1767225600000);
  assert.deepEqual(runStartMs({}), NaN);
  assert.deepEqual(runStartMs({ startedAt: "garbage" }), NaN);
});

test("EtaTracker: queued, estimating, then a counting-down ETA", () => {
  const tr = new EtaTracker();
  assert.deepEqual(tr.label({ status: "queued", progress: 0 }, 0), 'queued');
  assert.deepEqual(tr.label({ status: "running", progress: 0 }, 1000), 'running 0% · estimating…');
  assert.deepEqual(tr.label({ status: "running", progress: 0.01 }, 5000), 'running 1% · estimating…');
  assert.deepEqual(tr.label({ status: "running", progress: 0.05 }, 12000), 'running 5% · about 3 min left');
  assert.deepEqual(tr.label({ status: "running", progress: 0.1 }, 21000), 'running 10% · about 3 min left');
  assert.deepEqual(tr.label({ status: "running", progress: 0.15 }, 24000), 'running 15% · about 3 min left');
  assert.deepEqual(tr.label({ status: "running", progress: 0.2 }, 31000), 'running 20% · about 3 min left');
  assert.deepEqual(tr.label({ status: "running", progress: 0.4 }, 70000), 'running 40% · about 2 min left');
  assert.deepEqual(tr.label({ status: "running", progress: 0.9 }, 160000), 'running 90% · about 2 min left');
  assert.deepEqual(tr.label({ status: "done", progress: 1 }, 170000), 'done 100% · about 1 min left');
});

test("EtaTracker: stalled after 60 s without progress", () => {
  const tr = new EtaTracker();
  assert.deepEqual(tr.label({ status: "running", progress: 0.3 }, 0), 'running 30% · estimating…');
  assert.deepEqual(tr.label({ status: "running", progress: 0.3 }, 30000), 'running 30% · estimating…');
  assert.deepEqual(tr.label({ status: "running", progress: 0.3 }, 61000), 'running 30% · stalled?');
  assert.deepEqual(tr.label({ status: "running", progress: 0.3 }, 62000), 'running 30% · stalled?');
  assert.deepEqual(tr.label({ status: "running", progress: 0.31 }, 63000), 'running 31% · estimating…');
});

test("EtaTracker: opened mid-run uses the average since createdMs", () => {
  const tr = new EtaTracker(0);
  assert.deepEqual(tr.label({ status: "running", progress: 0.25 }, 100000), 'running 25% · about 5 min left');
  assert.deepEqual(tr.label({ status: "running", progress: 0.25 }, 101000), 'running 25% · about 5 min left');
  assert.deepEqual(tr.label({ status: "running", progress: 0.26 }, 104000), 'running 26% · about 5 min left');
});

test("EtaTracker: progress is clamped to 0..1 and missing progress counts as 0", () => {
  const tr = new EtaTracker();
  assert.deepEqual(tr.label({ status: "running", progress: 1.7 }, 0), 'running 100% · estimating…');
  assert.deepEqual(tr.label({ status: "running", progress: -2 }, 1000), 'running 0% · estimating…');
  assert.deepEqual(tr.label({ status: "running" }, 2000), 'running 0% · estimating…');
  assert.deepEqual(tr.label({ status: "failed", progress: 0.456 }, 3000), 'failed 46% · estimating…');
});
