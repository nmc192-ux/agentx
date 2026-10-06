// Every id interpolated into a request path goes through seg() (sprint 15 security
// review). A source scan over src/*.ts fails if a template literal path interpolates a
// raw value, so a new method cannot quietly reintroduce the hole that
// `posts.get("abc/replies")` -> GET /posts/abc/replies would open.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { AgentX } from "../src/agentx.ts";
import { seg } from "../src/http.ts";

const SRC = new URL("../src/", import.meta.url).pathname;

test("no request path interpolates an id without seg()", () => {
  const offenders: string[] = [];
  for (const file of readdirSync(SRC).filter((f) => f.endsWith(".ts")).sort()) {
    const lines = readFileSync(join(SRC, file), "utf8").split("\n");
    lines.forEach((line, i) => {
      // Template literal starting with "/" and a literal first segment: `/posts/${x}`.
      // (`/${path}` in http.ts joins a whole path, not an id, and does not match.)
      for (const literal of line.matchAll(/`(\/[A-Za-z][^`]*)`/g)) {
        for (const expr of literal[1].matchAll(/\$\{([^{}]+)\}/g)) {
          if (!expr[1].trim().startsWith("seg(")) offenders.push(`${file}:${i + 1}: \${${expr[1]}}`);
        }
      }
    });
  }
  assert.deepEqual(offenders, [], "unwrapped path ids:\n" + offenders.join("\n"));
});

test("seg() defeats the URL parser's dot-segment folding", () => {
  // The WHATWG parser treats "%2e%2e" like "..": `/posts/%2e%2e/x` is `/x`. seg() encodes
  // the "%", so what the server sees is the literal text, never a dot segment.
  for (const sneaky of ["%2e%2e", ".%2e", "%2e.", "%2E%2E"]) {
    const encoded = seg(sneaky);
    const url = new URL(`http://api.test/posts/${encoded}/replies`);
    assert.equal(url.pathname, `/posts/${encoded}/replies`, sneaky);
    assert.ok(!url.pathname.includes("/replies/") && url.pathname.startsWith("/posts/"));
  }
  // A full-width solidus is not a slash to the server; it is encoded, not refused.
  assert.equal(seg("a／b"), "a%EF%BC%8Fb");
  // Non-strings are refused, not coerced.
  for (const notAString of [undefined, null, 42, {}, ["abc"]]) {
    assert.throws(() => seg(notAString as unknown as string), TypeError);
  }
});

test("the new client sends a percent-encoded dot segment as literal text", async () => {
  const seen: string[] = [];
  const fetch = (async (url: string) => {
    seen.push(new URL(url).pathname);
    return new Response("{}", { status: 200 });
  }) as typeof globalThis.fetch;
  const enc = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const accessToken = `${enc({ alg: "HS256", typ: "JWT" })}.${enc({ sub: "did:agentx:me", exp: 9e9 })}.sig`;
  const agent = new AgentX({ accessToken, baseUrl: "http://api.test", fetch });
  await agent.posts.get("%2e%2e");
  assert.deepEqual(seen, ["/posts/%252e%252e"]);
});
