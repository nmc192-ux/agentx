import { generateTraceId, logEvent } from "./logger";

// Production guard: never fall back to localhost in production builds.
const BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");

// Endpoints that must never be cached (real-time data)
const NO_STORE_PATHS = ["/feed", "/feed/activity", "/notifications", "/messages"];

async function get<T>(
  path: string,
  params?: Record<string, string | number>
): Promise<T> {
  const url = new URL(path, BASE);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)));
  }
  const noStore = NO_STORE_PATHS.some((p) => path.startsWith(p));
  const traceId = generateTraceId();
  logEvent("TASK_STARTED", { method: "GET", path }, traceId);
  const res = await fetch(
    url.toString(),
    noStore ? { cache: "no-store" } : { next: { revalidate: 60 } }
  );
  if (!res.ok) {
    logEvent("TASK_FAILED", { method: "GET", path, status: res.status }, traceId);
    throw new Error(`API error ${res.status}: ${path}`);
  }
  logEvent("TASK_COMPLETED", { method: "GET", path, status: res.status }, traceId);
  return res.json();
}

/** Like `get`, but always resolves to a plain array.
 *  Handles paginated wrappers, non-array objects, and null gracefully. */
async function getList(
  path: string,
  params?: Record<string, string | number>
): Promise<Record<string, unknown>[]> {
  const data = await get<unknown>(path, params);
  return Array.isArray(data) ? (data as Record<string, unknown>[]) : [];
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const traceId = generateTraceId();
  logEvent("TASK_STARTED", { method: "POST", path }, traceId);
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    logEvent("TASK_FAILED", { method: "POST", path, status: res.status }, traceId);
    throw new Error(`API error ${res.status}: ${path}`);
  }
  logEvent("TASK_COMPLETED", { method: "POST", path, status: res.status }, traceId);
  return res.json();
}

// ── Feed ────────────────────────────────────────────────────────────────────
// /posts returns { posts: [...], total, page, limit, has_more }
// /feed/global returns a plain array of old seeded data — use /posts instead
export const getFeed = async (limit = 20): Promise<Record<string, unknown>[]> => {
  const data = await get<unknown>("/posts", { limit });
  if (Array.isArray(data)) return data as Record<string, unknown>[];
  const d = data as Record<string, unknown>;
  return Array.isArray(d?.posts) ? (d.posts as Record<string, unknown>[]) : [];
};
export const getActivity   = (limit = 50)          => getList("/feed/activity", { limit });

// ── Agents ──────────────────────────────────────────────────────────────────
export const getAgents     = (limit = 20, offset = 0) => getList("/agents", { limit, offset });
export const getAgent      = (did: string)         => get<Record<string, unknown>>(`/agents/${did}`);
export const discoverAgents = (q?: string)         => getList("/agents/discover", q ? { q } : undefined);
export const getTopAgents  = ()                    => getList("/agents/top");
/**
 * Fetch the trust network rooted at this agent — adapted for the UI
 * consumer at /agents/{did}/trust.
 *
 * The naive `get('/agents/{did}/trust-network')` was wrong: backend's
 * `agent_id` route param is UUID-formatted (openapi: format=uuid), so
 * passing a DID 422'd silently and the consumer's `.catch(() => null)`
 * swallowed it — the page rendered "0 connected nodes" forever. Mirror
 * the DID→UUID resolution from getTrustGraph below, then enrich peers
 * (which arrive as UUID-only GraphEdge records) back to DID +
 * display_name so the CivilizationMap visualisation has labels instead
 * of opaque UUIDs.
 *
 * Returns the seed agent as the centre node plus one node per peer.
 * Promise.allSettled on the per-peer profile lookups so a single
 * failed enrichment doesn't sink the whole network. Caller-side shape
 * stays envelope-compatible (`{ nodes }`) with the existing page.
 */
export interface TrustNetworkNode {
  agent_did:    string;
  trust_score:  number;
  display_name: string | null;
}

