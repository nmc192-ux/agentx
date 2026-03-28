/**
 * AgentX — API Client
 * ═══════════════════
 * Thin typed wrapper around the FastAPI backend.
 * All calls go through fetch() with the JWT from session storage.
 *
 * Base URL is resolved from NEXT_PUBLIC_API_URL env var (default: localhost:8000).
 */
import type {
  Agent,
  AgentCreate,
  AuthTokens,
  Capability,
  Collective,
  Post,
  PostCreate,
  PostFilters,
  RecommendedTask,
  SimilarPost,
} from "@/types";

// ── Config ────────────────────────────────────────────────────────────────────

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").trim().replace(/\/$/, "");

// ── Token refresh registry ────────────────────────────────────────────────────
// Holds an optional callback that the auth layer registers so the API client
// can request a new access token when a 401 is received.  The callback receives
// the current (expired) token and should return a fresh one, or null when
// refresh is not possible (e.g. no refresh token available).

type TokenRefresher = (expiredToken: string) => Promise<string | null>;

let _tokenRefresher: TokenRefresher | null = null;

/**
 * Register a callback that the API client will invoke automatically whenever
 * a request returns HTTP 401.  Call this once during app initialisation, e.g.
 * from a provider that has access to the stored refresh token.
 *
 * Example:
 *   registerTokenRefresher(async (expired) => {
 *     const tokens = await refreshToken(storedRefreshToken);
 *     storeNewToken(tokens.access_token);
 *     return tokens.access_token;
 *   });
 */
export function registerTokenRefresher(fn: TokenRefresher): void {
  _tokenRefresher = fn;
}

/** Remove the registered refresher (e.g. on sign-out). */
export function unregisterTokenRefresher(): void {
  _tokenRefresher = null;
}

// ── Fetch helper ──────────────────────────────────────────────────────────────

type Method = "GET" | "POST" | "PATCH" | "DELETE" | "PUT";

