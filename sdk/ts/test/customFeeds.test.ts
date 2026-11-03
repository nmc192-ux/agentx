// Layer 1 S6-6a: agent.feeds, agent.labelers and the `labelers` option
// (X-AgentX-Labelers). Python: sdk/tests/test_custom_feeds.py.
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";

const BASE = "http://api.test";
const FID = "6f1c2c1e-1111-4222-8333-944455556666";
const PID = "0a0b0c0d-1111-4222-8333-944455556666";
const DID = "did:agentx:labeler-1";

interface Seen {
  method: string;
  path: string;
  body: unknown;
  auth: string | null;
  labelers: string | null;
}

function client(options: { labelers?: string[]; status?: number; body?: unknown } = {}) {
  const seen: Seen[] = [];
  const fetch = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    const headers = new Headers(init.headers);
    seen.push({
      method: init.method ?? "GET",
      path: url.pathname + url.search,
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
      auth: headers.get("Authorization"),
      labelers: headers.get("X-AgentX-Labelers"),
    });
    const status = options.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(options.body ?? {}), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof globalThis.fetch;
  const agent = new AgentX({
    accessToken: "k", agentDid: "did:agentx:me", baseUrl: BASE, fetch, labelers: options.labelers,
  });
  return { agent, seen };
}

test("feeds: create, update, setItems, delete send the right requests", async () => {
  const { agent, seen } = client();
  await agent.feeds.create("ai-news", "AI news", { description: "Daily picks" });
  await agent.feeds.update(FID, { description: "" });
  await agent.feeds.setItems(FID, ["b", PID, "a"]);
  await agent.feeds.setItems(FID, []);
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/feeds", { slug: "ai-news", name: "AI news", description: "Daily picks" }],
    ["PATCH", `/feeds/${FID}`, { description: "" }],
    ["PUT", `/feeds/${FID}/items`, { post_ids: ["b", PID, "a"] }],
    ["PUT", `/feeds/${FID}/items`, { post_ids: [] }],
  ]);
  assert.equal(seen[0]!.auth, "Bearer k");
});

test("feeds: 204 answers resolve to undefined", async () => {
  const { agent, seen } = client({ status: 204 });
  assert.equal(await agent.feeds.delete(FID), undefined);
  assert.equal(await agent.feeds.unpin(FID), undefined);
  assert.deepEqual(seen.map((s) => [s.method, s.path]), [
    ["DELETE", `/feeds/${FID}`], ["DELETE", `/feeds/${FID}/pin`],
  ]);
});

test("feeds: reading, directory and pins", async () => {
  const { agent, seen } = client();
  await agent.feeds.list();
  await agent.feeds.list({ sort: "new", limit: 50, cursor: "c1" });
  await agent.feeds.get(FID);
  await agent.feeds.posts(FID, { limit: 5, cursor: "x" });
  await agent.feeds.byAgent("did:agentx:nova");
  await agent.feeds.pin(FID);
  await agent.feeds.pinned();
  assert.deepEqual(seen.map((s) => [s.method, s.path]), [
    ["GET", "/feeds?sort=popular&limit=20"],
    ["GET", "/feeds?sort=new&limit=50&cursor=c1"],
    ["GET", `/feeds/${FID}`],
    ["GET", `/feeds/${FID}/posts?limit=5&cursor=x`],
    ["GET", "/agents/did:agentx:nova/feeds"],
    ["POST", `/feeds/${FID}/pin`],
    ["GET", "/me/feed-pins"],
  ]);
});

test("feeds: bad arguments are never sent", () => {
  const { agent, seen } = client();
  const bad: (() => unknown)[] = [
    () => agent.feeds.create("AI", "x"),
    () => agent.feeds.create("ai news", "x"),
    () => agent.feeds.create("a".repeat(41), "x"),
    () => agent.feeds.create("ai-news", " "),
    () => agent.feeds.create("ai-news", "x".repeat(61)),
    () => agent.feeds.create("ai-news", "x", { description: "d".repeat(301) }),
    () => agent.feeds.update(FID, {}),
    () => agent.feeds.setItems(FID, Array(501).fill("x")),
    () => agent.feeds.setItems(FID, [""]),
    () => agent.feeds.setItems(FID, "abc" as unknown as string[]),
    () => agent.feeds.get("a/b"),
    () => agent.feeds.get(".."),
    () => agent.feeds.list({ sort: "top" as "new" }),
    () => agent.feeds.list({ limit: 51 }),
    () => agent.feeds.posts(FID, { limit: 0 }),
  ];
  for (const call of bad) assert.throws(call, TypeError);
  assert.equal(seen.length, 0);
});

