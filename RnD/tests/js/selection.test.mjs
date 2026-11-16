// node tests of js/util/selection.js (p6-02; audit 8.2): worldTrackOf, itemTooltip.
// Expected literals were printed by running the current Lab modules in the js-check image (p6-02); do not edit by hand.
import test from "node:test";
import assert from "node:assert/strict";
import { worldTrackOf, itemTooltip } from "../../lab/static/js/util/selection.js";

test("worldTrackOf: matches the image track id, skips dropped tracks", () => {
  assert.deepEqual(worldTrackOf({ worldTracks: [{ id: "w1", trackId: 7, state: "dropped", speedMps: 1 }, { id: "w2", trackId: 7, state: "active", speedMps: 1.26 }, { id: "w3", trackId: 8, state: "active" }] }, { trackId: 7 }), { id: 'w2', trackId: 7, state: 'active', speedMps: 1.26 });
  assert.deepEqual(worldTrackOf({ worldTracks: [{ id: "w1", trackId: 7, state: "dropped", speedMps: 1 }, { id: "w2", trackId: 7, state: "active", speedMps: 1.26 }, { id: "w3", trackId: 8, state: "active" }] }, { trackId: 8 }), { id: 'w3', trackId: 8, state: 'active' });
  assert.deepEqual(worldTrackOf({ worldTracks: [{ id: "w1", trackId: 7, state: "dropped", speedMps: 1 }, { id: "w2", trackId: 7, state: "active", speedMps: 1.26 }, { id: "w3", trackId: 8, state: "active" }] }, { trackId: 9 }), null);
  assert.deepEqual(worldTrackOf({ worldTracks: [{ id: "w1", trackId: 7, state: "dropped", speedMps: 1 }, { id: "w2", trackId: 7, state: "active", speedMps: 1.26 }, { id: "w3", trackId: 8, state: "active" }] }, { trackId: 0 }), null);
  assert.deepEqual(worldTrackOf({ worldTracks: [{ id: "w1", trackId: 7, state: "dropped", speedMps: 1 }, { id: "w2", trackId: 7, state: "active", speedMps: 1.26 }, { id: "w3", trackId: 8, state: "active" }] }, { trackId: null }), null);
  assert.deepEqual(worldTrackOf({ worldTracks: [{ id: "w1", trackId: 7, state: "dropped", speedMps: 1 }, { id: "w2", trackId: 7, state: "active", speedMps: 1.26 }, { id: "w3", trackId: 8, state: "active" }] }, {}), null);
  assert.deepEqual(worldTrackOf({ worldTracks: [{ id: "w1", trackId: 7, state: "dropped", speedMps: 1 }, { id: "w2", trackId: 7, state: "active", speedMps: 1.26 }, { id: "w3", trackId: 8, state: "active" }] }, null), null);
  assert.deepEqual(worldTrackOf({ worldTracks: [{ id: "w1", trackId: 7, state: "dropped", speedMps: 1 }, { id: "w2", trackId: 7, state: "active", speedMps: 1.26 }, { id: "w3", trackId: 8, state: "active" }] }, undefined), null);
  assert.deepEqual(worldTrackOf({}, { trackId: 1 }), null);
  assert.deepEqual(worldTrackOf(null, { trackId: 1 }), null);
  assert.deepEqual(worldTrackOf({ worldTracks: [{ trackId: 1, state: "dropped" }] }, { trackId: 1 }), null);
});

test("itemTooltip: full item", () => {
  assert.deepEqual(itemTooltip({ className: "car", role: "danger", trackId: 7, distanceM: 4.26, stepsTo: 5.94, clockText: "1", distanceSource: "depth" }, { worldTracks: [{ id: "w1", trackId: 7, state: "dropped", speedMps: 1 }, { id: "w2", trackId: 7, state: "active", speedMps: 1.26 }, { id: "w3", trackId: 8, state: "active" }] }), 'car · role danger · track 7\n4.3 m · 5.9 steps · 1\ndistance source depth\nworld track w2 · 1.3 m/s');
  assert.deepEqual(itemTooltip({ className: "pole", role: "feature", trackId: 8, distanceM: 12, stepsTo: 17.14, clock: "11:45", source: "ground" }, { worldTracks: [{ id: "w1", trackId: 7, state: "dropped", speedMps: 1 }, { id: "w2", trackId: 7, state: "active", speedMps: 1.26 }, { id: "w3", trackId: 8, state: "active" }] }), 'pole · role feature · track 8\n12.0 m · 17.1 steps · 11:45\ndistance source ground\nworld track w3 · ? m/s');
  assert.deepEqual(itemTooltip({ className: "pole", role: "feature", trackId: 8, distanceM: 12, stepsTo: 17.14, clock: "11:45", source: "ground" }, { worldTracks: [{ id: "w9", trackId: 8, state: "active" }] }), 'pole · role feature · track 8\n12.0 m · 17.1 steps · 11:45\ndistance source ground\nworld track w9 · ? m/s');
});

test("itemTooltip: missing fields print ?", () => {
  assert.deepEqual(itemTooltip({}, null), 'item · role none · track ?\n? m · ? steps · ?\ndistance source ?');
  assert.deepEqual(itemTooltip({ label: "x", trackId: 0, distanceM: NaN, stepsTo: Infinity }, undefined), 'x · role none · track 0\n? m · ? steps · ?\ndistance source ?');
  assert.deepEqual(itemTooltip({ className: "x", distanceM: 0.04, stepsTo: 0.05 }, {}), 'x · role none · track ?\n0.0 m · 0.1 steps · ?\ndistance source ?');
});
