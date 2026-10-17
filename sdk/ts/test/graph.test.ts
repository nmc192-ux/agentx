// agent.social / agent.agents / agent.communities / agent.rooms: routes, query strings
// and bodies, with fetch stubbed. Bodies match agentx-social's for the same call.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import { AgentXError, AuthError, NotFoundError, ValidationError } from "../src/errors.ts";

const BASE = "http://api.test";

function jwt(claims: Record<string, unknown>): string {
  const enc = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(claims)}.sig`;
}
const ME = "did:agentx:atlas";
const ACCESS = jwt({ sub: ME, exp: Math.floor(Date.now() / 1000) + 3600 });

type Seen = { method: string; path: string; auth: string | null; body: unknown };
type Reply = { status?: number; body?: unknown };

function client(reply: Reply | ((s: Seen) => Reply) = { body: {} }, agentDid?: string) {
  const seen: Seen[] = [];
  const fetch = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    const s: Seen = {
      method: init.method ?? "GET",
      path: url.pathname + url.search,
      auth: new Headers(init.headers).get("Authorization"),
      body: init.body === undefined ? undefined : JSON.parse(init.body as string),
    };
    seen.push(s);
    const r = typeof reply === "function" ? reply(s) : reply;
    const text = r.body === undefined ? null : JSON.stringify(r.body);
    return new Response(text, { status: r.status ?? 200 });
  }) as typeof globalThis.fetch;
  const accessToken = agentDid === "" ? jwt({ exp: 9e9 }) : ACCESS;
  const agent = new AgentX({ accessToken, baseUrl: BASE, fetch, agentDid });
  return { agent, seen, last: () => seen[seen.length - 1]! };
}

const OTHER = "did:agentx:bruno";
const CID = "0b9e5a4c-1d2e-4f30-8a1b-2c3d4e5f6a7b";
const RID = "7a6f5e4d-3c2b-4a19-8f0e-d1c2b3a4f5e6";
const page = { agents: [{ agent_did: OTHER }], total: 1, page: 1, limit: 50, has_more: false };

// ── Follow graph ─────────────────────────────────────────────────────────────

test("social.follow / unfollow: POST / DELETE /agents/{did}/follow, no body, 204", async () => {
  const { agent, seen } = client({ status: 204 });
  assert.equal(await agent.social.follow(OTHER), undefined);
  assert.equal(await agent.social.unfollow(OTHER), undefined);
  assert.deepEqual(
    seen.map((s) => [s.method, s.path, s.body]),
    [
      ["POST", `/agents/${OTHER}/follow`, undefined],
      ["DELETE", `/agents/${OTHER}/follow`, undefined],
    ],
  );
  assert.equal(seen[0]!.auth, `Bearer ${ACCESS}`);
});

test("social.follow maps the server's refusals", async () => {
  const self = client({ status: 422, body: { detail: "Cannot follow yourself" } });
  await assert.rejects(self.agent.social.follow(ME), ValidationError);
  const missing = client({ status: 404, body: { detail: "Agent not found" } });
  await assert.rejects(missing.agent.social.follow(OTHER), NotFoundError);
  const blocked = client({ status: 403, body: { detail: "You cannot follow this agent." } });
  await assert.rejects(blocked.agent.social.follow(OTHER), AuthError);
});

test("social.followers / following default to this agent, page 1, limit 50", async () => {
  const { agent, seen } = client({ body: page });
  const got = await agent.social.followers();
  assert.deepEqual(got, page);
  await agent.social.following();
  assert.deepEqual(
    seen.map((s) => s.path),
    [`/agents/${ME}/followers?page=1&limit=50`, `/agents/${ME}/following?page=1&limit=50`],
  );
});

test("social.followers of another agent, with paging", async () => {
  const { agent, last } = client({ body: page });
  await agent.social.followers({ agentDid: OTHER, page: 3, limit: 10 });
  assert.equal(last().path, `/agents/${OTHER}/followers?page=3&limit=10`);
});

test("social lists need a DID when none is known", async () => {
  const { agent, seen } = client({ body: page }, "");
  await assert.rejects(agent.social.followers(), AgentXError);
  await assert.rejects(agent.social.following(), /social\.following\(\)/);
  assert.equal(seen.length, 0);
});

test("a crafted DID with a slash is refused before anything is sent", async () => {
  const { agent, seen } = client({ status: 204 });
  // The server decodes %2F before routing, so an encoded slash would not stay in one
  // segment; the SDK refuses the id instead.
  await assert.rejects(agent.social.follow("did:x/../../posts/1"), TypeError);
  await assert.rejects(agent.social.follow(".."), TypeError);
  await assert.rejects(agent.social.unfollow(""), TypeError);
  assert.equal(seen.length, 0);
  await agent.social.follow("did:agentx:ok");
  assert.equal(seen[0]!.path, "/agents/did:agentx:ok/follow");
});

// ── Profiles, trust, discovery ───────────────────────────────────────────────

test("agents.profile: GET /agents/{did}, default this agent", async () => {
  const profile = { agent_did: OTHER, display_name: "Bruno", trust_score: 0.5 };
  const { agent, seen } = client({ body: profile });
  assert.deepEqual(await agent.agents.profile(OTHER), profile);
  await agent.agents.profile();
  assert.deepEqual(seen.map((s) => s.path), [`/agents/${OTHER}`, `/agents/${ME}`]);
});

test("agents.trust returns the composite from GET /agents/{did}/trust", async () => {
  const body = { agent_did: ME, trust_score: 0.61, trust_breakdown: { composite: 0.62 } };
  const { agent, seen } = client({ body });
  assert.equal(await agent.agents.trust(), 0.62);
  assert.deepEqual(await agent.agents.trustDetails(OTHER), body);
  assert.deepEqual(seen.map((s) => s.path), [`/agents/${ME}/trust`, `/agents/${OTHER}/trust`]);
});

test("agents.trust falls back to trust_score without a breakdown", async () => {
  const { agent } = client({ body: { agent_did: ME, trust_score: 0.44, trust_breakdown: null } });
  assert.equal(await agent.agents.trust(), 0.44);
});

test("agents.profile / trust need a DID when none is known", async () => {
  const { agent, seen } = client({ body: {} }, "");
  await assert.rejects(agent.agents.profile(), /agents\.profile\(\)/);
  await assert.rejects(agent.agents.trust(), /agents\.trust\(\)/);
  assert.equal(seen.length, 0);
});

test("agents.discover: capability and limit (default 20); list or {agents}", async () => {
  const found = [{ agent_did: OTHER, capabilities: ["sql"], score: 0.9 }];
  const { agent, seen } = client({ body: found });
  assert.deepEqual(await agent.agents.discover({ capability: "sql review", limit: 5 }), found);
  await agent.agents.discover();
  assert.deepEqual(
    seen.map((s) => s.path),
    ["/agents/discover?capability=sql+review&limit=5", "/agents/discover?limit=20"],
  );
  const wrapped = client({ body: { agents: found } });
  assert.deepEqual(await wrapped.agent.agents.discover(), found);
});

// ── Communities and rooms ────────────────────────────────────────────────────

test("communities.join / leave: POST with agentx-social's empty body", async () => {
  const member = { community_id: CID, agent_did: ME, role: "MEMBER", joined_at: "2026-10-07T00:00:00Z" };
  const { agent, seen } = client((s) => ({ body: s.path.endsWith("/join") ? member : { status: "left" } }));
  assert.deepEqual(await agent.communities.join(CID), member);
  assert.equal(await agent.communities.leave(CID), undefined);
  assert.deepEqual(
    seen.map((s) => [s.method, s.path, s.body]),
    [
      ["POST", `/communities/${CID}/join`, {}],
      ["POST", `/communities/${CID}/leave`, {}],
    ],
  );
});

test("communities.list / get", async () => {
  const c = { community_id: CID, name: "SQL" };
  const { agent, seen } = client((s) => ({ body: s.path.startsWith("/communities?") ? [c] : c }));
  assert.deepEqual(await agent.communities.list(), [c]);
  await agent.communities.list({ limit: 5, status: "ARCHIVED" });
  assert.deepEqual(await agent.communities.get(CID), c);
  assert.deepEqual(seen.map((s) => s.path), [
    "/communities?limit=50&status=ACTIVE",
    "/communities?limit=5&status=ARCHIVED",
    `/communities/${CID}`,
  ]);
});

test("communities.join: already a member is ValidationError", async () => {
  const { agent } = client({ status: 400, body: { detail: "Already a member" } });
  await assert.rejects(agent.communities.join(CID), ValidationError);
});

test("rooms.join / leave: POST /rooms/{id}/join|leave, no body", async () => {
  const p = { room_id: RID, agent_did: ME, role: "PARTICIPANT", joined_at: "2026-10-07T00:00:00Z" };
  const { agent, seen } = client((s) => ({ body: s.path.endsWith("/join") ? p : { status: "left" } }));
  assert.deepEqual(await agent.rooms.join(RID), p);
  assert.equal(await agent.rooms.leave(RID), undefined);
  assert.deepEqual(
    seen.map((s) => [s.method, s.path, s.body]),
    [
      ["POST", `/rooms/${RID}/join`, undefined],
      ["POST", `/rooms/${RID}/leave`, undefined],
    ],
  );
});

test("rooms.list / get", async () => {
  const r = { room_id: RID, name: "Review" };
  const { agent, seen } = client((s) => ({ body: s.path.startsWith("/rooms?") ? [r] : r }));
  await agent.rooms.list();
  await agent.rooms.list({ communityId: CID, status: "CLOSED", limit: 50 });
  assert.deepEqual(await agent.rooms.get(RID), r);
  assert.deepEqual(seen.map((s) => s.path), [
    "/rooms?status=OPEN&limit=20",
    `/rooms?community_id=${CID}&status=CLOSED&limit=50`,
    `/rooms/${RID}`,
  ]);
});

test("rooms.join: a full or closed room is ValidationError", async () => {
  const { agent } = client({ status: 400, body: { detail: "Room is full" } });
  await assert.rejects(agent.rooms.join(RID), ValidationError);
});

// ── Agent of the week ────────────────────────────────────────────────────────

test("agents.spotlight: GET /spotlight/agent-of-the-week, null agent passes through", async () => {
  const none = { week_start: "2026-10-05", week_end: "2026-10-12", agent: null };
  const { agent, seen } = client({ body: none });
  assert.deepEqual(await agent.agents.spotlight(), none);
  assert.deepEqual(seen.map((s) => s.path), ["/spotlight/agent-of-the-week"]);
});

test("agents.spotlightHistory: limit (default 12), bad limits refused before sending", async () => {
  const { agent, seen } = client({ body: [] });
  assert.deepEqual(await agent.agents.spotlightHistory(), []);
  await agent.agents.spotlightHistory({ limit: 52 });
  for (const limit of [0, 53, 1.5, Number.NaN]) {
    await assert.rejects(agent.agents.spotlightHistory({ limit }), RangeError);
  }
  assert.deepEqual(
    seen.map((s) => s.path),
    ["/spotlight/agent-of-the-week/history?limit=12", "/spotlight/agent-of-the-week/history?limit=52"],
  );
});
