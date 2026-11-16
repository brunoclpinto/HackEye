// node tests of the pure helpers of js/features/worldmap/worldmap.js (p6-02; audit 8.2).
// Expected literals were printed by running the current Lab modules in the js-check image (p6-02); do not edit by hand.
import test from "node:test";
import assert from "node:assert/strict";
import { isMassive, itemLine, markerOf, itemsNear, footprintOf, footprintDistance, regionOf, trackOf, worldTrackLine, wallEdgeSegments } from "../../lab/static/js/features/worldmap/worldmap.js";

// Floating-point results: compare recursively with a relative tolerance of 1e-9.
function close(actual, expected, path = "value") {
  if (typeof expected === "number") {
    assert.equal(typeof actual, "number", path);
    assert.ok(Math.abs(actual - expected) <= 1e-9 * Math.max(1, Math.abs(expected)), `${path}: ${actual} != ${expected}`);
  } else if (expected && typeof expected === "object") {
    assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort(), path);
    for (const k of Object.keys(expected)) close(actual[k], expected[k], `${path}.${k}`);
  } else assert.equal(actual, expected, path);
}

test("isMassive: building / bridge / tunnel as a whole word, case-insensitive", () => {
  assert.deepEqual(isMassive({ className: "building" }), true);
  assert.deepEqual(isMassive({ className: "Bridge" }), true);
  assert.deepEqual(isMassive({ className: "road tunnel" }), true);
  assert.deepEqual(isMassive({ className: "buildings" }), false);
  assert.deepEqual(isMassive({ className: "car" }), false);
  assert.deepEqual(isMassive({ className: "overbridge-x" }), false);
  assert.deepEqual(isMassive({}), false);
  assert.deepEqual(isMassive(null), false);
  assert.deepEqual(isMassive(undefined), false);
});

test("itemLine", () => {
  assert.deepEqual(itemLine({ className: "car", role: "danger", trackId: 7, distanceSource: "depth" }), 'car · role danger · track 7 · distance source depth');
  assert.deepEqual(itemLine({}), 'item · role none · track ? · distance source ?');
  assert.deepEqual(itemLine({ label: "pole", source: "ground", trackId: 0 }), 'pole · role none · track 0 · distance source ground');
  assert.deepEqual(itemLine({ className: "wall", role: "context", insideSolid: true }), 'wall · role context · track ? · distance source ? · inside solid');
  assert.deepEqual(itemLine({ className: "wall", insideSolid: true, solidCorrected: true }), 'wall · role none · track ? · distance source ? · inside solid (snapped)');
  assert.deepEqual(itemLine({ className: "man", coasting: true, ghost: true, insideSolid: true, role: "danger", trackId: 3, distanceSource: "tracking" }), 'man · role danger · track 3 · distance source tracking · inside solid, coasting, ghost');
});

test("markerOf: canvas position, drawn and hit radius", () => {
  close(markerOf({ lateralM: 0, distanceM: 0 }, 400), { x: 201, y: 401, r: 5.714285714285714, drawn: 5.714285714285714, hit: 5.714285714285714 });
  close(markerOf({ lateralM: 1.5, distanceM: 5 }, 400), { x: 231, y: 301, r: 5.714285714285714, drawn: 5.714285714285714, hit: 5.714285714285714 });
  close(markerOf({ lateralM: -2, distanceM: 10, role: "danger" }, 400), { x: 161, y: 201, r: 5.714285714285714, drawn: 11.428571428571429, hit: 11.428571428571429 });
  close(markerOf({ lateralM: 0.3, distanceM: 3, group: "moving" }, 400), { x: 207, y: 341, r: 8.571428571428571, drawn: 10.285714285714285, hit: 10.285714285714285 });
  close(markerOf({ lateralM: 0.3, distanceM: 3, group: "moving", role: "danger" }, 400), { x: 207, y: 341, r: 8.571428571428571, drawn: 17.142857142857142, hit: 17.142857142857142 });
  close(markerOf({ lateralM: 1, distanceM: 2 }, 100), { x: 55.25, y: 90.25, r: 3, drawn: 3, hit: 3 });
  close(markerOf({ lateralM: 1, distanceM: 2 }, 100, 8), { x: 55.25, y: 90.25, r: 3, drawn: 3, hit: 8 });
  close(markerOf({ lateralM: 1, distanceM: 2 }, 800, 8), { x: 442, y: 722, r: 11.428571428571429, drawn: 11.428571428571429, hit: 11.428571428571429 });
});

