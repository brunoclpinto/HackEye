// node tests of the collision-run summary helpers of js/features/collisions/summary.js (p6-02; audit 8.2; extracted from app.js in p6-04; collSummary takes the first run as a parameter).
// Expected literals were printed by running the current Lab modules in the js-check image (p6-02); do not edit by hand.
import test from "node:test";
import assert from "node:assert/strict";
import { lsKey, shortVal, flatKeys, collTags, collSummary, collText } from "../../lab/static/js/features/collisions/summary.js";

test("lsKey", () => {
  assert.deepEqual(lsKey("r1"), 'lab.collision.r1');
  assert.deepEqual(lsKey(""), 'lab.collision.');
  assert.deepEqual(lsKey(undefined), 'lab.collision.undefined');
  assert.deepEqual(lsKey(12), 'lab.collision.12');
});

test("shortVal", () => {
  assert.deepEqual(shortVal(true), 'on');
  assert.deepEqual(shortVal(false), 'off');
  assert.deepEqual(shortVal(null), 'auto');
  assert.deepEqual(shortVal(undefined), 'auto');
  assert.deepEqual(shortVal(0), '0');
  assert.deepEqual(shortVal("ground"), 'ground');
  assert.deepEqual(shortVal(1.5), '1.5');
  assert.deepEqual(shortVal({ a: 1, b: [2, 3] }), '{"a":1,"b":[2,3]}');
  assert.deepEqual(shortVal([1, 2]), '[1,2]');
  assert.deepEqual(shortVal(""), '');
  assert.deepEqual(shortVal(NaN), 'NaN');
});

test("flatKeys: dotted keys, arrays and null are leaves", () => {
  assert.deepEqual(flatKeys({}), {});
  assert.deepEqual(flatKeys({ a: 1 }), { a: 1 });
  assert.deepEqual(flatKeys({ a: { b: 1, c: { d: "x" } }, e: [1, 2], f: null, g: false }), { 'a.b': 1, 'a.c.d': 'x', e: [ 1, 2 ], f: null, g: false });
  assert.deepEqual(flatKeys({ collision: { source: { mode: "map" } }, "speech": { predictive: { enabled: true } } }), { 'collision.source.mode': 'map', 'speech.predictive.enabled': true });
  assert.deepEqual(flatKeys({ a: 1 }, "p"), { 'p.a': 1 });
  assert.deepEqual(flatKeys({ a: { b: 1 } }, "p", { z: 0 }), { z: 0, 'p.a.b': 1 });
  assert.deepEqual(flatKeys(5), { '': 5 });
  assert.deepEqual(flatKeys(null), { '': null });
  assert.deepEqual(flatKeys([1, 2]), { '': [ 1, 2 ] });
  assert.deepEqual(flatKeys({ a: {} }), {});
});

test("collTags: tagged overrides and the effective object distance", () => {
  assert.deepEqual(collTags({}), []);
  assert.deepEqual(collTags({ overrides: { source: { mode: "map" } } }), [ { k: 'source', text: 'source map' } ]);
  assert.deepEqual(collTags({ overrides: { collision: { source: { mode: "map" }, speech: { predictive: { enabled: true } } } } }), [ { k: 'source', text: 'source map' }, { k: 'predictive', text: 'predictive on' } ]);
  assert.deepEqual(collTags({ overrides: { ego: { headingSource: "gyro", cadenceSource: "imu" }, horizon: { source: "gravity" }, roles: { dangerSteps: 4 } } }), [ { k: 'heading', text: 'heading gyro' }, { k: 'cadence', text: 'cadence imu' }, { k: 'horizon', text: 'horizon gravity' } ]);
  assert.deepEqual(collTags({ settings: { objectDistance: "ground-contact", useHorizon: false }, objectDistanceEffective: "depth" }), [ { k: 'objDist', text: 'ground-contact -> depth (horizon off)' } ]);
  assert.deepEqual(collTags({ settings: { objectDistance: "ground-contact" }, objectDistanceEffective: "depth" }), [ { k: 'objDist', text: 'ground-contact -> depth (horizon on)' } ]);
  assert.deepEqual(collTags({ settings: { objectDistance: "depth" }, objectDistanceEffective: "depth" }), []);
  assert.deepEqual(collTags({ settings: { objectDistance: "depth" } }), []);
  assert.deepEqual(collTags({ overrides: { source: { mode: "ground" } }, settings: { objectDistance: "a", useHorizon: true }, objectDistanceEffective: "b" }), [ { k: 'source', text: 'source ground' }, { k: 'objDist', text: 'a -> b (horizon on)' } ]);
});

