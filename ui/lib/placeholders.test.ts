// Run with `npm test`. Layer 1 (S1-6): no "coming soon" placeholder on a visible page.
// Pages in a hidden layer are skipped (they render the ComingLater page anyway).
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { test } from "node:test";

import { layerForPath } from "./layers.ts";

const ROOT = join(import.meta.dirname, "..");

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return tsxFiles(p);
    return p.endsWith(".tsx") ? [p] : [];
  });
}

function isHidden(file: string): boolean {
  const parts = file.split("/").slice(1, -1).filter((s) => !/^\(.*\)$/.test(s));
  const route = "/" + parts.join("/");
  return route !== "/" && layerForPath(route) !== null;
}

test("no 'coming soon' text on visible pages", () => {
  const bad: string[] = [];
  for (const abs of tsxFiles(join(ROOT, "app"))) {
    const file = relative(ROOT, abs);
    if (isHidden(file)) continue;
    const src = readFileSync(abs, "utf8")
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    if (/coming soon/i.test(src)) bad.push(file);
  }
  assert.deepEqual(bad, []);
});
