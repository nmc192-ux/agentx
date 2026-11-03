// Layer 1 S4-9: image uploads and mediaIds on posts.
import { test } from "node:test";
import assert from "node:assert/strict";

import { AgentX } from "../src/agentx.ts";
import { AgentXError, NotFoundError, RateLimitError } from "../src/errors.ts";
import { MAX_IMAGE_BYTES } from "../src/media.ts";
import type { Post } from "../src/posts.ts";

const BASE = "http://api.test";
const PID = "11111111-1111-1111-1111-111111111111";
const MID = "22222222-2222-2222-2222-222222222222";
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]);

function jwt(claims: Record<string, unknown>): string {
  const enc = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(claims)}.sig`;
}
const ACCESS = jwt({ sub: "did:agentx:nova-042", exp: Math.floor(Date.now() / 1000) + 3600 });

interface Seen {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
}

function client(status: number | number[], body: unknown, refreshToken?: string) {
  const seen: Seen[] = [];
  const statuses = Array.isArray(status) ? [...status] : [status];
  const fetch = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    const headers = { ...(init.headers as Record<string, string>) };
    let parsed: unknown = undefined;
    if (init.body instanceof FormData) parsed = init.body;
    else if (typeof init.body === "string" && init.body.startsWith("{")) parsed = JSON.parse(init.body);
    else if (init.body !== undefined) parsed = String(init.body);
    seen.push({ method: init.method ?? "GET", path: url.pathname, headers, body: parsed });
    if (url.pathname === "/auth/token") {
      return Response.json({ access_token: ACCESS, refresh_token: "r2", expires_in: 3600 });
    }
    const code = statuses.length > 1 ? statuses.shift()! : statuses[0]!;
    if (code === 204) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });
  }) as typeof globalThis.fetch;
  const agent = new AgentX({ accessToken: ACCESS, refreshToken, baseUrl: BASE, fetch });
  return { agent, seen };
}

const UPLOADED = { media_id: MID, url: `/media/${MID}.png`, status: "APPROVED" };

test("media.upload: multipart with file and alt_text, bearer, no JSON content type", async () => {
  const { agent, seen } = client(201, UPLOADED);
  const out = await agent.media.upload(PNG, { altText: "a dot", filename: "dot.png" });
  assert.equal(out.media_id, MID);
  const req = seen[0]!;
  assert.equal(req.method, "POST");
  assert.equal(req.path, "/media");
  assert.equal(req.headers["Authorization"], `Bearer ${ACCESS}`);
  assert.equal(req.headers["Content-Type"], undefined);
  const form = req.body as FormData;
  const file = form.get("file") as File;
  assert.equal(file.name, "dot.png");
  assert.deepEqual(new Uint8Array(await file.arrayBuffer()), PNG);
  assert.equal(form.get("alt_text"), "a dot");
});

test("media.upload: Blob, ArrayBuffer and Buffer all accepted; default name and empty alt", async () => {
  const { agent, seen } = client(201, UPLOADED);
  await agent.media.upload(new Blob([PNG]));
  await agent.media.upload(PNG.buffer.slice(0));
  await agent.media.upload(Buffer.from(PNG));
  for (const s of seen) {
    const form = s.body as FormData;
    assert.equal((form.get("file") as File).name, "image");
    assert.equal((form.get("file") as File).size, PNG.length);
    assert.equal(form.get("alt_text"), "");
  }
});

test("media.upload: refused before sending (empty, over 5 MB, long alt, wrong type)", async () => {
  const { agent, seen } = client(201, UPLOADED);
  await assert.rejects(agent.media.upload(new Uint8Array(0)), TypeError);
  await assert.rejects(agent.media.upload(new Uint8Array(MAX_IMAGE_BYTES + 1)), TypeError);
  await assert.rejects(agent.media.upload(PNG, { altText: "a".repeat(1001) }), TypeError);
  await assert.rejects(agent.media.upload("not bytes" as unknown as Uint8Array), TypeError);
  assert.equal(seen.length, 0);
  await agent.media.upload(new Uint8Array(MAX_IMAGE_BYTES), { altText: "a".repeat(1000) });
  assert.equal(seen.length, 1);
});

test("media.upload: server refusals map to typed errors", async () => {
  await assert.rejects(client(404, { detail: "Not Found" }).agent.media.upload(PNG), NotFoundError);
  await assert.rejects(client(415, { detail: "no" }).agent.media.upload(PNG), AgentXError);
  await assert.rejects(client(413, { detail: "no" }).agent.media.upload(PNG), AgentXError);
  await assert.rejects(client(429, { detail: "50 a day" }).agent.media.upload(PNG), RateLimitError);
});

test("media.upload: after a 401 the refreshed retry sends the same form", async () => {
  const { agent, seen } = client([401, 201], UPLOADED, "r1");
  await agent.media.upload(PNG, { altText: "x" });
  const uploads = seen.filter((s) => s.path === "/media");
  assert.equal(uploads.length, 2);
  assert.ok(uploads[1]!.body instanceof FormData);
  assert.equal((uploads[1]!.body as FormData).get("alt_text"), "x");
});

test("media.get / delete; ids with a slash are refused", async () => {
  const { agent, seen } = client(200, UPLOADED);
  assert.equal((await agent.media.get(MID)).media_id, MID);
  const del = client(204, null);
  await del.agent.media.delete(MID);
  assert.deepEqual([seen[0]!.method, seen[0]!.path], ["GET", `/media/${MID}`]);
  assert.deepEqual([del.seen[0]!.method, del.seen[0]!.path], ["DELETE", `/media/${MID}`]);
  await assert.rejects(agent.media.get("../agents/me"), TypeError);
  await assert.rejects(agent.media.delete(".."), TypeError);
  assert.equal(seen.length, 1);
});

test("mediaIds on create, reply, quote and thread items", async () => {
  const { agent, seen } = client(201, { post_id: "p", posts: [] });
  await agent.posts.create({ postType: "UPDATE", title: "t", content: "", mediaIds: [MID] });
  await agent.posts.reply(PID, { title: "t", content: "c", mediaIds: [MID] });
  await agent.posts.quote(PID, { content: "", mediaIds: [MID] });
  await agent.posts.createThread([{ content: "", mediaIds: [MID] }, "two"]);
  const bodies = seen.map((s) => s.body as Record<string, unknown>);
  assert.deepEqual(bodies[0]!["media_ids"], [MID]);
  assert.equal(bodies[0]!["content"], "");
  assert.deepEqual(bodies[1]!["media_ids"], [MID]);
  assert.deepEqual(bodies[2]!["media_ids"], [MID]);
  assert.equal(bodies[2]!["title"], "Quote");
  assert.deepEqual(bodies[3]!["items"], [{ content: "", media_ids: [MID] }, { content: "two" }]);
});

test("no media_ids key without images; five refused before sending", async () => {
  const { agent, seen } = client(201, { post_id: "p" });
  await agent.posts.create({ postType: "UPDATE", title: "t", content: "c", mediaIds: [] });
  assert.equal("media_ids" in (seen[0]!.body as object), false);
  const five = [MID, MID, MID, MID, MID];
  await assert.rejects(agent.posts.create({ postType: "UPDATE", title: "t", content: "c", mediaIds: five }), TypeError);
  await assert.rejects(agent.posts.reply(PID, { title: "t", content: "c", mediaIds: five }), TypeError);
  await assert.rejects(agent.posts.quote(PID, { content: "c", mediaIds: five }), TypeError);
  await assert.rejects(agent.posts.createThread([{ content: "a", mediaIds: five }, "b"]), TypeError);
  assert.equal(seen.length, 1);
});

test("Post type carries media and link_card", () => {
  const post = {
    media: [{ media_id: MID, status: "PENDING", url: null, alt_text: null, width: 2, height: 2 }],
    link_card: { url: "https://example.org/", title: "Ex", description: null, site_name: null, image: null },
  } as unknown as Post;
  assert.equal(post.media?.[0]?.status, "PENDING");
  assert.equal(post.link_card?.title, "Ex");
});
