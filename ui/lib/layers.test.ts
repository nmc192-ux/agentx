// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 (S1-1): every hidden layer's routes show "coming later" while the
// layer's flag is off, through one layout gate per route segment.
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { HIDDEN_LAYERS, layerForPath, type LayerKey } from "./layers.ts";

const appDir = fileURLToPath(new URL("../app/", import.meta.url));
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const layers = Object.entries(HIDDEN_LAYERS) as [LayerKey, (typeof HIDDEN_LAYERS)[LayerKey]][];

test("the S1 list of hidden layers is covered", () => {
  const routes = layers.flatMap(([, l]) => l.routes);
  for (const r of [
    "markets", "tasks", "dashboard", "stats/economy", "governance", "groups",
    "communities", "rooms", "graph", "map", "sentinel", "capabilities",
    "services", "leaderboard", "spotlight",
  ]) assert.ok(routes.includes(r), `${r} is not hidden`);
});

test("each layer flag exists in flags.ts and defaults to off", () => {
  const flags = read("./flags.ts");
  for (const [, l] of layers) {
    const decl = new RegExp(
      `export const ${l.flag}\\s*=\\s*process\\.env\\.${l.envVar}\\s*===\\s*"true";`,
    );
    assert.match(flags, decl, `${l.flag} must read ${l.envVar} and be off unless "true"`);
  }
});

test("each hidden route segment has a layout gate for its own layer", () => {
  for (const [key, l] of layers) {
    for (const route of l.routes) {
      const layout = join(appDir, route, "layout.tsx");
      assert.ok(existsSync(layout), `app/${route}/layout.tsx is missing`);
      const src = readFileSync(layout, "utf8");
      assert.match(src, new RegExp(`import \\{ ${l.flag} \\} from "@/lib/flags";`));
      assert.match(src, new RegExp(`if \\(!${l.flag}\\) return <ComingLater layer="${key}" />;`));
      assert.match(src, /robots: \{ index: false \}/);
    }
  }
});

function pagesUnder(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return pagesUnder(p);
    return name === "page.tsx" ? [p] : [];
  });
}

test("no hidden page sends visitors home or to a 404 because of its flag", () => {
  for (const [, l] of layers) {
    for (const route of l.routes) {
      for (const page of pagesUnder(join(appDir, route))) {
        const src = readFileSync(page, "utf8");
        assert.doesNotMatch(src, /if \(!FEATURE_[A-Z_]+\) (redirect|notFound)\(/, page);
        assert.doesNotMatch(src, /redirect\("\/"\)/, page);
      }
    }
  }
});

test("layerForPath maps hidden routes and their sub-routes, nothing else", () => {
  assert.equal(layerForPath("/markets"), "economy");
  assert.equal(layerForPath("/markets/bounties"), "economy");
  assert.equal(layerForPath("/stats/economy"), "economy");
  assert.equal(layerForPath("/groups/3f2b8c1e-4d5a-4b6c-9e7f-0a1b2c3d4e5f"), "collectives");
  assert.equal(layerForPath("/rooms/abc?tab=x"), "rooms");
  assert.equal(layerForPath("/capabilities/"), "capabilities");
  assert.equal(layerForPath("/"), null);
  assert.equal(layerForPath("/stats"), null);
  assert.equal(layerForPath("/agents"), null);
  assert.equal(layerForPath("/marketsx"), null);
  assert.equal(layerForPath("/developer"), null);
});

test("the coming-later page points to Home and the developer page", () => {
  const src = read("../components/layout/ComingLater.tsx");
  assert.match(src, /href="\/"/);
  assert.match(src, /href="\/developer"/);
  assert.match(src, /Coming later/);
});
