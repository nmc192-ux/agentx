// agent.wallet / agent.governance / agent.collectives: routes, query strings, bodies and
// refusals, with fetch stubbed. Body-for-body parity with agentx-py is checked from Python
// in sdk/tests/test_ts_parity_economy.py.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import { AgentXError, AuthError, ConflictError, NotFoundError } from "../src/errors.ts";

const BASE = "http://api.test";
const DID = "did:agentx:atlas";
const PROPOSAL = "6f1c0e1e-7d8a-4c1b-9a51-0d3f2b7c1a10";
const COLL = "0b7a4c3e-2f1d-4e5a-8b6c-9d0e1f2a3b4c";

type Seen = { method: string; path: string; auth: string | null; body: unknown };
type Reply = { status?: number; body?: unknown };

function client(reply: Reply = { body: {} }, agentDid: string | undefined = DID) {
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
  const agent = new AgentX({ accessToken: "tok", agentDid, baseUrl: BASE, fetch });
  return { agent, seen, last: () => seen[seen.length - 1]! };
}

const WALLET = { wallet_id: COLL, agent_id: COLL, balance: 7, updated_at: "now", wallet_type: "agent" };

// ── Wallet ───────────────────────────────────────────────────────────────────

test("wallet.get looks this agent's wallet up by DID, authenticated", async () => {
  const { agent, last } = client({ body: WALLET });
  const w = await agent.wallet.get();
  assert.equal(w.balance, 7);
  assert.equal(last().method, "GET");
  assert.equal(last().path, "/wallets/by-did?agent_did=did%3Aagentx%3Aatlas");
  assert.equal(last().auth, "Bearer tok");
});

test("wallet.get on an agent with no wallet is NotFoundError", async () => {
  const { agent } = client({ status: 404, body: { detail: "No wallet" } });
  await assert.rejects(agent.wallet.get(), NotFoundError);
});

test("wallet.get without a known DID refuses before any request", async () => {
  const { agent, seen } = client({ body: WALLET }, "");
  await assert.rejects(async () => agent.wallet.get(), AgentXError);
  assert.equal(seen.length, 0);
});

test("wallet.create opens at 0 by default; a minting balance is passed through", async () => {
  const { agent, seen } = client({ status: 201, body: WALLET });
  await agent.wallet.create();
  await agent.wallet.create({ initialBalance: 100 });
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/wallets", { initial_balance: 0 }],
    ["POST", "/wallets", { initial_balance: 100 }],
  ]);
});

test("wallet.create with a balance by a non-founder surfaces the server's 403", async () => {
  const { agent } = client({ status: 403, body: { detail: "FOUNDER only" } });
  await assert.rejects(agent.wallet.create({ initialBalance: 100 }), AuthError);
});

test("wallet.balance is the wallet's balance", async () => {
  const { agent } = client({ body: WALLET });
  assert.equal(await agent.wallet.balance(), 7);
});

// ── Governance ───────────────────────────────────────────────────────────────

test("governance.createProposal sends agentx-py's body; options become payload", async () => {
  const { agent, seen } = client({ status: 201, body: { proposal_id: PROPOSAL } });
  await agent.governance.createProposal({ title: "t", description: "d" });
  await agent.governance.createProposal({
    title: "t",
    description: "d",
    proposalType: "parameter_change",
    options: { fee: 2 },
    votingDays: 3,
  });
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/governance/proposals", { title: "t", description: "d", proposal_type: "general", voting_days: 7 }],
    [
      "POST",
      "/governance/proposals",
      { title: "t", description: "d", proposal_type: "parameter_change", voting_days: 3, payload: { fee: 2 } },
    ],
  ]);
});

test("governance.listProposals: status only when given; list or {items} accepted", async () => {
  const one = client({ body: [{ proposal_id: PROPOSAL }] });
  assert.equal((await one.agent.governance.listProposals()).length, 1);
  assert.equal(one.last().path, "/governance/proposals");
  const two = client({ body: { items: [{ proposal_id: PROPOSAL }, { proposal_id: COLL }] } });
  assert.equal((await two.agent.governance.listProposals({ status: "all" })).length, 2);
  assert.equal(two.last().path, "/governance/proposals?status=all");
});

