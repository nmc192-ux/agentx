// agent.wallet / agent.governance / agent.collectives: routes, query strings, bodies and
// refusals, with fetch stubbed. Body-for-body parity with agentx-social is checked from Python
// in sdk/tests/test_ts_parity_economy.py.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import {
  AgentXError,
  AuthError,
  ConflictError,
  NotFoundError,
  RateLimitError,
  ServerError,
  ValidationError,
} from "../src/errors.ts";
import { FaucetRefusedError } from "../src/index.ts";

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

// ── Faucet ───────────────────────────────────────────────────────────────────

const CLAIM = {
  claim_id: PROPOSAL, agent_id: COLL, wallet_id: COLL, amount: 25, balance: 25,
  claim_day: "2026-10-15", next_claim_at: "2026-10-16T00:00:00+00:00", transaction_id: PROPOSAL,
};

/** A fetch stub that answers each call from `replies` in turn (with headers). */
function scripted(replies: { status?: number; body?: unknown; headers?: Record<string, string> }[]) {
  const seen: Seen[] = [];
  const fetch = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    seen.push({
      method: init.method ?? "GET",
      path: url.pathname + url.search,
      auth: new Headers(init.headers).get("Authorization"),
      body: init.body === undefined ? undefined : JSON.parse(init.body as string),
    });
    const r = replies[Math.min(seen.length - 1, replies.length - 1)]!;
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), {
      status: r.status ?? 200,
      headers: r.headers,
    });
  }) as typeof globalThis.fetch;
  const agent = new AgentX({ accessToken: "tok", agentDid: DID, baseUrl: BASE, fetch });
  return { agent, seen };
}

test("wallet.claimFaucet posts an empty body, authenticated, and returns the claim", async () => {
  const { agent, seen } = scripted([{ body: CLAIM }]);
  const claim = await agent.wallet.claimFaucet();
  assert.equal(claim.amount, 25);
  assert.equal(claim.balance, 25);
  assert.deepEqual(
    seen.map((s) => [s.method, s.path, s.body, s.auth]),
    [["POST", "/wallets/faucet", {}, "Bearer tok"]],
  );
});

test("wallet.claimFaucet never names an agent in the request", async () => {
  const { agent, seen } = scripted([{ body: CLAIM }]);
  await agent.wallet.claimFaucet();
  assert.ok(!JSON.stringify(seen[0]!.body).includes("did:"));
  assert.ok(!seen[0]!.path.includes("did"));
});

test("a claim already made today is FaucetRefusedError with reason, time and wait; no retry", async () => {
  const detail = {
    reason: "already_claimed",
    message: "Already claimed today.",
    next_claim_at: "2026-10-16T00:00:00+00:00",
  };
  const { agent, seen } = scripted([{ status: 429, body: { detail }, headers: { "Retry-After": "3600" } }]);
  const err = await agent.wallet.claimFaucet().then(
    () => assert.fail("expected a refusal"),
    (e: unknown) => e,
  );
  assert.ok(err instanceof FaucetRefusedError);
  assert.ok(err instanceof AgentXError);
  assert.equal(err.reason, "already_claimed");
  assert.equal(err.message, "Already claimed today.");
  assert.equal(err.nextClaimAt, "2026-10-16T00:00:00+00:00");
  assert.equal(err.retryAfter, 3600);
  assert.equal(err.status, 429);
  assert.equal(seen.length, 1);
});

test("faucet refusals keep their reason for 409 and 403 too", async () => {
  for (const [status, reason] of [[409, "balance_ceiling"], [403, "not_active"], [429, "dry"], [429, "too_young"]] as const) {
    const { agent } = scripted([{ status, body: { detail: { reason, message: "no", next_claim_at: null } } }]);
    await assert.rejects(agent.wallet.claimFaucet(), (e: unknown) => {
      assert.ok(e instanceof FaucetRefusedError);
      assert.equal(e.reason, reason);
      assert.equal(e.nextClaimAt, null);
      assert.equal(e.status, status);
      return true;
    });
  }
});

