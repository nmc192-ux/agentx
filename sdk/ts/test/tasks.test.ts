// agent.tasks / agent.bounties: routes, bodies, empty lists, error mapping, crafted ids,
// with fetch stubbed. Body-for-body parity with agentx-social is checked from Python in
// sdk/tests/test_ts_parity_tasks.py.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import { AuthError, ConflictError, NotFoundError, ValidationError } from "../src/errors.ts";

const BASE = "http://api.test";
const TASK = "6f1c0e1e-7d8a-4c1b-9a51-0d3f2b7c1a10";
const BOUNTY = "0b7a4c3e-2f1d-4e5a-8b6c-9d0e1f2a3b4c";

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

// ── Tasks ────────────────────────────────────────────────────────────────────

test("tasks.act sends to an executor, or routes without one", async () => {
  const { agent, seen } = client({ status: 201, body: { task_id: TASK, status: "PENDING" } });
  const direct = await agent.tasks.act("review", { data: { q: 1 }, executorDid: "did:agentx:bruno" });
  await agent.tasks.act("review");
  assert.equal(direct.task_id, TASK);
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/tasks/create", { task_type: "review", payload: { q: 1 }, executor_agent_did: "did:agentx:bruno" }],
    ["POST", "/tasks/route", { task_type: "review", payload: {} }],
  ]);
  assert.equal(seen[0]!.auth, "Bearer tok");
});

test("tasks.act with no executor available is NotFoundError", async () => {
  const { agent } = client({ status: 404, body: { detail: { error: "NO_EXECUTOR_AVAILABLE" } } });
  await assert.rejects(agent.tasks.act("review"), NotFoundError);
});

test("tasks.accept and tasks.complete update a direct task", async () => {
  const { agent, seen } = client({ body: { task_id: TASK } });
  await agent.tasks.accept(TASK);
  await agent.tasks.complete(TASK, { ok: true });
  assert.deepEqual(seen.map((s) => [s.path, s.body]), [
    [`/tasks/${TASK}/update`, { status: "IN_PROGRESS" }],
    [`/tasks/${TASK}/update`, { status: "COMPLETED", result: { ok: true } }],
  ]);
});

test("tasks.list uses agentx-social's defaults and turns an empty answer into []", async () => {
  const { agent, last } = client({ status: 200 });
  assert.deepEqual(await agent.tasks.list(), []);
  assert.equal(last().path, "/tasks?status=open&limit=50");
  await agent.tasks.list({ status: "in_review", limit: 5 });
  assert.equal(last().path, "/tasks?status=in_review&limit=5");
});

test("tasks.create, bid, submitResult, approve, reject, cancel: routes and bodies", async () => {
  const { agent, seen } = client({ body: {} });
  await agent.tasks.create({ taskType: "review", payload: { q: 1 }, reward: 25 });
  await agent.tasks.bid(TASK, { confidence: 0.4, bidPrice: 3 });
  await agent.tasks.submitResult(TASK, { answer: 42 });
  await agent.tasks.results(TASK);
  await agent.tasks.approve(TASK);
  await agent.tasks.reject(TASK, "missing tests");
  await agent.tasks.reject(TASK);
  await agent.tasks.cancel(TASK);
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/tasks", { task_type: "review", payload: { q: 1 }, reward: 25 }],
    ["POST", `/tasks/${TASK}/bid`, { confidence: 0.4, bid_price: 3 }],
    ["POST", `/tasks/${TASK}/result`, { result_payload: { answer: 42 } }],
    ["GET", `/tasks/${TASK}/results`, undefined],
    ["POST", `/tasks/${TASK}/approve`, {}],
    ["POST", `/tasks/${TASK}/reject`, { reason: "missing tests" }],
    ["POST", `/tasks/${TASK}/reject`, {}],
    ["POST", `/tasks/${TASK}/cancel`, {}],
  ]);
});

test("money errors keep their meaning: 400 short wallet, 403 own task, 409 twice", async () => {
  const poor = client({ status: 400, body: { detail: "Insufficient funds" } });
  await assert.rejects(poor.agent.tasks.create({ taskType: "review", reward: 10 }), ValidationError);
  const own = client({ status: 403, body: { detail: "Cannot bid on your own task" } });
  await assert.rejects(own.agent.tasks.bid(TASK), AuthError);
  const twice = client({ status: 409, body: { detail: "No result under review" } });
  await assert.rejects(twice.agent.tasks.approve(TASK), ConflictError);
});

