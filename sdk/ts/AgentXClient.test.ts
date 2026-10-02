// Route and body checks for the TypeScript client, with fetch stubbed.
// Run: node --test sdk/ts/AgentXClient.test.ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentClient } from "./AgentXClient.ts";

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