test("the faucet switched off (404) is FaucetRefusedError 'unavailable'", async () => {
  const { agent } = scripted([{ status: 404, body: { detail: "Not Found" } }]);
  await assert.rejects(agent.wallet.claimFaucet(), (e: unknown) => {
    assert.ok(e instanceof FaucetRefusedError);
    assert.equal(e.reason, "unavailable");
    assert.equal(e.status, 404);
    return true;
  });
});

test("other faucet failures keep their own error type", async () => {
  const cases = [
    [{ status: 500, body: { detail: "boom" } }, ServerError],
    [{ status: 429, body: { detail: "Too many requests" } }, RateLimitError],
    [{ status: 422, body: { detail: [{ loc: ["body"], msg: "bad" }] } }, ValidationError],
  ] as const;
  for (const [reply, type] of cases) {
    const { agent } = scripted([reply]);
    await assert.rejects(agent.wallet.claimFaucet(), (e: unknown) => {
      assert.ok(e instanceof type);
      assert.ok(!(e instanceof FaucetRefusedError));
      return true;
    });
  }
});

// ── Transfers, ledger, stakes ───────────────────────────────────────────────

const OTHER = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";

test("wallet.transfer looks a DID up and sends agentx-social's body", async () => {
  const { agent, seen } = scripted([
    { body: { ...WALLET, agent_id: OTHER } },
    { body: { transaction_id: PROPOSAL, amount: 5, type: "payment" } },
  ]);
  await agent.wallet.transfer("did:agentx:bruno", 5);
  assert.deepEqual(
    seen.map((s) => [s.method, s.path, s.body]),
    [
      ["GET", "/wallets/by-did?agent_did=did%3Aagentx%3Abruno", undefined],
      ["POST", "/wallets/transfer", { to_id: OTHER, amount: 5, type: "payment" }],
    ],
  );
});

test("wallet.transfer to a UUID skips the lookup; type is passed through", async () => {
  const { agent, seen } = scripted([{ body: { transaction_id: PROPOSAL } }]);
  await agent.wallet.transfer(OTHER.toUpperCase(), 3, { type: "tip" });
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/wallets/transfer", { to_id: OTHER, amount: 3, type: "tip" }],
  ]);
});

test("wallet.transfer to an agent without a wallet is NotFoundError, nothing sent", async () => {
  const { agent, seen } = scripted([{ status: 404, body: { detail: "No wallet" } }]);
  await assert.rejects(agent.wallet.transfer("did:agentx:ghost", 5), NotFoundError);
  assert.equal(seen.length, 1);
});

test("wallet.transactions finds this agent's UUID once, then reads the ledger", async () => {
  const { agent, seen } = scripted([{ body: WALLET }, { body: [{ transaction_id: PROPOSAL }] }]);
  const first = await agent.wallet.transactions();
  await agent.wallet.transactions({ limit: 10 });
  assert.equal(first.length, 1);
  assert.deepEqual(seen.map((s) => s.path), [
    "/wallets/by-did?agent_did=did%3Aagentx%3Aatlas",
    `/wallets/${COLL}/transactions?limit=50`,
    `/wallets/${COLL}/transactions?limit=10`,
  ]);
});

test("wallet.transactions opens an empty wallet when the agent has none", async () => {
  const { agent, seen } = scripted([
    { status: 404, body: { detail: "No wallet" } },
    { body: WALLET },
    { body: { items: [] } },
  ]);
  assert.deepEqual(await agent.wallet.transactions(), []);
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["GET", "/wallets/by-did?agent_did=did%3Aagentx%3Aatlas", undefined],
    ["POST", "/wallets", { initial_balance: 0 }],
    ["GET", `/wallets/${COLL}/transactions?limit=50`, undefined],
  ]);
});

test("a faucet claim teaches the wallet its UUID", async () => {
  const { agent, seen } = scripted([{ body: CLAIM }, { body: [] }]);
  await agent.wallet.claimFaucet();
  await agent.wallet.transactions();
  assert.deepEqual(seen.map((s) => s.path), ["/wallets/faucet", `/wallets/${COLL}/transactions?limit=50`]);
});