test("itemsNear: items within 0.3 m of the cell (map, solid-corrected raw and image positions)", () => {
  const frame = { hazards: [
    { className: "car", role: "danger", trackId: 1, distanceM: 5, lateralM: 1, distanceSource: "depth" },
    { className: "wall", trackId: 2, distanceM: 8, lateralM: -2, solidCorrected: true, insideSolid: true, rawDistanceM: 6, imageDistanceM: 7, imageLateralM: -1.5 },
    { label: "pole", distanceM: NaN, lateralM: 0, imageDistanceM: 3, imageLateralM: 0.5 },
    { className: "far", distanceM: 20, lateralM: 0 } ] };
  assert.deepEqual(itemsNear(frame, 5, 1), [ 'car · role danger · track 1 · distance source depth' ]);
  assert.deepEqual(itemsNear(frame, 5.2, 1.2), [ 'car · role danger · track 1 · distance source depth' ]);
  assert.deepEqual(itemsNear(frame, 5.4, 1), []);
  assert.deepEqual(itemsNear(frame, 6, -1.5), [ 'wall · role none · track 2 · distance source ? · inside solid (snapped)' ]);
  assert.deepEqual(itemsNear(frame, 7, -1.5), [ 'wall · role none · track 2 · distance source ? · inside solid (snapped)' ]);
  assert.deepEqual(itemsNear(frame, 3, 0.5), [ 'pole · role none · track ? · distance source ?' ]);
  assert.deepEqual(itemsNear(frame, 3.2, 0.6), [ 'pole · role none · track ? · distance source ?' ]);
  assert.deepEqual(itemsNear(frame, 0, 0), []);
  assert.deepEqual(itemsNear(frame, 20, 0), [ 'far · role none · track ? · distance source ?' ]);
  assert.deepEqual(itemsNear(frame, 5, 1).length, 1);
  assert.deepEqual(itemsNear(null, 5, 1), []);
  assert.deepEqual(itemsNear({}, 5, 1), []);
});

test("footprintOf: segment across the item's width (rectilinear, fisheye, no lens)", () => {
  close(footprintOf({ lateralM: 0, distanceM: 5, bbox: [0.4, 0.2, 0.6, 0.8] }, 400, { hfovDeg: 90, projection: "rectilinear" }), { x1: 181, y1: 301, x2: 221, y2: 301, x: 201, y: 301 });
  close(footprintOf({ lateralM: 1, distanceM: 5, bbox: [0.4, 0.2, 0.6, 0.8] }, 400, { hfovDeg: 90, projection: "fisheye" }), { x1: 205.16155596754638, y1: 301, x2: 236.83844403245362, y2: 301, x: 221, y: 301 });
  close(footprintOf({ lateralM: 1, distanceM: 5, bbox: [0.1, 0.2, 0.9, 0.8] }, 400, { hfovDeg: 120 }), { x1: 101, y1: 301, x2: 341, y2: 301, x: 221, y: 301 });
  close(footprintOf({ lateralM: 0, distanceM: 30, bbox: [0, 0, 1, 1] }, 400, { hfovDeg: 120 }), { x1: 81, y1: -199, x2: 321, y2: -199, x: 201, y: -199 });
  close(footprintOf({ lateralM: 0, distanceM: 5, bbox: [0.4, 0.2, 0.6, 0.8] }, 400, null), { x1: 201, y1: 301, x2: 201, y2: 301, x: 201, y: 301 });
  close(footprintOf({ lateralM: 0, distanceM: 5, bbox: [0.4, 0.2, 0.6, 0.8] }, 400, { hfovDeg: 0 }), { x1: 201, y1: 301, x2: 201, y2: 301, x: 201, y: 301 });
  close(footprintOf({ lateralM: 0, distanceM: 5 }, 400, { hfovDeg: 90 }), { x1: 201, y1: 301, x2: 201, y2: 301, x: 201, y: 301 });
  close(footprintOf({ lateralM: 0, distanceM: 0, bbox: [0.4, 0.2, 0.6, 0.8] }, 400, { hfovDeg: 90 }), { x1: 201, y1: 401, x2: 201, y2: 401, x: 201, y: 401 });
});

