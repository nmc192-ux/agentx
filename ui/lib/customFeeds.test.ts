// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 S6-7a: custom feeds in the web app (feed page, Home tabs, Explore).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  MAX_PINNED_FEEDS, addPinnedRef, feedCountsLabel, feedDirectoryPath, feedHref, feedPostsPath,
  findFeedBySlug, parseFeed, parseFeedList, parsePinnedRefs, refreshedLabel, removePinnedRef,
  toPinnedRef, type PinnedFeedRef,
} from "./customFeeds.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

const ID = "0b9c2a52-6f3e-4d7a-9a51-1f2e3d4c5b6a";
const id = (n: number) => `0b9c2a52-6f3e-4d7a-9a51-${String(n).padStart(12, "0")}`;

const RAW = {
  feed_id: ID, owner_did: "did:agentx:owner", owner_handle: "atlas", slug: "ai-news",
  name: "AI news", description: "What moved today", item_count: 12, pin_count: 3,
  refreshed_at: "2026-11-04T00:00:00Z", created_at: "2026-11-01T00:00:00Z", is_pinned: true,
};

test("a feed from the API keeps its fields; a wrong shape is dropped", () => {
  const f = parseFeed(RAW);
  assert.ok(f);
  assert.equal(f.name, "AI news");
  assert.equal(f.is_pinned, true);
  assert.equal(parseFeed({ ...RAW, is_pinned: undefined })?.is_pinned, null);
  assert.equal(parseFeed({ ...RAW, owner_handle: null })?.owner_handle, null);
  assert.equal(parseFeed({ ...RAW, item_count: -4 })?.item_count, 0);
  assert.equal(parseFeed({ ...RAW, feed_id: "nope" }), null);
  assert.equal(parseFeed({ ...RAW, slug: "Bad Slug" }), null);
  assert.equal(parseFeed({ ...RAW, owner_did: "" }), null);
  assert.equal(parseFeed(null), null);
});

test("a feed list keeps good feeds in the API's order", () => {
  const list = parseFeedList({
    feeds: [RAW, { junk: 1 }, { ...RAW, feed_id: id(2), slug: "second" }],
    next_cursor: "abc",
  });
  assert.deepEqual(list.feeds.map((f) => f.slug), ["ai-news", "second"]);
  assert.equal(list.next_cursor, "abc");
  assert.deepEqual(parseFeedList("nope"), { feeds: [], next_cursor: null });
});

test("feed pages live at /@handle/feed/slug, or by id without a handle", () => {
  assert.equal(feedHref({ feed_id: ID, owner_handle: "atlas", slug: "ai-news" }), "/@atlas/feed/ai-news");
  assert.equal(feedHref({ feed_id: ID, owner_handle: null, slug: "ai-news" }), `/feeds/${ID}`);
  assert.match(read("../next.config.ts"),
    /source: "\/@:handle\/feed\/:slug", destination: "\/u\/:handle\/feed\/:slug"/);
});

test("API paths carry the cursor and limit", () => {
  assert.equal(feedPostsPath(ID), `/feeds/${ID}/posts?limit=20`);
  assert.equal(feedPostsPath(ID, "c1", 5), `/feeds/${ID}/posts?limit=5&cursor=c1`);
  assert.equal(feedDirectoryPath("new"), "/feeds?sort=new&limit=10");
  assert.equal(feedDirectoryPath("popular", "x y"), "/feeds?sort=popular&limit=10&cursor=x+y");
});

test("a slug finds its feed among an agent's feeds", () => {
  const feeds = parseFeedList({ feeds: [RAW] }).feeds;
  assert.equal(findFeedBySlug(feeds, "AI-News ")?.feed_id, ID);
  assert.equal(findFeedBySlug(feeds, "other"), null);
});

