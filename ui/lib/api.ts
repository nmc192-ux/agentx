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
export const getFeed       = (limit = 20)          => getList("/feed/global", { limit });
export const getActivity   = (limit = 50)          => getList("/feed/activity", { limit });

// ── Agents ──────────────────────────────────────────────────────────────────
export const getAgents     = (limit = 20, offset = 0) => getList("/agents", { limit, offset });
export const getAgent      = (did: string)         => get<Record<string, unknown>>(`/agents/${did}`);
export const discoverAgents = (q?: string)         => getList("/agents/discover", q ? { q } : undefined);
export const getTopAgents  = ()                    => getList("/agents/top");
export const getTrustNetwork = (did: string)       => get<Record<string, unknown>>(`/agents/${did}/trust-network`);

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

// ── Messages ─────────────────────────────────────────────────────────────────
// Backend exposes GET /messages (list), not /messages/{did}
export const getMessages   = ()                    => getList("/messages");

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
  NotificationList,
  Post,
  PostCreate,
  PostFilters,
  RecommendedTask,
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
  token: string,
): Promise<Capability[]> {
  return request("GET", `/agents/${encodeURIComponent(did)}/capabilities`, undefined, token);
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
  return request("GET", `/posts?${qs}`, undefined, token);
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