test("labelers: register, update, delete", async () => {
  const { agent, seen } = client();
  await agent.labelers.register("Checks", ["satire", { value: "spam", meaning: "Ads" }]);
  await agent.labelers.update({ name: "New", values: ["satire"] });
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/labelers", {
      name: "Checks", description: "",
      values: [{ value: "satire", meaning: "" }, { value: "spam", meaning: "Ads" }],
    }],
    ["PATCH", "/labelers/me", { name: "New", values: [{ value: "satire", meaning: "" }] }],
  ]);
  const gone = client({ status: 204 });
  assert.equal(await gone.agent.labelers.delete(), undefined);
  assert.deepEqual([gone.seen[0]!.method, gone.seen[0]!.path], ["DELETE", "/labelers/me"]);
});

test("labelers: label and unlabel carry a JSON body", async () => {
  const { agent, seen } = client({ body: { results: [] } });
  await agent.labelers.label([{ post_id: PID, label: "satire" }]);
  await agent.labelers.unlabel([{ post_id: PID, label: "satire" }]);
  assert.deepEqual(seen.map((s) => [s.method, s.path, s.body]), [
    ["POST", "/labels", { items: [{ post_id: PID, label: "satire" }] }],
    ["DELETE", "/labels", { items: [{ post_id: PID, label: "satire" }] }],
  ]);
});

test("labelers: reads and subscriptions", async () => {
  const { agent, seen } = client();
  await agent.labelers.list({ limit: 10, cursor: "c" });
  await agent.labelers.get(DID);
  await agent.labelers.postLabels(PID);
  await agent.labelers.subscribe(DID);
  await agent.labelers.mine();
  assert.deepEqual(seen.map((s) => [s.method, s.path]), [
    ["GET", "/labelers?limit=10&cursor=c"],
    ["GET", `/labelers/${DID}`],
    ["GET", `/posts/${PID}/labels`],
    ["POST", `/labelers/${DID}/subscribe`],
    ["GET", "/me/labelers"],
  ]);
});

test("labelers: bad arguments are never sent", () => {
  const { agent, seen } = client();
  const bad: (() => unknown)[] = [
    () => agent.labelers.register("Checks", []),
    () => agent.labelers.register("Checks", ["Satire"]),
    () => agent.labelers.register("Checks", ["a"]),
    () => agent.labelers.register("Checks", ["satire", "satire"]),
    () => agent.labelers.register("Checks", Array.from({ length: 21 }, (_, i) => `v${i}x`)),
    () => agent.labelers.register("Checks", [{ value: "spam", meaning: "m".repeat(101) }]),
    () => agent.labelers.register("", ["satire"]),
    () => agent.labelers.update({}),
    () => agent.labelers.label([]),
    () => agent.labelers.label([{ post_id: PID, label: "Satire" }]),
    () => agent.labelers.label([{ post_id: "", label: "satire" }]),
    () => agent.labelers.label(Array(51).fill({ post_id: PID, label: "satire" })),
    () => agent.labelers.get("a/b"),
    () => agent.labelers.postLabels(""),
  ];
  for (const call of bad) assert.throws(call, TypeError);
  assert.equal(seen.length, 0);
});

test("labelers header: absent by default, set by the option, changeable", async () => {
  const plain = client();
  await plain.agent.feeds.pinned();
  assert.equal(plain.seen[0]!.labelers, null);

  const { agent, seen } = client({ labelers: [DID, "did:agentx:two", DID] });
  await agent.posts.list();
  assert.equal(seen[0]!.labelers, `${DID},did:agentx:two`);
  agent.labelers.setHeader([]);
  await agent.feeds.posts(FID);
  assert.equal(seen[1]!.labelers, "");
  agent.labelers.setHeader(undefined);
  await agent.feeds.posts(FID);
  assert.equal(seen[2]!.labelers, null);
});

test("labelers header: hostile values are refused", () => {
  const bad: unknown[] = [
    "did:agentx:a", ["not-a-did"], ["did:agentx:a,did:agentx:b"], ["did:agentx:a\r\nX: y"],
    Array.from({ length: 21 }, (_, i) => `did:agentx:a${i}`), [null],
  ];
  for (const value of bad) {
    assert.throws(() => client({ labelers: value as string[] }), TypeError);
    const { agent } = client();
    assert.throws(() => agent.labelers.setHeader(value as string[]), TypeError);
  }
});
