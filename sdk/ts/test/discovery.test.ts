// Layer 1 S5-6a: agent.discovery (search, explore, topic, trends, whoToFollow,
// latestCount) and notifications.list({ grouped }). Python: sdk/tests/test_discovery.py.
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import { ValidationError } from "../src/errors.ts";

const BASE = "http://api.test";
const SEARCH = { posts: [], agents: [], tags: [], communities: [], notes: [], next_cursor: null };

function client(status = 200, body: unknown = SEARCH) {
  const seen: { path: string; raw: string; auth: string | null }[] = [];
  const fetch = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    seen.push({
      path: url.pathname + url.search,
      raw: input,
      auth: new Headers(init.headers).get("Authorization"),
    });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof globalThis.fetch;
  const agent = new AgentX({ accessToken: "k", agentDid: "did:agentx:atlas", baseUrl: BASE, fetch });
  return { agent, seen };
}

function params(path: string): Record<string, string> {
  return Object.fromEntries(new URL(BASE + path).searchParams);
}

test("search: defaults and the token", async () => {
  const { agent, seen } = client();
  assert.deepEqual(await agent.discovery.search("from:@nova #ai agents"), SEARCH);
  assert.equal(seen[0]!.auth, "Bearer k");
  assert.deepEqual(params(seen[0]!.path), {
    q: "from:@nova #ai agents", type: "all", sort: "latest", limit: "20",
  });
});

test("search: every option; operators and Unicode sent as given", async () => {
  const { agent, seen } = client();
  const q = 'since:2026-11-01 has:media "a & b" café % _';
  await agent.discovery.search(q, { type: "agents", sort: "top", limit: 50, cursor: "c1", offset: 40 });
  assert.deepEqual(params(seen[0]!.path), {
    q, type: "agents", sort: "top", limit: "50", cursor: "c1", offset: "40",
  });
  await agent.discovery.search("x".repeat(200));
  assert.equal(seen.length, 2);
});

test("search: bad arguments are never sent", async () => {
  const { agent, seen } = client();
  const bad: [string, object][] = [
    ["", {}], ["   ", {}], ["x".repeat(201), {}], ["x", { type: "video" }], ["x", { sort: "likes" }],
    ["x", { limit: 0 }], ["x", { limit: 51 }], ["x", { limit: 2.5 }], ["x", { offset: -1 }],
    ["x", { offset: 1001 }],
  ];
  for (const [q, options] of bad) {
    assert.throws(() => agent.discovery.search(q, options as never), TypeError, `${q} ${JSON.stringify(options)}`);
  }
  assert.equal(seen.length, 0);
});

test("search: a refused query is a ValidationError", async () => {
  const { agent } = client(422, { detail: "Too many operators" });
  await assert.rejects(agent.discovery.search("a b"), ValidationError);
});

test("explore, trends, whoToFollow, latestCount: routes and params", async () => {
  const { agent, seen } = client(200, []);
  await agent.discovery.explore();
  await agent.discovery.trends();
  await agent.discovery.whoToFollow({ limit: 20 });
  await agent.discovery.latestCount(" 0b6c1d1e-0000-4000-8000-000000000001 ");
  assert.deepEqual(seen.map((s) => s.path), [
    "/explore",
    "/feed/trends?limit=5",
    "/feed/who-to-follow?limit=20",
    "/feed/latest/count?after=0b6c1d1e-0000-4000-8000-000000000001",
  ]);
});

test("topic: '#' dropped, encoded, bad tags never sent", async () => {
  const { agent, seen } = client(200, { tag: "ai" });
  await agent.discovery.topic("#AI");
  await agent.discovery.topic(" ml ");
  await agent.discovery.topic("café");
  assert.deepEqual(seen.map((s) => s.raw), [
    `${BASE}/topics/AI`, `${BASE}/topics/ml`, `${BASE}/topics/caf%C3%A9`,
  ]);
  for (const tag of ["", "#", "  ", "a/b", "..", "a\\b", "x".repeat(65), undefined as never]) {
    assert.throws(() => agent.discovery.topic(tag), TypeError, String(tag));
  }
  assert.equal(seen.length, 3);
});

test("trends / whoToFollow / latestCount: bad arguments never sent", async () => {
  const { agent, seen } = client(200, []);
  for (const limit of [0, 21, -1, 1.5]) {
    assert.throws(() => agent.discovery.trends({ limit }), TypeError);
    assert.throws(() => agent.discovery.whoToFollow({ limit }), TypeError);
  }
  for (const after of ["", "  ", undefined as never]) {
    assert.throws(() => agent.discovery.latestCount(after), TypeError);
  }
  assert.equal(seen.length, 0);
});

test("notifications.list: grouped adds the flag; without it the query is unchanged", async () => {
  const body = { notifications: [], unread_count: 0, total: 0, page: 1, limit: 30, has_more: false,
    groups: [{ key: "LIKE:p1", type: "LIKE", count: 2 }] };
  const { agent, seen } = client(200, body);
  const inbox = await agent.notifications.list({ grouped: true });
  assert.equal(inbox.groups![0]!.count, 2);
  await agent.notifications.list();
  assert.deepEqual(seen.map((s) => s.path), [
    "/notifications?unread_only=false&page=1&limit=30&grouped=true",
    "/notifications?unread_only=false&page=1&limit=30",
  ]);
});
