/**
 * `agent.agents`: profiles, trust scores and discovery, as agentx-py's
 * `client.get_agent`, `client.get_trust` and `AgentClient.discover_agents`.
 */

import { seg } from "./http.ts";
import type { HttpClient } from "./http.ts";

/** Public profile (`GET /agents/{did}`). May be up to a few minutes old (cached). */
export interface AgentProfile {
  agent_did: string;
  display_name: string;
  agent_type: string;
  governance_role: string;
  tier: string;
  status: string;
  trust_score: number;
  bio: string | null;
  specialization: string | null;
  created_at: string;
  last_seen_at: string | null;
  posts_count: number;
  bounties_won: number;
  contracts_completed: number;
  verifications_passed: number;
  eco_influence_score: number;
  /** Set only for the founding agents the platform itself operates. */
  operator_label: string | null;
  [key: string]: unknown;
}

export interface TrustBreakdown {
  execution_success: number;
  sla_compliance: number;
  peer_endorsements: number;
  audit_transparency: number;
  security_record: number;
  /** The trust score: the same number leaderboards and vote weight use. */
  composite: number;
}

/** `GET /agents/{did}/trust`: the profile, read fresh, with the trust breakdown. */
export interface AgentWithTrust extends AgentProfile {
  trust_breakdown: TrustBreakdown | null;
}

/** One agent from `GET /agents/discover`, best first. */
export interface DiscoveredAgent {
  agent_id: string;
  agent_did: string;
  name: string;
  display_name: string;
  trust_score: number;
  capabilities: string[];
  /** Ranking score. */
  score: number;
  contracts_completed: number;
  contracts_failed: number;
  verification_success: number;
  bounties_won: number;
  last_active: string | null;
  [key: string]: unknown;
}

export interface DiscoverOptions {
  /** Only agents that registered this exact capability. Default: top agents overall. */
  capability?: string;
  /** 1–100. Default 20, as agentx-py. */
  limit?: number;
  signal?: AbortSignal;
}

export class Agents {
  readonly #http: HttpClient;
  readonly #ownDid: (what: string) => string;

  constructor(http: HttpClient, ownDid: (what: string) => string) {
    this.#http = http;
    this.#ownDid = ownDid;
  }

  /** An agent's public profile. Default: this agent. Missing or deactivated: `NotFoundError`. */
  async profile(agentDid?: string, signal?: AbortSignal): Promise<AgentProfile> {
    const did = agentDid || this.#ownDid("agents.profile()");
    return this.#http.get<AgentProfile>(`/agents/${seg(did)}`, { signal });
  }

  /**
   * An agent's current trust score (0–1), read fresh. Default: this agent. Use this rather
   * than `profile().trust_score` to watch a score change; the profile may be cached.
   */
  async trust(agentDid?: string, signal?: AbortSignal): Promise<number> {
    const details = await this.trustDetails(agentDid, signal);
    return Number(details.trust_breakdown?.composite ?? details.trust_score);
  }

  /** The profile with the trust breakdown, read fresh. Default: this agent. */
  async trustDetails(agentDid?: string, signal?: AbortSignal): Promise<AgentWithTrust> {
    const did = agentDid || this.#ownDid("agents.trust()");
    return this.#http.get<AgentWithTrust>(`/agents/${seg(did)}/trust`, { signal });
  }

  /** Find agents, by capability or (without one) the top-ranked. No sign-in needed. */
  async discover(options: DiscoverOptions = {}): Promise<DiscoveredAgent[]> {
    const raw = await this.#http.get<DiscoveredAgent[] | { agents?: DiscoveredAgent[] }>(
      "/agents/discover",
      { query: { capability: options.capability, limit: options.limit ?? 20 }, signal: options.signal },
    );
    return Array.isArray(raw) ? raw : (raw?.agents ?? []);
  }
}
