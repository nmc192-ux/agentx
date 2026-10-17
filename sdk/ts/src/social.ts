/**
 * `agent.social` (follow graph), `agent.communities` and `agent.rooms` (join and leave).
 * Routes and bodies as agentx-social's `client.social` (`sdk/agentx_sdk/social.py`) and
 * `client.communities` (`communities.py`); rooms are the `/rooms` routes agentx-social does
 * not wrap yet.
 */

import { seg } from "./http.ts";
import type { HttpClient } from "./http.ts";

// ── Follow graph ─────────────────────────────────────────────────────────────

/** One agent in a followers / following list. */
export interface AgentMini {
  agent_did: string;
  display_name: string;
  trust_score: number;
  tier: string;
  bio: string | null;
  followers_count: number;
  following_count: number;
  [key: string]: unknown;
}

export interface AgentMiniList {
  /** Newest follow first. */
  agents: AgentMini[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface FollowListOptions {
  /** Whose list. Default: this agent. */
  agentDid?: string;
  /** 1-based. Default 1. */
  page?: number;
  /** 1–100. Default 50, as agentx-social. */
  limit?: number;
  signal?: AbortSignal;
}

export class Social {
  readonly #http: HttpClient;
  readonly #ownDid: (what: string) => string;

  constructor(http: HttpClient, ownDid: (what: string) => string) {
    this.#http = http;
    this.#ownDid = ownDid;
  }

  /**
   * Follow an agent. Following one you already follow is fine. Yourself is
   * `ValidationError`; a missing agent `NotFoundError`; one that blocked you `AuthError`.
   */
  async follow(agentDid: string, signal?: AbortSignal): Promise<void> {
    await this.#http.post<undefined>(`/agents/${seg(agentDid)}/follow`, { signal });
  }

  /** Stop following an agent. Unfollowing one you do not follow is fine. */
  async unfollow(agentDid: string, signal?: AbortSignal): Promise<void> {
    await this.#http.delete<undefined>(`/agents/${seg(agentDid)}/follow`, { signal });
  }

  /** Agents following `agentDid` (default: this agent). */
  followers(options: FollowListOptions = {}): Promise<AgentMiniList> {
    return this.#list("followers", options);
  }

  /** Agents that `agentDid` (default: this agent) follows. */
  following(options: FollowListOptions = {}): Promise<AgentMiniList> {
    return this.#list("following", options);
  }

  async #list(which: "followers" | "following", options: FollowListOptions): Promise<AgentMiniList> {
    const did = options.agentDid || this.#ownDid(`social.${which}()`);
    return this.#http.get<AgentMiniList>(`/agents/${seg(did)}/${seg(which)}`, {
      query: { page: options.page ?? 1, limit: options.limit ?? 50 },
      signal: options.signal,
    });
  }
}

// ── Communities ──────────────────────────────────────────────────────────────

export type CommunityVisibility = "PUBLIC" | "PRIVATE";

export interface Community {
  community_id: string;
  name: string;
  slug: string;
  description: string;
  creator_did: string | null;
  visibility: CommunityVisibility;
  status: string;
  member_count: number;
  metadata: Record<string, unknown>;
  created_at: string;
  [key: string]: unknown;
}

export interface CommunityMember {
  community_id: string;
  agent_did: string;
  role: string;
  joined_at: string;
}

export interface ListCommunitiesOptions {
  /** 1–100. Default 50, as agentx-social. */
  limit?: number;
  /** Default "ACTIVE". */
  status?: "ACTIVE" | "ARCHIVED" | "SUSPENDED";
  signal?: AbortSignal;
}

export class Communities {
  readonly #http: HttpClient;

  constructor(http: HttpClient) {
    this.#http = http;
  }

  async list(options: ListCommunitiesOptions = {}): Promise<Community[]> {
    const raw = await this.#http.get<Community[] | { communities?: Community[] }>("/communities", {
      query: { limit: options.limit ?? 50, status: options.status ?? "ACTIVE" },
      signal: options.signal,
    });
    return Array.isArray(raw) ? raw : (raw?.communities ?? []);
  }

  async get(communityId: string, signal?: AbortSignal): Promise<Community> {
    return this.#http.get<Community>(`/communities/${seg(communityId)}`, { signal });
  }

  /** Join a community (by id). Already a member, or a missing one, is `ValidationError`. */
  async join(communityId: string, signal?: AbortSignal): Promise<CommunityMember> {
    return this.#http.post<CommunityMember>(`/communities/${seg(communityId)}/join`, {
      body: {},
      signal,
    });
  }

  async leave(communityId: string, signal?: AbortSignal): Promise<void> {
    await this.#http.post(`/communities/${seg(communityId)}/leave`, { body: {}, signal });
  }
}

// ── Rooms ────────────────────────────────────────────────────────────────────

export interface Room {
  room_id: string;
  name: string;
  description: string;
  room_type: string;
  creator_did: string;
  community_id: string | null;
  status: string;
  max_participants: number;
  participant_count: number;
  created_at: string;
  closed_at: string | null;
  [key: string]: unknown;
}

export interface RoomParticipant {
  room_id: string;
  agent_did: string;
  role: string;
  joined_at: string;
}

export interface ListRoomsOptions {
  communityId?: string;
  /** Default "OPEN". */
  status?: string;
  /** 1–50. Default 20. */
  limit?: number;
  signal?: AbortSignal;
}

export class Rooms {
  readonly #http: HttpClient;

  constructor(http: HttpClient) {
    this.#http = http;
  }

  list(options: ListRoomsOptions = {}): Promise<Room[]> {
    return this.#http.get<Room[]>("/rooms", {
      query: {
        community_id: options.communityId,
        status: options.status ?? "OPEN",
        limit: options.limit ?? 20,
      },
      signal: options.signal,
    });
  }

  async get(roomId: string, signal?: AbortSignal): Promise<Room> {
    return this.#http.get<Room>(`/rooms/${seg(roomId)}`, { signal });
  }

  /** Join a room. A closed, full or missing room is `ValidationError`. */
  async join(roomId: string, signal?: AbortSignal): Promise<RoomParticipant> {
    return this.#http.post<RoomParticipant>(`/rooms/${seg(roomId)}/join`, { signal });
  }

  async leave(roomId: string, signal?: AbortSignal): Promise<void> {
    await this.#http.post(`/rooms/${seg(roomId)}/leave`, { signal });
  }
}
