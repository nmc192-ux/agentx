// Run with `npm test`. Layer 1 (S1-3): the sitemap never lists a hidden layer.
import assert from "node:assert/strict";
import { test } from "node:test";

import { HIDDEN_LAYERS, layerForPath, visibleItems } from "./layers.ts";
import { SITEMAP_PATHS } from "./sitemapPaths.ts";

const layerFlags = Object.values(HIDDEN_LAYERS).map((l) => l.flag);
const allOff = Object.fromEntries([...layerFlags.map((f) => [f, false]), ["FEATURE_JOIN", true]]);
const allOn = Object.fromEntries([...layerFlags, "FEATURE_JOIN"].map((f) => [f, true]));

test("with all layer flags off, the sitemap lists no hidden page", () => {
  const shown = visibleItems(SITEMAP_PATHS, allOff);
  for (const p of shown) assert.equal(layerForPath(p.href), null, `sitemap lists ${p.href}`);
  for (const href of ["/", "/agents", "/trending", "/about"]) {
    assert.ok(shown.some((p) => p.href === href), `${href} missing`);
  }
});

test("with the flags on, the hidden pages come back", () => {
  const shown = visibleItems(SITEMAP_PATHS, allOn).map((p) => p.href);
  for (const href of ["/leaderboard", "/rooms", "/governance", "/capabilities", "/services", "/communities"]) {
    assert.ok(shown.includes(href), `${href} missing`);
  }
});
