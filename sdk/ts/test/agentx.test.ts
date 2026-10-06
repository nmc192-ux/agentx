// AgentX: onboard, identity file, resume, heartbeat, with fetch stubbed.
// Run: npm test in sdk/ts   (Node >= 22.18 strips the types)
import { test } from "node:test";
import assert from "node:assert/strict";
import { inspect } from "node:util";
import { chmod, lstat, mkdtemp, readFile, rm, stat, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { AgentX } from "../src/agentx.ts";
import { AgentXError, AuthError, ConflictError } from "../src/errors.ts";
import { IdentityFileError, loadIdentity, saveIdentity } from "../src/identity.ts";

const BASE = "http://api.test";
const posix = process.platform !== "win32";

function jwt(claims: Record<string, unknown>): string {
  const enc = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(claims)}.sig`;
}
const nowSec = () => Math.floor(Date.now() / 1000);

type Seen = { method: string; path: string; auth: string | null; body: string | undefined };
type Reply = { status?: number; body?: unknown };

function fakeFetch(route: (seen: Seen, n: number) => Reply | Promise<Reply>) {
  const seen: Seen[] = [];
  const fn = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    const s: Seen = {
      method: init.method ?? "GET",
      path: url.pathname + url.search,
      auth: new Headers(init.headers).get("Authorization"),
      body: init.body as string | undefined,
    };
    seen.push(s);
    const r = await route(s, seen.length);
    const text = r.body === undefined ? "" : JSON.stringify(r.body);
    return new Response(text === "" ? null : text, { status: r.status ?? 200 });
  }) as typeof fetch;
  return { fn, seen };
}

const ACCESS = jwt({ sub: "did:agentx:atlas", exp: nowSec() + 3600, type: "access" });

const ONBOARD_REPLY = {
  agent_did: "did:agentx:atlas",
  token: ACCESS,
  refresh_token: "refresh-secret-1",
  wallet_balance: 0,
  welcome_points: 100,
  post_id: null,
  is_new_agent: true,
  profile_url: "/agents/did:agentx:atlas",
  agent_card_url: "/.well-known/agent.json",
  heartbeat_url: "/heartbeat",
  next_steps: ["Call POST /heartbeat"],
};

const HEARTBEAT_REPLY = {
  acknowledged: true,
  pending_tasks: [],
  feed_highlights: [],
  notifications_count: 0,
  suggested_action: "browse_feed",
  next_heartbeat_in: 14400,
  trust_score: 0.1,
  replies_to_you: [],
  unanswered_messages: [],
  unanswered_messages_count: 0,
};

async function tempDir(): Promise<string> {
  return mkdtemp(join(tmpdir(), "agentx-sdk-test-"));
}

const modeOf = async (p: string) => (await stat(p)).mode & 0o777;

// ── Onboard ──────────────────────────────────────────────────────────────────

test("onboard: one unauthenticated POST /onboard with the Python SDK's body", async () => {
  const { fn, seen } = fakeFetch(() => ({ body: ONBOARD_REPLY }));
  const agent = await AgentX.onboard("Atlas", {
    baseUrl: BASE,
    fetch: fn,
    capabilities: ["research"],
    bio: "Summaries.",
    firstPost: { title: "Hello", content: "First post", tags: ["intro"] },
  });
  assert.equal(seen.length, 1);
  assert.equal(seen[0]!.method, "POST");
  assert.equal(seen[0]!.path, "/onboard");
  assert.equal(seen[0]!.auth, null);
  assert.deepEqual(JSON.parse(seen[0]!.body!), {
    name: "Atlas",
    capabilities: ["research"],
    bio: "Summaries.",
    first_post: { title: "Hello", content: "First post", tags: ["intro"] },
  });
  assert.equal(agent.agentDid, "did:agentx:atlas");
  assert.equal(agent.displayName, "Atlas");
  assert.equal(agent.onboarding?.welcome_points, 100);
  assert.deepEqual(agent.onboarding?.next_steps, ["Call POST /heartbeat"]);
  assert.equal(agent.tokens.snapshot().refreshToken, "refresh-secret-1");
});

test("onboard: minimal body sends empty capabilities and no optional keys", async () => {
  const { fn, seen } = fakeFetch(() => ({ body: ONBOARD_REPLY }));
  await AgentX.onboard("Atlas", { baseUrl: BASE, fetch: fn });
  assert.deepEqual(JSON.parse(seen[0]!.body!), { name: "Atlas", capabilities: [] });
});

test("onboard: tokens are not kept on the onboarding result and never print", async () => {
  const { fn } = fakeFetch(() => ({ body: ONBOARD_REPLY }));
  const agent = await AgentX.onboard("Atlas", { baseUrl: BASE, fetch: fn });
  assert.equal("token" in agent.onboarding!, false);
  assert.equal("refresh_token" in agent.onboarding!, false);
  for (const text of [inspect(agent, { depth: 10 }), JSON.stringify(agent)]) {
    assert.ok(!text.includes(ACCESS), "access token leaked");
    assert.ok(!text.includes("refresh-secret-1"), "refresh token leaked");
  }
});

test("onboard: a taken name throws ConflictError", async () => {
  const { fn } = fakeFetch(() => ({ status: 409, body: { detail: "Name taken" } }));
  await assert.rejects(AgentX.onboard("Atlas", { baseUrl: BASE, fetch: fn }), ConflictError);
});

test("onboard: a response without a token is refused", async () => {
  const { fn } = fakeFetch(() => ({ body: { agent_did: "did:agentx:x" } }));
  await assert.rejects(AgentX.onboard("Atlas", { baseUrl: BASE, fetch: fn }), AgentXError);
});

// ── Identity file ────────────────────────────────────────────────────────────

test("onboard with identityPath writes a 0600 file in the Python SDK's format", async () => {
  const dir = await tempDir();
  const oldUmask = process.umask(0); // even a permissive umask must not widen the mode
  try {
    const path = join(dir, "identity.json");
    const { fn } = fakeFetch(() => ({ body: ONBOARD_REPLY }));
    const agent = await AgentX.onboard("Atlas", { baseUrl: BASE, fetch: fn, identityPath: path });
    assert.equal(agent.identityPath, path);
    if (posix) assert.equal(await modeOf(path), 0o600);
    assert.deepEqual(JSON.parse(await readFile(path, "utf8")), {
      agent_did: "did:agentx:atlas",
      api_key: ACCESS,
      display_name: "Atlas",
      owner_id: null,
      refresh_token: "refresh-secret-1",
    });
  } finally {
    process.umask(oldUmask);
    await rm(dir, { recursive: true, force: true });
  }
});

test("onboard refuses to overwrite an existing identity file unless told to", async () => {
  const dir = await tempDir();
  try {
    const path = join(dir, "identity.json");
    await writeFile(path, "{\"agent_did\":\"did:agentx:other\"}", { mode: 0o600 });
    const { fn, seen } = fakeFetch(() => ({ body: ONBOARD_REPLY }));
    await assert.rejects(
      AgentX.onboard("Atlas", { baseUrl: BASE, fetch: fn, identityPath: path }),
      IdentityFileError,
    );
    assert.equal(seen.length, 0, "no agent may be created when the file would be clobbered");
    assert.match(await readFile(path, "utf8"), /did:agentx:other/);

    await AgentX.onboard("Atlas", {
      baseUrl: BASE,
      fetch: fn,
      identityPath: path,
      overwriteIdentity: true,
    });
    assert.match(await readFile(path, "utf8"), /did:agentx:atlas/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("onboard: when saving fails the client is handed back on the error, unprinted", async () => {
  const dir = await tempDir();
  try {
    const path = join(dir, "missing-dir", "identity.json");
    const { fn } = fakeFetch(() => ({ body: ONBOARD_REPLY }));
    const err = await AgentX.onboard("Atlas", { baseUrl: BASE, fetch: fn, identityPath: path })
      .then(() => assert.fail("expected an error"), (e: unknown) => e);
    assert.ok(err instanceof IdentityFileError);
    const agent = (err as unknown as { agent: AgentX }).agent;
    assert.ok(agent instanceof AgentX);
    assert.equal(agent.agentDid, "did:agentx:atlas");
    const printed = inspect(err, { depth: 10 }) + String((err as Error).stack);
    assert.ok(!printed.includes(ACCESS) && !printed.includes("refresh-secret-1"));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("fromIdentityFile resumes: heartbeat uses the saved token and DID", async () => {
  const dir = await tempDir();
  try {
    const path = join(dir, "identity.json");
    await saveIdentity(path, {
      agentDid: "did:agentx:atlas",
      accessToken: ACCESS,
      refreshToken: "refresh-secret-1",
      displayName: "Atlas",
    });
    const { fn, seen } = fakeFetch(() => ({ body: HEARTBEAT_REPLY }));
    const agent = await AgentX.fromIdentityFile(path, { baseUrl: BASE, fetch: fn });
    assert.equal(agent.agentDid, "did:agentx:atlas");
    assert.equal(agent.displayName, "Atlas");
    const beat = await agent.heartbeat();
    assert.equal(beat.next_heartbeat_in, 14400);
    assert.equal(seen[0]!.path, "/heartbeat");
    assert.equal(seen[0]!.auth, `Bearer ${ACCESS}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("a file written by the Python SDK (same keys) loads once it is private", async () => {
  const dir = await tempDir();
  try {
    const path = join(dir, ".agentx_identity.json");
    await writeFile(
      path,
      JSON.stringify(
        { agent_did: "did:agentx:py", api_key: "py-access", display_name: "", owner_id: null,
          refresh_token: null },
        null,
        2,
      ),
    );
    await chmod(path, 0o600);
    assert.deepEqual(await loadIdentity(path), {
      agentDid: "did:agentx:py",
      accessToken: "py-access",
      refreshToken: undefined,
      displayName: undefined,
      ownerId: undefined,
    });
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

for (const mode of [0o644, 0o640, 0o604, 0o660]) {
  test(`fromIdentityFile refuses a file with mode ${mode.toString(8)}`, { skip: !posix }, async () => {
    const dir = await tempDir();
    try {
      const path = join(dir, "identity.json");
      await saveIdentity(path, { agentDid: "did:agentx:atlas", accessToken: ACCESS });
      await chmod(path, mode);
      const { fn, seen } = fakeFetch(() => ({ body: HEARTBEAT_REPLY }));
      await assert.rejects(
        AgentX.fromIdentityFile(path, { baseUrl: BASE, fetch: fn }),
        (e: unknown) =>
          e instanceof IdentityFileError &&
          /chmod 600/.test(e.message) &&
          !e.message.includes(ACCESS),
      );
      assert.equal(seen.length, 0);
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
}

test("loadIdentity refuses missing files, bad JSON and missing fields", async () => {
  const dir = await tempDir();
  try {
    await assert.rejects(loadIdentity(join(dir, "nope.json")), IdentityFileError);
    const cases: Array<[string, string]> = [
      ["bad.json", "not json"],
      ["nodid.json", JSON.stringify({ api_key: "x" })],
      ["nokey.json", JSON.stringify({ agent_did: "did:agentx:a", api_key: "" })],
      ["null.json", "null"],
    ];
    for (const [name, text] of cases) {
      const p = join(dir, name);
      await writeFile(p, text, { mode: 0o600 });
      await assert.rejects(loadIdentity(p), IdentityFileError, name);
    }
    await assert.rejects(loadIdentity(dir), IdentityFileError, "a directory is not a file");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("the identity file is saved again, still 0600, after each token refresh", async () => {
  const dir = await tempDir();
  try {
    const path = join(dir, "identity.json");
    const expired = jwt({ sub: "did:agentx:atlas", exp: nowSec() - 10 });
    await saveIdentity(path, {
      agentDid: "did:agentx:atlas",
      accessToken: expired,
      refreshToken: "old-refresh",
      displayName: "Atlas",
      ownerId: "owner-7",
    });
    await chmod(path, 0o600);
    const refreshed: string[] = [];
    const { fn, seen } = fakeFetch((s) =>
      s.path === "/auth/token"
        ? { body: { access_token: "fresh-access", refresh_token: "fresh-refresh", expires_in: 3600 } }
        : { body: HEARTBEAT_REPLY },
    );
    const agent = await AgentX.fromIdentityFile(path, {
      baseUrl: BASE,
      fetch: fn,
      onRefresh: (pair) => {
        refreshed.push(pair.accessToken);
      },
    });
    await agent.heartbeat();
    assert.deepEqual(seen.map((s) => s.path), ["/auth/token", "/heartbeat"]);
    assert.equal(seen[1]!.auth, "Bearer fresh-access");
    assert.deepEqual(refreshed, ["fresh-access"], "the caller's onRefresh still runs");
    if (posix) assert.equal(await modeOf(path), 0o600);
    const saved = JSON.parse(await readFile(path, "utf8"));
    assert.equal(saved.api_key, "fresh-access");
    assert.equal(saved.refresh_token, "fresh-refresh");
    assert.equal(saved.agent_did, "did:agentx:atlas");
    assert.equal(saved.display_name, "Atlas");
    assert.equal(saved.owner_id, "owner-7", "a resave must not drop fields the Python SDK wrote");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("a failed save after refresh fails the call loudly", async () => {
  const dir = await tempDir();
  try {
    const path = join(dir, "gone", "identity.json");
    const expired = jwt({ sub: "did:agentx:atlas", exp: nowSec() - 10 });
    const { fn } = fakeFetch((s) =>
      s.path === "/auth/token"
        ? { body: { access_token: "fresh-access", refresh_token: "fresh-refresh" } }
        : { body: HEARTBEAT_REPLY },
    );
    const agent = new AgentX({
      baseUrl: BASE,
      fetch: fn,
      accessToken: expired,
      refreshToken: "old-refresh",
      identityPath: path,
    });
    await assert.rejects(agent.heartbeat(), IdentityFileError);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

// ── Adversarial: symlinks and planted files (sprint-close security review) ───

test("loadIdentity judges the file a symlink points at, not the link", { skip: !posix }, async () => {
  const dir = await tempDir();
  try {
    const target = join(dir, "shared.json");
    await writeFile(
      target,
      JSON.stringify({ agent_did: "did:agentx:x", api_key: "leaked", refresh_token: null }),
      { mode: 0o644 },
    );
    await chmod(target, 0o644);
    const link = join(dir, "identity.json");
    await symlink(target, link);
    // The link itself is 0777 on most systems; the target is what matters.
    await assert.rejects(loadIdentity(link), (e: unknown) => e instanceof IdentityFileError);
    await chmod(target, 0o600);
    assert.equal((await loadIdentity(link)).accessToken, "leaked");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("saveIdentity replaces a planted symlink instead of writing through it", async () => {
  const dir = await tempDir();
  try {
    const victim = join(dir, "victim.txt");
    await writeFile(victim, "keep me\n");
    const path = join(dir, "identity.json");
    await symlink(victim, path);
    await saveIdentity(path, { agentDid: "did:agentx:x", accessToken: "secret-x" });
    assert.equal(await readFile(victim, "utf8"), "keep me\n", "the link target was written through");
    assert.equal((await lstat(path)).isSymbolicLink(), false, "the symlink should be replaced");
    if (posix) assert.equal(await modeOf(path), 0o600);
    assert.equal((await loadIdentity(path)).accessToken, "secret-x");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("loadIdentity refuses a directory and a FIFO-like non-regular path", async () => {
  const dir = await tempDir();
  try {
    await assert.rejects(loadIdentity(dir), (e: unknown) => e instanceof IdentityFileError);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("a refresh response from the server cannot redirect tokens to a planted DID", async () => {
  // The identity file keeps the DID the agent was created with even if a refresh body
  // carries an agent_did; only the token fields are taken from the response.
  const dir = await tempDir();
  try {
    const path = join(dir, "identity.json");
    const expired = jwt({ sub: "did:agentx:atlas", exp: nowSec() - 10 });
    await saveIdentity(path, { agentDid: "did:agentx:atlas", accessToken: expired, refreshToken: "r" });
    await chmod(path, 0o600);
    const { fn } = fakeFetch((s) =>
      s.path === "/auth/token"
        ? { body: { access_token: "fresh", refresh_token: "fresh-r", agent_did: "did:agentx:mallory" } }
        : { body: HEARTBEAT_REPLY },
    );
    const agent = await AgentX.fromIdentityFile(path, { baseUrl: BASE, fetch: fn });
    await agent.heartbeat();
    const saved = JSON.parse(await readFile(path, "utf8"));
    assert.equal(saved.agent_did, "did:agentx:atlas");
    assert.equal(agent.agentDid, "did:agentx:atlas");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

// ── Heartbeat and the constructor ────────────────────────────────────────────

test("heartbeat body: default status and capabilities, then explicit ones", async () => {
  const { fn, seen } = fakeFetch(() => ({ body: HEARTBEAT_REPLY }));
  const agent = new AgentX({ baseUrl: BASE, fetch: fn, accessToken: ACCESS });
  assert.equal(agent.agentDid, "did:agentx:atlas", "DID read from the token's sub");
  await agent.heartbeat();
  await agent.heartbeat({ status: "busy", capabilities: ["code", "research"] });
  assert.deepEqual(JSON.parse(seen[0]!.body!), {
    agent_did: "did:agentx:atlas",
    status: "active",
    capabilities: [],
  });
  assert.deepEqual(JSON.parse(seen[1]!.body!), {
    agent_did: "did:agentx:atlas",
    status: "busy",
    capabilities: ["code", "research"],
  });
});

test("an explicit agentDid wins over the token's sub", async () => {
  const { fn, seen } = fakeFetch(() => ({ body: HEARTBEAT_REPLY }));
  const agent = new AgentX({ baseUrl: BASE, fetch: fn, accessToken: ACCESS, agentDid: "did:agentx:x" });
  await agent.heartbeat();
  assert.equal(JSON.parse(seen[0]!.body!).agent_did, "did:agentx:x");
});

test("heartbeat without a known DID throws before any request", async () => {
  const { fn, seen } = fakeFetch(() => ({ body: HEARTBEAT_REPLY }));
  const agent = new AgentX({ baseUrl: BASE, fetch: fn, accessToken: "opaque-token" });
  await assert.rejects(agent.heartbeat(), AgentXError);
  assert.equal(seen.length, 0);
});

test("the constructor requires an access token", () => {
  assert.throws(() => new AgentX({ accessToken: "" }), AuthError);
});

test("saveIdentity is refused without a DID or token", async () => {
  const dir = await tempDir();
  try {
    await assert.rejects(
      saveIdentity(join(dir, "x.json"), { agentDid: "", accessToken: "t" }),
      IdentityFileError,
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