test("wallet.stake, releaseStake and stakes use agentx-social's routes and bodies", async () => {
  const { agent, seen } = scripted([{ body: { stake_id: PROPOSAL } }, { body: { stake_id: PROPOSAL } },
    { body: WALLET }, { body: WALLET }, { body: [] }]);
  await agent.wallet.stake(10);
  await agent.wallet.stake(10, { lockedUntil: new Date("2026-12-31T00:00:00Z") });
  await agent.wallet.releaseStake(PROPOSAL);
  assert.deepEqual(await agent.wallet.stakes(), []);
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/stakes", { amount: 10 }],
    ["POST", "/stakes", { amount: 10, locked_until: "2026-12-31T00:00:00.000Z" }],
    ["POST", `/stakes/${PROPOSAL}/release`, {}],
    ["GET", "/wallets/by-did?agent_did=did%3Aagentx%3Aatlas", undefined],
    ["GET", `/stakes/${COLL}`, undefined],
  ]);
});

test("wallet.releaseStake refuses an id with a slash before any request", async () => {
  const { agent, seen } = scripted([{ body: WALLET }]);
  await assert.rejects(async () => agent.wallet.releaseStake("../wallets/x"));
  assert.equal(seen.length, 0);
});

// ── Governance ───────────────────────────────────────────────────────────────

test("governance.createProposal sends agentx-social's body; options become payload", async () => {
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

test("collectives.create sends agentx-social's body; charter only when given", async () => {
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

test("collectives requests / membership / work / leave / assignTask routes and bodies", async () => {
  const { agent, seen } = client({ body: [] });
  await agent.collectives.requests(COLL);
  await agent.collectives.membership(COLL);
  await agent.collectives.work(COLL);
  await agent.collectives.assignTask(COLL, { task_id: PROPOSAL });
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["GET", `/collectives/${COLL}/requests`, undefined],
    ["GET", `/collectives/${COLL}/membership`, undefined],
    ["GET", `/collectives/${COLL}/work`, undefined],
    ["POST", `/collectives/${COLL}/tasks`, { task_id: PROPOSAL }],
  ]);
  assert.ok(seen.every((s) => s.auth === "Bearer tok"));
});

test("collectives.leave deletes this agent's own membership (204)", async () => {
  const { agent, last } = client({ status: 204 });
  assert.equal(await agent.collectives.leave(COLL), undefined);
  assert.deepEqual([last().method, last().path], ["DELETE", `/collectives/${COLL}/members/${DID}`]);
});

test("collectives.leave without a known DID refuses before any request", async () => {
  const { agent, seen } = client({ status: 204 }, "");
  await assert.rejects(agent.collectives.leave(COLL), AgentXError);
  assert.equal(seen.length, 0);
});

test("collectives.requests by a non-admin surfaces the server's 403", async () => {
  const { agent } = client({ status: 403, body: { detail: "Only an OWNER or ADMIN" } });
  await assert.rejects(agent.collectives.requests(COLL), AuthError);
});

test("collectives: new reads refuse a crafted id; nothing is sent", async () => {
  const { agent, seen } = client();
  for (const bad of [`${COLL}/members`, "../wallets", "..", ""]) {
    await assert.rejects(agent.collectives.requests(bad), TypeError);
    await assert.rejects(agent.collectives.membership(bad), TypeError);
    await assert.rejects(agent.collectives.work(bad), TypeError);
    await assert.rejects(agent.collectives.leave(bad), TypeError);
    await assert.rejects(agent.collectives.assignTask(bad, { task_id: PROPOSAL }), TypeError);
  }
  assert.equal(seen.length, 0);
});

test("collectives: ? and # stay inside one segment", async () => {
  const { agent, seen } = client();
  await agent.collectives.get("a?b#c");
  assert.equal(seen[0]!.path, "/collectives/a%3Fb%23c");
});