export interface TrustNetworkPayload {
  seed_did:   string;
  peer_count: number;
  nodes:      TrustNetworkNode[];
}

export async function getTrustNetwork(
  did: string,
): Promise<TrustNetworkPayload> {
  // Step 1: resolve DID → UUID via the public /agents/{did} lookup. The
  // response also gives us the seed agent's display_name + trust_score
  // for the centre node.
  const seedAgent = await get<Record<string, unknown>>(
    `/agents/${did}`,
  ).catch(() => null);
  const seedUuid  = seedAgent?.agent_id as string | undefined;
  const seedName  = (seedAgent?.display_name as string | null) ?? null;
  const seedTrust = (seedAgent?.trust_score as number) ?? 1.0;
  if (!seedUuid) {
    return { seed_did: did, peer_count: 0, nodes: [] };
  }

  // Step 2: trust-network via UUID. Soft-fail (empty peers) so the page
  // can still render the centre node when the agent has no edges yet.
  const network = await get<Record<string, unknown>>(
    `/agents/${seedUuid}/trust-network`,
  ).catch(() => null);
  const peers      = (network?.peers as Record<string, unknown>[]) ?? [];
  const peerCount  = (network?.peer_count as number) ?? peers.length;

  // Step 3: enrich peer UUIDs → agent records (DID + display_name).
  // Parallel fetches with Promise.allSettled so a missing or 404'd peer
  // doesn't cascade. De-dup peer UUIDs first because a peer can appear
  // on multiple edges in unusual graphs.
  const peerUuids = Array.from(
    new Set(
      peers
        .map((p) => p.peer_agent_id as string | undefined)
        .filter((u): u is string => Boolean(u)),
    ),
  );
  const settled = await Promise.allSettled(
    peerUuids.map((uuid) =>
      get<Record<string, unknown>>(`/agents/${uuid}`),
    ),
  );
  const uuidToAgent = new Map<string, Record<string, unknown>>();
  settled.forEach((res, idx) => {
    if (res.status === "fulfilled" && res.value) {
      uuidToAgent.set(peerUuids[idx], res.value);
    }
  });

  const peerNodes: TrustNetworkNode[] = peers
    .map((p): TrustNetworkNode | null => {
      const peerUuid = p.peer_agent_id as string;
      const agent    = uuidToAgent.get(peerUuid);
      const peerDid  = (agent?.agent_did as string) ?? "";
      // No DID = enrichment failed; drop the node rather than render an
      // unclickable opaque-UUID label.
      if (!peerDid) return null;
      return {
        agent_did:    peerDid,
        trust_score:  (p.trust_weight as number) ?? 0,
        display_name: (agent?.display_name as string | null) ?? null,
      };
    })
    .filter((n): n is TrustNetworkNode => n !== null);

  return {
    seed_did:   did,
    peer_count: peerCount,
    nodes: [
      // Seed at the centre — always included so the visualisation has a
      // root even when peer_count === 0 (otherwise the page would render
      // an empty map for any agent without trust edges yet).
      {
        agent_did:    did,
        trust_score:  seedTrust,
        display_name: seedName,
      },
      ...peerNodes,
    ],
  };
}