test("footprintDistance: point to segment, canvas px", () => {
  close(footprintDistance({ x1: 10, y1: 20, x2: 30, y2: 20 }, 20, 25), 5);
  close(footprintDistance({ x1: 10, y1: 20, x2: 30, y2: 20 }, 0, 20), 10);
  close(footprintDistance({ x1: 10, y1: 20, x2: 30, y2: 20 }, 33, 24), 5);
  close(footprintDistance({ x1: 10, y1: 20, x2: 30, y2: 20 }, 15, 20), 0);
  close(footprintDistance({ x1: 10, y1: 20, x2: 10, y2: 20 }, 13, 24), 5);
  close(footprintDistance({ x1: 0, y1: 0, x2: 10, y2: 10 }, 10, 0), 7.0710678118654755);
});

test("regionOf: 8-connected cells of the same class, null for unknown / outside", () => {
  const SZ = 6;
  const grid = new Uint8Array(SZ * SZ).fill(255);
  [[0, 0, 1], [0, 1, 1], [1, 1, 1], [3, 3, 1], [4, 4, 1], [2, 0, 2], [2, 1, 2], [5, 5, 2], [5, 4, 2], [0, 5, 3]].forEach(([r, c, v]) => { grid[r * SZ + c] = v; });
  const reg = (col, row) => { const r = regionOf(grid, col, row, SZ); return r && { count: r.count, classId: r.classId, cells: [...r.mask].flatMap((v, i) => (v ? [i] : [])), length: r.mask.length }; };
  assert.deepEqual(reg(0, 0), { count: 3, classId: 1, cells: [ 0, 1, 7 ], length: 36 });
  assert.deepEqual(reg(1, 1), { count: 3, classId: 1, cells: [ 0, 1, 7 ], length: 36 });
  assert.deepEqual(reg(0, 2), { count: 2, classId: 2, cells: [ 12, 13 ], length: 36 });
  assert.deepEqual(reg(3, 3), { count: 2, classId: 1, cells: [ 21, 28 ], length: 36 });
  assert.deepEqual(reg(4, 4), { count: 2, classId: 1, cells: [ 21, 28 ], length: 36 });
  assert.deepEqual(reg(5, 5), { count: 2, classId: 2, cells: [ 34, 35 ], length: 36 });
  assert.deepEqual(reg(5, 0), { count: 1, classId: 3, cells: [ 5 ], length: 36 });
  assert.deepEqual(reg(2, 2), null);
  assert.deepEqual(reg(9, 9), null);
  assert.deepEqual(regionOf(null, 0, 0, 6), null);
  assert.deepEqual(regionOf(undefined, 0, 0), null);
  assert.deepEqual(regionOf(grid, -1, 0, SZ), null);
});

test("trackOf: world track marker (1-sigma radius, hit radius)", () => {
  close(trackOf({ right: 0, fwd: 0 }, 400), { x: 201, y: 401, rad: 3, hit: 3 });
  close(trackOf({ right: 1, fwd: 5, sigmaM: 0.5 }, 400), { x: 221, y: 301, rad: 10, hit: 10 });
  close(trackOf({ right: -2, fwd: 10, sigmaM: 3 }, 400), { x: 161, y: 201, rad: 60, hit: 60 });
  close(trackOf({ right: 0, fwd: 2, sigmaM: 0.1 }, 400, 8), { x: 201, y: 361, rad: 3, hit: 8 });
  close(trackOf({ right: 0, fwd: 2, sigmaM: 0.1 }, 100, 8), { x: 50.25, y: 90.25, rad: 3, hit: 8 });
});

