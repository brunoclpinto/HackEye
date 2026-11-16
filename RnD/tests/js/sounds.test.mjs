// node tests of the pitch slider maths of js/features/sounds/sounds.js (p6-02; audit 8.2).
// Expected literals were printed by running the current Lab modules in the js-check image (p6-02); do not edit by hand.
import test from "node:test";
import assert from "node:assert/strict";
import { sliderToHz, hzToSlider, PITCH_STEPS } from "../../lab/static/js/features/sounds/sounds.js";

test("PITCH_STEPS", () => {
  assert.deepEqual(PITCH_STEPS, 1000);
});

test("sliderToHz: logarithmic mapping, rounded to Hz", () => {
  assert.deepEqual(sliderToHz(0, 200, 2000), 200);
  assert.deepEqual(sliderToHz(500, 200, 2000), 632);
  assert.deepEqual(sliderToHz(1000, 200, 2000), 2000);
  assert.deepEqual(sliderToHz(250, 200, 2000), 356);
  assert.deepEqual(sliderToHz(750, 200, 2000), 1125);
  assert.deepEqual(sliderToHz(1, 200, 2000), 200);
  assert.deepEqual(sliderToHz(-50, 200, 2000), 200);
  assert.deepEqual(sliderToHz(5000, 200, 2000), 2000);
  assert.deepEqual(sliderToHz(500, 400, 400), 400);
  assert.deepEqual(sliderToHz(333, 150, 1200), 300);
  assert.deepEqual(sliderToHz(500.4, 300, 1500), 671);
});

test("hzToSlider: inverse, rounded, clamped to the range", () => {
  assert.deepEqual(hzToSlider(200, 200, 2000), 0);
  assert.deepEqual(hzToSlider(2000, 200, 2000), 1000);
  assert.deepEqual(hzToSlider(632, 200, 2000), 500);
  assert.deepEqual(hzToSlider(100, 200, 2000), 0);
  assert.deepEqual(hzToSlider(9999, 200, 2000), 1000);
  assert.deepEqual(hzToSlider(440, 200, 2000), 342);
  assert.deepEqual(hzToSlider(880, 300, 1500), 669);
});

test("round trip slider -> Hz -> slider stays within 1 step", () => {
  assert.deepEqual([0, 100, 333, 500, 777, 1000].map((v) => hzToSlider(sliderToHz(v, 200, 2000), 200, 2000)), [ 0, 100, 333, 500, 777, 1000 ]);
  assert.deepEqual([0, 100, 333, 500, 777, 1000].map((v) => hzToSlider(sliderToHz(v, 150, 1200), 150, 1200)), [ 0, 101, 333, 500, 777, 1000 ]);
});
