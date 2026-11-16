// node tests of the pure run helpers of js/features/runs/runs.js (p6-02; audit 8.2; extracted from app.js in p6-04).
// Expected literals were printed by running the current Lab modules in the js-check image (p6-02); do not edit by hand.
import test from "node:test";
import assert from "node:assert/strict";
import { windowKey, runDepth, runOrientation, runLabel, isActive } from "../../lab/static/js/features/runs/runs.js";

test("windowKey: landscape or portrait-<side>", () => {
  assert.deepEqual(windowKey({}), 'landscape');
  assert.deepEqual(windowKey(null), 'landscape');
  assert.deepEqual(windowKey(undefined), 'landscape');
  assert.deepEqual(windowKey({ orientation: "landscape" }), 'landscape');
  assert.deepEqual(windowKey({ orientation: "portrait", request: { side: "left" } }), 'portrait-left');
  assert.deepEqual(windowKey({ request: { orientation: "portrait", side: "center" } }), 'portrait-center');
  assert.deepEqual(windowKey({ orientation: "portrait", side: "right" }), 'portrait-right');
  assert.deepEqual(windowKey({ orientation: "portrait", request: { side: "left" }, side: "right" }), 'portrait-left');
  assert.deepEqual(windowKey({ orientation: "portrait" }), 'portrait-undefined');
  assert.deepEqual(windowKey({ request: { orientation: "landscape", side: "left" } }), 'landscape');
  assert.deepEqual(windowKey({ orientation: "other" }), 'landscape');
});

test("runDepth: model name, null for older runs and \"none\"", () => {
  assert.deepEqual(runDepth({}), null);
  assert.deepEqual(runDepth(null), null);
  assert.deepEqual(runDepth({ depth: "da3-small" }), 'da3-small');
  assert.deepEqual(runDepth({ request: { depth: "unidepth-v2-s" } }), 'unidepth-v2-s');
  assert.deepEqual(runDepth({ depth: "none" }), null);
  assert.deepEqual(runDepth({ depth: "none", request: { depth: "da3-base" } }), null);
  assert.deepEqual(runDepth({ depth: "", request: { depth: "da3-base" } }), null);
  assert.deepEqual(runDepth({ depth: null, request: { depth: "da3-base" } }), 'da3-base');
  assert.deepEqual(runDepth({ request: { depth: "none" } }), null);
});

test("runOrientation", () => {
  assert.deepEqual(runOrientation({}), 'landscape');
  assert.deepEqual(runOrientation(null), 'landscape');
  assert.deepEqual(runOrientation({ orientation: "portrait", request: { side: "left" } }), 'portrait · left');
  assert.deepEqual(runOrientation({ orientation: "portrait", side: "center" }), 'portrait · center');
  assert.deepEqual(runOrientation({ request: { orientation: "landscape", side: "right" } }), 'landscape · right');
  assert.deepEqual(runOrientation({ orientation: "landscape" }), 'landscape');
  assert.deepEqual(runOrientation({ request: { side: "left" } }), 'landscape · left');
});

test("runLabel: range, orientation, fps, input size, depth", () => {
  assert.deepEqual(runLabel({ request: { start: 0, end: 450, fps: 6 } }), '0:00 – 7:30 · landscape · 6 fps');
  assert.deepEqual(runLabel({ request: { start: 4929, end: 5379.5, fps: 2 }, inputSpec: { w: 1280, h: 736 } }), '1:22:09 – 1:29:39 · landscape · 2 fps · 1280×736');
  assert.deepEqual(runLabel({ request: { start: 61, end: 3661, fps: 10 }, orientation: "portrait", inputSpec: { w: 720, h: 1280 }, depth: "da3-small" }), '1:01 – 1:01:01 · portrait · 10 fps · 720×1280 · da3-small');
  assert.deepEqual(runLabel({ request: { start: 1, end: 2, fps: 6, side: "left", orientation: "portrait", depth: "none" } }), '0:01 – 0:02 · portrait · left · 6 fps');
  assert.deepEqual(runLabel({ request: { start: NaN, end: undefined, fps: 6 } }), '--:-- – --:-- · landscape · 6 fps');
  assert.deepEqual(runLabel({ request: { start: 0, end: 5, fps: 6, depth: "unidepth-v2-s" } }), '0:00 – 0:05 · landscape · 6 fps · unidepth-v2-s');
});

test("isActive: queued or running", () => {
  assert.deepEqual(isActive({ status: "queued" }), true);
  assert.deepEqual(isActive({ status: "running" }), true);
  assert.deepEqual(isActive({ status: "done" }), false);
  assert.deepEqual(isActive({ status: "failed" }), false);
  assert.deepEqual(isActive({ status: "cancelled" }), false);
  assert.deepEqual(isActive({}), false);
});
