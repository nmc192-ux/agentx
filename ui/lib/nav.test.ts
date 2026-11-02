// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 (S1-2): with every layer flag off, no menu links into a hidden
// layer; with the flags on, the items come back.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { HIDDEN_LAYERS, isHrefVisible, layerForPath, visibleItems, type LayerKey } from "./layers.ts";
import { FOOTER_LINKS, PHONE_TAB_ITEMS, PULSE_QUICK_LINKS, SHELL_MENU_ITEMS, isMenuItemActive } from "./nav.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const layerFlags = Object.values(HIDDEN_LAYERS).map((l) => l.flag);
const allOff = Object.fromEntries([...layerFlags.map((f) => [f, false]), ["FEATURE_JOIN", true]]);
const allOn = Object.fromEntries([...layerFlags, "FEATURE_JOIN"].map((f) => [f, true]));
const lists = { SHELL_MENU_ITEMS, PHONE_TAB_ITEMS, FOOTER_LINKS, PULSE_QUICK_LINKS };

test("with all layer flags off, no menu links into a hidden layer", () => {
  for (const [name, list] of Object.entries(lists)) {
    for (const item of visibleItems(list, allOff)) {
      assert.equal(layerForPath(item.href), null, `${name} still shows ${item.href}`);
    }
  }
});

test("the menus did link to hidden layers, so the filter is doing the work", () => {
  const hidden = Object.values(lists).flat().filter((i) => layerForPath(i.href) !== null);
  for (const href of ["/stats/economy", "/governance", "/graph", "/rooms"]) {
    assert.ok(hidden.some((i) => i.href === href), `${href} is not in any menu`);
  }
});

test("turning a layer on brings its links back", () => {
  for (const [name, list] of Object.entries(lists)) {
    assert.equal(visibleItems(list, allOn).length, list.length, name);
  }
  const roomsOn = { ...allOff, FEATURE_ROOMS: true };
  assert.ok(visibleItems(PULSE_QUICK_LINKS, roomsOn).some((i) => i.href === "/rooms"));
  assert.ok(!visibleItems(PULSE_QUICK_LINKS, roomsOn).some((i) => i.href === "/governance"));
});

// S2-5: the shell's left menu is exactly the plan's list; the phone tab bar
// mirrors it.
test("left menu is exactly Home, Explore, Notifications, Messages, Profile, Developers (+ Join)", () => {
  assert.deepEqual(visibleItems(SHELL_MENU_ITEMS, allOff).map((i) => i.label),
    ["Home", "Explore", "Notifications", "Messages", "Profile", "Developers", "Join"]);
  assert.deepEqual(visibleItems(SHELL_MENU_ITEMS, { ...allOff, FEATURE_JOIN: false }).map((i) => i.label),
    ["Home", "Explore", "Notifications", "Messages", "Profile", "Developers"]);
  assert.deepEqual(SHELL_MENU_ITEMS.map((i) => i.href),
    ["/", "/explore", "/notifications", "/messages", "/me", "/developer", "/join"]);
  for (const item of SHELL_MENU_ITEMS) {
    assert.equal(layerForPath(item.href), null, `${item.href} is in a hidden layer`);
    assert.ok(item.icon, `${item.href} has no icon`);
  }
});

test("phone tab bar is the left menu's first five items, same order, same targets", () => {
  assert.deepEqual(PHONE_TAB_ITEMS.map((i) => i.href), SHELL_MENU_ITEMS.slice(0, 5).map((i) => i.href));
  assert.ok(PHONE_TAB_ITEMS.length <= 5, "more than five tabs do not fit a phone");
  for (const t of PHONE_TAB_ITEMS) {
    const m = SHELL_MENU_ITEMS.find((i) => i.href === t.href)!;
    assert.equal(t.icon, m.icon);
  }
});

test("isMenuItemActive: Home exact, others by prefix, Profile also on the viewer's own page", () => {
  assert.equal(isMenuItemActive("/", "/"), true);
  assert.equal(isMenuItemActive("/explore", "/"), false);
  assert.equal(isMenuItemActive("/messages/abc", "/messages"), true);
  assert.equal(isMenuItemActive("/messagesx", "/messages"), false);
  const own = "/agents/did%3Aagentx%3Anova-001";
  assert.equal(isMenuItemActive(own, "/me", own), true);
  assert.equal(isMenuItemActive(own + "/trust", "/me", own), true);
  assert.equal(isMenuItemActive("/agents/did%3Aagentx%3Aatlas-001", "/me", own), false);
  assert.equal(isMenuItemActive(own, "/me", null), false);
  assert.equal(isMenuItemActive("/me", "/me", null), true);
});

test("the shell renders the menus from lib/nav.ts; the top bar has no page links", () => {
  assert.match(read("../components/layout/MobileBottomNav.tsx"), /visibleItems\(PHONE_TAB_ITEMS, LAYER_FLAGS\)/);
  const top = read("../components/layout/TopNav.tsx");
  assert.doesNotMatch(top, /TOP_NAV_ITEMS|<nav\b/);
  const shell = read("../components/layout/AppShell.tsx");
  assert.match(shell, /<Sidebar \/>/);
  assert.match(shell, /<MobileBottomNav \/>/);
  assert.match(shell, /right\?: React\.ReactNode/);
});

test("an item's own flag is honoured (Join can be switched off)", () => {
  const joinOff = { ...allOff, FEATURE_JOIN: false };
  assert.ok(!visibleItems(SHELL_MENU_ITEMS, joinOff).some((i) => i.href === "/join"));
  assert.ok(visibleItems(SHELL_MENU_ITEMS, allOff).some((i) => i.href === "/join"));
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
    "../components/layout/Sidebar.tsx": /visibleItems\(SHELL_MENU_ITEMS, LAYER_FLAGS\)/,
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

// S1-2b: page tiles without an href are judged by their own flag.
test("items without an href follow their own flag", () => {
  const tiles = [{ label: "posts", href: "/explore" }, { label: "rooms", href: "/rooms" },
    { label: "txns", flag: "FEATURE_ECONOMY" }, { label: "plain" }];
  assert.deepEqual(visibleItems(tiles, allOff).map((t) => t.label), ["posts", "plain"]);
  assert.equal(visibleItems(tiles, allOn).length, tiles.length);
});

test("S1-2b: profile, stats, activity and duplicate feeds respect the layers", () => {
  const profile = read("../app/agents/[did]/AgentProfileClient.tsx");
  assert.match(profile, /if \(!FEATURE_CAPABILITIES\) return;/);
  assert.match(profile, /if \(!FEATURE_SERVICES\) return;/);
  assert.match(profile, /\{FEATURE_CAPABILITIES && visibleCapabilities/);
  assert.match(profile, /\{FEATURE_SERVICES && visibleServices/);
  assert.match(read("../app/stats/page.tsx"), /visibleItems\(tilesFromPulse\(pulse\), LAYER_FLAGS\)/);
  assert.match(read("../app/activity/page.tsx"), /FEATURE_ECONOMY \|\| r\.item_type === "post"/);
  for (const page of ["../app/feed/page.tsx", "../app/home/page.tsx"]) {
    assert.match(read(page), /redirect\("\/"\)/, page);
  }
  const guide = read("../components/feed/PostTypeGuide.tsx");
  assert.doesNotMatch(guide, /[Bb]ounty|[Gg]overnance/);
});
