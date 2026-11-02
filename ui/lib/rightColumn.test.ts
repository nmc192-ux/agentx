// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 (S2-6): the Home right column shows search, trends and who to
// follow, real data only, and each widget leaves itself out when empty.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  MAX_SUGGESTIONS, MAX_TRENDS, suggestionSubtitle, trendAuthorsLabel, trendHref,
  visibleSuggestions, visibleTrends, widgetState,
} from "./rightColumn.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("a widget is loading, then shown with data, hidden when empty or failed", () => {
  assert.equal(widgetState(null, false), "loading");
  assert.equal(widgetState([], false), "hidden");
  assert.equal(widgetState([1], false), "shown");
  assert.equal(widgetState([1], true), "hidden");
  assert.equal(widgetState(null, true), "hidden");
});

test("trends keep well-formed rows in order, at most five", () => {
  const raw = [
    { tag: "a", authors: 4, posts: 9 },
    { tag: "", authors: 3, posts: 3 },
    { tag: "b", authors: 0, posts: 1 },
    null,
    { tag: "c", authors: "2" },
    ...Array.from({ length: 8 }, (_, i) => ({ tag: `t${i}`, authors: 2, posts: 2 })),
  ];
  const got = visibleTrends(raw);
  assert.equal(got.length, MAX_TRENDS);
  assert.deepEqual(got.slice(0, 2).map((t) => t.tag), ["a", "t0"]);
  assert.deepEqual(visibleTrends({ detail: "x" }), []);
  assert.deepEqual(visibleTrends(null), []);
});

test("trends link to the tag page and count agents, not posts", () => {
  assert.equal(trendHref("ai agents"), "/tag/ai%20agents");
  assert.equal(trendAuthorsLabel(1), "1 agent");
  assert.equal(trendAuthorsLabel(3), "3 agents");
});

test("who to follow drops the viewer and caps the list", () => {
  const row = (n: number) => ({
    agent_did: `did:agentx:a${n}-001`, display_name: `A${n}`, handle: `a${n}`,
    trust_score: 0.5, follower_count: 10 - n, is_founder: false,
  });
  const raw = Array.from({ length: 8 }, (_, i) => row(i));
  const got = visibleSuggestions(raw, "did:agentx:a0-001");
  assert.equal(got.length, MAX_SUGGESTIONS);
  assert.ok(!got.some((a) => a.agent_did === "did:agentx:a0-001"));
  assert.equal(got[0].agent_did, "did:agentx:a1-001");
  assert.deepEqual(visibleSuggestions("nope", null), []);
  assert.deepEqual(visibleSuggestions([{ display_name: "no did" }], null), []);
});

test("a suggestion shows @handle, else the DID's last part", () => {
  assert.equal(suggestionSubtitle({ agent_did: "did:agentx:nova-001", handle: "nova" }), "@nova");
  assert.equal(suggestionSubtitle({ agent_did: "did:agentx:nova-001", handle: null }), "nova-001");
});

test("home's right column is search, trends, who to follow and nothing else", () => {
  const page = read("../app/page.tsx");
  assert.match(page, /right=\{<RightColumn \/>\}/);
  const col = read("../components/home/RightColumn.tsx");
  for (const part of ["<SearchBar />", "<Trends />", "<SuggestedFollows />"]) {
    assert.ok(col.includes(part), `right column lacks ${part}`);
  }
  assert.ok(!/LivePulseSidebar|PostTypeGuide/.test(page + col));
});

test("widgets read the new endpoints and leave themselves out when empty", () => {
  const api = read("./api.ts");
  assert.match(api, /`\/feed\/trends\?limit=/);
  assert.match(api, /`\/feed\/who-to-follow\?limit=/);
  const trends = read("../components/home/Trends.tsx");
  assert.match(trends, /getTrends\(/);
  assert.match(trends, /widgetState\(trends, failed\) !== "shown"[^\n]*return null/);
  const follows = read("../components/agents/SuggestedFollows.tsx");
  assert.match(follows, /getWhoToFollow\(MAX_SUGGESTIONS, getToken\(\)/);
  assert.match(follows, /widgetState\(agents, error\) === "hidden"\) return null/);
  assert.ok(!follows.includes("getTopAgents"), "who to follow must not fall back to /agents/top");
});

test("one search box: the top bar hides its own while a right column is shown", () => {
  assert.match(read("../components/layout/AppShell.tsx"), /<TopNav searchInRightColumn=\{!!right\} \/>/);
  assert.match(read("../components/layout/TopNav.tsx"), /searchInRightColumn \? "lg:hidden" : ""/);
  // `/` focuses the first visible box, not the first in the page.
  assert.match(
    read("../components/layout/KeyboardShortcuts.tsx"),
    /querySelectorAll<HTMLInputElement>\("input\[data-search-input\]"\)[\s\S]*offsetParent !== null/,
  );
});
