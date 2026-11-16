// node tests of js/features/overlay/overlay.js pure helpers fullBox / fullOutline (p6-02; audit 8.2).
// Expected literals were printed by running the current Lab modules in the js-check image (p6-02); do not edit by hand.
import test from "node:test";
import assert from "node:assert/strict";
import { fullBox, fullOutline } from "../../lab/static/js/features/overlay/overlay.js";

test("fullBox: bboxFull (rows above the horizon included) wins over bbox", () => {
  assert.deepEqual(fullBox({ bbox: [0.1, 0.2, 0.3, 0.4], bboxFull: [0.1, 0, 0.3, 0.4] }), [ 0.1, 0, 0.3, 0.4 ]);
  assert.deepEqual(fullBox({ bbox: [0.1, 0.2, 0.3, 0.4] }), [ 0.1, 0.2, 0.3, 0.4 ]);
  assert.deepEqual(fullBox({ bbox: [0.1, 0.2, 0.3, 0.4], bboxFull: null }), [ 0.1, 0.2, 0.3, 0.4 ]);
  assert.deepEqual(fullBox({}), undefined);
  assert.deepEqual(fullBox({ bboxFull: [0, 0, 1, 1] }), [ 0, 0, 1, 1 ]);
});

test("fullOutline: outlineFull wins; a bboxFull without outlineFull means no outline (v26.2.14)", () => {
  assert.deepEqual(fullOutline({ outline: [[0, 0], [1, 0], [1, 1]], outlineFull: [[0, 0], [1, 0], [1, 1], [0, 1]] }), [ [ 0, 0 ], [ 1, 0 ], [ 1, 1 ], [ 0, 1 ] ]);
  assert.deepEqual(fullOutline({ outline: [[0, 0], [1, 0], [1, 1]] }), [ [ 0, 0 ], [ 1, 0 ], [ 1, 1 ] ]);
  assert.deepEqual(fullOutline({ outline: [[0, 0], [1, 0], [1, 1]], bboxFull: [0, 0, 1, 1] }), null);
  assert.deepEqual(fullOutline({ outline: [[0, 0], [1, 0], [1, 1]], bboxFull: [0, 0, 1, 1], outlineFull: [[0, 0], [1, 1], [0, 1]] }), [ [ 0, 0 ], [ 1, 1 ], [ 0, 1 ] ]);
  assert.deepEqual(fullOutline({}), undefined);
  assert.deepEqual(fullOutline({ outlineFull: null, outline: [[0, 0]] }), [ [ 0, 0 ] ]);
});
