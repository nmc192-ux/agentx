// agent.contracts and agent.tasks.reclaim: routes, bodies, error mapping, crafted ids, with
// fetch stubbed. Body-for-body parity with agentx-social is checked from Python in
// sdk/tests/test_ts_parity_tasks.py.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import { AuthError, ConflictError, ValidationError } from "../src/errors.ts";

const BASE = "http://api.test";
const TASK = "6f1c0e1e-7d8a-4c1b-9a51-0d3f2b7c1a10";
const CONTRACT = "2d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f6a";
const BID = "3e4f5a6b-7c8d-4e9f-8a1b-2c3d4e5f6a7b";

type Seen = { method: string; path: string; auth: string | null; body: unknown };
type Reply = { status?: number; body?: unknown };

function client(reply: Reply = { body: {} }) {
  const seen: Seen[] = [];
  const fetch = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    seen.push({
      method: init.method ?? "GET",
      path: url.pathname + url.search,
      auth: new Headers(init.headers).get("Authorization"),
      body: init.body === undefined ? undefined : JSON.parse(init.body as string),
    });
    const text = reply.body === undefined ? null : JSON.stringify(reply.body);
    return new Response(text, { status: reply.status ?? 200 });
  }) as typeof globalThis.fetch;
  const agent = new AgentX({ accessToken: "tok", agentDid: "did:agentx:atlas", baseUrl: BASE, fetch });
  return { agent, seen, last: () => seen[seen.length - 1]! };
}

// ── Task reclaim ─────────────────────────────────────────────────────────────

test("tasks.reclaim posts {} with the bearer token", async () => {
  const { agent, last } = client({ body: { task_id: TASK, status: "cancelled" } });
  const t = await agent.tasks.reclaim(TASK);
  assert.equal(t.status, "cancelled");
  assert.deepEqual([last().method, last().path, last().body], ["POST", `/tasks/${TASK}/reclaim`, {}]);
  assert.equal(last().auth, "Bearer tok");
});

test("tasks.reclaim refusals keep their meaning: 403 not creator, 409 too early or off", async () => {
  const notMine = client({ status: 403, body: { detail: "Only the task creator can reclaim" } });
  await assert.rejects(notMine.agent.tasks.reclaim(TASK), AuthError);
  const early = client({ status: 409, body: { detail: "The work deadline has not passed" } });
  await assert.rejects(early.agent.tasks.reclaim(TASK), ConflictError);
});

// ── Contracts ────────────────────────────────────────────────────────────────

test("contracts.create sends agentx-social's body; capability goes in payload, Date as ISO", async () => {
  const { agent, seen } = client({ status: 201, body: { contract_id: CONTRACT } });
  await agent.contracts.create({ title: "t", description: "d", budget: 500 });
  await agent.contracts.create({
    title: "t", description: "d", budget: 500, requiredCapability: "sql",
    deadline: new Date(Date.UTC(2026, 11, 1)),
  });
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/contracts", { title: "t", description: "d", budget: 500 }],
    ["POST", "/contracts", {
      title: "t", description: "d", budget: 500, deadline: "2026-12-01T00:00:00.000Z",
      payload: { required_capability: "sql" },
    }],
  ]);
});

test("contracts.list pages like agentx-social and accepts a bare list or an envelope", async () => {
  const bare = client({ body: [{ contract_id: CONTRACT }] });
  assert.equal((await bare.agent.contracts.list()).length, 1);
  assert.equal(bare.last().path, "/contracts?status=open&limit=50&offset=0");
  await bare.agent.contracts.list({ status: "all", limit: 10, offset: 20 });
  assert.equal(bare.last().path, "/contracts?status=all&limit=10&offset=20");
  const env = client({ body: { items: [{ contract_id: CONTRACT }, { contract_id: BID }] } });
  assert.equal((await env.agent.contracts.list()).length, 2);
  const empty = client({ status: 200 });
  assert.deepEqual(await empty.agent.contracts.list(), []);
});

test("contracts.bid, assign, submitResult, complete, cancel, reclaim, dispute: routes and bodies", async () => {
  const { agent, seen } = client({ body: {} });
  await agent.contracts.bid(CONTRACT, 400, { proposal: "two days" });
  await agent.contracts.bid(CONTRACT, 300);
  await agent.contracts.assign(CONTRACT, BID);
  await agent.contracts.submitResult(CONTRACT, { content: { out: 1 }, metadata: { t: 2 } });
  await agent.contracts.submitResult(CONTRACT);
  await agent.contracts.complete(CONTRACT);
  await agent.contracts.cancel(CONTRACT);
  await agent.contracts.reclaim(CONTRACT);
  await agent.contracts.dispute(CONTRACT, "not delivered");
  const c = `/contracts/${CONTRACT}`;
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", `${c}/bid`, { bid_amount: 400, proposal: "two days" }],
    ["POST", `${c}/bid`, { bid_amount: 300 }],
    ["POST", `${c}/assign`, { bid_id: BID }],
    ["POST", `${c}/result`, { result_payload: { out: 1, t: 2 } }],
    ["POST", `${c}/result`, { result_payload: null }],
    ["POST", `${c}/complete`, {}],
    ["POST", `${c}/cancel`, {}],
    ["POST", `${c}/reclaim`, {}],
    ["POST", `${c}/dispute`, { reason: "not delivered" }],
  ]);
  assert.ok(seen.every((s) => s.auth === "Bearer tok"));
});

test("contract money errors: 400 short wallet, 403 not creator, 409 too early", async () => {
  const poor = client({ status: 400, body: { detail: "Insufficient balance" } });
  await assert.rejects(poor.agent.contracts.create({ title: "t", description: "d", budget: 9 }), ValidationError);
  const notMine = client({ status: 403, body: { detail: "creator only" } });
  await assert.rejects(notMine.agent.contracts.reclaim(CONTRACT), AuthError);
  const early = client({ status: 409, body: { detail: "deadline not passed" } });
  await assert.rejects(early.agent.contracts.reclaim(CONTRACT), ConflictError);
});

test("a crafted contract or task id is refused before anything is sent", async () => {
  const { agent, seen } = client({ body: {} });
  const crafted = `${CONTRACT}/../../tasks/${TASK}/approve`;
  for (const bad of ["", ".", "..", crafted, `${CONTRACT}/complete`]) {
    await assert.rejects(agent.contracts.reclaim(bad), TypeError);
    await assert.rejects(agent.contracts.complete(bad), TypeError);
    await assert.rejects(agent.contracts.assign(bad, BID), TypeError);
    await assert.rejects(agent.tasks.reclaim(bad), TypeError);
  }
  assert.equal(seen.length, 0);
});
