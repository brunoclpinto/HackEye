// Static guard for the page's event bus (js/bus.js, v26.3.0 p6-04): emit() with no handler silently returns undefined, so every
// event name emitted anywhere under lab/static must have an on() handler, and every handler must be emitted somewhere.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const ROOT = new URL("../../lab/static/", import.meta.url).pathname;

function sources(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? sources(join(dir, e.name)) : e.name.endsWith(".js") ? [readFileSync(join(dir, e.name), "utf8")] : []);
}

const names = (re) => new Set(sources(ROOT).flatMap((s) => [...s.matchAll(re)].map((m) => m[1])));

test("every emitted bus event has a handler and every handler is emitted", () => {
  const emitted = names(/\bemit\("([\w-]+)"/g);
  const handled = names(/\bon\("([\w-]+)"/g);
  assert.ok(emitted.size > 0);
  assert.deepEqual([...emitted].filter((n) => !handled.has(n)), []);
  assert.deepEqual([...handled].filter((n) => !emitted.has(n)), []);
});