test("labels", () => {
  assert.equal(feedCountsLabel({ item_count: 1, pin_count: 0 }), "1 post · pinned by 0");
  assert.equal(feedCountsLabel({ item_count: 12, pin_count: 3 }), "12 posts · pinned by 3");
  const now = Date.parse("2026-11-04T12:00:00Z");
  assert.equal(refreshedLabel(null, now), "Not refreshed yet");
  assert.equal(refreshedLabel("2026-11-04T11:59:30Z", now), "Refreshed just now");
  assert.equal(refreshedLabel("2026-11-04T11:50:00Z", now), "Refreshed 10 min ago");
  assert.equal(refreshedLabel("2026-11-04T09:00:00Z", now), "Refreshed 3 h ago");
  assert.equal(refreshedLabel("2026-11-03T12:00:00Z", now), "Refreshed 1 day ago");
  assert.equal(refreshedLabel("garbage", now), "");
});

test("a visitor's stored pins: malformed entries, repeats and overflow are dropped", () => {
  assert.deepEqual(parsePinnedRefs(null), []);
  assert.deepEqual(parsePinnedRefs("{not json"), []);
  assert.deepEqual(parsePinnedRefs('{"a":1}'), []);
  const many = Array.from({ length: 14 }, (_, i) => ({ feed_id: id(i), slug: `feed-${i}`, name: `F${i}` }));
  const stored = JSON.stringify([
    { feed_id: ID, slug: "ai-news", name: "x".repeat(200), owner_handle: "atlas" },
    { feed_id: ID, slug: "ai-news", name: "again" },
    { feed_id: "javascript:alert(1)", slug: "ai-news" },
    { feed_id: id(99), slug: "../../etc" },
    "string", null,
    ...many,
  ]);
  const refs = parsePinnedRefs(stored);
  assert.equal(refs.length, MAX_PINNED_FEEDS);
  assert.equal(refs[0].feed_id, ID);
  assert.equal(refs[0].name.length, 60);
  assert.equal(refs.filter((r) => r.feed_id === ID).length, 1);
  assert.ok(refs.every((r) => /^[a-z0-9-]{3,40}$/.test(r.slug)));
});

test("pinning in the browser: once each, at most 10, unpin removes", () => {
  const ref = toPinnedRef(parseFeed(RAW)!);
  assert.deepEqual(ref, { feed_id: ID, name: "AI news", owner_handle: "atlas", slug: "ai-news" });
  let list: PinnedFeedRef[] = [];
  ({ list } = addPinnedRef(list, ref));
  ({ list } = addPinnedRef(list, ref));
  assert.equal(list.length, 1);
  for (let i = 0; i < 9; i++) ({ list } = addPinnedRef(list, { ...ref, feed_id: id(i) }));
  assert.equal(list.length, MAX_PINNED_FEEDS);
  const over = addPinnedRef(list, { ...ref, feed_id: id(50) });
  assert.equal(over.full, true);
  assert.equal(over.list.length, MAX_PINNED_FEEDS);
  assert.equal(removePinnedRef(list, ID).length, MAX_PINNED_FEEDS - 1);
});

test("Home shows pinned feeds as tabs and Explore lists feeds", () => {
  const home = read("../app/LiveFeed.tsx");
  assert.match(home, /getMyFeedPins\(/);
  assert.match(home, /useLocalPinnedFeeds\(\)/);
  assert.match(home, /getFeedPosts\(feedId, cursor/);
  assert.match(home, /pinnedFeeds\.map\(/);
  const explore = read("../app/explore/page.tsx");
  assert.match(explore, /getFeedDirectory\(sort/);
  assert.match(explore, /id="feeds"/);
  const view = read("../components/feeds/FeedView.tsx");
  assert.match(view, /getFeedPosts\(/);
  assert.match(view, /pinFeedLocally\(/);
  assert.match(view, /pinFeed\(feed\.feed_id, token\)/);
  assert.match(read("../lib/storage/pinnedFeeds.ts"), /PINNED_FEEDS_KEY/);
});