test("worldTrackLine: readout line, heading as a clock position seen from the ego heading", () => {
  assert.deepEqual(worldTrackLine({ id: "w1", class: "car", state: "active", speedMps: 1.234, headingDeg: 90, cpaM: 1.26, cpaS: 3.14, onCourse: true, sigmaM: 0.37, imageTracks: [3, 4] }), 'World track w1 · car · active · 1.2 m/s toward 3 · closest 1.3 m in 3.1 s (on course) · σ 0.4 m · images 3, 4');
  assert.deepEqual(worldTrackLine({ id: "w1", class: "car", state: "active", speedMps: 1.234, headingDeg: 90, cpaM: 1.26, cpaS: 3.14, onCourse: true, sigmaM: 0.37, imageTracks: [3, 4] }, 90), 'World track w1 · car · active · 1.2 m/s toward 12 · closest 1.3 m in 3.1 s (on course) · σ 0.4 m · images 3, 4');
  assert.deepEqual(worldTrackLine({ id: "w1", class: "car", state: "active", speedMps: 1.234, headingDeg: 90, cpaM: 1.26, cpaS: 3.14, onCourse: true, sigmaM: 0.37, imageTracks: [3, 4] }, -170), 'World track w1 · car · active · 1.2 m/s toward 9 · closest 1.3 m in 3.1 s (on course) · σ 0.4 m · images 3, 4');
  assert.deepEqual(worldTrackLine({ id: "w2", class: "person", state: "new", speedMps: 0.05, headingDeg: 10, imageTracks: [] }), 'World track w2 · person · new · 0.1 m/s · σ 0.0 m · images ');
  assert.deepEqual(worldTrackLine({ id: "w3", class: "bike", state: "lost", speedMps: 2, headingDeg: 180, cpaM: 4 }, 0), 'World track w3 · bike · lost · 2.0 m/s toward 9 · closest 4.0 m in 0.0 s · σ 0.0 m · images ');
  assert.deepEqual(worldTrackLine({ id: "w4", class: "x", state: "s", speedMps: 2, headingDeg: 355 }, 10), 'World track w4 · x · s · 2.0 m/s toward 11:30 · σ 0.0 m · images ');
  assert.deepEqual(worldTrackLine({ id: "w5", class: "x", state: "s", speedMps: 2 }), 'World track w5 · x · s · 2.0 m/s · σ 0.0 m · images ');
  assert.deepEqual(worldTrackLine({ id: "w6", class: "x", state: "s" }, 45), 'World track w6 · x · s · 0.0 m/s · σ 0.0 m · images ');
  assert.deepEqual(worldTrackLine({ id: "w7", class: "x", state: "s", speedMps: 1, headingDeg: 45, cpaM: 0.04, cpaS: 0.05, sigmaM: 2.25, imageTracks: [9] }, 0), 'World track w7 · x · s · 1.0 m/s toward 1:30 · closest 0.0 m in 0.1 s · σ 2.3 m · images 9');
});

test("wallEdgeSegments: borders between face cells and 4-neighbouring surface cells", () => {
  const g = new Uint8Array(16).fill(255);
  [[0, 1, 5], [1, 1, 5], [1, 2, 1], [2, 1, 1], [1, 0, 1], [2, 2, 7], [3, 3, 5], [3, 2, 1]].forEach(([r, c, v]) => { g[r * 4 + c] = v; });
  assert.deepEqual(wallEdgeSegments(g, [5], [1], 4), [ [ 2, 1, 2, 2 ], [ 1, 1, 1, 2 ], [ 1, 2, 2, 2 ], [ 3, 3, 3, 4 ] ]);
  assert.deepEqual(wallEdgeSegments(g, [5], [1, 7], 4), [ [ 2, 1, 2, 2 ], [ 1, 1, 1, 2 ], [ 1, 2, 2, 2 ], [ 3, 3, 3, 4 ] ]);
  assert.deepEqual(wallEdgeSegments(g, [5, 7], [1], 4), [ [ 2, 1, 2, 2 ], [ 1, 1, 1, 2 ], [ 1, 2, 2, 2 ], [ 2, 2, 2, 3 ], [ 2, 3, 3, 3 ], [ 2, 2, 3, 2 ], [ 3, 3, 3, 4 ] ]);
  assert.deepEqual(wallEdgeSegments(g, [], [1], 4), []);
  assert.deepEqual(wallEdgeSegments(g, [5], [], 4), []);
  assert.deepEqual(wallEdgeSegments(g, null, null, 4), []);
  assert.deepEqual(wallEdgeSegments(g, [9], [1], 4), []);
  assert.deepEqual(wallEdgeSegments(g, [1], [5], 4).length, 4);
});