test("governance.vote posts the proposal id and option", async () => {
  const { agent, last } = client({ body: { vote_id: COLL, vote: "no" } });
  await agent.governance.vote(PROPOSAL, "no");
  assert.equal(last().method, "POST");
  assert.equal(last().path, "/governance/vote");
  assert.deepEqual(last().body, { proposal_id: PROPOSAL, vote: "no" });
});

test("governance.vote refuses an unknown option before any request", async () => {
  const { agent, seen } = client();
  for (const bad of ["YES", "maybe", "", undefined]) {
    await assert.rejects(agent.governance.vote(PROPOSAL, bad as never), TypeError);
  }
  assert.equal(seen.length, 0);
});

test("governance.vote twice surfaces the server's 409 as ConflictError", async () => {
  const { agent } = client({ status: 409, body: { detail: "Already voted" } });
  await assert.rejects(agent.governance.vote(PROPOSAL, "yes"), ConflictError);
});

test("governance.results reads the decided proposals", async () => {
  const { agent, last } = client({ body: [] });
  assert.deepEqual(await agent.governance.results(), []);
  assert.equal(last().path, "/governance/results");
});

// ── Collectives ──────────────────────────────────────────────────────────────

test("collectives.create sends agentx-py's body; charter only when given", async () => {
  const { agent, seen } = client({ status: 201, body: { collective_id: COLL } });
  await agent.collectives.create({ name: "Guild", description: "SQL" });
  await agent.collectives.create({ name: "Guild", description: "SQL", charter: "Be kind.", isPublic: false });
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/collectives", { name: "Guild", description: "SQL", is_public: true }],
    ["POST", "/collectives", { name: "Guild", description: "SQL", is_public: false, charter: "Be kind." }],
  ]);
});

test("collectives.list defaults to limit 50 and unwraps {collectives}", async () => {
  const { agent, last } = client({ body: { collectives: [{ collective_id: COLL }], total: 1 } });
  const list = await agent.collectives.list();
  assert.equal(list[0]!.collective_id, COLL);
  assert.equal(last().path, "/collectives?limit=50");
});

test("collectives get / members / join / approve routes and bodies", async () => {
  const { agent, seen } = client({ body: [] });
  await agent.collectives.get(COLL);
  await agent.collectives.members(COLL);
  await agent.collectives.join(COLL);
  await agent.collectives.join(COLL, { message: "hi" });
  await agent.collectives.approve(COLL, "did:agentx:bruno");
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["GET", `/collectives/${COLL}`, undefined],
    ["GET", `/collectives/${COLL}/members`, undefined],
    ["POST", `/collectives/${COLL}/join`, {}],
    ["POST", `/collectives/${COLL}/join`, { message: "hi" }],
    ["POST", `/collectives/${COLL}/members/did:agentx:bruno/approve`, {}],
  ]);
});

test("collectives.approve by a non-admin surfaces the server's 403", async () => {
  const { agent } = client({ status: 403, body: { detail: "Owner or admin only" } });
  await assert.rejects(agent.collectives.approve(COLL, "did:agentx:bruno"), AuthError);
});

test("collectives: a crafted id cannot pick another route; nothing is sent", async () => {
  const { agent, seen } = client();
  for (const bad of [`${COLL}/members`, "../wallets", "..", "", "a\\b"]) {
    await assert.rejects(agent.collectives.get(bad), TypeError);
    await assert.rejects(agent.collectives.members(bad), TypeError);
    await assert.rejects(agent.collectives.join(bad), TypeError);
    await assert.rejects(agent.collectives.approve(bad, "did:agentx:bruno"), TypeError);
    await assert.rejects(agent.collectives.approve(COLL, bad), TypeError);
  }
  assert.equal(seen.length, 0);
});

test("collectives: ? and # stay inside one segment", async () => {
  const { agent, seen } = client();
  await agent.collectives.get("a?b#c");
  assert.equal(seen[0]!.path, "/collectives/a%3Fb%23c");
});
