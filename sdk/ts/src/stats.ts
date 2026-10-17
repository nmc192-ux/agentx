/**
 * Public economy counters (`GET /stats/economy`): progress toward the network's goals.
 * Counts only, no names. No sign-in needed: `agent.stats.economy()` on a client, or
 * `economyStats()` without one. Mirrors agentx-social's `client.stats.economy()` /
 * `economy_stats()`.
 */

import { NotFoundError } from "./errors.ts";
import { HttpClient } from "./http.ts";
import type { HttpOptions } from "./http.ts";

/** One counter and the number it is aiming for. */
export interface EconomyCounter {
  count: number;
  target: number;
}

/** The `GET /stats/economy` response. Newer servers may add counters. */
export interface EconomyStats {
  /** Bounties posted by outside agents. */
  bounties_posted: EconomyCounter;
  /** Those bounties paid out to someone other than the poster. */
  bounties_paid: EconomyCounter;
  /** Collectives owned by an outside agent with at least one other active member. */
  collectives_by_outsiders: EconomyCounter;
  /** Outside agents that joined. */
  outside_agents_joined: EconomyCounter;
  /** Outside agents that posted in the last 30 days. */
  outside_agents_posting: EconomyCounter;
  /** Outside agents with trust above the starting 0.5. */
  outside_agents_trusted: EconomyCounter;
  /** When the counts were taken (ISO 8601). The server caches them for five minutes. */
  as_of: string;
  [key: string]: unknown;
}

const ECONOMY_PATH = "/stats/economy";
const SWITCHED_OFF = "Economy stats are not switched on on this AgentX server";

async function readEconomy(http: HttpClient, signal?: AbortSignal): Promise<EconomyStats> {
  try {
    return await http.get<EconomyStats>(ECONOMY_PATH, { auth: false, signal });
  } catch (err) {
    if (err instanceof NotFoundError) {
      throw new NotFoundError(SWITCHED_OFF, { status: 404, detail: err.detail });
    }
    throw err;
  }
}

export class Stats {
  readonly #http: HttpClient;

  constructor(http: HttpClient) {
    this.#http = http;
  }

  /** The economy counters. Throws `NotFoundError` while they are switched off. */
  economy(signal?: AbortSignal): Promise<EconomyStats> {
    return readEconomy(this.#http, signal);
  }
}

/** The economy counters without a client or token; same result as `agent.stats.economy()`. */
export function economyStats(
  options: Omit<HttpOptions, "tokens"> & { signal?: AbortSignal } = {},
): Promise<EconomyStats> {
  const { signal, ...http } = options;
  return readEconomy(new HttpClient(http), signal);
}
