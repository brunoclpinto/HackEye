// Cross-language pin (p6-02): js/util/clock.js (clockQuarter / clockText) must match engine.core.clock.clock_quarter / clock_text.
// tests/fixtures/clock_cases.json was printed by the Python functions (bearings -180..180 step 7.5 plus edge cases).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { clockQuarter, clockText } from "../../lab/static/js/util/clock.js";

const fixture = JSON.parse(readFileSync(new URL("../fixtures/clock_cases.json", import.meta.url), "utf8"));

test("fixture is the expected size", () => {
  assert.ok(fixture.bearings.length >= 60);
  assert.ok(fixture.quarters.length >= 73);
});

test("clockQuarter matches engine.core.clock.clock_quarter for every fixture bearing", () => {
  for (const c of fixture.bearings) {
    // `===` on purpose: for small negative bearings the JS function returns -0, Python 0 (same value, not Object.is-equal).
    assert.ok(clockQuarter(c.bearing) === c.quarter, `clockQuarter(${c.bearing}) = ${clockQuarter(c.bearing)}, expected ${c.quarter}`);
  }
});

test("clockText matches engine.core.clock.clock_text for every fixture quarter index", () => {
  for (const c of fixture.quarters) assert.equal(clockText(c.quarter), c.text, `clockText(${c.quarter})`);
});

test("clockText(clockQuarter(bearing)) matches the Python text for every fixture bearing", () => {
  for (const c of fixture.bearings) assert.equal(clockText(clockQuarter(c.bearing)), c.text, `bearing ${c.bearing}`);
});

test("spot checks of the documented examples", () => {
  assert.equal(clockText(0), "12");
  assert.equal(clockText(1), "12:15");
  assert.equal(clockText(-1), "11:45");
  assert.equal(clockText(4), "1");
  assert.equal(clockText(-12), "9");
  assert.ok(clockQuarter(90) === 12 && clockQuarter(-90) === -12 && clockQuarter(500) === 12 && clockQuarter(-500) === -12);
});
