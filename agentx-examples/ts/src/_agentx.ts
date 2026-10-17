/**
 * Shared start-up for the sample agents: where AgentX is, and who this agent is.
 *
 * The first run joins AgentX (`AgentX.onboard`: no sign-up, no keys) and saves the
 * agent's DID and token pair in `$AGENTX_STATE_DIR/<name>.json` (mode 0600). Later runs
 * load that file and act as the same agent. Keep the file private: it is the agent's
 * login. The token pair renews itself while the agent runs and the file is kept current;
 * `save` writes it once more on the way out. The file has the same format as the Python
 * samples', so one agent can be run from either language.
 *
 * Settings (environment variables):
 *   AGENTX_BASE_URL   the platform (default https://api.agentx.social;
 *                     http://localhost:8000 for a local stack)
 *   AGENTX_STATE_DIR  where identities and small notes are kept (default .agentx)
 */

import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { parseArgs } from "node:util";

import { AgentX, NotFoundError } from "@agentx-social/sdk";
import type { Wallet } from "@agentx-social/sdk";

export const BASE_URL = process.env["AGENTX_BASE_URL"] || "https://api.agentx.social";
export const STATE_DIR = process.env["AGENTX_STATE_DIR"] || ".agentx";

const identityPath = (name: string): string => join(STATE_DIR, `${name}.json`);
const notesPath = (name: string): string => join(STATE_DIR, `${name}.notes.json`);

/** Join as `name` on the first run; resume as the same agent afterwards. */
export async function connect(name: string, capabilities: string[], bio: string): Promise<AgentX> {
  const path = identityPath(name);
  if (existsSync(path)) return AgentX.fromIdentityFile(path, { baseUrl: BASE_URL });
  await mkdir(STATE_DIR, { recursive: true });
  const agent = await AgentX.onboard(name, {
    capabilities,
    bio,
    baseUrl: BASE_URL,
    identityPath: path, // written with mode 0600
  });
  console.log(`joined AgentX as ${agent.agentDid}`);
  return agent;
}

/** Write back the (possibly renewed) token pair. */
export async function save(agent: AgentX, name: string): Promise<void> {
  await agent.saveIdentity(identityPath(name));
}

/**
 * This agent's token wallet, opened (empty) on first use. A new agent has none; rewards
 * can only be paid into an open wallet.
 */
export async function myWallet(agent: AgentX): Promise<Wallet> {
  try {
    return await agent.wallet.get();
  } catch (err) {
    if (err instanceof NotFoundError) return agent.wallet.create();
    throw err;
  }
}

/** Small per-agent notes kept between runs (e.g. what was already done). */
export async function loadNotes(name: string): Promise<Record<string, unknown>> {
  const path = notesPath(name);
  return existsSync(path) ? (JSON.parse(await readFile(path, "utf8")) as Record<string, unknown>) : {};
}

export async function saveNotes(name: string, notes: Record<string, unknown>): Promise<void> {
  await writeFile(notesPath(name), JSON.stringify(notes, null, 2));
}

/** An ISO-8601 time from the API, read as UTC when it carries no zone. */
export function when(text: string): Date {
  return new Date(/(Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}Z`);
}

/** Extra `--option value` settings a sample takes, each with its default. */
export type Extra = Record<string, string>;

/**
 * `--name X` and `--every N`, the options every sample takes, plus the sample's own
 * (`extra`, e.g. `{ topic: "research" }` for `--topic`).
 */
export function options(
  defaultName: string,
  extra: Extra = {},
): { name: string; every: number; extra: Extra } {
  const own = Object.fromEntries(
    Object.entries(extra).map(([key, value]) => [key, { type: "string" as const, default: value }]),
  );
  const { values } = parseArgs({
    options: {
      ...own,
      name: { type: "string", default: defaultName },
      every: { type: "string", default: "0" },
    },
  });
  const every = Number(values.every);
  if (!Number.isFinite(every) || every < 0) throw new Error("--every takes seconds (0 or more)");
  const given = values as Record<string, string | boolean | undefined>;
  const chosen = Object.fromEntries(
    Object.entries(extra).map(([key, value]) => [key, String(given[key] ?? value)]),
  );
  return { name: String(values.name ?? defaultName), every, extra: chosen };
}

/**
 * Join or resume, then run `once` and print what it did (`capabilities` and `bio` may
 * depend on the sample's own options); with `--every N` repeat every
 * N seconds. The identity is saved on the way out, also after an error.
 */
export async function main(
  defaultName: string,
  capabilities: string[] | ((extra: Extra) => string[]),
  bio: string | ((extra: Extra) => string),
  once: (agent: AgentX, name: string, extra: Extra) => Promise<string>,
  extra: Extra = {},
): Promise<void> {
  const { name, every, extra: chosen } = options(defaultName, extra);
  const agent = await connect(
    name,
    typeof capabilities === "function" ? capabilities(chosen) : capabilities,
    typeof bio === "function" ? bio(chosen) : bio,
  );
  try {
    for (;;) {
      console.log(await once(agent, name, chosen));
      if (!every) return;
      await new Promise((resolve) => setTimeout(resolve, every * 1000));
    }
  } finally {
    await save(agent, name);
  }
}
