// Route and body checks for the TypeScript client, with fetch stubbed.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentClient, AgentXError } from "../src/legacy.ts";

type Call = { method: string; path: string; body: unknown };

function stubFetch(answers: Record<string, unknown> = {}): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = (async (url: string, init: RequestInit = {}) => {
    const u = new URL(url);
    const path = u.pathname + u.search;
    calls.push({
      method: init.method ?? "GET",
      path,
      body: init.body ? JSON.parse(init.body as string) : undefined,
    });
    const answer = path === "/auth/token" ? { access_token: "t" } : (answers[u.pathname] ?? {});
    return new Response(JSON.stringify(answer), { status: 200 });
  }) as typeof fetch;
  return calls;
}

function client(): AgentClient {
  return new AgentClient({ baseUrl: "http://api.test", agentDid: "did:agentx:me-001", secret: "s" });
}

const TASK = "11111111-1111-1111-1111-111111111111";

test("post() publishes a post, not the internal HTTP helper", async () => {
  const calls = stubFetch();
  await client().post("hello", { tags: ["intro"] });
  const last = calls.at(-1)!;
  assert.equal(last.path, "/posts");
  assert.equal((last.body as { content: string }).content, "hello");
});

test("like() posts to the like route with no body", async () => {
  const calls = stubFetch();
  await client().like("p1");
  assert.deepEqual(calls.at(-1), { method: "POST", path: "/posts/p1/like", body: undefined });
});

test("bidOnTask() uses /bid with bid_price and confidence", async () => {
  const calls = stubFetch();
  await client().bidOnTask(TASK, 50, { confidence: 0.9 });
  assert.deepEqual(calls.at(-1), {
    method: "POST",
    path: `/tasks/${TASK}/bid`,
    body: { bid_price: 50, confidence: 0.9 },
  });
});

test("completeTask() sends result_payload", async () => {
  const calls = stubFetch();
  await client().completeTask(TASK, { ok: true });
  assert.deepEqual(calls.at(-1)!.body, { result_payload: { ok: true } });
  assert.equal(calls.at(-1)!.path, `/tasks/${TASK}/result`);
});

test("cancelTask() posts to /cancel", async () => {
  const calls = stubFetch();
  await client().cancelTask(TASK);
  assert.equal(calls.at(-1)!.path, `/tasks/${TASK}/cancel`);
});

test("vote() uses /governance/vote with proposal_id and vote", async () => {
  const calls = stubFetch();
  await client().vote("prop-1", "yes");
  assert.deepEqual(calls.at(-1), {
    method: "POST",
    path: "/governance/vote",
    body: { proposal_id: "prop-1", vote: "yes" },
  });
});

test("vote() rejects an unknown choice before sending", async () => {
  const calls = stubFetch();
  await assert.rejects(client().vote("prop-1", "maybe" as "yes"));
  assert.equal(calls.length, 0);
});

// ── Ids cannot choose the route (sprint 15 security review) ──────────────────
//
// fetch() parses the URL with the WHATWG parser, which folds ".." and even "%2e%2e"
// path segments away: `/agents/../tasks/X/approve` becomes `/tasks/X/approve`. Every
// id therefore goes through seg(), which refuses slashes and dot segments before any
// request is sent and percent-encodes the rest (so "%2e%2e" reaches the server as the
// literal text "%2e%2e", never as "..").

test("legacy client refuses ids with a slash or dot segment before sending", async () => {
  const calls = stubFetch();
  const c = client();
  const attempts: Array<(bad: string) => Promise<unknown>> = [
    (bad) => c.like(bad),
    (bad) => c.joinRoom(bad),
    (bad) => c.leaveRoom(bad),
    (bad) => c.bidOnTask(bad),
    (bad) => c.completeTask(bad, {}),
    (bad) => c.cancelTask(bad),
    (bad) => c.invokeAgent(bad, "cap", {}),
    (bad) => c.getProfile(bad),
  ];
  for (const bad of ["../tasks/x/approve", "abc/close", "..", ".", "", "/", "a\\b"]) {
    for (const attempt of attempts) {
      // seg() throws TypeError; getProfile("") trips its own "no agentDid" check first.
      await assert.rejects(
        attempt(bad),
        (e: unknown) => e instanceof TypeError || e instanceof AgentXError,
        `${bad} was sent`,
      );
    }
  }
  assert.equal(calls.length, 0, "no request may leave for a refused id");
});

test("legacy client keeps odd ids inside their own path segment", async () => {
  const calls = stubFetch();
  const c = client();
  await c.getProfile("%2e%2e");
  assert.equal(calls.at(-1)!.path, "/agents/%252e%252e");
  await c.like("x?admin=1#y");
  assert.equal(calls.at(-1)!.path, "/posts/x%3Fadmin%3D1%23y/like");
  await c.getProfile("did:agentx:other-1");
  assert.equal(calls.at(-1)!.path, "/agents/did:agentx:other-1");
});
