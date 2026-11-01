// Run with `npm test`. Layer 1 (S1-7): agents are not sent to hidden website pages.
// The developer page may list API endpoints as text, but must not link to a hidden page;
// skill.md (platform/src/a2a/skill.py) may only point at website pages that are visible.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { layerForPath } from "./layers.ts";

const ROOT = join(import.meta.dirname, "..");

test("developer page has no link to a hidden page", () => {
  const src = readFileSync(join(ROOT, "app/developer/page.tsx"), "utf8");
  const hrefs = [...src.matchAll(/href=\{?["'`](\/[^"'`?#]*)/g)].map((m) => m[1]);
  for (const h of hrefs) assert.equal(layerForPath(h), null, `developer page links to hidden ${h}`);
});

test("skill.md only sends agents to visible website pages", () => {
  const src = readFileSync(join(ROOT, "../platform/src/a2a/skill.py"), "utf8");
  const pages = [...src.matchAll(/\{site_url\}(\/[A-Za-z0-9_\-/]*)/g)].map((m) => m[1]);
  assert.ok(pages.includes("/join"));
  for (const p of pages) assert.equal(layerForPath(p), null, `skill.md links to hidden ${p}`);
});
