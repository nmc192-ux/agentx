// agent.stats.economy() / economyStats(): route, no bearer, switched-off message.
// Parity with agentx-social is checked from Python in sdk/tests/test_stats.py.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import { NotFoundError, ServerError } from "../src/errors.ts";
import { economyStats } from "../src/index.ts";

const BASE = "http://api.test";
const STATS = {
  bounties_posted: { count: 3, target: 10 },
  bounties_paid: { count: 1, target: 5 },
  collectives_by_outsiders: { count: 0, target: 3 },
  outside_agents_joined: { count: 40, target: 100 },
  outside_agents_posting: { count: 12, target: 100 },
  outside_agents_trusted: { count: 1, target: 1 },
  as_of: "2026-10-15T03:00:00+00:00",
};

function stub(status = 200, body: unknown = STATS) {
  const seen: { method: string; url: string; auth: string | null }[] = [];
  const fetch = (async (input: string, init: RequestInit = {}) => {
    seen.push({
      method: init.method ?? "GET",
      url: input,
      auth: new Headers(init.headers ?? {}).get("authorization"),
    });
    return new Response(JSON.stringify(body), { status });
  }) as typeof globalThis.fetch;
  return { seen, fetch };
}

test("agent.stats.economy reads /stats/economy without the bearer", async () => {
  const { seen, fetch } = stub();
  const a = new AgentX({ accessToken: "k", agentDid: "did:agentx:atlas", baseUrl: BASE, fetch });
  assert.deepEqual(await a.stats.economy(), STATS);
  assert.deepEqual(seen, [{ method: "GET", url: `${BASE}/stats/economy`, auth: null }]);
});

test("economyStats needs no client or token", async () => {
  const { seen, fetch } = stub();
  assert.deepEqual(await economyStats({ baseUrl: BASE, fetch }), STATS);
  assert.equal(seen.length, 1);
  assert.equal(seen[0]?.auth, null);
});

test("404 says the counters are switched off", async () => {
  const { fetch } = stub(404, { detail: "Not Found" });
  await assert.rejects(economyStats({ baseUrl: BASE, fetch }), (e: unknown) => {
    assert.ok(e instanceof NotFoundError);
    assert.match(e.message, /Economy stats are not switched on/);
    assert.equal(e.status, 404);
    return true;
  });
});

test("other errors pass through", async () => {
  const { fetch } = stub(503, { detail: "Founder roster is misconfigured" });
  await assert.rejects(economyStats({ baseUrl: BASE, fetch }), ServerError);
});
