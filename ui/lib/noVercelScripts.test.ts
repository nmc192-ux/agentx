// Run with `npm test` (node --test; Node strips the types itself).
// The site is served from the VPS, not Vercel, so Vercel's Analytics and
// Speed Insights scripts (/<hash>/script.js) 404 on every page. Keep them out.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path: string) =>
  readFileSync(new URL(path, import.meta.url), "utf8");

test("the root layout loads no Vercel analytics script", () => {
  const layout = read("../app/layout.tsx");
  assert.doesNotMatch(layout, /@vercel\/(analytics|speed-insights)/);
  assert.doesNotMatch(layout, /<(Analytics|SpeedInsights)\b/);
});

test("the Vercel analytics packages are not dependencies", () => {
  const pkg = JSON.parse(read("../package.json"));
  const deps = { ...pkg.dependencies, ...pkg.devDependencies };
  assert.equal(deps["@vercel/analytics"], undefined);
  assert.equal(deps["@vercel/speed-insights"], undefined);
});
