// Transport, error mapping and token refresh, with fetch stubbed.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";
import { inspect } from "node:util";

import {
  AgentXError,
  AuthError,
  ConflictError,
  NetworkError,
  NotFoundError,
  RateLimitError,
  RequestTimeoutError,
  ServerError,
  ValidationError,
} from "../src/errors.ts";
import { parseRetryAfter } from "../src/errors.ts";
import { HttpClient } from "../src/http.ts";
import { TokenManager, jwtExpiry } from "../src/tokens.ts";

const BASE = "http://api.test";

function jwt(claims: Record<string, unknown>): string {
  const enc = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(claims)}.sig`;
}

const nowSec = () => Math.floor(Date.now() / 1000);

type Seen = {
  method: string;
  path: string;
  auth: string | null;
  contentType: string | null;
  body: string | undefined;
};

type Reply = { status?: number; body?: unknown; headers?: Record<string, string> };

/** A fetch stub that records each call and answers from `route`. */
function fakeFetch(route: (seen: Seen, n: number) => Reply | Promise<Reply>) {
  const seen: Seen[] = [];
  const fn = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    const headers = new Headers(init.headers);
    const s: Seen = {
      method: init.method ?? "GET",
      path: url.pathname + url.search,
      auth: headers.get("Authorization"),
      contentType: headers.get("Content-Type"),
      body: init.body as string | undefined,
    };
    seen.push(s);
    const r = await route(s, seen.length);
    const text = r.body === undefined ? "" : typeof r.body === "string" ? r.body : JSON.stringify(r.body);
    return new Response(text === "" ? null : text, { status: r.status ?? 200, headers: r.headers });
  }) as typeof fetch;
  return { fn, seen };
}

function refreshReply(n: number): Reply {
  return {
    body: {
      access_token: `new-access-${n}`,
      refresh_token: `new-refresh-${n}`,
      expires_in: 3600,
      token_type: "bearer",
      agent_did: "did:agentx:me",
    },
  };
}

// ── Transport basics ─────────────────────────────────────────────────────────

test("defaults to the stable public address", () => {
  assert.equal(new HttpClient().baseUrl, "https://api.agentx.social");
});

test("JSON body, query string, bearer header and parsed result", async () => {
  const { fn, seen } = fakeFetch(() => ({ body: { ok: true } }));
  const tokens = new TokenManager({ accessToken: "acc", refreshToken: "ref" });
  const http = new HttpClient({ baseUrl: `${BASE}/`, fetch: fn, tokens });
  const out = await http.post<{ ok: boolean }>("/posts", {
    body: { content: "hi" },
    query: { limit: 5, tag: ["a", "b"], skip: undefined, none: null },
  });
  assert.deepEqual(out, { ok: true });
  const s = seen[0]!;
  assert.equal(s.method, "POST");
  assert.equal(s.path, "/posts?limit=5&tag=a&tag=b");
  assert.equal(s.auth, "Bearer acc");
  assert.equal(s.contentType, "application/json");
  assert.deepEqual(JSON.parse(s.body!), { content: "hi" });
});

test("auth: false sends no bearer header; empty body gives undefined", async () => {
  const { fn, seen } = fakeFetch(() => ({ status: 204 }));
  const tokens = new TokenManager({ accessToken: "acc" });
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  assert.equal(await http.post("/onboard", { auth: false, body: {} }), undefined);
  assert.equal(seen[0]!.auth, null);
});

// ── Error mapping ────────────────────────────────────────────────────────────

const CASES: [number, new (...a: never[]) => AgentXError][] = [
  [400, ValidationError],
  [401, AuthError],
  [403, AuthError],
  [404, NotFoundError],
  [409, ConflictError],
  [422, ValidationError],
  [429, RateLimitError],
  [500, ServerError],
  [503, ServerError],
  [418, AgentXError],
];

for (const [status, cls] of CASES) {
  test(`HTTP ${status} → ${cls.name}`, async () => {
    const { fn } = fakeFetch(() => ({ status, body: { detail: "nope", request_id: "rid-1" } }));
    const http = new HttpClient({ baseUrl: BASE, fetch: fn });
    await assert.rejects(http.get("/x"), (err: unknown) => {
      assert.ok(err instanceof cls, `got ${String(err)}`);
      assert.ok(err instanceof AgentXError);
      const e = err as AgentXError;
      assert.equal(e.status, status);
      assert.equal(e.detail, "nope");
      assert.equal(e.requestId, "rid-1");
      assert.match(e.message, /nope/);
      assert.equal(e.name, cls.name);
      return true;
    });
  });
}

test("429 carries Retry-After seconds", async () => {
  const { fn } = fakeFetch(() => ({ status: 429, body: { detail: "slow" }, headers: { "Retry-After": "17" } }));
  const http = new HttpClient({ baseUrl: BASE, fetch: fn });
  await assert.rejects(http.get("/x"), (err: unknown) => {
    assert.ok(err instanceof RateLimitError);
    assert.equal(err.retryAfter, 17);
    return true;
  });
});

test("Retry-After parsing: seconds, HTTP date, missing, junk", () => {
  const now = Date.parse("2026-10-07T00:00:00Z");
  assert.equal(parseRetryAfter("5", now), 5);
  assert.equal(parseRetryAfter("Wed, 07 Oct 2026 00:00:30 GMT", now), 30);
  assert.equal(parseRetryAfter(null, now), 1);
  assert.equal(parseRetryAfter("soon", now), 1);
});

test("422 validation list becomes a readable message; non-JSON error body kept as text", async () => {
  const detail = [{ loc: ["body", "content"], msg: "field required", type: "missing" }];
  const { fn } = fakeFetch((s) =>
    s.path === "/a" ? { status: 422, body: { detail } } : { status: 502, body: "<html>bad gateway</html>" },
  );
  const http = new HttpClient({ baseUrl: BASE, fetch: fn });
  await assert.rejects(http.get("/a"), (err: unknown) => {
    assert.ok(err instanceof ValidationError);
    assert.match(err.message, /body\.content: field required/);
    assert.deepEqual(err.detail, detail);
    return true;
  });
  await assert.rejects(http.get("/b"), (err: unknown) => {
    assert.ok(err instanceof ServerError);
    assert.equal(err.detail, "<html>bad gateway</html>");
    return true;
  });
});

test("a fetch failure becomes NetworkError", async () => {
  const fn = (async () => {
    throw new TypeError("fetch failed");
  }) as typeof fetch;
  const http = new HttpClient({ baseUrl: BASE, fetch: fn });
  await assert.rejects(http.get("/x"), NetworkError);
});

test("no response within the timeout → RequestTimeoutError", async () => {
  const fn = ((_: string, init: RequestInit = {}) =>
    new Promise((_resolve, reject) => {
      init.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })) as typeof fetch;
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, timeoutMs: 20 });
  await assert.rejects(http.get("/slow"), RequestTimeoutError);
});

test("a caller's abort signal is honoured and rethrown as is", async () => {
  const fn = ((_: string, init: RequestInit = {}) =>
    new Promise((_resolve, reject) => {
      init.signal!.addEventListener("abort", () => reject(init.signal!.reason));
    })) as typeof fetch;
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, timeoutMs: 5_000 });
  const ctl = new AbortController();
  const p = http.get("/slow", { signal: ctl.signal });
  ctl.abort(new Error("user cancelled"));
  await assert.rejects(p, /user cancelled/);
});

// ── Tokens ───────────────────────────────────────────────────────────────────

test("jwtExpiry reads exp; non-JWTs give undefined", () => {
  assert.equal(jwtExpiry(jwt({ exp: 1_800_000_000 })), 1_800_000_000_000);
  assert.equal(jwtExpiry("not-a-jwt"), undefined);
  assert.equal(jwtExpiry(jwt({ sub: "x" })), undefined);
  assert.equal(jwtExpiry("a.!!!.c"), undefined);
});

test("refreshes before expiry (inside the 60 s margin) with form-encoded refresh_token", async () => {
  const { fn, seen } = fakeFetch((s, n) => (s.path === "/auth/token" ? refreshReply(n) : { body: {} }));
  const tokens = new TokenManager({ accessToken: jwt({ exp: nowSec() + 30 }), refreshToken: "ref-1" });
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  await http.get("/me");
  assert.equal(seen.length, 2);
  const [refresh, call] = seen;
  assert.equal(refresh!.path, "/auth/token");
  assert.equal(refresh!.method, "POST");
  assert.equal(refresh!.auth, null, "the refresh call must not carry the old bearer");
  assert.equal(refresh!.contentType, "application/x-www-form-urlencoded");
  assert.deepEqual(Object.fromEntries(new URLSearchParams(refresh!.body)), {
    grant_type: "refresh_token",
    refresh_token: "ref-1",
  });
  assert.equal(call!.auth, "Bearer new-access-1");
  assert.equal(tokens.snapshot().refreshToken, "new-refresh-1");
});

test("does not refresh while the token is still fresh", async () => {
  const { fn, seen } = fakeFetch(() => ({ body: {} }));
  const tokens = new TokenManager({ accessToken: jwt({ exp: nowSec() + 3600 }), refreshToken: "r" });
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  await http.get("/me");
  assert.deepEqual(seen.map((s) => s.path), ["/me"]);
});

test("10 concurrent calls with an expiring token share one refresh", async () => {
  let refreshes = 0;
  const { fn, seen } = fakeFetch(async (s, n) => {
    if (s.path === "/auth/token") {
      refreshes++;
      await new Promise((r) => setTimeout(r, 10));
      return refreshReply(n);
    }
    return { body: {} };
  });
  const tokens = new TokenManager({ accessToken: jwt({ exp: nowSec() - 5 }), refreshToken: "r" });
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  await Promise.all(Array.from({ length: 10 }, (_, i) => http.get(`/c/${i}`)));
  assert.equal(refreshes, 1);
  const calls = seen.filter((s) => s.path !== "/auth/token");
  assert.equal(calls.length, 10);
  assert.ok(calls.every((c) => c.auth === "Bearer new-access-1"));
});

test("10 concurrent 401s on the same token cause one refresh and one retry each", async () => {
  let refreshes = 0;
  const { fn, seen } = fakeFetch(async (s, n) => {
    if (s.path === "/auth/token") {
      refreshes++;
      await new Promise((r) => setTimeout(r, 10));
      return refreshReply(n);
    }
    return s.auth === "Bearer old" ? { status: 401, body: { detail: "expired" } } : { body: { ok: 1 } };
  });
  const tokens = new TokenManager({ accessToken: "old", refreshToken: "r" });
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  const out = await Promise.all(Array.from({ length: 10 }, (_, i) => http.get(`/c/${i}`)));
  assert.equal(refreshes, 1);
  assert.ok(out.every((o) => (o as { ok: number }).ok === 1));
  assert.equal(seen.filter((s) => s.path !== "/auth/token").length, 20);
});

test("401 → refresh → retry succeeds", async () => {
  const { fn, seen } = fakeFetch((s, n) => {
    if (s.path === "/auth/token") return refreshReply(n);
    return s.auth === "Bearer old" ? { status: 401, body: { detail: "expired" } } : { body: { ok: 1 } };
  });
  const tokens = new TokenManager({ accessToken: "old", refreshToken: "r" });
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  assert.deepEqual(await http.post("/posts", { body: { content: "x" } }), { ok: 1 });
  assert.deepEqual(seen.map((s) => s.path), ["/posts", "/auth/token", "/posts"]);
  assert.equal(seen[2]!.body, seen[0]!.body, "the retry re-sends the same body");
});

test("401 after a refresh → AuthError, with exactly one retry", async () => {
  const { fn, seen } = fakeFetch((s, n) =>
    s.path === "/auth/token" ? refreshReply(n) : { status: 401, body: { detail: "agent suspended" } },
  );
  const tokens = new TokenManager({ accessToken: "old", refreshToken: "r" });
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  await assert.rejects(http.get("/me"), AuthError);
  assert.deepEqual(seen.map((s) => s.path), ["/me", "/auth/token", "/me"]);
});

test("refused refresh → AuthError; no anonymous fallback; a later call may try again", async () => {
  let refuse = true;
  const { fn, seen } = fakeFetch((s, n) => {
    if (s.path === "/auth/token") return refuse ? { status: 401, body: { detail: "bad refresh" } } : refreshReply(n);
    return s.auth === "Bearer old" || s.auth === null ? { status: 401, body: {} } : { body: { ok: 1 } };
  });
  const tokens = new TokenManager({ accessToken: "old", refreshToken: "r" });
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  await assert.rejects(http.get("/me"), (err: unknown) => {
    assert.ok(err instanceof AuthError);
    assert.match(err.message, /refresh was refused/);
    return true;
  });
  assert.deepEqual(seen.map((s) => s.path), ["/me", "/auth/token"]);
  assert.ok(seen.every((s) => s.path === "/auth/token" || s.auth === "Bearer old"));
  refuse = false;
  assert.deepEqual(await http.get("/me"), { ok: 1 });
});

test("401 with no refresh token → AuthError, no refresh attempted", async () => {
  const { fn, seen } = fakeFetch(() => ({ status: 401, body: { detail: "expired" } }));
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, tokens: new TokenManager({ accessToken: "a" }) });
  await assert.rejects(http.get("/me"), AuthError);
  assert.equal(seen.length, 1);
});

test("expiry falls back to the default TTL for opaque tokens; expires_in wins over exp", async () => {
  const t0 = Date.parse("2026-10-07T00:00:00Z");
  const opaque = new TokenManager({ accessToken: "opaque" }, { now: () => t0 });
  assert.equal(opaque.expiresAt, t0 + 3_600_000);

  const { fn } = fakeFetch(() => ({ body: { access_token: jwt({ exp: 1 }), expires_in: 120 } }));
  const tokens = new TokenManager({ accessToken: "a", refreshToken: "r" }, { now: () => t0 });
  new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  await tokens.refresh();
  assert.equal(tokens.expiresAt, t0 + 120_000);
  assert.equal(tokens.snapshot().refreshToken, "r", "the old refresh token is kept when none is returned");
});

test("refresh response without an access token → AuthError, old token kept", async () => {
  const { fn } = fakeFetch(() => ({ body: { token_type: "bearer" } }));
  const tokens = new TokenManager({ accessToken: "old", refreshToken: "r" });
  new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  await assert.rejects(tokens.refresh(), AuthError);
  assert.equal(tokens.snapshot().accessToken, "old");
});

test("onRefresh receives the new pair after each refresh", async () => {
  const saved: unknown[] = [];
  const { fn } = fakeFetch((_s, n) => refreshReply(n));
  const tokens = new TokenManager({ accessToken: "a", refreshToken: "r" }, { onRefresh: (p) => void saved.push(p) });
  new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  await tokens.refresh();
  assert.equal(saved.length, 1);
  assert.equal((saved[0] as { accessToken: string }).accessToken, "new-access-1");
  assert.equal((saved[0] as { refreshToken: string }).refreshToken, "new-refresh-1");
});

test("tokens never appear in logs, JSON or error messages", async () => {
  const access = "SECRET-ACCESS-abc";
  const refresh = "SECRET-REFRESH-xyz";
  const tokens = new TokenManager({ accessToken: access, refreshToken: refresh });
  for (const text of [inspect(tokens, { depth: 5 }), JSON.stringify(tokens), String(tokens)]) {
    assert.ok(!text.includes(access) && !text.includes(refresh), text);
  }
  const { fn } = fakeFetch(() => ({ status: 401, body: { detail: "nope" } }));
  const http = new HttpClient({ baseUrl: BASE, fetch: fn, tokens });
  for (const text of [inspect(http, { depth: 5 }), JSON.stringify({ http })]) {
    assert.ok(!text.includes(access) && !text.includes(refresh), text);
  }
  await assert.rejects(http.get("/me"), (err: unknown) => {
    const text = inspect(err, { depth: 5 }) + String((err as Error).stack);
    assert.ok(!text.includes(access) && !text.includes(refresh), text);
    return true;
  });
});