test("a crafted task id with a slash, . or .. is refused before anything is sent", async () => {
  const { agent, seen } = client({ body: {} });
  const before = seen.length;
  // The server decodes %2F before routing, so this would otherwise approve or distribute
  // something other than TASK. It must fail on the client, without a request.
  const crafted = `${TASK}/../../markets/bounties/x/distribute`;
  for (const bad of ["", ".", "..", crafted, `${TASK}/cancel`]) {
    await assert.rejects(agent.tasks.approve(bad), TypeError);
    await assert.rejects(agent.tasks.reject(bad, "no"), TypeError);
    await assert.rejects(agent.bounties.distribute(bad), TypeError);
  }
  assert.equal(seen.length, before);
});

// ── Bounties ─────────────────────────────────────────────────────────────────

test("bounties.create sends the snake_case body; a Date deadline goes as ISO UTC", async () => {
  const { agent, seen } = client({ status: 201, body: { bounty_id: BOUNTY } });
  const b = await agent.bounties.create({
    title: "Fix the query",
    description: "Make it fast",
    capabilityRequired: "sql",
    rewardPool: 100,
  });
  await agent.bounties.create({
    title: "t",
    description: "",
    capabilityRequired: "sql",
    rewardPool: 1,
    deadline: new Date(Date.UTC(2026, 11, 1)),
  });
  assert.equal(b.bounty_id, BOUNTY);
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/markets/bounties", {
      title: "Fix the query", description: "Make it fast", capability_required: "sql", reward_pool: 100,
    }],
    ["POST", "/markets/bounties", {
      title: "t", description: "", capability_required: "sql", reward_pool: 1,
      deadline: "2026-12-01T00:00:00.000Z",
    }],
  ]);
});

test("bounties.list leaves out unset filters and pages like agentx-social", async () => {
  const { agent, last } = client({ status: 200 });
  assert.deepEqual(await agent.bounties.list(), []);
  assert.equal(last().path, "/markets/bounties?limit=50&offset=0");
  await agent.bounties.list({ status: "open", capability: "sql", limit: 5, offset: 10 });
  assert.equal(last().path, "/markets/bounties?status=open&capability=sql&limit=5&offset=10");
});

test("bounties.get, submit, submissions, evaluate, distribute, cancel", async () => {
  const { agent, seen } = client({ body: {} });
  const SUB = "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f";
  await agent.bounties.get(BOUNTY);
  await agent.bounties.submit(BOUNTY);
  await agent.bounties.submit(BOUNTY, { solutionData: { sql: "select 1" }, summary: "one line" });
  await agent.bounties.submissions(BOUNTY);
  await agent.bounties.evaluate(BOUNTY, SUB, 0.75);
  await agent.bounties.distribute(BOUNTY);
  await agent.bounties.cancel(BOUNTY);
  const root = `/markets/bounties/${BOUNTY}`;
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["GET", root, undefined],
    ["POST", `${root}/submit`, { solution_data: {} }],
    ["POST", `${root}/submit`, { solution_data: { sql: "select 1" }, summary: "one line" }],
    ["GET", `${root}/submissions`, undefined],
    ["POST", `${root}/submissions/${SUB}/evaluate`, { score: 0.75 }],
    ["POST", `${root}/distribute`, {}],
    ["POST", `${root}/cancel`, {}],
  ]);
});

test("bounty errors: 403 not the creator, 409 already paid, 404 missing", async () => {
  const notMine = client({ status: 403, body: { detail: "Only the creator" } });
  await assert.rejects(notMine.agent.bounties.distribute(BOUNTY), AuthError);
  const paid = client({ status: 409, body: { detail: "Already rewarded" } });
  await assert.rejects(paid.agent.bounties.distribute(BOUNTY), ConflictError);
  const gone = client({ status: 404, body: { detail: "Bounty not found" } });
  await assert.rejects(gone.agent.bounties.get(BOUNTY), NotFoundError);
});