// ── Trust Graph ──────────────────────────────────────────────────────────────
// Fetches /agents/{did}/trust-network and adapts the real backend shape:
//   { agent_id, peer_count, peers: GraphEdge[] }
//   GraphEdge: { agent_id (source), peer_agent_id (target), trust_weight }
// Returns { nodes, links } ready for AgentNetworkGraph.
export async function getTrustGraph(seedDid?: string): Promise<{
  nodes: { id: string; trust: number }[];
  links: { source: string; target: string }[];
}> {
  if (!seedDid) {
    const top = await getTopAgents();
    const first = Array.isArray(top) ? (top[0]?.agent_did as string) : undefined;
    if (!first) return { nodes: [], links: [] };
    seedDid = first;
  }

  // Resolve DID → UUID: backend trust-network route is parameterised as UUID, not DID
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const agent = await get<any>(`/agents/${seedDid}`);
  const uuid = agent?.agent_id as string | undefined;
  if (!uuid) return { nodes: [], links: [] };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const data = await get<any>(`/agents/${uuid}/trust-network`);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const peers: any[] = Array.isArray(data?.peers) ? data.peers : [];

  // Build node set: use UUID as node ID so all nodes + links share the same ID system
  // (links carry agent_id / peer_agent_id which are UUIDs; mixing DID here breaks D3 matching)
  const nodeMap = new Map<string, { id: string; trust: number }>();
  nodeMap.set(uuid, { id: uuid, trust: 1.0 });
  peers.forEach((p) => {
    const peerId = p.peer_agent_id as string;
    if (!nodeMap.has(peerId))
      nodeMap.set(peerId, { id: peerId, trust: (p.trust_weight as number) ?? 0.5 });
  });

  return {
    nodes: Array.from(nodeMap.values()),
    links: peers.map((p) => ({
      source: p.agent_id as string,
      target: p.peer_agent_id as string,
    })),
  };
}

// ── Communities ─────────────────────────────────────────────────────────────
export const getCommunities = (limit = 20)         => getList("/communities", { limit });
export const getCommunity   = (id: string)         => get<Record<string, unknown>>(`/communities/${id}`);
export const getThreads     = (communityId: string) => getList(`/communities/${communityId}/threads`);
export const getThread      = (threadId: string)   => get<Record<string, unknown>>(`/threads/${threadId}`);
export const getComments    = (threadId: string)   => getList(`/threads/${threadId}/comments`);
export const postComment    = (threadId: string, content: string) =>
  post<Record<string, unknown>>(`/threads/${threadId}/comments`, { content });

// ── Markets ─────────────────────────────────────────────────────────────────
export const getMarkets    = ()                    => getList("/markets/bounties");
export const getTasks      = (limit = 20)          => getList("/tasks", { limit });
export const getContracts  = ()                    => getList("/contracts");

// ── Notifications ────────────────────────────────────────────────────────────
export async function getNotifications(): Promise<Record<string, unknown>[]> {
  // Backend returns { notifications: [...], unread_count, total, ... } not a flat array
  const data = await get<Record<string, unknown>>("/notifications");
  return Array.isArray(data?.notifications)
    ? (data.notifications as Record<string, unknown>[])
    : [];
}

// ── Messages (A2A DM) ────────────────────────────────────────────────────────
// Real wrappers live further down: getAgentMessages(did, token?) hits
// GET /messages/{did} and sendMessage() posts to /messages/send. The
// previous getMessages() stub called a non-existent GET /messages
// endpoint and 404'd silently — removed to avoid dead-code drift.

// ── Ops helpers (used by client components) ──────────────────────────────────

/** Returns the raw /agents response including `total` count. */
export async function getAgentsWithMeta(
  limit = 30,
  offset = 0
): Promise<{ agents: Record<string, unknown>[]; total: number }> {
  const data = await get<Record<string, unknown>>("/agents", { limit, offset });
  const agents = Array.isArray(data)
    ? (data as Record<string, unknown>[])
    : Array.isArray((data as Record<string, unknown>)?.agents)
    ? ((data as Record<string, unknown>).agents as Record<string, unknown>[])
    : [];
  const total = (data as Record<string, unknown>)?.total as number ?? agents.length;
  return { agents, total };
}

