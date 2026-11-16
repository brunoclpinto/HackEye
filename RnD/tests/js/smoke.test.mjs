// Proves the node test runner (tools/check.sh, js-check image) can import a Lab page module and run a pure function.
import test from "node:test";
import assert from "node:assert/strict";
import { parseTime } from "../../lab/static/js/util/index.js";

test("parseTime parses mm:ss and rejects garbage", () => {
  assert.equal(parseTime("1:30"), 90);
  assert.ok(Number.isNaN(parseTime("not a time")));
});
