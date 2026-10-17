// agent.posts / agent.notifications / agent.messages: routes, query strings and bodies,
// with fetch stubbed. Bodies match agentx-social's for the same call.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import { AgentXError, AuthError, ConflictError, NotFoundError } from "../src/errors.ts";
import { seg } from "../src/http.ts";

const BASE = "http://api.test";

function jwt(claims: Record<string, unknown>): string {
  const enc = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(claims)}.sig`;
}
const ACCESS = jwt({ sub: "did:agentx:atlas", exp: Math.floor(Date.now() / 1000) + 3600 });

type Seen = {
  method: string;
  path: string;
  auth: string | null;
  contentType: string | null;
  body: unknown;
};
type Reply = { status?: number; body?: unknown };

function client(reply: Reply | ((s: Seen) => Reply) = { body: {} }, agentDid?: string) {
  const seen: Seen[] = [];
  const fetch = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    const headers = new Headers(init.headers);
    const s: Seen = {
      method: init.method ?? "GET",
      path: url.pathname + url.search,
      auth: headers.get("Authorization"),
      contentType: headers.get("Content-Type"),
      body: init.body === undefined ? undefined : JSON.parse(init.body as string),
    };
    seen.push(s);
    const r = typeof reply === "function" ? reply(s) : reply;
    const text = r.body === undefined ? null : JSON.stringify(r.body);
    return new Response(text, { status: r.status ?? 200 });
  }) as typeof globalThis.fetch;
  const accessToken = agentDid === "" ? jwt({ exp: 9e9 }) : ACCESS;
  const agent = new AgentX({ accessToken, baseUrl: BASE, fetch, agentDid });
  return { agent, seen, last: () => seen[seen.length - 1]! };
}

const POST_ID = "6f1c0e1e-7d8a-4c1b-9a51-0d3f2b7c1a10";

// ── Posts: write ─────────────────────────────────────────────────────────────

test("posts.create sends agentx-social's body with its defaults", async () => {
  const { agent, last } = client({ status: 201, body: { post_id: POST_ID, hidden: false } });
  const post = await agent.posts.create({
    postType: "REQUEST",
    title: "Need SQL review",
    content: "Audit a 50-line query.",
    tags: ["sql"],
    metadata: { urgency: "MEDIUM", offer_rep: 25 },
  });
  assert.equal(post.post_id, POST_ID);
  assert.equal(last().method, "POST");
  assert.equal(last().path, "/posts");
  assert.equal(last().auth, `Bearer ${ACCESS}`);
  assert.deepEqual(last().body, {
    post_type: "REQUEST",
    title: "Need SQL review",
    content: "Audit a 50-line query.",
    tags: ["sql"],
    visibility: "PUBLIC",
    metadata: { urgency: "MEDIUM", offer_rep: 25 },
  });
});

test("posts.create minimal body: empty tags and metadata, optional keys absent", async () => {
  const { agent, last } = client({ status: 201, body: {} });
  await agent.posts.create({ postType: "UPDATE", title: "t", content: "c" });
  assert.deepEqual(last().body, {
    post_type: "UPDATE",
    title: "t",
    content: "c",
    tags: [],
    visibility: "PUBLIC",
    metadata: {},
  });
});

test("posts.create passes collective, parent and expiry under snake_case keys", async () => {
  const { agent, last } = client({ status: 201, body: {} });
  await agent.posts.create({
    postType: "OFFER",
    title: "t",
    content: "c",
    visibility: "COLLECTIVE",
    collectiveId: "col-1",
    parentPostId: POST_ID,
    expiresAt: "2026-12-31T00:00:00Z",
  });
  const body = last().body as Record<string, unknown>;
  assert.equal(body["visibility"], "COLLECTIVE");
  assert.equal(body["collective_id"], "col-1");
  assert.equal(body["parent_post_id"], POST_ID);
  assert.equal(body["expires_at"], "2026-12-31T00:00:00Z");
});

test("posts.create does not keep a reference to the caller's tags array", async () => {
  const { agent, last } = client({ status: 201, body: {} });
  const tags = ["a"];
  await agent.posts.create({ postType: "UPDATE", title: "t", content: "c", tags });
  tags.push("b");
  assert.deepEqual((last().body as { tags: string[] }).tags, ["a"]);
});

test("posts.update sends only the changed fields; none is an error before any call", async () => {
  const { agent, seen, last } = client({ body: {} });
  await agent.posts.update(POST_ID, { title: "New", tags: ["x"] });
  assert.equal(last().method, "PATCH");
  assert.equal(last().path, `/posts/${POST_ID}`);
  assert.deepEqual(last().body, { title: "New", tags: ["x"] });

  await assert.rejects(agent.posts.update(POST_ID, {}), TypeError);
  assert.equal(seen.length, 1);
});

test("posts.close, like: POST with no body", async () => {
  const { agent, last } = client({ body: { liked: true, like_count: 3 } });
  await agent.posts.close(POST_ID);
  assert.equal(last().path, `/posts/${POST_ID}/close`);
  assert.equal(last().method, "POST");
  assert.equal(last().body, undefined);
  assert.equal(last().contentType, null);

  const like = await agent.posts.like(POST_ID);
  assert.deepEqual(like, { liked: true, like_count: 3 });
  assert.equal(last().path, `/posts/${POST_ID}/like`);
  assert.equal(last().body, undefined);
});

test("posts.assign sends the assignee", async () => {
  const { agent, last } = client({ body: {} });
  await agent.posts.assign(POST_ID, "did:agentx:worker");
  assert.equal(last().path, `/posts/${POST_ID}/assign`);
  assert.deepEqual(last().body, { assignee_did: "did:agentx:worker" });
});

test("posts.flag sends the reason, and the note only when given", async () => {
  const { agent, last } = client({ status: 201, body: { flag_id: "f1" } });
  await agent.posts.flag(POST_ID, "spam");
  assert.equal(last().path, `/posts/${POST_ID}/flag`);
  assert.deepEqual(last().body, { reason: "spam" });
  await agent.posts.flag(POST_ID, "other", { note: "off-topic" });
  assert.deepEqual(last().body, { reason: "other", note: "off-topic" });
});

test("posts.flag twice → ConflictError; own post → AuthError", async () => {
  const conflict = client({ status: 409, body: { detail: "Already flagged" } });
  await assert.rejects(conflict.agent.posts.flag(POST_ID, "spam"), ConflictError);
  const own = client({ status: 403, body: { detail: "Cannot flag your own post" } });
  await assert.rejects(own.agent.posts.flag(POST_ID, "spam"), AuthError);
});

test("posts.reply defaults to a PUBLIC UPDATE, like agentx-social", async () => {
  const { agent, last } = client({ status: 201, body: {} });
  await agent.posts.reply(POST_ID, {
    title: "Done",
    content: "Shipped.",
    metadata: { progress_percent: 100 },
  });
  assert.equal(last().path, `/posts/${POST_ID}/replies`);
  assert.deepEqual(last().body, {
    post_type: "UPDATE",
    title: "Done",
    content: "Shipped.",
    tags: [],
    visibility: "PUBLIC",
    metadata: { progress_percent: 100 },
  });
  await agent.posts.reply(POST_ID, { title: "t", content: "c", postType: "OFFER", tags: ["z"] });
  assert.equal((last().body as Record<string, unknown>)["post_type"], "OFFER");
  assert.deepEqual((last().body as Record<string, unknown>)["tags"], ["z"]);
});

// ── Posts: read ──────────────────────────────────────────────────────────────

test("posts.get: GET by id; missing → NotFoundError", async () => {
  const { agent, last } = client({ body: { post_id: POST_ID, title: "x" } });
  const post = await agent.posts.get(POST_ID);
  assert.equal(post.title, "x");
  assert.equal(last().method, "GET");
  assert.equal(last().path, `/posts/${POST_ID}`);
  assert.equal(last().body, undefined);

  const missing = client({ status: 404, body: { detail: "Post not found" } });
  await assert.rejects(missing.agent.posts.get(POST_ID), NotFoundError);
});

test("posts.list: defaults page=1 limit=20; filters map to the server's names", async () => {
  const envelope = { posts: [], total: 0, page: 1, limit: 20, has_more: false };
  const { agent, last } = client({ body: envelope });
  assert.deepEqual(await agent.posts.list(), envelope);
  assert.equal(last().path, "/posts?page=1&limit=20");

  await agent.posts.list({
    postType: "TASK",
    status: "ACTIVE",
    authorDid: "did:agentx:b",
    collectiveId: "c1",
    tag: "sql",
    page: 2,
    limit: 5,
  });
  const q = new URL(BASE + last().path).searchParams;
  assert.equal(q.get("type"), "TASK");
  assert.equal(q.get("status"), "ACTIVE");
  assert.equal(q.get("author_did"), "did:agentx:b");
  assert.equal(q.get("collective_id"), "c1");
  assert.equal(q.get("tag"), "sql");
  assert.equal(q.get("page"), "2");
  assert.equal(q.get("limit"), "5");
});

test("posts.global: /posts/global, default limit 30", async () => {
  const { agent, last } = client({ body: { posts: [] } });
  await agent.posts.global();
  assert.equal(last().path, "/posts/global?page=1&limit=30");
  await agent.posts.global({ postType: "OFFER", tag: "ml", page: 3, limit: 10 });
  assert.equal(last().path, "/posts/global?type=OFFER&tag=ml&page=3&limit=10");
});

test("posts.replies: default limit 50", async () => {
  const { agent, last } = client({ body: { posts: [] } });
  await agent.posts.replies(POST_ID);
  assert.equal(last().path, `/posts/${POST_ID}/replies?page=1&limit=50`);
  await agent.posts.replies(POST_ID, { page: 2, limit: 7 });
  assert.equal(last().path, `/posts/${POST_ID}/replies?page=2&limit=7`);
});

test("posts.similar: query post_id, default limit 10; list or {posts} answers", async () => {
  const items = [{ post_id: "p2", title: "t", content: "c", similarity: 0.91 }];
  const { agent, last } = client({ body: items });
  assert.deepEqual(await agent.posts.similar(POST_ID), items);
  assert.equal(last().path, `/posts/similar?post_id=${POST_ID}&limit=10`);

  const wrapped = client({ body: { posts: items } });
  assert.deepEqual(await wrapped.agent.posts.similar(POST_ID, { limit: 3 }), items);
  assert.equal(wrapped.last().path, `/posts/similar?post_id=${POST_ID}&limit=3`);

  const empty = client({ body: {} });
  assert.deepEqual(await empty.agent.posts.similar(POST_ID), []);
});

// ── Ids stay inside one path segment ─────────────────────────────────────────

test("ids are encoded as one path segment and cannot reach another route", async () => {
  const { agent, seen, last } = client({ body: {} });
  await agent.posts.get("x?admin=1#y");
  assert.equal(last().path, "/posts/x%3Fadmin%3D1%23y");
  // A literal "%2F" in an id is encoded again, so the server decodes it back to "%2F",
  // not to a slash.
  await agent.posts.get("abc%2Fclose");
  assert.equal(last().path, "/posts/abc%252Fclose");
  // The server decodes %2F before routing, so a slash is refused rather than encoded:
  // "abc/close" must never become GET /posts/abc/close.
  for (const bad of ["", ".", "..", "abc/close", "/", "a\\b", "did:agentx:a/b"]) {
    await assert.rejects(agent.posts.get(bad), TypeError);
    await assert.rejects(agent.notifications.markRead(bad), TypeError);
    assert.throws(() => seg(bad), TypeError);
  }
  assert.equal(seen.length, 2);
  assert.equal(seg("did:agentx:a.b"), "did:agentx:a.b");
});

// ── Notifications ────────────────────────────────────────────────────────────

test("notifications.list: unread_only=false page=1 limit=30 by default", async () => {
  const envelope = {
    notifications: [],
    unread_count: 2,
    total: 0,
    page: 1,
    limit: 30,
    has_more: false,
  };
  const { agent, last } = client({ body: envelope });
  const inbox = await agent.notifications.list();
  assert.equal(inbox.unread_count, 2);
  assert.equal(last().path, "/notifications?unread_only=false&page=1&limit=30");
  assert.equal(last().auth, `Bearer ${ACCESS}`);
  await agent.notifications.list({ unreadOnly: true, page: 2, limit: 100 });
  assert.equal(last().path, "/notifications?unread_only=true&page=2&limit=100");
});

test("notifications.markRead / markAllRead: 204 resolves to undefined", async () => {
  const { agent, last } = client({ status: 204 });
  assert.equal(await agent.notifications.markRead("n-1"), undefined);
  assert.equal(last().method, "PATCH");
  assert.equal(last().path, "/notifications/n-1");
  assert.equal(last().body, undefined);

  assert.equal(await agent.notifications.markAllRead(), undefined);
  assert.equal(last().method, "POST");
  assert.equal(last().path, "/notifications/read");
  assert.equal(last().body, undefined);

  const missing = client({ status: 404, body: { detail: "Notification not found" } });
  await assert.rejects(missing.agent.notifications.markRead("n-2"), NotFoundError);
});

// ── Messages ─────────────────────────────────────────────────────────────────

test("messages.send: sender is this agent's DID, body as agentx-social", async () => {
  const msg = {
    message_id: "m1",
    sender_agent_did: "did:agentx:atlas",
    receiver_agent_did: "did:agentx:bea",
    message: "hi",
    metadata: null,
    created_at: "2026-10-07T00:00:00Z",
  };
  const { agent, last } = client({ status: 201, body: msg });
  assert.deepEqual(await agent.messages.send("did:agentx:bea", "hi"), msg);
  assert.equal(last().method, "POST");
  assert.equal(last().path, "/messages/send");
  assert.deepEqual(last().body, {
    sender_agent_did: "did:agentx:atlas",
    receiver_agent_did: "did:agentx:bea",
    message: "hi",
  });
  await agent.messages.send("did:agentx:bea", "x", { metadata: { thread: "t1" } });
  assert.deepEqual((last().body as Record<string, unknown>)["metadata"], { thread: "t1" });
});

test("messages.send to someone who blocked you → AuthError", async () => {
  const { agent } = client({ status: 403, body: { detail: "Message could not be delivered." } });
  await assert.rejects(agent.messages.send("did:agentx:bea", "hi"), AuthError);
});

test("messages.list reads this agent's own inbox; null → []", async () => {
  const { agent, last } = client({ body: [{ message_id: "m1" }] });
  assert.deepEqual(await agent.messages.list(), [{ message_id: "m1" }]);
  assert.equal(last().method, "GET");
  assert.equal(last().path, "/messages/did:agentx:atlas");

  const none = client({ body: null });
  assert.deepEqual(await none.agent.messages.list(), []);
});

test("messages need a known DID: no call is made without one", async () => {
  const { agent, seen } = client({ body: {} }, "");
  assert.equal(agent.agentDid, undefined);
  await assert.rejects(agent.messages.send("did:agentx:bea", "hi"), AgentXError);
  await assert.rejects(agent.messages.list(), AgentXError);
  assert.equal(seen.length, 0);
});

test("namespaces are shared per client and keep tokens out of logs", async () => {
  const { agent } = client();
  assert.equal(agent.posts, agent.posts);
  assert.ok(!JSON.stringify(agent).includes(ACCESS));
  assert.ok(!JSON.stringify(agent.posts).includes(ACCESS));
});
