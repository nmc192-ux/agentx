// Run with `npm test` (node --test; Node strips the types itself).
import assert from "node:assert/strict";
import { test } from "node:test";

import { NOT_FOUND_PATH, pathDecodes } from "./safePath.ts";

test("ordinary and well-escaped paths pass", () => {
  for (const p of ["/", "/agents/did:agentx:abc", "/agents/did%3Aagentx%3Aabc", "/@atlas",
    "/tag/%E0%A4%85", "/u/atlas/feed/ai-news", "/search?q=%ZZ".split("?")[0]!, "/a%20b"]) {
    assert.equal(pathDecodes(p), true, p);
  }
});

test("a malformed escape anywhere is caught", () => {
  for (const p of ["/agents/%E0%A4%A", "/labelers/%E0%A4%A", "/feeds/%", "/tag/abc%ZZ",
    "/@%E0%A4%A", "/%C3%28", "/u/x/feed/%FF"]) {
    assert.equal(pathDecodes(p), false, p);
  }
});

test("the 404 target itself decodes and is not a real route", () => {
  assert.equal(pathDecodes(NOT_FOUND_PATH), true);
  assert.match(NOT_FOUND_PATH, /^\/_agentx_/);
});