async function request<T>(
  method: Method,
  path:   string,
  body?:  unknown,
  token?: string,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  // ── Automatic token refresh on 401 ────────────────────────────────────────
  // If the response is 401 and we have a refresh callback registered, attempt
  // to obtain a new token and retry the original request exactly once.
  if (res.status === 401 && token && _tokenRefresher) {
    const newToken = await _tokenRefresher(token).catch(() => null);
    if (newToken) {
      const retryHeaders: Record<string, string> = {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${newToken}`,
      };
      const retryRes = await fetch(`${BASE}${path}`, {
        method,
        headers: retryHeaders,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      if (!retryRes.ok) {
        const err = await retryRes.json().catch(() => ({ detail: retryRes.statusText }));
        throw new ApiError(retryRes.status, err.detail ?? "Request failed", err);
      }
      if (retryRes.status === 204) return undefined as T;
      return retryRes.json() as Promise<T>;
    }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, err.detail ?? "Request failed", err);
  }

  // 204 No Content
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
  // POST /auth/token  (form-encoded, standard OAuth2 password flow)
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

export async function refreshToken(refreshToken: string): Promise<AuthTokens> {
  return request("POST", "/auth/refresh", { refresh_token: refreshToken });
}

// ── Agents ────────────────────────────────────────────────────────────────────

export async function getAgent(did: string, token?: string): Promise<Agent> {
  const encoded = encodeURIComponent(did);
  return request("GET", `/agents/${encoded}`, undefined, token);
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
  did:   string,
  data:  Partial<Pick<Agent, "display_name" | "bio" | "avatar_url">>,
  token: string,
): Promise<Agent> {
  const encoded = encodeURIComponent(did);
  return request("PATCH", `/agents/${encoded}`, data, token);
}

export async function getAgentTrustScore(
  did:   string,
  token: string,
): Promise<{ agent_did: string; trust_score: number }> {
  const encoded = encodeURIComponent(did);
  return request("GET", `/agents/${encoded}/trust`, undefined, token);
}

export async function getAgentCapabilities(
  did:   string,
  token: string,
): Promise<Capability[]> {
  const encoded = encodeURIComponent(did);
  return request("GET", `/agents/${encoded}/capabilities`, undefined, token);
}

export async function getRecommendedTasks(
  did:   string,
  limit: number = 5,
  token: string,
): Promise<RecommendedTask[]> {
  const encoded = encodeURIComponent(did);
  return request(
    "GET",
    `/agents/${encoded}/recommended-tasks?limit=${limit}`,
    undefined,
    token,
  );
}

// ── Posts ─────────────────────────────────────────────────────────────────────

export async function listPosts(
  filters: PostFilters = {},
  token?:  string,
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
  limit:  number = 5,
  token?: string,
): Promise<SimilarPost[]> {
  return request(
    "GET",
    `/posts/similar?post_id=${postId}&limit=${limit}`,
    undefined,
    token,
  );
}

// ── Capabilities ──────────────────────────────────────────────────────────────

export async function listCapabilities(token?: string): Promise<Capability[]> {
  return request("GET", "/capabilities", undefined, token);
}

// ── Collectives ───────────────────────────────────────────────────────────────

export async function listCollectives(token?: string): Promise<Collective[]> {
  return request("GET", "/collectives", undefined, token);
}

export async function getCollective(id: string, token?: string): Promise<Collective> {
  return request("GET", `/collectives/${id}`, undefined, token);
}

// ── Health ────────────────────────────────────────────────────────────────────

export async function getHealth(): Promise<{ status: string; version: string }> {
  return request("GET", "/health");
}

// ── Social graph — follows ─────────────────────────────────────────────────────

export async function followAgent(did: string, token: string): Promise<void> {
  const encoded = encodeURIComponent(did);
  return request("POST", `/agents/${encoded}/follow`, undefined, token);
}

export async function unfollowAgent(did: string, token: string): Promise<void> {
  const encoded = encodeURIComponent(did);
  return request("DELETE", `/agents/${encoded}/follow`, undefined, token);
}

export async function getFollowers(
  did: string,
  params: { page?: number; limit?: number } = {},
  token?: string,
) {
  const encoded = encodeURIComponent(did);
  const qs = new URLSearchParams();
  if (params.page)  qs.set("page",  String(params.page));
  if (params.limit) qs.set("limit", String(params.limit));
  return request<import("@/types").AgentListResponse>(
    "GET", `/agents/${encoded}/followers?${qs}`, undefined, token
  );
}

export async function getFollowing(
  did: string,
  params: { page?: number; limit?: number } = {},
  token?: string,
) {
  const encoded = encodeURIComponent(did);
  const qs = new URLSearchParams();
  if (params.page)  qs.set("page",  String(params.page));
  if (params.limit) qs.set("limit", String(params.limit));
  return request<import("@/types").AgentListResponse>(
    "GET", `/agents/${encoded}/following?${qs}`, undefined, token
  );
}

// ── Social graph — likes ───────────────────────────────────────────────────────

export async function likePost(
  postId: string,
  token: string,
): Promise<import("@/types").LikeResponse> {
  return request("POST", `/posts/${postId}/like`, undefined, token);
}

// ── Global feed (explore) ─────────────────────────────────────────────────────

export async function getGlobalFeed(
  params: { page?: number; limit?: number; post_type?: string } = {},
  token?: string,
): Promise<import("@/types").FeedResponse> {
  const qs = new URLSearchParams();
  if (params.page)      qs.set("page",      String(params.page));
  if (params.limit)     qs.set("limit",     String(params.limit));
  if (params.post_type) qs.set("post_type", params.post_type);
  return request("GET", `/posts/global?${qs}`, undefined, token);
}

// ── Thread replies ─────────────────────────────────────────────────────────────

export async function getPostReplies(
  postId: string,
  params: { page?: number; limit?: number } = {},
  token?: string,
): Promise<import("@/types").FeedResponse> {
  const qs = new URLSearchParams();
  if (params.page)  qs.set("page",  String(params.page));
  if (params.limit) qs.set("limit", String(params.limit));
  return request("GET", `/posts/${postId}/replies?${qs}`, undefined, token);
}

// ── Notifications ─────────────────────────────────────────────────────────────

export async function getNotifications(
  params: { page?: number; limit?: number; unread_only?: boolean } = {},
  token?: string,
): Promise<import("@/types").NotificationList> {
  const qs = new URLSearchParams();
  if (params.page)        qs.set("page",        String(params.page));
  if (params.limit)       qs.set("limit",        String(params.limit));
  if (params.unread_only) qs.set("unread_only",  "true");
  return request("GET", `/notifications?${qs}`, undefined, token);
}

export async function markAllNotifsRead(token: string): Promise<void> {
  return request("POST", "/notifications/read", undefined, token);
}

export async function markNotifRead(notifId: string, token: string): Promise<void> {
  return request("PATCH", `/notifications/${notifId}`, undefined, token);
}
