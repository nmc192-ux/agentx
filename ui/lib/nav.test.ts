// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 (S1-2): with every layer flag off, no menu links into a hidden
// layer; with the flags on, the items come back.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { HIDDEN_LAYERS, isHrefVisible, layerForPath, visibleItems, type LayerKey } from "./layers.ts";
import { FOOTER_LINKS, PULSE_QUICK_LINKS, SIDEBAR_ITEMS, TOP_NAV_ITEMS } from "./nav.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const layerFlags = Object.values(HIDDEN_LAYERS).map((l) => l.flag);
const allOff = Object.fromEntries([...layerFlags.map((f) => [f, false]), ["FEATURE_JOIN", true]]);
const allOn = Object.fromEntries([...layerFlags, "FEATURE_JOIN"].map((f) => [f, true]));
const lists = { SIDEBAR_ITEMS, TOP_NAV_ITEMS, FOOTER_LINKS, PULSE_QUICK_LINKS };

test("with all layer flags off, no menu links into a hidden layer", () => {
  for (const [name, list] of Object.entries(lists)) {
    for (const item of visibleItems(list, allOff)) {
      assert.equal(layerForPath(item.href), null, `${name} still shows ${item.href}`);
    }
  }
});

test("the menus did link to hidden layers, so the filter is doing the work", () => {
  const hidden = Object.values(lists).flat().filter((i) => layerForPath(i.href) !== null);
  for (const href of ["/rooms", "/leaderboard", "/capabilities", "/services", "/dashboard",
    "/communities", "/stats/economy", "/governance", "/graph"]) {
    assert.ok(hidden.some((i) => i.href === href), `${href} is not in any menu`);
  }
});

test("Social links stay; turning a layer on brings its links back", () => {
  const sidebar = visibleItems(SIDEBAR_ITEMS, allOff).map((i) => i.href);
  for (const href of ["/agents", "/trending", "/tags", "/developer", "/settings"]) {
    assert.ok(sidebar.includes(href), `${href} missing`);
  }
  for (const [name, list] of Object.entries(lists)) {
    assert.equal(visibleItems(list, allOn).length, list.length, name);
  }
  const roomsOn = { ...allOff, FEATURE_ROOMS: true };
  assert.ok(visibleItems(SIDEBAR_ITEMS, roomsOn).some((i) => i.href === "/rooms"));
  assert.ok(!visibleItems(SIDEBAR_ITEMS, roomsOn).some((i) => i.href === "/governance"));
});

test("an item's own flag is honoured (Join can be switched off)", () => {
  const joinOff = { ...allOff, FEATURE_JOIN: false };
  assert.ok(!visibleItems(TOP_NAV_ITEMS, joinOff).some((i) => i.href === "/join"));
  assert.ok(visibleItems(TOP_NAV_ITEMS, allOff).some((i) => i.href === "/join"));
});

test("isHrefVisible: sub-routes and query strings are hidden too; external URLs are not", () => {
  assert.equal(isHrefVisible("/rooms/abc?x=1", allOff), false);
  assert.equal(isHrefVisible("/groups/", allOff), false);
  assert.equal(isHrefVisible("/roomsx", allOff), true);
  assert.equal(isHrefVisible("https://pypi.org/project/agentx-social/", allOff), true);
  assert.equal(isHrefVisible("/stats", allOff), true);
  assert.equal(isHrefVisible("/rooms", {}), false, "a missing flag counts as off");
});

test("LAYER_FLAGS in flags.ts names every layer flag and FEATURE_JOIN", () => {
  const flags = read("./flags.ts");
  const block = flags.slice(flags.indexOf("export const LAYER_FLAGS"));
  for (const f of [...layerFlags, "FEATURE_JOIN"]) {
    assert.match(block, new RegExp(`\\b${f},`), `${f} missing from LAYER_FLAGS`);
  }
});

test("menus and the home widgets read their links through the filter", () => {
  const uses: Record<string, RegExp> = {
    "../components/layout/Sidebar.tsx": /visibleItems\(ALL_SIDEBAR_ITEMS, LAYER_FLAGS\)/,
    "../components/layout/TopNav.tsx": /visibleItems\(TOP_NAV_ITEMS, LAYER_FLAGS\)/,
    "../components/layout/Footer.tsx": /visibleItems\(FOOTER_LINKS, LAYER_FLAGS\)/,
    "../components/pulse/LivePulseSidebar.tsx": /visibleItems\(PULSE_QUICK_LINKS, LAYER_FLAGS\)/,
    "../components/layout/CommandPalette.tsx": /isHrefVisible\(a\.hint \?\? "", LAYER_FLAGS\)/,
  };
  for (const [file, re] of Object.entries(uses)) assert.match(read(file), re, file);
  // No hard-coded hidden-layer links left in the chrome outside lib/nav.ts.
  const routes = (Object.values(HIDDEN_LAYERS) as (typeof HIDDEN_LAYERS)[LayerKey][])
    .flatMap((l) => l.routes).join("|");
  const literal = new RegExp(`href(=|:\\s*)["\`]/(${routes})\\b`);
  for (const file of ["../components/layout/Sidebar.tsx", "../components/layout/TopNav.tsx",
    "../components/layout/Footer.tsx", "../components/pulse/LivePulseSidebar.tsx",
    "../components/layout/MobileBottomNav.tsx"]) {
    assert.doesNotMatch(read(file), literal, file);
  }
});

test("Start Room on a post needs FEATURE_ROOMS", () => {
  assert.match(read("../components/feed/PostCard.tsx"), /const canStartRoom = FEATURE_ROOMS &&/);
});
