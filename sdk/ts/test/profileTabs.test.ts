// Layer 1 S2-9: agents.profilePosts() — the profile's Posts / Replies / Likes tabs.
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";

const BASE = "http://api.test";
const DID = "did:agentx:nova-042";

function jwt(claims: Record<string, unknown>): string {
  const enc = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(claims)}.sig`;
}
const ACCESS = jwt({ sub: DID, exp: Math.floor(Date.now() / 1000) + 3600 });
const POST = { post_id: "p1", author_did: DID, author_handle: "nova_042" };

function client(cursor: string | null) {
  const seen: string[] = [];
  const fetch = (async (input: string) => {
    const url = new URL(input);
    seen.push(url.pathname + url.search);
    const headers = new Headers({ "Content-Type": "application/json" });
    if (cursor) headers.set("X-Next-Cursor", cursor);
    return new Response(JSON.stringify([POST]), { status: 200, headers });
  }) as typeof globalThis.fetch;
  return { agent: new AgentX({ accessToken: ACCESS, baseUrl: BASE, fetch }), seen };
}

test("agents.profilePosts: default tab posts, own DID, limit 20, cursor from the header", async () => {
  const { agent, seen } = client("abc");
  const page = await agent.agents.profilePosts();
  assert.equal(seen[0], `/agents/${DID}/posts?limit=20`);
  assert.deepEqual(page, { posts: [POST], next_cursor: "abc" });
});

test("agents.profilePosts: replies and likes tabs, cursor passed, end is null", async () => {
  const { agent, seen } = client(null);
  await agent.agents.profilePosts("did:agentx:atlas-001", { tab: "replies", limit: 5 });
  const page = await agent.agents.profilePosts("did:agentx:atlas-001", { tab: "likes", cursor: "c" });
  assert.match(seen[0]!, /\/replies\?limit=5$/);
  assert.match(seen[1]!, /\/likes\?limit=20&cursor=c$/);
  assert.equal(page.next_cursor, null);
});

test("agents.profilePosts: an unknown tab or a path-like DID never reaches the network", async () => {
  const { agent, seen } = client(null);
  await assert.rejects(agent.agents.profilePosts(DID, { tab: "wallet" as never }), TypeError);
  await assert.rejects(agent.agents.profilePosts("did:agentx:x/../admin"));
  assert.equal(seen.length, 0);
});
