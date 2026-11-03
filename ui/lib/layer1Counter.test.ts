// Run with `npm test` (node --test; Node strips the types itself).
import assert from "node:assert/strict";
import { test } from "node:test";

import { layer1Percent, layer1Text, parseLayer1Counter } from "./layer1Counter.ts";

const good = { outside_posters_7d: 12, target: 25, window_days: 7, as_of: "2026-11-04T00:00:00Z" };

test("a good answer parses", () => {
  assert.deepEqual(parseLayer1Counter(200, good),
    { outside_posters_7d: 12, target: 25, window_days: 7 });
});

test("errors and odd bodies give null, never a made-up number", () => {
  assert.equal(parseLayer1Counter(503, good), null);
  assert.equal(parseLayer1Counter(404, null), null);
  assert.equal(parseLayer1Counter(200, null), null);
  assert.equal(parseLayer1Counter(200, "12"), null);
  assert.equal(parseLayer1Counter(200, { ...good, outside_posters_7d: "12" }), null);
  assert.equal(parseLayer1Counter(200, { ...good, outside_posters_7d: -1 }), null);
  assert.equal(parseLayer1Counter(200, { ...good, target: 0 }), null);
  assert.equal(parseLayer1Counter(200, { ...good, window_days: Number.NaN }), null);
});

test("text and bar", () => {
  const c = parseLayer1Counter(200, good)!;
  assert.equal(layer1Text(c), "12 of 25");
  assert.equal(layer1Percent(c), 48);
  assert.equal(layer1Percent({ ...c, outside_posters_7d: 40 }), 100);
  assert.equal(layer1Percent({ ...c, outside_posters_7d: 0 }), 0);
});
