// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 S5-7a: the /search page — tabs, request paths, well-formed rows,
// empty states that say something true, and the SearchBar submitting there.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  EMPTY_HINTS, MAX_QUERY_LENGTH, OPERATOR_HELP, SEARCH_TABS, agentSubtitle, cleanQuery,
  emptyTitle, parseTab, searchApiPath, searchHref, searchNotes, tagCountsLabel,
  visibleAgents, visibleTags,
} from "./search.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("tabs are posts, agents and tags; anything else is posts", () => {
  assert.deepEqual(SEARCH_TABS, ["posts", "agents", "tags"]);
  assert.equal(parseTab("agents"), "agents");
  assert.equal(parseTab("tags"), "tags");
  for (const bad of [null, undefined, "", "communities", "all", "POSTS", "posts "]) {
    assert.equal(parseTab(bad), "posts");
  }
});

test("the query is trimmed and cut to the server's 200-character cap", () => {
  assert.equal(MAX_QUERY_LENGTH, 200);
  assert.equal(cleanQuery("  hello  "), "hello");
  assert.equal(cleanQuery(null), "");
  assert.equal(cleanQuery("x".repeat(300)).length, 200);
});

test("website links keep operators intact and leave out the default tab", () => {
  assert.equal(searchHref("robots"), "/search?q=robots");
  assert.equal(searchHref("robots", "agents"), "/search?q=robots&tab=agents");
  const href = searchHref('from:@atlas has:media "a & b" #ai 100%_');
  const back = new URL(href, "https://x.test").searchParams;
  assert.equal(back.get("q"), 'from:@atlas has:media "a & b" #ai 100%_');
  assert.equal(back.get("tab"), null);
});

test("API path sends the tab as type and the cursor for posts only", () => {
  const p = new URL(searchApiPath("ai", "posts", "abc"), "https://x.test");
  assert.equal(p.pathname, "/search");
  assert.equal(p.searchParams.get("type"), "posts");
  assert.equal(p.searchParams.get("cursor"), "abc");
  assert.equal(p.searchParams.get("limit"), "20");
  const a = new URL(searchApiPath("ai", "agents", "abc"), "https://x.test");
  assert.equal(a.searchParams.get("type"), "agents");
  assert.equal(a.searchParams.get("cursor"), null);
  assert.equal(new URL(searchApiPath("ai", "posts"), "https://x.test").searchParams.get("cursor"), null);
});

test("agent rows need a DID and keep the server's order", () => {
  const got = visibleAgents([
    { agent_did: "did:agentx:a", handle: "atlas", display_name: "Atlas", bio: "maps", follower_count: 3 },
    { handle: "nodid" },
    null,
    { agent_did: "did:agentx:b", handle: "", display_name: null, follower_count: "7" },
  ]);
  assert.deepEqual(got.map((a) => a.agent_did), ["did:agentx:a", "did:agentx:b"]);
  assert.equal(got[1].handle, null);
  assert.equal(got[1].follower_count, 0);
  assert.deepEqual(visibleAgents({ detail: "x" }), []);
  assert.equal(agentSubtitle(got[0]), "@atlas");
  assert.equal(agentSubtitle(got[1]), "b");
});

test("tag rows need a name and both counts", () => {
  const got = visibleTags([
    { tag: "ai", authors: 3, posts: 7 },
    { tag: "", authors: 1, posts: 1 },
    { tag: "x", authors: "2", posts: 2 },
    { tag: "one", authors: 1, posts: 1 },
  ]);
  assert.deepEqual(got.map((t) => t.tag), ["ai", "one"]);
  assert.equal(tagCountsLabel(got[0]), "3 agents · 7 posts in 30 days");
  assert.equal(tagCountsLabel(got[1]), "1 agent · 1 post in 30 days");
  assert.deepEqual(visibleTags(null), []);
});

test("notes are strings only", () => {
  assert.deepEqual(searchNotes(["unknown handle @zz", "", 3, null]), ["unknown handle @zz"]);
  assert.deepEqual(searchNotes("x"), []);
});

test("empty states name the query and claim nothing else", () => {
  assert.equal(emptyTitle("posts", " robots "), "No posts match “robots”");
  assert.equal(emptyTitle("agents", "atlas"), "No agents match “atlas”");
  assert.equal(emptyTitle("tags", "#rob"), "No tags used in the last 30 days match “#rob”");
  for (const t of SEARCH_TABS) {
    assert.ok(EMPTY_HINTS[t].length > 0);
    assert.doesNotMatch(emptyTitle(t, "x") + EMPTY_HINTS[t], /no one|nobody|doesn't exist|try again later/i);
  }
});

test("the operator help line names every operator the server parses", () => {
  for (const op of ['"', "from:@", "has:media", "has:link", "since:", "until:", "#"]) {
    assert.ok(OPERATOR_HELP.includes(op), op);
  }
});

test("the page uses the shared post card, the tabs and the operator help", () => {
  const page = read("../app/search/page.tsx");
  assert.match(page, /<FeedList posts=\{posts\}/);
  assert.match(page, /OPERATOR_HELP/);
  assert.match(page, /searchHref\(q, t\)/);
  assert.match(page, /next_cursor/);
  assert.match(page, /getToken\(\)/);
  assert.match(page, /<Suspense/);
});

test("the SearchBar submits to the search page and keeps its suggestions", () => {
  const bar = read("../components/search/SearchBar.tsx");
  assert.match(bar, /kind: "search"/);
  assert.match(bar, /searchHref\(q\)/);
  assert.match(bar, /Search for “/);
  for (const kept of ['kind: "tag"', 'kind: "post"', 'kind: "agent"', 'kind: "history"']) {
    assert.ok(bar.includes(kept), kept);
  }
});

test("the dead-end crawl starts on a search results page", () => {
  assert.match(read("../e2e/dead_ends.spec.ts"), /"\/search\?q=/);
});
