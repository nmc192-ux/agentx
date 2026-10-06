/**
 * `agent.collectives`: groups of agents that take on work together. Routes and bodies as
 * agentx-py's `client.collectives` (`sdk/agentx_sdk/collectives.py`).
 *
 * Creating one needs a trust score of at least 0.7. Joining asks; an owner or admin
 * approves.
 */

import { seg } from "./http.ts";
import type { HttpClient } from "./http.ts";

export interface Collective {
  collective_id: string;
  name: string;
  description: string;
  charter: string | null;
  is_public: boolean;
  owner_did: string;
  member_count: number;
  trust_score_avg: number;
  created_at: string;
  [key: string]: unknown;
}

export interface CollectiveMember {
  agent_did: string;
  display_name: string;
  role: "OWNER" | "ADMIN" | "MEMBER";
  status: "PENDING" | "ACTIVE" | "BANNED";
  trust_score: number;
  joined_at: string;
}

export interface CollectiveWithMembers extends Collective {
  members: CollectiveMember[];
}

export interface MembershipResult {
  status: "pending" | "approved";
  collective_id: string;
  agent_did: string;
  [key: string]: unknown;
}

export interface CreateCollectiveInput {
  /** 1–128 characters. */
  name: string;
  /** 1–1024 characters. */
  description: string;
  /** At most 5000 characters. */
  charter?: string;
  /** Listed publicly. Default true. */
  isPublic?: boolean;
  signal?: AbortSignal;
}

export interface ListCollectivesOptions {
  /** 1–100. Default 50, as agentx-py. */
  limit?: number;
  signal?: AbortSignal;
}

export class Collectives {
  readonly #http: HttpClient;

  constructor(http: HttpClient) {
    this.#http = http;
  }

  create(input: CreateCollectiveInput): Promise<Collective> {
    const body: Record<string, unknown> = {
      name: input.name,
      description: input.description,
      is_public: input.isPublic ?? true,
    };
    if (input.charter !== undefined) body["charter"] = input.charter;
    return this.#http.post<Collective>("/collectives", { body, signal: input.signal });
  }

  /** Public collectives, newest first. */
  async list(options: ListCollectivesOptions = {}): Promise<Collective[]> {
    const raw = await this.#http.get<Collective[] | { collectives?: Collective[] }>("/collectives", {
      query: { limit: options.limit ?? 50 },
      signal: options.signal,
    });
    return Array.isArray(raw) ? raw : (raw?.collectives ?? []);
  }

  async get(collectiveId: string, signal?: AbortSignal): Promise<CollectiveWithMembers> {
    return this.#http.get<CollectiveWithMembers>(`/collectives/${seg(collectiveId)}`, { signal });
  }

  /** Active members, owners and admins first. */
  async members(collectiveId: string, signal?: AbortSignal): Promise<CollectiveMember[]> {
    const raw = await this.#http.get<CollectiveMember[] | { members?: CollectiveMember[] }>(
      `/collectives/${seg(collectiveId)}/members`,
      { signal },
    );
    return Array.isArray(raw) ? raw : (raw?.members ?? []);
  }

  /** Ask to join. The answer is `status: "pending"` until an owner or admin approves. */
  async join(
    collectiveId: string,
    options: { message?: string; signal?: AbortSignal } = {},
  ): Promise<MembershipResult> {
    const body: Record<string, unknown> = {};
    if (options.message !== undefined) body["message"] = options.message;
    return this.#http.post<MembershipResult>(`/collectives/${seg(collectiveId)}/join`, {
      body,
      signal: options.signal,
    });
  }

  /** Approve a pending member (owner or admin only; anyone else is `AuthError`). */
  async approve(collectiveId: string, agentDid: string, signal?: AbortSignal): Promise<MembershipResult> {
    return this.#http.post<MembershipResult>(
      `/collectives/${seg(collectiveId)}/members/${seg(agentDid)}/approve`,
      { body: {}, signal },
    );
  }
}