test("collSummary: what differs from the first collision run", () => {
  assert.deepEqual(collSummary({ id: "c1" }, undefined), 'first');
  assert.deepEqual(collSummary({ id: "c1" }, { id: "c1", settings: { objectDistance: "ground+depth", useHorizon: true, cameraSide: "left", hfovDeg: 90 }, overrides: { collision: { roles: { dangerSteps: 6 } } } }), 'first');
  assert.deepEqual(collSummary({ id: "c2", settings: { objectDistance: "ground+depth", useHorizon: true, cameraSide: "left", hfovDeg: 90 }, overrides: { collision: { roles: { dangerSteps: 6 } } } }, { id: "c1", settings: { objectDistance: "ground+depth", useHorizon: true, cameraSide: "left", hfovDeg: 90 }, overrides: { collision: { roles: { dangerSteps: 6 } } } }), 'same settings');
  assert.deepEqual(collSummary({ id: "c2", settings: { objectDistance: "depth", useHorizon: false, cameraSide: "right", hfovDeg: 90 } }, { id: "c1", settings: { objectDistance: "ground+depth", useHorizon: true, cameraSide: "left", hfovDeg: 90 }, overrides: { collision: { roles: { dangerSteps: 6 } } } }), 'objDist depth · horizon off');
  assert.deepEqual(collSummary({ id: "c3", settings: { objectDistance: "ground+depth", useHorizon: true, hfovDeg: 120, projection: "fisheye", userHeightM: null }, overrides: { collision: { roles: { dangerSteps: 6, finalSteps: 2 }, tones: { speechRate: 1.2 } } } }, { id: "c1", settings: { objectDistance: "ground+depth", useHorizon: true, cameraSide: "left", hfovDeg: 90 }, overrides: { collision: { roles: { dangerSteps: 6 } } } }), 'hfov 120 · lens fisheye · height auto · finalSteps 2 · speechRate 1.2');
  assert.deepEqual(collSummary({ id: "c4", settings: { objectDistance: "ground+depth" }, overrides: { source: { mode: "map" }, collision: { roles: { dangerSteps: 7 } } } }, { id: "c1", settings: { objectDistance: "ground+depth", useHorizon: true, cameraSide: "left", hfovDeg: 90 }, overrides: { collision: { roles: { dangerSteps: 6 } } } }), 'dangerSteps 7');
  assert.deepEqual(collSummary({ id: "c5", settings: { mount: "head", stepLengthM: 0.65, orientation: "portrait", cameraLocation: "chest", cameraHeightM: 1.3, distanceSource: "da3" } }, { id: "c1", settings: { objectDistance: "ground+depth", useHorizon: true, cameraSide: "left", hfovDeg: 90 }, overrides: { collision: { roles: { dangerSteps: 6 } } } }), 'mount head · step 0.65 · orient portrait · loc chest · camH 1.3 · dist da3');
  assert.deepEqual(collSummary({ id: "c2" }, { id: "c1" }), 'same settings');
  assert.deepEqual(collSummary({ id: "c2", settings: { foo: { a: 1 } } }, { id: "c1", settings: { foo: { a: 2 } } }), 'foo {"a":1}');
  assert.deepEqual(collSummary({ id: "c2" }, null), 'first');
});

test("collText: id, label or summary (UTC clock)", () => {
  process.env.TZ = "UTC";
  assert.deepEqual(collText({ id: "c1", label: "my run", createdAt: "2026-11-16T14:05:09Z" }), 'c1 · my run · 14:05');
  assert.deepEqual(collText({ id: "c1", createdAt: "2026-11-16T09:30:00Z" }), 'c1 · first · 09:30');
  assert.deepEqual(collText({ id: "c2", label: "x", createdAt: "2026-11-16T00:07:00Z" }, { id: "c1" }), 'c2 · x · 00:07');
});
