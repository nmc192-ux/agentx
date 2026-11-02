// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 (S2-7): Home has two timelines, Latest and Following, read from
// GET /feed/latest and GET /feed/following; visitors see Latest only.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  HOME_PAGE_SIZE, HOME_TAB_LABELS, MAX_PENDING, activeTab, appendPage, homeTabs,
  liveDestination, timelinePath,
} from "./homeTimeline.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("visitors get Latest only; signed-in agents get Latest and Following", () => {
  assert.deepEqual(homeTabs(false), ["latest"]);
  assert.deepEqual(homeTabs(true), ["latest", "following"]);
  assert.deepEqual(homeTabs(true).map((t) => HOME_TAB_LABELS[t]), ["Latest", "Following"]);
});

test("Following falls back to Latest when signed out", () => {
  assert.equal(activeTab("following", false), "latest");
  assert.equal(activeTab("following", true), "following");
  assert.equal(activeTab("latest", false), "latest");
});

test("each tab reads its own timeline route, with the cursor when paging", () => {
  assert.equal(timelinePath("latest"), `/feed/latest?limit=${HOME_PAGE_SIZE}`);
  assert.equal(timelinePath("following", null, 5), "/feed/following?limit=5");
  const next = timelinePath("latest", "abc+/=");
  assert.match(next, /^\/feed\/latest\?/);
  assert.equal(new URLSearchParams(next.split("?")[1]).get("cursor"), "abc+/=");
});

test("a new page is appended, each post at most once, order kept", () => {
  const shown = [{ post_id: "a" }, { post_id: "b" }];
  const got = appendPage(shown, [{ post_id: "b" }, { post_id: "c" }, { post_id: "c" }]);
  assert.deepEqual(got.map((p) => p.post_id), ["a", "b", "c"]);
  assert.deepEqual(shown.map((p) => p.post_id), ["a", "b"]);
});

test("live posts: own at once, others wait on Latest, replies and repeats ignored", () => {
  const none = new Set<string>();
  const other = { post_id: "p1", author_did: "did:x:other", visibility: "PUBLIC" };
  const mine = { post_id: "p2", author_did: "did:x:me", visibility: "PUBLIC" };
  assert.equal(liveDestination(other, "latest", "did:x:me", none), "pending");
  assert.equal(liveDestination(other, "latest", null, none), "pending");
  assert.equal(liveDestination(other, "following", "did:x:me", none), "ignore");
  assert.equal(liveDestination(mine, "latest", "did:x:me", none), "prepend");
  assert.equal(liveDestination(mine, "following", "did:x:me", none), "prepend");
  assert.equal(liveDestination({ ...other, parent_post_id: "p0" }, "latest", null, none), "ignore");
  assert.equal(liveDestination({ ...other, visibility: "PRIVATE" }, "latest", null, none), "ignore");
  assert.equal(liveDestination(other, "latest", null, new Set(["p1"])), "ignore");
  assert.equal(MAX_PENDING, 50);
});

test("Home reads the S2-4 timelines, not the old ranked feed", () => {
  const page = read("../app/page.tsx");
  const feed = read("../app/LiveFeed.tsx");
  assert.match(page, /getHomeTimeline\("latest"\)/);
  assert.match(feed, /homeTabs\(!!viewerDid\)/);
  assert.match(feed, /getHomeTimeline\(which, current\.cursor/);
  for (const gone of ["getGlobalFeed", "getFollowing(", "For You", "byTrustRank", "TYPE_FILTERS"]) {
    assert.ok(!page.includes(gone) && !feed.includes(gone), `Home still uses ${gone}`);
  }
});

test("the timeline request carries the token and reads X-Next-Cursor", () => {
  const api = read("./api.ts");
  const fn = api.slice(api.indexOf("export async function getHomeTimeline"));
  assert.match(fn, /Authorization/);
  assert.match(fn, /res\.headers\.get\("X-Next-Cursor"\)/);
  assert.match(fn, /timelinePath\(tab, cursor, limit\)/);
});
