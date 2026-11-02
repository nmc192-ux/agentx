// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 (S3-8a): the conversation page layout from GET /posts/{id}/conversation.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { conversationRows, MAX_INDENT, moreRepliesLabel, type ConvNode } from "./conversation.ts";

const p = (id: string, author = "a") => ({ post_id: id, author_did: `did:agentx:${author}` });
const n = (id: string, author: string, replies: ConvNode[] = [], more = 0): ConvNode =>
  ({ post: p(id, author), replies, more_replies: more });
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("ancestors, then the post, then replies depth-first", () => {
  const rows = conversationRows({
    ancestors: [{ post_id: "root", post: p("root", "x") }, { post_id: "mid", unavailable: true }],
    post: p("me", "a"),
    replies: [n("r1", "b", [n("r1a", "c")]), n("r2", "c")],
  });
  assert.deepEqual(rows.map((r) => r.key), ["a:root", "a:mid", "p:me", "r:r1", "r:r1a", "r:r2"]);
  assert.equal(rows[1].kind === "ancestor" && rows[1].post, null);
  assert.deepEqual(rows.slice(3).map((r) => (r.kind === "reply" ? r.depth : -1)), [1, 2, 1]);
});

test("an author's own first reply continues the thread at the same depth", () => {
  const rows = conversationRows({
    ancestors: [],
    post: p("t1", "a"),
    replies: [n("t2", "a", [n("t3", "a", [n("other", "b")])]), n("side", "b")],
  });
  const focal = rows[0];
  assert.ok(focal.kind === "focal" && focal.joinBelow);
  const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));
  for (const k of ["r:t2", "r:t3"]) {
    const r = byKey[k];
    assert.ok(r.kind === "reply" && r.depth === 0 && r.joinedAbove, k);
  }
  const t3 = byKey["r:t3"];
  assert.ok(t3.kind === "reply" && !t3.joinBelow);
  const other = byKey["r:other"];
  assert.ok(other.kind === "reply" && other.depth === 1 && !other.joinedAbove);
  const side = byKey["r:side"];
  assert.ok(side.kind === "reply" && side.depth === 1 && !side.joinedAbove);
});

test("only the first reply can continue a thread", () => {
  const rows = conversationRows({ ancestors: [], post: p("t1", "a"), replies: [n("x", "b"), n("t2", "a")] });
  const t2 = rows.find((r) => r.key === "r:t2");
  assert.ok(t2 && t2.kind === "reply" && t2.depth === 1 && !t2.joinedAbove);
});

test("indentation stops at MAX_INDENT", () => {
  let node = n("d9", "z9");
  for (let i = 8; i >= 1; i--) node = n(`d${i}`, `z${i}`, [node]);
  const rows = conversationRows({ ancestors: [], post: p("top", "a"), replies: [node] });
  const depths = rows.filter((r) => r.kind === "reply").map((r) => (r.kind === "reply" ? r.depth : 0));
  assert.equal(Math.max(...depths), MAX_INDENT);
});

test("more rows count the replies not shown, after the shown ones", () => {
  const rows = conversationRows({
    ancestors: [], post: p("me"), replies: [n("r1", "b", [], 3)], more_replies: 7,
  });
  assert.deepEqual(rows.map((r) => r.key), ["p:me", "r:r1", "m:r1", "m:me"]);
  const [, , under, top] = rows;
  assert.ok(under.kind === "more" && under.count === 3 && under.parentId === "r1" && !under.focal);
  assert.ok(top.kind === "more" && top.count === 7 && top.focal && top.depth === 1);
  assert.equal(moreRepliesLabel(1), "Show 1 more reply");
  assert.equal(moreRepliesLabel(3), "Show 3 more replies");
});

test("the post page reads the conversation endpoint and links unavailable rows nowhere", () => {
  const page = read("../app/post/[id]/page.tsx");
  assert.ok(page.includes("getConversation("));
  assert.ok(page.includes("conversationRows("));
  assert.ok(page.includes("This post is unavailable"));
  const api = read("./api.ts");
  assert.match(api, /\/posts\/\$\{postId\}\/conversation\?/);
});
