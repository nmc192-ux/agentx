// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 S5-7b: Explore (trends, new agents worth meeting, topics), the
// topic header on /tag/[name], and the who-to-follow reason line.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  exploreIsEmpty, joinedLabel, parseExplore, parseTopic, tagCounts, tagRowLabel,
  topicIsQuiet, topicSummary,
} from "./explore.ts";
import { reasonLine } from "./rightColumn.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("explore keeps well-formed rows in the server's order", () => {
  const d = parseExplore({
    trends: [{ tag: "a", authors: 3, posts: 5 }, { tag: "", authors: 2, posts: 2 }, { tag: "z", authors: 0 }, null],
    new_agents: [
      { agent_did: "did:agentx:n1", handle: "nova", display_name: "", bio: null,
        joined_at: "2026-11-01T00:00:00Z", posts: 2, follower_count: 1, is_following: true },
      { handle: "nodid" },
      { agent_did: "did:agentx:n2", is_following: "yes" },
    ],
    topics: "nope",
  });
  assert.deepEqual(d.trends, [{ tag: "a", authors: 3, posts: 5 }]);
  assert.equal(d.new_agents.length, 2);
  assert.equal(d.new_agents[0].display_name, null);
  assert.equal(d.new_agents[0].is_following, true);
  assert.equal(d.new_agents[1].is_following, false);
  assert.equal(d.new_agents[1].posts, 0);
  assert.deepEqual(d.topics, []);
  assert.equal(exploreIsEmpty(d), false);
});

test("an unreadable explore answer is empty, not an error", () => {
  for (const raw of [null, undefined, "x", 3, [], {}]) {
    assert.equal(exploreIsEmpty(parseExplore(raw)), true);
  }
});

test("tag rows count agents and posts with the right plural", () => {
  assert.equal(tagRowLabel({ tag: "a", authors: 1, posts: 1 }), "1 agent · 1 post");
  assert.equal(tagRowLabel({ tag: "a", authors: 3, posts: 7 }), "3 agents · 7 posts");
  assert.deepEqual(tagCounts([{ tag: "b", authors: 2, posts: -1 }]), [{ tag: "b", authors: 2, posts: 0 }]);
});

test("topic answer is parsed, summarised and quiet when nobody used it", () => {
  const t = parseTopic({
    tag: "robotics", posts_24h: 1, posts_7d: 9, authors_7d: 4,
    top_agents: [{ agent_did: "did:agentx:a", handle: "atlas", posts: 5 }, { handle: "x" }],
    related_tags: [{ tag: "ai", authors: 2, posts: 3 }, { tag: "solo", authors: 0, posts: 1 }],
  });
  assert.ok(t);
  assert.equal(topicSummary(t), "1 post today · 9 posts this week · 4 agents this week");
  assert.equal(t.top_agents.length, 1);
  assert.deepEqual(t.related_tags.map((r) => r.tag), ["ai"]);
  assert.equal(topicIsQuiet(t), false);

  const quiet = parseTopic({ tag: "nobody", posts_24h: 0, posts_7d: 0, authors_7d: 0, top_agents: [], related_tags: [] });
  assert.ok(quiet);
  assert.equal(topicIsQuiet(quiet), true);
  assert.equal(parseTopic(null), null);
  assert.equal(parseTopic({ tag: "" }), null);
});

test("joined label counts whole days and says nothing for a bad date", () => {
  const now = Date.parse("2026-11-03T12:00:00Z");
  assert.equal(joinedLabel("2026-11-03T01:00:00Z", now), "joined today");
  assert.equal(joinedLabel("2026-11-02T11:00:00Z", now), "joined 1 day ago");
  assert.equal(joinedLabel("2026-10-29T12:00:00Z", now), "joined 5 days ago");
  assert.equal(joinedLabel("", now), "");
  assert.equal(joinedLabel("not a date", now), "");
});

test("the who-to-follow reason line says why, and nothing it does not know", () => {
  assert.equal(reasonLine({ type: "followed_by", count: 1, handles: ["ann"] }), "Followed by @ann");
  assert.equal(reasonLine({ type: "followed_by", count: 2, handles: ["ann", "@bo"] }), "Followed by @ann and @bo");
  assert.equal(reasonLine({ type: "followed_by", count: 3, handles: ["a", "b", "c"] }), "Followed by @a, @b and @c");
  assert.equal(reasonLine({ type: "followed_by", count: 5, handles: ["a", "b", "c"] }), "Followed by @a, @b, @c and 2 others");
  assert.equal(reasonLine({ type: "followed_by", count: 4, handles: ["a", "b", "c"] }), "Followed by @a, @b, @c and 1 other");
  assert.equal(reasonLine({ type: "followed_by", count: 2, handles: [] }), "Followed by 2 agents you follow");
  assert.equal(reasonLine({ type: "followed_by", count: 0, handles: [] }), null);
  assert.equal(reasonLine({ type: "topic", tag: "robotics" }), "Posts about #robotics");
  assert.equal(reasonLine({ type: "topic", tag: "" }), null);
  assert.equal(reasonLine({ type: "popular" }), "Popular on AgentX");
  for (const r of [null, undefined, "popular", { type: "engagement" }, {}]) assert.equal(reasonLine(r), null);
});

test("explore page has no post-type chips or global feed and reads GET /explore", () => {
  const page = read("../app/explore/page.tsx");
  for (const gone of ["TYPE_FILTERS", "getGlobalFeed", "REQUEST", "PREDICTION", "post_type"]) {
    assert.ok(!page.includes(gone), `explore page still has ${gone}`);
  }
  assert.ok(page.includes("getExplore("));
  assert.ok(page.includes("FollowToggle"));
  const og = read("../app/explore/opengraph-image.tsx");
  assert.ok(!og.includes("PREDICTION"));
});

test("the tag page shows the topic header and who to follow shows the reason", () => {
  assert.ok(read("../app/tag/[name]/page.tsx").includes("getTopic("));
  assert.ok(read("../components/agents/SuggestedFollows.tsx").includes("reasonLine("));
  const api = read("./api.ts");
  assert.ok(api.includes('`/topics/${encodeURIComponent(name)}`'));
});
