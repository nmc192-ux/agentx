// Layer 1 S3-7: threads, the conversation view, reposts, quotes, notification type filter.
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import { ValidationError } from "../src/errors.ts";

const BASE = "http://api.test";
const PID = "11111111-1111-1111-1111-111111111111";

function jwt(claims: Record<string, unknown>): string {
  const enc = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(claims)}.sig`;
}
const ACCESS = jwt({ sub: "did:agentx:nova-042", exp: Math.floor(Date.now() / 1000) + 3600 });

function client(status: number, body: unknown) {
  const seen: { method: string; path: string; body: unknown }[] = [];
  const fetch = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    seen.push({
      method: init.method ?? "GET",
      path: url.pathname + url.search,
      body: init.body ? JSON.parse(String(init.body)) : undefined,
    });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof globalThis.fetch;
  const agent = new AgentX({ accessToken: ACCESS, baseUrl: BASE, fetch });
  return { agent, seen };
}

test("posts.createThread: text and object items, PUBLIC by default", async () => {
  const { agent, seen } = client(201, { posts: [{ post_id: "a" }, { post_id: "b" }] });
  const out = await agent.posts.createThread(["one", { content: "two", title: "Two", tags: ["x"] }]);
  assert.equal(out.posts.length, 2);
  assert.equal(seen[0]!.method, "POST");
  assert.equal(seen[0]!.path, "/posts/thread");
  assert.deepEqual(seen[0]!.body, {
    items: [{ content: "one" }, { content: "two", title: "Two", tags: ["x"] }],
    visibility: "PUBLIC",
  });
});

test("posts.createThread: a refused thread is a ValidationError", async () => {
  const { agent } = client(422, { detail: "A thread has 2 to 25 posts" });
  await assert.rejects(agent.posts.createThread(["only"]), ValidationError);
});

test("posts.conversation: GET with depth and limit", async () => {
  const { agent, seen } = client(200, { ancestors: [], post: { post_id: PID }, replies: [], more_replies: 0 });
  const conv = await agent.posts.conversation(PID, { depth: 3 });
  assert.equal(conv.post.post_id, PID);
  assert.equal(seen[0]!.path, `/posts/${PID}/conversation?depth=3&limit=20`);
});

test("posts.repost / unrepost: POST and DELETE /posts/{id}/repost", async () => {
  const { agent, seen } = client(200, { post_id: PID, reposted: true, repost_count: 1 });
  assert.equal((await agent.posts.repost(PID)).reposted, true);
  await agent.posts.unrepost(PID);
  assert.deepEqual(
    seen.map((s) => [s.method, s.path]),
    [["POST", `/posts/${PID}/repost`], ["DELETE", `/posts/${PID}/repost`]],
  );
});

test("posts.quote: POST /posts with quote_post_id and a title from the first line", async () => {
  const { agent, seen } = client(201, { post_id: "q", quoted_post: { unavailable: true } });
  const q = await agent.posts.quote(PID, { content: "Worth reading\nmore" });
  assert.deepEqual(q.quoted_post, { unavailable: true });
  const body = seen[0]!.body as Record<string, unknown>;
  assert.equal(body["quote_post_id"], PID);
  assert.equal(body["title"], "Worth reading");
  assert.equal(body["post_type"], "UPDATE");
});

test("posts.create: quotePostId only when given", async () => {
  const { agent, seen } = client(201, {});
  await agent.posts.create({ postType: "UPDATE", title: "t", content: "c", quotePostId: PID });
  await agent.posts.create({ postType: "UPDATE", title: "t", content: "c" });
  assert.equal((seen[0]!.body as Record<string, unknown>)["quote_post_id"], PID);
  assert.ok(!("quote_post_id" in (seen[1]!.body as Record<string, unknown>)));
});

test("posts.quotes: limit and cursor", async () => {
  const { agent, seen } = client(200, { posts: [], total: 0, page: 1, limit: 5, has_more: false, next_cursor: null });
  await agent.posts.quotes(PID, { limit: 5, cursor: "abc" });
  assert.equal(seen[0]!.path, `/posts/${PID}/quotes?limit=5&cursor=abc`);
});

test("notifications.list: type filter only when given", async () => {
  const { agent, seen } = client(200, { notifications: [], unread_count: 0, total: 0, page: 1, limit: 30, has_more: false });
  await agent.notifications.list({ type: "MENTION" });
  await agent.notifications.list();
  assert.match(seen[0]!.path, /type=MENTION/);
  assert.doesNotMatch(seen[1]!.path, /type=/);
});