/** Lightweight health probe — bypasses Next.js cache entirely. */
export async function getHealth(): Promise<{ status: string; version?: string }> {
  const url = `${BASE}/health`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

// ═══════════════════════════════════════════════════════════════════════════════
// Typed API methods — migrated from frontend/ (Step 3.1 consolidation)
// These methods accept an optional JWT token for authenticated requests.
// ═══════════════════════════════════════════════════════════════════════════════

import type {
  Agent,
  AgentCreate,
  AgentListResponse,
  AuthTokens,
  Capability,
  Collective,
  FeedResponse,
  LikeResponse,
  Message,
  NotificationList,
  Post,
  PostCreate,
  PostFilters,
  RecommendedTask,
  Service,
  SimilarPost,
} from "@/types";

/** Typed fetch helper with optional Bearer auth. */
async function request<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE" | "PUT",
  path: string,
  body?: unknown,
  token?: string,
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, err.detail ?? "Request failed", err);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function loginWithDid(
  agentDid: string,
  password?: string,
): Promise<AuthTokens> {
  const form = new URLSearchParams();
  form.set("username", agentDid);
  form.set("password", password ?? "");
  form.set("grant_type", "password");
  const res = await fetch(`${BASE}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(res.status, err.detail ?? "Login failed", err);
  }
  return res.json();
}

export async function refreshToken(rt: string): Promise<AuthTokens> {
  return request("POST", "/auth/refresh", { refresh_token: rt });
}

// ── Typed Agent methods ───────────────────────────────────────────────────────

export async function getAgentTyped(did: string, token?: string): Promise<Agent> {
  return request("GET", `/agents/${encodeURIComponent(did)}`, undefined, token);
}

export async function listAgents(
  params: { limit?: number; offset?: number; role?: string } = {},
  token?: string,
): Promise<Agent[]> {
  const qs = new URLSearchParams();
  if (params.limit  !== undefined) qs.set("limit",  String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.role)                  qs.set("role",   params.role);
  return request("GET", `/agents?${qs}`, undefined, token);
}

export async function createAgent(data: AgentCreate, token?: string): Promise<Agent> {
  return request("POST", "/agents", data, token);
}

export async function updateAgent(
  did: string,
  data: Partial<Pick<Agent, "display_name" | "bio" | "avatar_url">>,
  token: string,
): Promise<Agent> {
  return request("PATCH", `/agents/${encodeURIComponent(did)}`, data, token);
}

export async function getAgentTrustScore(
  did: string,
  token: string,
): Promise<{ agent_did: string; trust_score: number }> {
  return request("GET", `/agents/${encodeURIComponent(did)}/trust`, undefined, token);
}

export async function getAgentCapabilities(
  did: string,
  token?: string,
): Promise<Capability[]> {
  // Token is optional — capability listings are public on the backend
  // (mirrors /agents and /posts), so anonymous profile visitors can see
  // what an agent can do. Authenticated reads still get any private
  // capabilities the viewer has visibility into.
  return request("GET", `/agents/${encodeURIComponent(did)}/capabilities`, undefined, token);
}

/**
 * Peer-endorse another agent's capability. Returns the post-endorse
 * server state so the caller can reconcile the chip in place
 * (verified flag flips once verified_by_count crosses the threshold).
 *
 * Backed by POST /agents/{did}/capabilities/{cap_id}/verify. Capability
 * endorsement is AgentX's agent-native trust primitive — there is no
 * Twitter / Bluesky equivalent. Each peer endorsement increments
 * verified_by_count; once the count crosses the backend threshold
 * (currently 2) the capability flips to VERIFIED system-wide and the
 * BadgeCheck appears on the chip everywhere it's rendered.
 *
 * Constraints (enforced server-side; the UI mirrors them but the
 * backend is the source of truth):
 *   - Caller must be authenticated (token required, not optional)
 *   - Caller cannot endorse their own capability (422)
 *   - Target agent must hold the capability (404 otherwise)
 *
 * `endorser_did` is required by the backend schema; we always pass
 * the caller's DID since the server cross-checks against the bearer
 * token's claims.
 */
export async function verifyAgentCapability(
  agentDid:     string,
  capabilityId: string,
  endorserDid:  string,
  token:        string,
  notes?:       string,
): Promise<{
  capability_id:     string;
  agent_did:         string;
  verified:          boolean;
  verified_by_count: number;
  endorsed_by:       string;
}> {
  return request(
    "POST",
    `/agents/${encodeURIComponent(agentDid)}/capabilities/${encodeURIComponent(capabilityId)}/verify`,
    { endorser_did: endorserDid, notes },
    token,
  );
}

/**
 * Fetch the services a single agent offers. Returns a `Service[]` direct
 * from the backend (no envelope on this endpoint, unlike /services/search
 * which is forward-compat envelope-able). Used by the agent profile to
 * render the services chip row alongside capabilities.
 *
 * Token optional — services are public.
 */
export async function getAgentServices(
  did: string,
  token?: string,
): Promise<Service[]> {
  return request(
    "GET",
    `/services/agent/${encodeURIComponent(did)}`,
    undefined,
    token,
  );
}

/**
 * Fetch all messages where this agent is sender OR receiver. The /messages
 * inbox uses this with the signed-in agent's own DID, then groups
 * client-side by counterparty to render conversations.
 *
 * Backend returns `MessageResponse[]` directly (no envelope). The shape
 * matches the `Message` type — sender_agent_did / receiver_agent_did /
 * message / metadata / created_at.
 *
 * Token recommended — DMs aren't public.
 */
export async function getAgentMessages(
  did: string,
  token?: string,
): Promise<Message[]> {
  return request(
    "GET",
    `/messages/${encodeURIComponent(did)}`,
    undefined,
    token,
  );
}

/**
 * Send an A2A direct message. The backend records `sender_agent_did` →
 * `receiver_agent_did` with the body text plus optional protocol metadata
 * (used for service-fulfillment requests, system events, etc.).
 *
 * Returns the persisted MessageResponse so callers can optimistically
 * append it to the local thread without a refetch round-trip.
 */
export async function sendMessage(
  senderDid: string,
  receiverDid: string,
  message: string,
  token: string,
  metadata?: Record<string, unknown>,
): Promise<Message> {
  return request(
    "POST",
    "/messages/send",
    {
      sender_agent_did:   senderDid,
      receiver_agent_did: receiverDid,
      message,
      metadata: metadata ?? null,
    },
    token,
  );
}

export async function getRecommendedTasks(
  did: string,
  limit = 5,
  token: string,
): Promise<RecommendedTask[]> {
  return request(
    "GET",
    `/agents/${encodeURIComponent(did)}/recommended-tasks?limit=${limit}`,
    undefined,
    token,
  );
}

// ── Typed Post methods ────────────────────────────────────────────────────────

export async function listPosts(
  filters: PostFilters = {},
  token?: string,
): Promise<Post[]> {
  const qs = new URLSearchParams();
  if (filters.post_type)  qs.set("post_type",  filters.post_type);
  if (filters.status)     qs.set("status",     filters.status);
  if (filters.author_did) qs.set("author_did", filters.author_did);
  if (filters.tag)        qs.set("tag",        filters.tag);
  if (filters.limit  !== undefined) qs.set("limit",  String(filters.limit));
  if (filters.offset !== undefined) qs.set("offset", String(filters.offset));
  // Backend returns { posts: Post[], total, page, limit, has_more } — unwrap it
  const data = await request<{ posts: Post[] } | Post[]>("GET", `/posts?${qs}`, undefined, token);
  if (Array.isArray(data)) return data;
  return (data as { posts: Post[] }).posts ?? [];
}

export async function getPost(postId: string, token?: string): Promise<Post> {
  return request("GET", `/posts/${postId}`, undefined, token);
}

export async function createPost(data: PostCreate, token: string): Promise<Post> {
  return request("POST", "/posts", data, token);
}

export async function getSimilarPosts(
  postId: string,
  limit = 5,
  token?: string,
): Promise<SimilarPost[]> {
  return request("GET", `/posts/similar?post_id=${postId}&limit=${limit}`, undefined, token);
}

export async function getGlobalFeed(
  params: { page?: number; limit?: number; post_type?: string } = {},
  token?: string,
): Promise<FeedResponse> {
  const qs = new URLSearchParams();
  if (params.page)      qs.set("page",      String(params.page));
  if (params.limit)     qs.set("limit",     String(params.limit));
  if (params.post_type) qs.set("post_type", params.post_type);
  return request("GET", `/posts/global?${qs}`, undefined, token);
}

export async function getPostReplies(
  postId: string,
  params: { page?: number; limit?: number } = {},
  token?: string,
): Promise<FeedResponse> {
  const qs = new URLSearchParams();
  if (params.page)  qs.set("page",  String(params.page));
  if (params.limit) qs.set("limit", String(params.limit));
  return request("GET", `/posts/${postId}/replies?${qs}`, undefined, token);
}

// ── Social graph ─────────────────────────────────────────────────────────────

export async function blockAgent(targetDid: string, token: string): Promise<void> {
  return request("POST", "/blocks", { target_did: targetDid }, token);
}

export async function unblockAgent(targetDid: string, token: string): Promise<void> {
  return request("DELETE", `/blocks/${encodeURIComponent(targetDid)}`, undefined, token);
}

export async function followAgent(did: string, token: string): Promise<void> {
  return request("POST", `/agents/${encodeURIComponent(did)}/follow`, undefined, token);
}

export async function unfollowAgent(did: string, token: string): Promise<void> {
  return request("DELETE", `/agents/${encodeURIComponent(did)}/follow`, undefined, token);
}

export async function getFollowers(
  did: string,
  params: { page?: number; limit?: number } = {},
  token?: string,
): Promise<AgentListResponse> {
  const qs = new URLSearchParams();
  if (params.page)  qs.set("page",  String(params.page));
  if (params.limit) qs.set("limit", String(params.limit));
  return request("GET", `/agents/${encodeURIComponent(did)}/followers?${qs}`, undefined, token);
}

export async function getFollowing(
  did: string,
  params: { page?: number; limit?: number } = {},
  token?: string,
): Promise<AgentListResponse> {
  const qs = new URLSearchParams();
  if (params.page)  qs.set("page",  String(params.page));
  if (params.limit) qs.set("limit", String(params.limit));
  return request("GET", `/agents/${encodeURIComponent(did)}/following?${qs}`, undefined, token);
}

export async function likePost(postId: string, token: string): Promise<LikeResponse> {
  return request("POST", `/posts/${postId}/like`, undefined, token);
}

// ── Typed Capability methods ──────────────────────────────────────────────────

export async function listCapabilities(token?: string): Promise<Capability[]> {
  return request("GET", "/capabilities", undefined, token);
}

// ── Typed Collective methods ──────────────────────────────────────────────────

export async function listCollectives(token?: string): Promise<Collective[]> {
  const data = await request<{ collectives: Collective[] } | Collective[]>("GET", "/collectives", undefined, token);
  return Array.isArray(data) ? data : (data as { collectives: Collective[] }).collectives ?? [];
}

export async function getCollective(id: string, token?: string): Promise<Collective> {
  return request("GET", `/collectives/${id}`, undefined, token);
}

// ── Typed Notification methods ────────────────────────────────────────────────

export async function getNotificationsTyped(
  params: { page?: number; limit?: number; unread_only?: boolean } = {},
  token?: string,
): Promise<NotificationList> {
  const qs = new URLSearchParams();
  if (params.page)        qs.set("page",       String(params.page));
  if (params.limit)       qs.set("limit",      String(params.limit));
  if (params.unread_only) qs.set("unread_only", "true");
  return request("GET", `/notifications?${qs}`, undefined, token);
}

export async function markAllNotifsRead(token: string): Promise<void> {
  return request("POST", "/notifications/read", undefined, token);
}

export async function markNotifRead(notifId: string, token: string): Promise<void> {
  return request("PATCH", `/notifications/${notifId}`, undefined, token);
}

// ── Economy ───────────────────────────────────────────────────────────────────

// ── Phase 1 Enhanced Social Layer ────────────────────────────────────────────

import type {
  CanvasNode,
  Channel,
  Room,
  RoomActivity,
  RoomParticipant,
  Artifact,
  DebateDetail,
  DebateRound,
  DebateStatement,
  ConsensusSnapshot as ConsensusSnapshotType,
  ConstellationGraph,
  PulseData,
  TrendingPost,
} from "@/types";

// Channels
export async function listChannels(communityId: string, token?: string): Promise<Channel[]> {
  return request("GET", `/communities/${communityId}/channels`, undefined, token);
}

export async function getChannelFeed(channelId: string, limit = 50, token?: string): Promise<Post[]> {
  const data = await request<Post[] | { posts: Post[] }>("GET", `/channels/${channelId}/feed?limit=${limit}`, undefined, token);
  return Array.isArray(data) ? data : (data as { posts: Post[] }).posts ?? [];
}

// Search
export async function searchAll(q: string, type = "all", limit = 20): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>("/search", { q, type, limit });
}

// Rooms
export async function listRooms(params: { community_id?: string; status?: string; limit?: number } = {}, token?: string): Promise<Room[]> {
  const qs = new URLSearchParams();
  if (params.community_id) qs.set("community_id", params.community_id);
  if (params.status)       qs.set("status", params.status);
  if (params.limit)        qs.set("limit", String(params.limit));
  return request("GET", `/rooms?${qs}`, undefined, token);
}

export async function getRoom(roomId: string, token?: string): Promise<Room> {
  return request("GET", `/rooms/${roomId}`, undefined, token);
}

export async function createRoom(data: { name: string; description?: string; community_id?: string; room_type?: string; max_participants?: number }, token: string): Promise<Room> {
  return request("POST", "/rooms", data, token);
}

export async function joinRoom(roomId: string, token: string): Promise<RoomParticipant> {
  return request("POST", `/rooms/${roomId}/join`, undefined, token);
}

export async function getRoomParticipants(roomId: string, token?: string): Promise<RoomParticipant[]> {
  return request("GET", `/rooms/${roomId}/participants`, undefined, token);
}

export async function addArtifact(roomId: string, data: { artifact_type?: string; title?: string; content?: Record<string, unknown> }, token: string): Promise<Artifact> {
  return request("POST", `/rooms/${roomId}/artifacts`, data, token);
}

export async function listArtifacts(roomId: string, limit = 50, token?: string): Promise<Artifact[]> {
  return request("GET", `/rooms/${roomId}/artifacts?limit=${limit}`, undefined, token);
}

// Canvas
export async function getCanvasNodes(roomId: string, token?: string): Promise<CanvasNode[]> {
  return request("GET", `/rooms/${roomId}/canvas`, undefined, token);
}

export async function createCanvasNode(roomId: string, data: { artifact_id?: string; node_type?: string; label?: string; x?: number; y?: number; width?: number; height?: number; style?: Record<string, unknown> }, token: string): Promise<CanvasNode> {
  return request("POST", `/rooms/${roomId}/canvas`, data, token);
}

export async function updateCanvasNode(roomId: string, nodeId: string, data: { x?: number; y?: number; width?: number; height?: number; label?: string; style?: Record<string, unknown> }, token: string): Promise<CanvasNode> {
  return request("PATCH", `/rooms/${roomId}/canvas/${nodeId}`, data, token);
}

export async function deleteCanvasNode(roomId: string, nodeId: string, token: string): Promise<void> {
  return request("DELETE", `/rooms/${roomId}/canvas/${nodeId}`, undefined, token);
}

export async function batchMoveCanvasNodes(roomId: string, moves: { node_id: string; x: number; y: number }[], token: string): Promise<CanvasNode[]> {
  return request("POST", `/rooms/${roomId}/canvas/batch-move`, { moves }, token);
}

// Room activity
export async function getRoomActivity(roomId: string, limit = 50, token?: string): Promise<RoomActivity[]> {
  return request("GET", `/rooms/${roomId}/activity?limit=${limit}`, undefined, token);
}

// Leave room
export async function leaveRoom(roomId: string, token: string): Promise<{ status: string }> {
  return request("POST", `/rooms/${roomId}/leave`, undefined, token);
}

// Close room
export async function closeRoom(roomId: string, token: string): Promise<Room> {
  return request("POST", `/rooms/${roomId}/close`, undefined, token);
}

// Consensus / Debate
export async function getDebate(proposalId: string, token?: string): Promise<DebateDetail> {
  return request("GET", `/governance/proposals/${proposalId}/debate`, undefined, token);
}

export async function openDebate(proposalId: string, token: string): Promise<DebateRound> {
  return request("POST", `/governance/proposals/${proposalId}/debate`, { proposal_id: proposalId }, token);
}

export async function addDebateStatement(roundId: string, data: { position: string; content: string; evidence_refs?: Record<string, unknown>[] }, token: string): Promise<DebateStatement> {
  return request("POST", `/governance/debate/${roundId}/statements`, data, token);
}

export async function computeConsensus(proposalId: string, token: string): Promise<ConsensusSnapshotType> {
  return request("POST", `/governance/proposals/${proposalId}/consensus`, undefined, token);
}

export async function advanceDebate(proposalId: string, token: string): Promise<DebateRound> {
  return request("POST", `/governance/proposals/${proposalId}/advance`, undefined, token);
}

export async function getConsensusHistory(proposalId: string, token?: string): Promise<ConsensusSnapshotType[]> {
  return request("GET", `/governance/proposals/${proposalId}/consensus/history`, undefined, token);
}

// Graph
export async function getConstellation(
  center: string,
  params: { hops?: number; min_trust?: number; capability?: string; community_id?: string; include_rooms?: boolean } = {},
): Promise<ConstellationGraph> {
  const qs = new URLSearchParams({ center });
  if (params.hops !== undefined)          qs.set("hops", String(params.hops));
  if (params.min_trust !== undefined)     qs.set("min_trust", String(params.min_trust));
  if (params.capability)                  qs.set("capability", params.capability);
  if (params.community_id)               qs.set("community_id", params.community_id);
  if (params.include_rooms !== undefined) qs.set("include_rooms", String(params.include_rooms));
  return get<ConstellationGraph>(`/graph/constellation?${qs}`);
}

// Pulse
export async function getPulse(): Promise<PulseData> {
  return get<PulseData>("/pulse");
}

export async function getTrending(limit = 10): Promise<TrendingPost[]> {
  return get<TrendingPost[]>("/pulse/trending", { limit });
}

// ── Economy ───────────────────────────────────────────────────────────────────
export const getEconomyMetrics = () => get<Record<string, unknown>>("/economy/metrics");
export const getTreasury        = () => get<Record<string, unknown>>("/economy/treasury");

// ── Governance ────────────────────────────────────────────────────────────────

export interface Proposal {
  proposal_id: string;
  title: string;
  description: string;
  proposer_did: string;
  voting_ends_at: string;
  yes_votes: number;
  no_votes: number;
  abstain_votes: number;
  status: string;
  created_at: string;
}

export const getProposals = (): Promise<Proposal[]> =>
  get<Proposal[]>("/governance/proposals").catch(() => []);

export const getGovernanceResults = (): Promise<Proposal[]> =>
  get<Proposal[]>("/governance/results").catch(() => []);
export async function castVote(proposalId: string, vote: "yes" | "no" | "abstain", token: string): Promise<void> {
  await request("POST", "/governance/vote", { proposal_id: proposalId, vote }, token);
}
export async function createProposal(title: string, description: string, votingDays: number, token: string): Promise<Proposal> {
  return request<Proposal>("POST", "/governance/proposals", { title, description, voting_days: votingDays }, token);
}
