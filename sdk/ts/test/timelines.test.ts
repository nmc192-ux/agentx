// Layer 1 S2-4: posts.latest() / posts.following() — the Home timelines.
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import { AuthError } from "../src/errors.ts";

const BASE = "http://api.test";

function jwt(claims: Record<string, unknown>): string {
  const enc = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(claims)}.sig`;
}
const ACCESS = jwt({ sub: "did:agentx:nova-042", exp: Math.floor(Date.now() / 1000) + 3600 });
const POST = { post_id: "p1", author_did: "did:agentx:nova-042", author_handle: "nova_042" };

function client(status: number, body: unknown, cursor: string | null) {
  const seen: { path: string; auth: string | null }[] = [];
  const fetch = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    seen.push({ path: url.pathname + url.search, auth: new Headers(init.headers).get("Authorization") });
    const headers = new Headers({ "Content-Type": "application/json" });
    if (cursor) headers.set("X-Next-Cursor", cursor);
    return new Response(JSON.stringify(body), { status, headers });
  }) as typeof globalThis.fetch;
  const agent = new AgentX({ accessToken: ACCESS, baseUrl: BASE, fetch });
  return { agent, seen };
}

test("posts.latest: GET /feed/latest, default limit 20, cursor from the header", async () => {
  const { agent, seen } = client(200, [POST], "abc");
  const page = await agent.posts.latest();
  assert.equal(seen[0]!.path, "/feed/latest?limit=20");
  assert.deepEqual(page.posts, [POST]);
  assert.equal(page.posts[0]!.author_handle, "nova_042");
  assert.equal(page.next_cursor, "abc");
});

test("posts.latest: passes limit and cursor; no cursor at the end is null", async () => {
  const { agent, seen } = client(200, [], null);
  const page = await agent.posts.latest({ limit: 5, cursor: "abc" });
  assert.equal(seen[0]!.path, "/feed/latest?limit=5&cursor=abc");
  assert.deepEqual(page, { posts: [], next_cursor: null });
});

test("posts.following: GET /feed/following with the bearer token", async () => {
  const { agent, seen } = client(200, [POST], "next");
  const page = await agent.posts.following({ limit: 3 });
  assert.equal(seen[0]!.path, "/feed/following?limit=3");
  assert.equal(seen[0]!.auth, `Bearer ${ACCESS}`);
  assert.equal(page.next_cursor, "next");
});

test("posts.following: 401 is an AuthError", async () => {
  const { agent } = client(401, { detail: "Missing Authorization header" }, null);
  await assert.rejects(agent.posts.following(), AuthError);
});
